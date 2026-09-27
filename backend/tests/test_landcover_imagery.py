"""Raster land cover, Sentinel-2 spectral change, rule-cascade land fallback, facility-activity alert
conditions. No network: rasters are written to a temp GeoTIFF, scene reads are injected."""
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.integrations import raster
from app.ml.rule_cascade import RASTER_P_CAP, RuleCascadeClassifier
from app.processing.evidence import _imagery_items, _landcover_items
from app.services import imagery
from app.services.alerts import repeat_and_increase_ok

NAN = float("nan")


# --- raster helpers -------------------------------------------------------------------------------
def test_worldcover_tile_url_uses_the_south_west_corner_of_3_degree_tiles():
    assert raster.worldcover_tile_url(23.79, 86.43).endswith("_N21E084_Map.tif")
    assert raster.worldcover_tile_url(-0.5, -45.1).endswith("_S03W048_Map.tif")


def test_landcover_fractions_ignore_nodata_and_name_classes():
    window = np.array([[40, 40, 40, 50], [10, 0, 0, 0]], dtype="float32")
    res = raster.landcover_fractions(window)
    assert res["fractions"] == {"tree_cover": 0.2, "cropland": 0.6, "built_up": 0.2}
    assert res["dominant"] == "cropland" and res["valid_fraction"] == 0.625
    assert raster.landcover_fractions(np.zeros((3, 3)))["dominant"] is None


def test_group_fractions_sums_natural_vegetation():
    g = raster.group_fractions({"tree_cover": 0.3, "shrubland": 0.1, "grassland": 0.1, "cropland": 0.4, "built_up": 0.1})
    assert g == {"vegetation": 0.5, "cropland": 0.4, "built_up": 0.1, "bare": 0.0, "water": 0.0}


def test_reflectance_applies_the_baseline_4_offset_and_masks_nodata():
    dn = np.array([0, 1000, 3000], dtype="float32")
    old = raster.reflectance(dn, 3.0)
    new = raster.reflectance(dn, 5.12)
    assert math.isnan(old[0]) and math.isnan(new[0])
    assert old[2] == pytest.approx(0.30) and new[2] == pytest.approx(0.20) and new[1] == 0.0


def test_normalised_difference_and_scl_masking():
    nir, red = np.array([0.5, 0.0, 0.4]), np.array([0.1, 0.0, 0.4])
    nd = raster.normalised_difference(nir, red)
    assert nd[0] == pytest.approx(0.6667, abs=1e-4) and math.isnan(nd[1]) and nd[2] == 0.0
    scl = np.array([4, 4, 9])  # third pixel is cloud
    mean, share = raster.masked_mean(nd, scl)
    assert mean == pytest.approx(0.6667, abs=1e-4) and share == pytest.approx(1 / 3, abs=1e-4)
    assert raster.masked_mean(nd, np.array([9, 9, 9])) == (None, 0.0)


