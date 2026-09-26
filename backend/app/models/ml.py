import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._common import created_at, uuid_pk

SOURCE_CLASSES = (
    "flare",
    "process_heat",
    "coal_seam_fire",
    "agricultural_burn",
    "wildfire",
    "industrial_fire",
    "other",
    "unknown",
)
PERSISTENCE_CLASSES = ("transient", "recurring", "persistent")
CONFIDENCE_STATES = (
    "CONFIRMED",
    "HIGH_CONFIDENCE",
    "MODERATE_CONFIDENCE",
    "LOW_CONFIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "UNDER_REVIEW",
    "ANALYST_CONFIRMED",
    "ANALYST_REJECTED",
)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # rule | lightgbm
    description: Mapped[str] = mapped_column(Text, nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    classes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    training_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    label_provenance: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at()


class ModelPrediction(Base):
    """Raw output of one model for one event at one point in time."""

    __tablename__ = "model_predictions"
    __table_args__ = (Index("ix_predictions_event_created", "event_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False
    )
    model_version_id: Mapped[str] = mapped_column(String(64), ForeignKey("model_versions.id"), nullable=False)
    prediction: Mapped[str] = mapped_column(String(32), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    probabilities: Mapped[dict] = mapped_column(JSONB, nullable=False)
    features_used: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[dict | None] = mapped_column(JSONB)  # SHAP (gbm) or rule trace (rule)
    created_at: Mapped[datetime] = created_at()


class Classification(Base):
    """The system's adjudicated classification (models + confidence engine). One current row per event."""

    __tablename__ = "classifications"
    __table_args__ = (
        Index("ix_classifications_event_current", "event_id", "is_current"),
        Index("ix_classifications_current_model", "primary_model_id", postgresql_where=text("is_current")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False
    )
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    persistence_class: Mapped[str] = mapped_column(String(16), nullable=False)
    probability: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_state: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    primary_model_id: Mapped[str] = mapped_column(String(64), ForeignKey("model_versions.id"), nullable=False)
    supporting_model_ids: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = created_at()


class ClassificationEvidence(Base):
    __tablename__ = "classification_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    classification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classifications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thermal_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # firms | persistence | facility | land | weather | satellite | model | history | data_quality
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    # observed | derived | external | model  (the kind of knowledge — product principle §4)
    knowledge_type: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(12), nullable=False)  # supports | contradicts | neutral | missing
    strength: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONB)
    provenance: Mapped[dict | None] = mapped_column(JSONB)
