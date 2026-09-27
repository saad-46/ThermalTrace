"""Worker entrypoint: `python -m app.workers.run [--scheduler] [--once]`.

--scheduler also enqueues recurring jobs (use on exactly one worker; dedupe keys make an
accidental second scheduler harmless).
"""
import argparse
import logging
import os
import signal
import socket
import threading
import time
import traceback
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.logging import configure_logging, job_id_var
from app.db.session import SessionLocal
from app.models.ops import WorkerHeartbeat
from app.workers import queue
from app.workers.tasks import HANDLERS, SCHEDULE

logger = logging.getLogger("thermaltrace.worker")
_stop = False


def _handle_signal(*_):
    global _stop
    _stop = True


def _heartbeat(db, worker_id: str, started: datetime, done: int, scheduler: bool) -> None:
    stmt = insert(WorkerHeartbeat).values(worker_id=worker_id, started_at=started, jobs_done=done, is_scheduler=scheduler,
                                          last_seen_at=datetime.now(UTC))
    db.execute(stmt.on_conflict_do_update(index_elements=[WorkerHeartbeat.worker_id],
                                          set_={"last_seen_at": datetime.now(UTC), "jobs_done": done}))
    db.commit()


class _Beat:
    """Keeps the worker's heartbeat fresh from a thread while a (possibly long) job runs, on its own DB session, so
    recover_stale can tell a live long job from an orphaned one."""

    def __init__(self, worker_id: str, started: datetime, done: int, scheduler: bool):
        self.args = (worker_id, started, done, scheduler)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(queue.HEARTBEAT_S):
            db = SessionLocal()
            try:
                _heartbeat(db, *self.args)
            except Exception:  # a missed beat is harmless; the next one retries
                logger.debug("heartbeat failed", exc_info=True)
            finally:
                db.close()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


def run_one(db, job) -> None:
    token = job_id_var.set(str(job.id))
    started = time.perf_counter()
    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            queue.fail(db, job, f"unknown job kind {job.kind}")
            return
        logger.info("job %s (%s) started, attempt %d", job.id, job.kind, job.attempts)
        result = handler(db, job.payload or {}, job)
        queue.complete(db, job, result)
        logger.info("job %s (%s) succeeded in %.1fs", job.id, job.kind, time.perf_counter() - started)
    except Exception as exc:  # recorded on the job row, retried with backoff
        db.rollback()
        logger.exception("job %s (%s) failed", job.id, job.kind)
        queue.fail(db, job, f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}")
    finally:
        job_id_var.reset(token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduler", action="store_true")
    parser.add_argument("--once", action="store_true", help="drain the queue then exit")
    parser.add_argument("--lane", choices=["all", *queue.LANES], default="all",
                        help="restrict to a job lane (run one 'interactive' and one 'bulk' worker in production)")
    args = parser.parse_args()
    configure_logging(settings.log_level, settings.log_json)
    if settings.sentry_dsn:  # optional: job failures reach the same monitoring as API errors
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.0, send_default_pii=False)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    kinds = None if args.lane == "all" else queue.LANES[args.lane]
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{args.lane}"
    started = datetime.now(UTC)
    last_enqueued: dict[str, float] = {}
    done = 0
    db = SessionLocal()
    queue.recover_stale(db)
    logger.info("worker %s up (scheduler=%s, lane=%s)", worker_id, args.scheduler, args.lane)
    last_beat = 0.0
    last_recover = time.monotonic()
    backoff = 2.0
    while not _stop:
        try:
            now = time.monotonic()
            if args.scheduler:
                for kind, (interval, payload, priority) in SCHEDULE.items():
                    if now - last_enqueued.get(kind, -1e9) >= interval:
                        queue.enqueue(db, kind, payload, dedupe_key=f"sched:{kind}", priority=priority)
                        last_enqueued[kind] = now
            if now - last_beat > queue.HEARTBEAT_S:
                _heartbeat(db, worker_id, started, done, args.scheduler)
                last_beat = now
            if now - last_recover > 60:  # every worker sweeps for jobs orphaned by a stopped worker
                queue.recover_stale(db)
                last_recover = now
            job = queue.claim(db, worker_id, kinds)
            if job is None:
                if args.once:
                    break
                time.sleep(2)
                continue
            _heartbeat(db, worker_id, started, done, args.scheduler)
            with _Beat(worker_id, started, done, args.scheduler):
                run_one(db, job)
            done += 1
            backoff = 2.0
        except DBAPIError as exc:
            # Database restarted or unreachable: keep the worker alive, reconnect with backoff. A job interrupted
            # mid-run is requeued by recover_stale once it is older than its stale threshold.
            logger.warning("database unavailable (%s); retrying in %.0fs", type(exc.orig).__name__ if exc.orig else exc, backoff)
            try:
                db.rollback()
                db.close()
            except DBAPIError:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            db = SessionLocal()
            try:
                queue.recover_stale(db)
            except DBAPIError:
                db.rollback()
    db.close()
    logger.info("worker %s stopped after %d jobs", worker_id, done)


if __name__ == "__main__":
    main()
