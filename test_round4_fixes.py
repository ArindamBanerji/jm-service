"""Round-four contract, evidence, provenance, and upload admission regressions."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

import label_health.api as health_api
from auth import scoped_domain_id
from db import repository
from db.models import LabelLog
from test_resweep_fixes import client, detail, ingest, verify
from test_sweep3_fixes import correction_with_content
from test_tasks import add_schema_category


@pytest.mark.parametrize("action,outcome", [("approve", True), ("reject", False)])
def test_bulk_outcome_field_reaches_verified_label(client, action, outcome):
    assert ingest(client).status_code == 200
    response = client.post("/v1/labels/medical/bulk-verify", json={
        "label_ids": ["L1"], "action": action, "outcome": outcome,
    })
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == 1
    assert detail(client)["verified_outcome"] is outcome


def test_reordered_tags_do_not_create_revision(client):
    assert ingest(client, text="Example").status_code == 200
    add_schema_category(client, "B")
    attached = client.post("/v1/labels/medical/items/L1/content", json={
        "content_type": "text_multilabel", "spans": [], "tags": ["A", "B"], "image_url": None,
    })
    assert attached.status_code == 201, attached.text
    token = detail(client)["revision_id"]
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "A", "idempotency_token": token, "tags": ["B", "A"],
    })
    assert response.status_code == 409, response.text
    assert detail(client)["revision_id"] == token


def test_empty_ner_content_is_a_real_revision(client):
    assert ingest(client, text="Example").status_code == 200
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "A", "idempotency_token": detail(client)["revision_id"], "spans": [],
    })
    assert response.status_code == 200, response.text
    assert detail(client)["content"]["content_type"] == "text_ner"


def test_negative_evidence_remains_until_replacement_verified(client):
    assert ingest(client, text="John Smith").status_code == 200
    add_schema_category(client, "B")
    assert verify(client, outcome=False).status_code == 200

    async def accuracy():
        async with client.app.state.session_factory() as session:
            session.info["tenant_id"] = "tasks-tenant"
            return await repository.verified_accuracy(session, scoped_domain_id("tasks-tenant", "medical"), "A")

    before = asyncio.run(accuracy())
    response = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "B", "idempotency_token": detail(client)["revision_id"],
    })
    assert response.status_code == 200, response.text
    after = asyncio.run(accuracy())
    assert after == before == (1, 0.0)
    revised_id = detail(client)["label_id"]
    assert verify(client, label_id=revised_id, outcome=True).status_code == 200
    assert asyncio.run(accuracy()) == (0, None)


def test_verified_evidence_uses_latest_verified_descendant(client):
    assert ingest(client, text="Example").status_code == 200
    add_schema_category(client, "B")
    assert verify(client, outcome=False).status_code == 200
    first = client.post("/v1/labels/medical/items/L1/relabel", json={
        "category": "B", "idempotency_token": detail(client)["revision_id"],
    })
    assert first.status_code == 200, first.text
    middle = detail(client)
    second = client.post(f"/v1/labels/medical/items/{middle['label_id']}/relabel", json={
        "category": "A", "idempotency_token": middle["revision_id"],
    })
    assert second.status_code == 200, second.text
    latest = detail(client)

    async def accuracy():
        async with client.app.state.session_factory() as session:
            session.info["tenant_id"] = "tasks-tenant"
            return await repository.verified_accuracy(session, scoped_domain_id("tasks-tenant", "medical"), "A")

    assert asyncio.run(accuracy()) == (1, 0.0)
    assert verify(client, label_id=latest["label_id"], outcome=True).status_code == 200
    assert asyncio.run(accuracy()) == (1, 1.0)


def test_connector_revision_copies_image_and_provenance(client, monkeypatch):
    copied = correction_with_content(client, monkeypatch, "image_classification", [], [],
                                     "https://example.test/image.png")
    assert copied is not None and copied.content_type == "image_classification"
    assert copied.image_url == "https://example.test/image.png"

    async def revisions():
        async with client.app.state.session_factory() as session:
            rows = list((await session.scalars(select(LabelLog).where(
                LabelLog.source_task_id == "1").order_by(LabelLog.scored_at, LabelLog.id))).all())
            predecessor = next(row for row in rows if row.superseded_by)
            successor = next(row for row in rows if row.label_id == predecessor.superseded_by)
            return predecessor, successor

    predecessor, successor = asyncio.run(revisions())
    assert successor.prior_revision_id == str(predecessor.id)
    assert successor.revision_actor == "tasks-tenant"
    assert successor.revision_at is not None


def test_stalled_multipart_releases_admission_slot(monkeypatch):
    monkeypatch.setattr(health_api, "_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(health_api, "_UPLOAD_TIMEOUT", .02)

    async def receive():
        await asyncio.sleep(1)
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/v1/label-health/analyze",
                       "headers": [(b"content-type", b"multipart/form-data; boundary=test")]}, receive)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(health_api._analyze_request(request, "json"))
    assert failure.value.status_code == 408
    assert health_api._slots._value == 1


def test_stalled_file_read_releases_admission_slot(monkeypatch):
    monkeypatch.setattr(health_api, "_slots", asyncio.Semaphore(1))

    class SlowFile:
        filename = "labels.csv"

        async def read(self, limit):
            await asyncio.sleep(1)
            return b"label_id\nL1\n"

    async def run():
        deadline = asyncio.get_running_loop().time() + .02
        await health_api._slots.acquire()
        await health_api._analyze(SlowFile(), "json", slot_acquired=True,
                                  intake_deadline=deadline)

    with pytest.raises(HTTPException) as failure:
        asyncio.run(run())
    assert failure.value.status_code == 408
    assert health_api._slots._value == 1


def test_streamed_multipart_total_limit_releases_slot(monkeypatch):
    monkeypatch.setattr(health_api, "_slots", asyncio.Semaphore(1))
    monkeypatch.setattr(health_api, "_MAX_REQUEST_BYTES", 100)

    async def receive():
        return {"type": "http.request", "body": b"x" * 101, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/v1/label-health/analyze",
                       "headers": [(b"content-type", b"multipart/form-data; boundary=test")]}, receive)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(health_api._analyze_request(request, "json"))
    assert failure.value.status_code == 413
    assert health_api._slots._value == 1
