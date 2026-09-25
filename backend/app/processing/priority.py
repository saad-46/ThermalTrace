"""Triage priority — orders the analyst review queue.

A transparent, additive score built only from observed and derived evidence. It answers "what should an analyst look at first?", NOT "how dangerous is this?".
It is not a risk or threat score and is never presented as one.

priority (0–100) = Σ five components, each 0–20:
  thermal_intensity      log-scaled peak FRP (300 MW → full)
  persistence            persistence-engine score
  industrial_proximity   best facility attribution score (0.6 → full)
  classification_confidence  system confidence score
  sensor_corroboration   independent platforms (1 → 4, 2 → 12, ≥3 → 20)

Tiers: high ≥ 70 · elevated ≥ 50 · routine ≥ 30 · low < 30.
"""
import math
from dataclasses import dataclass

TIERS = ((70, "high"), (50, "elevated"), (30, "routine"), (0, "low"))
_SENSOR_POINTS = {0: 0, 1: 4, 2: 12}


@dataclass
class PriorityResult:
    score: float
    tier: str
    components: list[dict]

    def as_dict(self) -> dict:
        return {"score": self.score, "tier": self.tier, "components": self.components,
                "note": "Orders the review queue; not a risk or threat assessment."}


def tier_for(score: float) -> str:
    return next(name for threshold, name in TIERS if score >= threshold)


def compute_priority(frp_max: float | None, persistence_score: float | None, attribution_score: float | None,
                     confidence_score: float | None, sensor_count: int) -> PriorityResult:
    frp = max(frp_max or 0.0, 0.0)
    intensity = min(math.log1p(frp) / math.log1p(300), 1.0) * 20
    persistence = min(max(persistence_score or 0.0, 0.0), 1.0) * 20
    proximity = min((attribution_score or 0.0) / 0.6, 1.0) * 20
    confidence = min(max(confidence_score or 0.0, 0.0), 1.0) * 20
    sensors = _SENSOR_POINTS.get(sensor_count, 20)
    components = [
        {"name": "thermal_intensity", "points": round(intensity, 1), "max": 20, "detail": f"peak FRP {frp:.1f} MW"},
        {"name": "persistence", "points": round(persistence, 1), "max": 20,
         "detail": f"persistence score {persistence_score or 0:.2f}"},
        {"name": "industrial_proximity", "points": round(proximity, 1), "max": 20,
         "detail": "no attributable facility" if not attribution_score else f"attribution score {attribution_score:.2f}"},
        {"name": "classification_confidence", "points": round(confidence, 1), "max": 20,
         "detail": f"system confidence {confidence_score or 0:.2f}"},
        {"name": "sensor_corroboration", "points": float(sensors), "max": 20, "detail": f"{sensor_count} platform(s)"},
    ]
    score = float(round(sum(c["points"] for c in components)))  # integer, so the shown number and tier agree
    return PriorityResult(score, tier_for(score), components)
