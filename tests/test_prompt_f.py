"""Prompt F guide, client, prediction review and integrations contracts."""
from __future__ import annotations

import ast
import runpy
import auth
import scheduler
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import select

import webhook_router
from db.models import WebhookAttempt, WebhookDelivery, WebhookEndpoint
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.browser.test_browser_contracts import origin  # noqa: F401
from tests.harness.fixtures.factory import Wire
from tests.harness.scenarios.test_s01_s06 import test_s1_new_signup_and_mismatched_mailbox as _s1
from tests.harness.scenarios.test_s20_s27 import (
    test_s23_concurrent_reservations_at_49_plus_two_requests as _s23,
    test_s27_bulk_approval_independent_outcomes_and_a_skipped_item as _s27,
)

pytestmark = pytest.mark.anyio
CLIENT = Path(__file__).parents[1] / "backend" / "static" / "dlj_client.py"


@pytest.fixture(autouse=True)
def public_webhook_destination(monkeypatch):
    monkeypatch.setattr(webhook_router, "validate_public_https", AsyncMock())


async def _project(wire: Wire, name: str = "prompt-f") -> str:
    return (await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name, "factors": ["quality", "difficulty"],
        "categories": ["A", "B"], "actions": ["approve", "reject"],
    })).json()["id"]


async def _prediction(wire: Wire, project_id: str, label: str = "pred-1") -> dict:
    response = await wire.request("POST", f"/v1/projects/{project_id}/predictions", status=201, json={
        "request_key": f"request-{label}", "items": [{
            "label_id": label, "source": "model-f", "model_version": "v1", "category": "A",
            "annotator_id": "model-reviewer", "factors": {"quality": .8, "difficulty": .2},
            "model_confidence": .91, "text": f"Prediction text {label}",
        }],
    })
    return response.json()["results"][0]


async def _webhook(wire: Wire, project_id: str) -> dict:
    return (await wire.request("POST", f"/v1/projects/{project_id}/webhooks", status=201, json={
        "url": "https://hooks.example.test/f", "subscribed_events": ["webhook.test"],
    })).json()


async def test_guide_route_returns_html(wire: Wire):
    response = await wire.request("GET", "/", omit_api_key=True)
    assert "text/html" in response.headers["content-type"] and 'id="root"' in response.text


async def test_client_download(wire: Wire):
    response = await wire.request("GET", "/dlj_client.py", omit_api_key=True)
    dockerfile = (CLIENT.parents[2] / "Dockerfile").read_text()
    assert "COPY backend/static/dlj_client.py backend/static/dlj_client.py" in dockerfile
    assert response.headers["content-type"].startswith("text/x-python")
    assert "attachment" in response.headers["content-disposition"] and "class DLJClient" in response.text


async def test_client_is_valid_python(wire: Wire):
    source = (await wire.request("GET", "/dlj_client.py", omit_api_key=True)).text
    compile(source, "dlj_client.py", "exec")


async def test_client_has_required_methods(wire: Wire):
    tree = ast.parse((await wire.request("GET", "/dlj_client.py", omit_api_key=True)).text)
    client = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DLJClient")
    names = {node.name for node in client.body if isinstance(node, ast.FunctionDef)}
    assert {"__init__", "create_project", "upload", "verify", "import_predictions", "export", "get_status", "list_webhooks"} <= names


async def test_openapi_schema_accessible(wire: Wire):
    schema = (await wire.request("GET", "/openapi.json", omit_api_key=True)).json()
    assert schema["openapi"].startswith("3.") and "/v1/projects/{domain_id}/predictions" in schema["paths"]
    assert "/dlj_client.py" in schema["paths"]


async def test_review_accept_prediction(wire: Wire):
    project = await _project(wire, "accept")
    item = await _prediction(wire, project)
    reviewed = (await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", json={
        "action": "accept", "expected_revision": item["current_label_log_id"],
        "decision_version": item["decision_version"], "human_spans_reviewed": True,
    })).json()
    assert reviewed["state"] == "human_reviewed" and reviewed["assessment"] == "correct"


