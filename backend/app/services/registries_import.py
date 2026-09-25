"""Controlled facility-registry imports (GEM / CEA / WRI GPPD) with run bookkeeping."""
import time
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.integrations.http import ProviderError
from app.integrations.registries import CEAClient, GlobalEnergyMonitorClient, RegistryImport, WRIGPPDClient
from app.models.ops import DataSource
from app.services import facilities, source_health
from app.services.ingestion import _record_errors, finish_run, start_run


def _resolve_path(path: str | None) -> Path:
    if not path:
        raise AppError("A dataset file path is required for this source", code="dataset_file_required")
    p = Path(path)
    if not p.is_absolute():
        p = Path(settings.datasets_dir) / p
    p = p.resolve()
    if Path(settings.datasets_dir).resolve() not in p.parents:  # never read arbitrary server paths
        raise AppError("Dataset files must live under DATASETS_DIR", code="dataset_path_forbidden")
    if not p.exists():
        raise AppError(f"Dataset file not found: {p.name}", code="dataset_file_missing")
    return p


def run_import(db: Session, source: str, path: str | None = None, dataset_version: str | None = None,
               published_at: date | None = None, job_id=None) -> dict:
    started = time.perf_counter()
    run = start_run(db, source, "file", dataset_version, {"path": path}, job_id)
    try:
        if source == "wri_gppd":
            imp: RegistryImport = WRIGPPDClient().fetch(settings.region_country_iso3)
        elif source == "gem":
            imp = GlobalEnergyMonitorClient().import_file(_resolve_path(path), dataset_version or "unversioned", published_at)
        elif source == "cea":
            if not (dataset_version and published_at):
                raise AppError("CEA imports require the publication id and publication date", code="cea_metadata_required")
            imp = CEAClient().import_file(_resolve_path(path), dataset_version, published_at)
        else:
            raise AppError(f"Unknown registry source {source}")
    except (ProviderError, AppError, ValueError) as exc:
        finish_run(run, "failed", started, str(exc))
        source_health.record_failure(db, source, str(exc))
        db.commit()
        raise

    created = 0
    for f in imp.facilities:
        _, is_new = facilities.upsert(db, facilities.SourceRecord(
            source_id=f.source_id, external_id=f.external_id, name=f.name, facility_type=f.facility_type,
            source_type=f.source_type, latitude=f.latitude, longitude=f.longitude, operator=f.operator, status=f.status,
            capacity_value=f.capacity_value, capacity_unit=f.capacity_unit, country=f.country, state=f.state,
            district=f.district, source_url=f.source_url, dataset_version=imp.dataset_version,
            published_at=imp.published_at, raw=f.raw))
        created += int(is_new)
    _record_errors(db, run, "validate", imp.rejected)
    run.records_fetched = len(imp.facilities) + len(imp.rejected)
    run.records_inserted, run.records_duplicate, run.records_rejected = created, len(imp.facilities) - created, len(imp.rejected)
    run.dataset = imp.dataset_version
    finish_run(run, "partial" if imp.rejected else "success", started)
    src = db.get(DataSource, source)
    if src:
        src.dataset_version = imp.dataset_version
        src.dataset_published_at = (datetime.combine(imp.published_at, datetime.min.time(), tzinfo=UTC)
                                    if imp.published_at else None)
    source_health.record_success(db, source, None, created)
    db.commit()
    return {"source": source, "dataset_version": imp.dataset_version, "facilities": len(imp.facilities), "new": created,
            "rejected": len(imp.rejected), "origin": imp.origin}
