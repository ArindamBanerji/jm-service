"""Configurable synthetic data and small-grid smoke checks."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.exp_dlj_sweep import (SweepConfig, generate_synthetic_data,
                                       run_dlj_01_cell, run_dlj_02_cell,
                                       similarity_rule_shifts)


class TestConfigurableDataGenerator:
    def test_varying_factors(self) -> None:
        for count in (4, 8, 12):
            pool, test, factors, _, _ = generate_synthetic_data(40, count, 4, 4, 0, 42, test_size=10)
            assert len(factors) == count
            assert len(pool) == 40 and len(test) == 10
            assert all(len(item.factors) == count and all(0 <= value <= 1 for value in item.factors.values())
                       for item in pool + test)

    def test_varying_categories(self) -> None:
        for count in (2, 6, 10):
            pool, test, _, categories, _ = generate_synthetic_data(100, 6, count, 4, 0, 42, test_size=20)
            assert len(categories) == count
            assert {item.category for item in pool + test} == set(categories)

    def test_noise_injection(self) -> None:
        clean, clean_test, _, _, _ = generate_synthetic_data(2000, 6, 4, 4, 0, 42, test_size=100)
        noisy, noisy_test, _, _, _ = generate_synthetic_data(2000, 6, 4, 4, 0.5, 42, test_size=100)
        clean_by_text = {item.text: item for item in clean}
        changed = sum(item.action != clean_by_text[item.text].action for item in noisy)
        assert 900 <= changed <= 1100
        assert [(item.text, item.action) for item in clean_test] == [(item.text, item.action) for item in noisy_test]

    def test_similarity_mapping(self) -> None:
        assert all(shift == 0 for shift in similarity_rule_shifts(4, 1.0).values())
        assert all(shift != 0 for shift in similarity_rule_shifts(4, 0.0).values())
        assert list(similarity_rule_shifts(4, 0.75).values()) == [0, 0, 0, 1]


class TestSweepSmoke:
    def test_single_cell_runs(self) -> None:
        cell = run_dlj_01_cell(SweepConfig(pool_size=100, n_categories=2), seeds=[42], max_labels=100, test_size=40)
        assert set(cell["labels_to_85pct"]) == {"random", "uncertainty", "centroid_distance"}
        assert len(cell["per_seed"]) == 1
        assert -100 <= cell["centroid_advantage_pp"] <= 100

    def test_single_transfer_cell(self) -> None:
        cell = run_dlj_02_cell(source_size=100, target_similarity=0.5, seeds=[42],
                               max_labels=50, target_pool_size=100, test_size=40)
        assert cell["rule_shifts"] == {"category_0": 0, "category_1": 0,
                                       "category_2": 1, "category_3": 1}
        assert len(cell["per_seed"]) == 1
        assert 0 <= cell["per_seed"][0]["cold_final_accuracy"] <= 1
