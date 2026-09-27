"""Resilient outbound HTTP: timeouts, bounded retries with exponential backoff + jitter,
Retry-After awareness, and a typed error taxonomy every integration shares.
"""
import logging
import random
import threading
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """Base class. `kind` is one of: timeout, rate_limited, auth, not_found, server, network, malformed, provider_error.
    "No data" is never an error: providers return an empty result (or a dedicated no-data exception) for it."""

    kind = "provider_error"

    def __init__(self, provider: str, message: str, *, status: int | None = None, retry_after_s: float | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        self.retry_after_s = retry_after_s  # what the provider asked for (429 / 503 Retry-After), when it said


class ProviderTimeout(ProviderError):
    kind = "timeout"


class ProviderRateLimited(ProviderError):
    kind = "rate_limited"


class ProviderAuthError(ProviderError):
    kind = "auth"


class ProviderServerError(ProviderError):
    kind = "server"


class ProviderNetworkError(ProviderError):
    kind = "network"


class ProviderMalformed(ProviderError):
    kind = "malformed"


class ProviderNotFound(ProviderError):
    kind = "not_found"


@dataclass
class HttpResult:
    response: httpx.Response
    latency_ms: float
    attempts: int
    provider: str = "provider"

    def json(self):
        """The body as JSON; a body that is not JSON is a malformed provider reply, never an empty result."""
        try:
            return self.response.json()
        except ValueError:
            raise ProviderMalformed(self.provider, f"reply is not JSON (HTTP {self.response.status_code})",
                                    status=self.response.status_code) from None


def _retry_after(value: str | None) -> float | None:
    """Retry-After as seconds: either delta-seconds or an HTTP date (RFC 9110 §10.2.3)."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from datetime import UTC, datetime
        from email.utils import parsedate_to_datetime

        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


class _MinInterval:
    """Per-host politeness throttle (e.g. Overpass, Nominatim usage policies)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}

    def wait(self, key: str, min_interval_s: float) -> None:
        if min_interval_s <= 0:
            return
        with self._lock:
            now = time.monotonic()
            ready_at = self._last.get(key, 0.0) + min_interval_s
            delay = max(0.0, ready_at - now)
            self._last[key] = now + delay
        if delay:
            time.sleep(delay)


throttle = _MinInterval()


def request(
    provider: str,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    data: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    max_attempts: int = 4,
    backoff_base_s: float = 1.5,
    min_interval_s: float = 0.0,
    redact: str | None = None,
) -> HttpResult:
    """Perform a request with retries. Raises a ProviderError subclass on terminal failure.

    `redact` is a secret that must never appear in logs (e.g. a FIRMS MAP_KEY in the path).
    """
    safe_url = url.replace(redact, "***") if redact else url
    hdrs = {"User-Agent": settings.http_user_agent, **(headers or {})}
    last_exc: ProviderError | None = None
    started = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        throttle.wait(provider, min_interval_s)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.request(method, url, params=params, data=data, json=json, headers=hdrs)
        except httpx.TimeoutException:
            last_exc = ProviderTimeout(provider, f"timed out after {timeout}s ({safe_url})")
        except httpx.HTTPError as exc:
            last_exc = ProviderNetworkError(provider, f"network error: {type(exc).__name__}")
        else:
            latency = (time.perf_counter() - started) * 1000
            if resp.status_code < 400:
                return HttpResult(resp, latency, attempt, provider)
            if resp.status_code in (401, 403):
                raise ProviderAuthError(provider, f"authentication rejected (HTTP {resp.status_code})", status=resp.status_code)
            if resp.status_code == 404:
                raise ProviderNotFound(provider, f"not found (HTTP 404) {safe_url}", status=404)
            wait = _retry_after(resp.headers.get("retry-after"))
            if resp.status_code == 429:
                last_exc = ProviderRateLimited(provider, "rate limited (HTTP 429)", status=429, retry_after_s=wait)
            elif resp.status_code in RETRYABLE_STATUS:
                last_exc = ProviderServerError(provider, f"server error (HTTP {resp.status_code})", status=resp.status_code,
                                               retry_after_s=wait)
            if wait is not None and resp.status_code in (429, 503):
                if wait > 60 or attempt >= max_attempts:
                    raise last_exc  # the provider asked for longer than a request can wait: record it, retry later
                time.sleep(wait)
                continue
            if resp.status_code not in RETRYABLE_STATUS:
                raise ProviderError(provider, f"unexpected HTTP {resp.status_code}", status=resp.status_code)
        if attempt < max_attempts:
            sleep_s = backoff_base_s * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning("%s attempt %d/%d failed (%s); retrying in %.1fs", provider, attempt, max_attempts, last_exc, sleep_s)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc
