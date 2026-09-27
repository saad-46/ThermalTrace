"""Regression tests for the stabilisation pass: one evidence-stage definition everywhere, `reviewed` as a first-class
review status, demo sessions read-only on every write route, owner scoping (IDOR), literal search input, analytics
filter validation and reproducible alert explanations. Require TEST_DATABASE_URL (a disposable PostGIS database)."""
import re
import uuid

import pytest
from sqlalchemy import text

from tests.test_integration import _explore, _facility, _flare_site, _ingest

pytestmark = pytest.mark.integration


def _processed(db, days=7):
    from app.processing.pipeline import process_new_detections

    _facility(db)
    _ingest(db, _flare_site(days))
    process_new_detections(db)
    return db.execute(text("SELECT id, public_id FROM thermal_events ORDER BY observation_count DESC")).all()


def _login(client, make_user, role, email):
    u, pw = make_user(role, email=email)
    r = client.post("/api/v1/auth/login", json={"email": u.email, "password": pw})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------- evidence stages: one definition
def test_evidence_availability_agrees_across_page_alerts_and_analytics(client, db, auth_headers):
    from app.services import analytics as A
    from app.services import evidence_rules as R

    events = _processed(db)
    h = auth_headers("analyst")
    pid = events[0].public_id
    assert client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "mark_reviewed"}).status_code == 201

    per_stage = dict.fromkeys(R.STAGE_KEYS, 0)
    for eid, pid in events:
        bundle = client.get(f"/api/v1/events/{pid}", headers=h).json()["evidence_stages"]
        page = {s["key"]: s["state"] == "available" for s in bundle["stages"]}
        rules = R.availability(db, eid)
        assert [s["key"] for s in bundle["stages"]] == list(R.STAGE_KEYS)
        assert page == rules, pid
        assert bundle["completeness"]["available"] == sum(rules.values())
        alert_count = db.execute(text(f"SELECT {R.completeness_sql('e')} FROM thermal_events e WHERE e.id = :i"), {"i": eid}).scalar()
        assert alert_count == sum(rules.values()), pid
        for k, v in rules.items():
            per_stage[k] += v
        assert set(bundle["freshness"]) == {"latest_observation_at", "latest_evidence_refresh_at", "processed_at", "record_updated_at"}

    A._CACHE.clear()
    cov = client.get("/api/v1/analytics/evidence-coverage?days=3650", headers=h).json()
    assert cov["events"] == len(events) and cov["stages_total"] == R.TOTAL
    assert {k: cov[k] for k in R.STAGE_KEYS} == per_stage


def test_coverage_schema_has_exactly_the_stage_keys():
    from app.schemas.intelligence import EvidenceCoverageOut
    from app.services.evidence_rules import STAGE_KEYS

    assert set(EvidenceCoverageOut.model_fields) - {"events", "mean_stages", "stages_total", "note"} == set(STAGE_KEYS)


# ---------------------------------------------------------------- reviewed is a first-class status
def test_reviewed_status_is_displayed_counted_and_filterable(client, db, auth_headers):
    from app.services import analytics as A

    (eid, pid), *_ = _processed(db)
    h = auth_headers("analyst")
    client.post(f"/api/v1/events/{pid}/reviews", headers=h, json={"decision": "mark_reviewed"})
    ev = client.get(f"/api/v1/events/{pid}", headers=h).json()
    assert ev["review_status"] == "reviewed" and ev["display_state"] == "ANALYST_REVIEWED"
    final = next(s for s in ev["evidence_stages"]["stages"] if s["key"] == "final_status")
    assert final["state"] == "available"
    assert ev["reviews"][0]["previous_status"] == "unreviewed" and ev["reviews"][0]["new_status"] == "reviewed"

    listed = client.get("/api/v1/events?review_status=reviewed&since=2000-01-01T00:00:00Z", headers=h).json()["items"]
    assert [e["public_id"] for e in listed] == [pid] and listed[0]["display_state"] == "ANALYST_REVIEWED"
    bad = client.get("/api/v1/events?review_status=approved", headers=h)
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_review_status"

    A._CACHE.clear()
    totals = client.get("/api/v1/analytics/overview?days=3650", headers=h).json()["totals"]
    assert totals["reviewed"] == 1 and totals["confirmed"] == 0 and totals["rejected"] == 0


# ---------------------------------------------------------------- demo sessions are read-only everywhere
# writes that do not act on a session (they create or end one) or are public
_NO_SESSION_WRITES = {"/api/v1/auth/login", "/api/v1/auth/demo", "/api/v1/auth/logout"}


def test_demo_session_is_refused_on_every_write_route(client, db, monkeypatch):
    from app.main import app

    h, _ = _explore(client, monkeypatch, "admin")  # the highest demo role
    checked = []
    for route, ops in app.openapi()["paths"].items():
        for method in set(ops) & {"post", "put", "patch", "delete"}:
            if route in _NO_SESSION_WRITES:
                continue
            path = re.sub(r"\{[^}]*(ref|public_id)[^}]*\}", "TT-2026-000001", route)
            path = re.sub(r"\{action\}", "acknowledge", path)
            path = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
            r = client.request(method.upper(), path, headers=h, json={})
            checked.append((method, route))
            assert r.status_code == 403 and r.json()["error"]["code"] == "demo_read_only", (method, route, r.status_code, r.text[:200])
    assert len(checked) >= 20, checked  # 24 write routes at the time of writing; guards against an empty enumeration
    assert db.execute(text("SELECT count(*) FROM analyst_reviews")).scalar() == 0


