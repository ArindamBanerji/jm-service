"""Infrastructure tests; experimental PASS/FAIL is determined by full runs."""

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments import active_learning_harness as harness
from experiments import exp_dlj_01_active_learning as first
from experiments import exp_dlj_02_transfer as second


class TestActiveLearningHarness:
    def test_import(self) -> None:
        assert callable(harness.run_active_learning_experiment)

    def test_centroid_distances_no_centroids(self) -> None:
        engine = harness.make_engine(first.ACTIONS)
        engine.centroids.clear()
        item = harness.LabeledItem("test", first.extract_factors("test"), "world")
        assert np.isclose(harness.compute_centroid_distances(engine, [item])[0], np.sqrt(6))

    def test_uncertainty_computation(self) -> None:
        entropy = harness.compute_uncertainty(np.asarray([[0.25] * 4, [1.0, 0, 0, 0]]))
        assert entropy[0] > entropy[1]
        assert np.isclose(entropy[1], 0)

    def test_random_strategy_runs(self) -> None:
        rows = first._generate_synthetic_agnews(60, 12)
        items = [harness.LabeledItem(text, first.extract_factors(text), action) for text, action in rows]
        result = harness.run_active_learning_experiment(items[:40], items[40:], "random", seed=7, seed_size=8, rounds=2, batch_size=5)
        assert [point.n_labeled_total for point in result.rounds] == [8, 13, 18]
        assert 0 <= result.final_accuracy <= 1


class TestExpDLJ01:
    def test_factor_extraction(self) -> None:
        factors = first.extract_factors("NASA reports 123 launches, today!")
        assert set(factors) == set(first.FACTOR_NAMES)
        assert all(0 <= value <= 1 for value in factors.values())

    def test_synthetic_data_generation(self) -> None:
        rows = first._generate_synthetic_agnews(100, 42)
        assert len(rows) == 100
        assert {action for _, action in rows} == set(first.ACTIONS)
        assert all(text for text, _ in rows)

    def test_knn_classifier(self) -> None:
        rows = first._generate_synthetic_agnews(24, 42)
        items = [harness.LabeledItem(text, first.extract_factors(text), action) for text, action in rows]
        probabilities = harness.knn_probabilities(items[:16], items[16:], first.ACTIONS, first.FACTOR_NAMES)
        assert probabilities.shape == (8, 4)
        assert np.allclose(probabilities.sum(axis=1), 1)

    def test_data_loading_synthetic(self, monkeypatch) -> None:
        monkeypatch.setattr(first, "_local_agnews", lambda _split, _count: None)
        pool, test, source = first.load_data(100, 20, seed=42)
        assert (len(pool), len(test), source) == (100, 20, "synthetic_agnews_shape")
        assert len(pool[0].factors) == 6
        assert {item.action for item in pool + test} == set(first.ACTIONS)


class TestExpDLJ02:
    def test_source_training(self) -> None:
        source = second._items(first._generate_synthetic_agnews(100, 42))
        engine = second.train_source(source)
        assert len(engine.centroids) == 4
        assert any(any(abs(value - 0.5) > 0.001 for value in centroid) for centroid in engine.centroids.values())

    def test_cold_start_measurement(self) -> None:
        items = second._items(first._generate_synthetic_agnews(130, 43))
        result = second.measure_variant(items[:100], items[100:], seed=42, max_labels=100)
        assert [point["n_labels"] for point in result["trajectory"]] == [0, 25, 50, 75, 100]
        assert all(0 <= point["accuracy"] <= 1 for point in result["trajectory"])
