"""Unit tests for pure domain logic (no network, no database)."""
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, validate_password_strength, verify_password
from app.gis.geo import bbox_from_string, bearing_deg, compass, destination, haversine_m
from app.integrations.firms import _parse_csv, normalize_confidence, parse_row
from app.integrations.http import ProviderAuthError, ProviderMalformed
from app.integrations.overpass import build_query, classify_facility, classify_land
from app.integrations.sentinel import SceneMetadata, _dedupe_reprocessed
from app.ml.base import SOURCE_CLASSES
from app.ml.rule_cascade import RuleCascadeClassifier
from app.processing.attribution import attribution_score
from app.processing.confidence import QualityResult, assess_data_quality, compute_confidence, display_state
from app.processing.features import FEATURE_NAMES
from app.processing.persistence import classify_persistence

NAN = float("nan")


# --- FIRMS normalization -------------------------------------------------------------------------
VIIRS_ROW = {"latitude": "21.10547", "longitude": "72.64095", "bright_ti4": "340.1", "scan": "0.39", "track": "0.36",
             "acq_date": "2026-09-24", "acq_time": "644", "satellite": "N21", "confidence": "nominal", "version": "2.0NRT",
             "bright_ti5": "299.2", "frp": "12.4", "daynight": "N"}
MODIS_ROW = {"latitude": "23.7", "longitude": "86.4", "brightness": "320.5", "scan": "1.2", "track": "1.1",
             "acq_date": "2026-09-20", "acq_time": "0515", "satellite": "T", "confidence": "82", "version": "6.1NRT",
             "bright_t31": "295.0", "frp": "30.1", "daynight": "D"}


def test_viirs_row_normalized():
    d = parse_row(VIIRS_ROW, "VIIRS_NOAA21_NRT")
    assert d.sensor == "VIIRS" and d.satellite == "NOAA-21"
    assert d.acq_time == "0644"
    assert d.acq_datetime == datetime(2026, 9, 24, 6, 44, tzinfo=UTC)
    assert d.brightness == 340.1 and d.brightness_2 == 299.2
    assert d.confidence_raw == "nominal" and d.confidence_pct == 60.0
    assert d.daynight == "N"


def test_modis_row_normalized():
    d = parse_row(MODIS_ROW, "MODIS_NRT")
    assert d.sensor == "MODIS" and d.satellite == "Terra"
    assert d.confidence_pct == 82.0 and d.brightness == 320.5 and d.brightness_2 == 295.0


@pytest.mark.parametrize("bad, reason", [
    ({**VIIRS_ROW, "latitude": "abc"}, "core field"),
    ({**VIIRS_ROW, "latitude": "95"}, "out of range"),
    ({**VIIRS_ROW, "acq_time": "2575"}, "acq_time"),
])
def test_invalid_rows_rejected(bad, reason):
    with pytest.raises(ValueError, match=reason):
        parse_row(bad, "VIIRS_NOAA21_NRT")


def test_confidence_mapping():
    assert normalize_confidence("VIIRS", "l") == 25.0
    assert normalize_confidence("VIIRS", "high") == 90.0
    assert normalize_confidence("MODIS", "150") is None
    assert normalize_confidence("MODIS", "") is None


def test_csv_parse_filters_bbox_and_collects_rejects():
    header = ",".join(VIIRS_ROW)
    inside = ",".join(VIIRS_ROW.values())
    outside = ",".join({**VIIRS_ROW, "longitude": "120.0"}.values())
    broken = ",".join({**VIIRS_ROW, "acq_date": "not-a-date"}.values())
    good, bad = _parse_csv("\n".join([header, inside, outside, broken]), "VIIRS_NOAA21_NRT", (68, 6, 98, 36))
    assert len(good) == 1 and len(bad) == 1


def test_csv_html_and_auth_errors():
    with pytest.raises(ProviderMalformed):
        _parse_csv("<!DOCTYPE html><html>", "MODIS_NRT", None)
    with pytest.raises(ProviderAuthError):
        _parse_csv("Invalid MAP_KEY.", "MODIS_NRT", None)


# --- geodesy ------------------------------------------------------------------------------------
def test_geodesy_round_trip():
    lat, lon = destination(21.1, 72.6, 45.0, 5000)
    assert haversine_m(21.1, 72.6, lat, lon) == pytest.approx(5000, rel=1e-3)
    assert bearing_deg(21.1, 72.6, lat, lon) == pytest.approx(45.0, abs=0.1)
    assert compass(44) == "NE" and compass(359) == "N"


