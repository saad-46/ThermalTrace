"""Response schemas for the investigation-intelligence endpoints (clusters, recurrence, comparison, facility profiles,
filtered analytics, live status). Nested aggregates are typed where their shape is stable; free-form breakdowns are
lists of {key, n}."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class KeyCount(BaseModel):
    key: str
    n: int


class ClusterSummary(BaseModel):
    events: int
    detections: int
    first_detected: datetime | None
    last_detected: datetime | None
    frp_max: float | None
    frp_mean: float | None
    extent: dict | None
    max_distance_m: float | None
    duration_hours: float


class ClusterOut(BaseModel):
    cluster_id: str
    anchor: dict
    radius_km: float
    days: int
    summary: ClusterSummary
    classifications: list[KeyCount]
    persistence: list[KeyCount]
    landcover: list[KeyCount]
    facilities: list[dict]
    events: list[dict]
    truncated: bool
    note: str


class ActivityCounts(BaseModel):
    this_week: int
    previous_week: int
    last_30_days: int
    previous_30_days: int
    total: int
    first_activity: datetime | None
    last_activity: datetime | None
    detections: int
    frp_max_mean: float | None
    frp_max: float | None
    weekly_average: float
    history_weeks: float


class RecurrenceOut(BaseModel):
    radius_km: float
    activity: ActivityCounts
    classifications: list[KeyCount]
    persistence: list[KeyCount]
    monthly: list[dict]
    note: str


class RecurringOut(BaseModel):
    days: int
    min_events: int
    facilities: list[dict]
    places: list[dict]
    note: str


class FacilityProfileOut(BaseModel):
    within_m: float
    counts: dict
    activity: ActivityCounts
    comparison: dict
    distributions: dict
    weekly: list[dict]
    source_agreement: dict
    note: str


class CompareOut(BaseModel):
    a: dict
    b: dict
    distance_m: float
    note: str


class AnalyticsFiltersOut(BaseModel):
    since: datetime
    until: datetime
    state: str | None
    district: str | None
    facility_id: uuid.UUID | None
    classification: list[str]


class OverviewTotals(BaseModel):
    events: int
    detections: int
    active: int
    active_investigations: int
    needs_review: int
    confirmed: int
    rejected: int
    reviewed: int
    high_priority_queue: int
    persistent: int


class EvidenceCoverageOut(BaseModel):
    """Events with each evidence stage; one field per key of services.evidence_rules.RULES (a test keeps them equal)."""
    events: int
    detection: int
    clustering: int
    persistence: int
    facility_proximity: int
    facility_attribution: int
    landcover: int
    weather: int
    satellite: int
    spectral: int
    classification: int
    explainability: int
    review: int
    final_status: int
    mean_stages: float | None
    stages_total: int
    note: str


class OverviewOut(BaseModel):
    filters: AnalyticsFiltersOut
    totals: OverviewTotals
    recurring_facilities: int
    evidence_coverage: EvidenceCoverageOut
    processing: dict
    note: str


class SourceStatus(BaseModel):
    id: str
    name: str
    kind: str
    status: str  # healthy | configured | optional | no_data | degraded | failed | not_configured
    label: str
    requires_credentials: bool
    optional: bool
    last_success_at: datetime | None
    last_failure_at: datetime | None


class LiveStatusOut(BaseModel):
    sources: list[SourceStatus]
    sources_active: int
    sources_total: int
    jobs: dict
    last_firms_update: datetime | None
    last_weather_update: datetime | None
    last_satellite_search: datetime | None
    last_failed_source: dict | None
    worker_online: bool