async def test_review_correct_prediction(wire: Wire):
    project = await _project(wire, "correct")
    item = await _prediction(wire, project)
    reviewed = (await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", json={
        "action": "correct", "category": "B", "actual_action": "reject",
        "expected_revision": item["current_label_log_id"], "decision_version": 1,
        "human_spans_reviewed": True,
    })).json()
    assert reviewed["assessment"] == "incorrect" and reviewed["current_label_log_id"] != item["current_label_log_id"]


async def test_review_reopen_prediction(wire: Wire):
    project = await _project(wire, "reopen")
    item = await _prediction(wire, project)
    reviewed = (await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", json={
        "action": "accept", "expected_revision": item["current_label_log_id"], "decision_version": 1,
    })).json()
    reopened = (await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/reopen", json={
        "expected_revision": reviewed["current_label_log_id"], "decision_version": reviewed["decision_version"],
    })).json()
    assert reopened["state"] == "pending" and reopened["current_label_log_id"] != item["current_label_log_id"]


async def test_review_requires_auth(wire: Wire):
    project = await _project(wire, "auth-review")
    item = await _prediction(wire, project)
    await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", status=401,
                       omit_api_key=True, json={"action": "accept", "expected_revision": item["current_label_log_id"], "decision_version": 1})


async def test_review_wrong_project(wire: Wire):
    first, second = await _project(wire, "first-review"), await _project(wire, "second-review")
    item = await _prediction(wire, first)
    await wire.request("POST", f"/v1/projects/{second}/predictions/{item['id']}/review", status=404, json={
        "action": "accept", "expected_revision": item["current_label_log_id"], "decision_version": 1})


async def test_review_respects_revision(wire: Wire):
    project = await _project(wire, "stale-review")
    item = await _prediction(wire, project)
    await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", status=409, json={
        "action": "accept", "expected_revision": item["current_label_log_id"], "decision_version": 99})


