"""Password hashing and JWT handling. No hard-coded accounts, no bypass paths."""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

_ALGORITHM = "HS256"
_ISSUER = "thermaltrace"
# Constant-time dummy hash so unknown-email logins cost the same as wrong-password logins.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt(rounds=12)).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), (password_hash or _DUMMY_HASH).encode("utf-8")) and bool(
            password_hash
        )
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    classes = sum(
        [any(c.islower() for c in password), any(c.isupper() for c in password), any(c.isdigit() for c in password),
         any(not c.isalnum() for c in password)]
    )
    if classes < 3:
        raise ValueError("Password must mix at least three of: lowercase, uppercase, digits, symbols")


def create_access_token(user_id: uuid.UUID, role: str, session_id: uuid.UUID,
                        ttl_minutes: int | None = None) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes or settings.access_token_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": str(session_id),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "iss": _ISSUER,
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=_ALGORITHM), expires


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on any invalid/expired/tampered token."""
    return jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=[_ALGORITHM],
        issuer=_ISSUER,
        options={"require": ["sub", "jti", "exp", "iss"]},
    )
