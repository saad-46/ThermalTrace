"""Guided exploration ("Explore as Analyst / Admin") without credentials.

Security model, deliberately narrow:

- Off unless `EXPLORE_MODE_ENABLED=true`. When off, the endpoints return 404.
- Each role maps to one system account flagged `is_demo`. Its password hash is derived from a random
  secret that is never stored or shown, and password login is refused for demo accounts, so the only
  way in is `POST /auth/demo`. No credential exists anywhere to leak.
- Demo sessions are READ-ONLY, enforced server-side in `get_current_user` for every authenticated
  route: any non-GET request is rejected (except logging out). Reads with an external cost (the
  Copernicus SWIR render) are also refused.
- Responses to demo sessions mask personal data (email addresses, IP addresses).
- Sessions are short-lived and every one is audited (`auth.demo_session`).
"""
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, Forbidden
from app.core.security import hash_password
from app.models.auth import User

DEMO_ACCOUNTS: dict[str, tuple[str, str]] = {
    # role -> (email, display name). The .invalid TLD is reserved (RFC 2606): these can never be real mailboxes.
    "analyst": ("explore-analyst@thermaltrace.invalid", "Demo Analyst"),
    "admin": ("explore-admin@thermaltrace.invalid", "Demo Administrator"),
}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Writes a demo session may still make: ending itself.
DEMO_ALLOWED_WRITES = frozenset({"/api/v1/auth/logout"})
# Reads refused to demo sessions because each call consumes a paid/limited external quota.
_DEMO_BLOCKED_READS = (re.compile(r"^/api/v1/satellite/[^/]+/swir\.png$"),)


def ensure_enabled() -> None:
    if not settings.explore_mode_enabled:
        # Indistinguishable from a route that does not exist.
        from app.core.errors import NotFound

        raise NotFound("Not found")


def demo_user(db: Session, role: str) -> User:
    """The system account for a demo role, created on first use. Never converts a real account."""
    if role not in DEMO_ACCOUNTS:
        raise AppError(f"role must be one of {', '.join(DEMO_ACCOUNTS)}", code="invalid_role")
    email, name = DEMO_ACCOUNTS[role]
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, full_name=name, role=role, is_active=True, is_demo=True,
                    password_hash=hash_password(secrets.token_urlsafe(48)))  # unknowable: nobody can log in with it
        db.add(user)
        db.flush()
    elif not user.is_demo:
        raise Forbidden("Demo account unavailable", code="demo_account_conflict")
    return user


def session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.explore_session_minutes)


def enforce_read_only(method: str, path: str) -> None:
    """Called for every authenticated request made with a demo session."""
    if method.upper() not in SAFE_METHODS and path not in DEMO_ALLOWED_WRITES:
        raise Forbidden("Changes are disabled in demo mode. Sign in with an account to make changes.", code="demo_read_only")
    if any(p.match(path) for p in _DEMO_BLOCKED_READS):
        raise Forbidden("This view uses a limited external quota and is disabled in demo mode.", code="demo_quota_protected")


_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_IP_KEYS = {"ip", "client_ip", "remote_addr"}


def mask_email(value: str) -> str:
    """`analyst@thermaltrace.local` -> `a***@thermaltrace.local`: the domain stays readable, the person does not."""
    return _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", value)


def mask_pii(obj):
    """Recursively mask e-mail addresses and IP addresses for demo sessions."""
    if isinstance(obj, str):
        return mask_email(obj)
    if isinstance(obj, dict):
        return {k: ("hidden in demo mode" if k in _IP_KEYS and v else mask_pii(v)) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [mask_pii(v) for v in obj]
    return obj
