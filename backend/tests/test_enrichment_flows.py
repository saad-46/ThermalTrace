"""On-demand evidence for an event: Sentinel-2 search, NDVI/NBR readiness, weather, and facility details.

Providers are replaced at their client boundary (no network); everything else (API, queue, worker handler, database)
runs for real against the disposable PostGIS test database."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.test_integration import _facility, _flare_site, _ingest

pytestmark = pytest.mark.integration


def _event(db):
    """One processed event (a persistent flare-like site) next to a facility; returns (public_id, event row)."""
    from app.processing.pipeline import process_new_detections

    fac = _facility(db, "Test Refinery", "refinery", 22.352, 69.853)
    _ingest(db, _flare_site(5))
    process_new_detections(db)
    db.commit()
    row = db.execute(text("SELECT id, public_id, latitude, longitude, first_detected, last_detected FROM thermal_events LIMIT 1")).one()
    return row, fac


def _run_jobs(db, lane="interactive"):
    """Claim and run every queued job of a lane exactly as the worker does."""
    from app.workers import queue
    from app.workers.run import run_one

    done = []
    while (job := queue.claim(db, "test-worker", queue.LANES[lane])) is not None:
        run_one(db, job)
        db.refresh(job)
        done.append(job)
    return done


def _scene(item, when, cloud=10.0):
    from app.integrations.sentinel import SceneMetadata

    return SceneMetadata(provider="earth-search", source_id="earth_search", collection="sentinel-2-l2a", item_id=item,
                         platform="sentinel-2a", acquired_at=when, cloud_cover=cloud, processing_level="L2A", thumbnail_url=None,
                         item_url=f"https://example.invalid/{item}", bbox=None, assets={})


# ------------------------------------------------------------------ job registration
def test_every_handler_is_consumed_by_a_worker_lane_and_context_backfill_is_scheduled():
    from app.workers.queue import LANES
    from app.workers.tasks import HANDLERS, SCHEDULE

    served = set().union(*LANES.values())
    assert set(HANDLERS) <= served, f"no worker lane consumes: {set(HANDLERS) - served}"
    assert "enrich_event" in LANES["interactive"] and "imagery_analysis" in LANES["interactive"]
    assert "context_backfill" in LANES["bulk"] and "context_backfill" in SCHEDULE


# ------------------------------------------------------------------ Sentinel-2
def test_satellite_search_is_queued_run_by_the_worker_and_stored_with_before_after_counts(client, db, auth_headers, monkeypatch):
    from app.services import enrichment

    ev, _ = _event(db)
    calls = []

    def search(self, lat, lon, start, end, max_cloud=None, limit=20, newest_first=True):
        calls.append(dict(lat=lat, lon=lon, start=start, end=end, newest_first=newest_first))
        if end <= ev.first_detected:  # the window before the event
            return [_scene("S2A_before", ev.first_detected - timedelta(days=3))], 120.0
        return [_scene("S2A_after", ev.last_detected + timedelta(days=2))], 120.0

    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", search)
    h = auth_headers("analyst")
    r = client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["satellite"]}, headers=h)
    assert r.status_code == 202 and r.json()["steps"] == ["satellite"]
    bundle = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    assert [(j["kind"], j["steps"], j["status"]) for j in bundle["jobs"]] == [("enrich_event", ["satellite"], "queued")]

    jobs = _run_jobs(db)
    assert [j.status for j in jobs] == ["succeeded"]
    # two windows at the event's own location: the newest scenes before it, and the oldest from its first detection on
    # (a single newest-first search over months returns only recent scenes for an older event)
    before_call, after_call = calls
    assert (before_call["lat"], before_call["lon"]) == (pytest.approx(ev.latitude), pytest.approx(ev.longitude))
    assert before_call["start"] == ev.first_detected - timedelta(days=enrichment.SATELLITE_LOOKBACK_DAYS)
    assert before_call["end"] == ev.first_detected and before_call["newest_first"] is True
    assert after_call["start"] == ev.first_detected and after_call["newest_first"] is False
    bundle = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    st = bundle["enrichment_state"]["satellite"]
    assert st["status"] == "ok" and st["scenes"] == 2 and st["before"] == 1 and st["after"] == 1
    assert {s["relation"] for s in bundle["satellite"]} == {"before", "after"}
    assert bundle["imagery_readiness"] == {"ready": True, "reason": None, "max_cloud": 40.0}
    assert bundle["jobs"][0]["status"] == "succeeded"
    # other steps were not run for a satellite-only request
    assert "weather" not in bundle["enrichment_state"]


def test_satellite_no_scenes_and_provider_failure_are_different_states(client, db, auth_headers, monkeypatch):
    from app.integrations.http import ProviderServerError
    from app.services import enrichment

    ev, _ = _event(db)
    h = auth_headers("analyst")
    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", lambda self, *a, **k: ([], 80.0))
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["satellite"]}, headers=h)
    _run_jobs(db)
    b = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    assert b["enrichment_state"]["satellite"]["status"] == "ok" and b["enrichment_state"]["satellite"]["scenes"] == 0
    assert b["imagery_readiness"]["ready"] is False and "No suitable Sentinel-2 scene" in b["imagery_readiness"]["reason"]

    def down(self, *a, **k):
        raise ProviderServerError("earth_search", "HTTP 503", status=503)

    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", down)
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["satellite"]}, headers=h)
    _run_jobs(db)
    b = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    st = b["enrichment_state"]["satellite"]
    assert st["status"] == "failed" and st["category"] == "service_unavailable"
    assert "try again" in b["imagery_readiness"]["reason"] or "failed" in b["imagery_readiness"]["reason"]
    src = db.execute(text("SELECT last_failure_at, last_error FROM data_sources WHERE id = 'earth_search'")).one()
    assert src.last_failure_at is not None


def test_imagery_analysis_is_refused_without_a_clear_scene_on_both_sides(client, db, auth_headers, monkeypatch):
    from app.services import enrichment

    ev, _ = _event(db)
    h = auth_headers("analyst")
    r = client.post(f"/api/v1/events/{ev.public_id}/imagery-analysis", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "imagery_not_ready"
    assert "not been searched" in r.json()["error"]["message"]
    # scenes only before the event, and a cloudy one after: still nothing to compare
    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", lambda self, *a, **k: (
        [_scene("before", ev.first_detected - timedelta(days=5)), _scene("cloudy_after", ev.last_detected + timedelta(days=2), cloud=85)], 50.0))
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["satellite"]}, headers=h)
    _run_jobs(db)
    r = client.post(f"/api/v1/events/{ev.public_id}/imagery-analysis", headers=h)
    assert r.status_code == 409 and "after the last detection" in r.json()["error"]["message"]
    assert db.execute(text("SELECT count(*) FROM jobs WHERE kind = 'imagery_analysis'")).scalar() == 0


def test_imagery_analysis_job_stores_a_result_computed_from_the_scene_bands(client, db, auth_headers, monkeypatch):
    from app.services import enrichment, imagery

    ev, _ = _event(db)
    h = auth_headers("analyst")
    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", lambda self, *a, **k: (
        [_scene("before", ev.first_detected - timedelta(days=5)), _scene("after", ev.last_detected + timedelta(days=3))], 50.0))
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["satellite"]}, headers=h)
    _run_jobs(db)
    bands = {"before": {"ndvi": 0.62, "nbr": 0.41, "valid_fraction": 0.9, "processing_baseline": "05.11"},
             "after": {"ndvi": 0.31, "nbr": 0.12, "valid_fraction": 0.8, "processing_baseline": "05.11"}}
    monkeypatch.setattr(imagery, "_fetch_item", lambda url: url.rsplit("/", 1)[1])
    monkeypatch.setattr(imagery, "scene_indices", lambda item, lat, lon: bands[item])
    assert client.post(f"/api/v1/events/{ev.public_id}/imagery-analysis", headers=h).status_code == 202
    assert [j.status for j in _run_jobs(db)] == ["succeeded"]
    ia = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()["imagery_analysis"]
    assert ia["status"] == "ok" and ia["finding"] == "vegetation_loss_consistent"
    assert ia["deltas"] == {"ndvi": -0.31, "nbr": -0.29}
    assert ia["before_scene"]["item_id"] == "before" and ia["after_scene"]["item_id"] == "after"


def test_unknown_steps_are_rejected_and_demo_sessions_cannot_request(client, db, auth_headers, monkeypatch):
    from tests.test_integration import _explore

    ev, _ = _event(db)
    r = client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather", "bogus"]}, headers=auth_headers("analyst"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_steps"
    demo, _ = _explore(client, monkeypatch)
    r = client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather"]}, headers=demo)
    assert r.status_code == 403 and r.json()["error"]["code"] == "demo_read_only"
    assert client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather"]}, headers=auth_headers("viewer")).status_code == 403


# ------------------------------------------------------------------ weather
class _Res:
    def __init__(self, payload):
        self.response = SimpleNamespace(json=lambda: payload)
        self.latency_ms = 42.0


def _hourly(hour: str, temp=31.2, wind=18.0):
    return {"hourly": {"time": [hour], "temperature_2m": [temp], "relative_humidity_2m": [40], "wind_speed_10m": [wind],
                       "wind_direction_10m": [270], "precipitation": [0.0], "surface_pressure": [1002.1], "weather_code": [1]},
            "hourly_units": {"temperature_2m": "°C"}}


def test_weather_uses_the_event_location_and_time_and_is_stored(client, db, auth_headers, monkeypatch):
    from app.integrations import weather

    ev, _ = _event(db)
    calls = []

    def fake_request(provider, method, url, params=None, **kw):
        calls.append(params)
        return _Res(_hourly(ev.last_detected.astimezone(UTC).strftime("%Y-%m-%dT%H:00")))

    monkeypatch.setattr(weather, "request", fake_request)
    h = auth_headers("analyst")
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather"]}, headers=h)
    assert [j.status for j in _run_jobs(db)] == ["succeeded"]
    assert calls and calls[0]["latitude"] == pytest.approx(ev.latitude) and calls[0]["longitude"] == pytest.approx(ev.longitude)
    b = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    w = b["weather"][0]
    assert w["temperature_c"] == 31.2 and w["wind_speed_ms"] == 5.0 and w["condition"] == "Mainly clear"
    assert w["observed_at"].startswith(ev.last_detected.astimezone(UTC).strftime("%Y-%m-%dT%H"))
    assert b["enrichment_state"]["weather"]["status"] == "ok"


def test_weather_no_data_is_not_a_provider_failure(client, db, auth_headers, monkeypatch):
    from app.integrations import weather

    ev, _ = _event(db)
    monkeypatch.setattr(weather, "request", lambda *a, **k: _Res({"hourly": {"time": ["1999-01-01T00:00"]}}))
    before = db.execute(text("SELECT requests_failed FROM data_sources WHERE id = 'open_meteo'")).scalar()
    h = auth_headers("analyst")
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather"]}, headers=h)
    _run_jobs(db)
    b = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()
    assert b["weather"] == [] and b["enrichment_state"]["weather"]["status"] == "no_data"
    assert db.execute(text("SELECT requests_failed FROM data_sources WHERE id = 'open_meteo'")).scalar() == before


def test_weather_provider_failure_is_recorded_as_failed(client, db, auth_headers, monkeypatch):
    from app.integrations import weather
    from app.integrations.http import ProviderTimeout

    ev, _ = _event(db)

    def boom(*a, **k):
        raise ProviderTimeout("open_meteo", "timed out")

    monkeypatch.setattr(weather, "request", boom)
    h = auth_headers("analyst")
    client.post(f"/api/v1/events/{ev.public_id}/enrich", params={"steps": ["weather"]}, headers=h)
    _run_jobs(db)
    st = client.get(f"/api/v1/events/{ev.public_id}", headers=h).json()["enrichment_state"]["weather"]
    assert st["status"] == "failed" and st["category"] == "timeout"


def test_archive_hole_falls_back_to_recent_hours_and_old_holes_stay_no_data(monkeypatch):
    from app.integrations import weather

    when = (datetime.now(UTC) - timedelta(days=8)).replace(minute=0, second=0, microsecond=0)
    urls = []

    def fake(provider, method, url, params=None, **kw):
        urls.append(url)
        if "archive" in url:
            return _Res({"hourly": {"time": [when.strftime("%Y-%m-%dT%H:00")], "temperature_2m": [None], "wind_speed_10m": [None]}})
        return _Res(_hourly(when.strftime("%Y-%m-%dT%H:00"), temp=22.0))

    monkeypatch.setattr(weather.settings, "open_meteo_archive_url", "https://archive.invalid")
    monkeypatch.setattr(weather.settings, "open_meteo_forecast_url", "https://forecast.invalid")
    monkeypatch.setattr(weather, "request", fake)
    w = weather.WeatherClient().conditions_at(22.3, 69.8, when)
    assert w.temperature_c == 22.0 and "Forecast" in w.dataset and urls == ["https://archive.invalid", "https://forecast.invalid"]
    with pytest.raises(weather.WeatherNoData):
        weather.WeatherClient().conditions_at(22.3, 69.8, datetime.now(UTC) - timedelta(days=200))


def test_context_backfill_enriches_review_worthy_events_with_weather_and_imagery_only(db, monkeypatch):
    from app.services import enrichment
    from app.workers import tasks

    ev, _ = _event(db)
    db.execute(text("UPDATE thermal_events SET in_india = true, priority_score = 90"))
    db.commit()
    monkeypatch.setattr(enrichment.SatelliteSearchService, "search", lambda self, *a, **k: ([], 10.0))
    monkeypatch.setattr(enrichment.WeatherClient, "conditions_at", lambda self, *a, **k: (_ for _ in ()).throw(
        __import__("app.integrations.weather", fromlist=["WeatherNoData"]).WeatherNoData("none", 1.0)))
    assert enrichment.context_backfill_ids(db, 10) == [ev.id]
    out = tasks.context_backfill(db, {"limit": 10}, None)
    assert out["events"] == 1
    state = db.execute(text("SELECT enrichment_state FROM thermal_events WHERE id = :i"), {"i": ev.id}).scalar()
    assert set(state) >= {"weather", "satellite"} and "osm" not in state
    assert enrichment.context_backfill_ids(db, 10) == []  # done: not picked again


# ------------------------------------------------------------------ facilities
def test_facility_detail_history_and_relationship(client, db, auth_headers):
    ev, fac = _event(db)
    h = auth_headers("viewer")
    f = client.get(f"/api/v1/facilities/{fac.id}", headers=h).json()
    assert f["name"] == "Test Refinery" and f["sources"][0]["source"] == "osm" and "registries" in f
    hist = client.get(f"/api/v1/facilities/{fac.id}/events", params={"limit": 1}, headers=h).json()
    assert hist["total"] >= 1 and len(hist["events"]) == 1 and hist["limit"] == 1
    e = hist["events"][0]
    assert e["public_id"] == ev.public_id and e["brightness_max"] == 345.0 and "priority_score" in e and e["distance_m"] < 3000
    rel = client.get(f"/api/v1/facilities/{fac.id}/relationship", params={"event": ev.public_id}, headers=h).json()
    assert rel["linked"] is True and rel["rank"] == 1 and rel["distance_m"] < 3000 and rel["event"]["public_id"] == ev.public_id
    assert "not proof of causation" in rel["note"]
    assert client.get(f"/api/v1/facilities/{fac.id}/relationship", params={"event": ev.public_id}).status_code == 401
    assert client.get("/api/v1/facilities/00000000-0000-0000-0000-000000000000/relationship", params={"event": ev.public_id},
                      headers=h).status_code == 404