def test_bbox_validation():
    assert bbox_from_string("68,6,98,36") == (68, 6, 98, 36)
    with pytest.raises(ValueError):
        bbox_from_string("68,36,98,6")


# --- persistence ------------------------------------------------------------------------------------
def _days(n, start=date(2026, 9, 1), step=1):
    return [start + timedelta(days=i * step) for i in range(n)]


def test_persistence_classes():
    persistent = classify_persistence(_days(7), [30, 32, 29, 31, 30, 33, 30], 4, 0, 60)
    assert persistent.persistence_class == "persistent" and persistent.frp_cv < 0.1
    recurring = classify_persistence(_days(3, step=3), [5, 8, 4], 2, 0, 60)
    assert recurring.persistence_class == "recurring" and recurring.longest_gap_days == 2
    transient = classify_persistence(_days(1), [10], 1, 0, 60)
    assert transient.persistence_class == "transient"
    repeat_site = classify_persistence(_days(1), [10], 1, 3, 60)
    assert repeat_site.persistence_class == "persistent"
    assert 0 <= persistent.score <= 1 and persistent.score > recurring.score > transient.score


def test_persistence_flags_short_history():
    m = classify_persistence(_days(8), [1] * 8, 3, 0, 8)
    assert "full 8-day history" in m.rationale


# --- attribution -------------------------------------------------------------------------------------
def test_attribution_distance_decay_and_status():
    near = attribution_score("refinery", 500, 0.5, "operating")
    far = attribution_score("refinery", 5000, 0.5, "operating")
    retired = attribution_score("refinery", 500, 0.5, "retired")
    solar = attribution_score("power_plant_other", 500, 0.5, None)
    assert near > far > 0 and retired < near and solar < near


# --- OSM taxonomy (audit D6) ----------------------------------------------------------------------------
def test_osm_taxonomy():
    assert classify_facility({"man_made": "works"}) == "factory"  # NOT refinery
    assert classify_facility({"man_made": "works", "name": "Jamnagar Refinery"}) == "refinery"
    assert classify_facility({"power": "plant", "plant:source": "coal"}) == "power_plant_coal"
    assert classify_facility({"power": "plant", "name": "Kawas Thermal Power Station"}) == "power_plant_other"
    assert classify_facility({"landuse": "quarry", "resource": "coal"}) == "coal_mine"
    assert classify_facility({"man_made": "flare"}) == "flare_site"
    assert classify_facility({"man_made": "offshore_platform"}) == "oil_gas"
    assert classify_facility({"landuse": "farmland"}) is None
    assert classify_land({"landuse": "farmland"}) == "cropland"
    assert classify_land({"natural": "wood"}) == "forest"


def test_overpass_query_is_bounded_and_uses_bb():
    q = build_query(21.1, 72.6, 10000, 1500, land_points=[(21.1, 72.6), (21.2, 72.7)])
    assert q.count("around:10000,21.10000,72.60000") == 4 and q.count("nwr") == 6  # bounded, light query
    assert '"industrial"~' in q and 'nwr["industrial"](' not in q  # no key-only industrial filter
    assert q.strip().endswith("out tags bb;")  # `center` would be ignored alongside `bb`


# --- satellite ------------------------------------------------------------------------------------------
def test_reprocessed_scenes_deduped():
    t = datetime(2026, 9, 21, 6, 3, tzinfo=UTC)
    mk = lambda i: SceneMetadata("earth-search", "earth_search", "s2", i, "sentinel-2b", t, 10.0, "L2A", None, None, None, {})  # noqa: E731
    out = _dedupe_reprocessed([mk("S2B_42QWK_20260921_0_L2A"), mk("S2B_42QWK_20260921_1_L2A")])
    assert [s.item_id for s in out] == ["S2B_42QWK_20260921_1_L2A"]


# --- classifier -----------------------------------------------------------------------------------------
def _features(**over):
    f = {n: NAN for n in FEATURE_NAMES}
    f.update(frp_max_log=math.log1p(30), observation_count_log=math.log1p(20), sensor_count=3, persistence_score=0.6,
             night_fraction=0.7, recurrence_count=0, month_sin=0, month_cos=1)
    f.update(over)
    return f


def test_rule_flare_near_oil_gas():
    p = RuleCascadeClassifier().predict(_features(dist_oil_gas_km=0.8), {"persistence_class": "persistent", "month": 9, "osm_checked": True})
    assert p.label == "flare" and 0.6 < p.probability <= 0.88
    assert abs(sum(p.probabilities.values()) - 1) < 0.01 and set(p.probabilities) == set(SOURCE_CLASSES)
    assert p.trace and p.contributions


