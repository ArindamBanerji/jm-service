"""Settings account, domain recovery, and checkout integration."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import billing
import db.migrate as migrations
from account import router as account_router
from auth import scoped_domain_id
from db.connection import get_db
from db.models import ApiKey, Base, Domain
from labeling_router import router as labeling_router


@contextmanager
def account_client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'account.db').as_posix()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add_all([ApiKey(key_hash=hashlib.sha256(key.encode()).hexdigest(),
                                    tenant_id=tenant, tenant_name=f"Team {tenant}")
                             for key, tenant in (("key-a", "tenant-a"), ("key-b", "tenant-b"))])
            await session.commit()
    asyncio.run(setup())

    async def override():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(account_router)
    app.include_router(labeling_router)
    app.include_router(billing.router)
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(billing, "AsyncSessionLocal", factory)
    with TestClient(app) as http:
        yield http, factory
    asyncio.run(engine.dispose())


def auth(key="key-a"):
    return {"X-Api-Key": key}


def label(domain="demo"):
    return {"domain_id": domain, "label_id": "one", "category": "NER",
            "factors": {"confidence": .8, "difficulty": .2}}


def test_account_and_domains_require_key(tmp_path, monkeypatch):
    with account_client(tmp_path, monkeypatch) as (http, _):
        assert http.get("/v1/account").status_code == 401
        assert http.get("/v1/account/domains").status_code == 401
        assert http.post("/v1/account/domains/resolve", json={"domain_id": "demo"}).status_code == 401


def test_minimal_key_summary_and_utc_counters(tmp_path, monkeypatch):
    with account_client(tmp_path, monkeypatch) as (http, factory):
        now = datetime.now(timezone.utc)
        async def update(day, month, tier, cancelled=None):
            async with factory() as session:
                key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "tenant-a"))
                assert key is not None
                key.created_at = now - timedelta(days=2)
                key.labels_today = 17; key.labels_this_month = 123
                key.labels_day_key = day; key.labels_month_key = month
                key.tier = tier; key.cancelled_at = cancelled
                await session.commit()
        asyncio.run(update("old", "old", "trial"))
        body = http.get("/v1/account", headers=auth()).json()
        assert set(body) == {"tenant_id", "tenant_name", "tier", "created_at", "is_active",
                             "cancelled_at", "trial_expires_at", "trial_expired", "usage"}
        assert body["tenant_id"] == "tenant-a" and body["tenant_name"] == "Team tenant-a"
        assert body["usage"]["labels_today"] == body["usage"]["labels_this_month"] == 0
        assert body["usage"]["daily_cap"] == 50 and body["usage"]["monthly_cap"] is None
        assert body["trial_expires_at"] and not body["trial_expired"]
        asyncio.run(update(now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"), "professional"))
        paid = http.get("/v1/account", headers=auth()).json()
        assert paid["usage"]["labels_today"] == 17 and paid["usage"]["labels_this_month"] == 123
        assert paid["usage"]["monthly_cap"] == 100_000 and paid["trial_expires_at"] is None
        asyncio.run(update(now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"), "scale", now))
        unlimited = http.get("/v1/account", headers=auth()).json()
        assert unlimited["usage"]["monthly_cap"] is None and unlimited["cancelled_at"]
        assert "key_hash" not in str(unlimited) and "key-a" not in str(unlimited)


def test_public_domains_legacy_resolution_migration_and_isolation(tmp_path, monkeypatch):
    legacy_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    async def legacy():
        async with legacy_engine.begin() as connection:
            await connection.execute(text("CREATE TABLE domains (id CHAR(32) PRIMARY KEY, domain_id VARCHAR(200), "
                                          "domain_name VARCHAR(200), config_json JSON, created_at TIMESTAMP, "
                                          "updated_at TIMESTAMP)"))
    asyncio.run(legacy())
    monkeypatch.setattr(migrations, "engine", legacy_engine)
    asyncio.run(migrations.migrate())
    asyncio.run(migrations.migrate())
    async def columns():
        async with legacy_engine.connect() as connection:
            result = await connection.execute(text("PRAGMA table_info(domains)"))
            return {row[1] for row in result}
    assert "public_domain_id" in asyncio.run(columns())

    with account_client(tmp_path, monkeypatch) as (http, factory):
        assert http.post("/v1/labels/ingest", json=label(), headers=auth()).status_code == 200
        async def make_legacy():
            async with factory() as session:
                row = await session.scalar(select(Domain).where(Domain.tenant_id == "tenant-a"))
                assert row is not None
                row.public_domain_id = None
                row.domain_name = row.domain_id
                await session.commit()
        asyncio.run(make_legacy())
        unresolved = http.get("/v1/account/domains", headers=auth()).json()
        assert unresolved[0]["needs_name"] and unresolved[0]["public_domain_id"] is None
        assert scoped_domain_id("tenant-a", "demo") not in str(unresolved)
        assert http.post("/v1/account/domains/resolve", json={"domain_id": "demo"}, headers=auth("key-b")).status_code == 404
        for _ in range(2):
            assert http.post("/v1/account/domains/resolve", json={"domain_id": "demo"}, headers=auth()).status_code == 200
        assert http.get("/v1/account/domains", headers=auth()).json()[0]["public_domain_id"] == "demo"
        assert http.get("/v1/account/domains", headers=auth("key-b")).json() == []
        assert http.post("/v1/labels/ingest", json=label(), headers=auth("key-b")).status_code == 200
        assert http.get("/v1/account/domains", headers=auth("key-b")).json()[0]["public_domain_id"] == "demo"


def test_checkout_webhook_refreshes_tier(tmp_path, monkeypatch):
    with account_client(tmp_path, monkeypatch) as (http, _):
        calls = []
        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return None
            async def post(self, url, **kwargs):
                calls.append((url, kwargs))
                class Reply:
                    def raise_for_status(self): pass
                    def json(self): return {"data": {"checkout": {"url": "https://checkout.paddle.com/test"}}}
                return Reply()
        monkeypatch.setattr(billing.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        monkeypatch.setenv("PADDLE_API_KEY", "test")
        monkeypatch.setenv("PADDLE_PRICE_MAP", "starter=pri_starter")
        monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "secret")
        assert http.get("/v1/account", headers=auth()).json()["tier"] == "trial"
        checkout = http.get("/v1/billing/checkout-url?tier=starter", headers=auth())
        assert checkout.status_code == 200 and checkout.json()["checkout_url"].startswith("https://")
        custom = calls[0][1]["json"]["custom_data"]
        assert custom["tenant_id"] == "tenant-a" and custom["key_id"]
        payload = {"event_type": "subscription.created", "event_id": "evt-account",
                   "occurred_at": "2026-01-01T00:00:00Z", "data": {
            "id": "sub-1", "customer_id": "customer-1", "custom_data": custom,
            "items": [{"product": {"name": "DLJ Starter"}}]}}
        body = json.dumps(payload).encode()
        ts = "1234567890"
        signature = hmac.new(b"secret", ts.encode() + b":" + body, hashlib.sha256).hexdigest()
        response = http.post("/v1/billing/webhook", content=body, headers={
            "Paddle-Signature": f"ts={ts};h1={signature}", "Content-Type": "application/json"})
        assert response.status_code == 200, response.text
        refreshed = http.get("/v1/account", headers=auth()).json()
        assert refreshed["tier"] == "starter" and refreshed["usage"]["monthly_cap"] == 10_000
