"""Job handlers. Each receives (db, payload, job) and returns a JSON-able result."""
import logging
import uuid
from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ops import Job
from app.services import alerts, enrichment, ingestion, registries_import, reports
from app.workers.queue import enqueue

logger = logging.getLogger(__name__)
Handler = Callable[[Session, dict, Job], dict]


def continuation_key(kind: str) -> str:
    """Dedupe key for a job that queues its own next pass. It must differ from the running job's key:
    a queued/running job with the same key suppresses the insert, so reusing it would drop the continuation."""
    return f"{kind}:continue"


def firms_poll(db: Session, payload: dict, job: Job) -> dict:
    summary = ingestion.ingest_firms_nrt(db, payload.get("datasets"), payload.get("window", "24h"), job_id=job.id)
    if any(s.get("inserted") for s in summary.values()):
        enqueue(db, "process_events", {}, dedupe_key="process_events", priority=20)
    return summary


def firms_historical(db: Session, payload: dict, job: Job) -> dict:
    res = ingestion.ingest_firms_historical(db, payload["source"], payload["start"], int(payload.get("days", 1)), job_id=job.id)
    enqueue(db, "process_events", {}, dedupe_key="process_events", priority=20)
    return res


def load_demo(db: Session, payload: dict, job: Job) -> dict:
    res = ingestion.load_demo_dataset(db, job_id=job.id)
    enqueue(db, "process_events", {}, dedupe_key="process_events", priority=20)
    return res


def process_events(db: Session, payload: dict, job: Job) -> dict:
    from app.processing.pipeline import process_new_detections

    res = process_new_detections(db, reanalyse_all=bool(payload.get("reanalyse_all")))
    alert_res = alerts.evaluate_rules(db, res["event_ids"])
    if res["remaining_unassigned"]:  # large backfills are clustered 50,000 detections per pass
        enqueue(db, "process_events", {}, dedupe_key=continuation_key("process_events"), priority=20)
    enqueue(db, "enrich_batch", {"limit": 40}, dedupe_key="enrich_batch", priority=60)
    return {**{k: v for k, v in res.items() if k != "event_ids"}, "alerts": alert_res}


def enrich_event(db: Session, payload: dict, job: Job) -> dict:
    res = enrichment.enrich_events(db, [payload["event_id"]])
    alerts.evaluate_rules(db, [payload["event_id"]])
    return res


def landcover_backfill(db: Session, payload: dict, job: Job) -> dict:
    """Land cover for events enriched before that step existed; ~3 s per event, so batches stay small."""
    ids = enrichment.landcover_backfill_ids(db, int(payload.get("limit", 25)))
    if not ids:
        return {"events": 0}
    res = enrichment.enrich_events(db, ids, steps=("landcover",))
    if len(ids) == int(payload.get("limit", 25)):
        enqueue(db, "landcover_backfill", payload, dedupe_key=continuation_key("landcover_backfill"), priority=85, delay_s=5)
    return res


def imagery_analysis(db: Session, payload: dict, job: Job) -> dict:
    """Sentinel-2 NDVI/NBR change for one event (on demand: it reads several band windows per scene)."""
    from app.models.thermal import ThermalEvent
    from app.processing.pipeline import analyse_event
    from app.services import imagery

    ev = db.get(ThermalEvent, uuid.UUID(str(payload["event_id"])))
    if ev is None:
        raise ValueError("event not found")
    row = imagery.analyse_event_imagery(db, ev)
    db.flush()
    analyse_event(db, ev.id)
    return {"status": row.status, "finding": row.finding, "reason": row.reason}


def enrich_batch(db: Session, payload: dict, job: Job) -> dict:
    ids = enrichment.enrichment_priority(db, int(payload.get("limit", 40)))
    if not ids:
        return {"events": 0}
    res = enrichment.enrich_events(db, ids)
    alerts.evaluate_rules(db, [str(i) for i in ids])
    if len(ids) == int(payload.get("limit", 40)):  # more remaining — continue gradually
        enqueue(db, "enrich_batch", payload, dedupe_key=continuation_key("enrich_batch"), priority=80, delay_s=5)
    return res


def facility_sync(db: Session, payload: dict, job: Job) -> dict:
    from app.services import facility_sync as fs

    res = fs.sync_tiles(db, int(payload.get("limit", 4)))
    if res["remaining"] and (res["synced"] or res["failed"]):  # keep draining the backlog politely
        enqueue(db, "facility_sync", payload, dedupe_key="facility_sync", priority=45, delay_s=10)
    return res


def import_registry(db: Session, payload: dict, job: Job) -> dict:
    return registries_import.run_import(
        db, payload["source"], path=payload.get("path"), dataset_version=payload.get("dataset_version"),
        published_at=date.fromisoformat(payload["published_at"]) if payload.get("published_at") else None, job_id=job.id)


def render_report(db: Session, payload: dict, job: Job) -> dict:
    return reports.render(db, payload["report_id"])


def train_model(db: Session, payload: dict, job: Job) -> dict:
    from app.ml.registry import train_and_register

    mv = train_and_register(db, activate=bool(payload.get("activate", False)))
    db.commit()
    if mv.is_active:
        enqueue(db, "process_events", {"reanalyse_all": True}, dedupe_key="process_events", priority=40)
    return {"model_version": mv.id, "active": mv.is_active,
            "metrics": {k: mv.metrics.get(k) for k in ("macro_f1_holdout", "n_train", "n_test")}}


def housekeeping(db: Session, payload: dict, job: Job) -> dict:
    from app.services import cache

    purged = cache.purge_expired(db)
    db.commit()
    return {"cache_purged": purged}


HANDLERS: dict[str, Handler] = {
    "firms_poll": firms_poll,
    "firms_historical": firms_historical,
    "load_demo": load_demo,
    "process_events": process_events,
    "enrich_event": enrich_event,
    "enrich_batch": enrich_batch,
    "landcover_backfill": landcover_backfill,
    "imagery_analysis": imagery_analysis,
    "import_registry": import_registry,
    "facility_sync": facility_sync,
    "render_report": render_report,
    "train_model": train_model,
    "housekeeping": housekeeping,
}

# Recurring schedule: kind -> (interval seconds, payload, queue priority; lower runs first).
# Facility sync outranks per-event enrichment: every synced tile makes enrichment of its events cheap.
SCHEDULE: dict[str, tuple[int, dict, int]] = {
    "firms_poll": (settings.firms_poll_minutes * 60, {"window": "24h"}, 30),
    "facility_sync": (60 * 60, {"limit": 4}, 45),
    "enrich_batch": (15 * 60, {"limit": 40}, 60),
    "landcover_backfill": (20 * 60, {"limit": 25}, 70),
    "housekeeping": (6 * 3600, {}, 90),
}