def test_rule_process_heat_capped():
    p = RuleCascadeClassifier().predict(_features(dist_heavy_industry_km=0.5, persistence_score=1.0),
                                        {"persistence_class": "persistent", "month": 9, "osm_checked": True})
    assert p.label == "process_heat" and p.probability <= 0.75


def test_rule_insufficient_signal():
    p = RuleCascadeClassifier().predict(_features(frp_max_log=math.log1p(2), observation_count_log=math.log1p(1)),
                                        {"persistence_class": "transient", "month": 9})
    assert p.label == "unknown"


def test_rule_agri_needs_land_context():
    ctx = {"persistence_class": "transient", "month": 11, "osm_checked": True}
    assert RuleCascadeClassifier().predict(_features(land_cropland=1.0, land_forest=0.0), ctx).label == "agricultural_burn"
    unchecked = RuleCascadeClassifier().predict(_features(), {**ctx, "osm_checked": False})
    assert unchecked.label in ("unknown", "other")


# --- confidence --------------------------------------------------------------------------------------------
GOOD_Q = QualityResult("good", 0.7, [])


def _conf(**over):
    kw = dict(label="flare", probability=0.85, rule_label="flare", gbm_label="flare", persistence_class="persistent",
              attribution_score=0.5, land_support=None, sensor_count=4, satellite_status="ok", best_cloud=5.0,
              weather_ok=True, quality=GOOD_Q)
    kw.update(over)
    return compute_confidence(**kw)


def test_confidence_components_sum_and_high():
    c = _conf()
    assert c.state == "HIGH_CONFIDENCE"
    assert c.score == pytest.approx(sum(x.value * x.weight for x in c.components), abs=1e-3)
    assert abs(sum(x.weight for x in c.components) - 1.0) < 1e-9


def test_confidence_never_confirmed_without_imagery_analysis():
    assert _conf().state != "CONFIRMED"
    assert _conf(swir_confirmed=True).state == "CONFIRMED"


def test_confidence_drops_on_disagreement_and_unknown():
    assert _conf(gbm_label="process_heat").score < _conf().score
    assert _conf(label="unknown", rule_label="unknown", gbm_label=None).state == "INSUFFICIENT_EVIDENCE"
    assert _conf(quality=QualityResult("poor", 0.2, [])).state == "INSUFFICIENT_EVIDENCE"


def test_analyst_overrides_display_state():
    assert display_state("HIGH_CONFIDENCE", "analyst_rejected") == "ANALYST_REJECTED"
    assert display_state("LOW_CONFIDENCE", "escalated") == "UNDER_REVIEW"
    assert display_state("LOW_CONFIDENCE", "unreviewed") == "LOW_CONFIDENCE"


def test_data_quality_grades():
    good = assess_data_quality({"sensor_count": 4, "pixel_area_km2": 0.15, "osm_status": "ok", "facilities_10km": 5,
                                "best_cloud": 5, "satellite_status": "ok", "weather_status": "ok",
                                "history_window_days": 120, "hours_since_last": 3, "data_mode": "live"})
    poor = assess_data_quality({"sensor_count": 1, "pixel_area_km2": 2.0, "osm_status": None, "history_window_days": 2,
                                "hours_since_last": 200, "data_mode": "demo"})
    assert good.grade == "excellent" and poor.grade == "poor"
    assert {f["factor"] for f in good.factors} >= {"sensor_availability", "satellite_cloud", "historical_depth"}


# --- security ---------------------------------------------------------------------------------------------
def test_password_hash_and_policy():
    h = hash_password("Correct-horse-9")
    assert verify_password("Correct-horse-9", h) and not verify_password("wrong", h)
    assert not verify_password("anything", None)
    with pytest.raises(ValueError):
        validate_password_strength("short")
    with pytest.raises(ValueError):
        validate_password_strength("alllowercaseletters")


def test_jwt_round_trip_and_tamper():
    import uuid

    import jwt

    uid, sid = uuid.uuid4(), uuid.uuid4()
    token, _ = create_access_token(uid, "analyst", sid)
    claims = decode_access_token(token)
    assert claims["sub"] == str(uid) and claims["jti"] == str(sid)
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token[:-2] + ("A" if token[-1] != "A" else "B") + token[-1])


