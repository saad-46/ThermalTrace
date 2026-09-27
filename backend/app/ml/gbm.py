"""LightGBM classifier with SHAP explanations.

Training labels (stored in the model card, shown in the UI):
  1. Analyst adjudications (analyst_reviews confirm/reclassify) — weight 3.0
  2. Weak labels from the rule cascade where its probability ≥ WEAK_LABEL_MIN_P — weight 1.0
  ("unknown"/"other" rule outputs are never used as labels)

Because most labels are weak, this model largely *smooths* the rule cascade over all features;
its independent value grows as analyst adjudications accumulate. Validation uses a spatial
block split (1° cells) so neighbouring pixels never sit on both sides (leakage).
SHAP values are model evidence, not causal proof.
"""
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np

from app.ml.base import BaseClassifier, Contribution, Prediction
from app.processing.features import FEATURE_NAMES

logger = logging.getLogger(__name__)
WEAK_LABEL_MIN_P = 0.55
MIN_SAMPLES = 40
MIN_PER_CLASS = 5


class GradientBoostingClassifier(BaseClassifier):
    kind = "lightgbm"

    def __init__(self, model_id: str, booster, classes: list[str], feature_names: list[str]):
        self.model_id = model_id
        self.model = booster
        self.classes = classes
        self.feature_names = feature_names
        self._explainer = None

    # -- persistence ------------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "GradientBoostingClassifier":
        bundle = joblib.load(path)
        return cls(bundle["model_id"], bundle["model"], bundle["classes"], bundle["feature_names"])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model_id": self.model_id, "model": self.model, "classes": self.classes,
                     "feature_names": self.feature_names}, path)

    # -- inference --------------------------------------------------------------------------
    def _vector(self, features: dict[str, float]) -> np.ndarray:
        return np.array([[features.get(n, math.nan) for n in self.feature_names]], dtype=float)

    def predict(self, features: dict[str, float], context: dict) -> Prediction:
        x = self._vector(features)
        proba = self.model.predict_proba(x)[0]
        idx = int(np.argmax(proba))
        label = self.classes[idx]
        contributions = self._shap(x, idx, features)
        return Prediction(
            model_id=self.model_id,
            label=label,
            probability=round(float(proba[idx]), 4),
            probabilities={c: round(float(p), 4) for c, p in zip(self.classes, proba, strict=False)},
            explanation_kind="shap",
            contributions=contributions,
            notes=["SHAP values describe what moved this model's output — they are model evidence, not causal proof."],
        )

    def _shap(self, x: np.ndarray, class_idx: int, features: dict) -> list[Contribution]:
        try:
            import shap

            if self._explainer is None:
                self._explainer = shap.TreeExplainer(self.model)
            values = self._explainer.shap_values(x)
            if isinstance(values, list):  # older shap: list per class
                row = values[class_idx][0]
            elif values.ndim == 3:  # (n, features, classes)
                row = values[0, :, class_idx]
            else:
                row = values[0]
        except Exception:  # SHAP failure must not block classification — but it is logged
            logger.exception("SHAP explanation failed for %s", self.model_id)
            return []
        pairs = sorted(zip(self.feature_names, row, strict=False), key=lambda t: -abs(t[1]))
        out = []
        for name, val in pairs[:10]:
            fv = features.get(name)
            out.append(Contribution(name, None if fv is None or (isinstance(fv, float) and math.isnan(fv)) else fv,
                                    round(float(val), 4)))
        return out


def _spatial_block(lat: float, lon: float) -> int:
    return int(math.floor(lat)) * 1000 + int(math.floor(lon))


def train(rows: list[dict], model_dir: Path) -> tuple[GradientBoostingClassifier, dict]:
    """rows: {"features": {...}, "label": str, "weight": float, "lat": float, "lon": float, "origin": "analyst"|"weak"}"""
    from lightgbm import LGBMClassifier
    from sklearn.metrics import classification_report, f1_score

    labels = [r["label"] for r in rows]
    counts = {c: labels.count(c) for c in sorted(set(labels))}
    classes = [c for c, n in counts.items() if n >= MIN_PER_CLASS]
    rows = [r for r in rows if r["label"] in classes]
    if len(rows) < MIN_SAMPLES or len(classes) < 2:
        raise ValueError(f"not enough labelled data to train: {len(rows)} rows, class counts {counts}")

    X = np.array([[r["features"].get(n, math.nan) for n in FEATURE_NAMES] for r in rows], dtype=float)
    y = np.array([classes.index(r["label"]) for r in rows])
    w = np.array([r["weight"] for r in rows])
    blocks = np.array([_spatial_block(r["lat"], r["lon"]) for r in rows])

    rng = np.random.default_rng(42)
    unique_blocks = np.unique(blocks)
    test_blocks = set(rng.choice(unique_blocks, size=max(1, len(unique_blocks) // 5), replace=False).tolist())
    test_mask = np.array([b in test_blocks for b in blocks])

    params = dict(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=5,
                  class_weight="balanced", random_state=42, verbose=-1)
    metrics: dict = {"class_counts": counts, "n_train": int((~test_mask).sum()), "n_test": int(test_mask.sum()),
                     "split": "spatial block (1° cells), 20% of blocks held out"}
    if test_mask.sum() >= 10 and len(set(y[~test_mask])) == len(classes):
        eval_model = LGBMClassifier(**params).fit(X[~test_mask], y[~test_mask], sample_weight=w[~test_mask])
        pred = eval_model.predict(X[test_mask])
        metrics["macro_f1_holdout"] = round(float(f1_score(y[test_mask], pred, average="macro")), 3)
        metrics["report"] = classification_report(
            y[test_mask], pred, labels=list(range(len(classes))), target_names=classes, output_dict=True, zero_division=0)
        metrics["caveat"] = ("Hold-out labels are mostly weak (rule-derived); this F1 measures agreement with the rule "
                             "cascade, not accuracy against ground truth.")
        # the only labels independent of the rule cascade: analyst decisions in the held-out spatial blocks
        analyst = np.array([r["origin"] == "analyst" for r in rows]) & test_mask
        metrics["n_test_analyst"] = int(analyst.sum())
        if analyst.sum() >= 10:
            metrics["macro_f1_holdout_analyst"] = round(float(f1_score(y[analyst], eval_model.predict(X[analyst]), average="macro")), 3)
        else:
            metrics["macro_f1_holdout_analyst"] = None
            metrics["caveat_analyst"] = (f"Only {int(analyst.sum())} analyst-adjudicated label(s) in the held-out blocks "
                                         "(10 needed); there is no independent accuracy estimate yet.")
    else:
        metrics["macro_f1_holdout"] = None
        metrics["caveat"] = "Too few spatial blocks for a hold-out evaluation."

    final = LGBMClassifier(**params).fit(X, y, sample_weight=w)
    version = f"lgbm-{datetime.now(UTC):%Y%m%d%H%M%S}"
    clf = GradientBoostingClassifier(version, final, classes, FEATURE_NAMES)
    path = model_dir / f"{version}.joblib"
    clf.save(path)
    importance = sorted(zip(FEATURE_NAMES, final.feature_importances_.tolist(), strict=False), key=lambda t: -t[1])
    metrics["feature_importance_split"] = importance[:15]
    metrics["origins"] = {o: sum(1 for r in rows if r["origin"] == o) for o in ("analyst", "weak")}
    (model_dir / f"{version}.json").write_text(json.dumps(metrics, indent=2, default=str))
    return clf, {"path": str(path), "metrics": metrics, "classes": classes}
