"""Confidence engine and data-quality assessment — both fully decomposed, never a single opaque number.

CONFIDENCE (0–1) = Σ weight × component. Components (each 0–1, each explained):
  model_probability   primary model's probability for its label                     0.28
  model_agreement     rule cascade and GBM agree (1.0), disagree (0.25), GBM absent (0.5) 0.12
  context_support     facility attribution (industrial classes) or land context (vegetation) 0.16
  temporal_consistency persistence class consistent with the label                   0.14
  sensor_agreement    independent platforms observing (1 → 0.2, 2 → 0.6, ≥3 → 1.0)   0.10
  satellite           clear Sentinel-2 scene near detection time (1) / cloudy (0.5) / none (0.1) / not checked (0.3)  0.08
  weather             weather context retrieved (1) / not (0.3)                      0.04
  data_quality        data-quality score                                              0.08

STATE:
  unknown label, poor data quality, or confidence < 0.40 → INSUFFICIENT_EVIDENCE (manual review required)
  < 0.55 LOW_CONFIDENCE · < 0.72 MODERATE_CONFIDENCE · otherwise HIGH_CONFIDENCE
  CONFIRMED only if HIGH and corroborated by ≥2 platforms, a persistent/recurring pattern consistent
  with the label, strong context support, AND an independent imagery check (SWIR) passed. Without
  imagery analysis the system never claims CONFIRMED.
  Analyst decisions override the displayed state (ANALYST_CONFIRMED / ANALYST_REJECTED / ANALYST_REVIEWED / UNDER_REVIEW).
"""
from dataclasses import dataclass

WEIGHTS = {
    "model_probability": 0.28,
    "model_agreement": 0.12,
    "context_support": 0.16,
    "temporal_consistency": 0.14,
    "sensor_agreement": 0.10,
    "satellite": 0.08,
    "weather": 0.04,
    "data_quality": 0.08,
}
INDUSTRIAL = {"flare", "process_heat", "coal_seam_fire", "industrial_fire"}
VEGETATION = {"agricultural_burn", "wildfire"}
EXPECTED_PERSISTENCE = {
    "flare": {"persistent": 1.0, "recurring": 0.6, "transient": 0.2},
    "process_heat": {"persistent": 1.0, "recurring": 0.8, "transient": 0.3},
    "coal_seam_fire": {"persistent": 1.0, "recurring": 0.8, "transient": 0.2},
    "agricultural_burn": {"persistent": 0.3, "recurring": 0.8, "transient": 1.0},
    "wildfire": {"persistent": 0.5, "recurring": 0.8, "transient": 0.9},
    "industrial_fire": {"persistent": 0.3, "recurring": 0.5, "transient": 1.0},
    "other": {"persistent": 0.5, "recurring": 0.5, "transient": 0.5},
    "unknown": {"persistent": 0.3, "recurring": 0.3, "transient": 0.3},
}
REVIEW_OVERRIDES = {
    "analyst_confirmed": "ANALYST_CONFIRMED",
    "analyst_rejected": "ANALYST_REJECTED",
    "false_positive": "ANALYST_REJECTED",
    "under_review": "UNDER_REVIEW",
    "escalated": "UNDER_REVIEW",
    # an analyst reviewed the evidence and closed the review without confirming or rejecting the interpretation
    "reviewed": "ANALYST_REVIEWED",
}
# every review status an event can have (thermal_events.review_status); the list filter accepts only these
REVIEW_STATUSES = ("unreviewed", "under_review", "escalated", "reviewed", "analyst_confirmed", "analyst_rejected", "false_positive")


@dataclass
class Component:
    name: str
    value: float
    weight: float
    explanation: str


@dataclass
class ConfidenceResult:
    score: float
    state: str
    components: list[Component]
    missing: list[str]

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "state": self.state,
            "components": [c.__dict__ for c in self.components],
            "missing": self.missing,
        }


@dataclass
class QualityResult:
    grade: str  # excellent | good | limited | poor
    score: float
    factors: list[dict]

    def as_dict(self) -> dict:
        return {"grade": self.grade, "score": self.score, "factors": self.factors}


