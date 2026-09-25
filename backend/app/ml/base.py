"""Classifier interface. Every model returns the same Prediction shape so the confidence engine,
evidence builder and UI never special-case a model."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

SOURCE_CLASSES = ["flare", "process_heat", "coal_seam_fire", "agricultural_burn", "wildfire", "industrial_fire", "other", "unknown"]
CLASS_LABELS = {
    "flare": "Gas flare",
    "process_heat": "Industrial process heat",
    "coal_seam_fire": "Coal-seam / mine fire",
    "agricultural_burn": "Agricultural burn",
    "wildfire": "Wildfire / vegetation fire",
    "industrial_fire": "Industrial fire (possible accident)",
    "other": "Other thermal source",
    "unknown": "Unknown",
}


@dataclass
class Contribution:
    feature: str
    value: float | None
    contribution: float  # signed; for rules: +/- weight of the rule that fired


@dataclass
class Prediction:
    model_id: str
    label: str
    probability: float
    probabilities: dict[str, float]
    explanation_kind: str  # "rule_trace" | "shap"
    contributions: list[Contribution] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)  # human-readable reasoning (rules)
    notes: list[str] = field(default_factory=list)

    def explanation(self) -> dict:
        return {
            "kind": self.explanation_kind,
            "contributions": [c.__dict__ for c in self.contributions],
            "trace": self.trace,
            "notes": self.notes,
        }


class BaseClassifier(ABC):
    model_id: str
    kind: str

    @abstractmethod
    def predict(self, features: dict[str, float], context: dict) -> Prediction:
        """`context` carries non-feature facts used for explanations (e.g. facility names)."""


class RemoteSensingClassifier(BaseClassifier):  # pragma: no cover - interface placeholder by design
    """Extension point for an image-based model on Sentinel-2 SWIR chips (docs/ML.md §Roadmap).
    Deliberately not registered: there is no trained image model yet."""

    kind = "remote_sensing"
