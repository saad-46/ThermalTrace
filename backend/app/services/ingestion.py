"""FIRMS ingestion: fetch → normalize → idempotent upsert → run/error/checkpoint bookkeeping."""
import csv
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import REPO_DIR, settings
from app.core.errors import AppError
from app.integrations.firms import AREA_SOURCES, DATASETS, FetchResult, FIRMSClient, date_chunks, parse_row
from app.integrations.http import ProviderError
from app.models.ops import IngestionCheckpoint, IngestionError, IngestionRun
from app.models.thermal import ThermalDetection
from app.services import source_health

logger = logging.getLogger(__name__)
MAX_ERROR_ROWS = 200
_BATCH = 1000


def start_run(db: Session, source_id: str, mode: str, dataset: str | None, params: dict, job_id=None) -> IngestionRun:
    run = IngestionRun(source_id=source_id, mode=mode, dataset=dataset, params=params, status="running", job_id=job_id)
    db.add(run)
    db.flush()
    return run


def finish_run(run: IngestionRun, status: str, started: float, error: str | None = None) -> None:
    run.status = status
    run.completed_at = datetime.now(UTC)
    run.duration_ms = int((time.perf_counter() - started) * 1000)
    run.error_detail = error


def _record_errors(db: Session, run: IngestionRun, stage: str, rejected: list[tuple[dict, str]]) -> None:
    for row, reason in rejected[:MAX_ERROR_ROWS]:
        db.add(IngestionError(run_id=run.id, stage=stage, message=reason, payload={k: str(v) for k, v in row.items()}))


def persist_detections(db: Session, result: FetchResult, run: IngestionRun, data_mode: str) -> tuple[int, int]:
    """Insert detections; the natural key makes re-ingestion a no-op. Returns (inserted, duplicates)."""
    inserted = 0
    for i in range(0, len(result.detections), _BATCH):
        chunk = result.detections[i : i + _BATCH]
        values = [
            {
                "id": uuid.uuid4(),
                "geom": f"SRID=4326;POINT({d.longitude} {d.latitude})",
                "latitude": d.latitude,
                "longitude": d.longitude,
                "acq_datetime": d.acq_datetime,
                "acq_date": d.acq_date,
                "acq_time": d.acq_time,
                "sensor": d.sensor,
                "satellite": d.satellite,
                "dataset": d.dataset,
                "confidence_raw": d.confidence_raw,
                "confidence_pct": d.confidence_pct,
                "frp": d.frp,
                "brightness": d.brightness,
                "brightness_2": d.brightness_2,
                "scan": d.scan,
                "track": d.track,
                "daynight": d.daynight,
                "version": d.version,
                "data_mode": data_mode,
                "source_ref": result.source_ref,
                "raw": d.raw,
                "retrieved_at": result.retrieved_at,
                "ingestion_run_id": run.id,
            }
            for d in chunk
        ]
        stmt = insert(ThermalDetection).values(values).on_conflict_do_nothing(constraint="uq_detection_natural_key")
        inserted += len(db.execute(stmt.returning(ThermalDetection.id)).all())
    return inserted, len(result.detections) - inserted


def _advance_checkpoint(db: Session, source_id: str, dataset: str, result: FetchResult, run: IngestionRun) -> None:
    if not result.detections:
        return
    latest = max(d.acq_datetime for d in result.detections)
    cp = db.get(IngestionCheckpoint, (source_id, dataset))
    if cp is None:
        db.add(IngestionCheckpoint(source_id=source_id, dataset=dataset, last_acq_datetime=latest, last_run_id=run.id))
    elif cp.last_acq_datetime is None or latest > cp.last_acq_datetime:
        cp.last_acq_datetime = latest
        cp.last_run_id = run.id
        cp.updated_at = datetime.now(UTC)


def ingest_firms_nrt(db: Session, datasets: list[str] | None = None, window: str = "24h", job_id=None) -> dict:
    """Poll the keyless NRT files for each sensor. Each dataset is its own run (partial failure is visible)."""
    client = FIRMSClient()
    summary: dict[str, dict] = {}
    for ds in datasets or list(DATASETS):
        started = time.perf_counter()
        run = start_run(db, "firms", "live", ds, {"window": window, "region": settings.firms_region_name,
                                                   "bbox": list(settings.region_bbox)}, job_id)
        try:
            result = client.get_recent_detections(ds, window=window)
        except ProviderError as exc:
            finish_run(run, "failed", started, str(exc))
            source_health.record_failure(db, "firms", str(exc))
            db.commit()
            summary[ds] = {"status": "failed", "error": str(exc)}
            continue
        inserted, dupes = persist_detections(db, result, run, "live")
        _record_errors(db, run, "parse", result.rejected)
        run.records_fetched = len(result.detections) + len(result.rejected)
        run.records_inserted, run.records_duplicate, run.records_rejected = inserted, dupes, len(result.rejected)
        finish_run(run, "partial" if result.rejected else "success", started)
        _advance_checkpoint(db, "firms", ds, result, run)
        latest = max((d.acq_datetime for d in result.detections), default=None)
        source_health.record_success(db, "firms", result.latency_ms, inserted, latest)
        db.commit()
        summary[ds] = {"status": run.status, "fetched": run.records_fetched, "inserted": inserted, "duplicates": dupes,
                       "rejected": len(result.rejected)}
        logger.info("firms %s: %s", ds, summary[ds])
    return summary


