"""Importing this package registers every table on Base.metadata (used by Alembic)."""
from app.models.auth import Organization, Permission, PushSubscription, Role, User, UserSession  # noqa: F401
from app.models.enrichment import ImageryAnalysis, LandCoverObservation, SatelliteObservation, WeatherObservation  # noqa: F401
from app.models.facilities import (  # noqa: F401
    EventFacilityLink,
    Facility,
    FacilityRelationship,
    FacilitySource,
    LandContext,
)
from app.models.ml import Classification, ClassificationEvidence, ModelPrediction, ModelVersion  # noqa: F401
from app.models.ops import (  # noqa: F401
    ApiCache,
    AuditLog,
    DataSource,
    FacilitySyncTile,
    IngestionCheckpoint,
    IngestionError,
    IngestionRun,
    Job,
    SystemHealth,
    WorkerHeartbeat,
)
from app.models.places import Place  # noqa: F401
from app.models.reference import AdminArea, Boundary, BoundaryPart, RegistryStation  # noqa: F401
from app.models.thermal import ThermalDetection, ThermalEvent, ThermalObservation  # noqa: F401
from app.models.workflow import (  # noqa: F401
    Alert,
    AlertDelivery,
    AlertRule,
    AnalystReview,
    Investigation,
    InvestigationNote,
    Report,
    ReportExport,
    SavedLocation,
    Watchlist,
    WatchlistItem,
)
