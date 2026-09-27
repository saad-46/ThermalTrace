"""Unit tests for the production-hardening pass (no database): provider outcome classification, Retry-After, the raster
error path, enrichment step bookkeeping, evidence-matrix wording, demo masking, job continuations, secret and password
guards."""
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest


# ---------------------------------------------------------------- providers
def test_a_body_that_is_not_json_is_a_malformed_reply_not_an_empty_result():
    from app.integrations.http import HttpResult, ProviderMalformed

    res = HttpResult(httpx.Response(200, text="<html>maintenance</html>"), 12.0, 1, "open_meteo")
    with pytest.raises(ProviderMalformed) as err:
        res.json()
    assert err.value.kind == "malformed" and err.value.provider == "open_meteo"


def test_retry_after_accepts_seconds_and_http_dates():
    from app.integrations.http import _retry_after

    assert _retry_after("30") == 30.0
    later = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    assert 100 < _retry_after(later) <= 120
    assert _retry_after("soon") is None and _retry_after(None) is None


def test_a_missing_raster_is_a_classified_provider_error_not_a_crash(tmp_path):
    """Regression: ProviderNotFound(msg) was called without the provider name and raised TypeError instead."""
    from app.integrations import raster
    from app.integrations.http import ProviderError

    with pytest.raises(ProviderError) as err:
        raster.read_window(str(tmp_path / "missing.tif"), 21.1, 72.6, 750, 16)
    assert err.value.kind in ("not_found", "network", "malformed")


def test_stored_failure_categories_are_read_back_unchanged():
    from app.api.v1.intelligence import error_category_text

    assert error_category_text("[rate_limited] open_meteo: rate limited (HTTP 429)") == "rate_limited"
    assert error_category_text("[processing_failure] cdse: bad token") == "processing_failure"
    assert error_category_text("timeout") == "timeout"
    assert error_category_text(None) is None


def test_enrichment_failures_carry_a_category_and_count_attempts():
    from app.integrations.http import ProviderTimeout
    from app.models.thermal import ThermalEvent
    from app.services import enrichment

    ev = ThermalEvent(public_id="TT-TEST", enrichment_state={})
    enrichment._failed(ev, "weather", ProviderTimeout("open_meteo", "timed out"))
    enrichment._failed(ev, "weather", ProviderTimeout("open_meteo", "timed out"))
    step = ev.enrichment_state["weather"]
    assert step["status"] == "failed" and step["category"] == "timeout" and step["attempts"] == 2
    assert "open_meteo" not in (step["detail"] or "")  # the raw provider message stays in the log
    enrichment._mark(ev, "weather", "ok")
    assert "attempts" not in ev.enrichment_state["weather"]
    assert "'timeout', 'rate_limited', 'service_unavailable'" in enrichment._retry_due("weather")


def test_evidence_matrix_never_calls_a_failure_no_data():
    from app.repositories.events import _imagery_row, _landcover_row, _missing

    assert _missing("failed", "timeout", "none", "not yet")[0] == "failed"
    assert _missing("no_data", None, "none found", "not yet") == ("no data", "none found")
    assert _missing(None, None, "none", "not yet") == ("not requested", "not yet")
    assert _landcover_row(None, {"status": "failed", "category": "rate_limited"})["availability"] == "failed"
    assert _imagery_row({"status": "failed", "reason": "Sentinel-2 imagery could not be read (timeout)"})["availability"] == "failed"
    assert _imagery_row({"status": "unavailable", "reason": "cloud"})["availability"] == "no data"


# ---------------------------------------------------------------- demo sessions and security guards
def test_demo_masking_hides_people_but_keeps_the_evidence():
    from app.services.explore import mask_pii

    out = mask_pii({"reviews": [{"reviewer": "Priya Sharma", "notes": "flare visible", "decision": "confirm"}],
                    "notes": [{"author": "A. Analyst", "body": "mail ops@example.org"}], "full_name": "Admin Person"})
    assert out["reviews"][0]["reviewer"] == "(name hidden in demo)" and out["reviews"][0]["notes"] == "flare visible"
    assert out["notes"][0]["author"] == "(name hidden in demo)" and "o***@example.org" in out["notes"][0]["body"]
    assert out["full_name"] == "(name hidden in demo)"


def test_demo_sessions_cannot_export_or_call_providers_live():
    from app.core.errors import AppError
    from app.services.explore import enforce_read_only

    for path in ("/api/v1/reports/abc/download", "/api/v1/ml/training-dataset", "/api/v1/weather/current",
                 "/api/v1/satellite/abc/swir.png"):
        with pytest.raises(AppError):
            enforce_read_only("GET", path)
    enforce_read_only("GET", "/api/v1/events/TT-2026-000001")  # ordinary reads work


def test_the_public_development_secret_is_refused_for_a_public_origin():
    from app.core.config import Settings

    with pytest.raises(ValueError, match="public development secret"):
        Settings(secret_key="dev-only-insecure-secret-change-me", cors_origins="https://thermaltrace.example.org",
                 environment="development")
    Settings(secret_key="dev-only-insecure-secret-change-me", cors_origins="http://localhost:5173", environment="development")


def test_passwords_longer_than_bcrypt_reads_are_refused():
    from pydantic import ValidationError

    from app.schemas.api import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(email="a@example.org", full_name="A", password="é" * 40)  # 40 characters, 80 bytes
    assert UserCreate(email="a@example.org", full_name="A", password="x" * 72).password


# ---------------------------------------------------------------- jobs
def test_continuations_alternate_keys_so_a_chain_never_suppresses_itself():
    from app.models.ops import Job
    from app.workers.queue import LANES
    from app.workers.tasks import continuation_key

    first = continuation_key("enrich_batch", Job(dedupe_key="sched:enrich_batch"))
    second = continuation_key("enrich_batch", Job(dedupe_key=first))
    third = continuation_key("enrich_batch", Job(dedupe_key=second))
    assert first != second and third == first
    assert "process_events" in LANES["bulk"] and "process_events" not in LANES["interactive"]  # one clustering lane


def test_training_never_activates_a_model():
    import inspect

    from app.ml.registry import train_and_register

    assert list(inspect.signature(train_and_register).parameters) == ["db"]
