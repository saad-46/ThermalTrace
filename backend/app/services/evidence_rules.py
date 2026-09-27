"""The single definition of when each evidence stage of an event is *available*.

Every consumer is generated from RULES, so they cannot drift apart:
- the event page / mobile / report / share view (`availability()` for one event, used by investigation.stages),
- alert conditions (`completeness_sql()`, a per-event expression),
- analytics coverage (`coverage_sql()`, one set-based query over the filtered events).

A stage is available when its evidence exists. Anything else (pending, no data, not requested, failed, requires
analyst review) is decided by investigation.stages from the event's recorded state; those states never count as
available. Evidence availability is not confidence.
"""
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class StageRule:
    key: str
    title: str
    column: str | None = None  # predicate on the event row; {e} is the event alias
    table: str | None = None  # evidence table keyed by event_id
    where: str | None = None  # extra condition on that table (alias x)


RULES: tuple[StageRule, ...] = (
    StageRule("detection", "Thermal detection", column="{e}.observation_count > 0"),
    StageRule("clustering", "Event clustering", column="{e}.processed_at IS NOT NULL"),
    StageRule("persistence", "Temporal persistence", column="{e}.persistence_class IS NOT NULL"),
    # checked with nothing found is still evidence: no mapped facility within the search radius
    StageRule("facility_proximity", "Facility proximity", column="({e}.enrichment_state->'osm'->>'status') = 'ok'",
              table="event_facility_links"),
    StageRule("facility_attribution", "Facility attribution", table="event_facility_links", where="x.rank = 1"),
    StageRule("landcover", "Land cover", table="landcover_observations"),
    StageRule("weather", "Weather", table="weather_observations"),
    StageRule("satellite", "Satellite scene availability", table="satellite_observations"),
    StageRule("spectral", "Spectral analysis (NDVI / NBR)", table="imagery_analyses", where="x.status = 'ok'"),
    StageRule("classification", "Classification", column="{e}.classification IS NOT NULL"),
    StageRule("explainability", "Explainability", table="model_predictions", where="x.explanation IS NOT NULL"),
    StageRule("review", "Analyst review", table="analyst_reviews"),
    StageRule("final_status", "Final status",
              column="({e}.review_status IN ('analyst_confirmed', 'analyst_rejected', 'false_positive', 'reviewed') "
                     "OR {e}.confidence_state = 'CONFIRMED')"),
)
STAGE_KEYS = tuple(r.key for r in RULES)
TOTAL = len(RULES)


def predicate(rule: StageRule, e: str = "e") -> str:
    """Per-event SQL predicate (correlated), true when the stage is available."""
    parts = []
    if rule.column:
        parts.append(rule.column.format(e=e))
    if rule.table:
        cond = f" AND {rule.where}" if rule.where else ""
        parts.append(f"EXISTS (SELECT 1 FROM {rule.table} x WHERE x.event_id = {e}.id{cond})")
    return "(" + " OR ".join(parts) + ")"


def completeness_sql(e: str = "e") -> str:
    """Number of available stages for the event aliased `e` (0..TOTAL)."""
    return "(" + " + ".join(f"{predicate(r, e)}::int" for r in RULES) + ")"


def availability(db: Session, event_id) -> dict[str, bool]:
    """Which stages are available for one event, by exactly the rules alerts and analytics use."""
    cols = ", ".join(f"{predicate(r)} AS {r.key}" for r in RULES)
    row = db.execute(text(f"SELECT {cols} FROM thermal_events e WHERE e.id = :id"), {"id": event_id}).mappings().first()
    return {k: bool(row[k]) for k in STAGE_KEYS} if row else dict.fromkeys(STAGE_KEYS, False)


def coverage_sql(where: str) -> str:
    """Per-stage counts over the events matching `where` (event alias e), set-based: the filtered events are
    materialised once and every evidence table is reduced to them before a hash join (a correlated EXISTS per event,
    or an IN over tables of hundreds of thousands of rows, is far slower at a year's scale)."""
    col_rules = [r for r in RULES if r.column]
    ev_cols = ", ".join(f"{r.column.format(e='e')} AS c_{r.key}" for r in col_rules)
    ctes = [f"ev AS MATERIALIZED (SELECT e.id, {ev_cols} FROM thermal_events e WHERE {where})"]
    joins = []
    for r in RULES:
        if r.table:
            cond = f" WHERE {r.where}" if r.where else ""
            ctes.append(f"t_{r.key} AS MATERIALIZED (SELECT DISTINCT x.event_id FROM {r.table} x JOIN ev ON ev.id = x.event_id{cond})")
            joins.append(f"LEFT JOIN t_{r.key} ON t_{r.key}.event_id = ev.id")

    def counted(r: StageRule) -> str:
        parts = ([f"ev.c_{r.key}"] if r.column else []) + ([f"t_{r.key}.event_id IS NOT NULL"] if r.table else [])
        return f"count(*) FILTER (WHERE {' OR '.join(parts)}) AS {r.key}"

    return (f"WITH {', '.join(ctes)} SELECT count(*) AS events, " + ", ".join(counted(r) for r in RULES)
            + f" FROM ev {' '.join(joins)}")
