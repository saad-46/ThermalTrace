"""Event queries. All spatial/aggregate SQL for events lives here — routers never build SQL."""
import math
import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.db import like as like_pattern
from app.processing.confidence import display_state

SORTS = {
    "last_detected": "e.last_detected DESC",
    "confidence": "e.confidence_score DESC NULLS LAST",
    "frp": "e.frp_max DESC NULLS LAST",
    "persistence": "e.persistence_score DESC NULLS LAST",
    "observations": "e.observation_count DESC",
    "first_detected": "e.first_detected DESC",
    "priority": "e.priority_score DESC NULLS LAST",
}

_LIST_COLS = """
  e.id, e.public_id, e.latitude, e.longitude, e.data_mode, e.first_detected, e.last_detected,
  e.observation_count, e.sensor_count, e.sensors, e.days_active, e.duration_hours, e.frp_max, e.frp_mean,
  e.night_fraction, e.status, e.review_status, e.persistence_class, e.persistence_score, e.classification,
  e.classification_probability, e.confidence_score, e.confidence_state, e.data_quality,
  e.nearest_facility_distance_m, e.admin_state, e.admin_district, e.country, e.assigned_to, e.priority_score,
  e.place_name, e.place_admin1, e.place_country, e.place_distance_m,
  f.name AS nearest_facility_name, f.facility_type AS nearest_facility_type
"""


def _filters(p: dict) -> tuple[str, dict]:
    clauses, params = ["1=1"], {}
    if p.get("bbox"):
        w, s, e_, n = p["bbox"]
        clauses.append("e.geom && ST_MakeEnvelope(:w, :s, :e, :n, 4326)::geography")
        params.update(w=w, s=s, e=e_, n=n)
    if p.get("since"):
        clauses.append("e.last_detected >= :since")
        params["since"] = p["since"]
    if p.get("until"):
        clauses.append("e.first_detected <= :until")
        params["until"] = p["until"]
    for key, col in (("classification", "e.classification"), ("persistence", "e.persistence_class"),
                     ("confidence_state", "e.confidence_state"), ("status", "e.status"),
                     ("review_status", "e.review_status"), ("data_mode", "e.data_mode"),
                     ("data_quality", "e.data_quality")):
        if p.get(key):
            clauses.append(f"{col} = ANY(:{key})")
            params[key] = p[key]
    if p.get("sensor"):
        clauses.append("e.sensors && :sensor")
        params["sensor"] = p["sensor"]
    if p.get("facility_type"):
        clauses.append("EXISTS (SELECT 1 FROM event_facility_links l JOIN facilities ff ON ff.id = l.facility_id "
                       "WHERE l.event_id = e.id AND ff.facility_type = ANY(:facility_type) AND l.distance_m <= 5000)")
        params["facility_type"] = p["facility_type"]
    if p.get("min_frp") is not None:
        clauses.append("e.frp_max >= :min_frp")
        params["min_frp"] = p["min_frp"]
    if p.get("min_confidence") is not None:
        clauses.append("e.confidence_score >= :min_confidence")
        params["min_confidence"] = p["min_confidence"]
    if p.get("min_priority") is not None:
        clauses.append("e.priority_score >= :min_priority")
        params["min_priority"] = p["min_priority"]
    if p.get("min_observations") is not None:
        clauses.append("e.observation_count >= :min_observations")
        params["min_observations"] = p["min_observations"]
    if p.get("assigned_to"):
        clauses.append("e.assigned_to = :assigned_to")
        params["assigned_to"] = p["assigned_to"]
    if p.get("region", "india") == "india":
        # Known to be outside India's boundary: excluded. NULL (not yet classified / no boundary) is kept.
        clauses.append("e.in_india IS NOT FALSE")
    if p.get("q") and not re.sub(r"[\W_]+", "", p["q"]):
        clauses.append("false")  # only punctuation / wildcards: matches no id or name
    elif p.get("q"):
        clauses.append("(e.public_id ILIKE :q OR e.admin_district ILIKE :q OR e.admin_state ILIKE :q OR f.name ILIKE :q "
                       "OR e.place_name ILIKE :q OR e.place_admin1 ILIKE :q)")
        params["q"] = like_pattern.contains(p["q"])
    return " AND ".join(clauses), params


def _with_display(row: dict) -> dict:
    row["display_state"] = display_state(row.get("confidence_state") or "INSUFFICIENT_EVIDENCE", row["review_status"])
    return row


def list_events(db: Session, p: dict, sort: str, limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = _filters(p)
    base = f"FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id WHERE {where}"
    # The facility join only matters for the count when the text filter searches facility names (it is a
    # many-to-one join, so it never changes the number of rows); skipping it makes the full count ~4x faster.
    count_from = base if p.get("q") else f"FROM thermal_events e WHERE {where}"
    total = db.execute(text(f"SELECT count(*) {count_from}"), params).scalar_one()
    rows = db.execute(
        text(f"SELECT {_LIST_COLS} {base} ORDER BY {SORTS.get(sort, SORTS['last_detected'])}, e.id LIMIT :limit OFFSET :offset"),
        {**params, "limit": limit, "offset": offset},
    ).mappings().all()
    return [_with_display(dict(r)) for r in rows], total


def get_summary(db: Session, event_id: uuid.UUID) -> dict:
    row = db.execute(text(f"SELECT {_LIST_COLS} FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id "
                          "WHERE e.id = :id"), {"id": event_id}).mappings().first()
    if row is None:
        raise NotFound("Event not found")
    return _with_display(dict(row))


def events_geojson(db: Session, p: dict, limit: int) -> dict:
    """Compact GeoJSON for the map: only properties the map styles/filters on. Viewport-bounded."""
    where, params = _filters(p)
    rows = db.execute(text(f"""
        SELECT e.id, e.public_id, e.longitude, e.latitude, e.classification, e.persistence_class, e.confidence_state,
               e.review_status, e.confidence_score, e.frp_max, e.observation_count, e.status, e.data_mode, e.last_detected,
               e.priority_score
        FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id
        WHERE {where} ORDER BY e.last_detected DESC LIMIT :limit"""), {**params, "limit": limit + 1}).mappings().all()
    truncated = len(rows) > limit
    feats = []
    for r in rows[:limit]:
        feats.append({
            "type": "Feature", "id": str(r["id"]),
            "geometry": {"type": "Point", "coordinates": [round(r["longitude"], 5), round(r["latitude"], 5)]},
            "properties": {
                "id": str(r["id"]), "public_id": r["public_id"], "classification": r["classification"],
                "persistence": r["persistence_class"],
                "state": display_state(r["confidence_state"] or "INSUFFICIENT_EVIDENCE", r["review_status"]),
                "confidence": round(r["confidence_score"] or 0, 2), "frp": round(r["frp_max"] or 0, 1),
                "obs": r["observation_count"], "status": r["status"], "mode": r["data_mode"],
                "last": r["last_detected"].isoformat(), "priority": round(r["priority_score"] or 0),
            },
        })
    return {"type": "FeatureCollection", "features": feats, "truncated": truncated, "limit": limit}


def _event_row(db: Session, event_id: uuid.UUID) -> dict:
    row = db.execute(text(f"SELECT {_LIST_COLS}, e.persistence_metrics, e.confidence_components, e.data_quality_detail, "
                          "e.fingerprint, e.priority_components, e.enrichment_state, e.datasets, e.frp_sum, e.frp_std, e.confidence_mean, "
                          "e.processed_at, e.processing_version, e.created_at, e.updated_at, ST_AsGeoJSON(e.footprint::geometry)::json AS footprint "
                          "FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id "
                          "WHERE e.id = :id"), {"id": event_id}).mappings().first()
    if row is None:
        raise NotFound("Event not found")
    return _with_display(dict(row))


def resolve_event_id(db: Session, ref: str) -> uuid.UUID:
    try:
        return uuid.UUID(ref)
    except ValueError:
        eid = db.execute(text("SELECT id FROM thermal_events WHERE public_id = :p"), {"p": ref}).scalar()
        if eid is None:
            raise NotFound("Event not found") from None
        return eid


def get_bundle(db: Session, event_id: uuid.UUID, user_id: uuid.UUID | None = None) -> dict:
    """The full investigation bundle: event, observations, facilities, land, weather, satellite,
    predictions, classification, evidence, reviews, timeline."""
    ev = _event_row(db, event_id)
    eid = ev["id"]
    q = lambda sql, **kw: [dict(r) for r in db.execute(text(sql), {"id": eid, **kw}).mappings().all()]  # noqa: E731
    ev["detections"] = q("""SELECT id, latitude, longitude, acq_datetime, sensor, satellite, dataset, confidence_raw,
                              confidence_pct, frp, brightness, brightness_2, scan, track, daynight, version, data_mode,
                              source_ref, retrieved_at FROM thermal_detections WHERE event_id = :id
                              ORDER BY acq_datetime LIMIT 1000""")
    ev["observations"] = q("""SELECT obs_date, detection_count, frp_max, frp_sum, sensors, night_count, first_at, last_at,
                                spread_m FROM thermal_observations WHERE event_id = :id ORDER BY obs_date""")
    ev["facilities"] = q("""SELECT f.id, f.name, f.facility_type, f.operator, f.status, f.capacity_value, f.capacity_unit,
                              f.confidence, f.primary_source, f.source_count, f.latitude, f.longitude,
                              l.distance_m, l.bearing_deg, l.rank, l.attribution_score, l.computed_at,
                              (SELECT json_agg(json_build_object('source', s.source_id, 'external_id', s.external_id,
                                  'url', s.source_url, 'dataset_version', s.dataset_version,
                                  'published_at', s.published_at, 'retrieved_at', s.retrieved_at))
                               FROM facility_sources s WHERE s.facility_id = f.id) AS sources
                            FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
                            WHERE l.event_id = :id ORDER BY l.rank""")
    ev["land"] = q("""SELECT category, name, distance_m, osm_type, osm_id, retrieved_at FROM land_context
                      WHERE event_id = :id ORDER BY distance_m LIMIT 30""")
    ev["landcover"] = (q("""SELECT product, window_m, fractions, dominant, valid_fraction, source_ref, retrieved_at
                           FROM landcover_observations WHERE event_id = :id""") or [None])[0]
    ev["imagery_analysis"] = (q("""SELECT status, reason, finding, window_m, before_scene, after_scene, deltas, method,
                                  retrieved_at FROM imagery_analyses WHERE event_id = :id""") or [None])[0]
    ev["weather"] = q("""SELECT kind, source_id, dataset, observed_at, retrieved_at, temperature_c, humidity_pct,
                           wind_speed_ms, wind_direction_deg, precipitation_mm, pressure_hpa, weather_code, condition
                         FROM weather_observations WHERE event_id = :id ORDER BY observed_at DESC""")
    # Relation to the event from its current times: an event that keeps growing turns an earlier "after" into "during".
    ev["satellite"] = q("""SELECT s.id, s.provider, s.source_id, s.collection, s.item_id, s.platform, s.acquired_at, s.cloud_cover,
                             s.processing_level,
                             CASE WHEN s.acquired_at < e.first_detected THEN 'before'
                                  WHEN s.acquired_at > e.last_detected + interval '12 hours' THEN 'after'
                                  ELSE 'during' END AS relation,
                             s.thumbnail_url, s.item_url, s.bbox, s.retrieved_at
                           FROM satellite_observations s JOIN thermal_events e ON e.id = s.event_id
                           WHERE s.event_id = :id ORDER BY s.acquired_at""")
    ev["classification_current"] = (q("""SELECT id, source_class, persistence_class, probability, confidence_score,
                                   confidence_state, confidence_components, primary_model_id, supporting_model_ids,
                                   pipeline_version, created_at FROM classifications
                                 WHERE event_id = :id AND is_current ORDER BY created_at DESC LIMIT 1""") or [None])[0]
    ev["classification_history"] = q("""SELECT source_class, persistence_class, confidence_score, confidence_state,
                                        primary_model_id, created_at FROM classifications WHERE event_id = :id
                                        ORDER BY created_at DESC LIMIT 20""")
    ev["predictions"] = q("""SELECT DISTINCT ON (model_version_id) model_version_id, prediction, probability,
                               probabilities, features_used, explanation, created_at
                             FROM model_predictions WHERE event_id = :id ORDER BY model_version_id, created_at DESC""")
    ev["evidence"] = q("""SELECT category, knowledge_type, direction, strength, statement, value, provenance
                          FROM classification_evidence WHERE event_id = :id
                          ORDER BY CASE category WHEN 'firms' THEN 1 WHEN 'persistence' THEN 2 WHEN 'history' THEN 3
                            WHEN 'facility' THEN 4 WHEN 'land' THEN 5 WHEN 'landcover' THEN 6 WHEN 'weather' THEN 7
                            WHEN 'satellite' THEN 8 ELSE 9 END, strength DESC""")
    ev["reviews"] = q("""SELECT r.id, r.decision, r.source_class, r.persistence_class, r.false_positive_reason, r.notes,
                           r.system_source_class, r.system_confidence_score, r.previous_status, r.new_status, r.created_at,
                           u.full_name AS reviewer
                         FROM analyst_reviews r LEFT JOIN users u ON u.id = r.user_id WHERE r.event_id = :id
                         ORDER BY r.created_at DESC LIMIT 200""")
    ev["notes"] = q("""SELECT n.id, n.kind, n.body, n.url, n.created_at, u.full_name AS author FROM investigation_notes n
                       LEFT JOIN users u ON u.id = n.user_id WHERE n.event_id = :id ORDER BY n.created_at DESC LIMIT 200""")
    # alerts belong to the user whose rule raised them: only the caller's own (none when no user, e.g. a PDF report)
    ev["alerts"] = q("""SELECT a.id, a.title, a.severity, a.triggered_at, a.status, r.name AS rule_name FROM alerts a
                        JOIN alert_rules r ON r.id = a.rule_id WHERE a.event_id = :id AND a.user_id = :uid
                        ORDER BY a.triggered_at DESC""", uid=user_id) if user_id else []
    ev["investigation"] = (q("""SELECT i.id, i.status, i.priority, i.summary, i.opened_at, i.closed_at, i.assigned_to,
                                   u.full_name AS assignee FROM investigations i LEFT JOIN users u ON u.id = i.assigned_to
                                 WHERE i.event_id = :id""") or [None])[0]
    # On-demand work for this event (latest per kind and step set): lets the page show "searching…" across reloads
    # and a failed job instead of an unexplained empty tab. Only the error's type is exposed, never its message.
    ev["jobs"] = q("""SELECT DISTINCT ON (kind, steps) kind, steps, status, attempts, max_attempts, created_at, started_at,
                             finished_at, error_type
                      FROM (SELECT kind, COALESCE(payload->'steps', '[]'::jsonb) AS steps, status, attempts, max_attempts,
                                   created_at, started_at, finished_at,
                                   NULLIF(split_part(COALESCE(error, ''), ':', 1), '') AS error_type
                            FROM jobs WHERE payload ? 'event_id' AND payload->>'event_id' = CAST(:id AS text)
                              AND kind IN ('enrich_event', 'imagery_analysis') AND created_at > now() - interval '7 days') j
                      ORDER BY kind, steps, created_at DESC""")
    ev["imagery_readiness"] = imagery_readiness(ev)
    from app.services import evidence_rules, investigation

    stages = investigation.stages(ev, evidence_rules.availability(db, eid))
    ev["evidence_stages"] = {"stages": stages, "completeness": investigation.completeness(stages),
                             "freshness": investigation.freshness(ev)}
    ev["timeline"] = build_timeline(ev)
    ev["evidence_matrix"] = evidence_matrix(ev)
    return ev


def imagery_readiness(ev: dict) -> dict:
    """Whether NDVI/NBR can be attempted, by the same rule the imagery-analysis endpoint enforces."""
    from types import SimpleNamespace

    from app.services import imagery

    scenes = [SimpleNamespace(acquired_at=s["acquired_at"], cloud_cover=s["cloud_cover"]) for s in ev["satellite"]]
    ready, reason = imagery.readiness(SimpleNamespace(**{k: ev[k] for k in ("enrichment_state", "first_detected", "last_detected")}), scenes)
    return {"ready": ready, "reason": reason, "max_cloud": imagery.MAX_CLOUD}


def build_timeline(ev: dict) -> list[dict]:
    from app.services.investigation import timeline

    return timeline(ev)


def _missing(status: str | None, category: str | None, none_found: str, not_yet: str) -> tuple[str, str]:
    """Availability and detail for evidence that is not present, from the step's recorded outcome. A provider failure
    is "failed", an answer without data is "no data", and a step never run is "not requested"; never mixed up."""
    if status == "failed":
        return "failed", f"provider failure ({(category or 'error').replace('_', ' ')})"
    if status in ("ok", "no_data"):
        return "no data", none_found
    return "not requested", not_yet


def _landcover_row(wc: dict | None, step: dict) -> dict:
    if wc is None:
        avail, detail = _missing(step.get("status"), step.get("category"), "no WorldCover data here", "not yet retrieved")
        return {"type": "Land cover", "availability": avail, "strength": 0, "detail": detail}
    share = (wc["fractions"] or {}).get(wc["dominant"], 0)
    return {"type": "Land cover", "availability": "available", "strength": round(share, 2),
            "detail": f"{(wc['dominant'] or '').replace('_', ' ')} {share:.0%} (ESA WorldCover 2021)"}


def _imagery_row(ia: dict | None) -> dict:
    if ia is None:
        return {"type": "Spectral change", "availability": "not requested", "strength": 0,
                "detail": "NDVI/NBR change not computed (request it from the imagery tab)"}
    if ia["status"] == "failed":
        return {"type": "Spectral change", "availability": "failed", "strength": 0, "detail": ia["reason"]}
    if ia["status"] != "ok":
        return {"type": "Spectral change", "availability": "no data", "strength": 0, "detail": ia["reason"]}
    d = ia["deltas"] or {}
    return {"type": "Spectral change", "availability": "available",
            "strength": {"vegetation_loss_consistent": 0.8, "partial_change": 0.4}.get(ia["finding"], 0.1),
            "detail": f"NDVI change {d.get('ndvi', 0):+.2f}, NBR change {d.get('nbr', 0):+.2f} ({ia['finding'].replace('_', ' ')})"}


def evidence_matrix(ev: dict) -> list[dict]:
    """Evidence Type | Availability | Strength — the analyst's at-a-glance evidence quality grid. Availability is one
    of available / no data / not requested / failed (see _missing); strength is not a probability."""
    state = ev.get("enrichment_state") or {}

    def step(name):
        return state.get(name) or {}

    def missing(name, none_found, not_yet):
        return _missing(step(name).get("status"), step(name).get("category"), none_found, not_yet)

    comps = {c["name"]: c for c in ((ev.get("confidence_components") or {}).get("components") or [])}
    top_fac = ev["facilities"][0] if ev["facilities"] else None
    scenes = ev["satellite"]
    best_cloud = min((s["cloud_cover"] for s in scenes if s["cloud_cover"] is not None), default=None)
    pm = ev.get("persistence_metrics") or {}
    gbm = next((p for p in ev["predictions"] if p["model_version_id"].startswith("lgbm")), None)
    fac_a, fac_d = ("available", f"{top_fac['name'] or top_fac['facility_type']} at {top_fac['distance_m']:.0f} m") if top_fac         else missing("osm", "none mapped within 10 km", "not yet retrieved")
    sat_a, sat_d = ("available", f"{len(scenes)} scene(s)" + (f", best {best_cloud:.0f}% cloud" if best_cloud is not None else ""))         if scenes else missing("satellite", "no suitable scene under the cloud limit", "not yet searched")
    w_a, w_d = ("available", ev["weather"][0]["dataset"]) if ev["weather"] else missing("weather", "no weather for this time", "not yet retrieved")
    return [
        {"type": "FIRMS", "availability": "available", "strength": comps.get("sensor_agreement", {}).get("value", 0),
         "detail": f"{ev['observation_count']} detections, {ev['sensor_count']} platform(s)"},
        {"type": "Facility", "availability": fac_a, "strength": round(top_fac["attribution_score"] / 0.6, 2) if top_fac else 0,
         "detail": fac_d},
        {"type": "Satellite", "availability": sat_a, "strength": comps.get("satellite", {}).get("value", 0), "detail": sat_d},
        _landcover_row(ev.get("landcover"), step("landcover")),
        _imagery_row(ev.get("imagery_analysis")),
        {"type": "Weather", "availability": w_a, "strength": 1.0 if ev["weather"] else 0, "detail": w_d},
        {"type": "History", "availability": "available", "strength": ev.get("persistence_score") or 0,
         "detail": f"{pm.get('active_days', '–')} active day(s) of {pm.get('history_window_days', '–')} in history"},
        {"type": "ML", "availability": "available" if gbm else "rules only", "strength": ev.get("classification_probability") or 0,
         "detail": f"{ev.get('classification')} (class score {ev.get('classification_probability') or 0:.2f})"},
    ]


# Fingerprint expressions; must match the ix_events_fp_knn index (migration 0009) exactly.
_FP_DIMS = ("intensity", "persistence", "facility_proximity", "night_share", "sensor_agreement")
_FP_TYPE = "coalesce(e.fingerprint->>'facility_type', '')"
_FP_CUBE = "cube(ARRAY[" + ", ".join(f"coalesce((e.fingerprint->>'{d}')::float8, 0)" for d in _FP_DIMS) + "])"
# A different facility type adds this under the square root of the distance.
_FP_TYPE_PENALTY = 0.3


def _fp_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def similar_events(db: Session, event_id: uuid.UUID, limit: int = 8) -> list[dict]:
    """Nearest events by thermal fingerprint (excluding the event itself).

    distance = sqrt(sum of squared differences of the five numeric dimensions + 0.3 if the facility type differs).
    The penalty is the same for every event of another type, so the nearest events are the union of the index-ordered
    (KNN) nearest of the same type and of the other types; merging the two gives exactly the full-scan result."""
    me = db.execute(text("SELECT fingerprint, geom FROM thermal_events WHERE id = :id"), {"id": event_id}).first()
    if me is None or not me.fingerprint:
        return []
    vec = [_fp_float(me.fingerprint.get(d)) for d in _FP_DIMS]
    ftype = me.fingerprint.get("facility_type") or ""
    params = {"id": event_id, "t": ftype, "limit": limit, **{f"v{i}": v for i, v in enumerate(vec)}}
    target = "cube(ARRAY[:v0, :v1, :v2, :v3, :v4]::float8[])"

    def walk(same_type: bool) -> list[dict]:
        # Walk the KNN index in pure distance order (a secondary sort key or a "<>" filter would force a scan of every
        # event: ~1 s warm, several cold), in growing pages, until `limit` rows of the wanted type are found and every
        # tie at the cut-off is included; ties are then ordered by recency. Same result as the full scan.
        type_filter = f"AND {_FP_TYPE} = :t" if same_type else ""
        n = max(64, limit * 8)
        while True:
            rows = [dict(r) for r in db.execute(text(f"""
                SELECT e.id, e.last_detected, {_FP_TYPE} AS t, {_FP_CUBE} <-> {target} AS d5
                FROM thermal_events e WHERE e.fingerprint IS NOT NULL AND e.id <> :id {type_filter}
                ORDER BY {_FP_CUBE} <-> {target} LIMIT :n"""), {**params, "n": n}).mappings().all()]
            keep = sorted((r for r in rows if (r["t"] == ftype) == same_type),
                          key=lambda r: (r["d5"], -r["last_detected"].timestamp()))
            if len(rows) < n or (len(keep) >= limit and rows[-1]["d5"] > keep[limit - 1]["d5"]):
                return keep[:limit]
            n *= 4

    cands = [{**c, "fp_distance": c["d5"]} for c in walk(True)]
    cands += [{**c, "fp_distance": math.sqrt(c["d5"] ** 2 + _FP_TYPE_PENALTY)} for c in walk(False)]
    cands.sort(key=lambda c: (c["fp_distance"], -c["last_detected"].timestamp()))
    top = cands[:limit]
    if not top:
        return []
    rows = {r["id"]: dict(r) for r in db.execute(text(f"""
        SELECT {_LIST_COLS}, e.fingerprint, ST_Distance(e.geom, (SELECT geom FROM thermal_events WHERE id = :id)) AS distance_m
        FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id
        WHERE e.id = ANY(:ids)"""), {"id": event_id, "ids": [c["id"] for c in top]}).mappings().all()}
    from app.services.investigation import similarity_reasons

    mine = db.execute(text("SELECT fingerprint, persistence_class, classification FROM thermal_events WHERE id = :id"),
                      {"id": event_id}).mappings().one()
    return [_with_display({**rows[c["id"]], "fp_distance": c["fp_distance"],
                           "similarity_reasons": similarity_reasons(dict(mine), rows[c["id"]])}) for c in top if c["id"] in rows]


# Evidence a walkthrough event should have, with the weight used to rank candidates (then triage priority).
_FEATURE_CRITERIA = (
    ("facility", 3, "a mapped facility within 2 km", "no mapped facility within 2 km"),
    ("classified", 2, "a specific source classification", "no specific source classification"),
    ("confident", 2, "a confidence state above insufficient evidence", "insufficient evidence for a confident classification"),
    ("persistent", 2, "persistent or recurring heat", "not persistent or recurring"),
    ("landcover", 2, "ESA WorldCover land cover", "no land cover retrieved"),
    ("imagery", 2, "a Sentinel-2 before/after analysis", "no Sentinel-2 before/after analysis"),
)


def featured_event(db: Session) -> dict | None:
    """The real event that best shows the investigation workflow: ranked by how much evidence it carries (facility,
    classification, confidence, persistence, land cover, imagery analysis), then by triage priority. Candidates are the
    top of the priority queue plus every event with land cover or an imagery analysis. Nothing is invented: the
    response says which evidence it has and which is unavailable."""
    rows = db.execute(text("""
        WITH cand AS (
          (SELECT id FROM thermal_events ORDER BY priority_score DESC NULLS LAST, id LIMIT 300)
          UNION (SELECT event_id FROM landcover_observations LIMIT 500)
          UNION (SELECT event_id FROM imagery_analyses WHERE status = 'ok' LIMIT 500))
        SELECT e.id, e.priority_score,
          coalesce(e.nearest_facility_distance_m <= 2000, false) AS facility,
          coalesce(e.classification NOT IN ('unknown', 'other'), false) AS classified,
          coalesce(e.confidence_state <> 'INSUFFICIENT_EVIDENCE', false) AS confident,
          coalesce(e.persistence_class IN ('persistent', 'recurring'), false) AS persistent,
          EXISTS (SELECT 1 FROM landcover_observations l WHERE l.event_id = e.id) AS landcover,
          EXISTS (SELECT 1 FROM imagery_analyses i WHERE i.event_id = e.id AND i.status = 'ok') AS imagery
        FROM cand JOIN thermal_events e ON e.id = cand.id""")).mappings().all()
    if not rows:
        return None

    def rank(r):
        return (sum(w for key, w, _, _ in _FEATURE_CRITERIA if r[key]), r["priority_score"] or 0.0)

    best = max(rows, key=rank)
    summary = get_summary(db, best["id"])
    summary["selection_reasons"] = [has for key, _, has, _ in _FEATURE_CRITERIA if best[key]]
    summary["unavailable_evidence"] = [missing for key, _, _, missing in _FEATURE_CRITERIA if not best[key]]
    return summary