# --- consolidation additions ---------------------------------------------------------------------
def test_priority_components_and_tiers():
    from app.processing.priority import compute_priority, tier_for

    strong = compute_priority(frp_max=300, persistence_score=1.0, attribution_score=0.6, confidence_score=1.0, sensor_count=5)
    weak = compute_priority(frp_max=2, persistence_score=0.0, attribution_score=None, confidence_score=0.2, sensor_count=1)
    assert strong.score == 100 and strong.tier == "high"
    assert weak.score < 30 and weak.tier == "low"
    assert [c["name"] for c in strong.components] == [
        "thermal_intensity", "persistence", "industrial_proximity", "classification_confidence", "sensor_corroboration"]
    assert all(0 <= c["points"] <= c["max"] == 20 for c in strong.components + weak.components)
    assert "not a risk" in strong.as_dict()["note"]
    assert (tier_for(70), tier_for(69), tier_for(50), tier_for(30), tier_for(0)) == ("high", "elevated", "elevated", "routine", "low")


def test_search_coordinate_parsing():
    from app.api.v1.search import parse_coordinates

    assert parse_coordinates("21.10, 72.64") == (21.10, 72.64)
    assert parse_coordinates("21.1 72.6") == (21.1, 72.6)
    assert parse_coordinates("-12.5,-45") == (-12.5, -45.0)
    assert parse_coordinates("95, 72") is None
    assert parse_coordinates("Hazira") is None


def test_facility_tiles_cover_attribution_radius():
    from app.services.facility_sync import tile_key, tiles_around

    assert tile_key(21.1, 72.6) == "21:72"
    assert tile_key(-0.5, -0.5) == "-1:-1"
    assert tiles_around(21.5, 72.5) == {"21:72"}  # tile interior: one tile
    assert tiles_around(21.95, 72.95) == {"21:72", "22:72", "21:73", "22:73"}  # corner: neighbours needed


def test_overpass_split_queries():
    from app.integrations.overpass import build_facility_tile_query, build_land_query

    tile = build_facility_tile_query(21, 72, 22, 73)
    land = build_land_query([(21.1, 72.6)], 1500)
    assert tile.count("nwr") == 4 and "farmland" not in tile
    assert land.count("nwr") == 2 and "power" not in land


def test_alert_cooldown_window():
    from datetime import UTC, datetime, timedelta

    from app.models.workflow import AlertRule
    from app.services.alerts import in_cooldown

    now = datetime.now(UTC)
    assert not in_cooldown(AlertRule(cooldown_minutes=0, last_notified_at=now), now)
    assert not in_cooldown(AlertRule(cooldown_minutes=60, last_notified_at=None), now)
    assert in_cooldown(AlertRule(cooldown_minutes=60, last_notified_at=now - timedelta(minutes=10)), now)
    assert not in_cooldown(AlertRule(cooldown_minutes=60, last_notified_at=now - timedelta(minutes=61)), now)


