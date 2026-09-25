"""Postgres-backed TTL cache for expensive provider calls (Overpass, weather, STAC)."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ops import ApiCache


def make_key(namespace: str, **parts) -> str:
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:40]
    return f"{namespace}:{digest}"


def get(db: Session, key: str) -> dict | None:
    row = db.execute(select(ApiCache).where(ApiCache.key == key)).scalar_one_or_none()
    if row is None or row.expires_at < datetime.now(UTC):
        return None
    return row.value


def put(db: Session, key: str, value: dict, ttl: timedelta) -> None:
    expires = datetime.now(UTC) + ttl
    stmt = insert(ApiCache).values(key=key, value=value, expires_at=expires)
    db.execute(stmt.on_conflict_do_update(index_elements=[ApiCache.key], set_={"value": value, "expires_at": expires}))


def purge_expired(db: Session) -> int:
    return db.execute(delete(ApiCache).where(ApiCache.expires_at < datetime.now(UTC))).rowcount or 0
