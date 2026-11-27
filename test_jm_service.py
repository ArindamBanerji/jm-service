"""
test_jm_service.py — MVP Integration Test Suite

Tests the full JM API via FastAPI TestClient (no server needed).
Covers: registration, domain CRUD, score/learn loop, compounding,
error cases, validation, and state persistence.

Run: pytest test_jm_service.py -v
"""

import json
import asyncio
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


# ─── Fixtures ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Each test gets a fresh SQLite database."""
    db_path = str(tmp_path / "test.db")
    os.environ["JM_DB_PATH"] = db_path

    # Point the shared app at this test's database and clear its in-memory quotas.
    import jm_service
    jm_service.DB_PATH = db_path
    jm_service.limiter.reset()
    jm_service.init_db()

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def client(clean_db):
    import jm_service
    from pathlib import Path

    url = os.getenv("DLJ_DATABASE_URL") or f"sqlite+aiosqlite:///{Path(clean_db).with_name('labeling.db').as_posix()}"
    labeling_engine = create_async_engine(url, poolclass=NullPool)
    jm_service.labeling_engine = labeling_engine
    with TestClient(jm_service.app) as test_client:
        yield test_client
    asyncio.run(labeling_engine.dispose())


@pytest.fixture
def api_key(client):
    """Register a tenant and return the API key."""
    resp = client.post("/v1/register", json={"name": "test-tenant"})
    assert resp.status_code == 200
    return resp.json()["api_key"]


@pytest.fixture
def domain_id(client, api_key):
    """Create a procurement domain and return its ID."""
    resp = client.post(
        "/v1/domains",
        json={
            "name": "Procurement",
            "factors": ["spend", "risk", "urgency"],
            "categories": ["invoice", "po"],
            "actions": ["approve", "escalate", "reject"],
        },
        headers={"x-api-key": api_key},
    )
    assert resp.status_code == 201
    return resp.json()["domain_id"]


# ─── Registration Tests ─────────────────────────────────────────

