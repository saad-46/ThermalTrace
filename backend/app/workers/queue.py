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
    # source_probe is a ~1 s credential check: kept out of the bulk backlog so source health stays current.
    "interactive": ("render_report", "enrich_event", "imagery_analysis", "import_registry", "train_model", "source_probe"),
    "bulk": ("firms_poll", "firms_historical", "load_demo", "enrich_batch", "landcover_backfill", "context_backfill",
             "facility_sync", "housekeeping",
             "process_events"),
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


# A worker writes its heartbeat every HEARTBEAT_S seconds, also while a job runs (run.py). A running job whose worker
# has not been seen for STALE_AFTER_S is orphaned (process killed, host lost); a long job of a live worker never is.
HEARTBEAT_S = 30
STALE_AFTER_S = 180


def recover_stale(db: Session, stale_after_s: int = STALE_AFTER_S) -> int:
    """Requeue jobs whose worker stopped mid-run; a job that has used all its attempts is failed instead (a job that
    crashes its worker every time must not loop forever)."""
    res = db.execute(text(
        """UPDATE jobs j SET
             status = CASE WHEN j.attempts >= j.max_attempts THEN 'failed' ELSE 'queued' END,
             finished_at = CASE WHEN j.attempts >= j.max_attempts THEN now() ELSE j.finished_at END,
             error = left(concat_ws(E'\n', 'worker stopped while running this job (attempt ' || j.attempts || ')', j.error), 4000),
             run_after = now(), locked_by = NULL
           WHERE j.status = 'running' AND j.started_at < now() - make_interval(secs => :s)
             AND NOT EXISTS (SELECT 1 FROM worker_heartbeats h
                             WHERE h.worker_id = j.locked_by AND h.last_seen_at > now() - make_interval(secs => :s))"""),
        {"s": stale_after_s})
    db.commit()
    if res.rowcount:
        logger.warning("recovered %d job(s) orphaned by a stopped worker", res.rowcount)
    return res.rowcount or 0


def purge_finished(db: Session, keep_days: int = 30) -> int:
    """Drop succeeded jobs older than `keep_days` (failed ones are kept for diagnosis); the table would grow forever."""
    res = db.execute(text("DELETE FROM jobs WHERE status = 'succeeded' AND finished_at < now() - make_interval(days => :d)"),
                     {"d": keep_days})
    db.commit()
    return res.rowcount or 0
