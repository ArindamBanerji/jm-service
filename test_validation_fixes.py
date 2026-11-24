"""Regression coverage for relabel safety and API validation on both databases."""
import os

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from starlette.testclient import TestClient

import labeling_router
from jm_service import CreateDomainRequest
from label_studio import router as studio_router
from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("LABEL_STUDIO_TOKEN", "test-token")
    monkeypatch.setenv("LABEL_STUDIO_DOMAIN_ID", "ls-demo")
    monkeypatch.setenv("LS_CONFIG_PATH", str(tmp_path / "connector.json"))
    with open_tasks_client(tmp_path) as result:
        result.app.include_router(studio_router)
        yield result


def ingest(client, label_id="L1", category="A", **extra):
    return client.post("/v1/labels/ingest", json={
        "domain_id": "medical", "label_id": label_id, "category": category,
        "factors": {"confidence": .7, "difficulty": .2}, **extra})


def revision(client, label_id="L1"):
    return client.get(f"/v1/labels/medical/items/{label_id}").json()["revision_id"]


def relabel(client, token, category="A"):
    return client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": category, "idempotency_token": token})


def verify(client, outcome):
    return client.post("/v1/labels/verify", json={
        "domain_id": "medical", "label_id": "L1", "actual_action": "approve",
        "verified_outcome": outcome})


def test_unknown_relabel_category(client):
    assert ingest(client).status_code == 200
    response = relabel(client, revision(client), "UNKNOWN")
    assert response.status_code == 422
    assert response.json()["detail"] == "Category not in domain schema: UNKNOWN"


def test_valid_relabel_category(client):
    assert ingest(client).status_code == 200
    assert ingest(client, "L2", "B").status_code == 200
    response = relabel(client, revision(client), "B")
    assert response.status_code == 200, response.text
    assert response.json()["category"] == "B"
    successor = next(row for row in client.get("/v1/labels/medical/pending").json()
                     if row["category"] == "B" and row["label_id"] != "L2")
    checked = client.post("/v1/labels/verify", json={"domain_id": "medical",
        "label_id": successor["label_id"], "actual_action": "approve", "verified_outcome": True})
    assert checked.status_code == 200, checked.text


def test_verified_relabel_rejected(client):
    assert ingest(client).status_code == 200
    assert verify(client, True).status_code == 200
    response = relabel(client, revision(client))
    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot relabel a verified label. Use verify to change the outcome."


def test_incorrect_verification_can_be_corrected(client):
    assert ingest(client).status_code == 200
    assert verify(client, False).status_code == 200
    response = relabel(client, revision(client))
    assert response.status_code == 200, response.text
    assert client.get("/v1/labels/medical/items/L1").json()["verified_at"] is None


def test_domain_creation_race_returns_conflict(client, monkeypatch):
    async def conflict(*args, **kwargs):
        raise IntegrityError("INSERT INTO domains SECRET", {"text": "SECRET"}, Exception("duplicate"))
    monkeypatch.setattr(labeling_router.repository, "create_domain", conflict)
    response = client.post("/v1/labels/medical/tasks", json={"label_id": "T1", "text": "hello"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Domain already exists"


def test_long_label_id(client):
    assert ingest(client, label_id="x" * 201).status_code == 422


def test_long_annotator_id(client):
    assert ingest(client, annotator_id="x" * 201).status_code == 422


def test_long_category(client):
    assert ingest(client, category="x" * 201).status_code == 422


def test_batch_error_hides_sql(client, monkeypatch):
    async def conflict(*args, **kwargs):
        raise IntegrityError("INSERT INTO labels SECRET", {"text": "SECRET"}, Exception("duplicate"))
    monkeypatch.setattr(labeling_router, "_ingest", conflict)
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "medical", "items": [
        {"label_id": "L1", "category": "A", "factors": {"confidence": .7, "difficulty": .2}}]})
    assert response.status_code == 422
    assert "SECRET" not in response.text and "INSERT" not in response.text


def test_batch_duplicate_has_clean_message(client):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "medical", "items": [
        {"label_id": "L1", "category": "A", "factors": {"confidence": .7, "difficulty": .2}}]})
    assert response.status_code == 422
    assert response.json()["detail"] == {"item_index": 0, "error": "Duplicate or conflict at item 0"}


def predict(client, tasks):
    return client.post("/v1/label-studio/predict", headers={"X-LS-Token": "test-token"},
                       json={"project": "p1", "tasks": tasks})


def test_connector_non_object_task(client):
    response = predict(client, [123])
    assert response.status_code == 422
    assert "index 0" in response.text


def test_connector_invalid_factor(client):
    response = predict(client, [{"id": 1, "data": {"ml_confidence": 1.5, "agreement_score": .2}}])
    assert response.status_code == 422
    assert "index 0" in response.text


def test_empty_factor_range():
    app = FastAPI()
    @app.post("/domain")
    def domain(request: CreateDomainRequest):
        return request.model_dump()
    with TestClient(app) as client:
        assert client.post("/domain", json={"name": "test", "factors": ["a"],
            "categories": ["A"], "actions": ["approve", "reject"],
            "factor_ranges": {"a": []}}).status_code == 422


def test_single_element_factor_range():
    app = FastAPI()
    @app.post("/domain")
    def domain(request: CreateDomainRequest):
        return request.model_dump()
    with TestClient(app) as client:
        assert client.post("/domain", json={"name": "test", "factors": ["a"],
            "categories": ["A"], "actions": ["approve", "reject"],
            "factor_ranges": {"a": [0]}}).status_code == 422
