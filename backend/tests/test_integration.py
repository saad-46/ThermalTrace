"""Database + API integration tests (require TEST_DATABASE_URL, a disposable PostGIS database)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration


def _result(rows: list[dict], dataset="VIIRS_NOAA21_NRT"):
    from app.integrations.firms import FetchResult, parse_row

    return FetchResult([parse_row(r, dataset) for r in rows], [], "test://fixture", 1.0, datetime.now(UTC))


def _row(lat, lon, when: datetime, frp=20.0, dn="N", sat="N21"):
    return {"latitude": str(lat), "longitude": str(lon), "bright_ti4": "345", "scan": "0.4", "track": "0.4",
            "acq_date": when.strftime("%Y-%m-%d"), "acq_time": when.strftime("%H%M"), "satellite": sat,
            "confidence": "nominal", "version": "2.0NRT", "bright_ti5": "300", "frp": str(frp), "daynight": dn}


def _flare_site(days=7, base=None):
    """Synthetic *test fixture* resembling a persistent flare: nightly detections on consecutive days."""
    base = base or datetime.now(UTC).replace(hour=20, minute=30, second=0, microsecond=0) - timedelta(days=days)
    rows = []
    for d in range(days):
        for k, sat in enumerate(("N21", "N20", "N")):
            rows.append(_row(22.35 + 0.001 * k, 69.85 + 0.001 * d, base + timedelta(days=d, minutes=10 * k), frp=40 + d, sat=sat))
    return rows


def _ingest(db, rows, dataset="VIIRS_NOAA21_NRT"):
    from app.services.ingestion import finish_run, persist_detections, start_run

    run = start_run(db, "firms", "live", dataset, {})
    res = persist_detections(db, _result(rows, dataset), run, "live")
    finish_run(run, "success", 0.0)
    db.commit()
    return res


def _facility(db, name="Test Refinery", ftype="refinery", lat=22.352, lon=69.853):
    from app.services.facilities import SourceRecord, upsert

    fac, _ = upsert(db, SourceRecord("osm", f"way/{abs(hash(name)) % 10**8}", name, ftype, None, lat, lon))
    db.commit()
    return fac


# ---------------------------------------------------------------- ingestion
def test_ingestion_is_idempotent(db):
    rows = _flare_site(3)
    assert _ingest(db, rows) == (len(rows), 0)
    assert _ingest(db, rows) == (0, len(rows))
    from app.models.thermal import ThermalDetection

    assert db.execute(select(func.count(ThermalDetection.id))).scalar_one() == len(rows)


def test_geography_and_spatial_index_exist(db):
    idx = db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='thermal_detections'")).scalars().all()
    assert "ix_detections_geom" in idx
    assert db.execute(text("SELECT postgis_lib_version()")).scalar()


# ---------------------------------------------------------------- processing
def test_clustering_persistence_attribution_classification(db):
    from app.models.thermal import ThermalEvent
    from app.processing.pipeline import process_new_detections

    _facility(db)
    _ingest(db, _flare_site(7))
    _ingest(db, [_row(28.0, 77.0, datetime.now(UTC) - timedelta(days=1), frp=3, dn="D")])  # far away, single weak pixel
    out = process_new_detections(db)
    assert out["events_failed"] == 0 and out["events_analysed"] == 2
    events = db.execute(select(ThermalEvent).order_by(ThermalEvent.observation_count.desc())).scalars().all()
    flare, weak = events
    assert flare.observation_count == 21 and flare.sensor_count == 3 and flare.days_active == 7
    assert flare.persistence_class == "persistent" and flare.persistence_metrics["active_days"] == 7
    assert flare.nearest_facility_distance_m < 1000
    assert flare.classification == "flare"
    assert flare.confidence_state in ("MODERATE_CONFIDENCE", "HIGH_CONFIDENCE", "LOW_CONFIDENCE")
    assert weak.classification == "unknown" and weak.confidence_state == "INSUFFICIENT_EVIDENCE"
    ev_rows = db.execute(text("SELECT count(*) FROM classification_evidence WHERE event_id=:i"), {"i": flare.id}).scalar()
    assert ev_rows >= 5


def test_new_detection_extends_open_event(db):
    from app.models.thermal import ThermalEvent
    from app.processing.pipeline import process_new_detections

    _ingest(db, _flare_site(3))
    process_new_detections(db)
    _ingest(db, [_row(22.351, 69.852, datetime.now(UTC) - timedelta(hours=2))])
    process_new_detections(db)
    assert db.execute(select(func.count(ThermalEvent.id))).scalar_one() == 1


# ---------------------------------------------------------------- auth & security
def test_auth_flow_and_error_shape(client, make_user):
    u, pw = make_user("analyst")
    bad = client.post("/api/v1/auth/login", json={"email": u.email, "password": "wrong-password"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "unauthorized"
    assert client.get("/api/v1/events").status_code == 401
    tok = client.post("/api/v1/auth/login", json={"email": u.email, "password": pw}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/auth/me", headers=h).json()["role"] == "analyst"
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401  # revoked session


def test_roles_cannot_be_self_assigned(client, auth_headers):
    h = auth_headers("analyst")
    r = client.post("/api/v1/admin/users", headers=h, json={"email": "x@test.org", "full_name": "X", "password": "Aa1!aaaaaaaaaa", "role": "admin"})
    assert r.status_code == 403
    assert client.post("/api/v1/users/", json={"email": "x@test.org", "password": "p", "role": "admin"}).status_code in (404, 405)


def test_viewer_cannot_review(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections

    _ingest(db, _flare_site(2))
    process_new_detections(db)
    h = auth_headers("viewer")
    pid = client.get("/api/v1/events", headers=h).json()["items"][0]["public_id"]
    assert client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "confirm"}).status_code == 403


def test_validation_error_shape(client, auth_headers):
    r = client.get("/api/v1/events", headers=auth_headers(), params={"bbox": "1,2,3"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_bbox"
    r = client.get("/api/v1/events", headers=auth_headers("supervisor"), params={"limit": 9999})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------- analyst workflow, alerts, reports
def test_review_alert_report_workflow(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections
    from app.services.alerts import evaluate_rules
    from app.services.reports import render

    _facility(db)
    _ingest(db, _flare_site(7))
    process_new_detections(db)
    h = auth_headers("analyst")

    page = client.get("/api/v1/events", headers=h, params={"bbox": "69,22,70,23"}).json()
    assert page["total"] == 1
    pid = page["items"][0]["public_id"]
    detail = client.get(f"/api/v1/events/{pid}", headers=h).json()
    assert detail["facilities"][0]["name"] == "Test Refinery"
    assert {m["type"] for m in detail["evidence_matrix"]} == {"FIRMS", "Facility", "Satellite", "Weather", "History", "ML"}
    geo = client.get("/api/v1/events/geojson", headers=h, params={"bbox": "60,0,70,30"}).json()
    assert len(geo["features"]) == 1 and geo["features"][0]["properties"]["classification"] == "flare"

    rule = client.post("/api/v1/alert-rules", headers=h, json={
        "name": "Persistent near refineries", "persistence_classes": ["persistent"], "facility_types": ["refinery"],
        "facility_within_m": 3000, "channels": ["in_app", "email"]})
    assert rule.status_code == 201, rule.text
    alerts = client.get("/api/v1/alerts", headers=h).json()
    assert alerts["total"] == 1
    channels = {d["channel"]: d["status"] for d in alerts["items"][0]["deliveries"]}
    assert channels == {"in_app": "sent", "email": "skipped"}  # SMTP not configured -> recorded as skipped
    assert evaluate_rules(db, [detail["id"]])["alerts"] == 0  # one alert per (rule, event)

    r = client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "false_positive"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "reason_required"
    r = client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "confirm", "notes": "Known flare stack"})
    assert r.json()["review_status"] == "analyst_confirmed"
    assert client.get(f"/api/v1/events/{pid}", headers=h).json()["display_state"] == "ANALYST_CONFIRMED"
    fb = client.get("/api/v1/analytics/feedback", headers=h).json()
    assert fb["adjudicated_labels"] == 1

    rep = client.post("/api/v1/reports", headers=h, json={"event_id": pid})
    assert rep.status_code == 202
    render(db, rep.json()["id"])
    ready = client.get(f"/api/v1/reports/{rep.json()['id']}", headers=h).json()
    assert ready["status"] == "ready" and ready["size_bytes"] > 10_000
    pdf = client.get(f"/api/v1/reports/{rep.json()['id']}/download", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_demo_data_refused_outside_demo_mode(client, auth_headers):
    r = client.post("/api/v1/ingestion/trigger", headers=auth_headers("supervisor"), json={"kind": "load_demo", "payload": {}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "demo_mode_disabled"


def test_health_endpoints(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/v1/ready").json()["status"] == "ready"
    assert "thermaltrace_events_total" in client.get("/metrics").text