def assess_data_quality(ev: dict) -> QualityResult:
    """ev keys: sensor_count, pixel_area_km2, osm_status, facilities_10km, best_cloud, satellite_status,
    weather_status, history_window_days, hours_since_last, data_mode, observation_count"""
    factors = []

    def add(name: str, score: float, detail: str):
        factors.append({"factor": name, "score": round(score, 2), "detail": detail})

    sc = ev.get("sensor_count") or 0
    add("sensor_availability", min(sc / 3, 1.0), f"{sc} independent platform(s) observed this event")
    px = ev.get("pixel_area_km2")
    if px is None:
        add("location_precision", 0.5, "pixel footprint unknown")
    else:
        add("location_precision", 1.0 if px <= 0.3 else 0.7 if px <= 1.5 else 0.4,
            f"mean pixel footprint {px:.2f} km² ({'VIIRS 375 m class' if px <= 0.3 else 'coarse / MODIS 1 km class'})")
    osm = ev.get("osm_status")
    if osm == "ok":
        n = ev.get("facilities_10km") or 0
        add("facility_coverage", 1.0 if n else 0.6,
            f"OSM/registry checked; {n} mapped facilit{'y' if n == 1 else 'ies'} within 10 km"
            + ("" if n else " (absence may reflect incomplete mapping)"))
    else:
        add("facility_coverage", 0.3, "OSM context not yet retrieved" if osm is None else f"OSM lookup {osm}")
    sat = ev.get("satellite_status")
    cloud = ev.get("best_cloud")
    if sat == "ok" and cloud is not None:
        add("satellite_cloud", 1.0 if cloud < 20 else 0.6 if cloud < 60 else 0.3, f"best Sentinel-2 scene {cloud:.0f}% cloud")
    elif sat == "ok":
        add("satellite_cloud", 0.2, "no Sentinel-2 scene within the search window")
    else:
        add("satellite_cloud", 0.3, "imagery not yet searched" if sat is None else f"imagery search {sat}")
    add("weather_availability", 1.0 if ev.get("weather_status") == "ok" else 0.3,
        "weather at detection time retrieved" if ev.get("weather_status") == "ok" else "weather not available")
    hw = ev.get("history_window_days") or 0
    add("historical_depth", min(hw / 90, 1.0), f"{hw} day(s) of FIRMS history in the database for persistence analysis")
    if ev.get("data_mode") == "demo":
        add("source_freshness", 0.0, "synthetic demo data")
    else:
        h = ev.get("hours_since_last")
        add("source_freshness", 1.0 if h is not None and h <= 24 else 0.7 if h is not None and h <= 72 else 0.4,
            f"last detection {h:.0f} h ago" if h is not None else "unknown")
    weights = {"sensor_availability": 0.2, "location_precision": 0.1, "facility_coverage": 0.2, "satellite_cloud": 0.15,
               "weather_availability": 0.05, "historical_depth": 0.2, "source_freshness": 0.1}
    score = round(sum(weights[f["factor"]] * f["score"] for f in factors), 3)
    grade = "excellent" if score >= 0.8 else "good" if score >= 0.6 else "limited" if score >= 0.4 else "poor"
    return QualityResult(grade, score, factors)


def compute_confidence(
    *, label: str, probability: float, rule_label: str, gbm_label: str | None, persistence_class: str,
    attribution_score: float | None, land_support: bool | None, sensor_count: int, satellite_status: str | None,
    best_cloud: float | None, weather_ok: bool, quality: QualityResult, swir_confirmed: bool = False,
) -> ConfidenceResult:
    comps: list[Component] = []
    missing: list[str] = []

    def add(name: str, value: float, why: str):
        comps.append(Component(name, round(max(0.0, min(value, 1.0)), 3), WEIGHTS[name], why))

    add("model_probability", probability, f"primary model probability {probability:.2f} for '{label}'")
    if gbm_label is None:
        add("model_agreement", 0.5, "only the rule cascade is active (no trained model yet)")
        missing.append("trained model")
    elif gbm_label == rule_label:
        add("model_agreement", 1.0, f"rule cascade and gradient-boosting model agree ('{rule_label}')")
    else:
        add("model_agreement", 0.25, f"models disagree: rules '{rule_label}' vs GBM '{gbm_label}'")

    if label in INDUSTRIAL:
        if attribution_score:
            add("context_support", min(attribution_score / 0.6, 1.0), f"facility attribution score {attribution_score:.2f}")
        else:
            add("context_support", 0.1, "no mapped facility supports an industrial label")
    elif label in VEGETATION:
        if land_support is None:
            add("context_support", 0.3, "land context not yet retrieved")
            missing.append("land context")
        else:
            add("context_support", 0.9 if land_support else 0.3,
                "mapped land cover consistent with label" if land_support else "no supporting land cover mapped")
    else:
        add("context_support", 0.2, "no discriminating context")

    tc = EXPECTED_PERSISTENCE.get(label, {}).get(persistence_class, 0.3)
    add("temporal_consistency", tc, f"'{persistence_class}' pattern vs typical behaviour of '{label}'")
    add("sensor_agreement", {0: 0.0, 1: 0.2, 2: 0.6}.get(sensor_count, 1.0), f"{sensor_count} platform(s)")

    if satellite_status == "ok":
        if best_cloud is None:
            add("satellite", 0.1, "no Sentinel-2 scene in the window")
        else:
            add("satellite", 1.0 if best_cloud < 20 else 0.5, f"clearest scene {best_cloud:.0f}% cloud")
    else:
        add("satellite", 0.3, "imagery not yet checked")
        missing.append("satellite imagery")
    add("weather", 1.0 if weather_ok else 0.3, "weather context available" if weather_ok else "no weather context")
    if not weather_ok:
        missing.append("weather")
    add("data_quality", quality.score, f"data quality '{quality.grade}'")

    score = round(sum(c.value * c.weight for c in comps), 3)
    if label == "unknown" or quality.grade == "poor" or score < 0.40:
        state = "INSUFFICIENT_EVIDENCE"
    elif score < 0.55:
        state = "LOW_CONFIDENCE"
    elif score < 0.72:
        state = "MODERATE_CONFIDENCE"
    else:
        state = "HIGH_CONFIDENCE"
    if (state == "HIGH_CONFIDENCE" and swir_confirmed and sensor_count >= 2 and tc >= 0.8
            and next(c.value for c in comps if c.name == "context_support") >= 0.8):
        state = "CONFIRMED"
    return ConfidenceResult(score, state, comps, missing)


def display_state(system_state: str, review_status: str) -> str:
    return REVIEW_OVERRIDES.get(review_status, system_state)
