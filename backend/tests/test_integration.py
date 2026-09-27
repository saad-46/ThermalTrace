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
    assert detail["landcover"] is None and detail["imagery_analysis"] is None  # not retrieved: shown as not requested, not invented
    lc_row = next(m for m in detail["evidence_matrix"] if m["type"] == "Land cover")
    assert lc_row["availability"] == "not requested" and lc_row["strength"] == 0  # nothing queued: not "pending"
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
    assert r.status_code == 409 and r.json()["error"]["code"] == "imagery_not_ready"  # no scenes: nothing to compare
    from datetime import timedelta

    from app.models.enrichment import SatelliteObservation

    for item, when in (("before", now - timedelta(days=4)), ("after", now + timedelta(days=2))):
        db.add(SatelliteObservation(event_id=ev_id, provider="earth-search", source_id="earth_search", collection="sentinel-2-l2a",
                                    item_id=f"S2A_{item}", platform="sentinel-2a", acquired_at=when, cloud_cover=5.0,
                                    processing_level="L2A", relation=item, retrieved_at=now, assets={}))
    db.commit()
    r = client.post(f"/api/v1/events/{pid}/imagery-analysis", headers=h)
    assert r.status_code == 202
    assert db.execute(text("SELECT count(*) FROM jobs WHERE kind = 'imagery_analysis'")).scalar() == 1
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'event.imagery_analysis.request'")).scalar() == 1

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

    assert "activate" not in inspect.signature(train_and_register).parameters  # training can never activate
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


