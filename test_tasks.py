"""Text task and audited category revision contracts on SQLite and PostgreSQL."""
import asyncio
import hashlib
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from db.connection import get_db
from db.models import ApiKey, Base, Engine, LabelLog
from labeling_router import autonomy_router, router


@contextmanager
def open_tasks_client(tmp_path):
    url = os.getenv("DATABASE_URL")
    postgres = bool(url and url.startswith("postgresql"))
    schema = f"tasks_{uuid4().hex}"
    if postgres:
        assert url is not None
        admin = create_async_engine(url, poolclass=NullPool)
        async def make_schema():
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        asyncio.run(make_schema())
        engine = create_async_engine(url, poolclass=NullPool,
                                     connect_args={"server_settings": {"search_path": schema}})
    else:
        admin = None
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'tasks.db').as_posix()}")

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine)() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(b"tasks-key").hexdigest(),
                               tenant_id="tasks-tenant", tenant_name="Tasks tenant"))
            await session.commit()
    asyncio.run(setup())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def test_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(router)
    app.include_router(autonomy_router)
    app.dependency_overrides[get_db] = test_db
    try:
        with TestClient(app, headers={"X-Api-Key": "tasks-key"}) as client:
            yield client
    finally:
        asyncio.run(engine.dispose())
        if admin is not None:
            async def drop_schema():
                async with admin.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                await admin.dispose()
            asyncio.run(drop_schema())


@pytest.fixture
def client(tmp_path):
    with open_tasks_client(tmp_path) as result:
        yield result


def task(client, label_id="item-1", category=None, source="Aspirin appears in the list."):
    body = {"label_id": label_id, "text": source}
    if category is not None:
        body["category"] = category
    return client.post("/v1/labels/medical/tasks", json=body)


def detail(client, label_id="item-1"):
    return client.get(f"/v1/labels/medical/{label_id}")


def relabel(client, token, category="CONDITION", label_id="item-1", headers=None):
    return client.post(f"/v1/labels/medical/items/{label_id}/relabel",
                       json={"category": category, "idempotency_token": token}, headers=headers)


def test_text_task_waits_for_classification(client):
    response = task(client)
    assert response.status_code == 201, response.text
    assert response.json() == {"label_id": "item-1", "status": "pending_classification", "category": None}
    row = detail(client).json()
    assert row["text"] == "Aspirin appears in the list."
    assert row["confidence"] is None and row["factors"] == {}
    assert client.get("/v1/labels/medical/pending").json() == []
    token = row["revision_id"]
    first = relabel(client, token, "MEDICATION")
    assert first.status_code == 200, first.text
    assert detail(client).json()["status"] == "scored"


def test_text_task_with_category_scores_once(client):
    response = task(client, category="MEDICATION")
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "scored"
    assert detail(client).json()["confidence"] is not None
    assert len(client.get("/v1/labels/medical/pending").json()) == 1


def test_duplicate_label_id_is_conflict(client):
    assert task(client).status_code == 201
    assert task(client).status_code == 409


def test_oversized_utf8_text_is_rejected(client):
    assert task(client, source="😀" * 8193).status_code == 422
    assert client.get("/v1/labels/medical/pending").status_code == 404


def test_relabel_creates_audited_revision_without_rescore(client):
    assert task(client, category="MEDICATION").status_code == 201
    before = detail(client).json()
    async def state():
        async with client.app.state.session_factory() as session:
            key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "tasks-tenant"))
            engine = await session.scalar(select(Engine).where(Engine.tenant_id == "tasks-tenant"))
            assert key is not None and engine is not None
            return key.labels_today, engine.version
    usage_before = asyncio.run(state())
    response = relabel(client, before["revision_id"])
    assert response.status_code == 200, response.text
    assert response.json()["previous_category"] == "MEDICATION"
    after = detail(client).json()
    assert after["category"] == "CONDITION" and after["previous_category"] == "MEDICATION"
    assert after["confidence"] == before["confidence"]
    assert asyncio.run(state()) == usage_before
    async def inspect():
        async with client.app.state.session_factory() as session:
            return list((await session.scalars(select(LabelLog).order_by(LabelLog.label_id))).all())
    rows = asyncio.run(inspect())
    assert len(rows) == 2
    original = next(row for row in rows if row.label_id == "item-1")
    revision = next(row for row in rows if row.label_id != "item-1")
    assert original.category == "MEDICATION" and original.superseded_by == revision.label_id
    assert revision.prior_revision_id == str(original.id)
    assert revision.revision_actor == "tasks-tenant" and revision.revision_at is not None
    assert revision.idempotency_token == before["revision_id"]


def test_stale_relabel_token_conflicts(client):
    assert task(client, category="MEDICATION").status_code == 201
    token = detail(client).json()["revision_id"]
    assert relabel(client, token).status_code == 200
    assert relabel(client, token).status_code == 409


def test_relabel_missing_label_is_not_found(client):
    assert relabel(client, str(uuid4()), label_id="missing").status_code == 404


def test_task_and_relabel_are_tenant_scoped(client):
    assert task(client, category="MEDICATION").status_code == 201
    token = detail(client).json()["revision_id"]
    async def other_key():
        async with client.app.state.session_factory() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(b"other-key").hexdigest(),
                               tenant_id="other-tenant", tenant_name="Other tenant"))
            await session.commit()
    asyncio.run(other_key())
    headers = {"X-Api-Key": "other-key"}
    assert client.get("/v1/labels/medical/item-1", headers=headers).status_code == 404
    assert relabel(client, token, headers=headers).status_code == 404
    assert client.post("/v1/labels/medical/tasks", json={"label_id": "item-1", "text": "Other"},
                       headers=headers).status_code == 201
    assert detail(client).json()["text"] == "Aspirin appears in the list."
