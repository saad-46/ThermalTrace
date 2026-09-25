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
    """Base class. `kind` is one of: timeout, rate_limited, auth, not_found, server, network, malformed, empty."""

    kind = "provider_error"

    def __init__(self, provider: str, message: str, *, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status


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
                return HttpResult(resp, latency, attempt)
            if resp.status_code in (401, 403):
                raise ProviderAuthError(provider, f"authentication rejected (HTTP {resp.status_code})", status=resp.status_code)
            if resp.status_code == 404:
                raise ProviderNotFound(provider, f"not found (HTTP 404) {safe_url}", status=404)
            if resp.status_code == 429:
                last_exc = ProviderRateLimited(provider, "rate limited (HTTP 429)", status=429)
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit() and attempt < max_attempts:
                    time.sleep(min(int(retry_after), 60))
                    continue
            elif resp.status_code in RETRYABLE_STATUS:
                last_exc = ProviderServerError(provider, f"server error (HTTP {resp.status_code})", status=resp.status_code)
            else:
                raise ProviderError(provider, f"unexpected HTTP {resp.status_code}", status=resp.status_code)
        if attempt < max_attempts:
            sleep_s = backoff_base_s * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning("%s attempt %d/%d failed (%s); retrying in %.1fs", provider, attempt, max_attempts, last_exc, sleep_s)
            time.sleep(sleep_s)
    assert last_exc is not None
    raise last_exc
