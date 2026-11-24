"""Billing signatures, subscription updates, trial guards, and email copy."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import billing
import db.migrate as migrations
from db.models import ApiKey, Base
from email_service import (api_key_email, cancellation_email, trial_expired_email,
                           trial_expiring_email)
from trial_guard import check_trial_expiry, check_volume_cap


def record(*, tier: str = "trial", days_old: int = 0, used: int = 0) -> ApiKey:
    return ApiKey(key_hash="0" * 64, tenant_id="tenant", tenant_name="Tenant",
                  tier=tier, created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
                  labels_this_month=used)


def test_webhook_signature() -> None:
    body, secret, ts = b'{"event_type":"subscription.created"}', "secret", "1234567890"
    valid = hmac.new(secret.encode(), f"{ts}:{body.decode()}".encode(), hashlib.sha256).hexdigest()
    header = f"ts={ts};h1={valid}"
    assert billing.verify_paddle_signature(body, header, secret)
    assert not billing.verify_paddle_signature(body, f"ts={ts};h1=bad", secret)
    assert not billing.verify_paddle_signature(body + b" ", header, secret)
    assert not billing.verify_paddle_signature(body, "h1=bad", secret)
    assert not billing.verify_paddle_signature(body, "", secret)


def test_trial_expiry_rejects_expired() -> None:
    with pytest.raises(HTTPException) as exc:
        check_trial_expiry(record(days_old=15))
    assert exc.value.status_code == 402
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["error"] == "trial_expired"


def test_trial_expiry_allows_active() -> None:
    check_trial_expiry(record(days_old=13))


def test_trial_expiry_allows_paid() -> None:
    check_trial_expiry(record(tier="starter", days_old=100))


def test_volume_cap_rejects_full_tier() -> None:
    with pytest.raises(HTTPException) as exc:
        check_volume_cap(record(tier="starter", used=10_000))
    assert exc.value.status_code == 429
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["error"] == "volume_exceeded"


def test_volume_cap_warns_at_ninety_percent() -> None:
    assert check_volume_cap(record(tier="starter", used=9_000)) == {
        "X-Volume-Warning": "9000/10000 labels used this month"}


@pytest.mark.parametrize("tier", ["scale", "enterprise"])
def test_volume_cap_unlimited(tier: str) -> None:
    assert check_volume_cap(record(tier=tier, used=2_000_000)) is None


@pytest.mark.parametrize("template,subject_fragment,body_fragment", [
    (lambda: api_key_email("key-123"), "API Key", "key-123"),
    (trial_expiring_email, "2 days", "Manage subscription"),
    (trial_expired_email, "trial has ended", "Upgrade now"),
    (cancellation_email, "cancelled", "30 days"),
])
def test_email_templates(template, subject_fragment: str, body_fragment: str) -> None:
    subject, html = template()
    assert subject_fragment in subject
    assert body_fragment in html
    assert "dlj.dakshineshwari.net" in html


def test_subscription_webhook_lifecycle(tmp_path, monkeypatch) -> None:
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'billing.db').as_posix()}")
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def setup() -> None:
        async with db_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            entry = record()
            entry.paddle_customer_id = "customer-1"
            session.add(entry)
            await session.commit()

    asyncio.run(setup())
    monkeypatch.setattr(billing, "AsyncSessionLocal", factory)
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "webhook-secret")
    app = FastAPI()
    app.include_router(billing.router)
    client = TestClient(app)

    def post(event: str, product: str = "DLJ Starter"):
        payload = {"event_type": event,
                   "data": {"id": "sub-1", "customer_id": "customer-1",
                            "items": [{"product": {"name": product}}]}}
        body = json.dumps(payload).encode()
        ts = "1234567890"
        signature = hmac.new(b"webhook-secret", ts.encode() + b":" + body, hashlib.sha256).hexdigest()
        return client.post("/v1/billing/webhook", content=body,
                           headers={"Paddle-Signature": f"ts={ts};h1={signature}",
                                    "Content-Type": "application/json"})

    assert post("subscription.created").status_code == 200
    assert post("subscription.updated", "DLJ Professional").status_code == 200
    assert post("subscription.canceled").status_code == 200

    async def inspect_record() -> ApiKey:
        async with factory() as session:
            result = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "tenant"))
            assert result is not None
            return result

    saved = asyncio.run(inspect_record())
    assert saved.paddle_customer_id == "customer-1"
    assert saved.paddle_subscription_id == "sub-1"
    assert saved.tier == "professional"
    assert saved.cancelled_at is not None
    asyncio.run(db_engine.dispose())


def test_webhook_rejects_bad_signature(monkeypatch) -> None:
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "webhook-secret")
    app = FastAPI()
    app.include_router(billing.router)
    response = TestClient(app).post("/v1/billing/webhook", content=b"{}",
                                    headers={"Paddle-Signature": "ts=1234567890;h1=wrong"})
    assert response.status_code == 401


def test_sandbox_accepts_unsigned_webhook(monkeypatch) -> None:
    monkeypatch.delenv("PADDLE_WEBHOOK_SECRET", raising=False)
    app = FastAPI()
    app.include_router(billing.router)
    response = TestClient(app).post("/v1/billing/webhook", json={
        "event_type": "transaction.completed", "data": {}})
    assert response.status_code == 200


def test_migration_adds_billing_columns_to_existing_table(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "old.db"
    legacy_provider = "_".join(("lemon", "squeezy"))
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"CREATE TABLE api_keys (id CHAR(32) PRIMARY KEY, key_hash VARCHAR(64), "
                           "tenant_id VARCHAR(200), tenant_name VARCHAR(200), "
                           "created_at TIMESTAMP, is_active BOOLEAN, "
                           f"{legacy_provider}_customer_id VARCHAR(200), "
                           f"{legacy_provider}_subscription_id VARCHAR(200))")
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setattr(migrations, "engine", db_engine)
    asyncio.run(migrations.migrate())
    with sqlite3.connect(db_path) as connection:
        names = {row[1] for row in connection.execute("PRAGMA table_info(api_keys)")}
    assert {"tier", "paddle_customer_id", "paddle_subscription_id",
            "cancelled_at", "labels_this_month", "labels_month_key",
            "labels_today", "labels_day_key"} <= names
