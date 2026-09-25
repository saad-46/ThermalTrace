"""Event queries. All spatial/aggregate SQL for events lives here — routers never build SQL."""
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.processing.confidence import display_state

SORTS = {
    "last_detected": "e.last_detected DESC",
    "confidence": "e.confidence_score DESC NULLS LAST",
    "frp": "e.frp_max DESC NULLS LAST",
    "persistence": "e.persistence_score DESC NULLS LAST",
    "observations": "e.observation_count DESC",
    "first_detected": "e.first_detected DESC",
}

_LIST_COLS = """
  e.id, e.public_id, e.latitude, e.longitude, e.data_mode, e.first_detected, e.last_detected,
  e.observation_count, e.sensor_count, e.sensors, e.days_active, e.duration_hours, e.frp_max, e.frp_mean,
  e.night_fraction, e.status, e.review_status, e.persistence_class, e.persistence_score, e.classification,
  e.classification_probability, e.confidence_score, e.confidence_state, e.data_quality,
  e.nearest_facility_distance_m, e.admin_state, e.admin_district, e.country, e.assigned_to,
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
    if p.get("min_observations") is not None:
        clauses.append("e.observation_count >= :min_observations")
        params["min_observations"] = p["min_observations"]
    if p.get("assigned_to"):
        clauses.append("e.assigned_to = :assigned_to")
        params["assigned_to"] = p["assigned_to"]
    if p.get("q"):
        clauses.append("(e.public_id ILIKE :q OR e.admin_district ILIKE :q OR e.admin_state ILIKE :q OR f.name ILIKE :q)")
        params["q"] = f"%{p['q']}%"
    return " AND ".join(clauses), params


def _with_display(row: dict) -> dict:
    row["display_state"] = display_state(row.get("confidence_state") or "INSUFFICIENT_EVIDENCE", row["review_status"])
    return row


def list_events(db: Session, p: dict, sort: str, limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = _filters(p)
    base = f"FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id WHERE {where}"
    total = db.execute(text(f"SELECT count(*) {base}"), params).scalar_one()
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
               e.review_status, e.confidence_score, e.frp_max, e.observation_count, e.status, e.data_mode, e.last_detected
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
                "last": r["last_detected"].isoformat(),
            },
        })
    return {"type": "FeatureCollection", "features": feats, "truncated": truncated, "limit": limit}


def _event_row(db: Session, event_id: uuid.UUID) -> dict:
    row = db.execute(text(f"SELECT {_LIST_COLS}, e.persistence_metrics, e.confidence_components, e.data_quality_detail, "
                          "e.fingerprint, e.enrichment_state, e.datasets, e.frp_sum, e.frp_std, e.confidence_mean, "
                          "e.processed_at, e.processing_version, ST_AsGeoJSON(e.footprint::geometry)::json AS footprint "
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


def get_bundle(db: Session, event_id: uuid.UUID) -> dict:
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
                              l.distance_m, l.bearing_deg, l.rank, l.attribution_score,
                              (SELECT json_agg(json_build_object('source', s.source_id, 'external_id', s.external_id,
                                  'url', s.source_url, 'dataset_version', s.dataset_version,
                                  'published_at', s.published_at, 'retrieved_at', s.retrieved_at))
                               FROM facility_sources s WHERE s.facility_id = f.id) AS sources
                            FROM event_facility_links l JOIN facilities f ON f.id = l.facility_id
                            WHERE l.event_id = :id ORDER BY l.rank""")
    ev["land"] = q("""SELECT category, name, distance_m, osm_type, osm_id, retrieved_at FROM land_context
                      WHERE event_id = :id ORDER BY distance_m LIMIT 30""")
    ev["weather"] = q("""SELECT kind, source_id, dataset, observed_at, retrieved_at, temperature_c, humidity_pct,
                           wind_speed_ms, wind_direction_deg, precipitation_mm, pressure_hpa, weather_code, condition
                         FROM weather_observations WHERE event_id = :id ORDER BY observed_at DESC""")
    ev["satellite"] = q("""SELECT id, provider, source_id, collection, item_id, platform, acquired_at, cloud_cover,
                             processing_level, relation, thumbnail_url, item_url, bbox, retrieved_at
                           FROM satellite_observations WHERE event_id = :id ORDER BY acquired_at""")
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
                            WHEN 'facility' THEN 4 WHEN 'land' THEN 5 WHEN 'weather' THEN 6 WHEN 'satellite' THEN 7
                            ELSE 8 END, strength DESC""")
    ev["reviews"] = q("""SELECT r.id, r.decision, r.source_class, r.persistence_class, r.false_positive_reason, r.notes,
                           r.system_source_class, r.system_confidence_score, r.created_at, u.full_name AS reviewer
                         FROM analyst_reviews r LEFT JOIN users u ON u.id = r.user_id WHERE r.event_id = :id
                         ORDER BY r.created_at DESC""")
    ev["notes"] = q("""SELECT n.id, n.kind, n.body, n.url, n.created_at, u.full_name AS author FROM investigation_notes n
                       LEFT JOIN users u ON u.id = n.user_id WHERE n.event_id = :id ORDER BY n.created_at DESC""")
    ev["alerts"] = q("""SELECT a.id, a.title, a.severity, a.triggered_at, a.status, r.name AS rule_name FROM alerts a
                        JOIN alert_rules r ON r.id = a.rule_id WHERE a.event_id = :id ORDER BY a.triggered_at DESC""")
    ev["investigation"] = (q("""SELECT i.id, i.status, i.priority, i.summary, i.opened_at, i.closed_at, i.assigned_to,
                                   u.full_name AS assignee FROM investigations i LEFT JOIN users u ON u.id = i.assigned_to
                                 WHERE i.event_id = :id""") or [None])[0]
    ev["timeline"] = build_timeline(ev)
    ev["evidence_matrix"] = evidence_matrix(ev)
    return ev


def build_timeline(ev: dict) -> list[dict]:
    items: list[dict] = [{"at": ev["first_detected"], "kind": "first_seen", "label": "First detected",
                          "detail": f"{ev['detections'][0]['satellite']} ({ev['detections'][0]['dataset']})" if ev["detections"] else None}]
    for o in ev["observations"]:
        items.append({"at": o["first_at"], "kind": "observation",
                      "label": f"{o['detection_count']} detection(s)",
                      "detail": f"{', '.join(o['sensors'])}; max FRP {o['frp_max'] or 0:.1f} MW"})
    for s in ev["satellite"]:
        items.append({"at": s["acquired_at"], "kind": "satellite",
                      "label": f"Sentinel-2 scene ({s['relation']})",
                      "detail": f"{s['platform']}, {s['cloud_cover']:.0f}% cloud" if s["cloud_cover"] is not None else s["platform"]})
    for c in ev["classification_history"][:5]:
        items.append({"at": c["created_at"], "kind": "classification",
                      "label": f"Classified: {c['source_class']} / {c['persistence_class']}",
                      "detail": f"{c['confidence_state']} ({c['confidence_score']:.2f}) by {c['primary_model_id']}"})
    for r in ev["reviews"]:
        items.append({"at": r["created_at"], "kind": "review", "label": f"Analyst: {r['decision']}",
                      "detail": (r["reviewer"] or "") + (f" — {r['notes'][:120]}" if r["notes"] else "")})
    for a in ev["alerts"]:
        items.append({"at": a["triggered_at"], "kind": "alert", "label": f"Alert ({a['severity']})", "detail": a["rule_name"]})
    items.append({"at": ev["last_detected"], "kind": "latest", "label": "Latest detection", "detail": None})
    return sorted(items, key=lambda i: i["at"] if isinstance(i["at"], datetime) else datetime.fromisoformat(str(i["at"])))


def evidence_matrix(ev: dict) -> list[dict]:
    """Evidence Type | Availability | Strength — the analyst's at-a-glance evidence quality grid."""
    state = ev.get("enrichment_state") or {}

    def st(step):
        return (state.get(step) or {}).get("status")

    comps = {c["name"]: c for c in ((ev.get("confidence_components") or {}).get("components") or [])}
    top_fac = ev["facilities"][0] if ev["facilities"] else None
    scenes = ev["satellite"]
    best_cloud = min((s["cloud_cover"] for s in scenes if s["cloud_cover"] is not None), default=None)
    pm = ev.get("persistence_metrics") or {}
    gbm = next((p for p in ev["predictions"] if p["model_version_id"].startswith("lgbm")), None)
    return [
        {"type": "FIRMS", "availability": "available", "strength": comps.get("sensor_agreement", {}).get("value", 0),
         "detail": f"{ev['observation_count']} detections, {ev['sensor_count']} platform(s)"},
        {"type": "Facility", "availability": "available" if top_fac else ("checked" if st("osm") == "ok" else "pending"),
         "strength": round(top_fac["attribution_score"] / 0.6, 2) if top_fac else 0,
         "detail": f"{top_fac['name'] or top_fac['facility_type']} at {top_fac['distance_m']:.0f} m" if top_fac
         else ("none mapped within 10 km" if st("osm") == "ok" else "not yet retrieved")},
        {"type": "Satellite", "availability": "available" if scenes else ("checked" if st("satellite") == "ok" else "pending"),
         "strength": comps.get("satellite", {}).get("value", 0),
         "detail": f"{len(scenes)} scene(s), best {best_cloud:.0f}% cloud" if scenes and best_cloud is not None
         else ("no clear scene" if st("satellite") == "ok" else "not yet searched")},
        {"type": "Weather", "availability": "available" if ev["weather"] else ("failed" if st("weather") == "failed" else "pending"),
         "strength": 1.0 if ev["weather"] else 0, "detail": ev["weather"][0]["dataset"] if ev["weather"] else "not available"},
        {"type": "History", "availability": "available", "strength": ev.get("persistence_score") or 0,
         "detail": f"{pm.get('active_days', '–')} active day(s) of {pm.get('history_window_days', '–')} in history"},
        {"type": "ML", "availability": "available" if gbm else "rules only", "strength": ev.get("classification_probability") or 0,
         "detail": f"{ev.get('classification')} (p={ev.get('classification_probability') or 0:.2f})"},
    ]