# ---------------------------------------------------------------- owner scoping (IDOR)
def test_rules_alerts_watchlists_and_locations_are_owner_scoped(client, db, make_user):
    _processed(db)
    a = _login(client, make_user, "analyst", "owner@test.org")
    b = _login(client, make_user, "analyst", "other@test.org")
    rule = client.post("/api/v1/alert-rules", headers=a, json={"name": "mine", "min_priority": 1}).json()
    wl = client.post("/api/v1/watchlists", headers=a, json={"name": "mine"}).json()
    loc = client.post("/api/v1/saved-locations", headers=a, json={"name": "x", "latitude": 22.3, "longitude": 69.8, "zoom": 9}).json()
    alerts = client.get("/api/v1/alerts", headers=a).json()["items"]
    assert alerts, "the rule should have produced an alert for the owner"

    assert client.get("/api/v1/alert-rules", headers=b).json() == []
    assert client.put(f"/api/v1/alert-rules/{rule['id']}", headers=b, json={"name": "stolen", "min_priority": 1}).status_code == 404
    assert client.delete(f"/api/v1/alert-rules/{rule['id']}", headers=b).status_code == 404
    assert client.get("/api/v1/alerts", headers=b).json()["items"] == []
    assert client.post(f"/api/v1/alerts/{alerts[0]['id']}/acknowledge", headers=b).status_code == 404
    assert client.get(f"/api/v1/watchlists/{wl['id']}", headers=b).status_code == 404
    assert client.delete(f"/api/v1/watchlists/{wl['id']}", headers=b).status_code == 404
    assert client.delete(f"/api/v1/saved-locations/{loc['id']}", headers=b).status_code == 404
    assert client.get("/api/v1/admin/audit", headers=b).status_code == 403
    # nothing changed for the owner
    assert client.get("/api/v1/alert-rules", headers=a).json()[0]["name"] == "mine"
    assert client.get("/api/v1/alerts", headers=a).json()["items"][0]["status"] == "new"


# ---------------------------------------------------------------- search input is literal
def test_search_treats_wildcards_and_sql_as_literal_text(client, db, auth_headers):
    _processed(db)
    h = auth_headers("analyst")
    assert client.get("/api/v1/search?q=Refinery", headers=h).json()["facilities"]
    for q in ("%%", "__", "Test_Refinery", "%Refinery"):
        body = client.get("/api/v1/search", headers=h, params={"q": q}).json()
        assert body["facilities"] == [] and body["events"] == [] and body["places"] == [], q
    r = client.get("/api/v1/search", headers=h, params={"q": "'; DROP TABLE facilities; --"})
    assert r.status_code == 200 and r.json()["facilities"] == []
    assert client.get("/api/v1/events", headers=h, params={"q": "%"}).json()["total"] == 0
    assert db.execute(text("SELECT count(*) FROM facilities")).scalar() == 1


def test_analytics_rejects_unknown_classification(client, auth_headers):
    h = auth_headers("analyst")
    r = client.get("/api/v1/analytics/overview?classification=arson", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_classification"
    assert client.get("/api/v1/analytics/overview?classification=flare", headers=h).status_code == 200


# ---------------------------------------------------------------- alert explanations stay reproducible
def test_alert_keeps_the_rule_as_it_was_when_triggered(client, db, auth_headers):
    _processed(db)
    h = auth_headers("analyst")
    rule = client.post("/api/v1/alert-rules", headers=h, json={"name": "v1", "min_priority": 1}).json()
    client.put(f"/api/v1/alert-rules/{rule['id']}", headers=h, json={"name": "v2", "min_priority": 90})
    x = client.get("/api/v1/alerts", headers=h).json()["items"][0]["reason"]["explanation"]
    assert x["rule_id"] == rule["id"]
    assert x["rule_snapshot"]["name"] == "v1" and x["rule_snapshot"]["min_priority"] == 1
    cond = next(c for c in x["conditions"] if c["condition"] == "priority")
    assert cond["threshold"] == ">= 1" and cond["observed"] is not None


# ---------------------------------------------------------------- report: analyst conclusion kept apart
def test_report_separates_analyst_conclusion_from_automated_interpretation():
    from app.services.reports import _analyst_conclusion

    ev = {"review_status": "unreviewed"}
    assert "No analyst decision recorded" in _analyst_conclusion(ev, None)
    review = {"decision": "reclassify", "source_class": "flare", "reviewer": "A. Analyst", "created_at": "2026-09-25T06:00:00+00:00",
              "notes": "Flare stack visible in the scene."}
    text_ = _analyst_conclusion({"review_status": "analyst_confirmed"}, review)
    assert text_.startswith("Analyst confirmed.") and "as Gas flare" in text_ and "Flare stack visible" in text_
