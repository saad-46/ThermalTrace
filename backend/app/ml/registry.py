"""Model registry: which models exist, which is active, and loading them."""
import logging
import threading
from pathlib import Path

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.base import SOURCE_CLASSES
from app.ml.gbm import GradientBoostingClassifier, train
from app.ml.rule_cascade import MODEL_ID as RULE_ID
from app.ml.rule_cascade import RuleCascadeClassifier
from app.models.ml import ModelVersion
from app.processing.features import FEATURE_NAMES

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, GradientBoostingClassifier] = {}


def ensure_rule_model(db: Session) -> None:
    if db.get(ModelVersion, RULE_ID) is None:
        db.add(ModelVersion(
            id=RULE_ID, kind="rule", is_active=True, feature_names=FEATURE_NAMES, classes=SOURCE_CLASSES,
            description="Deterministic evidence cascade: facility type/distance, persistence, night fraction, "
                        "land context and season. Produces a readable rule trace.",
            label_provenance="Expert rules from published remote-sensing literature (docs/ML.md). Not learned from data.",
            training_summary={}, metrics={},
        ))
        db.flush()
    # Earlier rule versions stay in the registry (their past predictions reference them) but are retired.
    db.execute(update(ModelVersion).where(ModelVersion.kind == "rule", ModelVersion.id != RULE_ID,
                                          ModelVersion.is_active.is_(True)).values(is_active=False))


def rule_model() -> RuleCascadeClassifier:
    return RuleCascadeClassifier()


def active_gbm(db: Session) -> GradientBoostingClassifier | None:
    mv = db.execute(
        select(ModelVersion).where(ModelVersion.kind == "lightgbm", ModelVersion.is_active.is_(True))
    ).scalar_one_or_none()
    if mv is None or not mv.artifact_path or not Path(mv.artifact_path).exists():
        return None
    with _lock:
        if mv.id not in _cache:
            _cache.clear()
            _cache[mv.id] = GradientBoostingClassifier.load(Path(mv.artifact_path))
        return _cache[mv.id]


_TRAINING_ROWS = text(
    """
    SELECT e.id, e.latitude, e.longitude, p.features_used, p.prediction, p.probability, r.source_class AS analyst_label
    FROM thermal_events e
    JOIN LATERAL (SELECT features_used, prediction, probability FROM model_predictions mp
                  WHERE mp.event_id = e.id AND mp.model_version_id = :rule ORDER BY created_at DESC LIMIT 1) p ON true
    LEFT JOIN LATERAL (SELECT source_class FROM analyst_reviews ar
                       WHERE ar.event_id = e.id AND ar.decision IN ('confirm','reclassify') AND ar.source_class IS NOT NULL
                       ORDER BY created_at DESC LIMIT 1) r ON true
    WHERE e.data_mode <> 'demo'
    """
)


def train_and_register(db: Session) -> ModelVersion:
    """Train and store a model version. It is always stored INACTIVE: activation is a separate, audited admin
    decision (POST /models/{id}/activate) taken after reviewing the model card."""
    rows = []
    for r in db.execute(_TRAINING_ROWS, {"rule": RULE_ID}).mappings():
        feats = {k: (float("nan") if v is None else v) for k, v in (r["features_used"] or {}).items()}
        if r["analyst_label"]:
            rows.append({"features": feats, "label": r["analyst_label"], "weight": 3.0, "lat": r["latitude"],
                         "lon": r["longitude"], "origin": "analyst"})
        elif r["prediction"] not in ("unknown", "other") and r["probability"] >= 0.55:
            rows.append({"features": feats, "label": r["prediction"], "weight": 1.0, "lat": r["latitude"],
                         "lon": r["longitude"], "origin": "weak"})
    clf, info = train(rows, Path(settings.model_dir))
    metrics = info["metrics"]
    mv = ModelVersion(
        id=clf.model_id, kind="lightgbm", is_active=False, feature_names=FEATURE_NAMES, classes=info["classes"],
        description="LightGBM multiclass over the explicit feature pipeline, explained with SHAP TreeExplainer.",
        label_provenance=(f"{metrics['origins'].get('analyst', 0)} analyst-adjudicated labels (weight 3) + "
                          f"{metrics['origins'].get('weak', 0)} weak labels from {RULE_ID} with p ≥ 0.55 (weight 1)."),
        training_summary={"n_rows": len(rows), "class_counts": metrics["class_counts"], "split": metrics["split"]},
        metrics={k: v for k, v in metrics.items() if k not in ("class_counts",)},
        artifact_path=info["path"],
    )
    db.add(mv)
    db.flush()
    logger.info("trained %s on %d rows: %s", mv.id, len(rows), metrics.get("macro_f1_holdout"))
    return mv
