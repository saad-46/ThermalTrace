"""Event clustering: group detections into thermal events (audit D7).

Rule (documented in docs/GIS.md):
  A detection joins an event if it lies within CLUSTER_RADIUS_M of the event's running centroid
  AND its acquisition time is within CLUSTER_GAP_DAYS of the event's last detection.
  Otherwise it seeds a new event. Detections are processed in acquisition order, so the result
  is deterministic and incremental (new data extends open events; stale events stay closed).

A uniform grid (cell ≈ radius) limits candidate lookups to the 3×3 neighbourhood.
"""
import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.gis.geo import haversine_m
from app.models.thermal import ThermalDetection, ThermalEvent

logger = logging.getLogger(__name__)


@dataclass
class _Cluster:
    id: uuid.UUID
    lat: float
    lon: float
    n: int
    last: datetime
    is_new: bool
    members: list[uuid.UUID] = field(default_factory=list)

    def absorb(self, lat: float, lon: float, when: datetime, det_id: uuid.UUID) -> None:
        self.lat = (self.lat * self.n + lat) / (self.n + 1)
        self.lon = (self.lon * self.n + lon) / (self.n + 1)
        self.n += 1
        self.last = max(self.last, when)
        self.members.append(det_id)


class _Grid:
    def __init__(self, cell_deg: float):
        self.cell = cell_deg
        self.cells: dict[tuple[int, int], list[_Cluster]] = {}

    def key(self, lat: float, lon: float) -> tuple[int, int]:
        return int(math.floor(lat / self.cell)), int(math.floor(lon / self.cell))

    def add(self, c: _Cluster) -> None:
        self.cells.setdefault(self.key(c.lat, c.lon), []).append(c)

    def move(self, c: _Cluster, old_key: tuple[int, int]) -> None:
        new_key = self.key(c.lat, c.lon)
        if new_key != old_key:
            self.cells[old_key].remove(c)
            self.cells.setdefault(new_key, []).append(c)

    def near(self, lat: float, lon: float):
        ky, kx = self.key(lat, lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yield from self.cells.get((ky + dy, kx + dx), ())


def _new_public_id(db: Session, when: datetime) -> str:
    n = db.execute(text("SELECT nextval('thermal_event_public_seq')")).scalar_one()
    return f"TT-{when:%Y}-{n:06d}"


def assign_detections(db: Session, limit: int = 50_000) -> set[uuid.UUID]:
    """Assign unassigned detections to events. Returns ids of events that changed."""
    radius = settings.cluster_radius_m
    gap = timedelta(days=settings.cluster_gap_days)
    pending = db.execute(
        select(ThermalDetection.id, ThermalDetection.latitude, ThermalDetection.longitude,
               ThermalDetection.acq_datetime, ThermalDetection.data_mode)
        .where(ThermalDetection.event_id.is_(None))
        .order_by(ThermalDetection.acq_datetime)
        .limit(limit)
    ).all()
    if not pending:
        return set()

    earliest = pending[0].acq_datetime
    cell_deg = radius / 111_320.0
    grid = _Grid(cell_deg)
    open_events = db.execute(
        select(ThermalEvent.id, ThermalEvent.latitude, ThermalEvent.longitude, ThermalEvent.observation_count,
               ThermalEvent.last_detected)
        .where(ThermalEvent.last_detected >= earliest - gap)
    ).all()
    for ev in open_events:
        grid.add(_Cluster(ev.id, ev.latitude, ev.longitude, max(ev.observation_count, 1), ev.last_detected, False))

    created: list[_Cluster] = []
    touched: dict[uuid.UUID, _Cluster] = {}
    for det in pending:
        best, best_d = None, radius
        for c in grid.near(det.latitude, det.longitude):
            if det.acq_datetime - c.last > gap or c.last - det.acq_datetime > gap:
                continue
            d = haversine_m(det.latitude, det.longitude, c.lat, c.lon)
            if d <= best_d:
                best, best_d = c, d
        if best is None:
            best = _Cluster(uuid.uuid4(), det.latitude, det.longitude, 0, det.acq_datetime, True)
            grid.add(best)
            created.append(best)
            old_key = grid.key(best.lat, best.lon)
        else:
            old_key = grid.key(best.lat, best.lon)
        best.absorb(det.latitude, det.longitude, det.acq_datetime, det.id)
        grid.move(best, old_key)
        touched[best.id] = best

    modes = {d.id: d.data_mode for d in pending}
    for c in created:
        first_member_mode = modes[c.members[0]]
        db.add(ThermalEvent(
            id=c.id, public_id=_new_public_id(db, c.last), geom=f"SRID=4326;POINT({c.lon} {c.lat})",
            latitude=c.lat, longitude=c.lon, data_mode=first_member_mode, first_detected=c.last, last_detected=c.last,
            observation_count=0, sensor_count=0, sensors=[], datasets=[], days_active=0, duration_hours=0,
            status="active", review_status="unreviewed", enrichment_state={},
        ))
    db.flush()
    for c in touched.values():
        db.execute(update(ThermalDetection).where(ThermalDetection.id.in_(c.members)).values(event_id=c.id))
    logger.info("clustering: %d detections -> %d touched events (%d new)", len(pending), len(touched), len(created))
    return set(touched)


_STATS_SQL = text(
    """
    WITH agg AS (
      SELECT d.event_id,
             ST_SetSRID(ST_MakePoint(avg(d.longitude), avg(d.latitude)), 4326)::geography AS centroid,
             avg(d.latitude) AS lat, avg(d.longitude) AS lon,
             min(d.acq_datetime) AS first_detected, max(d.acq_datetime) AS last_detected,
             count(*) AS n,
             count(DISTINCT d.satellite) AS sensor_count,
             array_agg(DISTINCT d.satellite ORDER BY d.satellite) AS sensors,
             array_agg(DISTINCT d.dataset ORDER BY d.dataset) AS datasets,
             count(DISTINCT d.acq_date) AS days_active,
             max(d.frp) AS frp_max, avg(d.frp) AS frp_mean, sum(d.frp) AS frp_sum, stddev_samp(d.frp) AS frp_std,
             avg(d.confidence_pct) AS conf_mean,
             avg(CASE WHEN d.daynight = 'N' THEN 1.0 WHEN d.daynight = 'D' THEN 0.0 END) AS night_fraction,
             CASE WHEN bool_or(d.data_mode = 'demo') THEN 'demo'
                  WHEN bool_and(d.data_mode = 'historical') THEN 'historical' ELSE 'live' END AS data_mode,
             CASE WHEN count(*) >= 3 THEN
               ST_Buffer(ST_ConvexHull(ST_Collect(d.geom::geometry))::geography, 200)
             ELSE ST_Buffer(ST_Centroid(ST_Collect(d.geom::geometry))::geography, 375) END AS footprint
      FROM thermal_detections d
      WHERE d.event_id = ANY(:ids)
      GROUP BY d.event_id
    )
    UPDATE thermal_events e SET
      geom = agg.centroid, latitude = agg.lat, longitude = agg.lon,
      first_detected = agg.first_detected, last_detected = agg.last_detected,
      observation_count = agg.n, sensor_count = agg.sensor_count, sensors = agg.sensors, datasets = agg.datasets,
      days_active = agg.days_active,
      duration_hours = EXTRACT(EPOCH FROM (agg.last_detected - agg.first_detected)) / 3600.0,
      frp_max = agg.frp_max, frp_mean = agg.frp_mean, frp_sum = agg.frp_sum, frp_std = agg.frp_std,
      confidence_mean = agg.conf_mean, night_fraction = agg.night_fraction, data_mode = agg.data_mode,
      footprint = ST_GeogFromWKB(ST_AsBinary(ST_GeometryN(ST_Multi(agg.footprint::geometry), 1))),
      status = CASE WHEN agg.last_detected >= now() - make_interval(days => :gap) THEN 'active' ELSE 'dormant' END,
      updated_at = now()
    FROM agg WHERE e.id = agg.event_id
    """
)

_OBS_SQL = text(
    """
    DELETE FROM thermal_observations WHERE event_id = ANY(:ids);
    INSERT INTO thermal_observations (event_id, obs_date, detection_count, frp_max, frp_sum, sensors, night_count,
                                      first_at, last_at, spread_m)
    SELECT d.event_id, d.acq_date, count(*), max(d.frp), sum(d.frp), array_agg(DISTINCT d.satellite),
           count(*) FILTER (WHERE d.daynight = 'N'), min(d.acq_datetime), max(d.acq_datetime),
           max(ST_Distance(d.geom, e.geom))
    FROM thermal_detections d JOIN thermal_events e ON e.id = d.event_id
    WHERE d.event_id = ANY(:ids)
    GROUP BY d.event_id, d.acq_date;
    """
)


def refresh_event_stats(db: Session, event_ids: set[uuid.UUID]) -> None:
    if not event_ids:
        return
    ids = list(event_ids)
    for i in range(0, len(ids), 2000):
        chunk = ids[i : i + 2000]
        db.execute(_STATS_SQL, {"ids": chunk, "gap": settings.cluster_gap_days})
        for stmt in _OBS_SQL.text.split(";"):
            if stmt.strip():
                db.execute(text(stmt), {"ids": chunk})


def refresh_activity_status(db: Session) -> int:
    """Age active events into dormant once they exceed the gap tolerance."""
    res = db.execute(
        text("UPDATE thermal_events SET status = 'dormant', updated_at = now() "
             "WHERE status = 'active' AND last_detected < now() - make_interval(days => :gap)"),
        {"gap": settings.cluster_gap_days},
    )
    return res.rowcount or 0