MAX_BACKFILL_DAYS = 400


def ingest_firms_historical(db: Session, source: str, start: str, days: int, bbox: tuple | None = None, job_id=None,
                            client: FIRMSClient | None = None) -> dict:
    """Keyed Area API backfill over any number of days, fetched in API-sized windows (<= 5 days each).

    Each window is its own ingestion run and is committed before the next, so an interruption keeps
    everything already loaded; re-running is safe because detections are deduplicated by natural key.
    A provider failure stops the backfill, records the failed window, and re-raises.
    """
    if source not in AREA_SOURCES:
        raise AppError(f"Unknown FIRMS source {source!r}; use one of {', '.join(AREA_SOURCES)}", code="invalid_source")
    if not 1 <= days <= MAX_BACKFILL_DAYS:
        raise AppError(f"days must be between 1 and {MAX_BACKFILL_DAYS}", code="invalid_days")
    client = client or FIRMSClient()
    bbox = bbox or settings.region_bbox
    windows = date_chunks(datetime.fromisoformat(start).date(), days)
    totals = {"windows": len(windows), "windows_done": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
    for win_start, n in windows:
        started = time.perf_counter()
        run = start_run(db, "firms", "historical", source,
                        {"start": win_start.isoformat(), "days": n, "bbox": list(bbox)}, job_id)
        try:
            result = client.get_historical_detections(source, bbox, win_start, n)
        except ProviderError as exc:
            finish_run(run, "failed", started, str(exc))
            source_health.record_failure(db, "firms", str(exc))
            db.commit()
            logger.error("firms backfill %s stopped at %s: %s (%s)", source, win_start, exc, totals)
            raise
        age = datetime.now(UTC) - max((d.acq_datetime for d in result.detections), default=datetime.now(UTC))
        mode = "historical" if age > timedelta(days=7) or source.endswith("_SP") else "live"
        inserted, dupes = persist_detections(db, result, run, mode)
        _record_errors(db, run, "parse", result.rejected)
        run.records_fetched = len(result.detections) + len(result.rejected)
        run.records_inserted, run.records_duplicate, run.records_rejected = inserted, dupes, len(result.rejected)
        finish_run(run, "partial" if result.rejected else "success", started)
        source_health.record_success(db, "firms", result.latency_ms, inserted)
        db.commit()
        totals["windows_done"] += 1
        totals["inserted"] += inserted
        totals["duplicates"] += dupes
        totals["rejected"] += len(result.rejected)
        logger.info("firms backfill %s %s +%dd: %d new", source, win_start, n, inserted)
    return {"status": "success", "source": source, "start": start, "days": days, **totals}


def load_demo_dataset(db: Session, job_id=None) -> dict:
    """Synthetic data. Refuses unless DEMO_MODE=true; every row is tagged data_mode='demo'."""
    if not settings.demo_mode:
        raise AppError("Demo data can only be loaded when DEMO_MODE=true", code="demo_mode_disabled")
    path = REPO_DIR / "data" / "demo" / "firms_demo_india.csv"
    started = time.perf_counter()
    run = start_run(db, "demo", "demo", "firms_demo_india", {"file": path.name}, job_id)
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    good, bad = [], []
    for row in rows:
        dataset = "MODIS_NRT" if row.get("instrument") == "MODIS" else "VIIRS_NOAA20_NRT"
        try:
            good.append(parse_row(row, dataset))
        except ValueError as exc:
            bad.append((row, str(exc)))
    result = FetchResult(good, bad, f"file:data/demo/{path.name}", 0.0, datetime.now(UTC))
    inserted, dupes = persist_detections(db, result, run, "demo")
    run.records_fetched, run.records_inserted, run.records_duplicate, run.records_rejected = len(rows), inserted, dupes, len(bad)
    finish_run(run, "success", started)
    db.commit()
    return {"inserted": inserted, "duplicates": dupes}
