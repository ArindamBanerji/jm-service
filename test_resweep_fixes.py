"""Round-two backend regressions on SQLite and PostgreSQL."""
import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from threading import Thread

import pytest
from sqlalchemy import func, select

import billing
import label_studio
import scheduler
from db.models import ApiKey, ConnectorConfigRow, Domain, LabelLog
from test_billing_fixes import deliver, event
from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PADDLE_SANDBOX", "true")
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "test-signing-secret")
    monkeypatch.setenv("LABEL_STUDIO_TOKEN", "test-token")
    monkeypatch.setenv("LS_CONFIG_PATH", str(tmp_path / "connector.json"))
    with open_tasks_client(tmp_path) as http:
        http.app.include_router(billing.router)
        http.app.include_router(label_studio.router)
        factory = http.app.state.session_factory
        monkeypatch.setattr(billing, "AsyncSessionLocal", factory)
        monkeypatch.setattr(scheduler, "AsyncSessionLocal", factory)
        yield http


def read_key(client):
    async def read():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(ApiKey).where(
                ApiKey.key_hash == hashlib.sha256(b"tasks-key").hexdigest()))).one()
    return asyncio.run(read())


def set_key(client, **values):
    async def write():
        async with client.app.state.session_factory.begin() as session:
            row = (await session.scalars(select(ApiKey).where(
                ApiKey.key_hash == hashlib.sha256(b"tasks-key").hexdigest()))).one()
            for name, value in values.items():
                setattr(row, name, value)
    asyncio.run(write())


def count(client, model):
    async def read():
        async with client.app.state.session_factory() as session:
            return await session.scalar(select(func.count()).select_from(model))
    return asyncio.run(read())


def ingest(client, label_id="L1", category="A", text=None):
    return client.post("/v1/labels/ingest", json={
        "domain_id": "medical", "label_id": label_id, "category": category,
        "factors": {"confidence": .7, "difficulty": .2}, "text": text})


def detail(client, label_id="L1"):
    return client.get(f"/v1/labels/medical/items/{label_id}").json()


def verify(client, label_id="L1", outcome=False):
    return client.post("/v1/labels/verify", json={
        "domain_id": "medical", "label_id": label_id,
        "actual_action": "approve", "verified_outcome": outcome})


def setup_retention(client):
    assert ingest(client).status_code == 200
    set_key(client, tier="professional", paddle_subscription_id="sub-1",
            cancelled_at=datetime.now(timezone.utc) - timedelta(days=31))


def test_reactivation_between_scan_and_lock_prevents_cleanup(client, monkeypatch):
    setup_retention(client)
    real_factory = client.app.state.session_factory

    class ReactivatingFactory:
        def __call__(self):
            return real_factory()

        @asynccontextmanager
        async def begin(self):
            async def reactivate():
                async with real_factory.begin() as session:
                    row = await session.scalar(select(ApiKey))
                    row.cancelled_at = None
            await reactivate()
            async with real_factory.begin() as session:
                yield session

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", ReactivatingFactory())
    assert asyncio.run(scheduler.cleanup_cancelled_tenants()) == 0
    assert read_key(client).is_active and read_key(client).cancelled_at is None
    assert count(client, LabelLog) == 1


def test_cleanup_still_cancelled_deletes_tenant(client):
    setup_retention(client)
    assert asyncio.run(scheduler.cleanup_cancelled_tenants()) == 1
    assert not read_key(client).is_active
    assert count(client, LabelLog) == count(client, Domain) == 0


@pytest.mark.parametrize("product", ["Unknown product", "DLJ Retired"])
def test_cancellation_ignores_product(client, product):
    assert deliver(client, event()).status_code == 200
    assert deliver(client, event("canceled", 2, product)).status_code == 200
    assert read_key(client).cancelled_at is not None


def test_bulk_explicit_false_on_recommended_reject(client):
    assert ingest(client).status_code == 200
    async def recommend_reject():
        async with client.app.state.session_factory.begin() as session:
            row = await session.scalar(select(LabelLog))
            row.recommended_action = "reject"
    asyncio.run(recommend_reject())
    response = client.post("/v1/labels/medical/bulk-verify", json={
        "label_ids": ["L1"], "action": "approve", "outcome": False})
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == 1
    assert detail(client)["verified_outcome"] is False


def test_bulk_explicit_true_on_approve(client):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/medical/bulk-verify", json={
        "label_ids": ["L1"], "action": "approve", "outcome": True})
    assert response.status_code == 200, response.text
    assert detail(client)["verified_outcome"] is True


