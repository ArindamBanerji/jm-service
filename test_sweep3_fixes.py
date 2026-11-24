"""Round-three backend regressions on SQLite and PostgreSQL."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import label_health.api as health_api
import label_studio
import scheduler
from db import repository
from db.models import ApiKey, Domain, Engine, LabelContent, LabelLog
from test_billing_fixes import deliver, event
from test_label_studio import event as connector_event, task as connector_task
from test_resweep_fixes import client, count, detail, ingest, read_key, set_key, verify


def keys(client):
    async def read():
        async with client.app.state.session_factory() as session:
            return list((await session.scalars(select(ApiKey).where(
                ApiKey.tenant_id == "tasks-tenant"))).all())
    return asyncio.run(read())


def add_sibling(client, *, cancelled_at):
    async def write():
        async with client.app.state.session_factory.begin() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(b"sibling-key").hexdigest(),
                               tenant_id="tasks-tenant", tenant_name="Sibling",
                               tier="professional", cancelled_at=cancelled_at))
    asyncio.run(write())


def test_two_expired_cancelled_keys_clean_together(client):
    assert ingest(client).status_code == 200
    old = datetime.now(timezone.utc) - timedelta(days=31)
    set_key(client, tier="professional", cancelled_at=old, paddle_subscription_id="sub-1")
    add_sibling(client, cancelled_at=old)
    assert asyncio.run(scheduler.cleanup_cancelled_tenants()) == 2
    assert all(not key.is_active for key in keys(client))
    assert count(client, Domain) == count(client, LabelLog) == 0


def test_active_sibling_preserves_data_while_cancelled_key_expires(client):
    assert ingest(client).status_code == 200
    set_key(client, tier="professional", cancelled_at=datetime.now(timezone.utc) - timedelta(days=31))
    add_sibling(client, cancelled_at=None)
    assert asyncio.run(scheduler.cleanup_cancelled_tenants()) == 1
    active = {key.key_hash: key.is_active for key in keys(client)}
    assert not active[hashlib.sha256(b"tasks-key").hexdigest()]
    assert active[hashlib.sha256(b"sibling-key").hexdigest()]
    assert count(client, Domain) == count(client, LabelLog) == 1


@pytest.mark.parametrize("kind,extra", [
    ("canceled", {}), ("updated", {"status": "canceled"}),
])
def test_cancel_without_items_still_sets_cancelled_at(client, kind, extra):
    assert deliver(client, event()).status_code == 200
    payload = event(kind, 2, items=[], **extra)
    assert deliver(client, payload).status_code == 200
    assert read_key(client).cancelled_at is not None


def test_implicit_bulk_approve_sets_true(client):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/medical/bulk-verify", json={"label_ids": ["L1"], "action": "approve"})
    assert response.status_code == 200, response.text
    assert detail(client)["verified_outcome"] is True


def test_implicit_bulk_reject_sets_false(client):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/medical/bulk-verify", json={"label_ids": ["L1"], "action": "reject"})
    assert response.status_code == 200, response.text
    assert detail(client)["verified_outcome"] is False


def attach_spans(client):
    assert ingest(client, text="John Smith").status_code == 200
    spans = [{"start": 0, "end": 4, "label": "A", "text": "John"}]
    response = client.post("/v1/labels/medical/items/L1/content", json={
        "content_type": "text_ner", "spans": spans, "tags": [], "image_url": None})
    assert response.status_code == 201, response.text
    return spans


def test_identical_category_and_spans_is_noop(client):
    spans = attach_spans(client)
    assert verify(client, outcome=False).status_code == 200
    token = detail(client)["revision_id"]
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "A", "idempotency_token": token, "spans": spans})
    assert response.status_code == 409
    assert response.json()["detail"] == "No change detected."
    assert detail(client)["revision_id"] == token


def test_same_category_with_changed_spans_is_valid(client):
    attach_spans(client)
    assert verify(client, outcome=False).status_code == 200
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "A", "idempotency_token": detail(client)["revision_id"],
        "spans": [{"start": 5, "end": 10, "label": "A", "text": "Smith"}]})
    assert response.status_code == 200, response.text
    revised = detail(client)
    assert revised["content"]["spans"][0]["text"] == "Smith"
    assert revised["verified_at"] is None


def test_sqlite_naive_cancelled_timestamp_uses_daily_cap(client):
    set_key(client, tier="professional", labels_today=50,
            labels_day_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            cancelled_at=datetime.now(timezone.utc) - timedelta(days=1))
    assert read_key(client).cancelled_at is not None
    response = ingest(client)
    assert response.status_code == 429
    assert response.json()["detail"]["scope"] == "daily"


@pytest.mark.parametrize("remove_config_category", [True, False])
def test_connector_verify_syncs_missing_category_centroid(client, monkeypatch, remove_config_category):
    monkeypatch.setenv("LABEL_STUDIO_DOMAIN_ID", "ls-demo")
    task = connector_task()
    task["annotator_id"] = "7"
    predicted = client.post("/v1/label-studio/predict", headers={"X-LS-Token": "test-token"},
                            json={"project": "p1", "tasks": [task]})
    assert predicted.status_code == 200, predicted.text

    async def stale_snapshot():
        async with client.app.state.session_factory.begin() as session:
            engine = await session.scalar(select(Engine).where(Engine.annotator_id == "7"))
            assert engine is not None
            state = dict(engine.state_json)
            if remove_config_category:
                state["config"] = {**state["config"], "categories": ["default"]}
            state["centroids"] = {name: values for name, values in state["centroids"].items()
                                   if not name.startswith("NER|")}
            engine.state_json = state
    asyncio.run(stale_snapshot())
    response = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"},
                           json=connector_event())
    assert response.status_code == 200, response.text
    async def read_centroids():
        async with client.app.state.session_factory() as session:
            engine = await session.scalar(select(Engine).where(Engine.annotator_id == "7"))
            assert engine is not None
            return engine.state_json["centroids"]
    assert "NER|approve" in asyncio.run(read_centroids())


def correction_with_content(client, monkeypatch, content_type, spans, tags):
    monkeypatch.setenv("LABEL_STUDIO_DOMAIN_ID", "ls-demo")
    first = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"},
                        json=connector_event())
    assert first.status_code == 200, first.text
    async def attach():
        async with client.app.state.session_factory.begin() as session:
            original = await session.scalar(select(LabelLog).where(LabelLog.source_task_id == "1"))
            assert original is not None
            original.text = "John Smith"
            await repository.record_label_content(session, original.id, content_type, spans, tags, None)
    asyncio.run(attach())
    changed = connector_event(action="ANNOTATION_UPDATED", actual="reject", truth="reject")
    response = client.post("/v1/label-studio/webhook", headers={"X-LS-Token": "test-token"}, json=changed)
    assert response.status_code == 200, response.text
    async def content():
        async with client.app.state.session_factory() as session:
            original = await session.scalar(select(LabelLog).where(LabelLog.source_task_id == "1")
                                            .order_by(LabelLog.scored_at, LabelLog.id))
            assert original is not None and original.superseded_by is not None
            successor = await session.scalar(select(LabelLog).where(LabelLog.label_id == original.superseded_by))
            assert successor is not None
            return await repository.get_label_content(session, successor.id)
    return asyncio.run(content())


def test_connector_revision_copies_ner_spans(client, monkeypatch):
    spans = [{"start": 0, "end": 4, "label": "NER", "text": "John"}]
    copied = correction_with_content(client, monkeypatch, "text_ner", spans, [])
    assert copied is not None and copied.spans_json == spans


def test_connector_revision_copies_tags(client, monkeypatch):
    copied = correction_with_content(client, monkeypatch, "text_multilabel", [], ["NER"])
    assert copied is not None and copied.tags_json == ["NER"]


def test_busy_report_worker_rejects_before_read(monkeypatch):
    monkeypatch.setattr(health_api, "_slots", asyncio.Semaphore(0))
    class UnreadFile:
        filename = "labels.csv"
        async def read(self, limit):
            raise AssertionError("upload body was read")
    with pytest.raises(HTTPException) as error:
        asyncio.run(health_api._analyze(UnreadFile(), "json"))
    assert error.value.status_code == 503
    app = FastAPI()
    app.include_router(health_api.router)
    response = TestClient(app).post("/v1/label-health/analyze", content=b"invalid multipart",
                                    headers={"Content-Type": "multipart/form-data; boundary=broken"})
    assert response.status_code == 503


def test_oversized_report_upload_is_rejected(monkeypatch):
    monkeypatch.setattr(health_api, "_slots", asyncio.Semaphore(1))
    class OversizedFile:
        filename = "labels.csv"
        async def read(self, limit):
            assert limit == health_api._MAX_BYTES + 1
            return b"a" * limit
    with pytest.raises(HTTPException) as error:
        asyncio.run(health_api._analyze(OversizedFile(), "json"))
    assert error.value.status_code == 413
    assert health_api._slots._value == 1
    app = FastAPI()
    app.include_router(health_api.router)
    response = TestClient(app).post("/v1/label-health/analyze",
                                    files={"file": ("large.csv", b"a" * (health_api._MAX_BYTES + 1))})
    assert response.status_code == 413
