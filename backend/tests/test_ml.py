"""ML pipeline tests: training, persistence, prediction and SHAP explanations on a synthetic fixture matrix."""
import math
import random

import pytest

from app.ml.gbm import GradientBoostingClassifier, train
from app.processing.features import FEATURE_NAMES


def _rows(n_per_class: int = 40):
    rng = random.Random(7)
    rows = []
    for i in range(n_per_class):
        base = {k: float("nan") for k in FEATURE_NAMES}
        flare = {**base, "dist_oil_gas_km": rng.uniform(0.1, 1.5), "night_fraction": rng.uniform(0.6, 1), "persistence_score": rng.uniform(0.5, 1),
                 "frp_max_log": math.log1p(rng.uniform(20, 80)), "sensor_count": 3.0}
        agri = {**base, "land_cropland": 1.0, "night_fraction": rng.uniform(0, 0.2), "persistence_score": rng.uniform(0, 0.2),
                "frp_max_log": math.log1p(rng.uniform(2, 15)), "sensor_count": 1.0, "month_sin": -0.5}
        # spread across 1° blocks so the spatial split has blocks to hold out
        rows.append({"features": flare, "label": "flare", "weight": 1.0, "lat": 20 + i % 8, "lon": 70 + i % 5, "origin": "weak"})
        rows.append({"features": agri, "label": "agricultural_burn", "weight": 3.0 if i < 5 else 1.0, "lat": 29 + i % 8, "lon": 75 + i % 5,
                     "origin": "analyst" if i < 5 else "weak"})
    return rows


def test_train_predict_explain_roundtrip(tmp_path):
    clf, info = train(_rows(), tmp_path)
    assert set(info["classes"]) == {"flare", "agricultural_burn"}
    m = info["metrics"]
    assert m["origins"] == {"analyst": 5, "weak": 75}
    assert "caveat" in m and m["split"].startswith("spatial block")

    loaded = GradientBoostingClassifier.load(tmp_path / f"{clf.model_id}.joblib")
    sample = {k: float("nan") for k in FEATURE_NAMES} | {"dist_oil_gas_km": 0.5, "night_fraction": 0.9, "persistence_score": 0.8,
                                                         "frp_max_log": math.log1p(50), "sensor_count": 3.0}
    p = loaded.predict(sample, {})
    assert p.label == "flare" and p.probability > 0.5
    assert abs(sum(p.probabilities.values()) - 1) < 1e-3
    assert p.explanation_kind == "shap" and p.contributions, "SHAP contributions must be produced"
    assert all(c.feature in FEATURE_NAMES for c in p.contributions)
    assert any("not causal" in n for n in p.notes)


def test_refuses_to_train_without_enough_labels(tmp_path):
    with pytest.raises(ValueError, match="not enough labelled data"):
        train(_rows(3), tmp_path)
