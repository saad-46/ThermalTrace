"""Integration-test setup. Integration tests need TEST_DATABASE_URL (a disposable PostGIS database);
they are skipped otherwise. The database is migrated with Alembic once per session and cleaned
between tests."""
import os

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL")

# Tests must never reach real providers with a developer's credentials. Settings also read the local
# .env file, but environment variables take precedence, so these blanks always win. Tests that need a
# provider configured monkeypatch the setting and stub the network call.
PROVIDER_CREDENTIALS = (
    "FIRMS_MAP_KEY", "COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET", "SMTP_HOST", "SMTP_USERNAME", "SMTP_USER",
    "SMTP_PASSWORD", "SMTP_FROM", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT", "SENTRY_DSN",
)
for _name in PROVIDER_CREDENTIALS:
    os.environ[_name] = ""
# Behaviour switches a local .env may turn on; tests that need them enable them explicitly.
os.environ["EXPLORE_MODE_ENABLED"] = "false"

if TEST_DB:
    # Must be set before app modules create the engine.
    os.environ["DATABASE_URL"] = TEST_DB
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ["DEMO_MODE"] = "false"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
    os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "100000"


def pytest_collection_modifyitems(config, items):
    if TEST_DB:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated():
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # also proves migrations apply cleanly on an empty database
    yield


_TRUNCATE = """TRUNCATE thermal_detections, thermal_events, facilities, facility_sources, alerts, alert_rules, analyst_reviews,
  investigations, investigation_notes, reports, jobs, ingestion_runs, users, user_sessions, watchlists, api_cache,
  model_predictions, classifications, audit_logs RESTART IDENTITY CASCADE"""


@pytest.fixture
def db(migrated):
    from sqlalchemy import text

    from app.db.session import SessionLocal

    s = SessionLocal()
    s.execute(text(_TRUNCATE))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture
def make_user(db):
    from app.core.security import hash_password
    from app.models.auth import User

    def _make(role: str = "analyst", email: str | None = None, password: str = "Str0ng-Test-Pass!"):
        u = User(email=email or f"{role}@test.org", full_name=f"Test {role}", password_hash=hash_password(password), role=role)
        db.add(u)
        db.commit()
        return u, password

    return _make


@pytest.fixture
def auth_headers(client, make_user):
    def _h(role: str = "analyst"):
        u, pw = make_user(role)
        r = client.post("/api/v1/auth/login", json={"email": u.email, "password": pw})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _h
