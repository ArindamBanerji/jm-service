"""Canonical factor computation for RGI Data Label Judgment."""
from __future__ import annotations

from math import isfinite, log
from typing import TypedDict

FACTOR_NAMES = (
    "model_confidence", "annotator_calibration", "item_difficulty", "schema_complexity"
)


class FactorDisplay(TypedDict):
    factor: str
    display_name: str
    value: float
    low_label: str
    high_label: str
    description: str
    is_default: bool


class FactorArray(list[float]):
    """Ordered float list that also satisfies jm_core.score's named lookup."""

    def get(self, factor: str, default: float = 0.5) -> float:
        try:
            return self[FACTOR_NAMES.index(factor)]
        except ValueError:
            return default


def _number(value: float) -> float:
    if not isfinite(value):
        raise ValueError("Factor inputs must be finite")
    return value


def _display(factor: str, name: str, value: float, low: str, high: str,
             description: str, is_default: bool = False) -> FactorDisplay:
    return {"factor": factor, "display_name": name, "value": value,
            "low_label": low, "high_label": high, "description": description,
            "is_default": is_default}


def model_confidence(value: float) -> FactorDisplay:
    """Clip a model prediction probability to the canonical range."""
    clipped = min(1.0, max(0.0, _number(value)))
    return _display("model_confidence", "Model Confidence", clipped,
                    "0.20 = guessing", "0.95 = very confident",
                    "The pre-label model's confidence in its proposed class.")


def annotator_calibration(label_log: list[dict], category: str) -> FactorDisplay:
    """Use prior verified records, ordered oldest to newest.

    The caller filters by annotator and epoch and excludes imports and the current label.
    """
    matching = [row for row in label_log if row.get("category") == category
                and isinstance(row.get("annotator_correct", row.get("outcome_correct")), bool)]
    recent = matching[-50:]
    value = (sum(row.get("annotator_correct", row.get("outcome_correct")) for row in recent)
             / len(recent)) if recent else 0.5
    return _display("annotator_calibration", "Annotator Calibration", float(value),
                    "0.50 = half correct", "0.95 = reliable",
                    "Accuracy on the latest 50 qualified prior labels for this annotator, category and epoch.",
                    is_default=not recent)


def item_difficulty(scores: list[float]) -> FactorDisplay:
    """Estimate difficulty from entropy across confidence bands."""
    for raw in scores:
        score = _number(raw)
        if not 0.0 <= score <= 1.0:
            raise ValueError("Item scores must be in [0, 1]")
    if len(scores) <= 1:
        value = 0.5
    else:
        counts = [0, 0, 0]
        for score in scores:
            counts[min(2, int(score * 3))] += 1
        probabilities = [count / len(scores) for count in counts if count]
        entropy = -sum(prob * log(prob) for prob in probabilities) / log(3)
        value = max(0.0, min(1.0, entropy))
    return _display("item_difficulty", "Item Difficulty", value,
                    "0.15 = simple item", "0.80 = difficult item",
                    "Difficulty proxy from confidence-band disagreement; higher means harder.",
                    is_default=len(scores) <= 1)


def schema_complexity(schema_def: dict[str, int]) -> FactorDisplay:
    """Normalize active class count and hierarchy depth per the v6 contract."""
    for key in ("entity_types", "nesting_depth"):
        raw = schema_def.get(key, 0 if key == "entity_types" else 1)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw) or raw < (1 if key == "nesting_depth" else 0):
            raise ValueError(f"Invalid schema component: {key}")
    classes = schema_def.get("entity_types", 0)
    depth = schema_def.get("nesting_depth", 1)
    value = min(1.0, 0.8 * classes / 20 + 0.2 * (depth - 1) / 2)
    return _display("schema_complexity", "Schema Complexity", value,
                    "0.20 = small, flat schema", "0.90 = complex schema",
                    "Complexity from active label class count and nesting depth.",
                    is_default=not schema_def)


def compute_factor_vector(
    model_confidence_value: float, label_log: list[dict], category: str,
    item_scores: list[float], schema_def: dict[str, int]
) -> list[FactorDisplay]:
    return [model_confidence(model_confidence_value), annotator_calibration(label_log, category),
            item_difficulty(item_scores), schema_complexity(schema_def)]


def compute_factor_array(
    model_confidence_value: float, label_log: list[dict], category: str,
    item_scores: list[float], schema_def: dict[str, int]
) -> list[float]:
    """Canonical floats, with named lookup for the frozen engine's score API."""
    return FactorArray([row["value"] for row in compute_factor_vector(
        model_confidence_value, label_log, category, item_scores, schema_def
    )])
