import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import select

import billing
from db.connection import sanitize_database_error
from db.models import LabelLog
from .contracts.test_connector import HEADERS, annotation
from .fixtures.factory import Wire
from .fixtures.failures import KnownGap


@pytest.mark.prompt_a
def test_known_failure_diagnostic_fields():
    # Synthetic formatter input only. Arbitrary driver prose is not connection metadata.
    result = sanitize_database_error(RuntimeError("sample-value unreachable"))
    if "sample-value" in result:
        raise KnownGap("Untrusted diagnostic field copied into the result")
    class DriverError(Exception):
        statement = "INSERT INTO api_keys (key_hash) VALUES ('dlj_secret_canary')"
        params = {"key_hash": "dlj_secret_canary"}
        orig = RuntimeError("dlj_secret_canary unreachable")
    rendered = sanitize_database_error(DriverError("dlj_secret_canary"))
    assert "dlj_secret_canary" not in rendered
    assert "INSERT INTO api_keys" in rendered


@pytest.mark.anyio
@pytest.mark.prompt_a
async def test_known_failure_billing_intake_deadline(monkeypatch):
    # Advance the test loop's clock at a read boundary. Only one small local body is used.
    loop = asyncio.get_running_loop()
    clock = loop.time
    elapsed = 0
    monkeypatch.setattr(loop, "time", lambda: clock() + elapsed)
    monkeypatch.setenv("PADDLE_SANDBOX", "true")
    monkeypatch.delenv("PADDLE_WEBHOOK_SECRET", raising=False)

    async def receive():
        nonlocal elapsed
        elapsed = 3600
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b'{"event_type":"test"}', "more_body": False}

    request: Request = Request({"type": "http", "method": "POST", "path": "/v1/billing/webhook", "headers": []}, receive)
    try:
        result = await billing.paddle_webhook(request)
    except HTTPException as error:
        assert error.status_code == 408
    else:
        assert result == {"status": "ok"}
        raise KnownGap("Intake completed after its deadline")


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_known_failure_connector_order(wire: Wire):
    path = "/v1/label-studio/webhook"
    await wire.request("POST", path, headers=HEADERS, json=annotation(stamp="2026-01-01T12:00:00Z"))
    await wire.request("POST", path, headers=HEADERS,
                       json=annotation("reject", kind="ANNOTATION_UPDATED", stamp="2026-01-02T12:00:00Z"))
    # An undated new edit returning to the first decision is ambiguous. A controlled conflict is valid.
    response = await wire.client.post(path, headers=HEADERS, json=annotation(kind="ANNOTATION_UPDATED"))
    if response.status_code == 409:
        return
    assert response.status_code == 200
    async with wire.factory.sessions() as fresh:
        row = (await fresh.scalars(select(LabelLog).where(LabelLog.superseded_by.is_(None)))).one()
        if response.json()["status"] == "processed" and row.actual_action != "approve":
            raise KnownGap("An intentional correction was acknowledged and discarded")


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_known_failure_task_binding(wire: Wire):
    path = "/v1/label-studio/webhook"
    await wire.request("POST", path, headers=HEADERS, json=annotation())
    response = await wire.client.post(path, headers=HEADERS, json=annotation(task_id=2))
    assert response.status_code in (200, 409)
    async with wire.factory.sessions() as fresh:
        stored = (await fresh.scalars(select(LabelLog.source_task_id))).one()
    if stored != "1":
        raise KnownGap("The existing revision's task binding changed")
    assert response.status_code == 409
