"""Exercise Paddle delivery, ordering, and entitlements against the selected database."""
import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

import billing
from auth import generate_api_key
from db.models import ApiKey
from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PADDLE_SANDBOX", "true")
    monkeypatch.delenv("PADDLE_WEBHOOK_SECRET", raising=False)
    with open_tasks_client(tmp_path) as http:
        http.app.include_router(billing.router)
        monkeypatch.setattr(billing, "AsyncSessionLocal", http.app.state.session_factory)
        yield http


def event(kind="created", sequence=1, product="DLJ Professional", **fields):
    return {"event_type": f"subscription.{kind}", "event_id": f"evt-{sequence}",
            "occurred_at": f"2026-01-{sequence:02d}T12:00:00Z",
            "data": {"id": "sub-1", "customer_id": "ctm-1", "custom_data": {"tenant_id": "tasks-tenant"},
                     "items": [{"product": {"name": product}}], **fields}}


def deliver(client, payload):
    return client.post("/v1/billing/webhook", json=payload)


def key(client, plain="tasks-key"):
    async def read():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(ApiKey).where(
                ApiKey.key_hash == hashlib.sha256(plain.encode()).hexdigest()))).one()
    return asyncio.run(read())


def add_key(client, tenant, email=None):
    plain, row = generate_api_key(tenant, "Another key")
    row.contact_email = email

    async def save():
        async with client.app.state.session_factory.begin() as session:
            session.add(row)
    asyncio.run(save())
    return plain


def test_unsigned_live_rejected(client, monkeypatch):
    for setting in (None, "false"):
        if setting is None:
            monkeypatch.delenv("PADDLE_SANDBOX")
        else:
            monkeypatch.setenv("PADDLE_SANDBOX", setting)
        response = deliver(client, event())
        assert response.status_code == 503
        assert response.json()["detail"] == "Webhook secret not configured"
    assert key(client).tier == "trial"


def test_unsigned_sandbox_accepted(client):
    assert deliver(client, event()).status_code == 200
    assert key(client).tier == "professional"


def test_valid_signature_live(client, monkeypatch):
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "test-signing-secret")
    monkeypatch.setenv("PADDLE_SANDBOX", "false")
    payload = event()
    assert deliver(client, payload).status_code == 401
    body = json.dumps(payload).encode()
    ts = "1767268800"
    digest = hmac.new(b"test-signing-secret", ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    response = client.post("/v1/billing/webhook", content=body, headers={
        "Paddle-Signature": f"ts={ts};h1={digest}", "Content-Type": "application/json"})
    assert response.status_code == 200
    assert key(client).tier == "professional"


def test_checkout_upgrades_specific_key(client, monkeypatch):
    purchaser = "tasks-key"
    monkeypatch.setenv("PADDLE_API_KEY", "test-provider-key")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "professional=pri_1")
    reply = httpx.Response(201, request=httpx.Request("POST", "https://example.test"),
                           json={"data": {"id": "txn_test123", "checkout": {"url": "https://example.test/checkout?_ptxn=txn_test123"}}})
    post = AsyncMock(return_value=reply)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    checkout = client.get("/v1/billing/checkout-url?tier=professional", headers={"X-Api-Key": purchaser})
    assert checkout.status_code == 200
    assert checkout.json()["checkout_url"] == "https://example.test/checkout?_ptxn=txn_test123"
    assert post.await_args is not None
    custom = post.await_args.kwargs["json"]["custom_data"]
    assert custom["tenant_id"] == "tasks-tenant"
    assert custom["key_id"] == str(key(client, purchaser).id)
    assert custom["checkout_intent_id"]
    other_key = add_key(client, "tasks-tenant")
    assert deliver(client, event(custom_data=custom)).status_code == 200
    assert key(client, purchaser).tier == "professional"
    assert key(client, other_key).tier == "trial"
    # Once linked, the customer's original key wins over a later same-tenant hint.
    other = {"tenant_id": "tasks-tenant", "key_id": str(key(client, other_key).id)}
    assert deliver(client, event(sequence=2, product="DLJ Business", custom_data=other)).status_code == 200
    assert key(client, purchaser).tier == "business"
    assert key(client, other_key).paddle_customer_id is None


def test_duplicate_event_rejected_after_intervening_update(client):
    assert deliver(client, event()).status_code == 200
    assert deliver(client, event("updated", 2, "DLJ Scale")).status_code == 200
    assert deliver(client, event()).status_code == 200
    assert key(client).tier == "scale" and key(client).paddle_event_id == "evt-2"


def test_older_activation_preserves_cancellation(client):
    assert deliver(client, event()).status_code == 200
    assert deliver(client, event("canceled", 3)).status_code == 200
    assert deliver(client, event(sequence=2, product="DLJ Business")).status_code == 200
    saved = key(client)
    assert saved.tier == "professional" and saved.paddle_event_id == "evt-3"
    assert saved.cancelled_at == saved.paddle_event_occurred_at
    assert saved.cancelled_at.replace(tzinfo=timezone.utc) == datetime(2026, 1, 3, 12, tzinfo=timezone.utc)
    assert deliver(client, event(sequence=2)).status_code == 200
    assert deliver(client, event("updated", 4, status="active")).status_code == 200
    assert key(client).cancelled_at is None


def test_email_conflict_preserves_entitlement(client, caplog):
    owner = add_key(client, "other-tenant", "owner@example.test")
    payload = event(customer={"email": "OWNER@example.test"})
    assert deliver(client, payload).status_code == 200
    assert key(client).tier == "professional" and key(client).contact_email is None
    assert key(client, owner).contact_email == "owner@example.test"
    assert "contact email conflicts" in caplog.text
    assert deliver(client, payload).status_code == 200


def test_non_string_product_rejected(client):
    response = deliver(client, event(product={"value": "DLJ Starter"}))
    assert response.status_code == 400 and response.json()["detail"] == "Unknown product"
    assert key(client).tier == "trial"


def test_unknown_product_rejected(client, caplog):
    response = deliver(client, event(product="Unmapped"))
    assert response.status_code == 400 and response.json()["detail"] == "Unknown product"
    assert "Unmapped" in caplog.text and key(client).paddle_customer_id is None


def test_known_product_upgrades(client):
    assert deliver(client, event(product="DLJ Business")).status_code == 200
    saved = key(client)
    assert (saved.tier, saved.paddle_customer_id, saved.paddle_subscription_id) == ("business", "ctm-1", "sub-1")
