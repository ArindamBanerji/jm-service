"""API tests for the persisted labeling loop."""
import asyncio
import hashlib
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db.connection import get_db
from db.models import ApiKey, Base, Engine, LabelLog
from label_health.api import router as health_router
from labeling_router import autonomy_router, router as labeling_router


@contextmanager
def open_client(tmp_path, keep_schema=False):
    url = os.getenv("DATABASE_URL")
    postgres = bool(url and url.startswith("postgresql"))
    schema = f"labels_{hashlib.sha256(str(tmp_path).encode()).hexdigest()[:24]}"
    if postgres:
        assert url is not None
        admin = create_async_engine(url, poolclass=NullPool)
        async def make_schema():
            async with admin.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        asyncio.run(make_schema())
        db_engine = create_async_engine(url, poolclass=NullPool,
                                        connect_args={"server_settings": {"search_path": schema}})
    else:
        admin = None
        db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'labels.db').as_posix()}")
    async def create_schema():
        async with db_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(db_engine)() as session:
            digest = hashlib.sha256(b"test-key").hexdigest()
            if await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest)) is None:
                session.add(ApiKey(key_hash=digest, tenant_id="", tenant_name="Local test tenant"))
                await session.commit()
    asyncio.run(create_schema())
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

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
    app.include_router(labeling_router)
    app.include_router(autonomy_router)
    app.include_router(health_router)
    app.dependency_overrides[get_db] = test_db
    with TestClient(app, headers={"X-Api-Key": "test-key"}) as test_client:
        yield test_client
    asyncio.run(db_engine.dispose())
    if admin is not None and not keep_schema:
        async def drop_schema():
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()
        asyncio.run(drop_schema())
    elif admin is not None:
        asyncio.run(admin.dispose())


@pytest.fixture
def client(tmp_path):
    with open_client(tmp_path) as test_client:
        yield test_client


def tenant_key(client, tenant: str) -> dict[str, str]:
    key = f"key-{tenant}"
    async def create() -> None:
        async with client.app.state.session_factory() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(key.encode()).hexdigest(),
                               tenant_id=tenant, tenant_name=tenant))
            await session.commit()
    asyncio.run(create())
    return {"X-Api-Key": key}


def test_unauthenticated_ingest_401(client):
    assert client.post("/v1/labels/ingest", json=item(), headers={"X-Api-Key": ""}).status_code == 401


def test_valid_key_ingest_200(client):
    assert client.post("/v1/labels/ingest", json=item(), headers=tenant_key(client, "valid")).status_code == 200


def set_key_usage(client, *, tier="trial", daily=0, monthly=0, days_old=0):
    async def update_usage():
        async with client.app.state.session_factory() as session:
            key = await session.scalar(select(ApiKey).where(
                ApiKey.key_hash == hashlib.sha256(b"test-key").hexdigest()))
            assert key is not None
            now = datetime.now(timezone.utc)
            key.tier = tier
            key.created_at = now - timedelta(days=days_old)
            key.labels_today = daily
            key.labels_day_key = now.strftime("%Y-%m-%d")
            key.labels_this_month = monthly
            key.labels_month_key = now.strftime("%Y-%m")
            await session.commit()
    asyncio.run(update_usage())


def test_trial_daily_cap_enforced_on_ingest(client):
    set_key_usage(client, daily=50)
    response = client.post("/v1/labels/ingest", json=item())
    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "volume_exceeded"


def test_batch_rolls_back_when_trial_cap_is_reached(client):
    set_key_usage(client, daily=49)
    payload = {"domain_id": "demo", "items": [item(label_id="L1"), item(label_id="L2")]}
    response = client.post("/v1/labels/ingest/batch", json=payload)
    assert response.status_code == 429
    assert client.get("/v1/labels/demo/pending").status_code == 404


def test_expired_trial_rejected_on_ingest(client):
    set_key_usage(client, days_old=15)
    response = client.post("/v1/labels/ingest", json=item())
    assert response.status_code == 402
    assert response.json()["detail"]["error"] == "trial_expired"


def test_paid_volume_warning_and_cap(client):
    set_key_usage(client, tier="starter", monthly=8_999)
    response = client.post("/v1/labels/ingest", json=item())
    assert response.status_code == 200
    assert response.headers["X-Volume-Warning"] == "9000/10000 labels used this month"
    set_key_usage(client, tier="starter", monthly=10_000)
    response = client.post("/v1/labels/ingest", json=item(label_id="L2"))
    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "volume_exceeded"


def test_wrong_key_401(client):
    assert client.post("/v1/labels/ingest", json=item(), headers={"X-Api-Key": "wrong"}).status_code == 401


def test_tenant_isolation(client):
    a, b = tenant_key(client, "a"), tenant_key(client, "b")
    assert client.post("/v1/labels/ingest", json=item(label_id="only-a"), headers=a).status_code == 200
    assert client.get("/v1/labels/demo/pending", headers=b).status_code == 404
    assert client.get("/v1/domains/demo/autonomy", headers=b).status_code == 404
    assert client.post("/v1/labels/ingest", json=item(label_id="only-b"), headers=b).status_code == 200
    assert [row["label_id"] for row in client.get("/v1/labels/demo/pending", headers=a).json()] == ["only-a"]
    assert [row["label_id"] for row in client.get("/v1/labels/demo/pending", headers=b).json()] == ["only-b"]


