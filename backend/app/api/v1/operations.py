"""Analytics, data sources, ingestion, jobs, admin and system status."""
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.api.v1.intelligence import error_category_text
from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, Page, SupervisorUser, pagination
from app.core.errors import AppError, NotFound
from app.db import like as like_pattern
from app.db.session import get_db
from app.models.auth import User
from app.models.ml import ModelVersion
from app.models.ops import DataSource, IngestionError, IngestionRun, Job
from app.processing.features import FEATURES
from app.schemas.api import IngestionTriggerIn, JobOut
from app.schemas.api import Page as PageOut
from app.services import audit, source_health
from app.services.source_health import configuration_state
from app.workers.queue import enqueue

router = APIRouter()


def _window(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# --- system status (freshness indicator) ---------------------------------------------------------------
@router.get("/status", tags=["system"], summary="Data freshness + mode indicator shown in every screen header")
def status(user: User = CurrentUser, db: Session = Depends(get_db)):
    r = db.execute(text("""
        SELECT (SELECT max(completed_at) FROM ingestion_runs WHERE source_id='firms' AND status IN ('success','partial')) AS firms_sync,
               (SELECT max(acq_datetime) FROM thermal_detections WHERE data_mode <> 'demo') AS latest_detection,
               (SELECT max(completed_at) FROM ingestion_runs WHERE source_id IN ('gem','cea','wri_gppd') AND status IN ('success','partial')) AS registry_sync,
               (SELECT max(last_success_at) FROM data_sources WHERE id='osm') AS osm_sync,
               (SELECT max(retrieved_at) FROM satellite_observations) AS satellite_update,
               (SELECT max(acquired_at) FROM satellite_observations) AS latest_scene,
               (SELECT count(*) FROM thermal_detections WHERE data_mode='demo') AS demo_detections,
               (SELECT count(*) FROM thermal_events WHERE status='active' AND in_india IS NOT FALSE) AS active_events,
               (SELECT max(last_seen_at) FROM worker_heartbeats) AS worker_seen
    """)).mappings().one()
    worker_ok = r["worker_seen"] is not None and r["worker_seen"] > datetime.now(UTC) - timedelta(minutes=3)
    return {**dict(r), "demo_mode": settings.demo_mode, "environment": settings.environment, "worker_online": worker_ok,
            "server_time": datetime.now(UTC)}


# --- analytics ---------------------------------------------------------------------------------------
@router.get("/analytics/summary", tags=["analytics"])
def summary(days: int = Query(30, ge=1, le=3650), user: User = CurrentUser, db: Session = Depends(get_db)):
    p = {"since": _window(days)}
    totals = db.execute(text("""
        SELECT count(*) events, count(*) FILTER (WHERE status='active') active,
               count(*) FILTER (WHERE persistence_class='persistent') persistent,
               count(*) FILTER (WHERE confidence_state='INSUFFICIENT_EVIDENCE' AND review_status='unreviewed') needs_review,
               count(*) FILTER (WHERE review_status IN ('analyst_confirmed')) confirmed,
               count(*) FILTER (WHERE review_status IN ('analyst_rejected','false_positive')) rejected,
               COALESCE(sum(observation_count),0) detections
        FROM thermal_events WHERE last_detected >= :since AND in_india IS NOT FALSE"""), p).mappings().one()
    by_class = db.execute(text("""SELECT COALESCE(classification,'unclassified') k, count(*) n FROM thermal_events
                                  WHERE last_detected >= :since AND in_india IS NOT FALSE GROUP BY 1 ORDER BY 2 DESC"""), p).mappings().all()
    by_state = db.execute(text("""SELECT COALESCE(confidence_state,'UNPROCESSED') k, count(*) n FROM thermal_events
                                  WHERE last_detected >= :since AND in_india IS NOT FALSE GROUP BY 1 ORDER BY 2 DESC"""), p).mappings().all()
    return {"window_days": days, "totals": dict(totals), "by_classification": [dict(r) for r in by_class],
            "by_confidence_state": [dict(r) for r in by_state]}


@router.get("/analytics/trends", tags=["analytics"], summary="Daily detections/events by class (operational trend)")
def trends(days: int = Query(30, ge=1, le=3650), bucket: str = Query("day", pattern="^(day|week|month)$"),
           user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(text(f"""
        SELECT date_trunc('{bucket}', d.acq_datetime) AS bucket, COALESCE(e.classification, 'unclassified') AS classification,
               count(*) AS detections, count(DISTINCT d.event_id) AS events, round(sum(d.frp)::numeric, 1) AS frp_sum
        FROM thermal_detections d LEFT JOIN thermal_events e ON e.id = d.event_id
        WHERE d.acq_datetime >= :since AND e.in_india IS NOT FALSE GROUP BY 1, 2 ORDER BY 1"""), {"since": _window(days)}).mappings().all()
    return {"bucket": bucket, "rows": [dict(r) for r in rows]}


@router.get("/analytics/diurnal", tags=["analytics"], summary="Day/night + hour-of-day pattern by sensor")
def diurnal(days: int = Query(30, ge=1, le=3650), user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(text("""SELECT satellite, daynight, extract(hour FROM acq_datetime)::int AS hour, count(*) n
                              FROM thermal_detections WHERE acq_datetime >= :since GROUP BY 1,2,3 ORDER BY 1,3"""),
                      {"since": _window(days)}).mappings().all()
    return [dict(r) for r in rows]


@router.get("/analytics/persistent-sources", tags=["analytics"],
            summary="Locations repeatedly producing thermal anomalies — ranked by evidence, not a threat ranking")
def persistent_sources(limit: int = Query(25, ge=1, le=200), user: User = CurrentUser, db: Session = Depends(get_db)):
    from app.repositories.events import _LIST_COLS, _with_display

    rows = db.execute(text(f"""
        SELECT {_LIST_COLS}, (e.persistence_metrics->>'recurrence_count')::int AS recurrence_count,
               (e.persistence_metrics->>'active_days')::int AS active_days_m
        FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id
        WHERE e.persistence_class IN ('persistent','recurring') AND e.in_india IS NOT FALSE
        ORDER BY (e.persistence_class = 'persistent') DESC, e.persistence_score DESC, e.sensor_count DESC, e.observation_count DESC
        LIMIT :limit"""), {"limit": limit}).mappings().all()
    return [_with_display(dict(r)) for r in rows]


@router.get("/analytics/hotspots", tags=["analytics"], summary="Districts and facility types with most thermal activity")
def hotspots(days: int = Query(30, ge=1, le=3650), user: User = CurrentUser, db: Session = Depends(get_db)):
    p = {"since": _window(days)}
    districts = db.execute(text("""
        SELECT admin_state, admin_district, count(*) events, sum(observation_count) detections,
               count(*) FILTER (WHERE persistence_class='persistent') persistent,
               count(*) FILTER (WHERE classification IN ('flare','process_heat','coal_seam_fire','industrial_fire')) industrial
        FROM thermal_events WHERE last_detected >= :since AND admin_district IS NOT NULL AND in_india IS NOT FALSE
        GROUP BY 1,2 ORDER BY events DESC LIMIT 25"""), p).mappings().all()
    ftypes = db.execute(text("""
        SELECT f.facility_type, count(DISTINCT e.id) events, count(DISTINCT f.id) facilities
        FROM thermal_events e JOIN event_facility_links l ON l.event_id = e.id AND l.rank = 1 AND l.distance_m <= 2000
        JOIN facilities f ON f.id = l.facility_id WHERE e.last_detected >= :since AND e.in_india IS NOT FALSE GROUP BY 1 ORDER BY 2 DESC"""), p).mappings().all()
    return {"districts": [dict(r) for r in districts], "facility_types": [dict(r) for r in ftypes],
            "note": "Districts are only known for geocoded (enriched) events."}


@router.get("/analytics/sensors", tags=["analytics"])
def sensors(days: int = Query(30, ge=1, le=3650), user: User = CurrentUser, db: Session = Depends(get_db)):
    p = {"since": _window(days)}
    per = db.execute(text("""SELECT dataset, satellite, count(*) n, round(avg(frp)::numeric,1) frp_mean,
                               round(avg(confidence_pct)::numeric,1) conf_mean
                             FROM thermal_detections WHERE acq_datetime >= :since GROUP BY 1,2 ORDER BY 3 DESC"""), p).mappings().all()
    agreement = db.execute(text("""SELECT sensor_count, count(*) n FROM thermal_events WHERE last_detected >= :since AND in_india IS NOT FALSE
                                   GROUP BY 1 ORDER BY 1"""), p).mappings().all()
    return {"per_sensor": [dict(r) for r in per], "multi_sensor_agreement": [dict(r) for r in agreement]}


@router.get("/analytics/feedback", tags=["analytics"], summary="Training feedback dataset + false-positive intelligence")
def feedback(user: User = CurrentUser, db: Session = Depends(get_db)):
    decisions = db.execute(text("SELECT decision, count(*) n FROM analyst_reviews GROUP BY 1 ORDER BY 2 DESC")).mappings().all()
    fp = db.execute(text("""SELECT false_positive_reason, system_source_class, count(*) n FROM analyst_reviews
                            WHERE decision = 'false_positive' GROUP BY 1,2 ORDER BY 3 DESC""")).mappings().all()
    agreement = db.execute(text("""
        SELECT system_source_class, count(*) FILTER (WHERE decision='confirm') confirmed,
               count(*) FILTER (WHERE decision='reclassify') reclassified,
               count(*) FILTER (WHERE decision IN ('reject','false_positive')) rejected
        FROM analyst_reviews WHERE system_source_class IS NOT NULL GROUP BY 1 ORDER BY 1""")).mappings().all()
    labelled = db.execute(text("""SELECT count(DISTINCT event_id) FROM analyst_reviews
                                  WHERE decision IN ('confirm','reclassify') AND source_class IS NOT NULL""")).scalar_one()
    return {"decisions": [dict(r) for r in decisions], "false_positives": [dict(r) for r in fp],
            "system_vs_analyst": [dict(r) for r in agreement], "adjudicated_labels": labelled}


# --- data sources / ingestion / jobs --------------------------------------------------------------------
@router.get("/sources", tags=["sources"], summary="Source registry with health, freshness and configuration state")
def sources(user: User = CurrentUser, db: Session = Depends(get_db)):
    cfg = configuration_state()
    srcs = db.execute(select(DataSource).order_by(DataSource.kind, DataSource.id)).scalars().all()
    runs = {r.source_id: r for r in db.execute(text("""
        SELECT DISTINCT ON (source_id) source_id, status, started_at, completed_at, records_inserted, error_detail
        FROM ingestion_runs ORDER BY source_id, started_at DESC""")).mappings().all()}
    # Station registries (CEA): listed, located, for review, not located; with the coordinate sources used.
    registries = {row.source_id: dict(row._mapping) for row in db.execute(text("""
        SELECT source_id, count(*) AS stations, count(facility_id) AS located,
               count(*) FILTER (WHERE match_status = 'ambiguous') AS ambiguous,
               count(*) FILTER (WHERE match_status = 'unmatched') AS unmatched,
               count(DISTINCT facility_id) AS facilities, max(imported_at) AS imported_at,
               array_remove(array_agg(DISTINCT coordinate_source), NULL) AS coordinate_sources
        FROM registry_stations GROUP BY source_id""")).all()}
    out = []
    for s in srcs:
        err_rate = (s.requests_failed / s.requests_total) if s.requests_total else None
        state = cfg.get(s.id, {})
        status_ = s.status
        if s.id == "demo":
            status_ = "enabled" if settings.demo_mode else "disabled"
        elif state.get("configured") is False and s.status in ("unknown",):
            status_ = "not_configured"
        eff = source_health.effective_state(s.id, s.status, s.access, s.last_success_at is not None, cfg, s.health_detail)
        req = source_health.REQUIREMENTS.get(s.id, {})
        row = {c.key: getattr(s, c.key) for c in DataSource.__table__.columns}
        # the failure category is for everyone; the raw provider message (may hold URLs) only for administrators
        row["last_error_category"] = error_category_text(s.last_error)
        run = dict(runs[s.id]) if s.id in runs else None
        if user.role != "admin" or user.is_demo:
            row["last_error"] = None
            if run:
                run["error_detail"] = None
        out.append({**row, "status": status_,
                    "error_rate": round(err_rate, 3) if err_rate is not None else None,
                    "configuration": state, "last_run": run,
                    "state": eff["state"], "state_reason": eff["reason"], "requirement": eff["requirement"],
                    "requirement_env": req.get("env"), "requirement_how": req.get("how"),
                    "registry": registries.get(s.id)})
    return out


@router.get("/sources/facility-index", tags=["sources"], summary="Local OSM facility index coverage (1° tiles)")
def facility_index(user: User = CurrentUser, db: Session = Depends(get_db)):
    from app.services.facility_sync import FRESH_DAYS, coverage

    tiles = db.execute(text("""SELECT tile_key, status, event_count, features_found, facilities_new, last_synced_at, error
                               FROM facility_sync_tiles ORDER BY event_count DESC LIMIT 50""")).mappings().all()
    return {"coverage": coverage(db), "fresh_days": FRESH_DAYS, "tiles": [dict(t) for t in tiles]}


@router.get("/ingestion/runs", tags=["sources"])
def ingestion_runs(source: str | None = None, page: Page = Depends(pagination), user: User = CurrentUser, db: Session = Depends(get_db)):
    q = select(IngestionRun)
    if source:
        q = q.where(IngestionRun.source_id == source)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(IngestionRun.started_at.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": [{c.key: getattr(r, c.key) for c in IngestionRun.__table__.columns} for r in rows],
            "total": total, "limit": page.limit, "offset": page.offset}


@router.get("/ingestion/runs/{run_id}/errors", tags=["sources"])
def ingestion_errors(run_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(select(IngestionError).where(IngestionError.run_id == run_id).order_by(IngestionError.id).limit(200)).scalars()
    return [{c.key: getattr(r, c.key) for c in IngestionError.__table__.columns} for r in rows]


@router.post("/ingestion/trigger", response_model=JobOut, status_code=202, tags=["sources"],
             summary="Queue an ingestion/processing job (supervisor+; model training admin only)")
def trigger(body: IngestionTriggerIn, request: Request, user: User = SupervisorUser, db: Session = Depends(get_db)):
    if body.kind == "train_model" and user.role != "admin":
        raise AppError("Only admins can train models", code="forbidden")
    if body.kind == "load_demo" and not settings.demo_mode:
        raise AppError("Demo data can only be loaded when DEMO_MODE=true", code="demo_mode_disabled")
    if body.kind == "firms_historical":
        if not settings.firms_key:
            raise AppError("Historical FIRMS ingestion needs FIRMS_MAP_KEY", code="provider_not_configured")
        if not {"source", "start"} <= body.payload.keys():
            raise AppError("payload requires source and start (YYYY-MM-DD)", code="invalid_payload")
        from app.integrations.firms import AREA_SOURCES
        from app.services.ingestion import MAX_BACKFILL_DAYS

        if body.payload["source"] not in AREA_SOURCES:
            raise AppError(f"source must be one of {', '.join(AREA_SOURCES)}", code="invalid_source")
        days = body.payload.get("days", 1)
        if not isinstance(days, int) or not 1 <= days <= MAX_BACKFILL_DAYS:
            raise AppError(f"days must be an integer between 1 and {MAX_BACKFILL_DAYS}", code="invalid_days")
    job_id = enqueue(db, body.kind, body.payload, dedupe_key=f"manual:{body.kind}:{sorted(body.payload.items())}",
                     priority=15, created_by=user.id)
    audit.record(db, request, user.id, "job.trigger", "job", job_id, {"kind": body.kind, "payload": body.payload})
    db.commit()
    return db.get(Job, job_id)


@router.get("/jobs", response_model=PageOut[JobOut], tags=["sources"])
def jobs(status: str | None = None, kind: str | None = None, page: Page = Depends(pagination), user: User = CurrentUser,
         db: Session = Depends(get_db)):
    q = select(Job)
    if status:
        q = q.where(Job.status == status)
    if kind:
        q = q.where(Job.kind == kind)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    items = db.execute(q.order_by(Job.created_at.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": [_job_view(j, user) for j in items], "total": total, "limit": page.limit, "offset": page.offset}


def _job_view(j: Job, user: User) -> dict:
    out = JobOut.model_validate(j).model_dump()
    if user.is_demo:
        out["error"] = "hidden in demo mode" if out.get("error") else None
    elif user.role != "admin" and out.get("error"):
        lines = [ln for ln in out["error"].strip().splitlines() if ln.strip()]
        out["error"] = lines[-1][:300] if lines else None
    return out


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["sources"])
def job(job_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if j is None:
        raise NotFound("Job not found")
    return _job_view(j, user)


# --- models ----------------------------------------------------------------------------------------------
@router.get("/models", tags=["models"], summary="Model versions with model cards")
def models(user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(select(ModelVersion).order_by(ModelVersion.created_at.desc())).scalars().all()
    usage = dict(db.execute(text("SELECT primary_model_id, count(*) FROM classifications WHERE is_current GROUP BY 1")).all())
    return {"models": [{**{c.key: getattr(m, c.key) for c in ModelVersion.__table__.columns if c.key != "artifact_path"},
                        "current_classifications": usage.get(m.id, 0)} for m in rows],
            "features": [f.__dict__ for f in FEATURES]}


@router.post("/models/{model_id}/activate", tags=["models"])
def activate(model_id: str, request: Request, admin: User = AdminUser, db: Session = Depends(get_db)):
    mv = db.get(ModelVersion, model_id)
    if mv is None or mv.kind != "lightgbm":
        raise NotFound("Trainable model version not found")
    previous = db.execute(select(ModelVersion.id).where(ModelVersion.kind == "lightgbm", ModelVersion.is_active.is_(True))).scalar()
    db.execute(update(ModelVersion).where(ModelVersion.kind == "lightgbm").values(is_active=False))
    mv.is_active = True
    audit.record(db, request, admin.id, "model.activate", "model_version", model_id,
                 {"previous_active": previous, "new_active": model_id})
    db.commit()
    enqueue(db, "process_events", {"reanalyse_all": True}, dedupe_key="process_events:reanalyse", priority=40)
    return {"active": model_id}


@router.post("/models/{model_id}/deactivate", tags=["models"],
             summary="Deactivate a trained model; the rule cascade becomes the classifier of record again")
def deactivate(model_id: str, request: Request, admin: User = AdminUser, db: Session = Depends(get_db)):
    mv = db.get(ModelVersion, model_id)
    if mv is None or mv.kind != "lightgbm":
        raise NotFound("Trainable model version not found")
    was_active = mv.is_active
    mv.is_active = False
    audit.record(db, request, admin.id, "model.deactivate", "model_version", model_id,
                 {"was_active": was_active, "classifier_of_record": "rule cascade"})
    db.commit()
    enqueue(db, "process_events", {"reanalyse_all": True}, dedupe_key="process_events:reanalyse", priority=40)
    return {"active": None}


# --- ML training feedback dataset ---------------------------------------------------------------------
_TRAINING_SQL = text(
    """
    SELECT e.public_id, e.id AS event_id, r.id AS review_id, r.created_at AS reviewed_at, u.email AS reviewer,
           r.decision, r.source_class AS analyst_label, r.persistence_class AS analyst_persistence,
           r.false_positive_reason, r.system_source_class AS system_label, r.system_confidence_score AS system_confidence,
           c.primary_model_id AS model_version, c.pipeline_version, e.latitude, e.longitude, e.first_detected,
           (SELECT mp.features_used FROM model_predictions mp WHERE mp.event_id = e.id AND mp.created_at <= r.created_at
             ORDER BY mp.created_at DESC LIMIT 1) AS features
    FROM analyst_reviews r
    JOIN thermal_events e ON e.id = r.event_id
    LEFT JOIN users u ON u.id = r.user_id
    LEFT JOIN classifications c ON c.id = r.classification_id
    WHERE r.decision <> 'note' AND e.data_mode <> 'demo'
    ORDER BY r.created_at
    """
)


@router.get("/ml/training-dataset", tags=["models"],
            summary="Adjudicated training dataset (event → prediction → analyst label → features → reviewer → model version)")
def training_dataset(fmt: str = Query("json", alias="format", pattern="^(json|csv)$"), request: Request = None,
                     user: User = SupervisorUser, db: Session = Depends(get_db)):
    import csv
    import io

    from fastapi.responses import Response

    from app.processing.features import FEATURE_NAMES

    rows = [dict(r) for r in db.execute(_TRAINING_SQL).mappings()]
    if user.is_demo:
        from app.services.explore import mask_pii

        rows = mask_pii(rows)
    audit.record(db, request, user.id, "ml.training_dataset.export", detail={"rows": len(rows), "format": fmt})
    db.commit()
    label_rule = ("confirm/reclassify → analyst_label is a positive label for that class; reject/false_positive → the "
                  "system_label is wrong (false_positive_reason says what it was); escalate → unresolved, exclude from training")
    if fmt == "json":
        return {"rows": rows, "count": len(rows), "feature_names": FEATURE_NAMES, "label_semantics": label_rule}
    buf = io.StringIO()
    cols = [k for k in (rows[0].keys() if rows else _TRAINING_COLS) if k != "features"] + FEATURE_NAMES
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({**{k: v for k, v in r.items() if k != "features"}, **(r.get("features") or {})})
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"content-disposition": 'attachment; filename="thermaltrace_training_dataset.csv"'})


_TRAINING_COLS = ("public_id", "event_id", "review_id", "reviewed_at", "reviewer", "decision", "analyst_label",
                  "analyst_persistence", "false_positive_reason", "system_label", "system_confidence", "model_version",
                  "pipeline_version", "latitude", "longitude", "first_detected")


# --- admin: audit + system health --------------------------------------------------------------------------
@router.get("/admin/audit", tags=["admin"])
def audit_log(action: str | None = None, page: Page = Depends(pagination), admin: User = AdminUser, db: Session = Depends(get_db)):
    where = "WHERE a.action LIKE :action" if action else ""
    rows = db.execute(text(f"""SELECT a.*, u.email FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id {where}
                               ORDER BY a.id DESC LIMIT :limit OFFSET :offset"""),
                      {"action": like_pattern.prefix(action or ""), "limit": page.limit, "offset": page.offset}).mappings().all()
    out = [dict(r) for r in rows]
    if admin.is_demo:
        from app.services.explore import mask_pii

        out = mask_pii(out)
    return out


@router.get("/admin/system", tags=["admin"], summary="Workers, queue depth, DB size, recent failures")
def system(admin: User = AdminUser, db: Session = Depends(get_db)):
    t = time.perf_counter()
    db.execute(text("SELECT 1"))
    db_ms = round((time.perf_counter() - t) * 1000, 1)
    workers = db.execute(text("SELECT * FROM worker_heartbeats ORDER BY last_seen_at DESC")).mappings().all()
    queue = db.execute(text("SELECT status, count(*) n FROM jobs GROUP BY 1")).mappings().all()
    failures = db.execute(text("""SELECT id, kind, finished_at, left(error, 300) error FROM jobs WHERE status='failed'
                                  ORDER BY finished_at DESC LIMIT 20""")).mappings().all()
    sizes = db.execute(text("""SELECT relname AS table, n_live_tup AS rows FROM pg_stat_user_tables
                               ORDER BY n_live_tup DESC LIMIT 15""")).mappings().all()
    return {"database": {"latency_ms": db_ms, "size": db.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar(),
                         "postgis": db.execute(text("SELECT postgis_lib_version()")).scalar(), "tables": [dict(r) for r in sizes]},
            "workers": [dict(w) for w in workers], "queue": [dict(q) for q in queue], "recent_failures": [dict(f) for f in failures],
            "configuration": configuration_state()}
