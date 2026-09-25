import json
import math
import uuid
from collections.abc import Iterator
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


def _normalize_url(url: str) -> str:
    # Accept the common postgres:// and postgresql:// forms used by hosting providers.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _clean(obj):
    """JSONB-safe values: ISO datetimes, string UUIDs, NaN/inf -> null (Postgres rejects NaN in JSON)."""
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    return obj


def json_serializer(obj) -> str:
    return json.dumps(_clean(obj), default=str, allow_nan=False)


engine = create_engine(
    _normalize_url(settings.database_url),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    json_serializer=json_serializer,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request; commit is explicit in services."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
