"""Evidence bundle + thermal fingerprint.

Each evidence item states what KIND of knowledge it is (product principle §4):
  observed  — satellite measurement (FIRMS)
  derived   — computed by ThermalTrace from observations (persistence, clustering)
  external  — third-party context (OSM, GEM/CEA/WRI, weather, imagery catalogue)
  model     — model output (prediction, SHAP)
"""
import math
from dataclasses import dataclass, field

from app.gis.geo import compass
from app.ml.base import CLASS_LABELS, Prediction

INDUSTRIAL_LABELS = {"flare", "process_heat", "coal_seam_fire", "industrial_fire"}
FACILITY_LABELS = {
    "refinery": "refinery", "oil_gas": "oil & gas facility", "flare_site": "flare stack", "power_plant_coal": "coal power plant",
    "power_plant_gas": "gas/oil power plant", "power_plant_other": "power plant", "steel_plant": "steel plant",
    "cement_plant": "cement plant", "chemical_plant": "chemical plant", "mine": "mine", "coal_mine": "coal mine",
    "landfill": "landfill", "factory": "factory", "industrial_area": "industrial area", "rail": "rail facility", "other": "facility",
}


@dataclass
class EvidenceItem:
    category: str
    knowledge_type: str
    direction: str
    strength: float
    statement: str
    value: dict | None = None
    provenance: dict | None = field(default=None)


def _fmt_km(m: float) -> str:
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{m:.0f} m"