def test_smtp_user_alias(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("SMTP_USER", "ops-mailer")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    assert Settings().smtp_username == "ops-mailer"


def test_rate_limit_is_per_token_not_per_ip(monkeypatch):
    """Analysts behind one NAT must not share a bucket; anonymous traffic stays per-IP."""
    from fastapi.testclient import TestClient

    from app.core import middleware
    from app.main import app

    monkeypatch.setattr(middleware.settings, "rate_limit_per_minute", 3)
    monkeypatch.setattr(middleware, "_limiter", middleware._FixedWindow())
    c = TestClient(app)
    codes = [c.get("/api/v1/events").status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]  # anonymous: shared IP bucket exhausted
    tok_a = {"Authorization": "Bearer " + "a" * 60}
    tok_b = {"Authorization": "Bearer " + "b" * 60}
    assert [c.get("/api/v1/events", headers=tok_a).status_code for _ in range(3)] == [401, 401, 401]
    assert c.get("/api/v1/events", headers=tok_a).status_code == 429
    assert c.get("/api/v1/events", headers=tok_b).status_code == 401  # separate bucket, still authenticated-checked


def test_env_templates_have_no_inline_comments_on_blank_values():
    """A copied template must parse to empty values, not comment text (a blank key with an inline
    comment made Sentry, SMTP, VAPID and Copernicus look configured)."""
    from pathlib import Path

    from dotenv import dotenv_values

    root = Path(__file__).resolve().parents[2]
    templates = sorted(root.glob(".env*.example"))
    assert len(templates) == 3
    for template in templates:
        polluted = [k for k, v in dotenv_values(template).items() if v and v.lstrip().startswith("#")]
        assert polluted == [], f"{template.name}: {polluted}"


def test_firms_backfill_windows_respect_the_5_day_api_limit():
    from app.integrations.firms import MAX_DAY_RANGE, date_chunks

    assert MAX_DAY_RANGE == 5
    w = date_chunks(date(2025, 7, 1), 12)
    assert w == [(date(2025, 7, 1), 5), (date(2025, 7, 6), 5), (date(2025, 7, 11), 2)]
    year = date_chunks(date(2025, 7, 1), 365)
    assert len(year) == 73 and sum(n for _, n in year) == 365 and all(1 <= n <= 5 for _, n in year)
    assert year[-1][0] + timedelta(days=year[-1][1] - 1) == date(2026, 6, 30)
    with pytest.raises(ValueError):
        date_chunks(date(2025, 7, 1), 0)


def test_tests_never_see_real_provider_credentials():
    """conftest blanks provider credentials, so a developer's local .env can never make tests send email,
    push notifications or keyed API calls."""
    from app.core.config import Settings

    s = Settings()
    assert not s.smtp_host and not s.smtp_password and not s.firms_key and not s.copernicus_client_secret
    assert not s.vapid_private_key and not s.sentry_dsn


def test_production_settings_fail_closed(monkeypatch):
    """Outside development the API refuses the dev secret, the dev database password and localhost-only CORS."""
    from pydantic import ValidationError

    from app.core.config import Settings

    good = {"environment": "production", "secret_key": "s" * 48,
            "database_url": "postgresql+psycopg://tt:real-password@db.internal:5432/tt", "cors_origins": "https://thermaltrace.example.org"}
    assert Settings(**good).environment == "production"
    for bad in ({"secret_key": "short"}, {"database_url": "postgresql+psycopg://thermaltrace:thermaltrace_dev_only@db:5432/tt"},
                {"cors_origins": "http://localhost:5173"}, {"cors_origins": "http://127.0.0.1:5173,http://app.localhost"}):
        with pytest.raises(ValidationError):
            Settings(**{**good, **bad})
    assert Settings(environment="development").environment == "development"  # dev defaults still work locally


def test_relative_datasets_dir_resolves_from_the_repository():
    from pathlib import Path

    from app.core.config import REPO_DIR, Settings

    s = Settings(datasets_dir=Path("./data/datasets"))
    assert s.datasets_dir == (REPO_DIR / "data" / "datasets").resolve()
    absolute = Path(REPO_DIR.anchor) / "srv" / "data"
    assert Settings(datasets_dir=absolute).datasets_dir == absolute


def test_sentry_initialises_with_the_installed_web_stack():
    """sentry-sdk 2.19 raised ImportError at init under Starlette 1.x, so setting SENTRY_DSN crashed the API.
    The DSN here is a syntactically valid placeholder; nothing is sent."""
    import sentry_sdk

    sentry_sdk.init(dsn="https://public@o0.ingest.sentry.io/0", default_integrations=True, send_default_pii=False)
    try:
        assert sentry_sdk.get_client().is_active()
    finally:
        sentry_sdk.get_client().close(timeout=0)
        sentry_sdk.init()  # back to a disabled client


def test_geonames_parsing_keeps_region_places_and_names_states():
    from app.services.places import parse_admin1, parse_cities

    admin1 = parse_admin1("IN.36\tJharkhand\tJharkhand\t1444365\nPK.04\tPunjab\tPunjab\t1168\nbad line\n")
    assert admin1 == {"IN.36": "Jharkhand", "PK.04": "Punjab"}
    cols = lambda i, n, lat, lon, cc, a1, pop: "\t".join([str(i), n, n, "", str(lat), str(lon), "P", "PPL", cc, "", a1, "", "", "", str(pop)])  # noqa: E731
    tsv = "\n".join([cols(1, "Dhanbad", 23.79, 86.43, "IN", "36", 1162472), cols(2, "Paris", 48.85, 2.35, "FR", "11", 2138551),
                     cols(3, "Alahabad", 30.9, 74.1, "PK", "04", 900), cols(4, "Ghost", "x", 80, "IN", "36", 5)])
    rows = parse_cities(tsv, admin1, (68.0, 6.5, 97.5, 35.7))
    assert [r["name"] for r in rows] == ["Dhanbad", "Alahabad"]  # Paris is outside the region; the bad row is skipped
    assert rows[0]["admin1"] == "Jharkhand" and rows[0]["population"] == 1162472 and rows[1]["country_code"] == "PK"