def test_verify_wrong_tenant_404(client):
    a, b = tenant_key(client, "owner"), tenant_key(client, "stranger")
    assert client.post("/v1/labels/ingest", json=item(), headers=a).status_code == 200
    payload = {"domain_id": "demo", "label_id": "L1", "actual_action": "approve", "verified_outcome": True}
    assert client.post("/v1/labels/verify", json=payload, headers=b).status_code == 404


def test_verify_correct_tenant_200(client):
    headers = tenant_key(client, "reviewer")
    assert client.post("/v1/labels/ingest", json=item(), headers=headers).status_code == 200
    payload = {"domain_id": "demo", "label_id": "L1", "actual_action": "approve", "verified_outcome": True}
    assert client.post("/v1/labels/verify", json=payload, headers=headers).status_code == 200


def test_health_report_no_auth(client):
    frame = pd.DataFrame([{"label_id": str(i), "category": "NER", "verified_outcome": True,
                           "factor_a": .4, "factor_b": .6} for i in range(200)])
    response = client.post("/v1/label-health/analyze", files={"file": ("labels.csv", frame.to_csv(index=False))},
                           headers={"X-Api-Key": ""})
    assert response.status_code == 200, response.text


def seed(client, correct: list[bool]) -> None:
    """Add already adjudicated history in deterministic verification order."""
    async def write() -> None:
        async with client.app.state.session_factory() as session:
            base = datetime(2026, 1, 1, tzinfo=timezone.utc)
            session.add_all([
                LabelLog(
                    domain_id="demo", label_id=f"seed-{index}", category="NER",
                    factors_json={"confidence": .9, "difficulty": .1},
                    recommended_action="approve", actual_action="approve" if outcome else "reject",
                    verified_outcome=outcome, confidence=.5,
                    verified_at=base + timedelta(seconds=index),
                )
                for index, outcome in enumerate(correct)
            ])
            await session.commit()
    asyncio.run(write())


def item(label_id="L1", category="NER", factors=None, annotator_id=None):
    return {"domain_id": "demo", "label_id": label_id, "category": category,
            "annotator_id": annotator_id,
            "factors": factors or {"confidence": .9, "difficulty": .1}}


def ingest(client, **kwargs):
    return client.post("/v1/labels/ingest", json=item(**kwargs))


def verify(client, label_id="L1", outcome=True, action="approve"):
    return client.post("/v1/labels/verify",
                       json={"domain_id": "demo", "label_id": label_id,
                             "actual_action": action, "verified_outcome": outcome})


def test_postgres_compatible_accuracy(client):
    for index in range(5):
        assert ingest(client, label_id=str(index)).status_code == 200
    for index, correct in enumerate([True, True, False]):
        response = verify(client, label_id=str(index), outcome=correct)
        assert response.status_code == 200, response.text
    assert response.json()["new_accuracy"] == pytest.approx(2 / 3)
    category = client.get("/v1/domains/demo/autonomy").json()["categories"][0]
    assert category["verified_count"] == 3
    assert category["accuracy"] == pytest.approx(2 / 3)


def test_category_survives_restart(tmp_path):
    def categories(client):
        response = client.get("/v1/domains/demo/autonomy")
        assert response.status_code == 200, response.text
        return {row["category"] for row in response.json()["categories"]}

    with open_client(tmp_path, keep_schema=True) as first:
        assert ingest(first, category="A", annotator_id="alex").status_code == 200
        assert ingest(first, label_id="L2", category="B", annotator_id="sam").status_code == 200
        assert categories(first) == {"A", "B"}
    with open_client(tmp_path) as restarted:
        assert categories(restarted) == {"A", "B"}


def test_cold_annotator_not_auto_accepted(client):
    assert ingest(client).status_code == 200
    seed(client, [index % 100 >= 13 for index in range(200)])  # 174/200 correct
    for i in range(32):
        response = ingest(client, label_id=f"new-{i}", annotator_id="new")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["tier"] == "autonomous"
        # At 29 verifications accuracy is 24/29. At 30 it is 24/30, then 24/31.
        assert result["auto_accepted"] is (i == 30)
        if i < 31:
            assert verify(client, label_id=f"new-{i}", outcome=i < 24).status_code == 200


def test_zero_verified_null_accuracy(client):
    for index in range(5):
        response = ingest(client, label_id=str(index))
        assert response.status_code == 200, response.text
        assert response.json()["tier_status"]["accuracy"] is None
    category = client.get("/v1/domains/demo/autonomy").json()["categories"][0]
    assert category["accuracy"] is None
    assert category["verified_count"] == 0
    assert category["tier"] == "red"


def test_ingest_basic(client):
    response = ingest(client)
    assert response.status_code == 200, response.text
    assert response.json()["recommended_action"] in ("approve", "reject")
    assert 0 <= response.json()["confidence"] <= 1


