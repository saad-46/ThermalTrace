import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import AdminUser, CurrentUser, Page, pagination
from app.core.errors import Conflict, NotFound, Unauthorized
from app.core.security import create_access_token, hash_password, validate_password_strength, verify_password
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.schemas.api import DemoIn, LoginIn, TokenOut, UserCreate, UserOut, UserUpdate
from app.schemas.api import Page as PageOut
from app.services import audit

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut, summary="Exchange email + password for a bearer token")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active or user.is_demo:  # demo accounts never log in with a password
        audit.record(db, request, user.id if user else None, "auth.login_failed", "user", None, {"email": body.email.lower()})
        db.commit()
        raise Unauthorized("Invalid email or password")
    session = UserSession(user_id=user.id, expires_at=datetime.now(UTC),
                          user_agent=(request.headers.get("user-agent") or "")[:400],
                          ip=request.client.host if request.client else None)
    db.add(session)
    db.flush()
    token, expires = create_access_token(user.id, user.role, session.id)
    session.expires_at = expires
    user.last_login_at = datetime.now(UTC)
    audit.record(db, request, user.id, "auth.login", "user", user.id)
    db.commit()
    return TokenOut(access_token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.get("/auth/demo", summary="Whether guided exploration (read-only demo sessions) is available")
def demo_config():
    from app.core.config import settings
    from app.services.explore import DEMO_ACCOUNTS

    return {"enabled": settings.explore_mode_enabled, "roles": list(DEMO_ACCOUNTS) if settings.explore_mode_enabled else []}


@router.post("/auth/demo", response_model=TokenOut, summary="Start a read-only guided exploration session (no credentials)")
def demo_session(body: DemoIn, request: Request, db: Session = Depends(get_db)):
    from app.core.config import settings
    from app.services import explore

    explore.ensure_enabled()
    user = explore.demo_user(db, body.role)
    expires = explore.session_expiry()
    session = UserSession(user_id=user.id, expires_at=expires, user_agent=(request.headers.get("user-agent") or "")[:400],
                          ip=request.client.host if request.client else None)
    db.add(session)
    db.flush()
    token, expires = create_access_token(user.id, user.role, session.id, ttl_minutes=settings.explore_session_minutes)
    session.expires_at = expires
    user.last_login_at = datetime.now(UTC)
    audit.record(db, request, user.id, "auth.demo_session", "user", user.id, {"role": body.role})
    db.commit()
    return TokenOut(access_token=token, expires_at=expires, user=UserOut.model_validate(user))


@router.post("/auth/logout", status_code=204, summary="Revoke the current session")
def logout(request: Request, user: User = CurrentUser, db: Session = Depends(get_db)):
    session = db.get(UserSession, request.state.session_id)
    if session:
        session.revoked_at = datetime.now(UTC)
    audit.record(db, request, user.id, "auth.logout", "user", user.id)
    db.commit()


@router.get("/auth/me", response_model=UserOut)
def me(user: User = CurrentUser):
    return user


@router.get("/users/directory", summary="Minimal user directory for assignment pickers")
def directory(user: User = CurrentUser, db: Session = Depends(get_db)):
    rows = db.execute(select(User.id, User.full_name, User.role).where(User.is_active.is_(True), User.role != "viewer",
                                                                     User.is_demo.is_(False))
                      .order_by(User.full_name)).all()
    out = [{"id": r.id, "full_name": r.full_name, "role": r.role} for r in rows]
    if user.is_demo:
        from app.services.explore import mask_pii

        out = mask_pii(out)
    return out


@router.get("/admin/users", response_model=PageOut[UserOut], tags=["admin"])
def list_users(page: Page = Depends(pagination), admin: User = AdminUser, db: Session = Depends(get_db)):
    total = db.execute(select(func.count(User.id))).scalar_one()
    items = db.execute(select(User).order_by(User.created_at.desc()).limit(page.limit).offset(page.offset)).scalars().all()
    if admin.is_demo:
        from app.services.explore import mask_pii

        items = [mask_pii(UserOut.model_validate(u).model_dump()) for u in items]
    return {"items": items, "total": total, "limit": page.limit, "offset": page.offset}


@router.post("/admin/users", response_model=UserOut, status_code=201, tags=["admin"],
             summary="Create a user (roles are only ever assigned by an admin)")
def create_user(body: UserCreate, request: Request, admin: User = AdminUser, db: Session = Depends(get_db)):
    validate_password_strength(body.password)
    if db.execute(select(User.id).where(User.email == body.email.lower())).first():
        raise Conflict("A user with this email already exists")
    user = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password), role=body.role,
                organization_id=admin.organization_id)
    db.add(user)
    db.flush()
    audit.record(db, request, admin.id, "user.create", "user", user.id, {"role": body.role})
    db.commit()
    return user


@router.patch("/admin/users/{user_id}", response_model=UserOut, tags=["admin"])
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, admin: User = AdminUser, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("User not found")
    changes = body.model_dump(exclude_none=True)
    if user.id == admin.id and ("role" in changes or changes.get("is_active") is False):
        raise Conflict("Admins cannot change their own role or deactivate themselves")
    previous = {k: getattr(user, k) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    if changes.get("is_active") is False:
        for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))).scalars():
            s.revoked_at = datetime.now(UTC)
    audit.record(db, request, admin.id, "user.update", "user", user.id, {"previous": previous, "new": changes})
    db.commit()
    return user
