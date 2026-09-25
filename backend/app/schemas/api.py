"""Typed request/response schemas for /api/v1."""
import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.ml.base import SOURCE_CLASSES
from app.models.workflow import FALSE_POSITIVE_REASONS

T = TypeVar("T")
SourceClass = Literal["flare", "process_heat", "coal_seam_fire", "agricultural_burn", "wildfire", "industrial_fire", "other", "unknown"]
PersistenceClass = Literal["transient", "recurring", "persistent"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# --- auth -------------------------------------------------------------------------------------
class LoginIn(BaseModel):
    # Not EmailStr: login only needs an exact match, and internal domains (e.g. *.local) are valid here.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=200)
    role: Literal["viewer", "analyst", "supervisor", "admin"] = "viewer"


class UserUpdate(BaseModel):
    role: Literal["viewer", "analyst", "supervisor", "admin"] | None = None
    is_active: bool | None = None
    full_name: str | None = Field(None, min_length=1, max_length=200)


# --- events -----------------------------------------------------------------------------------
class EventSummary(BaseModel):
    id: uuid.UUID
    public_id: str
    latitude: float
    longitude: float
    data_mode: str
    first_detected: datetime
    last_detected: datetime
    observation_count: int
    sensor_count: int
    sensors: list[str]
    days_active: int
    duration_hours: float
    frp_max: float | None
    frp_mean: float | None
    night_fraction: float | None
    status: str
    review_status: str
    persistence_class: str | None
    persistence_score: float | None
    classification: str | None
    classification_probability: float | None
    confidence_score: float | None
    confidence_state: str | None
    display_state: str
    data_quality: str | None
    nearest_facility_distance_m: float | None
    nearest_facility_name: str | None
    nearest_facility_type: str | None
    admin_state: str | None
    admin_district: str | None
    country: str | None
    assigned_to: uuid.UUID | None


class EventDetail(EventSummary):
    persistence_metrics: dict | None
    confidence_components: dict | None
    data_quality_detail: dict | None
    fingerprint: dict | None
    enrichment_state: dict | None
    datasets: list[str]
    footprint: dict | None
    processed_at: datetime | None
    processing_version: str | None
    detections: list[dict]
    observations: list[dict]
    facilities: list[dict]
    land: list[dict]
    weather: list[dict]
    satellite: list[dict]
    classification_current: dict | None
    classification_history: list[dict]
    predictions: list[dict]
    evidence: list[dict]
    reviews: list[dict]
    notes: list[dict]
    alerts: list[dict]
    investigation: dict | None
    timeline: list[dict]
    evidence_matrix: list[dict]


class ReviewIn(BaseModel):
    decision: Literal["confirm", "reject", "false_positive", "escalate", "reclassify", "note"]
    source_class: SourceClass | None = None
    persistence_class: PersistenceClass | None = None
    false_positive_reason: str | None = None
    notes: str | None = Field(None, max_length=5000)

    @field_validator("false_positive_reason")
    @classmethod
    def _fp_reason(cls, v):
        if v is not None and v not in FALSE_POSITIVE_REASONS:
            raise ValueError(f"must be one of {FALSE_POSITIVE_REASONS}")
        return v


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    url: str | None = Field(None, max_length=2000)

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v and not v.startswith(("https://", "http://")):
            raise ValueError("attachment links must be http(s) URLs")
        return v


class AssignIn(BaseModel):
    user_id: uuid.UUID | None
    priority: Literal["low", "normal", "high"] = "normal"


# --- facilities ---------------------------------------------------------------------------------
class FacilityOut(BaseModel):
    id: uuid.UUID
    name: str | None
    facility_type: str
    operator: str | None
    status: str | None
    capacity_value: float | None
    capacity_unit: str | None
    state: str | None
    district: str | None
    latitude: float
    longitude: float
    confidence: float
    primary_source: str
    source_count: int
    event_count: int | None = None
    sources: list[dict] | None = None


# --- alerts / watchlists --------------------------------------------------------------------------
class AlertRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_m: float | None = Field(None, gt=0, le=500_000)
    watchlist_id: uuid.UUID | None = None
    source_classes: list[SourceClass] = []
    persistence_classes: list[PersistenceClass] = []
    facility_types: list[str] = []
    facility_within_m: float | None = Field(None, gt=0, le=50_000)
    min_confidence: float | None = Field(None, ge=0, le=1)
    min_frp: float | None = Field(None, ge=0)
    min_duration_hours: float | None = Field(None, ge=0)
    channels: list[Literal["in_app", "email", "push"]] = ["in_app"]


class AlertRuleOut(AlertRuleIn):
    id: uuid.UUID
    created_at: datetime
    last_triggered_at: datetime | None
    alert_count: int = 0


class AlertOut(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str
    event_id: uuid.UUID
    event_public_id: str
    triggered_at: datetime
    severity: str
    title: str
    reason: dict
    status: str
    acknowledged_at: datetime | None
    deliveries: list[dict]


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)


class WatchlistItemIn(BaseModel):
    kind: Literal["facility", "location", "polygon", "district", "event"]
    label: str = Field(min_length=1, max_length=200)
    facility_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    radius_m: float | None = Field(None, gt=0, le=200_000)
    polygon: list[list[float]] | None = None  # [[lon, lat], ...] closed ring
    admin_district: str | None = None


class WatchlistOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    items: list[dict]
    summary: dict


class SavedLocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    zoom: float | None = Field(None, ge=0, le=22)


# --- reports / jobs / sources -----------------------------------------------------------------------
class ReportIn(BaseModel):
    event_id: str


class ReportOut(ORM):
    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    status: str
    format: str
    size_bytes: int | None
    sha256: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class JobOut(ORM):
    id: uuid.UUID
    kind: str
    status: str
    payload: dict
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    result: dict | None


class IngestionTriggerIn(BaseModel):
    kind: Literal["firms_poll", "firms_historical", "process_events", "enrich_batch", "import_registry", "load_demo", "train_model"]
    payload: dict[str, Any] = {}


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(max_length=2000)
    keys: dict[str, str]


class RegistryImportIn(BaseModel):
    source: Literal["gem", "cea", "wri_gppd"]
    path: str | None = None
    dataset_version: str | None = None
    published_at: date | None = None


ALL_CLASSES = SOURCE_CLASSES
