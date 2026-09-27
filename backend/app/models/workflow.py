import uuid
from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import created_at, updated_at, uuid_pk

REVIEW_DECISIONS = ("confirm", "reject", "false_positive", "escalate", "reclassify", "note")
FALSE_POSITIVE_REASONS = (
    "industrial_process_heat",
    "agricultural_burn",
    "sensor_artifact",
    "construction",
    "known_static_source",
    "sun_glint_or_reflection",
    "other",
)


def _user_fk(nullable: bool = True, ondelete: str = "SET NULL"):
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete=ondelete), nullable=nullable)


class AnalystReview(Base):
    """Every analyst decision. Also the Training Feedback Dataset (adjudicated labels)."""

    __tablename__ = "analyst_reviews"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = _user_fk()
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    source_class: Mapped[str | None] = mapped_column(String(32))  # analyst's label (confirm/reclassify)
    persistence_class: Mapped[str | None] = mapped_column(String(16))
    false_positive_reason: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    system_source_class: Mapped[str | None] = mapped_column(String(32))  # snapshot at review time
    system_confidence_score: Mapped[float | None] = mapped_column(Float)
    # the event's review status before and after this decision (0012): history is never overwritten silently
    previous_status: Mapped[str | None] = mapped_column(String(24))
    new_status: Mapped[str | None] = mapped_column(String(24))
    classification_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classifications.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (UniqueConstraint("event_id", name="uq_investigation_event"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | in_progress | closed
    priority: Mapped[str] = mapped_column(String(12), nullable=False, default="normal")  # low | normal | high
    assigned_to: Mapped[uuid.UUID | None] = _user_fk()
    opened_by: Mapped[uuid.UUID | None] = _user_fk()
    summary: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"
    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = _user_fk()
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="note")  # note | attachment
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = _user_fk(nullable=False, ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    center = mapped_column(Geography("POINT", srid=4326, spatial_index=False))
    radius_m: Mapped[float | None] = mapped_column(Float)
    watchlist_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE")
    )
    source_classes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    persistence_classes: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, default=list)
    facility_types: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    facility_within_m: Mapped[float | None] = mapped_column(Float)
    min_confidence: Mapped[float | None] = mapped_column(Float)
    min_frp: Mapped[float | None] = mapped_column(Float)
    min_duration_hours: Mapped[float | None] = mapped_column(Float)
    channels: Mapped[list[str]] = mapped_column(ARRAY(String(12)), nullable=False, default=lambda: ["in_app"])
    created_at: Mapped[datetime] = created_at()
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # External deliveries (email/push) are suppressed within this window after the last notification;
    # alerts are still created in-app and the suppression is recorded on each delivery row.
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Triage and activity conditions. `min_priority` is the 0-100 triage priority (not a risk score).
    # `min_repeat_events`: the event's nearest facility has at least this many events in `repeat_days`.
    # `activity_increase`: that facility's last-7-day event count is at least 3 and at least double the prior 7 days.
    min_priority: Mapped[int | None] = mapped_column(Integer)
    min_repeat_events: Mapped[int | None] = mapped_column(Integer)
    repeat_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    activity_increase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Advanced conditions (0012). `increase_factor` / `increase_window_days` parameterise `activity_increase`;
    # `repeat_within_m` counts events within that distance of the event's nearest facility instead of sharing it.
    increase_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.0, server_default="2")
    increase_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    repeat_within_m: Mapped[float | None] = mapped_column(Float)
    min_active_days: Mapped[int | None] = mapped_column(Integer)  # persistence: days with detections
    min_evidence_stages: Mapped[int | None] = mapped_column(Integer)  # evidence availability (not confidence)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("rule_id", "event_id", name="uq_alert_rule_event"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = _user_fk(nullable=False, ondelete="CASCADE")
    triggered_at: Mapped[datetime] = created_at()
    severity: Mapped[str] = mapped_column(String(12), nullable=False)  # info | warning | critical
    title: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new")  # new | acknowledged | resolved
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("alert_id", "channel", name="uq_alert_deliveries_alert_channel"),)  # 0013
    id: Mapped[uuid.UUID] = uuid_pk()
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)  # sent | failed | skipped
    recipient: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = created_at()


class SavedLocation(Base):
    __tablename__ = "saved_locations"
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk(nullable=False, ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=False)
    zoom: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at()


class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = _user_fk(nullable=False, ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WatchlistItem(Base):
    """One monitored target. Exactly one of facility_id / geom / admin_district is set."""

    __tablename__ = "watchlist_items"
    id: Mapped[uuid.UUID] = uuid_pk()
    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # facility | location | polygon | district | event
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("facilities.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"))
    geom = mapped_column(Geography("GEOMETRY", srid=4326, spatial_index=False))
    radius_m: Mapped[float | None] = mapped_column(Float)
    admin_district: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = created_at()


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = _user_fk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")  # pending | ready | failed
    format: Mapped[str] = mapped_column(String(8), nullable=False, default="pdf")
    file_path: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReportExport(Base):
    __tablename__ = "report_exports"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = _user_fk()
    exported_at: Mapped[datetime] = created_at()
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="download")
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
