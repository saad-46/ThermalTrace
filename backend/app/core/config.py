"""Central configuration. Every value comes from the environment (see ../.env.example).

Credentials are optional wherever a provider can work without them; an integration whose
credential is missing reports itself as `not_configured` instead of silently degrading.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

_INSECURE_DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore", case_sensitive=False
    )

    # --- runtime ---------------------------------------------------------------------------
    environment: Literal["development", "staging", "production", "test"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    demo_mode: bool = False

    # --- database --------------------------------------------------------------------------
    database_url: str = "postgresql+psycopg://thermaltrace:thermaltrace_dev_only@localhost:5432/thermaltrace"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- security --------------------------------------------------------------------------
    secret_key: SecretStr = SecretStr(_INSECURE_DEV_SECRET)
    access_token_ttl_minutes: int = 480
    cors_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 600  # per session token (per IP when anonymous)
    login_rate_limit_per_minute: int = 10

    # --- NASA FIRMS ------------------------------------------------------------------------
    firms_map_key: SecretStr | None = None
    firms_base_url: str = "https://firms.modaps.eosdis.nasa.gov"
    # Region of interest for scheduled ingestion: west,south,east,north
    region_bbox: tuple[float, float, float, float] = (68.0, 6.5, 97.5, 35.7)
    region_country_iso3: str = "IND"
    # Which public NRT regional files to poll (keyless). See integrations/firms.py.
    firms_region_name: str = "South_Asia"
    firms_poll_minutes: int = 30

    # --- OSM / Overpass ---------------------------------------------------------------------
    overpass_urls: str = "https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter"
    overpass_min_interval_s: float = 2.0
    osm_cache_ttl_hours: int = 24 * 7

    # --- facility registries (controlled dataset ingestion) ----------------------------------
    datasets_dir: Path = REPO_DIR / "data" / "datasets"

    # --- Sentinel-2 -------------------------------------------------------------------------
    earth_search_url: str = "https://earth-search.aws.element84.com/v1"
    cdse_stac_url: str = "https://stac.dataspace.copernicus.eu/v1"
    copernicus_client_id: str | None = None
    copernicus_client_secret: SecretStr | None = None
    satellite_max_cloud: float = 60.0

    # --- weather ----------------------------------------------------------------------------
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"

    # --- geocoding ----------------------------------------------------------------------------
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # --- delivery ----------------------------------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = Field(None, validation_alias=AliasChoices("smtp_username", "smtp_user"))
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str | None = None

    # --- storage / observability --------------------------------------------------------------
    report_storage_dir: Path = BACKEND_DIR / "var" / "reports"
    model_dir: Path = BACKEND_DIR / "var" / "models"
    sentry_dsn: str | None = None
    http_user_agent: str = "ThermalTrace/1.0 (+https://github.com/saad-46/thermal-trace-demo-1)"

    # --- processing parameters (documented in docs/GIS.md) ---------------------------------------
    cluster_radius_m: float = Field(1500.0, gt=0)
    cluster_gap_days: int = Field(5, ge=1)
    attribution_radius_m: float = Field(10000.0, gt=0)

    @model_validator(mode="after")
    def _guard_production(self) -> "Settings":
        if self.environment in ("staging", "production"):
            if self.secret_key.get_secret_value() == _INSECURE_DEV_SECRET or len(self.secret_key.get_secret_value()) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters outside development")
            if self.demo_mode and self.environment == "production":
                raise ValueError("DEMO_MODE cannot be enabled in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def overpass_url_list(self) -> list[str]:
        return [u.strip() for u in self.overpass_urls.split(",") if u.strip()]

    @property
    def firms_key(self) -> str | None:
        return self.firms_map_key.get_secret_value() if self.firms_map_key else None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
