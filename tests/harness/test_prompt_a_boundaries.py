"""Focused Prompt A connector-boundary regressions; S5/S6 remain broader gates."""

import pytest
from sqlalchemy import func, select

import billing
from db.models import LabelLog
from .fixtures.factory import Wire


@pytest.mark.anyio
async def test_malformed_connector_action_has_no_write(wire: Wire):
    headers = {"X-LS-Token": "harness-ls"}
    for action in ({"unexpected": True}, ["ANNOTATION_CREATED"], None):
        response = await wire.request("POST", "/v1/label-studio/webhook", status=422,
                                      headers=headers, json={"action": action})
        assert "action must be a string" in response.json()["detail"]
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(LabelLog)) == 0


@pytest.mark.anyio
async def test_connector_derived_id_limits_have_no_write(wire: Wire):
    headers = {"X-LS-Token": "harness-ls"}
    valid = {"id": "t" * 200, "data": {"quality": .8, "difficulty": .2, "category": "A"}}
    for project, task in (({"id": "p" * 201}, valid),
                          ({"id": "demo"}, {**valid, "id": "t" * 201}),
                          ({"id": "demo"}, {"id": "t" * 200, "data": {"quality": .8, "difficulty": .2, "category": "c" * 201}})):
        await wire.request("POST", "/v1/label-studio/predict", status=422,
                           headers=headers, json={"project": project, "tasks": [task]})
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(LabelLog)) == 0


@pytest.mark.anyio
async def test_billing_admission_rejects_before_body_read(wire: Wire):
    for _ in range(billing.MAX_BILLING_READERS):
        await billing._billing_reader_slots.acquire()
    try:
        response = await wire.request("POST", "/v1/billing/webhook", status=503,
                                      content=b"not a webhook")
        assert response.json()["detail"] == "Billing intake is busy"
    finally:
        for _ in range(billing.MAX_BILLING_READERS):
            billing._billing_reader_slots.release()
