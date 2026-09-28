import json
import math
import uuid
from collections.abc import Iterator
from datetime import date, datetime
from urllib.parse import urlsplit

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


def uses_transaction_pooler(url: str, override: bool | None = None) -> bool:
    """Whether DATABASE_URL goes through a transaction-mode pooler (see Settings.db_transaction_pooler)."""
    if override is not None:
        return override
    parts = urlsplit(_normalize_url(url))
    host = (parts.hostname or "").lower()
    return parts.port == 6543 or "-pooler." in host or host.endswith(".pooler.supabase.com")


def _connect_args(url: str) -> dict:
    if uses_transaction_pooler(url, settings.db_transaction_pooler):
        # No server-side prepared statements (they live on one server connection; the pooler hands each transaction
        # to any of them) and no startup `options`, which poolers reject. JIT is then switched off per database
        # instead: `python -m app.cli prepare-database` runs ALTER DATABASE ... SET jit = off.
        return {"prepare_threshold": None}
    # PostgreSQL's JIT compiles queries whose cost estimate is high even when they touch few rows (correlated
    # sub-selects over indexed lookups): ~1.2 s of compilation for a 70 ms query. The application's queries are short
    # and index-driven, so JIT only adds latency.
    return {"options": "-c jit=off"}


engine = create_engine(
    _normalize_url(settings.database_url),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    json_serializer=json_serializer,
    future=True,
    connect_args=_connect_args(settings.database_url),
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
