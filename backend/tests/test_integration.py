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
    assert {m["type"] for m in detail["evidence_matrix"]} == {
        "FIRMS", "Facility", "Land cover", "Spectral change", "Satellite", "Weather", "History", "ML"}
    assert detail["landcover"] is None and detail["imagery_analysis"] is None  # not retrieved: shown as pending, not invented
    lc_row = next(m for m in detail["evidence_matrix"] if m["type"] == "Land cover")
    assert lc_row["availability"] == "pending" and lc_row["strength"] == 0
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


# ---------------------------------------------------------------- consolidation additions
def test_priority_search_training_export_and_facility_profile(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections

    fac = _facility(db)
    _ingest(db, _flare_site(7))
    process_new_detections(db)
    h = auth_headers("supervisor")

    ev = client.get("/api/v1/events", headers=h, params={"sort": "priority"}).json()["items"][0]
    assert ev["priority_score"] is not None and ev["priority_score"] > 30
    detail = client.get(f"/api/v1/events/{ev['public_id']}", headers=h).json()
    assert {c["name"] for c in detail["priority_components"]["components"]} >= {"thermal_intensity", "persistence"}
    assert client.get("/api/v1/events", headers=h, params={"min_priority": 101}).status_code == 422

    s = client.get("/api/v1/search", headers=h, params={"q": "Test Refin"}).json()
    assert s["facilities"][0]["name"] == "Test Refinery"
    s = client.get("/api/v1/search", headers=h, params={"q": "22.352, 69.853"}).json()
    assert s["coordinates"] and s["events"][0]["public_id"] == ev["public_id"]
    s = client.get("/api/v1/search", headers=h, params={"q": "flare"}).json()
    assert any(c["key"] == "flare" for c in s["classifications"])

    client.post(f"/api/v1/events/{ev['public_id']}/reviews", headers=h, json={"decision": "reclassify", "source_class": "flare"})
    data = client.get("/api/v1/ml/training-dataset", headers=h).json()
    assert data["count"] == 1
    row = data["rows"][0]
    assert row["analyst_label"] == "flare" and row["model_version"] == "rule-cascade-v1.1" and row["reviewer"]
    assert row["features"]["sensor_count"] == 3.0
    csv_resp = client.get("/api/v1/ml/training-dataset", headers=h, params={"format": "csv"})
    assert csv_resp.status_code == 200 and "analyst_label" in csv_resp.text.splitlines()[0]
    assert client.get("/api/v1/ml/training-dataset", headers=auth_headers("analyst")).status_code == 403

    prof = client.get(f"/api/v1/facilities/{fac.id}/events", headers=h).json()["profile"]
    assert prof["events"] == 1 and prof["persistent"] == 1 and prof["classifications"][0]["n"] == 1


def test_alert_cooldown_suppresses_external_delivery(client, db, auth_headers, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.workflow import AlertRule
    from app.processing.pipeline import process_new_detections
    from app.services import alerts

    monkeypatch.setattr(alerts.settings, "smtp_host", "smtp.test.invalid")
    monkeypatch.setattr(alerts.settings, "smtp_from", "tt@test.org")
    sent = []
    monkeypatch.setattr(alerts, "_send_email", lambda to, alert: sent.append(alert.title))
    _ingest(db, _flare_site(7))
    _ingest(db, [_row(28.0, 77.0, datetime.now(UTC).replace(microsecond=0), frp=60)])
    process_new_detections(db)
    h = auth_headers("analyst")
    r = client.post("/api/v1/alert-rules", headers=h, json={"name": "any event", "source_classes": [
        "flare", "unknown", "other", "process_heat", "wildfire", "agricultural_burn", "coal_seam_fire", "industrial_fire"],
        "channels": ["in_app", "email"], "cooldown_minutes": 60})
    assert r.status_code == 201, r.text
    items = client.get("/api/v1/alerts", headers=h).json()["items"]
    assert len(items) == 2 and len(sent) == 1  # second alert created in-app, email suppressed
    emails = sorted(d["status"] for a in items for d in a["deliveries"] if d["channel"] == "email")
    assert emails == ["sent", "skipped"]
    assert any("cooldown" in (d["error"] or "") for a in items for d in a["deliveries"])
    rule = db.execute(select(AlertRule)).scalar_one()
    db.refresh(rule)
    assert rule.last_notified_at is not None


def test_landcover_imagery_and_audit_trail(client, db, auth_headers, monkeypatch):
    """Stored land cover reaches features, evidence and the bundle; imagery analysis is queued and
    audited; reviews, rule edits and watchlist changes record who changed what."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.models.enrichment import LandCoverObservation
    from app.processing.pipeline import analyse_event, process_new_detections

    now = datetime.now(UTC).replace(microsecond=0)
    _ingest(db, [_row(30.99, 74.22, now, frp=15), _row(30.991, 74.221, now, frp=18)])
    process_new_detections(db)
    ev_id = db.execute(text("SELECT id FROM thermal_events")).scalar_one()
    db.add(LandCoverObservation(event_id=ev_id, source_id="esa_worldcover", product="ESA WorldCover 10 m 2021 v200",
                                window_m=1500, fractions={"cropland": 0.92, "tree_cover": 0.05, "built_up": 0.03},
                                dominant="cropland", valid_fraction=1.0, source_ref="test", retrieved_at=now))
    db.execute(text("UPDATE thermal_events SET enrichment_state = jsonb_build_object('landcover', "
                    "jsonb_build_object('status', 'ok')) WHERE id = :i"), {"i": ev_id})
    db.flush()
    analyse_event(db, ev_id)
    db.commit()
    h = auth_headers("supervisor")
    pid = db.execute(text("SELECT public_id FROM thermal_events")).scalar_one()
    d = client.get(f"/api/v1/events/{pid}", headers=h).json()
    assert d["landcover"]["dominant"] == "cropland"
    assert d["classification"] == "agricultural_burn" and d["classification_probability"] <= 0.6
    lc_ev = [e for e in d["evidence"] if e["category"] == "landcover"]
    assert lc_ev and lc_ev[0]["direction"] == "supports" and "does not decide" in lc_ev[0]["statement"]
    feats = d["predictions"][0]["features_used"]
    assert feats["lc_cropland_frac"] == 0.92 and feats["dndvi"] is None  # no imagery analysis: NaN -> null, never 0

    r = client.post(f"/api/v1/events/{pid}/imagery-analysis", headers=h)
    assert r.status_code == 202
    assert db.execute(text("SELECT count(*) FROM jobs WHERE kind = 'imagery_analysis'")).scalar() == 1

    client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "reclassify", "source_class": "wildfire"})
    audit_row = db.execute(text("SELECT detail FROM audit_logs WHERE action = 'event.review.reclassify'")).scalar_one()
    assert audit_row["previous"]["system_class"] == "agricultural_burn" and audit_row["previous"]["review_status"] == "unreviewed"
    assert audit_row["new"]["analyst_class"] == "wildfire"

    rule = client.post("/api/v1/alert-rules", headers=h, json={"name": "priority only", "min_priority": 101 - 1}).json()
    upd = client.put(f"/api/v1/alert-rules/{rule['id']}", headers=h, json={"name": "priority only", "min_priority": 10})
    assert upd.status_code == 200 and upd.json()["min_priority"] == 10
    change = db.execute(text("SELECT detail FROM audit_logs WHERE action = 'alert_rule.update'")).scalar_one()
    assert change["changes"]["min_priority"] == {"from": 100, "to": 10}

    wl = client.post("/api/v1/watchlists", headers=h, json={"name": "Punjab"}).json()
    item = client.post(f"/api/v1/watchlists/{wl['id']}/items", headers=h, json={"kind": "district", "label": "Firozpur", "admin_district": "Firozpur"})
    assert item.status_code == 201
    actions = {r[0] for r in db.execute(text("SELECT action FROM audit_logs WHERE entity_type = 'watchlist'"))}
    assert actions == {"watchlist.create", "watchlist.item_add"}


def test_alert_min_priority_condition(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections

    _facility(db)
    _ingest(db, _flare_site(7))
    process_new_detections(db)
    h = auth_headers("analyst")
    prio = client.get("/api/v1/events", headers=h).json()["items"][0]["priority_score"]
    none = client.post("/api/v1/alert-rules", headers=h, json={"name": "above", "min_priority": prio + 1})
    assert none.status_code == 201 and none.json()["alert_count"] == 0
    hit = client.post("/api/v1/alert-rules", headers=h, json={"name": "at", "min_priority": prio})
    assert hit.json()["alert_count"] == 1
    reason = client.get("/api/v1/alerts", headers=h).json()["items"][0]["reason"]
    assert reason["priority"] == prio
    too_broad = client.post("/api/v1/alert-rules", headers=h, json={"name": "nothing"})
    assert too_broad.status_code == 400


def test_model_activation_is_an_audited_admin_decision(client, db, auth_headers):
    """Training stores a model inactive; an admin activates and can deactivate it (rules take over again)."""
    import inspect

    from sqlalchemy import text

    from app.ml.registry import train_and_register
    from app.models.ml import ModelVersion

    assert inspect.signature(train_and_register).parameters["activate"].default is False
    db.add(ModelVersion(id="lgbm-test", kind="lightgbm", is_active=False, feature_names=[], classes=[], description="t",
                        label_provenance="t", training_summary={}, metrics={}))
    db.commit()
    assert client.post("/api/v1/models/lgbm-test/activate", headers=auth_headers("analyst")).status_code == 403
    admin = auth_headers("admin")
    assert client.post("/api/v1/models/lgbm-test/activate", headers=admin).status_code == 200
    assert db.execute(text("SELECT is_active FROM model_versions WHERE id = 'lgbm-test'")).scalar() is True
    assert client.post("/api/v1/models/lgbm-test/deactivate", headers=admin).status_code == 200
    assert db.execute(text("SELECT is_active FROM model_versions WHERE id = 'lgbm-test'")).scalar() is False
    actions = [r[0] for r in db.execute(text("SELECT action FROM audit_logs WHERE entity_type = 'model_version' ORDER BY id"))]
    assert actions == ["model.activate", "model.deactivate"]
    db.execute(text("DELETE FROM model_versions WHERE id = 'lgbm-test'"))
    db.commit()


def test_firms_backfill_is_chunked_and_keeps_progress_on_failure(db):
    """12 days -> three API windows; a provider failure in window 3 keeps windows 1-2 and records the failure."""
    from datetime import UTC, date, datetime

    import pytest
    from sqlalchemy import text

    from app.integrations.firms import FetchResult, parse_row
    from app.integrations.http import ProviderServerError
    from app.services.ingestion import ingest_firms_historical

    calls = []

    def detection(source, start):
        row = {"latitude": "23.7", "longitude": "86.4", "acq_date": start.isoformat(), "acq_time": "0800",
               "satellite": "N", "instrument": "VIIRS", "confidence": "n", "frp": "12.5", "bright_ti4": "330",
               "bright_ti5": "295", "scan": "0.4", "track": "0.4", "daynight": "D", "version": "2.0NRT"}
        return FetchResult([parse_row(row, source)], [], "test", 1.0, datetime.now(UTC))

    class FailingThirdWindow:
        def get_historical_detections(self, source, bbox, start, n):
            calls.append((start, n))
            if len(calls) == 3:
                raise ProviderServerError("firms", "HTTP 503")
            return detection(source, start)

    with pytest.raises(ProviderServerError):
        ingest_firms_historical(db, "VIIRS_SNPP_SP", "2025-07-01", 12, client=FailingThirdWindow())
    assert calls == [(date(2025, 7, 1), 5), (date(2025, 7, 6), 5), (date(2025, 7, 11), 2)]
    assert db.execute(text("SELECT count(*) FROM thermal_detections WHERE data_mode = 'historical'")).scalar() == 2
    runs = [r[0] for r in db.execute(text("SELECT status FROM ingestion_runs WHERE mode = 'historical' ORDER BY started_at"))]
    assert runs == ["success", "success", "failed"]

    # Re-running is safe: the two completed windows deduplicate, the third now succeeds.
    class AllWindowsOk:
        def get_historical_detections(self, source, bbox, start, n):
            return detection(source, start)

    res = ingest_firms_historical(db, "VIIRS_SNPP_SP", "2025-07-01", 12, client=AllWindowsOk())
    assert res["windows_done"] == 3 and res["inserted"] == 1 and res["duplicates"] == 2


def test_firms_backfill_trigger_validates_before_queueing(client, auth_headers, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(settings, "firms_map_key", SecretStr("x" * 32))
    h = auth_headers("supervisor")
    bad_src = client.post("/api/v1/ingestion/trigger", headers=h, json={"kind": "firms_historical",
                          "payload": {"source": "NOPE", "start": "2025-07-01", "days": 10}})
    assert bad_src.status_code == 400 and bad_src.json()["error"]["code"] == "invalid_source"
    bad_days = client.post("/api/v1/ingestion/trigger", headers=h, json={"kind": "firms_historical",
                           "payload": {"source": "VIIRS_SNPP_SP", "start": "2025-07-01", "days": 5000}})
    assert bad_days.json()["error"]["code"] == "invalid_days"
    ok = client.post("/api/v1/ingestion/trigger", headers=h, json={"kind": "firms_historical",
                     "payload": {"source": "VIIRS_SNPP_SP", "start": "2025-07-01", "days": 365}})
    assert ok.status_code == 202
