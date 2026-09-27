"""Local facility index: scheduled, tile-based synchronisation of OSM facilities.

Why: querying public Overpass for industrial facilities around every event took ≈30 s per
cell and throttled enrichment (see docs/BUG_FIXES.md). Instead:

    OSM Overpass ──(scheduled, 1° tiles, busiest tiles first)──► facilities (PostGIS, GiST)
                                                                     │
    event enrichment ──(local ST_DWithin, milliseconds)──────────────┘

Tiles are refreshed every FRESH_DAYS. Event enrichment only asks Overpass for land use when
every tile within the attribution radius of the event is fresh; otherwise it falls back to
the bounded per-cell facility query, so coverage never depends on the sync having run.
"""
import logging
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.http import ProviderError
from app.integrations.overpass import OsmFeature, OverpassClient, classify_facility
from app.models.ops import FacilitySyncTile
from app.services import facilities, source_health

logger = logging.getLogger(__name__)
TILE_DEG = 1.0
FRESH_DAYS = 30
EDGE_PAD_DEG = 0.1  # ≈11 km: attribution radius (10 km) must be covered by fresh tiles


def tile_key(lat: float, lon: float) -> str:
    return f"{math.floor(lat / TILE_DEG) * TILE_DEG:g}:{math.floor(lon / TILE_DEG) * TILE_DEG:g}"


def tiles_around(lat: float, lon: float, pad: float = EDGE_PAD_DEG) -> set[str]:
    return {tile_key(lat + dy, lon + dx) for dy in (-pad, 0, pad) for dx in (-pad, 0, pad)}


def upsert_osm_facilities(db: Session, feats: list[OsmFeature], endpoint: str) -> int:
    """Upsert OSM facility candidates; returns the number of new source records."""
    created = 0
    for f in feats:
        ftype = classify_facility(f.tags)
        if not ftype:
            continue
        _, is_new = facilities.upsert(db, facilities.SourceRecord(
            source_id="osm", external_id=f"{f.osm_type}/{f.osm_id}", name=f.name, facility_type=ftype,
            source_type=", ".join(f"{k}={f.tags[k]}" for k in ("power", "man_made", "industrial", "landuse") if k in f.tags) or None,
            latitude=f.latitude, longitude=f.longitude, operator=f.tags.get("operator"),
            status="operating (per OSM)" if not f.tags.get("disused") else "disused",
            source_url=f"https://www.openstreetmap.org/{f.osm_type}/{f.osm_id}",
            dataset_version=f"OSM via {endpoint.split('/')[2]}", raw={"tags": f.tags, "bounds": f.bounds},
        ))
        created += int(is_new)
    return created


def register_tiles(db: Session) -> int:
    """Create/refresh tile rows for every tile containing events (event_count drives priority)."""
    res = db.execute(text(
        """
        INSERT INTO facility_sync_tiles (tile_key, west, south, east, north, status, event_count)
        SELECT (floor(latitude / :d) * :d)::text || ':' || (floor(longitude / :d) * :d)::text,
               floor(longitude / :d) * :d, floor(latitude / :d) * :d,
               floor(longitude / :d) * :d + :d, floor(latitude / :d) * :d + :d, 'pending', count(*)
        FROM thermal_events GROUP BY 1, 2, 3, 4, 5
        ON CONFLICT (tile_key) DO UPDATE SET event_count = EXCLUDED.event_count
        """), {"d": TILE_DEG})
    db.commit()
    return res.rowcount or 0


def fresh_tiles(db: Session, keys: set[str]) -> set[str]:
    if not keys:
        return set()
    cutoff = datetime.now(UTC) - timedelta(days=FRESH_DAYS)
    rows = db.execute(select(FacilitySyncTile.tile_key).where(
        FacilitySyncTile.tile_key.in_(keys), FacilitySyncTile.status == "ok", FacilitySyncTile.last_synced_at >= cutoff))
    return set(rows.scalars())


def due_tiles(db: Session, limit: int) -> list[FacilitySyncTile]:
    cutoff = datetime.now(UTC) - timedelta(days=FRESH_DAYS)
    retry_after = datetime.now(UTC) - timedelta(hours=6)
    return list(db.execute(
        select(FacilitySyncTile)
        .where((FacilitySyncTile.last_synced_at.is_(None)) | (FacilitySyncTile.last_synced_at < cutoff))
        .where((FacilitySyncTile.last_attempt_at.is_(None)) | (FacilitySyncTile.last_attempt_at < retry_after)
               | (FacilitySyncTile.status != "failed"))
        .order_by(FacilitySyncTile.event_count.desc()).limit(limit)).scalars())


def sync_tiles(db: Session, limit: int = 4) -> dict:
    """Sync up to `limit` due tiles, then re-attribute events inside them (local, fast)."""
    from app.processing.pipeline import analyse_event

    register_tiles(db)
    client = OverpassClient(settings.overpass_url_list)
    out = {"synced": 0, "failed": 0, "facilities_new": 0, "events_reanalysed": 0, "remaining": 0}
    for tile in due_tiles(db, limit):
        tile.last_attempt_at = datetime.now(UTC)
        try:
            feats, endpoint, latency = client.query_facility_tile(tile.south, tile.west, tile.north, tile.east)
        except ProviderError as exc:
            tile.status, tile.error = "failed", f"{exc.kind}: {exc}"[:500]
            source_health.record_failure(db, "osm", exc)
            db.commit()
            out["failed"] += 1
            continue
        new = upsert_osm_facilities(db, feats, endpoint)
        tile.status, tile.error = "ok", None
        tile.features_found, tile.facilities_new = len(feats), new
        tile.last_synced_at = datetime.now(UTC)
        source_health.record_success(db, "osm", latency, new)
        db.commit()
        out["synced"] += 1
        out["facilities_new"] += new
        if new:
            ids = db.execute(text(
                "SELECT id FROM thermal_events WHERE latitude >= :s - 0.1 AND latitude < :n + 0.1 "
                "AND longitude >= :w - 0.1 AND longitude < :e + 0.1"),
                {"s": tile.south, "n": tile.north, "w": tile.west, "e": tile.east}).scalars().all()
            for eid in ids:
                with db.begin_nested():
                    analyse_event(db, eid)
            db.commit()
            out["events_reanalysed"] += len(ids)
    out["remaining"] = len(due_tiles(db, 10_000))
    logger.info("facility sync: %s", out)
    return out


def coverage(db: Session) -> dict:
    row = db.execute(text(
        """SELECT count(*) total, count(*) FILTER (WHERE status='ok' AND last_synced_at >= now() - make_interval(days => :f)) fresh,
                  count(*) FILTER (WHERE status='failed') failed, coalesce(sum(event_count), 0) events,
                  coalesce(sum(event_count) FILTER (WHERE status='ok'), 0) events_covered, max(last_synced_at) last_synced
           FROM facility_sync_tiles"""), {"f": FRESH_DAYS}).mappings().one()
    return dict(row)
