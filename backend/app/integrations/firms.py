"""NASA FIRMS client — all sensors, one normalized schema.

Two official access paths (https://firms.modaps.eosdis.nasa.gov):

1. **Public regional NRT files (no key)** — `/data/active_fire/<product>/csv/<prefix>_<Region>_<24h|48h|7d>.csv`.
   Used for scheduled near-real-time polling. Verified reachable 2026-09-25 for all four products.
2. **Area / Country API (MAP_KEY)** — `/api/area/csv/<KEY>/<SOURCE>/<bbox>/<days>/<date>` supports historical
   dates and the Standard Processing (SP) archive. Required for `get_historical_detections`.

Nothing here falls back to synthetic data. A failure raises a ProviderError the caller records.
"""
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from app.core.config import settings
from app.integrations.http import ProviderAuthError, ProviderError, ProviderMalformed, request

logger = logging.getLogger(__name__)
PROVIDER = "firms"


@dataclass(frozen=True)
class FirmsDataset:
    key: str  # internal dataset id == FIRMS API source name for NRT
    sensor: str  # MODIS | VIIRS
    platform: str  # human label
    public_dir: str  # directory under /data/active_fire
    public_prefix: str


DATASETS: dict[str, FirmsDataset] = {
    d.key: d
    for d in (
        FirmsDataset("MODIS_NRT", "MODIS", "Terra/Aqua MODIS C6.1", "modis-c6.1", "MODIS_C6_1"),
        FirmsDataset("VIIRS_SNPP_NRT", "VIIRS", "Suomi-NPP VIIRS 375m", "suomi-npp-viirs-c2", "SUOMI_VIIRS_C2"),
        FirmsDataset("VIIRS_NOAA20_NRT", "VIIRS", "NOAA-20 VIIRS 375m", "noaa-20-viirs-c2", "J1_VIIRS_C2"),
        FirmsDataset("VIIRS_NOAA21_NRT", "VIIRS", "NOAA-21 VIIRS 375m", "noaa-21-viirs-c2", "J2_VIIRS_C2"),
    )
}
# Archive (standard processing) sources available through the keyed Area API.
HISTORICAL_SOURCES = ("MODIS_SP", "VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")
# Sources the keyed Area API accepts for backfill: the archive plus the NRT stream (recent months).
AREA_SOURCES = HISTORICAL_SOURCES + tuple(DATASETS)
# The Area and Country APIs accept a DAY_RANGE of 1-5; 6 or more returns HTTP 400 (verified 2026-09-26).
MAX_DAY_RANGE = 5


def date_chunks(start: date, days: int, step: int = MAX_DAY_RANGE) -> list[tuple[date, int]]:
    """Split [start, start + days) into consecutive windows the API accepts: [(start, n), ...]."""
    from datetime import timedelta

    if days < 1:
        raise ValueError("days must be at least 1")
    out, cursor, left = [], start, days
    while left > 0:
        n = min(step, left)
        out.append((cursor, n))
        cursor, left = cursor + timedelta(days=n), left - n
    return out

_SATELLITE_NAMES = {"T": "Terra", "A": "Aqua", "Terra": "Terra", "Aqua": "Aqua", "N": "S-NPP", "1": "NOAA-20",
                    "N20": "NOAA-20", "N21": "NOAA-21", "2": "NOAA-21"}
_VIIRS_CONF = {"l": 25.0, "low": 25.0, "n": 60.0, "nominal": 60.0, "h": 90.0, "high": 90.0}


@dataclass
class Detection:
    latitude: float
    longitude: float
    acq_datetime: datetime
    acq_date: date
    acq_time: str
    sensor: str
    satellite: str
    dataset: str
    confidence_raw: str | None
    confidence_pct: float | None
    frp: float | None
    brightness: float | None
    brightness_2: float | None
    scan: float | None
    track: float | None
    daynight: str | None
    version: str | None
    raw: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    detections: list[Detection]
    rejected: list[tuple[dict, str]]
    source_ref: str
    latency_ms: float
    retrieved_at: datetime


def normalize_confidence(sensor: str, raw: str | None) -> float | None:
    """MODIS: 0–100 numeric. VIIRS: categorical low/nominal/high mapped to a documented midpoint.

    confidence_raw stays authoritative; confidence_pct is a comparison convenience only."""
    value = (raw or "").strip().lower()
    if not value:
        return None
    if sensor == "VIIRS":
        return _VIIRS_CONF.get(value)
    try:
        pct = float(value)
    except ValueError:
        return None
    return pct if 0 <= pct <= 100 else None


def _f(row: dict, *keys: str) -> float | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except ValueError:
                return None
    return None