class TestRegistration:
    def test_register_returns_api_key(self, client):
        resp = client.post("/v1/register", json={"name": "my-company"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"].startswith("jm_")
        assert len(data["api_key"]) == 27  # "jm_" + 24 hex chars
        assert data["name"] == "my-company"

    def test_register_default_name(self, client):
        resp = client.post("/v1/register")
        assert resp.status_code == 200
        assert resp.json()["name"] == "default"

    def test_two_registrations_get_different_keys(self, client):
        r1 = client.post("/v1/register", json={"name": "a"})
        r2 = client.post("/v1/register", json={"name": "b"})
        assert r1.json()["api_key"] != r2.json()["api_key"]


class TestRateLimits:
    def test_registration_limit_and_health_exemption(self, client):
        for _ in range(10):
            assert client.post("/v1/register").status_code == 200
        assert client.post("/v1/register").status_code == 429
        assert client.get("/v1/health").status_code == 200

    def test_score_limit(self, client, api_key, domain_id):
        url = f"/v1/domains/{domain_id}/score"
        payload = {"factors": {"spend": 0.5, "risk": 0.5, "urgency": 0.5},
                   "category": "invoice"}
        headers = {"x-api-key": api_key}
        for _ in range(30):
            assert client.post(url, json=payload, headers=headers).status_code == 200
        assert client.post(url, json=payload, headers=headers).status_code == 429

    def test_read_limit(self, client, api_key):
        headers = {"x-api-key": api_key}
        for _ in range(60):
            assert client.get("/v1/domains", headers=headers).status_code == 200
        assert client.get("/v1/domains", headers=headers).status_code == 429


# ─── Auth Tests ──────────────────────────────────────────────────

class TestAuth:
    def test_no_api_key_returns_422(self, client):
        resp = client.get("/v1/domains")
        assert resp.status_code == 422  # FastAPI missing header

    def test_bad_api_key_returns_401(self, client):
        resp = client.get("/v1/domains", headers={"x-api-key": "jm_fake"})
        assert resp.status_code == 401


# ─── Domain Tests ────────────────────────────────────────────────

class TestDomains:
    def test_create_domain(self, client, api_key):
        resp = client.post(
            "/v1/domains",
            json={
                "name": "Test Domain",
                "factors": ["a", "b"],
                "categories": ["cat1"],
                "actions": ["act1", "act2"],
            },
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["domain_id"].startswith("dom_")
        assert data["centroids_initialized"] == 2  # 1 cat × 2 actions
        assert data["factors"] == ["a", "b"]

    def test_list_domains(self, client, api_key, domain_id):
        resp = client.get("/v1/domains", headers={"x-api-key": api_key})
        assert resp.status_code == 200
        domains = resp.json()["domains"]
        assert len(domains) == 1
        assert domains[0]["domain_id"] == domain_id
        assert domains[0]["name"] == "Procurement"

    def test_empty_domain_list(self, client, api_key):
        resp = client.get("/v1/domains", headers={"x-api-key": api_key})
        assert resp.status_code == 200
        assert resp.json()["domains"] == []

    def test_create_domain_rejects_duplicates_in_factors(self, client, api_key):
        resp = client.post(
            "/v1/domains",
            json={
                "name": "Bad",
                "factors": ["a", "a", "b"],
                "categories": ["c"],
                "actions": ["x", "y"],
            },
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422

    def test_create_domain_rejects_single_action(self, client, api_key):
        resp = client.post(
            "/v1/domains",
            json={
                "name": "Bad",
                "factors": ["a"],
                "categories": ["c"],
                "actions": ["only_one"],
            },
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422

    def test_create_domain_rejects_empty_factor_name(self, client, api_key):
        resp = client.post(
            "/v1/domains",
            json={
                "name": "Bad",
                "factors": ["a", ""],
                "categories": ["c"],
                "actions": ["x", "y"],
            },
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422


# ─── Score Tests ─────────────────────────────────────────────────

class TestScore:
    def test_cold_score(self, client, api_key, domain_id):
        resp = client.post(
            f"/v1/domains/{domain_id}/score",
            json={"factors": {"spend": 0.5, "risk": 0.5, "urgency": 0.5}, "category": "invoice"},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "decision_id" in data
        assert data["recommended_action"] in ["approve", "escalate", "reject"]
        assert 0.0 <= data["confidence"] <= 1.0
        assert data["gate_status"] == "warmup"
        assert data["category"] == "invoice"
        assert len(data["all_scores"]) == 3

    def test_unknown_category_rejected(self, client, api_key, domain_id):
        resp = client.post(
            f"/v1/domains/{domain_id}/score",
            json={"factors": {"spend": 0.5}, "category": "nonexistent"},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422
        assert "Unknown category" in resp.json()["detail"]

    def test_unknown_factor_rejected(self, client, api_key, domain_id):
        resp = client.post(
            f"/v1/domains/{domain_id}/score",
            json={"factors": {"spend": 0.5, "BOGUS": 0.9}, "category": "invoice"},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422
        assert "Unknown factors" in resp.json()["detail"]

    def test_factor_values_clamped(self, client, api_key, domain_id):
        """Values outside [0,1] should be clamped, not rejected."""
        resp = client.post(
            f"/v1/domains/{domain_id}/score",
            json={"factors": {"spend": 1.5, "risk": -0.3, "urgency": 0.5}, "category": "invoice"},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 200  # clamped, not rejected

    def test_nonexistent_domain_404(self, client, api_key):
        resp = client.post(
            "/v1/domains/dom_nonexistent/score",
            json={"factors": {"x": 0.5}, "category": "y"},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 404


# ─── Learn Tests ─────────────────────────────────────────────────

class TestLearn:
    def _score(self, client, api_key, domain_id):
        resp = client.post(
            f"/v1/domains/{domain_id}/score",
            json={"factors": {"spend": 0.8, "risk": 0.2, "urgency": 0.6}, "category": "invoice"},
            headers={"x-api-key": api_key},
        )
        return resp.json()["decision_id"]

    def test_learn_confirm(self, client, api_key, domain_id):
        dec_id = self._score(client, api_key, domain_id)
        resp = client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": dec_id, "actual_action": "approve", "confirmed": True},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["centroid_moved"] is True
        assert data["learning_rate_used"] == 0.05

    def test_learn_override(self, client, api_key, domain_id):
        dec_id = self._score(client, api_key, domain_id)
        resp = client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": dec_id, "actual_action": "reject", "confirmed": False},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 200
        assert resp.json()["learning_rate_used"] == 0.01

    def test_duplicate_learn_rejected(self, client, api_key, domain_id):
        dec_id = self._score(client, api_key, domain_id)
        # First learn
        client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": dec_id, "actual_action": "approve", "confirmed": True},
            headers={"x-api-key": api_key},
        )
        # Second learn — should fail
        resp = client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": dec_id, "actual_action": "reject", "confirmed": False},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 409
        assert "already has a learn result" in resp.json()["detail"]

    def test_unknown_action_rejected(self, client, api_key, domain_id):
        dec_id = self._score(client, api_key, domain_id)
        resp = client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": dec_id, "actual_action": "BOGUS_ACTION", "confirmed": True},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 422
        assert "Unknown action" in resp.json()["detail"]

    def test_nonexistent_decision_404(self, client, api_key, domain_id):
        resp = client.post(
            f"/v1/domains/{domain_id}/learn",
            json={"decision_id": "fake_id_12345", "actual_action": "approve", "confirmed": True},
            headers={"x-api-key": api_key},
        )
        assert resp.status_code == 404


# ─── Compounding Test ────────────────────────────────────────────

class TestCompounding:
    def test_accuracy_improves_with_training(self, client, api_key, domain_id, monkeypatch):
        """The core JM claim: score/learn loop produces compounding accuracy."""
        import jm_service
        import random
        monkeypatch.setattr(jm_service.limiter, "enabled", False)
        random.seed(42)

        headers = {"x-api-key": api_key}

        # Define a ground truth: high spend + low risk → approve, otherwise escalate
        def ground_truth(spend, risk, urgency):
            if spend > 0.6 and risk < 0.4:
                return "approve"
            elif risk > 0.7:
                return "reject"
            else:
                return "escalate"

        # Cold accuracy (first 20)
        cold_correct = 0
        for _ in range(20):
            s, r, u = random.random(), random.random(), random.random()
            resp = client.post(
                f"/v1/domains/{domain_id}/score",
                json={"factors": {"spend": s, "risk": r, "urgency": u}, "category": "invoice"},
                headers=headers,
            )
            data = resp.json()
            truth = ground_truth(s, r, u)
            if data["recommended_action"] == truth:
                cold_correct += 1
            # Learn the truth
            client.post(
                f"/v1/domains/{domain_id}/learn",
                json={"decision_id": data["decision_id"], "actual_action": truth, "confirmed": data["recommended_action"] == truth},
                headers=headers,
            )

        cold_accuracy = cold_correct / 20

        # Train 200 more
        for _ in range(200):
            s, r, u = random.random(), random.random(), random.random()
            resp = client.post(
                f"/v1/domains/{domain_id}/score",
                json={"factors": {"spend": s, "risk": r, "urgency": u}, "category": "invoice"},
                headers=headers,
            )
            data = resp.json()
            truth = ground_truth(s, r, u)
            client.post(
                f"/v1/domains/{domain_id}/learn",
                json={"decision_id": data["decision_id"], "actual_action": truth, "confirmed": data["recommended_action"] == truth},
                headers=headers,
            )

        # Warm accuracy (next 30)
        warm_correct = 0
        for _ in range(30):
            s, r, u = random.random(), random.random(), random.random()
            resp = client.post(
                f"/v1/domains/{domain_id}/score",
                json={"factors": {"spend": s, "risk": r, "urgency": u}, "category": "invoice"},
                headers=headers,
            )
            data = resp.json()
            truth = ground_truth(s, r, u)
            if data["recommended_action"] == truth:
                warm_correct += 1
            client.post(
                f"/v1/domains/{domain_id}/learn",
                json={"decision_id": data["decision_id"], "actual_action": truth, "confirmed": data["recommended_action"] == truth},
                headers=headers,
            )

        warm_accuracy = warm_correct / 30

        # The gap should be meaningful (>10pp improvement)
        improvement = warm_accuracy - cold_accuracy
        assert improvement > 0.10, (
            f"Expected >10pp improvement, got {improvement:.1%} "
            f"(cold={cold_accuracy:.1%}, warm={warm_accuracy:.1%})"
        )


# ─── Diagnostics & State ────────────────────────────────────────

class TestDiagnostics:
    def test_diagnostics(self, client, api_key, domain_id):
        headers = {"x-api-key": api_key}
        # Score + learn a few times
        for _ in range(5):
            resp = client.post(
                f"/v1/domains/{domain_id}/score",
                json={"factors": {"spend": 0.7, "risk": 0.3, "urgency": 0.5}, "category": "invoice"},
                headers=headers,
            )
            dec_id = resp.json()["decision_id"]
            client.post(
                f"/v1/domains/{domain_id}/learn",
                json={"decision_id": dec_id, "actual_action": "approve", "confirmed": True},
                headers=headers,
            )

        resp = client.get(f"/v1/domains/{domain_id}/diagnostics", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_decisions"] == 5
        assert "noise_fingerprint" in data
        assert "spend" in data["noise_fingerprint"]
        assert "gate_status" in data
        assert "state_size_bytes" in data
        assert data["state_size_bytes"] > 0

    def test_state_export(self, client, api_key, domain_id):
        headers = {"x-api-key": api_key}
        resp = client.get(f"/v1/domains/{domain_id}/state", headers=headers)
        assert resp.status_code == 200
        state = resp.json()
        assert "config" in state
        assert "centroids" in state
        assert state["config"]["factors"] == ["spend", "risk", "urgency"]


# ─── Multi-Tenant Isolation ──────────────────────────────────────

class TestMultiTenant:
    def test_tenant_isolation(self, client):
        """Two tenants can't see each other's domains."""
        # Register two tenants
        r1 = client.post("/v1/register", json={"name": "tenant-a"})
        r2 = client.post("/v1/register", json={"name": "tenant-b"})
        key_a = r1.json()["api_key"]
        key_b = r2.json()["api_key"]

        # Tenant A creates a domain
        resp = client.post(
            "/v1/domains",
            json={
                "name": "A's Domain",
                "factors": ["x"],
                "categories": ["c"],
                "actions": ["a1", "a2"],
            },
            headers={"x-api-key": key_a},
        )
        dom_a = resp.json()["domain_id"]

        # Tenant B can't see it
        resp = client.get("/v1/domains", headers={"x-api-key": key_b})
        assert resp.json()["domains"] == []

        # Tenant B can't score on it
        resp = client.post(
            f"/v1/domains/{dom_a}/score",
            json={"factors": {"x": 0.5}, "category": "c"},
            headers={"x-api-key": key_b},
        )
        assert resp.status_code == 404


# ─── Health ──────────────────────────────────────────────────────

class TestHealth:
    def test_health(self, client):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
        assert resp.json()["version"] == "0.2.0"
        assert resp.json()["checks"] == {
            "labeling_db": "connected", "legacy_db": "connected", "engine_hash": "verified"
        }
