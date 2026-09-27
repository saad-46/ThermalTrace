"""Raster land cover (ESA WorldCover) around an event: sampled, stored with provenance, never invented."""
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.integrations import raster
from app.integrations.http import ProviderError, ProviderNotFound
from app.models.enrichment import LandCoverObservation
from app.models.thermal import ThermalEvent
from app.services import source_health

logger = logging.getLogger(__name__)
SOURCE_ID = "esa_worldcover"
WINDOW_HALF_M = 750.0  # 1.5 km square, matching the OSM land-use search distance


def enrich_landcover(db: Session, ev: ThermalEvent, mark) -> None:
    """Sample WorldCover around the event. `mark(ev, step, status, detail)` records the enrichment step."""
    started = time.monotonic()
    try:
        res = raster.sample_worldcover(ev.latitude, ev.longitude, WINDOW_HALF_M)
    except ProviderNotFound:
        # no WorldCover tile covers this point (open sea): the provider has no data here, it did not fail
        mark(ev, "landcover", "no_data", "no WorldCover tile at this location (offshore or outside coverage)")
        return
    except ProviderError as exc:
        source_health.record_failure(db, SOURCE_ID, exc)
        category = source_health.error_category(exc)
        logger.warning("landcover for %s failed: %s", ev.public_id, exc)
        mark(ev, "landcover", "failed", category.replace("_", " "), category=category)
        return
    latency_ms = (time.monotonic() - started) * 1000
    db.execute(delete(LandCoverObservation).where(LandCoverObservation.event_id == ev.id))
    if res["valid_fraction"] < 0.5:
        # Offshore or outside coverage: say so, and do not store a class from a sliver of pixels.
        source_health.record_success(db, SOURCE_ID, latency_ms, 0)
        mark(ev, "landcover", "no_data", "no land-cover data at this location (offshore or outside coverage)")
        return
    db.add(LandCoverObservation(
        event_id=ev.id, source_id=SOURCE_ID, product=res["product"], window_m=res["window_m"], fractions=res["fractions"],
        dominant=res["dominant"], valid_fraction=res["valid_fraction"], source_ref=res["source_ref"], retrieved_at=datetime.now(UTC),
    ))
    source_health.record_success(db, SOURCE_ID, latency_ms, 1)
    mark(ev, "landcover", "ok", f"{res['product']}: {res['dominant']}")