def parse_row(row: dict, dataset: str) -> Detection:
    """Normalize one FIRMS CSV row. Raises ValueError with a reason on invalid input."""
    sensor = DATASETS[dataset].sensor if dataset in DATASETS else ("MODIS" if dataset.startswith("MODIS") else "VIIRS")
    try:
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        acq_date = date.fromisoformat(row["acq_date"].strip())
        acq_time = row["acq_time"].strip().zfill(4)
    except (KeyError, ValueError, AttributeError) as exc:
        raise ValueError(f"missing/invalid core field: {exc}") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordinates out of range")
    if not acq_time.isdigit() or int(acq_time[:2]) > 23 or int(acq_time[2:]) > 59:
        raise ValueError(f"invalid acq_time {acq_time!r}")
    acq_dt = datetime(acq_date.year, acq_date.month, acq_date.day, int(acq_time[:2]), int(acq_time[2:]), tzinfo=UTC)
    sat_raw = (row.get("satellite") or "").strip()
    conf_raw = (row.get("confidence") or "").strip() or None
    daynight = (row.get("daynight") or "").strip().upper()[:1] or None
    return Detection(
        latitude=round(lat, 5),
        longitude=round(lon, 5),
        acq_datetime=acq_dt,
        acq_date=acq_date,
        acq_time=acq_time,
        sensor=sensor,
        satellite=_SATELLITE_NAMES.get(sat_raw, sat_raw or "unknown"),
        dataset=dataset,
        confidence_raw=conf_raw,
        confidence_pct=normalize_confidence(sensor, conf_raw),
        frp=_f(row, "frp"),
        brightness=_f(row, "bright_ti4", "brightness"),
        brightness_2=_f(row, "bright_ti5", "bright_t31"),
        scan=_f(row, "scan"),
        track=_f(row, "track"),
        daynight=daynight if daynight in ("D", "N") else None,
        version=(row.get("version") or "").strip() or None,
        raw={k: v for k, v in row.items() if k},
    )


def _parse_csv(text: str, dataset: str, bbox: tuple[float, float, float, float] | None) -> tuple[list[Detection], list]:
    stripped = text.lstrip()
    if stripped.lower().startswith(("<!doctype", "<html")):
        raise ProviderMalformed(PROVIDER, "received HTML instead of CSV")
    if stripped.lower().startswith("invalid") or "invalid map_key" in stripped.lower()[:200]:
        raise ProviderAuthError(PROVIDER, "MAP_KEY rejected by FIRMS")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "latitude" not in reader.fieldnames:
        raise ProviderMalformed(PROVIDER, f"unexpected CSV header: {reader.fieldnames}")
    good, bad = [], []
    for row in reader:
        try:
            det = parse_row(row, dataset)
        except ValueError as exc:
            bad.append((row, str(exc)))
            continue
        if bbox:
            w, s, e, n = bbox
            if not (w <= det.longitude <= e and s <= det.latitude <= n):
                continue
        good.append(det)
    return good, bad


class FIRMSClient:
    def __init__(self, map_key: str | None = None, base_url: str | None = None):
        self.map_key = map_key if map_key is not None else settings.firms_key
        self.base_url = (base_url or settings.firms_base_url).rstrip("/")

    @property
    def has_key(self) -> bool:
        return bool(self.map_key)

    # -- keyless NRT --------------------------------------------------------------------------
    def get_recent_detections(
        self, dataset: str, window: str = "24h", region: str | None = None, bbox: tuple | None = None
    ) -> FetchResult:
        if dataset not in DATASETS:
            raise ValueError(f"unknown dataset {dataset}")
        if window not in ("24h", "48h", "7d"):
            raise ValueError("window must be 24h, 48h or 7d")
        ds = DATASETS[dataset]
        url = f"{self.base_url}/data/active_fire/{ds.public_dir}/csv/{ds.public_prefix}_{region or settings.firms_region_name}_{window}.csv"
        res = request(PROVIDER, "GET", url, timeout=60)
        good, bad = _parse_csv(res.response.text, dataset, bbox or settings.region_bbox)
        return FetchResult(good, bad, url, res.latency_ms, datetime.now(UTC))

    # -- keyed Area / Country API ---------------------------------------------------------------
    def _require_key(self) -> str:
        if not self.map_key:
            raise ProviderAuthError(PROVIDER, "FIRMS_MAP_KEY is not configured (required for historical/area queries)")
        return self.map_key

    def get_detections_by_bbox(
        self, source: str, bbox: tuple[float, float, float, float], day_range: int = 1, start: date | None = None
    ) -> FetchResult:
        key = self._require_key()
        day_range = max(1, min(day_range, MAX_DAY_RANGE))
        bbox_s = ",".join(f"{c:g}" for c in bbox)
        url = f"{self.base_url}/api/area/csv/{key}/{source}/{bbox_s}/{day_range}"
        if start:
            url += f"/{start.isoformat()}"
        res = request(PROVIDER, "GET", url, timeout=90, redact=key)
        good, bad = _parse_csv(res.response.text, source, bbox)
        return FetchResult(good, bad, url.replace(key, "***"), res.latency_ms, datetime.now(UTC))

    def get_historical_detections(self, source: str, bbox: tuple, start: date, day_range: int) -> FetchResult:
        return self.get_detections_by_bbox(source, bbox, day_range=day_range, start=start)

    def get_detections_by_country(self, source: str, iso3: str, day_range: int = 1, start: date | None = None) -> FetchResult:
        key = self._require_key()
        url = f"{self.base_url}/api/country/csv/{key}/{source}/{iso3}/{max(1, min(day_range, MAX_DAY_RANGE))}"
        if start:
            url += f"/{start.isoformat()}"
        res = request(PROVIDER, "GET", url, timeout=90, redact=key)
        good, bad = _parse_csv(res.response.text, source, None)
        return FetchResult(good, bad, url.replace(key, "***"), res.latency_ms, datetime.now(UTC))

    def get_available_datasets(self) -> list[dict]:
        """With a key: FIRMS data_availability (min/max date per source). Without: the keyless NRT catalogue."""
        if not self.map_key:
            return [
                {"dataset": d.key, "sensor": d.sensor, "platform": d.platform, "access": "public NRT file (24h/48h/7d)"}
                for d in DATASETS.values()
            ]
        url = f"{self.base_url}/api/data_availability/csv/{self.map_key}/ALL"
        try:
            res = request(PROVIDER, "GET", url, timeout=30, redact=self.map_key)
        except ProviderError:
            raise
        return list(csv.DictReader(io.StringIO(res.response.text)))