def test_processing_continues_across_batches_and_continuations_are_not_suppressed(db):
    """A backlog larger than one clustering pass is finished by continuation jobs; a job that re-queues
    itself while running must use a different dedupe key or the queue silently drops the continuation."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    from app.processing.pipeline import process_new_detections
    from app.workers.queue import enqueue
    from app.workers.tasks import continuation_key

    now = datetime.now(UTC).replace(microsecond=0)
    _ingest(db, [_row(20.0 + i, 75.0, now - timedelta(hours=i), frp=30) for i in range(3)])
    first = process_new_detections(db, batch_size=2)
    assert first["remaining_unassigned"] == 1
    assert process_new_detections(db, batch_size=2)["remaining_unassigned"] == 0

    running = enqueue(db, "process_events", {}, dedupe_key="process_events")
    db.execute(text("UPDATE jobs SET status = 'running' WHERE id = :i"), {"i": running})
    db.commit()
    assert enqueue(db, "process_events", {}, dedupe_key="process_events") == running  # same key: suppressed
    cont = enqueue(db, "process_events", {}, dedupe_key=continuation_key("process_events"))
    assert cont != running and db.execute(text("SELECT status FROM jobs WHERE id = :i"), {"i": cont}).scalar() == "queued"


def test_events_are_named_by_the_nearest_place_and_far_events_stay_unnamed(client, db, auth_headers):
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.processing.pipeline import process_new_detections

    def place(i, name, admin1, cc, lat, lon):
        db.execute(text("INSERT INTO places (geonameid, name, admin1, country_code, population, latitude, longitude, geom) "
                        "VALUES (:i, :n, :a, :c, 5000, :la, :lo, ST_SetSRID(ST_MakePoint(:lo, :la), 4326)::geography)"),
                   {"i": i, "n": name, "a": admin1, "c": cc, "la": lat, "lo": lon})

    place(1, "Dhanbad", "Jharkhand", "IN", 23.795, 86.43)
    place(2, "Jamtara", "Jharkhand", "IN", 23.96, 86.80)
    db.commit()
    now = datetime.now(UTC).replace(microsecond=0)
    _ingest(db, [_row(23.79, 86.43, now, frp=25), _row(23.791, 86.431, now, frp=30), _row(10.0, 80.0, now, frp=25), _row(10.001, 80.001, now, frp=30)])
    process_new_detections(db)
    h = auth_headers("analyst")
    # region=all: the far point is at sea off Tamil Nadu, outside India's boundary (excluded by default)
    items = {round(e["latitude"]): e for e in client.get("/api/v1/events", headers=h, params={"region": "all"}).json()["items"]}
    near, far = items[24], items[10]
    assert near["place_name"] == "Dhanbad" and near["place_admin1"] == "Jharkhand" and near["place_country"] == "IN"
    assert near["place_distance_m"] < 2000
    assert far["place_name"] is None and far["place_distance_m"] > 50_000  # too far: coordinates only, never a misleading name
    found = client.get("/api/v1/events", headers=h, params={"q": "dhanbad"}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == near["id"]  # searching a place finds the events near it
    s = client.get("/api/v1/search", headers=h, params={"q": "Dhanb"}).json()
    assert s["places"] and s["places"][0]["admin_district"] == "Dhanbad" and s["places"][0]["admin_state"] == "Jharkhand"


def _explore(client, monkeypatch, role="analyst"):
    from app.core.config import settings

    monkeypatch.setattr(settings, "explore_mode_enabled", True)
    r = client.post("/api/v1/auth/demo", json={"role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


def test_explore_mode_is_off_unless_enabled(client):
    assert client.get("/api/v1/auth/demo").json() == {"enabled": False, "roles": []}
    r = client.post("/api/v1/auth/demo", json={"role": "admin"})
    assert r.status_code == 404  # indistinguishable from a route that does not exist


def test_explore_sessions_are_read_only_and_audited(client, db, monkeypatch):
    from sqlalchemy import text

    from app.processing.pipeline import process_new_detections

    _facility(db)
    _ingest(db, _flare_site(3))
    process_new_detections(db)
    h, body = _explore(client, monkeypatch, "analyst")
    assert body["user"]["is_demo"] is True and body["user"]["role"] == "analyst"
    assert client.get("/api/v1/auth/me", headers=h).json()["is_demo"] is True
    pid = client.get("/api/v1/events", headers=h).json()["items"][0]["public_id"]
    assert client.get(f"/api/v1/events/{pid}", headers=h).status_code == 200  # reads work
    for method, path, payload in (("post", f"/api/v1/events/{pid}/reviews", {"decision": "confirm"}),
                                  ("post", f"/api/v1/events/{pid}/notes", {"body": "x"}),
                                  ("post", "/api/v1/reports", {"event_id": pid}),
                                  ("post", "/api/v1/alert-rules", {"name": "x", "min_priority": 1}),
                                  ("post", "/api/v1/watchlists", {"name": "x"})):
        r = getattr(client, method)(path, headers=h, json=payload)
        assert r.status_code == 403 and r.json()["error"]["code"] == "demo_read_only", (path, r.text)
    assert db.execute(text("SELECT count(*) FROM analyst_reviews")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM audit_logs WHERE action = 'auth.demo_session'")).scalar() == 1
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204  # the only write allowed
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401  # and it really ends the session


def test_explore_admin_sees_admin_views_with_personal_data_masked_and_cannot_mutate(client, db, monkeypatch, make_user):
    make_user("analyst", email="real.person@agency.gov.in")
    h, _ = _explore(client, monkeypatch, "admin")
    users = client.get("/api/v1/admin/users", headers=h).json()["items"]
    emails = {u["email"] for u in users}
    assert "real.person@agency.gov.in" not in emails and "r***@agency.gov.in" in emails
    audit_rows = client.get("/api/v1/admin/audit", headers=h).json()
    assert audit_rows and all(r["ip"] in (None, "hidden in demo mode") for r in audit_rows)
    assert client.get("/api/v1/admin/system", headers=h).status_code == 200
    real = next(u for u in users if u["email"].startswith("r***"))
    for method, path, payload in (("patch", f"/api/v1/admin/users/{real['id']}", {"role": "admin"}),
                                  ("post", "/api/v1/admin/users", {"email": "x@y.org", "full_name": "x", "role": "admin", "password": "Str0ng-Test-Pass!"}),
                                  ("post", "/api/v1/ingestion/trigger", {"kind": "firms_poll", "payload": {}}),
                                  ("post", "/api/v1/models/rule-cascade-v1.1/activate", None)):
        r = getattr(client, method)(path, headers=h, json=payload)
        assert r.status_code == 403 and r.json()["error"]["code"] == "demo_read_only", (path, r.text)
    assert client.get("/api/v1/satellite/00000000-0000-0000-0000-000000000000/swir.png", headers=h).json()["error"]["code"] == "demo_quota_protected"


def test_demo_accounts_cannot_log_in_with_a_password_and_are_not_assignable(client, db, monkeypatch, auth_headers):
    from sqlalchemy import text

    _explore(client, monkeypatch, "admin")
    email = db.execute(text("SELECT email FROM users WHERE is_demo")).scalar_one()
    assert email.endswith(".invalid")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "anything-at-all"})
    assert r.status_code == 401
    names = [u["full_name"] for u in client.get("/api/v1/users/directory", headers=auth_headers("supervisor")).json()]
    assert "Demo Administrator" not in names
    # a real login still works alongside demo mode
    assert client.get("/api/v1/auth/me", headers=auth_headers("analyst")).json()["is_demo"] is False


def test_old_or_backfilled_events_never_alert(client, db, auth_headers, monkeypatch):
    """A historical backfill must not notify anyone about months-old events; recent events still alert."""
    from datetime import UTC, datetime, timedelta

    from app.processing.pipeline import process_new_detections
    from app.services import alerts

    sent = []
    monkeypatch.setattr(alerts.settings, "smtp_host", "smtp.test.invalid")
    monkeypatch.setattr(alerts.settings, "smtp_from", "tt@test.org")
    monkeypatch.setattr(alerts, "_send_email", lambda to, alert: sent.append(alert.title))
    old = datetime.now(UTC).replace(microsecond=0) - timedelta(days=120)
    _ingest(db, [_row(28.0, 77.0, old, frp=60), _row(28.001, 77.001, old + timedelta(hours=1), frp=70)])
    process_new_detections(db)
    h = auth_headers("analyst")
    r = client.post("/api/v1/alert-rules", headers=h, json={"name": "anything", "min_priority": 0, "channels": ["in_app", "email"]})
    assert r.status_code == 201 and r.json()["alert_count"] == 0 and sent == []
    _ingest(db, [_row(22.0, 70.0, datetime.now(UTC).replace(microsecond=0), frp=60)])
    res = process_new_detections(db)
    assert alerts.evaluate_rules(db, res["event_ids"])["alerts"] == 1 and len(sent) == 1


def test_land_context_accepts_current_openstreetmap_ids(db):
    """OSM ids passed 2^31; a 32-bit column made land-use enrichment fail with 'integer out of range'."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from app.models.facilities import LandContext
    from app.processing.pipeline import process_new_detections

    _ingest(db, [_row(22.0, 70.0, datetime.now(UTC).replace(microsecond=0), frp=30)])
    process_new_detections(db)
    ev_id = db.execute(text("SELECT id FROM thermal_events")).scalar_one()
    db.add(LandContext(event_id=ev_id, osm_type="way", osm_id=3_000_000_123, category="farmland", distance_m=120.0,
                       tags={}, retrieved_at=datetime.now(UTC)))
    db.commit()
    assert db.execute(text("SELECT osm_id FROM land_context")).scalar_one() == 3_000_000_123