def test_read_window_on_a_local_geotiff(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    path = tmp_path / "wc.tif"
    data = np.full((200, 200), 40, dtype="uint8")
    data[:, 100:] = 50  # east half built-up
    with rasterio.open(path, "w", driver="GTiff", width=200, height=200, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(86.0, 24.0, 0.0001, 0.0001)) as ds:
        ds.write(data, 1)
    res = raster.sample_worldcover(23.99, 86.01, 300.0, href=str(path))
    assert set(res["fractions"]) == {"cropland", "built_up"}
    assert res["fractions"]["cropland"] == pytest.approx(0.5, abs=0.1) and res["valid_fraction"] == 1.0


# --- spectral change ------------------------------------------------------------------------------------
def test_classify_change_needs_both_indices_for_consistent_loss():
    # changes are after minus before; burning lowers NDVI and NBR (dNBR = before - after >= 0.10)
    assert imagery.classify_change(-0.2, -0.25) == "vegetation_loss_consistent"
    assert imagery.classify_change(-0.2, -0.02) == "partial_change"
    assert imagery.classify_change(0.01, -0.15) == "partial_change"
    assert imagery.classify_change(0.01, 0.0) == "no_change_detected"


def test_vegetation_green_up_is_not_a_burn_signal():
    # a real case (TT-2026-325802, May -> September): NDVI +0.12, NBR +0.24 after the monsoon
    assert imagery.classify_change(0.12, 0.24) == "no_change_detected"
    assert imagery.classify_change(-0.2, 0.25) == "partial_change"  # NDVI loss alone, NBR rose


def _scene(item, days, cloud=5.0):
    base = datetime(2026, 9, 20, tzinfo=UTC)
    return SimpleNamespace(item_id=item, acquired_at=base + timedelta(days=days), cloud_cover=cloud, item_url=f"https://x/{item}")


def test_scene_choice_brackets_the_event_nearest_first():
    ev = SimpleNamespace(first_detected=datetime(2026, 9, 20, 8, tzinfo=UTC), last_detected=datetime(2026, 9, 21, 8, tzinfo=UTC))
    scenes = [_scene("b-far", -10), _scene("b-near", -2), _scene("during", 1), _scene("a-near", 5), _scene("a-far", 15)]
    assert [s.item_id for s in imagery.pick_scenes(scenes, ev, True)] == ["b-near", "b-far"]
    assert [s.item_id for s in imagery.pick_scenes(scenes, ev, False)] == ["a-near", "a-far"]


def test_first_usable_skips_cloudy_and_mostly_masked_scenes():
    reads = {"https://x/masked": {"ndvi": 0.7, "nbr": 0.5, "valid_fraction": 0.2},
             "https://x/good": {"ndvi": 0.6, "nbr": 0.4, "valid_fraction": 0.9}}
    got = imagery._first_usable([_scene("cloudy", 1, cloud=80), _scene("masked", 2), _scene("good", 3)], 0, 0,
                                fetch=lambda url: url, reader=lambda item, lat, lon: reads[item])
    assert got[0].item_id == "good"
    assert imagery._first_usable([_scene("cloudy", 1, cloud=80)], 0, 0, fetch=lambda u: u, reader=None) is None


# --- evidence wording: missing is never negative -----------------------------------------------------
def test_unavailable_imagery_is_missing_evidence_not_no_change():
    items = _imagery_items({"status": "unavailable", "reason": "No usable clear scene after the event.", "retrieved_at": None},
                           "wildfire")
    assert items[0].direction == "missing" and "could not be computed" in items[0].statement


def test_spectral_loss_supports_vegetation_classes_only():
    ia = {"status": "ok", "finding": "vegetation_loss_consistent", "retrieved_at": None, "method": {},
          "deltas": {"ndvi": -0.3, "nbr": 0.35},
          "before_scene": {"ndvi": 0.7, "nbr": 0.5, "acquired_at": "2026-09-10T05:00:00"},
          "after_scene": {"ndvi": 0.4, "nbr": 0.15, "acquired_at": "2026-09-30T05:00:00"}}
    assert _imagery_items(ia, "agricultural_burn")[0].direction == "supports"
    assert _imagery_items(ia, "process_heat")[0].direction == "neutral"
    assert "not proof" in _imagery_items(ia, "wildfire")[0].statement


def test_landcover_evidence_is_context_with_honest_absence():
    assert _landcover_items(None, None, "wildfire")[0].direction == "missing"
    assert "offshore" in _landcover_items(None, "ok", "wildfire")[0].statement
    wc = {"fractions": {"cropland": 0.9, "tree_cover": 0.1}, "dominant": "cropland", "product": "ESA WorldCover 10 m 2021 v200",
          "window_m": 1500, "retrieved_at": None}
    assert _landcover_items(wc, "ok", "agricultural_burn")[0].direction == "supports"
    assert _landcover_items(wc, "ok", "wildfire")[0].direction == "neutral"
    built = {**wc, "fractions": {"built_up": 0.95, "water": 0.05}, "dominant": "built_up"}
    assert _landcover_items(built, "ok", "agricultural_burn")[0].direction == "contradicts"


# --- rule cascade: raster fallback -------------------------------------------------------------------------
def _features(**over):
    f = {"frp_max_log": math.log1p(20), "observation_count_log": math.log1p(3), "night_fraction": 0.0, "persistence_score": 0.1,
         "sensor_count": 2.0, "dist_oil_gas_km": NAN, "dist_heavy_industry_km": NAN, "dist_mine_km": NAN,
         "land_cropland": NAN, "land_forest": NAN, "lc_cropland_frac": NAN, "lc_vegetation_frac": NAN, "lc_built_up_frac": NAN}
    return {**f, **over}


def test_raster_cropland_majority_gives_a_capped_agricultural_label():
    p = RuleCascadeClassifier().predict(_features(lc_cropland_frac=0.95, lc_vegetation_frac=0.02, lc_built_up_frac=0.0),
                                        {"persistence_class": "transient", "month": 11, "osm_checked": False})
    assert p.label == "agricultural_burn" and p.probability == RASTER_P_CAP
    assert any("WorldCover" in t for t in p.trace)


def test_raster_fallback_is_not_used_for_built_up_areas_or_when_osm_was_checked():
    built = RuleCascadeClassifier().predict(_features(lc_cropland_frac=0.55, lc_vegetation_frac=0.0, lc_built_up_frac=0.4),
                                            {"persistence_class": "transient", "month": 11, "osm_checked": False})
    assert built.label == "unknown" and any("built-up" in t for t in built.trace)
    osm = RuleCascadeClassifier().predict(_features(land_cropland=0.0, land_forest=0.0, lc_cropland_frac=0.95),
                                          {"persistence_class": "transient", "month": 11, "osm_checked": True})
    assert osm.label == "unknown"


def test_raster_vegetation_majority_gives_a_capped_wildfire_label():
    p = RuleCascadeClassifier().predict(_features(lc_cropland_frac=0.05, lc_vegetation_frac=0.8, lc_built_up_frac=0.01),
                                        {"persistence_class": "transient", "month": 4, "osm_checked": False})
    assert p.label == "wildfire" and p.probability <= RASTER_P_CAP


# --- facility-activity alert conditions --------------------------------------------------------------------
def test_repeat_and_increase_conditions():
    rule = SimpleNamespace(min_repeat_events=None, activity_increase=False)
    assert repeat_and_increase_ok(rule, 0, 0, 0)
    rule.min_repeat_events = 3
    assert not repeat_and_increase_ok(rule, 2, 0, 0) and repeat_and_increase_ok(rule, 3, 0, 0)
    rule.min_repeat_events, rule.activity_increase = None, True
    assert not repeat_and_increase_ok(rule, 5, 2, 0)   # two new events are not a surge
    assert not repeat_and_increase_ok(rule, 9, 4, 3)   # not doubled
    assert repeat_and_increase_ok(rule, 9, 4, 2)


def test_every_job_handler_is_served_by_a_worker_lane():
    """Production runs one worker per lane; a handler missing from every lane would queue forever."""
    from app.workers.queue import LANES
    from app.workers.tasks import HANDLERS, SCHEDULE

    served = set().union(*LANES.values())
    assert set(HANDLERS) <= served, set(HANDLERS) - served
    assert set(SCHEDULE) <= set(HANDLERS)


def test_dark_surface_yields_no_spectral_finding(monkeypatch):
    """Real case (TT-2026-101331, a coal plant yard): NIR ~0.03 in both scenes; NDVI/NBR there are noise."""
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    ev = SimpleNamespace(id=1, public_id="TT-x", latitude=22.06, longitude=82.60, first_detected=datetime(2026, 2, 5, tzinfo=UTC),
                         last_detected=datetime(2026, 2, 10, tzinfo=UTC), enrichment_state={"satellite": {"status": "ok"}})
    scenes = [SimpleNamespace(acquired_at=ev.first_detected - timedelta(days=2), cloud_cover=0.0, item_url="b", item_id="b"),
              SimpleNamespace(acquired_at=ev.last_detected + timedelta(days=3), cloud_cover=0.2, item_url="a", item_id="a")]
    idx = {"b": {"ndvi": 0.79, "nbr": -0.30, "valid_fraction": 0.54, "processing_baseline": "05.11", "nir_reflectance": 0.029},
           "a": {"ndvi": 0.79, "nbr": -0.38, "valid_fraction": 0.52, "processing_baseline": "05.12", "nir_reflectance": 0.031}}
    added = []
    db = SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(scalars=lambda: scenes), add=added.append, flush=lambda: None)
    monkeypatch.setattr(imagery, "_fetch_item", lambda url: url)
    monkeypatch.setattr(imagery, "scene_indices", lambda item, lat, lon: idx[item])
    row = imagery.analyse_event_imagery(db, ev)
    assert row.status == "unavailable" and row.finding is None and row.deltas is None
    assert "too dark" in row.reason and "0.03 before" in row.reason
    assert row.before_scene["item_id"] == "b"  # what was read stays visible
