"""Explicit, traceable feature pipeline. Every feature is declared here with its origin.

Missing inputs are NaN (never imputed with a fabricated constant); LightGBM handles NaN natively
and the rule classifier treats them as "not available". docs/ML.md renders this table.
"""
import math
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

NAN = float("nan")


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    origin: str  # firms | derived | facility | land | weather | calendar
    description: str


FEATURES: list[FeatureSpec] = [
    FeatureSpec("frp_max_log", "firms", "log1p of maximum Fire Radiative Power (MW) across detections"),
    FeatureSpec("frp_mean_log", "firms", "log1p of mean FRP (MW)"),
    FeatureSpec("frp_cv", "derived", "coefficient of variation of daily max FRP (steadiness)"),
    FeatureSpec("brightness_mean", "firms", "mean brightness temperature, MODIS 4µm / VIIRS I4 (K)"),
    FeatureSpec("brightness_delta", "firms", "mean difference MIR − TIR brightness (K): hot small source vs broad fire"),
    FeatureSpec("confidence_mean", "firms", "mean detection confidence (0–100; VIIRS l/n/h mapped 25/60/90)"),
    FeatureSpec("night_fraction", "firms", "share of detections acquired at night"),
    FeatureSpec("pixel_area_km2", "firms", "mean scan × track pixel footprint (km²): location precision"),
    FeatureSpec("observation_count_log", "derived", "log1p of detections in the event"),
    FeatureSpec("active_days", "derived", "distinct days with detections"),
    FeatureSpec("span_days", "derived", "days between first and last detection (inclusive)"),
    FeatureSpec("observation_frequency", "derived", "active_days / span_days"),
    FeatureSpec("sensor_count", "derived", "distinct satellite platforms observing the event"),
    FeatureSpec("persistence_score", "derived", "persistence engine score (0–1)"),
    FeatureSpec("recurrence_count", "derived", "earlier separate events within 1.5 km in prior 365 days"),
    FeatureSpec("spatial_spread_km", "derived", "max distance of any pixel from the event centroid (km)"),
    FeatureSpec("dist_oil_gas_km", "facility", "distance to nearest refinery / oil-gas / flare facility (km, NaN if none within 10 km)"),
    FeatureSpec("dist_heavy_industry_km", "facility", "distance to nearest steel/cement/chemical/coal-power/factory/industrial area (km)"),
    FeatureSpec("dist_mine_km", "facility", "distance to nearest mine / coal mine (km)"),
    FeatureSpec("facility_count_5km", "facility", "mapped facilities within 5 km"),
    FeatureSpec("land_cropland", "land", "1 if OSM farmland/orchard/meadow within 1.5 km, 0 if checked and absent, NaN if not checked"),
    FeatureSpec("land_forest", "land", "1 if OSM forest/wood/scrub within 1.5 km (0/NaN as above)"),
    FeatureSpec("land_residential", "land", "1 if OSM residential landuse within 1.5 km (0/NaN as above)"),
    FeatureSpec("wind_speed_ms", "weather", "10 m wind speed at last detection (m/s)"),
    FeatureSpec("month_sin", "calendar", "sin(2π·month/12) of first detection — seasonality"),
    FeatureSpec("month_cos", "calendar", "cos(2π·month/12) of first detection — seasonality"),
]
FEATURE_NAMES = [f.name for f in FEATURES]

OIL_GAS = ("refinery", "oil_gas", "flare_site")
HEAVY = ("steel_plant", "cement_plant", "chemical_plant", "power_plant_coal", "factory", "industrial_area", "power_plant_gas")
MINES = ("mine", "coal_mine")

_Q = text(
    """
    SELECT e.*,
      (SELECT avg(d.brightness) FROM thermal_detections d WHERE d.event_id = e.id) AS brightness_mean,
      (SELECT avg(d.brightness - d.brightness_2) FROM thermal_detections d WHERE d.event_id = e.id) AS brightness_delta,
      (SELECT avg(d.scan * d.track) FROM thermal_detections d WHERE d.event_id = e.id) AS pixel_area,
      (SELECT max(o.spread_m) FROM thermal_observations o WHERE o.event_id = e.id) AS spread_m,
      (SELECT min(l.distance_m) FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
        WHERE l.event_id = e.id AND f.facility_type = ANY(:oil)) AS d_oil,
      (SELECT min(l.distance_m) FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
        WHERE l.event_id = e.id AND f.facility_type = ANY(:heavy)) AS d_heavy,
      (SELECT min(l.distance_m) FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
        WHERE l.event_id = e.id AND f.facility_type = ANY(:mines)) AS d_mine,
      (SELECT count(*) FROM facilities f WHERE ST_DWithin(f.geom, e.geom, 5000)) AS fac_5km,
      (SELECT array_agg(DISTINCT category) FROM land_context lc WHERE lc.event_id = e.id) AS land_cats,
      (SELECT w.wind_speed_ms FROM weather_observations w WHERE w.event_id = e.id AND w.kind = 'at_last_detection'
        ORDER BY w.observed_at DESC LIMIT 1) AS wind_speed
    FROM thermal_events e WHERE e.id = :id
    """
)


def _log1p(v) -> float:
    return math.log1p(v) if v is not None and v >= 0 else NAN


def _km(v) -> float:
    return round(v / 1000.0, 3) if v is not None else NAN


def _num(v) -> float:
    return float(v) if v is not None else NAN


def build_features(db: Session, event_id) -> dict[str, float]:
    r = db.execute(_Q, {"id": event_id, "oil": list(OIL_GAS), "heavy": list(HEAVY), "mines": list(MINES)}).mappings().one()
    pm = r["persistence_metrics"] or {}
    osm_checked = bool((r["enrichment_state"] or {}).get("osm", {}).get("status") == "ok")
    cats = set(r["land_cats"] or [])

    def land(*names: str) -> float:
        if not osm_checked:
            return NAN
        return 1.0 if cats.intersection(names) else 0.0

    month = r["first_detected"].month
    return {
        "frp_max_log": _log1p(r["frp_max"]),
        "frp_mean_log": _log1p(r["frp_mean"]),
        "frp_cv": _num(pm.get("frp_cv")),
        "brightness_mean": _num(r["brightness_mean"]),
        "brightness_delta": _num(r["brightness_delta"]),
        "confidence_mean": _num(r["confidence_mean"]),
        "night_fraction": _num(r["night_fraction"]),
        "pixel_area_km2": _num(r["pixel_area"]),
        "observation_count_log": _log1p(r["observation_count"]),
        "active_days": _num(pm.get("active_days")),
        "span_days": _num(pm.get("span_days")),
        "observation_frequency": _num(pm.get("observation_frequency")),
        "sensor_count": float(r["sensor_count"]),
        "persistence_score": _num(r["persistence_score"]),
        "recurrence_count": _num(pm.get("recurrence_count")),
        "spatial_spread_km": _km(r["spread_m"]),
        "dist_oil_gas_km": _km(r["d_oil"]),
        "dist_heavy_industry_km": _km(r["d_heavy"]),
        "dist_mine_km": _km(r["d_mine"]),
        "facility_count_5km": float(r["fac_5km"]),
        "land_cropland": land("cropland"),
        "land_forest": land("forest", "scrub"),
        "land_residential": land("residential"),
        "wind_speed_ms": _num(r["wind_speed"]),
        "month_sin": round(math.sin(2 * math.pi * month / 12), 4),
        "month_cos": round(math.cos(2 * math.pi * month / 12), 4),
    }


def to_json_safe(features: dict[str, float]) -> dict[str, float | None]:
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in features.items()}
