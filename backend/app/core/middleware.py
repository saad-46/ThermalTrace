"""Request id propagation, access logging, security headers, and a fixed-window rate limiter.

The limiter is in-process (per API replica). It protects against accidental floods and
credential stuffing on /auth/login; a shared limiter (e.g. at the gateway) is the documented
upgrade for multi-replica deployments (docs/SECURITY.md).
"""
import hashlib
import logging
import threading
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import request_id_var

logger = logging.getLogger("thermaltrace.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid[:64])
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["x-frame-options"] = "DENY"
        if request.url.path not in ("/health", "/api/v1/health"):
            logger.info(
                "%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, latency_ms,
                extra={"request_id": rid, "status": response.status_code, "latency_ms": latency_ms},
            )
        return response


class _FixedWindow:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def hit(self, key: str, limit: int, window_s: int = 60) -> bool:
        now_window = int(time.time() // window_s)
        with self._lock:
            window, count = self._hits[key]
            if window != now_window:
                window, count = now_window, 0
            count += 1
            self._hits[key] = (window, count)
            if len(self._hits) > 50_000:  # bound memory
                self._hits.clear()
            return count <= limit


_limiter = _FixedWindow()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client = request.client.host if request.client else "unknown"
        path = request.url.path
        if path.startswith("/api/v1/auth/login"):
            ok = _limiter.hit(f"login:{client}", settings.login_rate_limit_per_minute)
        elif path.startswith("/api/"):
            # Authenticated traffic is limited per session token, not per IP: analysts behind one
            # office NAT must not share a bucket. Forged tokens gain nothing — they fail JWT
            # verification (no DB work) and anonymous requests stay limited per IP.
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer ") and len(auth) > 40:
                key = "tok:" + hashlib.sha256(auth[7:].encode()).hexdigest()[:24]
            else:
                key = f"ip:{client}"
            ok = _limiter.hit(key, settings.rate_limit_per_minute)
        else:
            ok = True
        if not ok:
            return JSONResponse(
                status_code=429,
                headers={"retry-after": "60"},
                content={"error": {"code": "rate_limited", "message": "Too many requests, retry in a minute", "details": {}}},
            )
        return await call_next(request)