def test_featured_event_is_the_real_event_with_most_evidence(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections

    h = auth_headers("analyst")
    assert client.get("/api/v1/events/featured", headers=h).json() is None  # empty database: nothing invented
    _facility(db)
    _ingest(db, _flare_site(7))
    _ingest(db, [_row(28.0, 77.0, datetime.now(UTC) - timedelta(days=1), frp=3, dn="D")])
    process_new_detections(db)
    # Even if the weak, isolated event were at the top of the queue, the evidence-rich one is featured.
    db.execute(text("UPDATE thermal_events SET priority_score = CASE WHEN observation_count = 1 THEN 99 ELSE 10 END"))
    db.commit()
    f = client.get("/api/v1/events/featured", headers=h).json()
    assert f["observation_count"] == 21
    assert "a mapped facility within 2 km" in f["selection_reasons"]
    assert "persistent or recurring heat" in f["selection_reasons"]
    assert "no Sentinel-2 before/after analysis" in f["unavailable_evidence"]  # stated, not invented


def test_similar_events_equal_a_full_fingerprint_scan(db):
    import json
    import math

    from app.processing.pipeline import process_new_detections
    from app.repositories.events import similar_events

    now = datetime.now(UTC) - timedelta(days=1)
    _ingest(db, [_row(10 + 2 * i, 75.0, now, frp=5 + i) for i in range(8)])
    process_new_detections(db)
    ids = [r[0] for r in db.execute(text("SELECT id FROM thermal_events ORDER BY latitude"))]
    types = ["refinery", "refinery", "refinery", None, "mine", "refinery", None, "mine"]
    fps = [{"intensity": 0.1 * i, "persistence": 0.5, "facility_proximity": 0.2 * (i % 3), "night_share": 1.0,
            "sensor_agreement": 0.3, "facility_type": t} for i, t in enumerate(types)]
    for i, fp in zip(ids, fps, strict=True):
        db.execute(text("UPDATE thermal_events SET fingerprint = CAST(:fp AS jsonb) WHERE id = :id"), {"fp": json.dumps(fp), "id": i})
    db.commit()

    def dist(a, b):
        d = sum((a[k] - b[k]) ** 2 for k in ("intensity", "persistence", "facility_proximity", "night_share", "sensor_agreement"))
        return math.sqrt(d + (0.3 if a["facility_type"] != b["facility_type"] else 0))

    for me in range(len(ids)):
        for limit in (1, 3, 6):
            expected = sorted((dist(fps[j], fps[me]), j) for j in range(len(ids)) if j != me)[:limit]
            got = similar_events(db, ids[me], limit)
            assert [r["fp_distance"] for r in got] == pytest.approx([d for d, _ in expected])


def test_creating_a_rule_evaluates_only_that_rule(client, db, auth_headers, make_user):
    from app.processing.pipeline import process_new_detections

    _facility(db)
    _ingest(db, _flare_site(7))
    process_new_detections(db)
    h = auth_headers("analyst")
    first = client.post("/api/v1/alert-rules", headers=h, json={"name": "first", "min_priority": 0}).json()
    assert first["alert_count"] == 1
    db.execute(text("DELETE FROM alerts WHERE rule_id = :r"), {"r": first["id"]})
    db.commit()
    other, pw = make_user("analyst", email="other@test.org")
    tok = client.post("/api/v1/auth/login", json={"email": other.email, "password": pw}).json()["access_token"]
    second = client.post("/api/v1/alert-rules", headers={"Authorization": f"Bearer {tok}"},
                         json={"name": "second", "min_priority": 0}).json()
    assert second["alert_count"] == 1
    # Another user's rule is not re-run (and cannot notify anyone) because a new rule was created.
    assert db.execute(text("SELECT count(*) FROM alerts WHERE rule_id = :r"), {"r": first["id"]}).scalar() == 0


def test_watchlist_matches_every_item_kind_once(client, db, auth_headers):
    from app.processing.pipeline import process_new_detections

    fac = _facility(db)
    _ingest(db, _flare_site(7))
    _ingest(db, [_row(28.0, 77.0, datetime.now(UTC) - timedelta(days=1), frp=3, dn="D")])
    process_new_detections(db)
    weak = db.execute(text("SELECT id, public_id FROM thermal_events WHERE observation_count = 1")).one()
    db.execute(text("UPDATE thermal_events SET admin_district = 'Firozpur' WHERE id = :i"), {"i": weak.id})
    db.commit()
    h = auth_headers("analyst")
    wl = client.post("/api/v1/watchlists", headers=h, json={"name": "all kinds"}).json()

    def add_and_count(item: dict) -> int:
        assert client.post(f"/api/v1/watchlists/{wl['id']}/items", headers=h, json=item).status_code == 201
        return client.get(f"/api/v1/watchlists/{wl['id']}", headers=h).json()["summary"]["events"]

    assert add_and_count({"kind": "location", "label": "site", "latitude": 22.35, "longitude": 69.85, "radius_m": 5000}) == 1
    assert add_and_count({"kind": "district", "label": "Firozpur", "admin_district": "firozpur"}) == 2  # case-insensitive
    assert add_and_count({"kind": "facility", "label": "refinery", "facility_id": str(fac.id)}) == 2  # same event, counted once
    assert add_and_count({"kind": "event", "label": weak.public_id, "event_id": str(weak.id)}) == 2


def test_public_landing_exposes_only_safe_live_aggregates(client, db, make_user, monkeypatch):
    import json

    from app.api.v1 import public
    from app.core.config import settings
    from app.processing.pipeline import process_new_detections

    make_user("admin", email="private.person@agency.gov.in")
    _facility(db)
    _ingest(db, _flare_site(7))
    _ingest(db, [_row(28.0, 77.0, datetime.now(UTC) - timedelta(days=1), frp=3, dn="D")])
    process_new_detections(db)
    db.execute(text("UPDATE thermal_events SET data_mode = 'demo' WHERE observation_count = 1"))  # demo data is not counted
    db.execute(text("UPDATE thermal_detections SET data_mode = 'demo' WHERE event_id IN "
                    "(SELECT id FROM thermal_events WHERE data_mode = 'demo')"))
    db.commit()
    public.clear_cache()

    r = client.get("/api/v1/public/landing")  # no Authorization header
    assert r.status_code == 200
    d = r.json()
    assert d["counts"] == {"detections": 21, "events": 1, "events_recent": 1, "facilities": 1, "events_outside_india": 0}
    assert d["classifier"] == "rule-cascade-v1.1"
    assert d["sources_total"] == len(d["sources"]) and all(s["id"] != "demo" for s in d["sources"])
    assert d["activity"]["cells"] == [[22.38, 69.88, 1]]  # 0.25° cell centre and a count  # 1° cell centre and a count, nothing identifying
    body = json.dumps(d)
    for private in ("private.person", "@", "TT-", "password", "token"):
        assert private not in body

    public.clear_cache()
    monkeypatch.setattr(settings, "public_landing_enabled", False)
    assert client.get("/api/v1/public/landing").status_code == 404


def test_source_states_come_from_the_backend_and_say_what_is_missing(client, auth_headers):
    from app.api.v1 import public

    # conftest blanks provider credentials: Copernicus must say so, never claim to be active
    rows = {s["id"]: s for s in client.get("/api/v1/sources", headers=auth_headers("analyst")).json()}
    assert rows["cdse"]["state"] == "credentials_required"
    assert rows["cdse"]["requirement_env"] == ["COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET"]
    assert rows["cea"]["state"] == "import_required" and "import-registry --source cea" in rows["cea"]["requirement_how"]

    public.clear_cache()
    d = client.get("/api/v1/public/landing").json()
    states = {s["id"]: s for s in d["sources"]}
    assert states["cdse"]["state"] == "credentials_required"
    assert states["cdse"]["requirement"] == "Copernicus Data Space OAuth client"
    assert "COPERNICUS_CLIENT" not in str(d)  # configuration names stay with signed-in users
    assert d["sources_active"] == sum(1 for s in d["sources"] if s["state"] == "active")
    public.clear_cache()


def test_india_boundary_loaded_by_migration_classifies_mainland_and_islands(db):
    from app.gis.boundaries import IN_INDIA_SQL

    b = db.execute(text("SELECT pov, ST_NumGeometries(geom::geometry) FROM boundaries WHERE code = 'IND'")).one()
    assert b[0] == "IND" and b[1] >= 30  # mainland plus Lakshadweep and Andaman & Nicobar islands
    assert db.execute(text("SELECT count(*) FROM admin_areas WHERE country = 'IND'")).scalar() == 36

    def inside(lat, lon):
        return db.execute(text(f"SELECT {IN_INDIA_SQL.format(geom='ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)')}"),
                          {"lat": lat, "lon": lon}).scalar()

    assert inside(28.61, 77.21)          # New Delhi
    assert inside(10.57, 72.64)          # Kavaratti, Lakshadweep
    assert inside(11.62, 92.73)          # Port Blair, Andaman & Nicobar
    assert not inside(31.55, 74.34)      # Lahore, Pakistan
    assert not inside(27.72, 85.32)      # Kathmandu, Nepal
    assert not inside(6.93, 79.85)       # Colombo, Sri Lanka
    assert not inside(23.81, 90.41)      # Dhaka, Bangladesh


def test_events_outside_india_are_excluded_from_the_india_dashboard(client, db, auth_headers):
    from app.api.v1 import public
    from app.processing.pipeline import process_new_detections

    now = datetime.now(UTC) - timedelta(days=1)
    _ingest(db, [_row(22.35, 69.85, now, frp=40)])          # Gujarat, India
    _ingest(db, [_row(31.52, 74.30, now, frp=40)])          # Lahore, Pakistan (inside a crude lat/lon box for India)
    process_new_detections(db)
    flags = dict(db.execute(text("SELECT round(latitude)::int, in_india FROM thermal_events")).all())
    assert flags == {22: True, 32: False}
    h = auth_headers("analyst")
    assert client.get("/api/v1/events", headers=h).json()["total"] == 1
    assert client.get("/api/v1/events", headers=h, params={"region": "all"}).json()["total"] == 2
    geo = client.get("/api/v1/events/geojson", headers=h, params={"bbox": "60,5,100,40"}).json()
    assert len(geo["features"]) == 1
    public.clear_cache()
    counts = client.get("/api/v1/public/landing").json()["counts"]
    assert counts["events"] == 1 and counts["events_outside_india"] == 1
    public.clear_cache()


def test_attribution_skips_plants_that_were_never_built_and_plants_that_burn_nothing(db):
    from app.processing.pipeline import process_new_detections

    solar = _facility(db, name="Solar Park", ftype="power_plant_other", lat=22.3505, lon=69.8505)
    cancelled = _facility(db, name="Cancelled Coal Plant", ftype="power_plant_coal", lat=22.3502, lon=69.8502)
    refinery = _facility(db, name="Real Refinery", ftype="refinery", lat=22.352, lon=69.853)
    db.execute(text("UPDATE facilities SET subtype = 'solar' WHERE id = :i"), {"i": solar.id})
    db.execute(text("UPDATE facilities SET status = 'cancelled' WHERE id = :i"), {"i": cancelled.id})
    db.commit()
    _ingest(db, _flare_site(3))
    process_new_detections(db)
    linked = {r[0] for r in db.execute(text("SELECT facility_id FROM event_facility_links"))}
    assert refinery.id in linked and solar.id not in linked and cancelled.id not in linked


def test_public_boundary_serves_india_its_mask_and_states(client):
    b = client.get("/api/v1/public/boundary", params={"detail": "overview"})
    assert b.status_code == 200 and "max-age" in b.headers["cache-control"]
    d = b.json()
    assert d["india"]["geometry"]["type"] == "MultiPolygon" and len(d["india"]["geometry"]["coordinates"]) >= 30
    assert d["mask"]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert len(d["states"]["features"]) == 36 and d["pov"] == "IND"
    w, s, e, n = d["bbox"]
    assert w < 68.5 and e > 97 and s < 7 and n > 36  # includes Andaman & Nicobar (south-east) and the north


def test_cea_registry_import_links_stations_to_located_facilities_with_provenance(client, db, monkeypatch, tmp_path, auth_headers):
    from datetime import date

    from app.api.v1 import public
    from app.integrations.cea_pdf import parse_lines
    from app.services import cea_registry
    from app.services.facilities import SourceRecord, upsert

    wri, _ = upsert(db, SourceRecord("wri_gppd", "IND0001", "GIRAL", "power_plant_coal", None, 26.03, 71.24,
                                     capacity_value=250, raw={"primary_fuel": "Coal"}))
    db.commit()
    monkeypatch.setattr(cea_registry, "parse_pdf", lambda path: parse_lines([_cea_page()]))
    report = cea_registry.import_registry(db, tmp_path / "List_of_Power_Station.pdf", "CEA list 31.03.2025", date(2025, 3, 31), tmp_path)
    db.commit()
    assert report["stations"] == 4 and report["coordinates_in_source"] is False
    giral = db.execute(text("SELECT facility_id, coordinate_source, match_status FROM registry_stations WHERE name = 'GIRAL TPS'")).one()
    assert giral.facility_id == wri.id and giral.coordinate_source == "wri_gppd" and giral.match_status == "matched"
    cea_src = db.execute(text("SELECT raw FROM facility_sources WHERE source_id = 'cea' AND facility_id = :f"), {"f": wri.id}).scalar()
    assert cea_src["coordinate_source"] == "wri_gppd" and "CEA publishes no coordinates" in cea_src["note"]
    unlocated = db.execute(text("SELECT count(*) FROM registry_stations WHERE facility_id IS NULL")).scalar()
    assert unlocated == 3  # listed, kept, not placed on the map without a location
    assert (tmp_path / "cea_stations_normalized.csv").exists() and (tmp_path / "cea_validation_report.json").exists()
    public.clear_cache()
    # figures for signed-in users (Data sources page); the public card shows only name, purpose and state
    cea = next(s for s in client.get("/api/v1/sources", headers=auth_headers("admin")).json() if s["id"] == "cea")
    assert cea["registry"]["stations"] == 4 and cea["registry"]["located"] == 1 and cea["registry"]["coordinate_sources"] == ["wri_gppd"]
    public.clear_cache()
    card = next(s for s in client.get("/api/v1/public/landing").json()["sources"] if s["id"] == "cea")
    assert set(card) == {"id", "name", "kind", "state", "reason", "requirement", "last_success_at"}
    public.clear_cache()


def _cea_page() -> str:
    from tests.test_units import CEA_PAGE
    return CEA_PAGE
