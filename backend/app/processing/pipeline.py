"""Processing orchestrator: clustering → persistence → attribution → features → classify →
confidence → evidence. Idempotent: re-analysing an event replaces its current classification
(history retained with is_current=false)."""
import logging
import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.integrations.raster import group_fractions
from app.ml import registry
from app.ml.base import Prediction
from app.ml.rule_cascade import RASTER_MAJORITY
from app.models.enrichment import ImageryAnalysis, LandCoverObservation, SatelliteObservation, WeatherObservation
from app.models.facilities import LandContext
from app.models.ml import Classification, ClassificationEvidence, ModelPrediction
from app.models.thermal import ThermalEvent
from app.processing import attribution, clustering, persistence
from app.processing.confidence import assess_data_quality, compute_confidence
from app.processing.evidence import build_evidence, fingerprint
from app.processing.features import HEAVY, MINES, OIL_GAS, build_features, to_json_safe
from app.processing.priority import compute_priority

logger = logging.getLogger(__name__)
PIPELINE_VERSION = "pipeline-1.0"


def _row(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


def analyse_event(db: Session, event_id: uuid.UUID, history_days: int | None = None) -> Classification:
    ev = db.get(ThermalEvent, event_id)
    if ev is None:
        raise ValueError(f"event {event_id} not found")
    window = history_days if history_days is not None else persistence.history_window_days(db)

    pm = persistence.compute_for_event(db, ev.id, ev.sensor_count, window)
    ev.persistence_class, ev.persistence_score, ev.persistence_metrics = pm.persistence_class, pm.score, pm.as_dict()
    db.flush()

    ranked = attribution.attribute_event(db, ev.id)
    db.flush()
    feats = build_features(db, ev.id)

    state = ev.enrichment_state or {}
    osm_status = (state.get("osm") or {}).get("status")
    sat_status = (state.get("satellite") or {}).get("status")
    wx_status = (state.get("weather") or {}).get("status")

    def first_of(types) -> dict | None:
        return next((r for r in sorted(ranked, key=lambda r: r["distance_m"]) if r["facility_type"] in types), None)

    oil, heavy, mine = first_of(OIL_GAS), first_of(HEAVY), first_of(MINES)
    context = {
        "persistence_class": pm.persistence_class,
        "month": ev.first_detected.month,
        "osm_checked": osm_status == "ok",
        "oil_name": oil and oil["name"], "heavy_name": heavy and heavy["name"], "mine_name": mine and mine["name"],
    }

    rule_pred = registry.rule_model().predict(feats, context)
    gbm = registry.active_gbm(db)
    gbm_pred: Prediction | None = gbm.predict(feats, context) if gbm else None
    registry.ensure_rule_model(db)
    for p in filter(None, (rule_pred, gbm_pred)):
        db.add(ModelPrediction(event_id=ev.id, model_version_id=p.model_id, prediction=p.label, probability=p.probability,
                               probabilities=p.probabilities, features_used=to_json_safe(feats), explanation=p.explanation()))

    # Primary = GBM when trained AND agreeing or more confident; the rule cascade remains the
    # readable baseline. Disagreement is surfaced by the confidence engine, never hidden.
    primary = gbm_pred if (gbm_pred and gbm_pred.probability >= rule_pred.probability) else rule_pred

    land = [_row(lc) for lc in db.execute(select(LandContext).where(LandContext.event_id == ev.id)).scalars()]
    weather = db.execute(
        select(WeatherObservation).where(WeatherObservation.event_id == ev.id, WeatherObservation.kind == "at_last_detection")
        .order_by(WeatherObservation.observed_at.desc()).limit(1)
    ).scalar_one_or_none()
    scenes = [_row(s) for s in db.execute(select(SatelliteObservation).where(SatelliteObservation.event_id == ev.id)).scalars()]
    best_cloud = min((s["cloud_cover"] for s in scenes if s["cloud_cover"] is not None), default=None)

    wc_row = db.execute(select(LandCoverObservation).where(LandCoverObservation.event_id == ev.id)).scalar_one_or_none()
    ia_row = db.execute(select(ImageryAnalysis).where(ImageryAnalysis.event_id == ev.id)).scalar_one_or_none()
    lc_status = (state.get("landcover") or {}).get("status")

    hours_since = (datetime.now(UTC) - ev.last_detected).total_seconds() / 3600
    quality = assess_data_quality({
        "sensor_count": ev.sensor_count,
        "pixel_area_km2": None if math.isnan(feats["pixel_area_km2"]) else feats["pixel_area_km2"],
        "osm_status": osm_status, "facilities_10km": len(ranked), "best_cloud": best_cloud,
        "satellite_status": sat_status, "weather_status": wx_status, "history_window_days": window,
        "hours_since_last": hours_since, "data_mode": ev.data_mode, "observation_count": ev.observation_count,
    })
    land_cats = sorted({lc["category"] for lc in land})
    land_support = None if osm_status != "ok" else bool(
        (primary.label == "agricultural_burn" and "cropland" in land_cats)
        or (primary.label == "wildfire" and ({"forest", "scrub"} & set(land_cats))))
    if land_support is None and wc_row is not None:
        # OSM land use not retrieved: fall back to raster land cover, for the vegetation classes only.
        g = group_fractions(wc_row.fractions)
        land_support = bool((primary.label == "agricultural_burn" and g["cropland"] >= RASTER_MAJORITY)
                            or (primary.label == "wildfire" and g["vegetation"] >= RASTER_MAJORITY))
    conf = compute_confidence(
        label=primary.label, probability=primary.probability, rule_label=rule_pred.label,
        gbm_label=gbm_pred.label if gbm_pred else None, persistence_class=pm.persistence_class,
        attribution_score=ranked[0]["score"] if ranked else None, land_support=land_support,
        sensor_count=ev.sensor_count, satellite_status=sat_status, best_cloud=best_cloud,
        weather_ok=weather is not None, quality=quality,
    )

    db.execute(update(Classification).where(Classification.event_id == ev.id, Classification.is_current.is_(True))
               .values(is_current=False))
    cls = Classification(
        event_id=ev.id, source_class=primary.label, persistence_class=pm.persistence_class, probability=primary.probability,
        confidence_score=conf.score, confidence_state=conf.state, confidence_components=conf.as_dict(),
        primary_model_id=primary.model_id,
        supporting_model_ids=[p.model_id for p in (rule_pred, gbm_pred) if p and p.model_id != primary.model_id],
        is_current=True, pipeline_version=PIPELINE_VERSION,
    )
    db.add(cls)
    db.flush()

    ev_dict = _row(ev)
    ctx = {"event": ev_dict, "persistence": pm.as_dict(), "facilities": ranked, "osm_status": osm_status, "land": land,
           "weather": _row(weather) if weather else None, "satellite": scenes, "satellite_status": sat_status,
           "landcover": _row(wc_row) if wc_row else None, "landcover_status": lc_status,
           "imagery": _row(ia_row) if ia_row else None}
    db.execute(delete(ClassificationEvidence).where(ClassificationEvidence.event_id == ev.id))
    for item in build_evidence(ctx, primary.label, rule_pred, gbm_pred):
        db.add(ClassificationEvidence(classification_id=cls.id, event_id=ev.id, **item.__dict__))

    top = ranked[0] if ranked else None
    ev.classification = primary.label
    ev.classification_probability = primary.probability
    ev.confidence_score, ev.confidence_state, ev.confidence_components = conf.score, conf.state, conf.as_dict()
    ev.data_quality, ev.data_quality_detail = quality.grade, quality.as_dict()
    ev.nearest_facility_id = min(ranked, key=lambda r: r["distance_m"])["id"] if ranked else None
    ev.nearest_facility_distance_m = min((r["distance_m"] for r in ranked), default=None)
    ev.fingerprint = fingerprint(ev_dict, pm.as_dict(), top, land_cats, _row(weather) if weather else None)
    prio = compute_priority(ev.frp_max, pm.score, top["score"] if top else None, conf.score, ev.sensor_count)
    ev.priority_score, ev.priority_components = prio.score, prio.as_dict()
    ev.processed_at = datetime.now(UTC)
    ev.processing_version = PIPELINE_VERSION
    return cls


def process_new_detections(db: Session, reanalyse_all: bool = False) -> dict:
    """Cluster new detections and (re)analyse every touched event. Commits in batches."""
    registry.ensure_rule_model(db)
    touched = clustering.assign_detections(db)
    clustering.refresh_event_stats(db, touched)
    aged = clustering.refresh_activity_status(db)
    db.commit()
    if reanalyse_all:
        touched |= set(db.execute(text("SELECT id FROM thermal_events")).scalars())
    window = persistence.history_window_days(db)
    done = failed = 0
    for i, event_id in enumerate(sorted(touched, key=str)):
        try:
            with db.begin_nested():
                analyse_event(db, event_id, window)
            done += 1
        except Exception:
            failed += 1
            logger.exception("analysis failed for event %s", event_id)
        if i % 200 == 199:
            db.commit()
    db.commit()
    logger.info("processing: analysed=%d failed=%d aged=%d", done, failed, aged)
    return {"events_analysed": done, "events_failed": failed, "events_aged": aged, "event_ids": [str(e) for e in touched]}
