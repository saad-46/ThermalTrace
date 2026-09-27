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
# Below this mean NIR reflectance the window is water, coal, ash or deep shadow: NDVI and NBR become ratios of
# near-zero values (noise), so no finding is reported (vegetation reflects ~0.3 in NIR, bare soil ~0.2).
MIN_NIR_REFLECTANCE = 0.05
# Thresholds follow common burn-severity practice: dNBR = NBR_before - NBR_after >= 0.10 is the lowest "burned" class
# (USGS / UN-SPIDER) - burning lowers NBR; dNDVI <= -0.10 marks a meaningful vegetation decrease. Stored deltas are
# after minus before for both indices, so the burn signal is an NBR change <= -0.10. They flag a change worth a look.
DNBR_THRESHOLD = 0.10
DNDVI_THRESHOLD = -0.10
METHOD = {
    "indices": {"ndvi": "(NIR B08 - Red B04) / (NIR + Red)", "nbr": "(NIR B8A - SWIR B12) / (NIR + SWIR)"},
    "window_m": WINDOW_HALF_M * 2, "resolution_m": 20, "mask": "SCL classes 4, 5, 7 only (cloud, shadow, cirrus, water, snow excluded)",
    "reflectance": "DN/10000, minus a 1000 DN offset for processing baseline >= 04.00",
    "thresholds": {"dnbr": DNBR_THRESHOLD, "dndvi": DNDVI_THRESHOLD},
    "deltas": "after minus before; burn-consistent when NDVI change <= dndvi and NBR change <= -dnbr (dNBR = before - after)",
    "scene_choice": f"latest scene before the first detection and earliest after the last detection, cloud <= {MAX_CLOUD:.0f}%",
    "dark_surface": f"no finding when mean NIR (B8A) reflectance in the window is below {MIN_NIR_REFLECTANCE} in either scene",
}
REQUIRED_ASSETS = ("red", "nir", "nir08", "swir22", "scl")


def classify_change(ndvi_change: float | None, nbr_change: float | None) -> str:
    """Descriptive finding from the two changes (after minus before). Burning lowers both indices: a vegetation
    green-up (both rising, e.g. after the monsoon) is not a burn signal."""
    ndvi_hit = ndvi_change is not None and ndvi_change <= DNDVI_THRESHOLD
    nbr_hit = nbr_change is not None and -nbr_change >= DNBR_THRESHOLD  # dNBR = before - after
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
    nir_mean, _ = raster.masked_mean(refl["nir08"], band["scl"])
    return {"ndvi": ndvi_mean, "nbr": nbr_mean, "valid_fraction": valid, "processing_baseline": baseline,
            "nir_reflectance": None if nir_mean is None else round(nir_mean, 4)}


def _fetch_item(url: str) -> dict:
    return request("earth_search", "GET", url, timeout=30, max_attempts=3).response.json()


def pick_scenes(scenes: list, ev, before: bool) -> list:
    """Candidates ordered nearest-first to the event: before the first detection, or after the last."""
    if before:
        return sorted((s for s in scenes if s.acquired_at < ev.first_detected), key=lambda s: s.acquired_at, reverse=True)
    return sorted((s for s in scenes if s.acquired_at > ev.last_detected + timedelta(hours=12)), key=lambda s: s.acquired_at)


def readiness(ev, scenes: list) -> tuple[bool, str | None]:
    """Whether a before/after comparison can be attempted from the stored scenes, and if not, why.
    Computing without a scene on both sides of the event would produce nothing, so it is not offered."""
    searched = (ev.enrichment_state or {}).get("satellite")
    if not scenes:
        if not searched:
            return False, "Sentinel-2 has not been searched for this event yet."
        if searched.get("status") == "failed":
            return False, "The last Sentinel-2 search failed; search again."
        return False, (f"No suitable Sentinel-2 scene was available for this event (cloud <= "
                       f"{searched.get('max_cloud', MAX_CLOUD):.0f}%).")
    clear = [s for s in scenes if s.cloud_cover is None or s.cloud_cover <= MAX_CLOUD]
    before = [s for s in clear if s.acquired_at < ev.first_detected]
    after = [s for s in clear if s.acquired_at > ev.last_detected + timedelta(hours=12)]
    if not before or not after:
        side = "before the first detection" if not before else "after the last detection"
        return False, (f"Before/after analysis cannot be completed: no Sentinel-2 scene with cloud <= {MAX_CLOUD:.0f}% "
                       f"{side} yet.")
    return True, None


def _first_usable(candidates: list, lat: float, lon: float, fetch=None, reader=None, tried: list | None = None):
    """The nearest scene whose event window is clear enough. `tried` collects each scene's clear-pixel share."""
    fetch, reader = fetch or _fetch_item, reader or scene_indices  # resolved per call (patchable)
    for s in candidates[:3]:
        if (s.cloud_cover is not None and s.cloud_cover > MAX_CLOUD) or not s.item_url:
            continue
        idx = reader(fetch(s.item_url), lat, lon)
        if tried is not None:
            tried.append(idx["valid_fraction"])
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
        ready, why = readiness(ev, scenes)
        if not ready:
            row.reason = why
        else:
            tried_b: list[float] = []
            tried_a: list[float] = []
            before = _first_usable(pick_scenes(scenes, ev, True), ev.latitude, ev.longitude, tried=tried_b)
            after = _first_usable(pick_scenes(scenes, ev, False), ev.latitude, ev.longitude, tried=tried_a)
            if before is None or after is None:
                missing = [(n, t) for n, v, t in (("before", before, tried_b), ("after", after, tried_a)) if v is None]
                detail = "; ".join(f"best {n}: {max(t):.0%} clear" if t else f"{n}: no scene to read" for n, t in missing)
                row.reason = (f"The {WINDOW_HALF_M * 2 / 1000:.0f} km window around the event is cloud- or shadow-covered in "
                              f"the nearest scenes {' and '.join(n for n, _ in missing)} the event ({detail}; "
                              f"at least {MIN_VALID_FRACTION:.0%} clear pixels needed).")
            else:
                (bs, bi), (a_s, ai) = before, after
                row.before_scene, row.after_scene = _scene_json(bs, bi), _scene_json(a_s, ai)
                dark = [(n, i["nir_reflectance"]) for n, i in (("before", bi), ("after", ai))
                        if i.get("nir_reflectance") is not None and i["nir_reflectance"] < MIN_NIR_REFLECTANCE]
                if dark:
                    row.reason = ("The surface in the window is too dark for NDVI/NBR to be meaningful (mean NIR reflectance "
                                  + ", ".join(f"{v:.2f} {n}" for n, v in dark)
                                  + "; typical of water, coal, ash or deep shadow). No spectral finding is reported.")
                else:
                    deltas = {k: round(ai[k] - bi[k], 4) for k in ("ndvi", "nbr")}
                    row.status, row.finding, row.deltas = "ok", classify_change(deltas["ndvi"], deltas["nbr"]), deltas
    except ProviderError as exc:
        logger.warning("imagery analysis for %s failed: %s", ev.public_id, exc)
        source_health.record_failure(db, SOURCE_ID, str(exc))
        row.reason = (f"Sentinel-2 imagery could not be read ({source_health.error_category(exc).replace('_', ' ')}); "
                      "try again later.")
    db.execute(delete(ImageryAnalysis).where(ImageryAnalysis.event_id == ev.id))
    db.add(row)
    db.flush()
    return row
