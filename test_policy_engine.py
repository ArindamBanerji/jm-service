"""Tier boundaries and policy integration."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jm_core import DomainConfig, JudgmentMemoryEngine
from policy_engine import (AutonomyTier, action_policy, check_demotion,
                           compute_tier, compute_tier_status, evaluate_domain)
from test_labeling_router import client, ingest, item, seed, verify


def tier(count, accuracy, gate=True):
    return compute_tier("NER", count, accuracy, gate)


def test_tier_none_accuracy():
    assert compute_tier("NER", 0, None, True) is AutonomyTier.RED
    assert compute_tier("NER", 200, None, True) is AutonomyTier.RED


def test_tier_red_insufficient():
    assert tier(20, 1) is AutonomyTier.RED


def test_tier_amber_building():
    assert tier(50, .70) is AutonomyTier.AMBER


def test_tier_green_earned():
    assert tier(120, .82) is AutonomyTier.GREEN


def test_tier_autonomous_earned():
    assert tier(250, .87) is AutonomyTier.AUTONOMOUS


def test_tier_red_conservation_fail():
    assert tier(200, .90, False) is AutonomyTier.RED


def test_tier_amber_low_accuracy():
    assert tier(150, .65) is AutonomyTier.AMBER


def test_tier_green_not_autonomous():
    assert tier(150, .83) is AutonomyTier.GREEN


def test_tier_boundary_exact():
    assert tier(100, .80) is AutonomyTier.GREEN
    assert tier(30, .70) is AutonomyTier.AMBER
    assert tier(200, .85) is AutonomyTier.AUTONOMOUS
    assert compute_tier("preference", 200, .89, True, .90) is AutonomyTier.GREEN
    assert compute_tier("preference", 200, .90, True, .90) is AutonomyTier.AUTONOMOUS


def test_policy_red_human_review():
    assert action_policy(AutonomyTier.RED) == "human_review"


def test_policy_amber_confirm():
    assert action_policy(AutonomyTier.AMBER) == "confirm"
    assert action_policy(AutonomyTier.GREEN) == "confirm"


def test_policy_autonomous_auto_accept():
    assert action_policy(AutonomyTier.AUTONOMOUS) == "auto_accept"


def test_demotion_autonomous_to_green():
    assert check_demotion(AutonomyTier.AUTONOMOUS, .82, True) is AutonomyTier.GREEN
    assert check_demotion(AutonomyTier.AUTONOMOUS, .70, True) is AutonomyTier.AMBER


def test_demotion_green_to_amber():
    assert check_demotion(AutonomyTier.GREEN, .73, True) is AutonomyTier.AMBER


def test_demotion_conservation_to_red():
    assert check_demotion(AutonomyTier.GREEN, .90, False) is AutonomyTier.RED


def test_status_next_tier_requirements():
    status = compute_tier_status("NER", 50, .70, True)
    assert status.next_tier is AutonomyTier.GREEN
    assert status.next_tier_requirements == "Need 80% accuracy and 100 verified"


def test_status_autonomous_no_next():
    status = compute_tier_status("NER", 250, .90, True)
    assert status.next_tier is None and status.next_tier_requirements is None


def test_ingest_includes_tier(client):
    response = ingest(client)
    assert response.status_code == 200, response.text
    assert response.json()["tier"] == "red"
    assert response.json()["action_policy"] == "human_review"
    assert response.json()["auto_accepted"] is False


def test_ingest_auto_accepted_flag(client):
    assert ingest(client).status_code == 200
    seed(client, [index % 20 not in (0, 1) for index in range(250)])
    response = ingest(client, label_id="L2")
    assert response.status_code == 200, response.text
    assert response.json()["tier"] == "autonomous"
    assert response.json()["auto_accepted"] is True


def test_autonomy_endpoint(client):
    assert ingest(client).status_code == 200
    seed(client, [True] * 30)
    response = client.get("/v1/domains/demo/autonomy")
    assert response.status_code == 200, response.text
    assert response.json()["domain_id"] == "demo"
    assert response.json()["overall_tier"] == "amber"
    assert response.json()["categories"][0]["verified_count"] == 30


def test_autonomy_demotion_after_errors(client):
    assert ingest(client).status_code == 200
    seed(client, [index % 5 != 0 for index in range(100)])
    before = client.get("/v1/domains/demo/autonomy").json()
    assert before["overall_tier"] == "green"
    payload = {"domain_id": "demo", "items": [item(label_id=f"error-{index}") for index in range(10)]}
    assert client.post("/v1/labels/ingest/batch", json=payload).status_code == 200
    for index in range(10):
        assert verify(client, label_id=f"error-{index}", outcome=False).status_code == 200
    after = client.get("/v1/domains/demo/autonomy").json()
    assert after["overall_tier"] == "amber"