def build_evidence(ctx: dict, label: str, rule: Prediction, gbm: Prediction | None) -> list[EvidenceItem]:
    """ctx: event dict + persistence + facilities (ranked) + land + weather + satellite + quality."""
    ev = ctx["event"]
    items: list[EvidenceItem] = []
    firms_prov = {"source": "NASA FIRMS", "datasets": ev["datasets"],
                  "observed_from": ev["first_detected"], "observed_to": ev["last_detected"]}

    # --- observed ---------------------------------------------------------------------------
    items.append(EvidenceItem(
        "firms", "observed", "neutral", 0.6,
        f"{ev['observation_count']} FIRMS detection(s) from {ev['sensor_count']} platform(s) "
        f"({', '.join(ev['sensors'])}); max FRP {ev['frp_max'] or 0:.1f} MW.",
        {"observation_count": ev["observation_count"], "sensors": ev["sensors"], "frp_max": ev["frp_max"],
         "frp_mean": ev["frp_mean"]}, firms_prov))
    if ev["sensor_count"] >= 2:
        items.append(EvidenceItem("firms", "observed", "supports", min(0.3 * ev["sensor_count"], 1.0),
                                  f"Multi-sensor agreement: {ev['sensor_count']} independent platforms detected this source.",
                                  {"sensors": ev["sensors"]}, firms_prov))
    nf = ev.get("night_fraction")
    if nf is not None and label == "flare":
        items.append(EvidenceItem("firms", "observed", "supports" if nf >= 0.4 else "contradicts", abs(nf - 0.4) + 0.3,
                                  f"{nf:.0%} of detections were at night (flares burn continuously; many other fires are daytime).",
                                  {"night_fraction": nf}, firms_prov))

    # --- derived ----------------------------------------------------------------------------
    pm = ctx["persistence"]
    items.append(EvidenceItem(
        "persistence", "derived", "neutral", pm["score"],
        f"{pm['persistence_class'].upper()}: {pm['rationale']}.",
        {k: pm[k] for k in ("active_days", "span_days", "observation_frequency", "longest_gap_days", "frp_cv",
                            "recurrence_count", "history_window_days")},
        {"method": "ThermalTrace persistence engine", "doc": "docs/GIS.md#persistence"}))
    if pm["recurrence_count"]:
        items.append(EvidenceItem("history", "derived", "supports" if label in INDUSTRIAL_LABELS else "neutral", 0.6,
                                  f"{pm['recurrence_count']} earlier, separate thermal event(s) within 1.5 km in the prior year.",
                                  {"recurrence_count": pm["recurrence_count"]}))
    if pm["history_window_days"] < 30:
        items.append(EvidenceItem("history", "derived", "missing", 0.5,
                                  f"Only {pm['history_window_days']} days of FIRMS history are loaded — long-term persistence "
                                  "cannot yet be established.", {"history_window_days": pm["history_window_days"]}))

    # --- external: facilities ------------------------------------------------------------------
    facs = ctx["facilities"]
    if ctx["osm_status"] != "ok" and not facs:
        items.append(EvidenceItem("facility", "external", "missing", 0.5,
                                  "Infrastructure context not yet retrieved for this location.", None))
    elif not facs:
        items.append(EvidenceItem("facility", "external", "contradicts" if label in INDUSTRIAL_LABELS else "supports", 0.5,
                                  "No mapped industrial facility within 10 km (OSM and loaded registries; mapping may be incomplete).",
                                  None, {"sources": ["OpenStreetMap"]}))
    for f in facs[:3]:
        direction = "supports" if (label in INDUSTRIAL_LABELS and f["score"] >= 0.15) else (
            "contradicts" if label in ("agricultural_burn", "wildfire") and f["distance_m"] < 2000 and f["score"] >= 0.2 else "neutral")
        name = f.get("name") or "unnamed"
        items.append(EvidenceItem(
            "facility", "external", direction, min(f["score"] / 0.6, 1.0),
            f"Thermal event is {_fmt_km(f['distance_m'])} {compass(f['bearing'] or 0) if f.get('bearing') is not None else ''} "
            f"of a mapped {FACILITY_LABELS.get(f['facility_type'], f['facility_type'])} ({name}; source {f['primary_source']}).".replace("  ", " "),
            {"facility_id": str(f["id"]), "distance_m": round(f["distance_m"]), "type": f["facility_type"],
             "attribution_score": f["score"], "status": f.get("status")},
            {"source": f["primary_source"], "source_count": f["source_count"]}))

    # --- external: land ---------------------------------------------------------------------------
    land = ctx["land"]
    if land:
        cats = sorted({lc["category"] for lc in land})
        nearest = {c: min(lc["distance_m"] for lc in land if lc["category"] == c) for c in cats}
        veg = label in ("agricultural_burn", "wildfire")
        items.append(EvidenceItem(
            "land", "external", "supports" if veg and ({"cropland", "forest", "scrub"} & set(cats)) else "neutral", 0.5,
            "Mapped land use nearby: " + ", ".join(f"{c} ({_fmt_km(d)})" for c, d in nearest.items()) + ".",
            {"categories": nearest}, {"source": "OpenStreetMap"}))
    elif ctx["osm_status"] == "ok":
        items.append(EvidenceItem("land", "external", "neutral", 0.2, "No farmland, forest or residential land use mapped within 1.5 km.",
                                  None, {"source": "OpenStreetMap"}))

    # --- external: weather ----------------------------------------------------------------------
    w = ctx["weather"]
    if w:
        disp = (w["wind_direction_deg"] + 180) % 360 if w.get("wind_direction_deg") is not None else None
        items.append(EvidenceItem(
            "weather", "external", "neutral", 0.3,
            f"At {w['observed_at']:%d %b %H:%M} UTC: {w.get('condition') or 'conditions n/a'}, "
            f"{w['temperature_c'] if w['temperature_c'] is not None else '–'} °C, RH {w['humidity_pct'] if w['humidity_pct'] is not None else '–'}%, "
            f"wind {w['wind_speed_ms'] if w['wind_speed_ms'] is not None else '–'} m/s from {compass(w['wind_direction_deg']) if w.get('wind_direction_deg') is not None else '–'}"
            + (f"; potential dispersion direction toward {compass(disp)} ({disp:.0f}°)." if disp is not None else "."),
            {"wind_direction_deg": w.get("wind_direction_deg"), "dispersion_bearing_deg": disp,
             "wind_speed_ms": w.get("wind_speed_ms"), "precipitation_mm": w.get("precipitation_mm")},
            {"source": "Open-Meteo", "dataset": w["dataset"], "retrieved_at": w["retrieved_at"]}))
        if (w.get("precipitation_mm") or 0) > 2 and label in ("agricultural_burn", "wildfire"):
            items.append(EvidenceItem("weather", "external", "contradicts", 0.3,
                                      f"{w['precipitation_mm']} mm precipitation in the hour of detection is atypical for open burning.",
                                      None))
    else:
        items.append(EvidenceItem("weather", "external", "missing", 0.2, "Weather at detection time not available.", None))

    # --- external: satellite -----------------------------------------------------------------------
    scenes = ctx["satellite"]
    if ctx["satellite_status"] != "ok":
        items.append(EvidenceItem("satellite", "external", "missing", 0.4,
                                  "Sentinel-2 imagery not yet searched for this event.", None))
    elif not scenes:
        items.append(EvidenceItem("satellite", "external", "missing", 0.4,
                                  "No Sentinel-2 L2A scene within the search window under the cloud threshold.", None))
    else:
        best = min(scenes, key=lambda s: (s["cloud_cover"] if s["cloud_cover"] is not None else 101))
        items.append(EvidenceItem(
            "satellite", "external", "neutral", 0.4,
            f"{len(scenes)} Sentinel-2 L2A scene(s) available; clearest {best['acquired_at']:%d %b %Y} "
            f"({best['cloud_cover']:.0f}% cloud, {best['platform']}). Imagery is available for analyst "
            "comparison — it has not been analysed automatically.",
            {"scene_count": len(scenes), "best_item": best["item_id"], "best_cloud": best["cloud_cover"]},
            {"source": "Copernicus Sentinel-2 via Earth Search", "item": best["item_id"]}))

    # --- model --------------------------------------------------------------------------------
    items.append(EvidenceItem(
        "model", "model", "neutral", rule.probability,
        f"Rule cascade ({rule.model_id}) → {CLASS_LABELS[rule.label]} (p={rule.probability:.2f}). " + " ".join(rule.trace),
        {"trace": rule.trace}, {"model": rule.model_id}))
    if gbm is not None:
        agree = gbm.label == rule.label
        top = ", ".join(f"{c.feature} ({'+' if c.contribution >= 0 else ''}{c.contribution:.2f})" for c in gbm.contributions[:4])
        items.append(EvidenceItem(
            "model", "model", "supports" if agree else "contradicts", gbm.probability,
            f"Gradient-boosting model ({gbm.model_id}) → {CLASS_LABELS.get(gbm.label, gbm.label)} (p={gbm.probability:.2f})"
            f"{'' if agree else ' — disagrees with the rule cascade'}. Largest SHAP contributions: {top}.",
            {"shap": [c.__dict__ for c in gbm.contributions]}, {"model": gbm.model_id}))
    return items


def fingerprint(ev: dict, pm: dict, top_facility: dict | None, land_cats: list[str], weather: dict | None) -> dict:
    """Compact, comparable signature of an event (used for display and similar-event search)."""
    frp = ev.get("frp_max") or 0.0
    intensity = min(math.log1p(frp) / math.log1p(500), 1.0)
    proximity = 0.0 if not top_facility else round(math.exp(-top_facility["distance_m"] / 1500), 3)
    return {
        "intensity": round(intensity, 3),
        "persistence": pm["score"],
        "sensor_agreement": pm["sensor_agreement"],
        "facility_proximity": proximity,
        "recurrence": round(min(pm["recurrence_count"] / 3, 1.0), 3),
        "night_share": round(ev.get("night_fraction") or 0.0, 3),
        "facility_type": top_facility["facility_type"] if top_facility else None,
        "land": land_cats,
        "wind_speed_ms": weather.get("wind_speed_ms") if weather else None,
        "month": ev["first_detected"].month,
    }