def test_ingest_auto_creates_domain(client):
    assert ingest(client).status_code == 200
    assert client.get("/v1/labels/demo/pending").status_code == 200


def test_ingest_new_category(client):
    ingest(client, annotator_id="alex")
    response = ingest(client, label_id="L2", category="other", annotator_id="sam")
    assert response.status_code == 200, response.text
    assert response.json()["category"] == "other"
    assert ingest(client, label_id="L3", category="other", annotator_id="alex").status_code == 200


def test_ingest_factor_mismatch(client):
    ingest(client)
    response = ingest(client, label_id="L2", factors={"new_factor": .7, "difficulty": .1})
    assert response.status_code == 422


def test_ingest_invalid_factors(client):
    assert ingest(client, factors={"confidence": 1.2, "difficulty": .1}).status_code == 422


def test_ingest_missing_fields(client):
    payload = item()
    del payload["category"]
    assert client.post("/v1/labels/ingest", json=payload).status_code == 422


def test_verify_basic(client):
    ingest(client)
    response = verify(client)
    assert response.status_code == 200, response.text
    assert response.json()["engine_updated"] is True


def test_verify_not_found(client):
    assert verify(client).status_code == 404


def test_verify_already_verified(client):
    ingest(client)
    assert verify(client).status_code == 200
    assert verify(client).status_code == 409


def test_verify_binds_provided_annotator(client):
    ingest(client)
    response = client.post("/v1/labels/verify", json={
        "domain_id": "demo", "label_id": "L1", "actual_action": "approve",
        "verified_outcome": True, "annotator_id": "reviewer-7",
    })
    assert response.status_code == 200, response.text
    assert client.get("/v1/labels/demo/pending").json() == []
    async def read_identity() -> tuple[str | None, bool]:
        async with client.app.state.session_factory() as session:
            row = await session.scalar(select(LabelLog).where(LabelLog.label_id == "L1"))
            reviewer_engine = await session.scalar(select(Engine).where(
                Engine.domain_id == "demo", Engine.annotator_id == "reviewer-7"))
            assert row is not None
            return row.annotator_id, reviewer_engine is not None

    assert asyncio.run(read_identity()) == ("reviewer-7", True)


def test_verify_updates_accuracy(client):
    for index in range(10):
        ingest(client, label_id=f"L{index}")
        response = verify(client, label_id=f"L{index}", outcome=index < 8)
        assert response.status_code == 200, response.text
    assert response.json()["new_accuracy"] == .8


def test_verify_learns(client):
    first = ingest(client).json()["confidence"]
    verify(client)
    second = ingest(client, label_id="L2").json()["confidence"]
    assert second != first


def test_batch_ingest(client):
    payload = {"domain_id": "demo", "items": [item(label_id=f"L{i}") for i in range(5)]}
    response = client.post("/v1/labels/ingest/batch", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["batch_size"] == len(response.json()["results"]) == 5


def test_batch_exceeds_limit(client):
    payload = {"domain_id": "demo", "items": [item(label_id=f"L{i}") for i in range(101)]}
    assert client.post("/v1/labels/ingest/batch", json=payload).status_code == 422


def test_batch_partial_invalid(client):
    items = [item(label_id=f"L{i}") for i in range(5)]
    items[2]["factors"] = {"confidence": .3, "different": .4}
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "demo", "items": items})
    assert response.status_code == 422 and response.json()["detail"]["item_index"] == 2
    assert client.get("/v1/labels/demo/pending").status_code == 404


def test_pending_returns_unverified(client):
    for index in range(5):
        ingest(client, label_id=f"L{index}")
    for index in range(2):
        verify(client, label_id=f"L{index}")
    assert len(client.get("/v1/labels/demo/pending").json()) == 3


def test_pending_sorted_by_confidence(client):
    ingest(client)
    verify(client)
    ingest(client, label_id="L2")
    ingest(client, label_id="L3", factors={"confidence": .2, "difficulty": .8})
    values = [row["confidence"] for row in client.get("/v1/labels/demo/pending").json()]
    assert values == sorted(values)


def test_ingest_then_health_report(client):
    set_key_usage(client, tier="business")
    items = [item(label_id=f"L{i}") for i in range(200)]
    for chunk in (items[:100], items[100:]):
        response = client.post("/v1/labels/ingest/batch", json={"domain_id": "demo", "items": chunk})
        assert response.status_code == 200, response.text
    frame = pd.DataFrame([{"label_id": entry["label_id"], "category": "NER",
                           "verified_outcome": index % 5 != 0,
                           "confidence": .9, "difficulty": .1}
                          for index, entry in enumerate(items)])
    response = client.post("/v1/label-health/analyze",
                           files={"file": ("labels.csv", frame.to_csv(index=False).encode(), "text/csv")})
    assert response.status_code == 200, response.text
    assert response.json()["overall_accuracy"] == .8


def test_full_loop(client):
    first = ingest(client)
    assert first.status_code == 200
    verified = verify(client)
    assert verified.status_code == 200 and verified.json()["new_accuracy"] == 1
    second = ingest(client, label_id="L2")
    assert second.status_code == 200 and second.json()["confidence"] > first.json()["confidence"]
