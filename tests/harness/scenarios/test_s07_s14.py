import pytest
import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy import text

import billing
import account as account_module
from auth import scoped_domain_id
from db import migrate as db_migrate
import scheduler
import trial_guard
from db.tenant_lock import lock_tenant
from db.models import ConnectorConfigRow, Domain, ProjectRequest
from db.models import ApiKey, CheckoutIntent, LifecycleNotice, PaddleWebhookEvent, ProjectBillingOwner, ProviderRepairManifest, ProviderRepairQuarantine, SubscriptionBinding, TenantGuard, TransitionLog
from ..fixtures.factory import Wire


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s7_checkout_with_two_keys_and_existing_customer(wire: Wire, monkeypatch):
    """S7. Checkout with two keys and existing customer."""
    purchaser_key = await wire.factory.user()
    monkeypatch.setenv("PADDLE_API_KEY", "provider-test-key")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "professional=pri_test")
    await wire.request("GET", "/v1/billing/checkout-url?tier=professional", status=400,
                       headers={"X-Api-Key": purchaser_key})
    await wire.request("POST", "/v1/labels/ingest", status=409,
                       headers={"X-Api-Key": purchaser_key}, json={
                           "domain_id": "ambiguous", "label_id": "blocked-before-owner",
                           "category": "A", "factors": {"quality": .8, "difficulty": .2}})
    async with wire.factory.sessions.begin() as session:
        payer = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(wire.client.headers["x-api-key"].encode()).hexdigest()))
        purchaser = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(purchaser_key.encode()).hexdigest()))
        assert payer is not None and purchaser is not None
        payer.paddle_customer_id = "ctm-s7"
        session.add(TenantGuard(tenant_id=wire.factory.tenant))
        await session.flush()
        session.add(ProjectBillingOwner(owner_tenant_id=wire.factory.tenant,
                                        billing_key_id=payer.id, trial_started_at=payer.created_at))
    unsolicited = {"event_type": "subscription.created", "event_id": "evt-s7-no-intent",
                   "occurred_at": datetime.now(timezone.utc).isoformat(),
                   "data": {"id": "sub-unbound", "customer_id": "ctm-s7",
                            "transaction_id": "txn_s7unbound",
                            "custom_data": {"tenant_id": wire.factory.tenant,
                                            "key_id": str(purchaser.id)},
                            "items": [{"product": {"name": "DLJ Professional"}}]}}
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=unsolicited)
    captured: dict = {}
    def transact(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={"data": {"id": "txn_s7", "checkout": {
            "url": "https://example.test/pay?_ptxn=txn_s7"}}})
    monkeypatch.setattr(billing, "httpx", SimpleNamespace(
        AsyncClient=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(transact), **kw),
        HTTPError=httpx.HTTPError))
    result = await wire.request("GET", "/v1/billing/checkout-url?tier=professional",
                                headers={"X-Api-Key": purchaser_key})
    assert result.json()["checkout_url"].endswith("txn_s7")
    custom = captured["custom_data"]
    assert custom["key_id"] == str(purchaser.id)
    async with wire.factory.sessions() as fresh:
        intent = await fresh.get(CheckoutIntent, UUID(custom["checkout_intent_id"]))
        assert intent is not None and intent.payer == payer.id and intent.purchaser == purchaser.id
    event = {"event_type": "subscription.created", "event_id": "evt-s7",
             "occurred_at": datetime.now(timezone.utc).isoformat(),
             "data": {"id": "sub-s7", "customer_id": "ctm-s7", "transaction_id": "txn_s7", "custom_data": custom,
                      "items": [{"product": {"name": "DLJ Professional"}}]}}
    mismatched = json.loads(json.dumps(event))
    mismatched["event_id"] = "evt-s7-wrong-tier"
    mismatched["data"]["items"][0]["product"]["name"] = "DLJ Starter"
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       json=mismatched, omit_api_key=True)
    mismatched = json.loads(json.dumps(event))
    mismatched["event_id"] = "evt-s7-wrong-transaction"
    mismatched["data"]["transaction_id"] = "txn_other"
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       json=mismatched, omit_api_key=True)
    async with wire.factory.sessions() as fresh:
        unconsumed = await fresh.get(CheckoutIntent, UUID(custom["checkout_intent_id"]))
        assert unconsumed is not None and unconsumed.consumed_at is None
    await wire.request("POST", "/v1/billing/webhook", json=event, omit_api_key=True)
    async with wire.factory.sessions() as fresh:
        paid = await fresh.get(ApiKey, payer.id)
        unpaid = await fresh.get(ApiKey, purchaser.id)
        assert paid is not None and unpaid is not None
        assert paid.tier == "professional" and unpaid.tier == "trial"
    await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Payer project", "public_domain_id": "payer-project",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })
    await wire.request("POST", "/v1/labels/ingest", headers={"X-Api-Key": purchaser_key},
                       json={"domain_id": "payer-project", "label_id": "payer-score",
                             "category": "A", "factors": {"quality": .8, "difficulty": .2}})
    async with wire.factory.sessions() as fresh:
        paid = await fresh.get(ApiKey, payer.id)
        unpaid = await fresh.get(ApiKey, purchaser.id)
        assert paid is not None and unpaid is not None
        assert paid.labels_today == 1 and unpaid.labels_today == 0
    async with wire.factory.sessions.begin() as session:
        paid = await session.get(ApiKey, payer.id)
        assert paid is not None
        paid.subscription_state = "past_due"
    sibling_summary = await wire.request("GET", "/v1/account",
                                         headers={"X-Api-Key": purchaser_key})
    assert sibling_summary.json()["subscription_state"] == "past_due"
    assert sibling_summary.json()["usage"]["monthly_cap"] == 0
    await wire.request("POST", "/v1/labels/ingest", status=402,
                       headers={"X-Api-Key": purchaser_key}, json={
                           "domain_id": "payer-project", "label_id": "blocked-sibling",
                           "category": "A", "factors": {"quality": .8, "difficulty": .2}})
    await wire.request("POST", "/v1/label-studio/webhook", status=402,
                       headers={"X-Api-Key": purchaser_key, "X-LS-Token": "harness-ls"},
                       json={"action": "ANNOTATION_CREATED", "project": "p",
                             "annotation": {"id": "1", "actual_action": "approve"},
                             "task": {"id": "1", "data": {"category": "A"}}})


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s8_status_sequence_including_past_due_pause_resume_and_replaced_subscription(wire: Wire):
    """S8. Status sequence including past due, pause, resume and replaced subscription."""
    start = datetime.now(timezone.utc)
    sequence = (("created", "active"), ("updated", "past_due"),
                ("updated", "paused"), ("updated", "active"),
                ("canceled", "cancelled"))
    for index, (kind, state) in enumerate(sequence):
        event: dict[str, Any] = {"event_type": f"subscription.{kind}", "event_id": f"evt-s8-{index}",
                 "occurred_at": (start + timedelta(seconds=index)).isoformat(),
                 "data": {"id": "sub-s8", "status": state, "customer_id": "ctm-s8",
                          "custom_data": {"tenant_id": wire.factory.tenant},
                          "items": [{"product": {"name": "DLJ Professional"}}]}}
        if kind == "created":
            event["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s8initial")
            event["data"]["transaction_id"] = "txn_s8initial"
        await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=event)
        summary = await wire.request("GET", "/v1/account")
        assert summary.json()["subscription_state"] == state
        async with wire.factory.sessions() as fresh:
            current = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
            assert current is not None and current.subscription_state == state
            log = await fresh.get(TransitionLog, event["event_id"])
            assert log is not None and log.new_state == state
        scored = await wire.client.post("/v1/labels/ingest", json={
            "domain_id": "s8", "label_id": f"item-{index}", "category": "A",
            "factors": {"quality": .8, "difficulty": .2}})
        assert scored.status_code == (402 if state in {"past_due", "paused"} else 200)
    invalid_resume = {"event_type": "subscription.updated", "event_id": "evt-s8-invalid-resume",
                      "occurred_at": (start + timedelta(seconds=5)).isoformat(),
                      "data": {"id": "sub-s8", "status": "active", "customer_id": "ctm-s8",
                               "items": [{"product": {"name": "DLJ Professional"}}]}}
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=invalid_resume)
    assert (await wire.request("GET", "/v1/account")).json()["subscription_state"] == "cancelled"
    replacement: dict[str, Any] = {"event_type": "subscription.created", "event_id": "evt-s8-replacement",
                   "occurred_at": (start + timedelta(seconds=6)).isoformat(),
                   "data": {"id": "sub-s8-new", "status": "active", "customer_id": "ctm-s8",
                            "custom_data": {"tenant_id": wire.factory.tenant},
                            "items": [{"product": {"name": "DLJ Professional"}}]}}
    replacement["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s8replacement")
    replacement["data"]["transaction_id"] = "txn_s8replacement"
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=replacement)
    late_retired = {**invalid_resume, "event_id": "evt-s8-retired",
                    "occurred_at": (start + timedelta(seconds=7)).isoformat()}
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=late_retired)
    async with wire.factory.sessions() as fresh:
        previous = await fresh.get(SubscriptionBinding, "sub-s8")
        replacement_binding = await fresh.get(SubscriptionBinding, "sub-s8-new")
        assert previous is not None and previous.retired_at is not None
        assert replacement_binding is not None and replacement_binding.retired_at is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s9_unknown_duplicate_and_delayed_events_amid_cancellation(wire: Wire):
    """S9. Unknown, duplicate and delayed events amid cancellation."""
    start = datetime.now(timezone.utc)
    def event(kind: str, sequence: int, status: str) -> dict:
        return {"event_type": f"subscription.{kind}", "event_id": f"evt-s9-{sequence}",
                "occurred_at": (start + timedelta(seconds=sequence)).isoformat(),
                "data": {"id": "sub-s9", "status": status, "customer_id": "ctm-s9",
                         "custom_data": {"tenant_id": wire.factory.tenant},
                         "items": [{"product": {"name": "DLJ Professional"}}]}}
    created = event("created", 1, "active")
    created["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s9initial")
    created["data"]["transaction_id"] = "txn_s9initial"
    cancelled = event("canceled", 3, "canceled")
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=created)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=cancelled)
    unknown = event("unknown", 4, "active")
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True,
                       json=unknown)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True,
                       json=unknown)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True,
                       json=event("updated", 2, "active"))
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=cancelled)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "cancelled" and key.state_version == 2
        assert key.paddle_event_occurred_at is not None
        assert key.paddle_event_occurred_at.replace(tzinfo=timezone.utc) == start + timedelta(seconds=3)
        dispositions = (await fresh.scalars(select(TransitionLog.disposition))).all()
        assert sorted(dispositions) == ["applied", "applied", "duplicate", "rejected", "rejected", "stale"]
        notices = (await fresh.scalars(select(LifecycleNotice.kind))).all()
        assert sorted(notices) == ["cancellation_scheduled", "entitlement_changed"]
        assert await fresh.get(PaddleWebhookEvent, "evt-s9-4") is None
    restored = event("created", 5, "active")
    restored["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s9restored")
    restored["data"]["transaction_id"] = "txn_s9restored"
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=restored)
    restored["data"]["id"] = "sub-s9-replacement"
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=restored)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "active"
        assert key.paddle_event_id == "evt-s9-5"
    premature = event("updated", 7, "past_due")
    premature["event_id"] = "evt-s9-future-update"
    premature["data"]["id"] = "sub-s9-future"
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=premature)
    future = event("created", 6, "active")
    future["data"]["id"] = "sub-s9-future"
    future["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s9future")
    future["data"]["transaction_id"] = "txn_s9future"
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=future)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=premature)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=premature)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "past_due"
        applied = (await fresh.scalars(select(TransitionLog).where(
            TransitionLog.event_id == premature["event_id"]))).all()
        retry_notices = (await fresh.scalars(select(LifecycleNotice).where(
            LifecycleNotice.event_id == premature["event_id"]))).all()
        assert len(applied) == len(retry_notices) == 1
    equal_older = event("updated", 7, "paused")
    equal_older["event_id"] = "evt-s9-aa"
    equal_older["data"]["id"] = "sub-s9-future"
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=equal_older)
    equal_newer = event("updated", 7, "active")
    equal_newer["event_id"] = "evt-s9-zz"
    equal_newer["data"]["id"] = "sub-s9-future"
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=equal_newer)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "active"
        assert key.paddle_event_id == "evt-s9-zz"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s10_cleanup_versus_reactivation_on_separate_connections(wire: Wire, monkeypatch, db_engine):
    """S10. Cleanup versus reactivation on separate connections."""
    domain = await wire.factory.domain("retained")
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
        key_id = key.id
    at_guard = asyncio.Event()
    original_lock = scheduler.lock_tenant

    async def observed_lock(session, tenant_id):
        at_guard.set()
        await original_lock(session, tenant_id)

    monkeypatch.setattr(scheduler, "lock_tenant", observed_lock)
    async with wire.factory.sessions.begin() as renewal:
        await lock_tenant(renewal, wire.factory.tenant)
        key = await renewal.get(ApiKey, key_id, with_for_update=True)
        assert key is not None
        task = asyncio.create_task(scheduler.cleanup_cancelled_tenants())
        await asyncio.wait_for(at_guard.wait(), 5)
        key.subscription_state = "active"
        key.cancelled_at = None
        key.state_version += 1
    assert await asyncio.wait_for(task, 5) == 0
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is not None
        record = await fresh.get(ApiKey, key_id)
        assert record is not None and record.subscription_state == "active"

    async with wire.factory.sessions.begin() as session:
        key = await session.get(ApiKey, key_id)
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
    renewal_event: dict[str, Any] = {"event_type": "subscription.created", "event_id": "evt-s10-renewal",
                     "occurred_at": datetime.now(timezone.utc).isoformat(),
                     "data": {"id": "sub-s10-renewed", "status": "active",
                              "customer_id": "ctm-s10", "custom_data": {"tenant_id": wire.factory.tenant},
                              "items": [{"product": {"name": "DLJ Professional"}}]}}
    renewal_event["data"]["custom_data"] = await wire.paddle_intent("professional", "txn_s10renewal")
    renewal_event["data"]["transaction_id"] = "txn_s10renewal"
    monkeypatch.setattr(scheduler, "lock_tenant", original_lock)
    original_billing_lock = billing.lock_tenant
    if db_engine.dialect.name == "postgresql":
        renewal_has_guard = asyncio.Event()
        release_renewal = asyncio.Event()
        async def paused_renewal_lock(session, tenant_id):
            await original_billing_lock(session, tenant_id)
            renewal_has_guard.set()
            await asyncio.wait_for(release_renewal.wait(), 5)
        monkeypatch.setattr(billing, "lock_tenant", paused_renewal_lock)
        renewal_task = asyncio.create_task(wire.request(
            "POST", "/v1/billing/webhook", omit_api_key=True, json=renewal_event))
        await asyncio.wait_for(renewal_has_guard.wait(), 5)
        at_guard.clear()
        monkeypatch.setattr(scheduler, "lock_tenant", observed_lock)
        cleanup_after_renewal = asyncio.create_task(scheduler.cleanup_cancelled_tenants())
        await asyncio.wait_for(at_guard.wait(), 5)
        assert not cleanup_after_renewal.done(), "Cleanup did not wait for provider renewal guard"
        release_renewal.set()
        await asyncio.wait_for(renewal_task, 5)
        assert await asyncio.wait_for(cleanup_after_renewal, 5) == 0
        monkeypatch.setattr(billing, "lock_tenant", original_billing_lock)
        monkeypatch.setattr(scheduler, "lock_tenant", original_lock)
    else:
        await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=renewal_event)
        assert await scheduler.cleanup_cancelled_tenants() == 0
    async with wire.factory.sessions() as fresh:
        record = await fresh.get(ApiKey, key_id)
        assert record is not None and record.subscription_state == "active"
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is not None

        applied = await fresh.get(TransitionLog, "evt-s10-renewal")
        assert applied is not None and applied.disposition == "applied" and applied.key_id == key_id
        assert await fresh.scalar(select(CheckoutIntent.consumed_at).where(
            CheckoutIntent.transaction_id == "txn_s10renewal")) is not None

    # In the opposite commit order, cleanup wins and key issuance sees a tombstone.
    async with wire.factory.sessions.begin() as session:
        key = await session.get(ApiKey, key_id)
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
        session.add(CheckoutIntent(id=uuid4(), tenant_id=wire.factory.tenant,
                                   purchaser=key_id, payer=key_id, tier="professional",
                                   expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)))
    assert await scheduler.cleanup_cancelled_tenants() == 0
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is not None
    async with wire.factory.sessions.begin() as session:
        intent = await session.scalar(select(CheckoutIntent).where(
            CheckoutIntent.tenant_id == wire.factory.tenant,
            CheckoutIntent.consumed_at.is_(None)))
        assert intent is not None
        intent.consumed_at = datetime.now(timezone.utc)
    assert await scheduler.cleanup_cancelled_tenants() == 1
    await wire.request("POST", "/v1/admin/api-keys", status=409,
                       headers={"X-Admin-Key": "harness-admin"}, json={
                           "tenant_id": wire.factory.tenant, "tenant_name": "Revived",
                       })
    late_renewal = {**renewal_event, "event_id": "evt-s10-after-cleanup",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "data": {**renewal_event["data"], "id": "sub-s10-too-late"}}
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=late_renewal)
    async with wire.factory.sessions() as fresh:
        record = await fresh.get(ApiKey, key_id)
        assert record is not None and record.subscription_state == "cleaned_up"
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is None

    # Cleanup-first: a signed late purchase delivery blocks on the same
    # tenant guard, then observes the terminal payer and cannot revive it.
    await wire.factory.user("cleanup-first-provider")
    terminal_domain = scoped_domain_id("cleanup-first-provider", "cleanup-first-data")
    async with wire.factory.sessions.begin() as session:
        terminal = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == "cleanup-first-provider"))
        assert terminal is not None
        terminal.subscription_state = "cancelled"
        terminal.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
        terminal.tier = "professional"
        terminal.paddle_customer_id = "ctm-s10-terminal"
        terminal.paddle_subscription_id = "sub-s10-terminal"
        terminal_id = terminal.id
        session.add(Domain(
            domain_id=terminal_domain, public_domain_id="cleanup-first-data",
            tenant_id="cleanup-first-provider", domain_name="cleanup-first-data",
            config_json={"domain_id": terminal_domain, "domain_name": "cleanup-first-data",
                         "factors": ["quality", "difficulty"], "categories": ["A", "B"],
                         "actions": ["approve", "reject"]}))
        # Payment was initiated before expiry. Delivery arrives after the
        # intent's hold lapses, when retention is allowed to win the guard.
        terminal_intent = uuid4()
        session.add(CheckoutIntent(id=terminal_intent, tenant_id=terminal.tenant_id,
                                   purchaser=terminal.id, payer=terminal.id, tier="professional",
                                   transaction_id="txn_s10terminal",
                                   expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    cleanup_has_guard = asyncio.Event()
    release_cleanup = asyncio.Event()
    async def paused_cleanup_lock(session, tenant_id):
        await original_lock(session, tenant_id)
        if tenant_id == "cleanup-first-provider":
            cleanup_has_guard.set()
            await asyncio.wait_for(release_cleanup.wait(), 5)
    monkeypatch.setattr(scheduler, "lock_tenant", paused_cleanup_lock)
    terminal_event = {
        "event_type": "subscription.created", "event_id": "evt-s10-terminal-reconcile",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {"id": "sub-s10-new", "status": "active",
                 "custom_data": {"tenant_id": "cleanup-first-provider", "key_id": str(terminal_id),
                                 "checkout_intent_id": str(terminal_intent)},
                 "customer_id": "ctm-s10-terminal", "transaction_id": "txn_s10terminal",
                 "items": [{"product": {"name": "DLJ Professional"}}]},
    }
    if db_engine.dialect.name == "postgresql":
        terminal_cleanup = asyncio.create_task(scheduler.cleanup_cancelled_tenants())
        await asyncio.wait_for(cleanup_has_guard.wait(), 5)
        billing_at_guard = asyncio.Event()
        async def arriving_renewal(session, tenant_id):
            billing_at_guard.set()
            await original_billing_lock(session, tenant_id)
        monkeypatch.setattr(billing, "lock_tenant", arriving_renewal)
        terminal_renewal = asyncio.create_task(wire.request(
            "POST", "/v1/billing/webhook", status=409,
            omit_api_key=True, json=terminal_event))
        await asyncio.wait_for(billing_at_guard.wait(), 5)
        assert not terminal_renewal.done(), "Renewal did not wait for cleanup tenant guard"
        release_cleanup.set()
        assert await asyncio.wait_for(terminal_cleanup, 5) == 1
        await asyncio.wait_for(terminal_renewal, 5)
    else:
        release_cleanup.set()
        assert await scheduler.cleanup_cancelled_tenants() == 1
        await wire.request("POST", "/v1/billing/webhook", status=409,
                           omit_api_key=True, json=terminal_event)
    async with wire.factory.sessions() as fresh:
        terminal = await fresh.get(ApiKey, terminal_id)
        assert terminal is not None and terminal.subscription_state == "cleaned_up"
        assert await fresh.scalar(select(Domain).where(
            Domain.domain_id == terminal_domain)) is None
        retention = await fresh.scalar(select(TransitionLog.event_id).where(
            TransitionLog.key_id == terminal_id,
            TransitionLog.reason_code == "retention_elapsed"))
        assert retention is not None
        rejection = await fresh.scalar(select(TransitionLog).where(
            TransitionLog.actor_ref == terminal_event["event_id"],
            TransitionLog.disposition == "rejected"))
        assert rejection is not None and rejection.reason_code == "purchase_after_retention"
        unused = await fresh.get(CheckoutIntent, terminal_intent)
        assert unused is not None and unused.consumed_at is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s11_key_creation_and_rotation_during_cleanup(wire: Wire, monkeypatch):
    """S11. Key creation and rotation during cleanup."""
    domain = await wire.factory.domain("cleanup-race")
    old = datetime.now(timezone.utc) - timedelta(days=31)
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = old
        old_key_id = key.id
    cleanup_locked = asyncio.Event()
    release_cleanup = asyncio.Event()
    original_lock = scheduler.lock_tenant

    async def paused_lock(session, tenant_id):
        await original_lock(session, tenant_id)
        cleanup_locked.set()
        await asyncio.wait_for(release_cleanup.wait(), 5)

    monkeypatch.setattr(scheduler, "lock_tenant", paused_lock)
    cleanup = asyncio.create_task(scheduler.cleanup_cancelled_tenants())
    await asyncio.wait_for(cleanup_locked.wait(), 5)
    issue = asyncio.create_task(wire.client.post("/v1/admin/api-keys",
        headers={"X-Admin-Key": "harness-admin"},
        json={"tenant_id": wire.factory.tenant, "tenant_name": "New sibling"}))
    rotation = asyncio.create_task(wire.client.post(
        f"/v1/admin/api-keys/{old_key_id}/rotate",
        headers={"X-Admin-Key": "harness-admin"}))
    await asyncio.sleep(.05)
    assert not issue.done(), "Sibling issuance did not wait for tenant cleanup lock"
    assert not rotation.done(), "Key rotation did not wait for tenant cleanup lock"
    release_cleanup.set()
    assert await asyncio.wait_for(cleanup, 5) == 1
    response = await asyncio.wait_for(issue, 5)
    assert response.status_code == 409
    assert (await asyncio.wait_for(rotation, 5)).status_code == 409
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is None
        rows = (await fresh.scalars(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))).all()
        assert len(rows) == 1 and rows[0].subscription_state == "cleaned_up"

    # Issuance-first is the opposite commit order: the new sibling preserves data.
    first_key = await wire.factory.user("issuance-first")
    project = (await wire.request("POST", "/v1/projects", status=201,
                                  headers={"X-Api-Key": first_key}, json={
                                      "name": "Retained", "public_domain_id": "issued-first",
                                      "factors": ["quality", "difficulty"], "categories": ["A"],
                                  })).json()["id"]
    async with wire.factory.sessions.begin() as session:
        old_key = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == "issuance-first"))
        assert old_key is not None
        old_key.subscription_state = "cancelled"
        old_key.cancelled_at = old
    issued = await wire.request("POST", "/v1/admin/api-keys", json={
        "tenant_id": "issuance-first", "tenant_name": "Fresh sibling"},
        headers={"X-Admin-Key": "harness-admin"})
    assert issued.json()["api_key"] != first_key
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        new_key = await fresh.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(issued.json()["api_key"].encode()).hexdigest()))
        assert new_key is not None
        new_key_id = new_key.id
    rotated = await wire.request("POST", f"/v1/admin/api-keys/{new_key_id}/rotate",
                                 headers={"X-Admin-Key": "harness-admin"})
    assert rotated.json()["api_key"] != issued.json()["api_key"]
    await wire.request("GET", "/v1/account", status=401,
                       headers={"X-Api-Key": issued.json()["api_key"]})
    await wire.request("GET", "/v1/account",
                       headers={"X-Api-Key": rotated.json()["api_key"]})
    await wire.request("POST", "/v1/projects", status=201,
                       headers={"X-Api-Key": rotated.json()["api_key"]}, json={
                           "name": "Continued work", "public_domain_id": "post-cleanup",
                           "factors": ["quality", "difficulty"], "categories": ["A"],
                       })
    async with wire.factory.sessions() as fresh:
        assert await fresh.get(Domain, UUID(project)) is not None
        keys = (await fresh.scalars(select(ApiKey).where(
            ApiKey.tenant_id == "issuance-first"))).all()
        assert len(keys) == 2 and {key.subscription_state for key in keys} == {"cleaned_up", "trial"}


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s12_two_old_cancelled_siblings_versus_one_entitled_sibling(wire: Wire, db_engine, monkeypatch):
    """S12. Two old cancelled siblings versus one entitled sibling."""
    domain = await wire.factory.domain("sibling-data")
    await wire.factory.user()
    entitled_key = await wire.factory.user()
    cutoff = datetime.now(timezone.utc) - timedelta(days=31)
    async with wire.factory.sessions.begin() as session:
        keys = (await session.scalars(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant).order_by(ApiKey.id))).all()
        assert len(keys) == 3
        active_hash = hashlib.sha256(entitled_key.encode()).hexdigest()
        entitled = next(key for key in keys if key.key_hash == active_hash)
        old_owner = next(key for key in keys if key.id != entitled.id)
        project_id = await session.scalar(select(Domain.id).where(Domain.domain_id == domain))
        session.add(ProjectRequest(project_id=project_id, actor_key_id=old_owner.id, operation="import_batch",
                                   request_key="prior", payload_digest="0" * 64, result_json={},
                                   expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        session.add(ConnectorConfigRow(tenant_id=wire.factory.tenant, project_id="studio", config_json={}))
        session.add(TenantGuard(tenant_id=wire.factory.tenant))
        await session.flush()
        session.add(ProjectBillingOwner(owner_tenant_id=wire.factory.tenant,
                                        billing_key_id=old_owner.id,
                                        trial_started_at=old_owner.created_at))
        for key in keys:
            if key.id != entitled.id:
                key.subscription_state = "cancelled"
                key.cancelled_at = cutoff
            else:
                key.subscription_state = None  # Upgrade-era paid row without lifecycle backfill.
                key.tier = "professional"
                key.is_active = False
                key.reproof_required = True
    if db_engine.dialect.name == "postgresql":
        both_at_guard = asyncio.Event()
        guard_attempts = 0
        original_lock = scheduler.lock_tenant
        async def witnessed_lock(session, tenant_id):
            nonlocal guard_attempts
            guard_attempts += 1
            if guard_attempts == 2:
                both_at_guard.set()
            await asyncio.wait_for(both_at_guard.wait(), 5)
            await original_lock(session, tenant_id)
        monkeypatch.setattr(scheduler, "lock_tenant", witnessed_lock)
        counts = await asyncio.gather(scheduler.cleanup_cancelled_tenants(),
                                      scheduler.cleanup_cancelled_tenants())
        assert guard_attempts >= 2
        monkeypatch.setattr(scheduler, "lock_tenant", original_lock)
        assert sorted(counts) == [0, 2]
    else:
        assert await scheduler.cleanup_cancelled_tenants() == 2
    assert await scheduler.cleanup_cancelled_tenants() == 0
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is not None
        assert await fresh.scalar(select(ProjectRequest).where(ProjectRequest.project_id == project_id)) is not None
        assert await fresh.get(ConnectorConfigRow, (wire.factory.tenant, "studio")) is not None
        keys = (await fresh.scalars(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))).all()
        assert sum(key.is_active for key in keys) == 0
        assert next(key for key in keys if key.id == entitled.id).subscription_state is None
        owner = await fresh.get(ProjectBillingOwner, wire.factory.tenant)
        assert owner is not None and owner.billing_key_id == entitled.id
        assert await fresh.scalar(select(func.count()).select_from(TransitionLog).where(
            TransitionLog.source == "scheduler", TransitionLog.new_state == "cleaned_up")) == 2
        assert await fresh.scalar(select(TransitionLog.reason_code).where(
            TransitionLog.source == "scheduler", TransitionLog.new_state == "cleaned_up")) == "retention_elapsed"
    async with wire.factory.sessions.begin() as session:
        recovered = await session.get(ApiKey, entitled.id)
        assert recovered is not None
        recovered.is_active = True
        recovered.reproof_required = False
    assert (await wire.request("GET", "/v1/account",
                               headers={"X-Api-Key": entitled_key})).json()["subscription_state"] == "active"
    async with wire.factory.sessions.begin() as session:
        recovered = await session.get(ApiKey, entitled.id)
        assert recovered is not None
        recovered.subscription_state = "cancelled"
        recovered.cancelled_at = cutoff
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == domain)) is None
        assert await fresh.scalar(select(ProjectRequest).where(ProjectRequest.project_id == project_id)) is None
        assert await fresh.get(ConnectorConfigRow, (wire.factory.tenant, "studio")) is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s13_historical_postgresql_provider_upgrade_twice_sqlite_advisory(wire: Wire, db_engine, monkeypatch):
    """S13. Historical PostgreSQL provider upgrade twice (SQLite advisory)."""
    ambiguous_key = await wire.factory.user("ambiguous-tenant")
    await wire.factory.user("ambiguous-tenant")
    legacy_key = await wire.factory.user("legacy-tenant")
    conflict_key = await wire.factory.user("conflict-tenant")
    async with wire.factory.sessions.begin() as session:
        confirmed = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        ambiguous = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(ambiguous_key.encode()).hexdigest()))
        legacy = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(legacy_key.encode()).hexdigest()))
        conflict = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(conflict_key.encode()).hexdigest()))
        assert confirmed is not None and ambiguous is not None and legacy is not None and conflict is not None
        confirmed.paddle_customer_id = "ctm_confirmed"
        confirmed.paddle_subscription_id = "sub_confirmed"
        confirmed.labels_day_key = "2026-11-25"
        confirmed.labels_today = 11
        confirmed.labels_month_key = "2026-11"
        confirmed.labels_this_month = 321
        ambiguous.paddle_customer_id = "ctm_ambiguous"
        ambiguous.paddle_subscription_id = "sub_ambiguous"
        conflict.paddle_customer_id = "ctm_conflict"
        conflict.paddle_subscription_id = "sub_conflict"
        session.add(SubscriptionBinding(subscription_id="sub_existing", payer=conflict.id,
                                        customer_id="ctm_conflict"))
        confirmed_id, ambiguous_id, legacy_id, conflict_id = confirmed.id, ambiguous.id, legacy.id, conflict.id
    async with db_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE api_keys ADD COLUMN lemon_squeezy_customer_id VARCHAR(200)"))
        await connection.execute(text("UPDATE api_keys SET lemon_squeezy_customer_id='legacy_123' WHERE id=:id"),
                                 {"id": legacy_id.hex})
    monkeypatch.setattr(db_migrate, "engine", db_engine)
    await db_migrate.migrate()
    await db_migrate.migrate()
    async with wire.factory.sessions() as fresh:
        confirmed = await fresh.get(ApiKey, confirmed_id)
        manifest = await fresh.get(ProviderRepairManifest, confirmed_id)
        binding = await fresh.get(SubscriptionBinding, "sub_confirmed")
        owner = await fresh.get(ProjectBillingOwner, wire.factory.tenant)
        quarantined = await fresh.get(ProviderRepairQuarantine, ambiguous_id)
        legacy_quarantine = await fresh.get(ProviderRepairQuarantine, legacy_id)
        conflict_quarantine = await fresh.get(ProviderRepairQuarantine, conflict_id)
        legacy = await fresh.get(ApiKey, legacy_id)
        assert confirmed is not None and manifest is not None and binding is not None and owner is not None
        assert confirmed.paddle_customer_id == "ctm_confirmed"
        assert binding.payer == confirmed_id and owner.billing_key_id == confirmed_id
        assert (manifest.labels_today, manifest.labels_this_month) == (11, 321)
        assert (confirmed.labels_today, confirmed.labels_this_month) == (11, 321)
        assert quarantined is not None and quarantined.reason_code == "ambiguous_payer"
        assert legacy_quarantine is not None and legacy_quarantine.reason_code == "legacy_provider_unmapped"
        assert conflict_quarantine is not None and conflict_quarantine.reason_code == "current_binding_conflict"
        assert legacy is not None and legacy.paddle_customer_id is None
        assert await fresh.scalar(select(func.count()).select_from(ProviderRepairManifest)) == 1
    async with db_engine.connect() as connection:
        legacy_value = await connection.scalar(text(
            "SELECT lemon_squeezy_customer_id FROM api_keys WHERE id=:id"), {"id": legacy_id.hex})
        assert legacy_value == "legacy_123"
    monkeypatch.setenv("PADDLE_API_KEY", "provider-test-key")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "starter=pri_test")
    await wire.request("GET", "/v1/billing/checkout-url?tier=starter", status=409,
                       headers={"X-Api-Key": ambiguous_key})
    await wire.request("GET", "/v1/billing/checkout-url?tier=starter", status=409,
                       headers={"X-Api-Key": legacy_key})
    async with db_engine.begin() as connection:
        assert await connection.run_sync(lambda sync: db_migrate.undo_provider_link(sync, confirmed_id))
    async with wire.factory.sessions() as fresh:
        assert await fresh.get(ProviderRepairManifest, confirmed_id) is None
        assert await fresh.get(SubscriptionBinding, "sub_confirmed") is None
    await db_migrate.migrate()
    async with wire.factory.sessions.begin() as session:
        owner = await session.get(ProjectBillingOwner, wire.factory.tenant)
        assert owner is not None
        original_trial_start = owner.trial_started_at
        owner.trial_started_at = original_trial_start + timedelta(seconds=1)
    async with db_engine.begin() as connection:
        with pytest.raises(ValueError, match="manual reconciliation"):
            await connection.run_sync(lambda sync: db_migrate.undo_provider_link(sync, confirmed_id))
    async with wire.factory.sessions.begin() as session:
        owner = await session.get(ProjectBillingOwner, wire.factory.tenant)
        assert owner is not None
        owner.trial_started_at = original_trial_start
        binding = await session.get(SubscriptionBinding, "sub_confirmed")
        assert binding is not None
        binding.retired_at = datetime.now(timezone.utc)
    async with db_engine.begin() as connection:
        with pytest.raises(ValueError, match="manual reconciliation"):
            await connection.run_sync(lambda sync: db_migrate.undo_provider_link(sync, confirmed_id))
    async with wire.factory.sessions.begin() as session:
        binding = await session.get(SubscriptionBinding, "sub_confirmed")
        assert binding is not None
        binding.retired_at = None
    async with wire.factory.sessions.begin() as session:
        confirmed = await session.get(ApiKey, confirmed_id)
        assert confirmed is not None
        confirmed.labels_today += 1
    async with db_engine.begin() as connection:
        with pytest.raises(ValueError, match="manual reconciliation"):
            await connection.run_sync(lambda sync: db_migrate.undo_provider_link(sync, confirmed_id))


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_s14_cancelled_paid_utc_day_and_month_boundaries(wire: Wire, monkeypatch):
    """S14. Cancelled/paid UTC day and month boundaries."""
    clock = {"now": datetime(2026, 11, 25, 23, 59, tzinfo=timezone.utc)}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"].astimezone(tz or timezone.utc)

    monkeypatch.setattr(trial_guard, "datetime", FrozenDateTime)
    monkeypatch.setattr(account_module, "datetime", FrozenDateTime)
    async with wire.factory.sessions.begin() as session:
        cancelled = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert cancelled is not None
        cancelled.tier = "professional"
        cancelled.subscription_state = "cancelled"
        cancelled.cancelled_at = clock["now"] - timedelta(days=1)
        cancelled.labels_day_key = "2026-11-25"
        cancelled.labels_today = 49
        cancelled.labels_month_key = "2026-11"
        cancelled.labels_this_month = 400

    async def score(key: str | None, name: str, expected: int) -> None:
        headers = {"X-Api-Key": key} if key else None
        response = await wire.client.post("/v1/labels/ingest", headers=headers, json={
            "domain_id": "boundary", "label_id": name, "category": "A",
            "factors": {"quality": .8, "difficulty": .2},
        })
        assert response.status_code == expected, response.text

    await score(None, "cancelled-last", 200)
    await score(None, "cancelled-over", 429)
    summary = await wire.request("GET", "/v1/account")
    assert summary.json()["usage"]["labels_today"] == 50
    assert summary.json()["usage"]["daily_cap"] == 50
    clock["now"] = datetime(2026, 11, 26, 0, 1, tzinfo=timezone.utc)
    await score(None, "cancelled-new-day", 200)
    assert (await wire.request("GET", "/v1/account")).json()["usage"]["labels_today"] == 1

    paid_key = await wire.factory.user("paid-tenant")
    async with wire.factory.sessions.begin() as session:
        paid = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(paid_key.encode()).hexdigest()))
        assert paid is not None
        paid.tier = "starter"
        paid.subscription_state = "active"
        paid.labels_month_key = "2026-11"
        paid.labels_this_month = 9_999
    clock["now"] = datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)
    await score(paid_key, "paid-last", 200)
    await score(paid_key, "paid-over", 429)
    paid_summary = await wire.request("GET", "/v1/account", headers={"X-Api-Key": paid_key})
    assert paid_summary.json()["usage"]["labels_this_month"] == 10_000
    assert paid_summary.json()["usage"]["monthly_cap"] == 10_000
    clock["now"] = datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)
    await score(paid_key, "paid-new-month", 200)
    paid_summary = await wire.request("GET", "/v1/account", headers={"X-Api-Key": paid_key})
    assert paid_summary.json()["usage"]["labels_this_month"] == 1
