"""Persistence engine — transparent metrics, then a documented rule to a class.

Metrics (all stored on the event, never a black-box label):
  active_days          distinct UTC days with ≥1 detection
  span_days            calendar days between first and last detection (inclusive)
  observation_frequency active_days / span_days
  longest_gap_days     largest run of days without detections inside the span
  frp_cv               coefficient of variation of daily max FRP (low = steady source)
  sensor_agreement     distinct platforms / 5 (Terra, Aqua, S-NPP, NOAA-20, NOAA-21)
  recurrence_count     earlier *separate* events within 1.5 km in the prior 365 days
  history_window_days  how many days of FIRMS history exist in the database at all — bounds
                       what persistence can be claimed (7 days of data cannot prove a
                       year-long source)

Classes:
  PERSISTENT  (active_days ≥ 5 and frequency ≥ 0.5 and span ≥ 5) or recurrence_count ≥ 3
  RECURRING   active_days ≥ 2 and span ≥ 2, or recurrence_count ≥ 1
  TRANSIENT   otherwise
"""
import math
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

N_PLATFORMS = 5


@dataclass
class PersistenceMetrics:
    active_days: int
    span_days: int
    observation_frequency: float
    longest_gap_days: int
    frp_cv: float | None
    sensor_agreement: float
    recurrence_count: int
    history_window_days: int
    recurrence_pattern: str
    score: float
    persistence_class: str
    rationale: str

    def as_dict(self) -> dict:
        return asdict(self)


def classify_persistence(
    obs_dates: list[date], daily_frp_max: list[float | None], sensor_count: int, recurrence_count: int,
    history_window_days: int,
) -> PersistenceMetrics:
    days = sorted(set(obs_dates))
    if not days:
        raise ValueError("event has no observations")
    span = (days[-1] - days[0]).days + 1
    active = len(days)
    gaps = [(b - a).days - 1 for a, b in zip(days, days[1:], strict=False)]
    longest_gap = max(gaps, default=0)
    freq = active / span
    frp_vals = [v for v in daily_frp_max if v is not None]
    frp_cv = None
    if len(frp_vals) >= 3:
        mean = sum(frp_vals) / len(frp_vals)
        if mean > 0:
            var = sum((v - mean) ** 2 for v in frp_vals) / (len(frp_vals) - 1)
            frp_cv = round(math.sqrt(var) / mean, 3)
    sensor_agreement = round(min(sensor_count, N_PLATFORMS) / N_PLATFORMS, 2)

    if (active >= 5 and freq >= 0.5 and span >= 5) or recurrence_count >= 3:
        cls = "persistent"
        why = (f"active on {active} of {span} days" if active >= 5 else f"{recurrence_count} earlier separate events at this location")
    elif (active >= 2 and span >= 2) or recurrence_count >= 1:
        cls = "recurring"
        why = f"active on {active} day(s) over a {span}-day span" + (
            f"; {recurrence_count} earlier event(s) at this location" if recurrence_count else "")
    else:
        cls = "transient"
        why = f"observed on a single day ({active} active day, no earlier events within 1.5 km)"

    if span >= history_window_days - 1 and cls != "transient":
        why += f" — activity spans the full {history_window_days}-day history available, so true duration may be longer"

    pattern = "continuous" if freq >= 0.8 and span > 1 else ("intermittent" if active > 1 else "single-day")
    if recurrence_count >= 1:
        pattern += " + repeat site"

    score = (
        0.35 * min(active / 10.0, 1.0)
        + 0.25 * freq * (1.0 if span > 1 else 0.3)
        + 0.20 * min(span / 30.0, 1.0)
        + 0.20 * min(recurrence_count / 3.0, 1.0)
    )
    return PersistenceMetrics(active, span, round(freq, 3), longest_gap, frp_cv, sensor_agreement, recurrence_count,
                              history_window_days, pattern, round(score, 3), cls, why)


_OBS_Q = text("SELECT obs_date, frp_max FROM thermal_observations WHERE event_id = :id ORDER BY obs_date")
_RECUR_Q = text(
    """SELECT count(*) FROM thermal_events o, thermal_events e
       WHERE e.id = :id AND o.id <> e.id AND o.last_detected < e.first_detected
         AND o.last_detected >= e.first_detected - interval '365 days'
         AND ST_DWithin(o.geom, e.geom, 1500)"""
)


def history_window_days(db: Session) -> int:
    # acq_date is the UTC date of acq_datetime; min/max of the indexed timestamp is an index lookup, whereas
    # acq_date (unindexed) needs a full scan of every detection.
    row = db.execute(text("SELECT (min(acq_datetime) AT TIME ZONE 'UTC')::date, (max(acq_datetime) AT TIME ZONE 'UTC')::date "
                          "FROM thermal_detections")).one()
    if row[0] is None:
        return 0
    return (row[1] - row[0]).days + 1


def compute_for_event(db: Session, event_id, sensor_count: int, window: int) -> PersistenceMetrics:
    rows = db.execute(_OBS_Q, {"id": event_id}).all()
    recurrence = db.execute(_RECUR_Q, {"id": event_id}).scalar_one()
    return classify_persistence([r.obs_date for r in rows], [r.frp_max for r in rows], sensor_count, recurrence, window)

