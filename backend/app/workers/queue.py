"""Postgres-backed durable job queue (FOR UPDATE SKIP LOCKED). Safe with N workers."""
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ops import Job

logger = logging.getLogger(__name__)


def enqueue(db: Session, kind: str, payload: dict | None = None, *, dedupe_key: str | None = None, priority: int = 100,
            delay_s: float = 0, max_attempts: int = 3, created_by: uuid.UUID | None = None) -> uuid.UUID | None:
    """Enqueue a job. With dedupe_key, a queued/running job with the same key suppresses duplicates
    (returns the existing job id)."""
    values = dict(id=uuid.uuid4(), kind=kind, payload=payload or {}, dedupe_key=dedupe_key, priority=priority,
                  run_after=datetime.now(UTC) + timedelta(seconds=delay_s), max_attempts=max_attempts,
                  created_by=created_by, status="queued", attempts=0)
    stmt = insert(Job).values(**values)
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[Job.dedupe_key], index_where=text("status IN ('queued','running') AND dedupe_key IS NOT NULL"))
    new_id = db.execute(stmt.returning(Job.id)).scalar_one_or_none()
    if new_id is None and dedupe_key:
        new_id = db.execute(select(Job.id).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running")))).scalar()
    db.commit()
    return new_id


# Lanes keep user-facing work (reports, on-demand enrichment) from queueing behind bulk jobs.
LANES: dict[str, tuple[str, ...]] = {
    "interactive": ("render_report", "enrich_event", "process_events", "import_registry", "train_model"),
    "bulk": ("firms_poll", "firms_historical", "load_demo", "enrich_batch", "facility_sync", "housekeeping", "process_events"),
}

_CLAIM = text(
    """
    UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_by = :worker, started_at = now()
    WHERE id = (
      SELECT id FROM jobs WHERE status = 'queued' AND run_after <= now()
        AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[])))
      ORDER BY priority, run_after FOR UPDATE SKIP LOCKED LIMIT 1
    ) RETURNING id
    """
)


def claim(db: Session, worker_id: str, kinds: tuple[str, ...] | None = None) -> Job | None:
    job_id = db.execute(_CLAIM, {"worker": worker_id, "kinds": list(kinds) if kinds else None}).scalar()
    db.commit()
    return db.get(Job, job_id) if job_id else None


def complete(db: Session, job: Job, result: dict | None) -> None:
    job.status, job.result, job.finished_at, job.error = "succeeded", result, datetime.now(UTC), None
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    job.error = error[:4000]
    if job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = datetime.now(UTC) + timedelta(seconds=30 * 2 ** (job.attempts - 1))
    else:
        job.status, job.finished_at = "failed", datetime.now(UTC)
    db.commit()


def recover_stale(db: Session, older_than_minutes: int = 30) -> int:
    """Requeue jobs whose worker died mid-run."""
    res = db.execute(text(
        "UPDATE jobs SET status = 'queued', locked_by = NULL WHERE status = 'running' "
        "AND started_at < now() - make_interval(mins => :m)"), {"m": older_than_minutes})
    db.commit()
    return res.rowcount or 0
