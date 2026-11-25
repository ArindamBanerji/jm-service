import pytest
import asyncio
import threading
import logging
from typing import cast
from unittest.mock import AsyncMock
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError
import httpx

import auth
import billing
import jm_service
import scheduler
from label_health import api as health_api
from db.models import ApiKey
from ..fixtures.factory import Wire


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s1_new_signup_and_mismatched_mailbox(wire: Wire):
    """S1. New signup and mismatched mailbox."""
    response = await wire.request("POST", "/v1/auth/register", status=202,
                                  omit_api_key=True, json={"email": "proof@example.test"})
    assert "api_key" not in response.json()
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(ApiKey).where(
            ApiKey.contact_email == "proof@example.test")) == 0
    await wire.request("POST", "/v1/auth/confirm", status=400,
                       omit_api_key=True, json={"token": "f" * 64})
    delivery = cast(AsyncMock, auth.send_signup_challenge_email)
    assert delivery.await_args is not None
    assert delivery.await_args.args[0] == "proof@example.test"
    token = delivery.await_args.args[1]
    confirmed = await wire.request("POST", "/v1/auth/confirm", status=201,
                                   omit_api_key=True, json={"token": token})
    account = await wire.request("GET", "/v1/account",
                                 headers={"X-Api-Key": confirmed.json()["api_key"]})
    assert account.json()["tenant_id"] == confirmed.json()["tenant_id"]
    assert account.json()["is_active"] is True
    await wire.request("POST", "/v1/auth/confirm", status=400,
                       omit_api_key=True, json={"token": token})


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s2_concurrent_proof_consumption_and_mail_failure(wire: Wire, monkeypatch):
    """S2. Concurrent proof consumption and mail failure."""
    failed = AsyncMock(return_value=False)
    monkeypatch.setattr(auth, "send_signup_challenge_email", failed)
    await wire.request("POST", "/v1/auth/register", status=503,
                       omit_api_key=True, json={"email": "failed@example.test"})
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(ApiKey).where(
            ApiKey.contact_email == "failed@example.test")) == 0
    delivered = AsyncMock(return_value=True)
    monkeypatch.setattr(auth, "send_signup_challenge_email", delivered)
    await wire.request("POST", "/v1/auth/register", status=202,
                       omit_api_key=True, json={"email": "race@example.test"})
    assert delivered.await_args is not None
    token = delivered.await_args.args[1]
    first, second = await asyncio.gather(*(
        wire.client.post("/v1/auth/confirm", json={"token": token}) for _ in range(2)))
    assert sorted((first.status_code, second.status_code)) == [201, 400]
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(ApiKey).where(
            ApiKey.contact_email == "race@example.test")) == 1


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s3_concurrent_anonymous_uploads_at_admission_limit(wire: Wire, monkeypatch):
    """S3. Concurrent anonymous uploads at admission limit."""
    started = threading.Event()
    release = threading.Event()
    count = 0

    def slow_report(data: bytes, output: str) -> dict:
        nonlocal count
        count += 1
        if count == 2:
            started.set()
        release.wait(5)
        return {"status": "ok"}

    monkeypatch.setattr(health_api, "_run_sync", slow_report)
    body = {"file": ("sample.csv", b"label_id,category,factor_a,factor_b\nL1,A,.8,.2", "text/csv")}
    pending = [asyncio.create_task(wire.client.post("/v1/label-health/analyze", files=body)) for _ in range(2)]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), 6)
        rejected = await wire.client.post("/v1/label-health/report/pdf", content=b"ignored")
        assert rejected.status_code == 503
        assert count == 2
    finally:
        release.set()
        completed = await asyncio.gather(*pending)
        assert all(response.status_code == 200 for response in completed)

    billing_started = asyncio.Event()
    billing_release = asyncio.Event()
    billing_count = 0

    async def slow_billing(request):
        nonlocal billing_count
        billing_count += 1
        if billing_count == 4:
            billing_started.set()
        await billing_release.wait()
        return {"status": "ok"}

    monkeypatch.setattr(billing, "_process_paddle_webhook", slow_billing)
    deliveries = [asyncio.create_task(wire.client.post("/v1/billing/webhook", content=b"{}"))
                  for _ in range(4)]
    try:
        await asyncio.wait_for(billing_started.wait(), 5)
        refused = await wire.client.post("/v1/billing/webhook", content=b"{}")
        assert refused.status_code == 503 and billing_count == 4
    finally:
        billing_release.set()
        completed = await asyncio.gather(*deliveries)
        assert all(response.status_code == 200 for response in completed)


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s4_forced_unhandled_database_failure_through_asgi_and_scheduler(wire: Wire, monkeypatch, caplog):
    """S4. Forced unhandled database failure through ASGI and scheduler."""
    canary = "dlj_sql_private_canary"
    failure = StatementError("driver failed", "INSERT INTO api_keys (key_hash) VALUES (:value)",
                             {"value": canary}, Exception(f"parameter={canary}"))
    async def broken_auth(key, session):
        raise failure
    monkeypatch.setattr(auth, "verify_api_key", broken_auth)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=jm_service.app, raise_app_exceptions=False),
            base_url="http://harness.test") as client:
        response = await client.get("/v1/account", headers={"X-Api-Key": "canary"})
    assert response.status_code == 500
    assert canary not in response.text
    async def broken_job():
        raise failure
    monkeypatch.setattr(scheduler, "expire_trial_keys", broken_job)
    with caplog.at_level(logging.ERROR):
        await scheduler.run_scheduled_tasks()
    assert canary not in caplog.text
    assert "StatementError" in caplog.text


@pytest.mark.prompt_a
@pytest.mark.xfail(strict=True, reason="Prompt A not yet shipped")
def test_s5_malformed_connector_dispatch_results():
    """S5. Malformed connector dispatch/results."""
    # TODO: Validate before access, controlled response and zero writes, N03/R31.
    pytest.skip("Scenario S5: awaiting Prompt A")


@pytest.mark.prompt_a
@pytest.mark.xfail(strict=True, reason="Prompt A not yet shipped")
def test_s6_identifier_limits_through_all_create_reuse_paths():
    """S6. Identifier limits through all create/reuse paths."""
    # TODO: PostgreSQL 422 and no writes at max+1, success at max, R05/R11.
    pytest.skip("Scenario S6: awaiting Prompt A")