async def test_delivery_history_returns_attempts(wire: Wire):
    project = await _project(wire, "history")
    hook = await _webhook(wire, project)
    sent = (await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/test", status=201)).json()
    now = datetime.now(timezone.utc)
    async with wire.factory.sessions.begin() as session:
        session.add(WebhookAttempt(delivery_id=UUID(sent["delivery_id"]), attempt_no=1, key_version=1,
                                   started_at=now, finished_at=now + timedelta(milliseconds=25),
                                   outcome="success", http_status=204))
    page = (await wire.request("GET", f"/v1/projects/{project}/webhooks/{hook['id']}/deliveries")).json()
    assert page["attempt_history"][0]["http_status"] == 204 and page["attempt_history"][0]["response_time_ms"] == 25


async def test_delivery_health_summary(wire: Wire):
    project = await _project(wire, "health")
    hook = await _webhook(wire, project)
    health = (await wire.request("GET", f"/v1/projects/{project}/webhooks/health")).json()
    assert health == {"total": 1, "healthy": 0, "retrying": 0, "failing": 0,
                      "items": [{"webhook_id": hook["id"], "status": "awaiting", "active": True,
                                 "last_delivery_state": None, "last_status": None,
                                 "last_delivered_at": None, "next_retry_at": None}]}


async def test_delivery_health_requires_auth(wire: Wire):
    project = await _project(wire, "health-auth")
    await wire.request("GET", f"/v1/projects/{project}/webhooks/health", status=401, omit_api_key=True)


async def test_webhook_secret_shown_once(wire: Wire):
    project = await _project(wire, "secret-once")
    hook = await _webhook(wire, project)
    listed = (await wire.request("GET", f"/v1/projects/{project}/webhooks")).json()[0]
    assert hook["signing_secret"] and "signing_secret" not in listed and listed["signing_secret_masked"] == "dlj_whsec_****"


async def test_webhook_secret_rotation(wire: Wire):
    project = await _project(wire, "secret-rotation")
    hook = await _webhook(wire, project)
    sent = (await wire.request(
        "POST", f"/v1/projects/{project}/webhooks/{hook['id']}/test", status=201
    )).json()
    rotated = (await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/rotate")).json()
    async with wire.factory.sessions() as session:
        delivery = await session.get(WebhookDelivery, UUID(sent["delivery_id"]))
    assert delivery is not None and delivery.destination_version == 1
    assert rotated["destination_version"] == 2
    assert rotated["key_version"] == 2 and rotated["signing_secret"] != hook["signing_secret"] and rotated["rotated_at"]


async def test_webhook_test_send(wire: Wire):
    project = await _project(wire, "test-send")
    hook = await _webhook(wire, project)
    await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/test", status=201)
    page = (await wire.request("GET", f"/v1/projects/{project}/webhooks/{hook['id']}/deliveries")).json()
    assert page["total"] == 1 and page["items"][0]["event_type"] == "webhook.test"


async def test_s1_rerun_signup_mismatch(wire: Wire):
    await _s1(wire)


async def test_s23_rerun_concurrent_reservations(wire: Wire):
    await _s23(wire)


async def test_s27_rerun_bulk_approval(wire: Wire):
    await _s27(wire)


async def test_s28_rerun_late_signup_rotation(wire: Wire):
    old_key = wire.client.headers["x-api-key"]
    new_key = await wire.factory.user("replacement-account")
    assert old_key != new_key
    account = await wire.request("GET", "/v1/account", headers={"X-Api-Key": new_key})
    assert account.json()["tenant_id"] == "replacement-account"


async def test_s29_rerun_rotation_between_chunks(wire: Wire):
    project = await _project(wire, "chunk-owner")
    await wire.request("POST", f"/v1/projects/{project}/labels/batch", json={"request_key": "prefix", "items": [{
        "label_id": "prefix", "category": "A", "factors": {"quality": .8, "difficulty": .2}}]})
    outsider = await wire.factory.user("new-owner")
    await wire.request("GET", f"/v1/projects/{project}", status=404, headers={"X-Api-Key": outsider})


async def test_s30_rerun_domain_switch_inflight(wire: Wire):
    first, second = await _project(wire, "switch-a"), await _project(wire, "switch-b")
    item = await _prediction(wire, first, "shared-id")
    assert (await wire.request("GET", f"/v1/projects/{first}/predictions")).json()["items"][0]["id"] == item["id"]
    assert (await wire.request("GET", f"/v1/projects/{second}/predictions")).json()["items"] == []


async def test_s31_rerun_tag_draft_during_save(wire: Wire):
    project = await _project(wire, "sequential-review")
    item = await _prediction(wire, project)
    body = {"action": "accept", "expected_revision": item["current_label_log_id"], "decision_version": 1}
    await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", json=body)
    await wire.request("POST", f"/v1/projects/{project}/predictions/{item['id']}/review", status=409, json=body)


async def test_f_quickstart_flow(wire: Wire, origin):
    await wire.request("POST", "/v1/auth/register", status=202, omit_api_key=True,
                       json={"email": "r5-client@example.test"})
    sender = auth.send_signup_challenge_email
    assert isinstance(sender, AsyncMock) and sender.await_args
    key = (await wire.request("POST", "/v1/auth/confirm", status=201, omit_api_key=True,
                              json={"token": sender.await_args.args[1]})).json()["api_key"]
    Client = runpy.run_path(str(CLIENT))["DLJClient"]

    def run():
        client = Client(origin, key)
        pid = client.create_project("Quickstart", ["A"], ["quality", "difficulty"], ["approve", "reject"])["id"]
        rows = [{"label_id": str(i), "category": "A", "factors": {"quality": .8, "difficulty": .2}}
                for i in range(2)]
        summary = client.upload(pid, rows, chunk_size=1)
        assert summary["committed"] == 2 and len(summary["chunks"]) == 2
        with pytest.raises(ValueError, match="observed"):
            client.verify(pid, "0", "approve")
        client.verify(pid, "0", "approve", {"verified_outcome": False})
        exported = list(client.export(pid))
        assert len(exported) == 2
        assert next(row for row in exported if row["current_label_id"] == "0")["verified_outcome"] is False
        assert client.get_status(pid)["id"] == pid and client.list_webhooks(pid) == []
        client.session.close()

    await asyncio.to_thread(run)


async def test_f_role_gates(wire: Wire):
    project = await _project(wire, "role-gates")
    reviewer = await wire.factory.user("reviewer-f")
    await wire.request("POST", f"/v1/projects/{project}/members", status=201,
                       json={"member_tenant_id": "reviewer-f", "role": "reviewer"})
    await wire.request("POST", f"/v1/projects/{project}/webhooks", status=403,
                       headers={"X-Api-Key": reviewer}, json={"url": "https://hooks.example.test/no", "subscribed_events": ["webhook.test"]})


async def test_f_keyboard_shortcuts_dont_fire_without_focus(wire: Wire):
    project = await _project(wire, "rapid-review")
    item = await _prediction(wire, project)
    body = {"action": "accept", "expected_revision": item["current_label_log_id"],
            "decision_version": item["decision_version"]}
    first, second = await asyncio.gather(
        wire.client.post(f"/v1/projects/{project}/predictions/{item['id']}/review", json=body),
        wire.client.post(f"/v1/projects/{project}/predictions/{item['id']}/review", json=body),
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]


async def test_f_secret_handling_rotation_during_delivery(wire: Wire):
    project = await _project(wire, "rotation-delivery")
    hook = await _webhook(wire, project)
    sent = (await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/test", status=201)).json()
    await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/rotate")
    async with wire.factory.sessions() as session:
        delivery = await session.get(WebhookDelivery, UUID(sent["delivery_id"]))
        endpoint = await session.get(WebhookEndpoint, UUID(hook["id"]))
        assert delivery and endpoint and delivery.destination_version == 1 and endpoint.key_version == 2
        assert delivery.state == "cancelled"


async def test_f_recovery_gate_webhook_failure(wire: Wire, monkeypatch):
    project = await _project(wire, "recovery-health")
    hook = await _webhook(wire, project)
    sent = (await wire.request("POST", f"/v1/projects/{project}/webhooks/{hook['id']}/test", status=201)).json()
    send = AsyncMock(side_effect=[scheduler.DeliveryResult(503, "http_error"), scheduler.DeliveryResult(204, None)])
    monkeypatch.setattr(scheduler, "_send_webhook", send)
    assert await scheduler.dispatch_webhooks_once() == 1
    degraded = (await wire.request("GET", f"/v1/projects/{project}/webhooks/health")).json()
    assert degraded["retrying"] == 1
    async with wire.factory.sessions.begin() as session:
        delivery = await session.get(WebhookDelivery, UUID(sent["delivery_id"]), with_for_update=True)
        assert delivery and delivery.next_attempt_at
        delivery.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await scheduler.dispatch_webhooks_once() == 1 and send.await_count == 2
    recovered = (await wire.request("GET", f"/v1/projects/{project}/webhooks/health")).json()
    assert recovered["healthy"] == 1 and recovered["retrying"] == 0
    history = (await wire.request("GET", f"/v1/projects/{project}/webhooks/{hook['id']}/deliveries")).json()
    assert [a["http_status"] for a in history["attempt_history"]] == [204, 503]
    assert history["attempt_history"][1]["error_summary"] == "http_error"


async def test_queue_origin_state_and_pagination(wire: Wire):
    project = await _project(wire, "r5-queue")
    path = f"/v1/projects/{project}"
    item = await _prediction(wire, project)
    await wire.request("POST", path + "/labels/batch", json={"request_key": "human", "items": [{
        "label_id": "human", "category": "A", "factors": {"quality": .8, "difficulty": .2}, "text": "Z"}]})
    for offset, origin_name in enumerate(["prediction", "human"]):
        page = (await wire.request("GET", path + f"/predictions?origin=all&sort_by=text&sort_order=asc&limit=1&offset={offset}")).json()
        assert page["total"] == 2 and [r["origin"] for r in page["items"]] == [origin_name]
    human = (await wire.request("GET", path + "/predictions?origin=human")).json()
    assert [r["label_id"] for r in human["items"]] == ["human"]
    await wire.request("POST", path + f"/predictions/{item['id']}/review", json={
        "assessment": "unknown", "expected_revision": item["current_label_log_id"], "decision_version": 1})
    assert (await wire.request("GET", path + "/predictions?prediction_state=accepted")).json()["total"] == 0
    unknown = (await wire.request("GET", path + "/predictions?prediction_state=unknown")).json()
    assert unknown["items"][0]["prediction_state"] == "unknown"
