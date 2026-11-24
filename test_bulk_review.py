"""Bulk review uses the same verification transaction on SQLite and PostgreSQL."""
import asyncio
import hashlib
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from db.models import ApiKey, Engine, LabelLog
from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    with open_tasks_client(tmp_path) as result:
        yield result


def seed(client, count=3, headers=None):
    rows = [{"label_id": f"L{index}", "category": "MEDICATION",
             "factors": {"model_confidence": 0.7, "item_difficulty": 0.2}}
            for index in range(count)]
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "medical", "items": rows},
                           headers=headers)
    assert response.status_code == 200, response.text
    return [row["label_id"] for row in rows]


def bulk(client, label_ids, action="approve", headers=None, reason=None):
    body = {"label_ids": label_ids, "action": action}
    if reason is not None:
        body["reason"] = reason
    return client.post("/v1/labels/medical/bulk-verify", json=body, headers=headers)


def rows(client):
    async def read():
        async with client.app.state.session_factory() as session:
            return list((await session.scalars(select(LabelLog).where(
                LabelLog.tenant_id == "tasks-tenant").order_by(LabelLog.label_id))).all())
    return asyncio.run(read())


def test_bulk_approve_confirms_and_learns(client):
    ids = seed(client)
    async def version():
        async with client.app.state.session_factory() as session:
            engine = await session.scalar(select(Engine).where(Engine.tenant_id == "tasks-tenant"))
            assert engine is not None
            return engine.version
    before = asyncio.run(version())
    response = bulk(client, ids, reason="Reviewed against reference")
    assert response.status_code == 200, response.text
    assert response.json() == {"processed": 3, "skipped": 0, "errors": []}
    assert asyncio.run(version()) == before + 3
    assert all(row.verified_outcome is True and row.verified_at is not None and
               row.actual_action == row.recommended_action and
               row.verification_reason == "Reviewed against reference" for row in rows(client))


def test_bulk_reject_overrides_and_learns(client):
    ids = seed(client)
    response = bulk(client, ids, action="reject")
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == 3
    assert all(row.verified_outcome is False and row.actual_action != row.recommended_action
               for row in rows(client))


def test_already_verified_row_is_skipped(client):
    ids = seed(client)
    assert client.post("/v1/labels/verify", json={"domain_id": "medical", "label_id": ids[0],
                "actual_action": "approve", "verified_outcome": True}).status_code == 200
    response = bulk(client, ids)
    assert response.status_code == 200, response.text
    assert response.json() == {"processed": 2, "skipped": 1,
                               "errors": [{"label_id": ids[0], "error": "already_verified"}]}
    assert sum(row.verified_at is not None for row in rows(client)) == 3


def test_wrong_tenant_batch_is_rejected_before_changes(client):
    seed(client, 1)
    async def add_other():
        async with client.app.state.session_factory() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(b"other-bulk").hexdigest(),
                               tenant_id="other-bulk", tenant_name="Other"))
            await session.commit()
    asyncio.run(add_other())
    other = {"X-Api-Key": "other-bulk"}
    assert seed(client, 2, headers=other) == ["L0", "L1"]
    response = bulk(client, ["L0", "L1"])
    assert response.status_code == 404
    assert rows(client)[0].verified_at is None
    assert bulk(client, ["L0"], headers=other).status_code == 200
    assert rows(client)[0].verified_at is None


def test_max_batch_size_is_200(client):
    assert bulk(client, [f"L{index}" for index in range(201)]).status_code == 422


def test_daily_trial_cap_processes_only_remaining_five(client):
    ids = seed(client, 10)
    async def near_cap():
        async with client.app.state.session_factory() as session:
            key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "tasks-tenant"))
            assert key is not None
            key.labels_day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            key.labels_today = 45
            await session.commit()
    asyncio.run(near_cap())
    response = bulk(client, ids)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["processed"] == 5 and body["skipped"] == 5
    assert body["errors"] == [{"label_id": label_id, "error": "daily_cap_exceeded"}
                              for label_id in ids[5:]]
    assert sum(row.verified_at is not None for row in rows(client)) == 5


def test_empty_label_ids_rejected(client):
    assert bulk(client, []).status_code == 422


def test_invalid_action_rejected(client):
    assert bulk(client, ["L0"], action="accept").status_code == 422
