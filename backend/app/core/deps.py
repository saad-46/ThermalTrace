"""FastAPI dependencies: authentication, role guards, pagination."""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import jwt
from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.logging import user_id_var
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.auth import ROLE_RANK, User, UserSession

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise Unauthorized("Authentication required")
    try:
        claims = decode_access_token(creds.credentials)
        user_id = uuid.UUID(claims["sub"])
        session_id = uuid.UUID(claims["jti"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise Unauthorized("Invalid or expired token") from None

    session = db.get(UserSession, session_id)
    now = datetime.now(UTC)
    if session is None or session.user_id != user_id or session.revoked_at is not None or session.expires_at < now:
        raise Unauthorized("Session is no longer valid")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthorized("Account is disabled")
    request.state.is_demo = bool(user.is_demo)
    if user.is_demo:  # guided exploration sessions are read-only for every authenticated route
        from app.services.explore import enforce_read_only

        enforce_read_only(request.method, request.url.path)
    request.state.user = user
    request.state.session_id = session_id
    user_id_var.set(str(user.id))
    return user


def require_role(minimum: str):
    """Role hierarchy: viewer < analyst < supervisor < admin."""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[minimum]:
            raise Forbidden(f"This action requires the '{minimum}' role or higher")
        return user

    return _guard


CurrentUser = Depends(get_current_user)
AnalystUser = Depends(require_role("analyst"))
SupervisorUser = Depends(require_role("supervisor"))
AdminUser = Depends(require_role("admin"))


@dataclass
class Page:
    limit: int
    offset: int


def pagination(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0, le=100_000)) -> Page:
    return Page(limit=limit, offset=offset)
