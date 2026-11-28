"""Prompt E contracts: webhook administration and durable delivery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, inspect, select

import scheduler
import webhook_router
import webhook_security
from db.models import (ApiKey, Domain, WebhookAttempt, WebhookDelivery,
                       WebhookEndpoint, WebhookEvent)
from webhook_security import signature
from .fixtures.factory import Wire


async def _project(wire: Wire, name: str = "Hooks") -> str:
    response = await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name.lower(),
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })
    return response.json()["id"]


async def _endpoint(wire: Wire, project_id: str, *, suffix: str = "one",
                    events: list[str] | None = None) -> dict:
    response = await wire.request("POST", f"/v1/projects/{project_id}/webhooks",
                                  status=201, json={
        "url": f"https://hooks.example.test/{suffix}",
        "subscribed_events": events or ["label.verified"],
    })
    return response.json()


async def _event(wire: Wire, project_id: str, transition: str = "transition-1") -> UUID:
    from db.repository import record_webhook_event
    async with wire.factory.sessions.begin() as session:
        project = await session.get(Domain, UUID(project_id))
        assert project is not None
        event = await record_webhook_event(session, project, "label.verified", transition, {"label_id": "L1"})
        return event.id


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_verified_label_delivery_and_archive_boundary(wire: Wire, monkeypatch):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Joint", "public_domain_id": "joint", "categories": ["A"],
        "factors": ["quality", "difficulty"]})).json()["id"]
    endpoint = await _endpoint(wire, project)
    base = f"/v1/projects/{project}"
    for name in ("first", "second"):
        await wire.request("POST", base + "/labels", headers={"Idempotency-Key": name},
                           json={"label_id": name, "category": "A", "annotator_id": "reviewer",
                                 "factors": {"quality": .9, "difficulty": .3}})
        await wire.request("POST", base + "/labels/verify", json={
            "label_id": name, "actual_action": "approve", "verified_outcome": True})
    sender = AsyncMock(return_value=scheduler.DeliveryResult(204, None))
    monkeypatch.setattr(scheduler, "_send_webhook", sender)
    assert await scheduler.dispatch_webhooks_once() == 1
    assert sender.await_args is not None
    body = sender.await_args.args[2]
    async with wire.factory.sessions() as session:
        event = await session.get(WebhookEvent, UUID(json.loads(body)["event_id"]))
        assert event and event.canonical_body == body and event.event_type == "label.verified"
        assert json.loads(body)["project_id"] == project
    claims = await scheduler._claim_webhook_deliveries()
    assert len(claims) == 1
    await wire.request("PUT", base + "/settings", json={"status": "archived", "settings_version": 1})
    await scheduler._deliver_claim(claims[0])
    sender.assert_awaited_once()
    async with wire.factory.sessions() as session:
        delivery = await session.get(WebhookDelivery, claims[0].delivery_id)
        target = await session.get(WebhookEndpoint, UUID(endpoint["id"]))
        assert delivery and delivery.state == "cancelled" and delivery.terminal_at
        assert target and not target.active


@pytest.fixture(autouse=True)
def public_webhook_urls(monkeypatch):
    monkeypatch.setattr(webhook_router, "validate_public_https", AsyncMock())
    monkeypatch.setattr(scheduler, "validate_public_https", AsyncMock(return_value="8.8.8.8"))


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_webhook_crud_secret_once_limit_and_role_gate(wire: Wire):
    project_id = await _project(wire)
    created = await _endpoint(wire, project_id)
    assert created["signing_secret"]
    endpoint_id = created["id"]
    async with wire.factory.sessions() as session:
        stored = await session.get(WebhookEndpoint, UUID(endpoint_id))
        assert stored is not None
        assert created["signing_secret"].encode() not in stored.secret_ciphertext
    listed = (await wire.request("GET", f"/v1/projects/{project_id}/webhooks")).json()
    assert len(listed) == 1 and "signing_secret" not in listed[0]
    assert "secret_ciphertext" not in listed[0]
    updated = (await wire.request(
        "PATCH", f"/v1/projects/{project_id}/webhooks/{endpoint_id}", json={
            "url": "https://hooks.example.test/updated",
            "subscribed_events": ["label.verified", "prediction.auto_approved"],
        })).json()
    assert updated["destination_version"] == 2
    assert updated["url"].endswith("/updated")

    for index in range(2, 6):
        await _endpoint(wire, project_id, suffix=str(index))
    await wire.request("POST", f"/v1/projects/{project_id}/webhooks", status=422, json={
        "url": "https://hooks.example.test/six", "subscribed_events": ["label.verified"],
    })

    reviewer_key = await wire.factory.user("reviewer-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201, json={
        "member_tenant_id": "reviewer-tenant", "role": "reviewer",
    })
    await wire.request("POST", f"/v1/projects/{project_id}/webhooks", status=403,
                       headers={"X-Api-Key": reviewer_key}, json={
                           "url": "https://hooks.example.test/reviewer",
                           "subscribed_events": ["label.verified"],
                       })
    deleted = (await wire.request(
        "DELETE", f"/v1/projects/{project_id}/webhooks/{endpoint_id}")).json()
    assert deleted["active"] is False and deleted["destination_version"] == 3
    replacement = await _endpoint(wire, project_id, suffix="replacement")
    assert replacement["active"] is True


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_webhook_admin_member_can_create(wire: Wire):
    project_id = await _project(wire)
    admin_key = await wire.factory.user("admin-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201, json={
        "member_tenant_id": "admin-tenant", "role": "admin",
    })
    response = await wire.request(
        "POST", f"/v1/projects/{project_id}/webhooks", status=201,
        headers={"X-Api-Key": admin_key}, json={
            "url": "https://hooks.example.test/admin",
            "subscribed_events": ["label.verified"],
        })
    assert response.json()["signing_secret"]


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_webhook_test_event_and_hourly_rate_limit(wire: Wire):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    path = f"/v1/projects/{project_id}/webhooks/{endpoint['id']}/test"
    for _ in range(10):
        result = await wire.request("POST", path, status=201)
        assert result.json()["event_id"] and result.json()["delivery_id"]
    await wire.request("POST", path, status=429)
    page = (await wire.request(
        "GET", f"/v1/projects/{project_id}/webhooks/{endpoint['id']}/deliveries",
        params={"limit": 3, "offset": 2})).json()
    assert page["total"] == 10 and page["limit"] == 3 and page["offset"] == 2
    assert len(page["items"]) == 3
    assert all("canonical_body" not in item for item in page["items"])
    async with wire.factory.sessions() as session:
        tests = await session.scalar(select(func.count()).select_from(WebhookEvent).where(
            WebhookEvent.project_id == UUID(project_id),
            WebhookEvent.event_type == "webhook.test"))
        deliveries = await session.scalar(select(func.count()).select_from(WebhookDelivery))
    assert tests == 10 and deliveries == 10


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_dispatch_records_attempt_and_delivers_exact_event(wire: Wire, monkeypatch, caplog):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id)
    observed: list[str] = []

    async def deliver(url: str, ciphertext: bytes, body: str, key_version: int) -> scheduler.DeliveryResult:
        observed.append(body)
        return scheduler.DeliveryResult(204, None)

    monkeypatch.setattr(scheduler, "_send_webhook", deliver)
    assert await scheduler.dispatch_webhooks_once() == 1
    async with wire.factory.sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == UUID(endpoint["id"]),
            WebhookDelivery.event_id == event_id))
        assert delivery is not None
        attempt = await session.get(WebhookAttempt, (delivery.id, 1))
        event = await session.get(WebhookEvent, event_id)
    assert event is not None and observed == [event.canonical_body]
    assert delivery.state == "delivered" and delivery.last_status == 204
    assert attempt is not None and attempt.outcome == "delivered" and attempt.http_status == 204
    assert "label_id" not in caplog.text and "L1" not in caplog.text


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_retry_schedule_then_dead(wire: Wire, monkeypatch):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id)
    monkeypatch.setattr(scheduler, "_send_webhook", AsyncMock(
        return_value=scheduler.DeliveryResult(500, "http_error")))
    expected_delays = (10, 60, 300)
    for attempt_no in range(1, 5):
        before = datetime.now(timezone.utc)
        assert await scheduler.dispatch_webhooks_once() == 1
        async with wire.factory.sessions.begin() as session:
            delivery = await session.scalar(select(WebhookDelivery).where(
                WebhookDelivery.endpoint_id == UUID(endpoint["id"]),
                WebhookDelivery.event_id == event_id).with_for_update())
            assert delivery is not None and delivery.attempts == attempt_no
            if attempt_no < 4:
                assert delivery.state == "pending" and delivery.next_attempt_at is not None
                due = delivery.next_attempt_at
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                delta = (due - before).total_seconds()
                assert expected_delays[attempt_no - 1] <= delta < expected_delays[attempt_no - 1] + 3
                delivery.next_attempt_at = before - timedelta(seconds=1)
            else:
                assert delivery.state == "dead" and delivery.next_attempt_at is None

    for permanent_status in (302, 400):
        permanent_event = await _event(wire, project_id, f"permanent-{permanent_status}")
        monkeypatch.setattr(scheduler, "_send_webhook", AsyncMock(
            return_value=scheduler.DeliveryResult(permanent_status, "http_error")))
        assert await scheduler.dispatch_webhooks_once() == 1
        async with wire.factory.sessions() as fresh:
            final = await fresh.scalar(select(WebhookDelivery).where(
                WebhookDelivery.event_id == permanent_event))
            assert final and final.state == "dead" and final.attempts == 1
    for retryable in (scheduler.DeliveryResult(408, "http_error"),
                      scheduler.DeliveryResult(429, "http_error"),
                      scheduler.DeliveryResult(None, "timeout"),
                      scheduler.DeliveryResult(None, "dns_error")):
        assert retryable.retryable


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_expired_lease_is_reclaimed(wire: Wire, monkeypatch):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id)
    old_token = uuid4()
    async with wire.factory.sessions.begin() as session:
        delivery = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event_id))
        assert delivery is not None
        delivery.state = "leased"
        delivery.lease_token = old_token
        delivery.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        row = await session.get(WebhookEndpoint, UUID(endpoint["id"]))
        assert row is not None
        row.lease_token = old_token
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(scheduler, "_send_webhook", AsyncMock(
        return_value=scheduler.DeliveryResult(200, None)))
    assert await scheduler.dispatch_webhooks_once() == 1
    async with wire.factory.sessions() as session:
        delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.event_id == event_id))
    assert delivery is not None and delivery.state == "delivered" and delivery.attempts == 1


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_worker_crash_after_fourth_attempt_never_sends_a_fifth(wire: Wire, monkeypatch):
    project = await _project(wire)
    await _endpoint(wire, project)
    await _event(wire, project)
    claim, = await scheduler._claim_webhook_deliveries()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    async with wire.factory.sessions.begin() as session:
        delivery = await session.get(WebhookDelivery, claim.delivery_id)
        target = await session.get(WebhookEndpoint, claim.endpoint_id)
        assert delivery and target
        delivery.attempts = 3
        delivery.lease_until = target.lease_until = past
        session.add(WebhookAttempt(delivery_id=delivery.id, attempt_no=4, started_at=past))
    sender = AsyncMock()
    monkeypatch.setattr(scheduler, "_send_webhook", sender)
    await scheduler._deliver_claim(claim)
    assert await scheduler.dispatch_webhooks_once() == 1
    sender.assert_not_awaited()
    async with wire.factory.sessions() as session:
        final = await session.get(WebhookDelivery, claim.delivery_id)
        assert final and final.state == "dead" and final.attempts == 4


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_rotation_cancels_old_version_and_new_event_uses_new_version(wire: Wire, monkeypatch):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    old_event = await _event(wire, project_id, "old")
    rotated = (await wire.request(
        "POST", f"/v1/projects/{project_id}/webhooks/{endpoint['id']}/rotate")).json()
    assert rotated["key_version"] == 2 and rotated["destination_version"] == 2
    assert rotated["signing_secret"] != endpoint["signing_secret"]
    new_event = await _event(wire, project_id, "new")
    monkeypatch.setattr(scheduler, "_send_webhook", AsyncMock(
        return_value=scheduler.DeliveryResult(200, None)))
    assert await scheduler.dispatch_webhooks_once() == 1
    async with wire.factory.sessions() as session:
        old = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.event_id == old_event))
        new = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.event_id == new_event))
    assert old is not None and old.state == "cancelled"
    assert new is not None and new.destination_version == 2 and new.state == "delivered"


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_signature_contract_and_two_workers_do_not_duplicate(wire: Wire, monkeypatch):
    body = '{"event_id":"known","schema_version":1}'
    timestamp = "1700000000"
    expected = hmac.new(b"known-secret", timestamp.encode() + b"." + body.encode(),
                        hashlib.sha256).hexdigest()
    assert signature("known-secret", timestamp, body) == expected

    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id)
    calls = 0

    async def slow_send(url: str, ciphertext: bytes, canonical_body: str, key_version: int) -> scheduler.DeliveryResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(.05)
        return scheduler.DeliveryResult(200, None)

    monkeypatch.setattr(scheduler, "_send_webhook", slow_send)
    counts = await asyncio.gather(
        scheduler.dispatch_webhooks_once(), scheduler.dispatch_webhooks_once())
    assert sum(counts) == 1 and calls == 1
    async with wire.factory.sessions() as session:
        total = await session.scalar(select(func.count()).select_from(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == UUID(endpoint["id"]),
            WebhookDelivery.event_id == event_id))
        attempts = await session.scalar(select(func.count()).select_from(WebhookAttempt))
    assert total == 1 and attempts == 1


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_send_uses_exact_body_and_signature_header(wire: Wire, monkeypatch):
    from webhook_security import encrypt_secret

    body = '{"data":{"unicode":"café"},"schema_version":1}'
    captured: dict[str, object] = {}

    class Response:
        status_code = 202

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class Client:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def stream(self, method, url, *, content, headers, extensions):
            assert url.host == "8.8.8.8" and extensions["sni_hostname"] == "hooks.example.test"
            captured.update(url=url, content=content, headers=headers)
            return Response()

    monkeypatch.setattr(scheduler.httpx, "AsyncClient", Client)
    monkeypatch.setattr(scheduler, "time", lambda: 1700000000)
    result = await scheduler._send_webhook(
        "https://hooks.example.test/exact", encrypt_secret("known-secret"), body, 2)
    expected = signature("known-secret", "1700000000", body)
    assert result == scheduler.DeliveryResult(202, None)
    assert captured["content"] == body.encode("utf-8")
    assert captured["headers"] == {
        "Paddle-Signature": f"ts=1700000000;h1={expected}",
        "Host": "hooks.example.test", "X-Webhook-Key-Version": "2",
        "Content-Type": "application/json",
    }
    assert captured["options"] == {"timeout": 10.0, "follow_redirects": False, "trust_env": False}


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_new_endpoint_does_not_backfill_old_events(wire: Wire, monkeypatch):
    project_id = await _project(wire)
    old_event = await _event(wire, project_id, "before-registration")
    endpoint = await _endpoint(wire, project_id)
    new_event = await _event(wire, project_id, "after-registration")
    monkeypatch.setattr(scheduler, "_send_webhook", AsyncMock(
        return_value=scheduler.DeliveryResult(200, None)))
    assert await scheduler.dispatch_webhooks_once() == 1
    async with wire.factory.sessions() as session:
        old_delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == UUID(endpoint["id"]),
            WebhookDelivery.event_id == old_event))
        new_delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.endpoint_id == UUID(endpoint["id"]),
            WebhookDelivery.event_id == new_event))
    assert old_delivery is None
    assert new_delivery is not None and new_delivery.state == "delivered"


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_destination_validation_rejects_non_https_and_private_addresses(monkeypatch):
    with pytest.raises(Exception) as insecure:
        await webhook_security.validate_public_https("http://example.test/hook")
    assert getattr(insecure.value, "status_code", None) == 422
    with pytest.raises(Exception) as private:
        await webhook_security.validate_public_https("https://127.0.0.1/hook")
    assert getattr(private.value, "status_code", None) == 422
    monkeypatch.setattr(webhook_security.asyncio, "to_thread", AsyncMock(return_value=[
        (2, 1, 6, "", ("8.8.8.8", 443)),
    ]))
    assert await webhook_security.validate_public_https(
        "https://hooks.example.test/path") == "8.8.8.8"


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_outbound_delivery_schema_matches_ledger(db_engine):
    def inspect_schema(connection):
        schema = inspect(connection)
        return {
            "tables": set(schema.get_table_names()),
            "endpoint": {column["name"]: column for column in schema.get_columns("webhook_endpoint")},
            "delivery": {column["name"]: column for column in schema.get_columns("webhook_delivery")},
            "indexes": {index["name"] for index in schema.get_indexes("webhook_delivery")},
            "uniques": {tuple(item["column_names"]) for item in schema.get_unique_constraints(
                "webhook_delivery")},
            "checks": " ".join(item["sqltext"] for item in schema.get_check_constraints(
                "webhook_delivery")),
            "attempt_pk": schema.get_pk_constraint("webhook_attempt")["constrained_columns"],
        }

    async with db_engine.connect() as connection:
        result = await connection.run_sync(inspect_schema)
    assert {"webhook_endpoint", "webhook_event", "webhook_delivery", "webhook_attempt"} <= result["tables"]
    assert result["endpoint"]["url"]["type"].length == 2048
    assert result["endpoint"]["secret_ciphertext"]["nullable"] is False
    assert result["delivery"]["destination_version"]["nullable"] is False
    assert {"ix_delivery_due", "ix_delivery_lease"} <= result["indexes"]
    assert ("endpoint_id", "event_id") in result["uniques"]
    assert all(state in result["checks"] for state in (
        "pending", "leased", "delivered", "dead", "cancelled"))
    assert result["attempt_pk"] == ["delivery_id", "attempt_no"]


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_claims_are_globally_bounded_to_four(wire: Wire):
    project_id = await _project(wire)
    endpoint_ids = [UUID((await _endpoint(wire, project_id, suffix=str(index)))["id"])
                    for index in range(5)]
    await _event(wire, project_id)
    first = await scheduler._claim_webhook_deliveries()
    second = await scheduler._claim_webhook_deliveries()
    assert len(first) == 4 and len({claim.endpoint_id for claim in first}) == 4
    assert second == []
    assert {claim.endpoint_id for claim in first} <= set(endpoint_ids)


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_retention_removes_webhook_children_before_project(wire: Wire):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id)
    async with wire.factory.sessions.begin() as session:
        delivery = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event_id))
        assert delivery is not None
        delivery.state = "dead"
        delivery.attempts = 1
        session.add(WebhookAttempt(
            delivery_id=delivery.id, attempt_no=1,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc), outcome="http_error", http_status=500))
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
        key.paddle_subscription_id = "sub_retention_webhook"
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WebhookAttempt)) == 0
        assert await session.scalar(select(func.count()).select_from(WebhookDelivery)) == 0
        assert await session.scalar(select(func.count()).select_from(WebhookEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(WebhookEndpoint)) == 0
        assert await session.scalar(select(func.count()).select_from(Domain).where(
            Domain.id == UUID(project_id))) == 0


@pytest.mark.prompt_e
@pytest.mark.anyio
async def test_terminal_history_prunes_after_thirty_days_without_redelivery(wire: Wire):
    project_id = await _project(wire)
    endpoint = await _endpoint(wire, project_id)
    event_id = await _event(wire, project_id, "old-terminal")
    dead_event_id = await _event(wire, project_id, "old-dead")
    old = datetime.now(timezone.utc) - timedelta(days=31)
    async with wire.factory.sessions.begin() as session:
        event = await session.get(WebhookEvent, event_id)
        dead_event = await session.get(WebhookEvent, dead_event_id)
        target = await session.get(WebhookEndpoint, UUID(endpoint["id"]))
        assert event is not None and dead_event is not None and target is not None
        target.created_at = old - timedelta(days=1)
        target.updated_at = old - timedelta(days=1)
        event.created_at = old
        dead_event.created_at = old
        delivery = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == event.id))
        assert delivery is not None
        delivery.state, delivery.attempts, delivery.delivered_at = "delivered", 1, old
        session.add(WebhookAttempt(
            delivery_id=delivery.id, attempt_no=1, started_at=old,
            finished_at=old, outcome="delivered", http_status=200))
        dead_delivery = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.event_id == dead_event.id))
        assert dead_delivery is not None
        dead_delivery.state, dead_delivery.attempts = "dead", 4
        session.add(WebhookAttempt(
            delivery_id=dead_delivery.id, attempt_no=4, started_at=old,
            finished_at=old, outcome="http_error", http_status=500))
    assert await scheduler.dispatch_webhooks_once() == 0
    async with wire.factory.sessions() as session:
        assert await session.get(WebhookEvent, event_id) is None
        assert await session.get(WebhookEvent, dead_event_id) is None
        assert await session.scalar(select(func.count()).select_from(WebhookDelivery)) == 0
        assert await session.scalar(select(func.count()).select_from(WebhookAttempt)) == 0
