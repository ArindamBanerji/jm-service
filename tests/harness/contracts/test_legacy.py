import sqlite3
from contextlib import closing

import pytest

from ..fixtures.factory import NUMBER, Wire, shape

pytestmark = pytest.mark.anyio

DOMAIN = {"name": "Example", "factors": ["f", "g"], "categories": ["A"], "actions": ["approve", "reject"]}
SCORE = {"category": "A", "factors": {"f": .6, "g": .2}}


def persisted(wire, query):
    async def check():
        with closing(sqlite3.connect(wire.directory / "legacy.db")) as fresh:
            assert fresh.execute(query).fetchone()[0] == 1
    return check


async def register(wire):
    response = await wire.request("POST", "/v1/register", json={"name": "Owner"})
    return {"X-Api-Key": response.json()["api_key"]}


async def domain(wire):
    headers = await register(wire)
    response = await wire.request("POST", "/v1/domains", json=DOMAIN, headers=headers, status=201)
    return headers, "/v1/domains/" + response.json()["domain_id"]


async def test_registration(wire: Wire):
    response = await wire.request("POST", "/v1/register", json={"name": "Owner"},
                                  before_send=persisted(wire, "SELECT count(*) FROM tenants WHERE name='Owner'"))
    shape(response.json(), {"api_key": str, "name": str})


async def test_create_domain(wire: Wire):
    response = await wire.request("POST", "/v1/domains", json=DOMAIN, headers=await register(wire), status=201,
                                  before_send=persisted(wire, "SELECT count(*) FROM domains"))
    shape(response.json(), {"domain_id": str, "name": str, "factors": [str], "actions": [str],
                            "categories": [str], "centroids_initialized": int, "state_size_bytes": int})


async def test_list_domains(wire: Wire):
    headers, _ = await domain(wire)
    response = await wire.request("GET", "/v1/domains", headers=headers)
    assert response.json()["domains"]
    shape(response.json(), {"domains": [{"domain_id": str, "name": str, "created_at": NUMBER, "updated_at": NUMBER}]})


async def test_score(wire: Wire):
    headers, base = await domain(wire)
    response = await wire.request("POST", base + "/score", json=SCORE, headers=headers,
                                  before_send=persisted(wire, "SELECT count(*) FROM decision_log"))
    shape(response.json(), {"decision_id": str, "recommended_action": str, "confidence": NUMBER,
                            "all_scores": dict, "gate_status": str, "category": str})


async def test_learn(wire: Wire):
    headers, base = await domain(wire)
    score = await wire.request("POST", base + "/score", json=SCORE, headers=headers)
    response = await wire.request("POST", base + "/learn", headers=headers,
                                  json={"decision_id": score.json()["decision_id"], "actual_action": "approve"},
                                  before_send=persisted(wire, "SELECT count(*) FROM decision_log WHERE learned_at IS NOT NULL"))
    shape(response.json(), {"decision_id": str, "centroid_moved": bool, "old_distance": NUMBER,
                            "new_distance": NUMBER, "learning_rate_used": NUMBER, "gate_status": str})


async def test_diagnostics(wire: Wire):
    headers, base = await domain(wire)
    response = await wire.request("GET", base + "/diagnostics", headers=headers)
    shape(response.json(), {"domain": str, "noise_fingerprint": dict, "total_decisions": int,
                            "total_correct": int, "accuracy": NUMBER, "rolling_accuracy": NUMBER,
                            "gate_status": str, "conservation": dict, "centroid_count": int, "state_size_bytes": int})


async def test_state(wire: Wire):
    headers, base = await domain(wire)
    response = await wire.request("GET", base + "/state", headers=headers)
    shape(response.json(), {"config": dict, "tau": NUMBER, "eta_confirm": NUMBER, "eta_override": NUMBER,
                            "centroids": dict, "variance_trackers": dict, "correct_trackers": dict,
                            "incorrect_trackers": dict, "conservation": dict, "total_decisions": int, "total_correct": int})
