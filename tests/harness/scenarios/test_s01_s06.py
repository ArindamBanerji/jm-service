import pytest
import asyncio
import threading
import logging
import hashlib
import hmac
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID
from sqlalchemy import func, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

import auth
import billing
import label_studio
import jm_service
import scheduler
from label_health import api as health_api
from db.models import ApiKey, Domain, Engine, LabelLog, SignupChallenge
from db.connection import normalize_database_url, sanitize_database_error
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
async def test_legacy_shared_signup_key_requires_proof_and_rotates(wire: Wire):
    old_key = await wire.factory.user("legacy-tenant")
    async with wire.factory.sessions.begin() as session:
        record = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "legacy-tenant"))
        assert record is not None
        old_id = record.id
        record.contact_email = "legacy@example.test"
        record.signup_email = "legacy@example.test"  # Reconciled owner evidence.
        record.tier = "professional"
        record.subscription_state = "active"
        record.is_active = False  # Migration quarantines unproved historical signups.
        record.reproof_required = True
    await wire.request("GET", "/v1/account", status=401, headers={"X-Api-Key": old_key})
    await wire.request("POST", "/v1/auth/register", status=202,
                       omit_api_key=True, json={"email": "legacy@example.test"})
    delivery = cast(AsyncMock, auth.send_signup_challenge_email)
    assert delivery.await_args is not None
    token = delivery.await_args.args[1]
    confirmed = await wire.request("POST", "/v1/auth/confirm", status=201,
                                   omit_api_key=True, json={"token": token})
    assert confirmed.json()["tenant_id"] == "legacy-tenant"
    assert confirmed.json()["tier"] == "professional"
    assert confirmed.json()["api_key"] != old_key
    await wire.request("GET", "/v1/account", status=401, headers={"X-Api-Key": old_key})
    await wire.request("GET", "/v1/account", headers={
        "X-Api-Key": confirmed.json()["api_key"]})
    async with wire.factory.sessions() as fresh:
        record = await fresh.get(ApiKey, old_id)
        assert record is not None and record.is_active and record.email_verified_at is not None
        assert record.reproof_required is False


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_unrelated_revoked_key_cannot_recover_by_email(wire: Wire):
    await wire.factory.user("revoked-tenant")
    async with wire.factory.sessions.begin() as session:
        record = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "revoked-tenant"))
        assert record is not None
        record.contact_email = "revoked@example.test"
        record.is_active = False
        record.reproof_required = False
    await wire.request("POST", "/v1/auth/register", status=409,
                       omit_api_key=True, json={"email": "revoked@example.test"})


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
    delivered_tokens: list[str] = []
    async def delivered_mail(email: str, token: str) -> bool:
        # Delivery observes only committed proof, from an independent session.
        async with wire.factory.sessions() as fresh:
            proof = await fresh.get(SignupChallenge, hashlib.sha256(token.encode()).hexdigest())
            assert proof is not None and proof.email == email
            assert await fresh.scalar(select(func.count()).select_from(ApiKey).where(
                ApiKey.contact_email == email)) == 0
        delivered_tokens.append(token)
        return True
    delivered = AsyncMock(side_effect=delivered_mail)
    monkeypatch.setattr(auth, "send_signup_challenge_email", delivered)
    await wire.request("POST", "/v1/auth/register", status=202,
                       omit_api_key=True, json={"email": "race@example.test"})
    assert delivered.await_args is not None
    token = delivered_tokens[-1]
    both_at_claim = asyncio.Event()
    claims = 0
    execute = AsyncSession.execute
    async def claim_barrier(self, statement, *args, **kwargs):
        nonlocal claims
        if "UPDATE signup_challenge" in str(statement):
            claims += 1
            if claims == 2:
                both_at_claim.set()
            await asyncio.wait_for(both_at_claim.wait(), 5)
        return await execute(self, statement, *args, **kwargs)
    monkeypatch.setattr(AsyncSession, "execute", claim_barrier)
    first, second = await asyncio.gather(*(
        wire.client.post("/v1/auth/confirm", json={"token": token}) for _ in range(2)))
    assert claims == 2
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

    async def interrupted_upload():
        yield b"--incomplete\r\n"
        raise RuntimeError("test upload disconnected")

    with pytest.raises(RuntimeError, match="test upload disconnected"):
        await wire.client.post("/v1/label-health/analyze", content=interrupted_upload(),
                               headers={"Content-Type": "multipart/form-data; boundary=incomplete"})
    # Require both real worker callbacks to overlap after the disconnect.
    count = 0
    started.clear()
    release.clear()
    recovered_reports = [asyncio.create_task(wire.client.post(
        "/v1/label-health/analyze", files=body)) for _ in range(2)]
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert count == 2
    finally:
        release.set()
        assert all(r.status_code == 200 for r in await asyncio.gather(*recovered_reports))

    original_report_slots = health_api._slots
    report_waiters_started = asyncio.Event()
    release_report_waiters = asyncio.Event()
    active_report_waiters = 0
    peak_report_waiters = 0
    class DelayedReportSlots:
        def locked(self):
            return False
        async def acquire(self):
            nonlocal active_report_waiters, peak_report_waiters
            active_report_waiters += 1
            peak_report_waiters = max(peak_report_waiters, active_report_waiters)
            if active_report_waiters == 2:
                report_waiters_started.set()
            try:
                await release_report_waiters.wait()
                return await original_report_slots.acquire()
            finally:
                active_report_waiters -= 1
        def release(self):
            original_report_slots.release()
    monkeypatch.setattr(health_api, "_slots", DelayedReportSlots())
    monkeypatch.setattr(health_api, "_ADMISSION_WAIT", 1.0)
    report_contenders = [asyncio.create_task(wire.client.post(
        "/v1/label-health/analyze", files=body)) for _ in range(5)]
    await asyncio.wait_for(report_waiters_started.wait(), 5)
    await asyncio.sleep(0)
    assert peak_report_waiters == 2
    release_report_waiters.set()
    report_results = await asyncio.gather(*report_contenders)
    assert sum(response.status_code == 503 for response in report_results) == 3
    assert health_api._waiters == 0
    monkeypatch.setattr(health_api, "_slots", original_report_slots)

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

    original_process = billing._process_paddle_webhook
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

    monkeypatch.setattr(billing, "_process_paddle_webhook", original_process)
    signed_body = json.dumps({
        "event_type": "subscription.unknown", "event_id": "evt-s3-stream",
        "occurred_at": datetime.now(timezone.utc).isoformat(), "data": {},
    }).encode()
    stamp = "1700000000"
    digest = hmac.new(b"harness-secret", stamp.encode() + b":" + signed_body,
                      hashlib.sha256).hexdigest()
    signed_headers = {"Content-Type": "application/json",
                      "Paddle-Signature": f"ts={stamp};h1={digest}"}
    stream_started = asyncio.Event()
    release_stream = asyncio.Event()
    readers = 0
    extra_read = 0

    async def held_stream():
        nonlocal readers
        readers += 1
        if readers == billing.MAX_BILLING_READERS:
            stream_started.set()
        yield signed_body[:5]
        await release_stream.wait()
        yield signed_body[5:]

    async def refused_stream():
        nonlocal extra_read
        extra_read += 1
        yield signed_body

    held = [asyncio.create_task(wire.client.post(
        "/v1/billing/webhook", content=held_stream(), headers=signed_headers))
        for _ in range(billing.MAX_BILLING_READERS)]
    try:
        await asyncio.wait_for(stream_started.wait(), 5)
        refused = await wire.client.post("/v1/billing/webhook",
                                         content=refused_stream(), headers=signed_headers)
        assert refused.status_code == 503 and extra_read == 0
    finally:
        release_stream.set()
        completed = await asyncio.gather(*held)
        assert all(response.status_code == 200 for response in completed)
    recovered = await wire.client.post("/v1/billing/webhook",
                                       content=signed_body, headers=signed_headers)
    assert recovered.status_code == 200
    async def disconnected_stream():
        yield signed_body[:5]
        raise RuntimeError("client disconnected")
    with pytest.raises(RuntimeError, match="client disconnected"):
        await wire.client.post("/v1/billing/webhook", content=disconnected_stream(),
                               headers=signed_headers)
    after_disconnect = await wire.client.post("/v1/billing/webhook",
                                              content=signed_body, headers=signed_headers)
    assert after_disconnect.status_code == 200
    recovered_started = asyncio.Event()
    recovered_release = asyncio.Event()
    recovered_active = 0
    recovered_peak = 0
    async def recovered_process(request):
        nonlocal recovered_active, recovered_peak
        recovered_active += 1
        recovered_peak = max(recovered_peak, recovered_active)
        if recovered_active == billing.MAX_BILLING_READERS:
            recovered_started.set()
        try:
            await recovered_release.wait()
            return {"status": "ok"}
        finally:
            recovered_active -= 1
    monkeypatch.setattr(billing, "_process_paddle_webhook", recovered_process)
    recovered_tasks = [asyncio.create_task(wire.client.post(
        "/v1/billing/webhook", content=signed_body, headers=signed_headers))
        for _ in range(billing.MAX_BILLING_READERS)]
    await asyncio.wait_for(recovered_started.wait(), 5)
    assert recovered_peak == billing.MAX_BILLING_READERS
    recovered_release.set()
    recovered_capacity = await asyncio.gather(*recovered_tasks)
    assert all(response.status_code == 200 for response in recovered_capacity)
    monkeypatch.setattr(billing, "_process_paddle_webhook", original_process)
    original_slots = billing._billing_reader_slots
    admission_started = asyncio.Event()
    release_admission = asyncio.Event()
    active_waiters = 0
    peak_waiters = 0
    class DelayedSlots:
        def locked(self):
            return False
        async def acquire(self):
            nonlocal active_waiters, peak_waiters
            active_waiters += 1
            peak_waiters = max(peak_waiters, active_waiters)
            if active_waiters == billing.MAX_BILLING_READERS:
                admission_started.set()
            try:
                await release_admission.wait()
                return await original_slots.acquire()
            finally:
                active_waiters -= 1
        def release(self):
            original_slots.release()
    monkeypatch.setattr(billing, "_billing_reader_slots", DelayedSlots())
    contenders = [asyncio.create_task(wire.client.post(
        "/v1/billing/webhook", content=signed_body, headers=signed_headers)) for _ in range(10)]
    try:
        await asyncio.wait_for(admission_started.wait(), 5)
        await asyncio.sleep(.02)
        assert peak_waiters <= billing.MAX_BILLING_READERS
    finally:
        release_admission.set()
    results = await asyncio.gather(*contenders)
    assert sum(response.status_code == 503 for response in results) >= 6
    assert billing._billing_waiters == 0


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s4_forced_unhandled_database_failure_through_asgi_and_scheduler(wire: Wire, monkeypatch, caplog):
    """S4. Forced unhandled database failure through ASGI and scheduler."""
    canary = "dlj_sql_private_canary"
    failure = StatementError("driver failed", "INSERT INTO api_keys (key_hash) VALUES (:value)",
                             {"value": canary}, Exception(f"parameter={canary}"))
    original_select = auth.select
    def broken_auth(*args, **kwargs):
        raise failure
    monkeypatch.setattr(auth, "select", broken_auth)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=jm_service.app, raise_app_exceptions=False),
            base_url="http://harness.test") as client:
        response = await client.get("/v1/account", headers={"X-Api-Key": "canary"})
    assert response.status_code == 500
    assert canary not in response.text
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=jm_service.app, raise_app_exceptions=True),
            base_url="http://harness.test") as client:
        with pytest.raises(RuntimeError) as server_error:
            await client.get("/v1/account", headers={"X-Api-Key": "canary"})
    assert canary not in str(server_error.value)
    monkeypatch.setattr(auth, "select", original_select)
    original_scalar = AsyncSession.scalar
    async def real_driver_failure(self, statement, *args, **kwargs):
        if "FROM api_keys" in str(statement):
            await self.execute(text("INSERT INTO nonexistent_dlj_s4 (secret) VALUES (:secret)"),
                               {"secret": canary})
        return await original_scalar(self, statement, *args, **kwargs)
    monkeypatch.setattr(AsyncSession, "scalar", real_driver_failure)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=jm_service.app, raise_app_exceptions=True),
            base_url="http://harness.test") as client:
        with pytest.raises(RuntimeError) as driver_error:
            await client.get("/v1/account", headers={"X-Api-Key": "canary"})
    assert canary not in "".join(traceback.format_exception(driver_error.value))
    monkeypatch.setattr(AsyncSession, "scalar", original_scalar)
    async def broken_job():
        raise failure
    monkeypatch.setattr(scheduler, "expire_trial_keys", broken_job)
    with caplog.at_level(logging.ERROR):
        await scheduler.run_scheduled_tasks()
    assert canary not in caplog.text
    startup = subprocess.run([sys.executable, "-c", "import db.connection"],
                             capture_output=True, text=True, timeout=15,
                             env={**os.environ, "DATABASE_URL":
                                  f"postgresql+asyncpg://user:{canary}@[bad/db"})
    assert startup.returncode != 0
    assert canary not in startup.stderr
    assert "Database URL is invalid" in startup.stderr
    assert "StatementError" in caplog.text
    with pytest.raises(ValueError) as invalid_option:
        normalize_database_url(f"postgresql+asyncpg://user:pass@localhost/db?sslmode={canary}")
    assert canary not in str(invalid_option.value)
    with caplog.at_level(logging.DEBUG):
        async with wire.factory.sessions() as fresh:
            with pytest.raises(Exception) as actual:
                await fresh.execute(text(
                    "INSERT INTO nonexistent_dlj_s4 (secret) VALUES (:secret)"),
                    {"secret": canary})
    assert canary not in sanitize_database_error(actual.value)
    assert canary not in caplog.text


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s5_malformed_connector_dispatch_results(wire: Wire, monkeypatch):
    """S5. Malformed connector dispatch/results."""
    headers = {"X-LS-Token": "harness-ls"}
    original_config = label_studio._config
    def forbidden_lookup(*args, **kwargs):
        raise AssertionError("Malformed dispatch reached connector configuration lookup")
    monkeypatch.setattr(label_studio, "_config", forbidden_lookup)
    for action in ({"bad": "value"}, ["ANNOTATION_CREATED"], None):
        response = await wire.request("POST", "/v1/label-studio/webhook", status=422,
                                      headers=headers, json={"action": action, "project": "p"})
        assert "action must be a string" in response.text
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED",
                                              "project": "p", "annotation": []})
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED",
                                              "project": "p", "annotation": {"id": "a", "result": [{}]}})
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED",
                                              "project": "p", "annotation": {
                                                  "id": "a", "result": [{"value": {"choices": [{"bad": 1}]}}]}})
    monkeypatch.setattr(label_studio, "_config", original_config)
    original_entitlement = label_studio.resolve_entitlement
    async def forbidden_entitlement(*args, **kwargs):
        raise AssertionError("Malformed connector input reached payer lookup")
    monkeypatch.setattr(label_studio, "resolve_entitlement", forbidden_entitlement)
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED", "project": "p",
                                              "annotation": {"id": "bad-task", "actual_action": "approve"},
                                              "task": {"id": "bad", "data": []}})
    for annotation, data in [
            ({"id": "a", "actual_action": "approve", "result": [{"value": {"choices": [None]}}]}, {}),
            ({"id": "a", "actual_action": "approve"}, {"quality": 2})]:
        await wire.request("POST", "/v1/label-studio/webhook", status=422, headers=headers, json={
            "action": "ANNOTATION_CREATED", "project": "p", "annotation": annotation,
            "task": {"id": "invalid", "data": data}})
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED", "project": "p",
                                              "annotation": {"id": "bad-truth", "actual_action": "approve"},
                                              "task": {"id": "unknown-truth", "data": {
                                                  "category": "default", "ground_truth": "unknown"}}})
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers=headers, json={"action": "ANNOTATION_CREATED",
                                              "project": "p", "annotation": {
                                                  "id": "wrong-action", "actual_action": "unknown"},
                                              "task": {"id": "pending", "data": {
                                                  "category": "A"}}})
    monkeypatch.setattr(label_studio, "resolve_entitlement", original_entitlement)
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(LabelLog)) == 0
        assert await fresh.scalar(select(func.count()).select_from(Domain)) == 0
        assert await fresh.scalar(select(func.count()).select_from(Engine)) == 0
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.labels_today == 0 and key.labels_this_month == 0


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s6_identifier_limits_through_all_create_reuse_paths(wire: Wire, monkeypatch):
    """S6. Identifier limits through all create/reuse paths."""
    project_body = {"name": "schema", "public_domain_id": "schema", "factors": ["x", "y"],
                    "categories": ["normal"], "actions": ["approve", "reject"]}
    for field in ("categories", "actions"):
        await wire.request("POST", "/v1/projects", status=422,
                           json={**project_body, field: ["invalid|name"]})
    longest = {"label_id": "L" * 200, "category": "C" * 200,
               "annotator_id": "A" * 200}
    base = {"domain_id": "bounded", "factors": {"quality": .8, "difficulty": .2}}
    await wire.request("POST", "/v1/labels/ingest", json={**base, **longest})
    for field in longest:
        invalid = {**longest, field: longest[field] + "X"}
        await wire.request("POST", "/v1/labels/ingest", status=422,
                           json={**base, **invalid})
    await wire.request("POST", "/v1/labels/ingest", status=422,
                       json={**base, **longest, "domain_id": "D" * 201})
    await wire.request("POST", "/v1/labels/bounded/tasks", status=422,
                       json={"label_id": "T" * 201, "text": "Task"})
    await wire.request("POST", f"/v1/labels/{'D' * 200}/tasks", status=201,
                       json={"label_id": "path-max", "text": "Task"})
    await wire.request("POST", f"/v1/labels/{'D' * 201}/tasks", status=422,
                       json={"label_id": "path-too-long", "text": "Task"})
    monkeypatch.delenv("LABEL_STUDIO_DOMAIN_ID", raising=False)
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers={"X-LS-Token": "harness-ls"}, json={
                           "action": "ANNOTATION_CREATED", "project": "p",
                           "annotation": {"id": "Z" * 200, "actual_action": "approve"},
                           "task": {"id": 1, "data": {"category": "A", "quality": .8,
                                                        "difficulty": .2}},
                       })
    await wire.request("POST", "/v1/label-studio/webhook", status=422,
                       headers={"X-LS-Token": "harness-ls"}, json={
                           "action": "ANNOTATION_CREATED", "project": "P" * 200,
                           "annotation": {"id": "1", "actual_action": "approve"},
                           "task": {"id": "1", "data": {"category": "A"}},
                       })
    at_limit = {"action": "ANNOTATION_CREATED", "project": "P" * 197,
                "annotation": {"id": "10", "actual_action": "approve", "completed_by": 7},
                "task": {"id": "limit-task", "data": {"category": "default",
                         "quality": .8, "difficulty": .2, "ground_truth": "approve"}}}
    await wire.request("POST", "/v1/label-studio/webhook",
                       headers={"X-LS-Token": "harness-ls"}, json=at_limit)
    await wire.request("POST", "/v1/label-studio/webhook",
                       headers={"X-LS-Token": "harness-ls"},
                       json={**at_limit, "action": "ANNOTATION_UPDATED"})
    bounded_action = "A" * 200
    project = await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Bounded actions", "public_domain_id": "bounded-actions",
        "factors": ["quality", "difficulty"], "categories": ["A"],
        "actions": [bounded_action],
    })
    scored = await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "bounded-actions", "label_id": "action-max", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    assert scored.json()["recommended_action"] == bounded_action
    project_path = "/v1/projects/" + project.json()["id"]
    await wire.request("PATCH", project_path, status=422, headers={"If-Match": "1"},
                       json={"actions": ["A" * 201]})
    assert (await wire.request("GET", project_path)).json()["settings_version"] == 1
    await wire.request("GET", "/v1/labels/bounded/items/" + "X" * 201, status=422)
    await wire.request("POST", "/v1/projects", status=422, json={
        "name": "Too long", "public_domain_id": "bounded-actions-too-long",
        "factors": ["quality", "difficulty"], "categories": ["A"],
        "actions": ["A" * 201],
    })
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog))).all()
        assert len(rows) == 4
        assert any(row.annotation_id == f"{'P' * 197}:10" for row in rows)
        assert {longest["label_id"], "path-max", "action-max"} <= {row.label_id for row in rows}
        assert await fresh.get(Domain, UUID(project.json()["id"])) is not None
