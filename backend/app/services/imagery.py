"""Sentinel-2 spectral change around an event: NDVI and NBR before vs after.

This is supporting evidence only. It measures how vegetation reflectance changed between two clear
scenes in a 1 km window; it does not prove the cause, and an absence of change does not rule out a
fire (revisit interval, cloud, sub-pixel size, or a non-vegetation source). Missing imagery is
recorded as `unavailable`, never as "no change".
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations import raster
from app.integrations.http import ProviderError, ProviderMalformed, request
from app.models.enrichment import ImageryAnalysis, SatelliteObservation
from app.models.thermal import ThermalEvent
from app.services import source_health

logger = logging.getLogger(__name__)
SOURCE_ID = "earth_search"
WINDOW_HALF_M = 500.0
OUT_PX = 50  # 1 km at 20 m
MAX_CLOUD = 40.0
MIN_VALID_FRACTION = 0.5
# Thresholds follow common burn-severity practice: dNBR >= 0.10 is the lowest "burned" class (USGS / UN-SPIDER);
# dNDVI <= -0.10 marks a meaningful vegetation decrease. They flag a change worth an analyst's look.
DNBR_THRESHOLD = 0.10
DNDVI_THRESHOLD = -0.10
METHOD = {
    "indices": {"ndvi": "(NIR B08 - Red B04) / (NIR + Red)", "nbr": "(NIR B8A - SWIR B12) / (NIR + SWIR)"},
    "window_m": WINDOW_HALF_M * 2, "resolution_m": 20, "mask": "SCL classes 4, 5, 7 only (cloud, shadow, cirrus, water, snow excluded)",
    "reflectance": "DN/10000, minus a 1000 DN offset for processing baseline >= 04.00",
    "thresholds": {"dnbr": DNBR_THRESHOLD, "dndvi": DNDVI_THRESHOLD},
    "scene_choice": f"latest scene before the first detection and earliest after the last detection, cloud <= {MAX_CLOUD:.0f}%",
}
REQUIRED_ASSETS = ("red", "nir", "nir08", "swir22", "scl")


def classify_change(dndvi: float | None, dnbr: float | None) -> str:
    """Descriptive finding from the two deltas."""
    ndvi_hit = dndvi is not None and dndvi <= DNDVI_THRESHOLD
    nbr_hit = dnbr is not None and dnbr >= DNBR_THRESHOLD
    if ndvi_hit and nbr_hit:
        return "vegetation_loss_consistent"
    if ndvi_hit or nbr_hit:
        return "partial_change"
    return "no_change_detected"


def scene_indices(item: dict, lat: float, lon: float) -> dict:
    """Read the bands of one STAC item and return mean NDVI/NBR over usable pixels."""
    assets = item.get("assets") or {}
    for need in REQUIRED_ASSETS:
        if need not in assets:
            raise ProviderMalformed(f"scene lacks the {need} asset")
    baseline = item.get("properties", {}).get("s2:processing_baseline")
    baseline_f = float(baseline) if baseline not in (None, "") else None
    band = {k: raster.read_window(assets[k]["href"], lat, lon, WINDOW_HALF_M, OUT_PX) for k in REQUIRED_ASSETS}
    refl = {k: raster.reflectance(v, baseline_f) for k, v in band.items() if k != "scl"}
    ndvi = raster.normalised_difference(refl["nir"], refl["red"])
    nbr = raster.normalised_difference(refl["nir08"], refl["swir22"])
    ndvi_mean, valid = raster.masked_mean(ndvi, band["scl"])
    nbr_mean, _ = raster.masked_mean(nbr, band["scl"])
    return {"ndvi": ndvi_mean, "nbr": nbr_mean, "valid_fraction": valid, "processing_baseline": baseline}


def _fetch_item(url: str) -> dict:
    return request("earth_search", "GET", url, timeout=30, max_attempts=3).response.json()


def pick_scenes(scenes: list, ev, before: bool) -> list:
    """Candidates ordered nearest-first to the event: before the first detection, or after the last."""
    if before:
        return sorted((s for s in scenes if s.acquired_at < ev.first_detected), key=lambda s: s.acquired_at, reverse=True)
    return sorted((s for s in scenes if s.acquired_at > ev.last_detected + timedelta(hours=12)), key=lambda s: s.acquired_at)


def _first_usable(candidates: list, lat: float, lon: float, fetch=_fetch_item, reader=scene_indices):
    for s in candidates[:3]:
        if (s.cloud_cover is not None and s.cloud_cover > MAX_CLOUD) or not s.item_url:
            continue
        idx = reader(fetch(s.item_url), lat, lon)
        if idx["valid_fraction"] >= MIN_VALID_FRACTION and idx["ndvi"] is not None and idx["nbr"] is not None:
            return s, idx
    return None


def _scene_json(s, idx: dict) -> dict:
    return {"item_id": s.item_id, "acquired_at": s.acquired_at.isoformat(), "cloud_cover": s.cloud_cover, **idx}


def analyse_event_imagery(db: Session, ev: ThermalEvent) -> ImageryAnalysis:
    """Compute and store the analysis. Provider errors are recorded as `unavailable` with the reason."""
    scenes = list(db.execute(select(SatelliteObservation).where(SatelliteObservation.event_id == ev.id)).scalars())
    row = ImageryAnalysis(event_id=ev.id, source_id=SOURCE_ID, status="unavailable", window_m=WINDOW_HALF_M * 2,
                          method=METHOD, retrieved_at=datetime.now(UTC))
    try:
        if not scenes:
            row.reason = "No Sentinel-2 scenes stored for this event; run enrichment first."
        else:
            before = _first_usable(pick_scenes(scenes, ev, True), ev.latitude, ev.longitude)
            after = _first_usable(pick_scenes(scenes, ev, False), ev.latitude, ev.longitude)
            if before is None or after is None:
                missing = " and ".join(n for n, v in (("before", before), ("after", after)) if v is None)
                row.reason = (f"No usable clear scene {missing} the event (cloud <= {MAX_CLOUD:.0f}%, at least "
                              f"{MIN_VALID_FRACTION:.0%} valid pixels in the window).")
            else:
                (bs, bi), (a_s, ai) = before, after
                deltas = {k: round(ai[k] - bi[k], 4) for k in ("ndvi", "nbr")}
                row.status, row.finding = "ok", classify_change(deltas["ndvi"], deltas["nbr"])
                row.before_scene, row.after_scene, row.deltas = _scene_json(bs, bi), _scene_json(a_s, ai), deltas
    except ProviderError as exc:
        source_health.record_failure(db, SOURCE_ID, str(exc))
        row.reason = f"Imagery unavailable: {exc.kind}: {exc}"
    db.execute(delete(ImageryAnalysis).where(ImageryAnalysis.event_id == ev.id))
    db.add(row)
    db.flush()
    return row