def similar_events(db: Session, event_id: uuid.UUID, limit: int = 8) -> list[dict]:
    """Fingerprint-distance search over analysed events (excluding the event itself)."""
    rows = db.execute(text(f"""
        WITH me AS (SELECT fingerprint fp, classification, geom FROM thermal_events WHERE id = :id)
        SELECT {_LIST_COLS},
          sqrt(power(coalesce((e.fingerprint->>'intensity')::float,0) - coalesce((me.fp->>'intensity')::float,0),2)
             + power(coalesce((e.fingerprint->>'persistence')::float,0) - coalesce((me.fp->>'persistence')::float,0),2)
             + power(coalesce((e.fingerprint->>'facility_proximity')::float,0) - coalesce((me.fp->>'facility_proximity')::float,0),2)
             + power(coalesce((e.fingerprint->>'night_share')::float,0) - coalesce((me.fp->>'night_share')::float,0),2)
             + power(coalesce((e.fingerprint->>'sensor_agreement')::float,0) - coalesce((me.fp->>'sensor_agreement')::float,0),2)
             + CASE WHEN e.fingerprint->>'facility_type' IS DISTINCT FROM me.fp->>'facility_type' THEN 0.3 ELSE 0 END
          ) AS fp_distance,
          ST_Distance(e.geom, me.geom) AS distance_m
        FROM thermal_events e LEFT JOIN facilities f ON f.id = e.nearest_facility_id, me
        WHERE e.id <> :id AND e.fingerprint IS NOT NULL
        ORDER BY fp_distance, e.last_detected DESC LIMIT :limit"""), {"id": event_id, "limit": limit}).mappings().all()
    return [_with_display(dict(r)) for r in rows]