def test_bulk_without_truth_does_not_verify(client):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/medical/bulk-verify", json={
        "label_ids": ["L1"], "action": "reject"})
    assert response.status_code == 200, response.text
    assert response.json() == {"processed": 0, "skipped": 1,
                               "errors": [{"label_id": "L1", "error": "outcome_required"}]}
    assert detail(client)["verified_at"] is None


def test_batch_conflict_log_redacts_source(client, caplog):
    source = "SENSITIVE-SOURCE-98765"
    assert ingest(client, text=source).status_code == 200
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "medical", "items": [{
        "label_id": "L1", "category": "A", "text": source,
        "factors": {"confidence": .7, "difficulty": .2}}]})
    assert response.status_code == 422
    assert source not in caplog.text and "confidence" not in caplog.text
    assert "IntegrityError" in caplog.text
    records = [record for record in caplog.records if "Batch item" in record.message]
    assert len(records) == 1 and len(records[0].request_id) == 32


@pytest.mark.parametrize("field,value", [("categories", ["A|B"]), ("actions", ["approve", "re|ject"])])
def test_legacy_separator_rejected(field, value):
    from pydantic import ValidationError
    from jm_service import CreateDomainRequest
    body = {"name": "Legacy", "factors": ["confidence"],
            "categories": ["A"], "actions": ["approve", "reject"]}
    body[field] = value
    with pytest.raises(ValidationError, match="Category/action names must not contain"):
        CreateDomainRequest.model_validate(body)


def test_verified_incorrect_same_category_conflicts(client):
    assert ingest(client).status_code == 200
    assert verify(client).status_code == 200
    revision = detail(client)["revision_id"]
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "A", "idempotency_token": revision})
    assert response.status_code == 409
    assert response.json()["detail"] == "No change detected."
    assert detail(client)["revision_id"] == revision


def test_verified_incorrect_different_category_succeeds(client):
    assert ingest(client).status_code == 200
    assert ingest(client, "L2", "B").status_code == 200
    assert verify(client).status_code == 200
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "B", "idempotency_token": detail(client)["revision_id"]})
    assert response.status_code == 200, response.text
    assert detail(client)["category"] == "B"


def test_cancelled_paid_key_uses_trial_daily_cap(client):
    set_key(client, tier="professional", labels_today=50,
            labels_day_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            cancelled_at=datetime.now(timezone.utc) - timedelta(days=1))
    response = ingest(client)
    assert response.status_code == 429
    assert response.json()["detail"]["scope"] == "daily"


def test_active_paid_key_keeps_paid_cap(client):
    set_key(client, tier="professional", labels_today=50,
            labels_day_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    assert ingest(client).status_code == 200
    assert read_key(client).labels_today == 51


def connector_event(result, annotation_id=1):
    return {"project": "p1", "action": "ANNOTATION_CREATED",
            "annotation": {"id": annotation_id, "task": 1, "result": result},
            "task": {"id": 1, "data": {"category": "NER", "ml_confidence": .7,
                                      "agreement_score": .2, "ground_truth": "approve"}}}


def test_malformed_connector_result_rejected_before_lookup(client):
    response = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"},
                           json=connector_event([3]))
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid annotation result"
    assert count(client, LabelLog) == 0


def test_null_connector_annotation_id_is_rejected(client):
    response = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"},
                           json=connector_event([{"value": {"choices": ["approve"]}}], None))
    assert response.status_code == 422
    assert count(client, LabelLog) == 0


def test_concurrent_connector_config_preserves_both_projects(client):
    results = []
    def configure(project):
        results.append(client.post("/v1/label-studio/configure", headers={"X-LS-Token": "test-token"},
                                   json={"domain_id": "medical", "project_id": project,
                                         "factor_map": {"a": "data.a", "b": "data.b"}}))
    threads = [Thread(target=configure, args=(project,)) for project in ("p1", "p2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert [response.status_code for response in results] == [200, 200]
    async def read_configs():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(ConnectorConfigRow).where(
                ConnectorConfigRow.tenant_id == "tasks-tenant"))).all()
    saved = asyncio.run(read_configs())
    assert {row.project_id for row in saved} == {"p1", "p2"}
    assert all(row.version == 1 and row.config_json["domain_id"] == "medical" for row in saved)


def test_connector_overflow_integer_is_422(client):
    response = client.post("/v1/label-studio/predict", headers={"X-LS-Token": "test-token"},
                           json={"project": "p1", "tasks": [{"id": 1, "data": {
                               "ml_confidence": 10 ** 400, "agreement_score": .2}}]})
    assert response.status_code == 422


def test_connector_webhook_invalid_item_is_422(client):
    payload = connector_event([{"value": {"choices": ["approve"]}}])
    payload["task"]["data"]["category"] = "x" * 201
    response = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"},
                           json=payload)
    assert response.status_code == 422
    assert count(client, LabelLog) == 0
