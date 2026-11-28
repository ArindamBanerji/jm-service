"""Public recovery proves the signup mailbox and rotates the existing payer credential."""
import asyncio
import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

import auth
import email_service
from db.models import ApiKey
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio


@pytest.fixture
def mail(monkeypatch):
    received = Event()

    async def deliver(*args) -> bool:
        received.set()
        return True

    delivery = AsyncMock(side_effect=deliver)
    delivery.wait_received = received
    monkeypatch.setattr(email_service, "send_email", delivery)
    return delivery


async def signup(wire: Wire, email: str) -> dict:
    await wire.request("POST", "/v1/auth/register", status=202, omit_api_key=True, json={"email": email})
    sender = auth.send_signup_challenge_email
    assert isinstance(sender, AsyncMock) and sender.await_args
    response = await wire.request("POST", "/v1/auth/confirm", status=201, omit_api_key=True,
                                  json={"token": sender.await_args.args[1]})
    return response.json()


async def send_code(wire: Wire, email: str, mail: AsyncMock) -> str:
    response = await wire.request("POST", "/v1/auth/recover", omit_api_key=True, json={"email": email})
    assert response.json() == {"message": "Check your email for a recovery code."}
    assert mail.await_args
    address, subject, html = mail.await_args.args
    assert address == email.strip().lower() and "Recover" in subject
    match = re.search(r"<pre>([0-9a-f]{64})</pre>", html)
    assert match is not None
    return match[1]


async def test_verified_mailbox_recovers_same_paid_project(wire: Wire, mail: AsyncMock):
    email = "owner@example.test"
    owner = await signup(wire, email)
    old = {"X-Api-Key": owner["api_key"]}
    async with wire.factory.sessions.begin() as session:
        key = (await session.scalars(select(ApiKey).where(ApiKey.signup_email == email))).one()
        key.tier, key.subscription_state = "professional", "active"
        key_id = key.id
    project = await wire.request("POST", "/v1/projects", status=201, headers=old, json={
        "name": "First project", "public_domain_id": "first", "factors": ["quality", "difficulty"],
        "categories": ["default"]})
    token = await send_code(wire, "OWNER@example.test", mail)
    await wire.request("GET", "/v1/projects", headers=old)
    async with wire.factory.sessions() as fresh:
        stored = await fresh.get(ApiKey, key_id)
        assert stored and stored.recovery_token_hash == hashlib.sha256(token.encode()).hexdigest()
    result = await wire.request("POST", "/v1/auth/recover/confirm", omit_api_key=True, json={"token": token})
    assert "no-store" in result.headers["cache-control"]
    assert result.json()["tenant_id"] == owner["tenant_id"] and result.json()["api_key"] != owner["api_key"]
    new = {"X-Api-Key": result.json()["api_key"]}
    listing = await wire.request("GET", "/v1/projects", headers=new)
    assert project.json()["id"] in [p["id"] for p in listing.json()]
    await wire.request("GET", "/v1/projects", headers=old, status=401)
    async with wire.factory.sessions() as fresh:
        stored = await fresh.get(ApiKey, key_id)
        assert stored and stored.tier == "professional" and stored.subscription_state == "active"
        assert stored.recovery_token_hash is None and stored.recovery_token_expires is None
    await wire.request("POST", "/v1/auth/recover/confirm", status=401, omit_api_key=True, json={"token": token})


async def test_unknown_and_billing_contact_get_identical_response(wire: Wire, mail: AsyncMock):
    await signup(wire, "owner@example.test")
    async with wire.factory.sessions.begin() as session:
        key = (await session.scalars(select(ApiKey).where(ApiKey.signup_email == "owner@example.test"))).one()
        key.contact_email = "billing@example.test"
    for email in ("unknown@example.test", "billing@example.test"):
        result = await wire.request("POST", "/v1/auth/recover", omit_api_key=True, json={"email": email})
        assert result.json() == {"message": "Check your email for a recovery code."}
    mail.assert_not_awaited()


async def test_recovery_limit_uses_normalized_email_for_everyone(wire: Wire, mail: AsyncMock):
    await signup(wire, "owner@example.test")
    for address in ("owner@example.test", "unknown@example.test"):
        for email in (address, address.upper(), " " + address):
            await wire.request("POST", "/v1/auth/recover", omit_api_key=True, json={"email": email})
        await wire.request("POST", "/v1/auth/recover", status=429, omit_api_key=True, json={"email": address})
    assert mail.await_count == 3


async def test_recovery_replaces_codes_and_enforces_expiry(wire: Wire, mail: AsyncMock):
    owner = await signup(wire, "owner@example.test")
    first = await send_code(wire, "owner@example.test", mail)
    second = await send_code(wire, "owner@example.test", mail)
    assert first != second
    async with wire.factory.sessions.begin() as session:
        key = (await session.scalars(select(ApiKey).where(ApiKey.tenant_id == owner["tenant_id"]))).one()
        key.recovery_token_expires = datetime.now(timezone.utc) - timedelta(seconds=1)
    for token in (first, second, uuid4().hex, "x" * 64):
        refused = await wire.request("POST", "/v1/auth/recover/confirm", status=401,
                                     omit_api_key=True, json={"token": token})
        assert refused.json()["detail"] == "Invalid or expired recovery code"
    await wire.request("GET", "/v1/projects", headers={"X-Api-Key": owner["api_key"]})


async def test_concurrent_recovery_has_one_winner(wire: Wire, mail: AsyncMock):
    await signup(wire, "owner@example.test")
    token = await send_code(wire, "owner@example.test", mail)
    results = await asyncio.gather(*(wire.client.post("/v1/auth/recover/confirm", json={"token": token})
                                     for _ in range(2)))
    assert sorted(response.status_code for response in results) == [200, 401]
    success = next(response for response in results if response.status_code == 200)
    await wire.request("GET", "/v1/projects", headers={"X-Api-Key": success.json()["api_key"]})


async def test_admin_rotation_invalidates_outstanding_code(wire: Wire, mail: AsyncMock):
    owner = await signup(wire, "owner@example.test")
    token = await send_code(wire, "owner@example.test", mail)
    async with wire.factory.sessions() as session:
        key_id = await session.scalar(select(ApiKey.id).where(ApiKey.tenant_id == owner["tenant_id"]))
    await wire.request("POST", f"/v1/admin/api-keys/{key_id}/rotate", omit_api_key=True,
                       headers={"X-Admin-Key": os.environ["ADMIN_API_KEY"]})
    await wire.request("POST", "/v1/auth/recover/confirm", status=401, omit_api_key=True, json={"token": token})


async def test_project_refuses_unscorable_factor_count(wire: Wire):
    payload = {"name": "First", "public_domain_id": "first", "factors": ["quality"], "categories": ["default"]}
    await wire.request("POST", "/v1/projects", json=payload, status=422)
    payload["factors"] = ["quality", "difficulty"]
    await wire.request("POST", "/v1/projects", json=payload, status=201)
