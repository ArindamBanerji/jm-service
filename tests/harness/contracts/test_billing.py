import json
import hashlib
import hmac
from types import SimpleNamespace

import httpx
import pytest

import billing
from ..fixtures.factory import Wire, shape
from db.models import ApiKey
from sqlalchemy import select

pytestmark = pytest.mark.anyio


async def test_checkout(wire: Wire, monkeypatch):
    monkeypatch.setenv("PADDLE_API_KEY", "fake-test-key")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "starter=pri_contract")
    ledger = wire.directory / "provider.json"

    def transact(request: httpx.Request):
        ledger.write_bytes(request.content)
        return httpx.Response(201, json={"data": {"id": "txn_test123", "checkout": {"url": "https://example.test/checkout?_ptxn=txn_test123"}}})

    # Replace only billing's provider transport. The API client still calls the real application.
    monkeypatch.setattr(billing, "httpx", SimpleNamespace(
        AsyncClient=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(transact), **kw),
        HTTPError=httpx.HTTPError))

    async def provider_committed():
        async with wire.factory.sessions() as session:
            purchaser = await session.scalar(select(ApiKey).where(
                ApiKey.key_hash == hashlib.sha256(wire.client.headers["x-api-key"].encode()).hexdigest()))
        assert purchaser is not None
        custom = json.loads(ledger.read_bytes())["custom_data"]
        assert custom["tenant_id"] == wire.factory.tenant
        assert custom["key_id"] == str(purchaser.id)
        assert custom["checkout_intent_id"]

    response = await wire.request("GET", "/v1/billing/checkout-url", before_send=provider_committed)
    shape(response.json(), {"checkout_url": str, "tier": str})
    assert response.json()["checkout_url"] == "https://example.test/checkout?_ptxn=txn_test123"


async def test_webhook_entitlement(wire: Wire):
    custom = await wire.paddle_intent("professional", "txn_contract")
    payload = {"event_type": "subscription.created", "event_id": "contract-event",
               "occurred_at": "2026-01-01T12:00:00Z", "data": {"id": "sub-test", "customer_id": "cust-test",
               "transaction_id": "txn_contract", "custom_data": custom,
               "items": [{"product": {"name": "DLJ Professional"}}]}}
    response = await wire.request("POST", "/v1/billing/webhook", json=payload,
                                  omit_api_key=True,
                                  before_send=wire.committed("SELECT tier FROM api_keys WHERE paddle_event_id='contract-event'", "professional"))
    shape(response.json(), {"status": str})


async def test_signed_webhook_without_tenant_key(wire: Wire, monkeypatch):
    monkeypatch.setenv("PADDLE_SANDBOX", "false")
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "harness-secret")
    custom = await wire.paddle_intent("professional", "txn_signedcontract")
    payload = {"event_type": "subscription.created", "event_id": "signed-contract",
               "occurred_at": "2026-01-01T12:00:00Z", "data": {"id": "sub-signed", "customer_id": "cust-signed",
               "transaction_id": "txn_signedcontract", "custom_data": custom,
               "items": [{"product": {"name": "DLJ Professional"}}]}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = "1790000000"
    signature = hmac.new(b"harness-secret", timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    response = await wire.request("POST", "/v1/billing/webhook", content=body,
                                  headers={"Paddle-Signature": f"ts={timestamp};h1={signature}",
                                           "Content-Type": "application/json"},
                                  omit_api_key=True,
                                  before_send=wire.committed("SELECT tier FROM api_keys WHERE paddle_event_id='signed-contract'", "professional"))
    shape(response.json(), {"status": str})
