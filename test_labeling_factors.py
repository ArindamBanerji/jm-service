import sys
from typing import cast
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from labeling_factors import (
    model_confidence, annotator_calibration, item_difficulty, schema_complexity,
    compute_factor_vector, compute_factor_array,
)
from jm_core import DomainConfig, JudgmentMemoryEngine


def args():
    return (0.87, [], "NER", [0.95, 0.93, 0.97],
            {"entity_types": 2, "nesting_depth": 1, "relation_count": 0})


def test_model_confidence_passthrough():
    result = model_confidence(0.87)
    assert result["value"] == 0.87 and not result["is_default"]


def test_model_confidence_clips_above_1():
    assert model_confidence(1.5)["value"] == 1.0


def test_model_confidence_clips_below_0():
    assert model_confidence(-0.3)["value"] == 0.0


def test_calibration_basic():
    rows = [{"category": "NER", "outcome_correct": i < 8} for i in range(10)]
    assert annotator_calibration(rows, "NER")["value"] == 0.8


def test_calibration_cold_start():
    result = annotator_calibration([], "NER")
    assert result["value"] == 0.5 and result["is_default"]


def test_calibration_one_record():
    result = annotator_calibration([{"category": "NER", "annotator_correct": True}], "NER")
    assert result["value"] == 1.0 and not result["is_default"]


def test_calibration_observed_half_is_not_default():
    rows = [{"category": "NER", "annotator_correct": True},
            {"category": "NER", "annotator_correct": False}]
    result = annotator_calibration(rows, "NER")
    assert result["value"] == 0.5 and not result["is_default"]


def test_calibration_latest_fifty():
    rows = ([{"category": "NER", "annotator_correct": False}] * 10 +
            [{"category": "NER", "annotator_correct": True}] * 50)
    assert annotator_calibration(rows, "NER")["value"] == 1.0


def test_calibration_category_filter():
    rows = ([{"category": "NER", "outcome_correct": True}] * 5 +
            [{"category": "OTHER", "outcome_correct": False}] * 10)
    assert annotator_calibration(rows, "NER")["value"] == 1.0


def test_calibration_empty_log():
    result = annotator_calibration([], "NER")
    assert result["value"] == 0.5 and result["is_default"]


def test_difficulty_unanimous():
    assert item_difficulty([0.95, 0.93, 0.97])["value"] < 0.2


def test_difficulty_split():
    assert item_difficulty([0.9, 0.1, 0.5])["value"] > 0.8


def test_difficulty_single_score():
    result = item_difficulty([0.7])
    assert result["value"] == 0.5 and result["is_default"]


def test_difficulty_empty():
    result = item_difficulty([])
    assert result["value"] == 0.5 and result["is_default"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_difficulty_single_invalid(value):
    with pytest.raises(ValueError):
        item_difficulty([value])


def test_schema_simple():
    assert schema_complexity({"entity_types": 2, "nesting_depth": 1, "relation_count": 0})["value"] < 0.3


def test_schema_complex():
    assert schema_complexity({"entity_types": 20, "nesting_depth": 3})["value"] == 1.0


def test_schema_flat_five_classes():
    assert schema_complexity({"entity_types": 5, "nesting_depth": 1})["value"] == 0.2


def test_schema_defaults():
    result = schema_complexity({})
    assert result["value"] == 0.0 and result["is_default"]


def test_schema_invalid_depth():
    with pytest.raises(ValueError):
        schema_complexity({"entity_types": 5, "nesting_depth": 0})


def test_vector_returns_dicts_with_default():
    rows = compute_factor_vector(*args())
    assert len(rows) == 4
    assert all(set(row) == {"factor", "display_name", "value", "low_label", "high_label", "description", "is_default"} for row in rows)


def test_vector_canonical_order():
    assert [row["factor"] for row in compute_factor_vector(*args())] == [
        "model_confidence", "annotator_calibration", "item_difficulty", "schema_complexity"
    ]


def test_vector_display_names():
    assert all(row["display_name"] and row["description"] for row in compute_factor_vector(*args()))


def test_array_returns_4_floats():
    values = compute_factor_array(*args())
    assert len(values) == 4 and all(isinstance(value, float) for value in values)


def test_array_matches_vector():
    assert compute_factor_array(*args()) == [row["value"] for row in compute_factor_vector(*args())]


def test_factor_array_feeds_jm_core():
    names = ["model_confidence", "annotator_calibration", "item_difficulty", "schema_complexity"]
    engine = JudgmentMemoryEngine(DomainConfig("d", "labeling", names, ["NER", "OTHER", "A", "B"], ["confirm", "review"]))
    result = engine.score(cast(dict[str, float], compute_factor_array(*args())), "NER")
    assert result.recommended_action in engine.config.actions
