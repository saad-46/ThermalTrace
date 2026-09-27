import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import created_at, uuid_pk


class DataSource(Base):
    """Registry + health of every external provider (the Data Sources page reads this)."""

    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # firms | osm | gem | cea | wri_gppd | ...
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # detections | facilities | imagery | weather | geocoding
    homepage: Mapped[str] = mapped_column(Text, nullable=False)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    access: Mapped[str] = mapped_column(String(24), nullable=False)  # api | api_key | oauth | file_import
    cadence: Mapped[str] = mapped_column(Text, nullable=False)  # human description of update frequency
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")  # healthy | degraded | down | not_configured | unknown
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_record_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    requests_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    requests_failed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latency_ms_ewma: Mapped[float | None] = mapped_column(Float)
    dataset_version: Mapped[str | None] = mapped_column(String(120))
    dataset_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Per-capability health recorded by real checks, e.g. {"auth": {...}, "preview": {...}} for Copernicus.
    health_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_ingestion_runs_source_started", "source_id", "started_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dataset: Mapped[str | None] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # live | historical | demo | file
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="running")  # running | success | partial | failed
    started_at: Mapped[datetime] = created_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    records_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text)


class IngestionError(Base):
    __tablename__ = "ingestion_errors"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = created_at()
    stage: Mapped[str] = mapped_column(String(24), nullable=False)  # fetch | parse | validate | persist
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB)


class IngestionCheckpoint(Base):
    __tablename__ = "ingestion_checkpoints"
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("data_sources.id"), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_acq_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = created_at()


class Job(Base):
    """Durable background job. Claimed with FOR UPDATE SKIP LOCKED by workers."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "status", "run_after", "priority"),
        Index(
            "uq_jobs_dedupe_active",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('queued','running') AND dedupe_key IS NOT NULL"),
        ),
        # per-event job status on the event page (enrichment, imagery analysis)
        Index("ix_jobs_event", text("(payload->>'event_id')"), postgresql_where=text("payload ? 'event_id'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")  # queued | running | succeeded | failed
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)  # lower runs first
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    run_after: Mapped[datetime] = created_at()
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = created_at()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))


class SystemHealth(Base):
    __tablename__ = "system_health"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    checked_at: Mapped[datetime] = created_at()
    component: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict | None] = mapped_column(JSONB)


class ApiCache(Base):
    __tablename__ = "api_cache"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class FacilitySyncTile(Base):
    """Local facility index maintenance: one row per 1-degree tile synced from OSM Overpass.
    Event enrichment reads facilities from the local index instead of querying Overpass per event."""

    __tablename__ = "facility_sync_tiles"
    tile_key: Mapped[str] = mapped_column(String(24), primary_key=True)  # "lat:lon" of the SW corner
    west: Mapped[float] = mapped_column(Float, nullable=False)
    south: Mapped[float] = mapped_column(Float, nullable=False)
    east: Mapped[float] = mapped_column(Float, nullable=False)
    north: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")  # pending | ok | failed
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    features_found: Mapped[int | None] = mapped_column(Integer)
    facilities_new: Mapped[int | None] = mapped_column(Integer)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    last_seen_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    jobs_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_scheduler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
