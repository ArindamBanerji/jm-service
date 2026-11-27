"""Focused R2 regressions at authenticated HTTP and committed DB boundaries."""
import hashlib
import asyncio
import re
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, select, text

from db.connection import normalize_database_url
from db import migrate as db_migrate
from db.models import (ApiKey, CheckoutIntent, Domain, LabelLog, LifecycleNotice, ProjectInvite, ProjectMember,
                       PaddleWebhookEvent, ProviderRepairManifest, ProviderRepairQuarantine,
                       SubscriptionBinding, TransitionLog)
import scheduler
import projects_router
import billing
import auth
from db.tenant_lock import lock_tenant
from .fixtures.factory import Wire


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_member_role_is_rechecked_after_tenant_lock(wire: Wire, monkeypatch):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Role race", "public_domain_id": "role-race",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })).json()["id"]
    member_key = await wire.factory.user("role-race-member")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201,
                       json={"member_tenant_id": "role-race-member", "role": "reviewer"})
    await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "role-race", "label_id": "L1", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    discovered = asyncio.Event()
    release = asyncio.Event()
    original_lock = auth.lock_tenant
    async def paused_lock(session, tenant_id):
        discovered.set()
        await asyncio.wait_for(release.wait(), 5)
        await original_lock(session, tenant_id)
    monkeypatch.setattr(auth, "lock_tenant", paused_lock)
    mutation = asyncio.create_task(wire.client.post(
        "/v1/labels/verify", headers={"X-Api-Key": member_key}, json={
            "domain_id": "role-race", "label_id": "L1",
            "actual_action": "approve", "verified_outcome": True,
        }))
    await asyncio.wait_for(discovered.wait(), 5)
    async with wire.factory.sessions.begin() as session:
        member = await session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == UUID(project_id),
            ProjectMember.member_tenant_id == "role-race-member"))
        assert member is not None
        member.active = False
    release.set()
    response = await asyncio.wait_for(mutation, 5)
    assert response.status_code == 403
    async with wire.factory.sessions() as fresh:
        row = await fresh.scalar(select(LabelLog).where(LabelLog.label_id == "L1"))
        assert row is not None and row.verified_at is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_purchase_and_project_creation_share_payer_eligibility(wire: Wire, monkeypatch):
    monkeypatch.setenv("PADDLE_API_KEY", "provider-test")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "professional=pri_test")
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.reproof_required = True
    await wire.request("GET", "/v1/billing/checkout-url?tier=professional", status=409)
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(CheckoutIntent.id).limit(1)) is None
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.reproof_required = False
        key.subscription_state = "paused"
    await wire.request("POST", "/v1/projects", status=402, json={
        "name": "Blocked", "public_domain_id": "blocked-project",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain.id).where(
            Domain.public_domain_id == "blocked-project")) is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_uuid_public_name_and_invalid_provider_transaction_are_rejected(wire: Wire):
    await wire.request("POST", "/v1/projects", status=422, json={
        "name": "UUID alias", "public_domain_id": str(uuid4()),
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })
    await wire.request("POST", "/v1/billing/webhook", status=422,
                       omit_api_key=True, json={
                           "event_type": "subscription.created", "event_id": "evt-bad-txn",
                           "occurred_at": datetime.now(timezone.utc).isoformat(),
                           "data": {"id": "sub-bad-txn", "status": "active",
                                    "customer_id": "ctm-bad-txn", "transaction_id": "txn/bad",
                                    "items": [{"product": {"name": "DLJ Professional"}}]},
                       })
    async with wire.factory.sessions() as fresh:
        assert await fresh.get(TransitionLog, "evt-bad-txn") is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_migration_normalizes_empty_mixed_tombstone(wire: Wire, db_engine, monkeypatch):
    async with wire.factory.sessions.begin() as session:
        cleaned = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant))
        assert cleaned is not None
        cleaned.is_active = False
        cleaned.subscription_state = "cleaned_up"
        _, sibling = auth.generate_api_key(wire.factory.tenant, "Revoked sibling")
        sibling.is_active = False
        sibling.subscription_state = "trial"
        session.add(sibling)
    monkeypatch.setattr(db_migrate, "engine", db_engine)
    await db_migrate.migrate()
    async with wire.factory.sessions() as fresh:
        states = (await fresh.scalars(select(ApiKey.subscription_state).where(
            ApiKey.tenant_id == wire.factory.tenant))).all()
        assert len(states) == 2 and set(states) == {"cleaned_up"}


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_alias_collision_refuses_unqualified_member_write(wire: Wire):
    owner_project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Owner copy", "public_domain_id": "same-alias",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
    })).json()["id"]
    member_key = await wire.factory.user("member-tenant")
    private_project = (await wire.request("POST", "/v1/projects", status=201,
                       headers={"X-Api-Key": member_key}, json={
                           "name": "Private copy", "public_domain_id": "same-alias",
                           "factors": ["quality", "difficulty"], "categories": ["A", "B"],
                       })).json()["id"]
    await wire.request("POST", f"/v1/projects/{owner_project}/members", status=201,
                       json={"member_tenant_id": "member-tenant", "role": "reviewer"})
    await wire.request("POST", "/v1/labels/same-alias/tasks", status=409,
                       headers={"X-Api-Key": member_key},
                       json={"label_id": "must-not-land", "text": "Example"})
    await wire.request("POST", f"/v1/labels/{owner_project}/tasks", status=201,
                       headers={"X-Api-Key": member_key},
                       json={"label_id": "shared-by-uuid", "text": "Example"})
    await wire.request("POST", f"/v1/labels/{private_project}/tasks", status=201,
                       headers={"X-Api-Key": member_key},
                       json={"label_id": "private-by-uuid", "text": "Example"})
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(LabelLog.id).where(
            LabelLog.label_id == "must-not-land")) is None
        shared = await fresh.scalar(select(LabelLog).where(LabelLog.label_id == "shared-by-uuid"))
        private = await fresh.scalar(select(LabelLog).where(LabelLog.label_id == "private-by-uuid"))
        assert shared is not None and private is not None
        assert shared.domain_id != private.domain_id
        assert shared.tenant_id == wire.factory.tenant
        assert private.tenant_id == "member-tenant"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_member_revision_records_authenticated_key(wire: Wire):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Shared", "public_domain_id": "shared-revision",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
    })).json()["id"]
    await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "shared-revision", "label_id": "L1", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    member_key = await wire.factory.user("revision-member")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201,
                       json={"member_tenant_id": "revision-member", "role": "reviewer"})
    async with wire.factory.sessions() as fresh:
        original = await fresh.scalar(select(LabelLog).where(LabelLog.label_id == "L1"))
        member = await fresh.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(member_key.encode()).hexdigest()))
        assert original is not None and member is not None
        token, member_id = str(original.id), member.id
    result = await wire.request("POST", "/v1/labels/shared-revision/items/L1/relabel",
                                headers={"X-Api-Key": member_key}, json={
                                    "category": "B", "idempotency_token": token})
    async with wire.factory.sessions() as fresh:
        successor = await fresh.get(LabelLog, UUID(result.json()["revision_id"]))
        assert successor is not None
        assert successor.revision_actor == "revision-member"
        assert successor.revision_by_key_id == member_id


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_uuid_project_routes_enforce_if_match(wire: Wire):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Versioned", "public_domain_id": "versioned",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })).json()["id"]
    detail = await wire.request("GET", f"/v1/projects/{project_id}")
    assert detail.json()["settings_version"] == 1
    await wire.request("PATCH", f"/v1/projects/{project_id}", status=428,
                       json={"description": "new"})
    changed = await wire.request("PATCH", f"/v1/projects/{project_id}",
                                 headers={"If-Match": "1"}, json={"description": "new"})
    assert changed.json()["settings_version"] == 2
    await wire.request("DELETE", f"/v1/projects/{project_id}", status=409,
                       headers={"If-Match": "1"})
    archived = await wire.request("DELETE", f"/v1/projects/{project_id}",
                                  headers={"If-Match": "2"})
    assert archived.json()["status"] == "archived"
    assert (await wire.request("GET", f"/v1/projects/{project_id}")).json()["status"] == "archived"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_billing_contact_cannot_recover_different_signup_owner(wire: Wire):
    await wire.factory.user("legacy-contact-tenant")
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == "legacy-contact-tenant"))
        assert key is not None
        key.contact_email = "billing@example.test"
        key.signup_email = None  # Historical billing contact alone proves no credential ownership.
        key.is_active = False
        key.reproof_required = True
        original_hash = key.key_hash
    await wire.request("POST", "/v1/auth/register", status=409,
                       omit_api_key=True, json={"email": "billing@example.test"})
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(
            ApiKey.tenant_id == "legacy-contact-tenant"))
        assert key is not None and key.key_hash == original_hash and not key.is_active
        key_id = key.id
    await wire.request("POST", f"/v1/admin/api-keys/{key_id}/reconcile-signup-owner",
                       headers={"X-Admin-Key": "harness-admin"}, json={
                           "signup_email": "owner@example.test",
                           "evidence_reference": "manual-ticket-123",
                       })
    await wire.request("POST", "/v1/auth/register", status=202,
                       omit_api_key=True, json={"email": "owner@example.test"})
    delivery = auth.send_signup_challenge_email
    assert isinstance(delivery, AsyncMock)
    assert delivery.await_args is not None
    token = delivery.await_args.args[1]
    result = await wire.request("POST", "/v1/auth/confirm", status=201,
                                omit_api_key=True, json={"token": token})
    assert result.json()["tenant_id"] == "legacy-contact-tenant"
    async with wire.factory.sessions() as fresh:
        key = await fresh.get(ApiKey, key_id)
        assert key is not None and key.is_active
        assert key.contact_email == "billing@example.test"
        assert key.signup_email == "owner@example.test"
        assert key.signup_reconciliation_reference == "manual-ticket-123"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_provider_repair_hold_prevents_retention(wire: Wire):
    scoped = await wire.factory.domain("held-data")
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.subscription_state = "cancelled"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
        key_id = key.id
        session.add(ProviderRepairQuarantine(
            key_id=key.id, tenant_id=wire.factory.tenant,
            reason_code="owner_mismatch", quarantined_at=datetime.now(timezone.utc)))
    assert await scheduler.cleanup_cancelled_tenants() == 0
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == scoped)) is not None
    async with wire.factory.sessions.begin() as session:
        hold = await session.get(ProviderRepairQuarantine, key_id)
        assert hold is not None
        await session.delete(hold)
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain).where(Domain.domain_id == scoped)) is None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_null_state_paid_sibling_survives_retention_and_deleted_tenant_stays_closed(wire: Wire, db_engine):
    paid_key = await wire.factory.user()
    scoped = await wire.factory.domain("pre-a-paid")
    cutoff = datetime.now(timezone.utc) - timedelta(days=31)
    async with wire.factory.sessions.begin() as session:
        keys = (await session.scalars(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant))).all()
        payer = next(key for key in keys if key.key_hash == hashlib.sha256(paid_key.encode()).hexdigest())
        cancelled = next(key for key in keys if key.id != payer.id)
        payer.tier = "professional"
        payer.subscription_state = None
        payer.is_active = False
        payer.reproof_required = True
        cancelled.subscription_state = "cancelled"
        cancelled.cancelled_at = cutoff
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(Domain.id).where(Domain.domain_id == scoped)) is not None
        protected = await fresh.get(ApiKey, payer.id)
        cleaned = await fresh.get(ApiKey, cancelled.id)
        assert protected is not None and protected.subscription_state is None
        assert cleaned is not None and cleaned.subscription_state == "cleaned_up"

    destroyed_key = await wire.factory.user("destroyed-tenant")
    await wire.factory.user("destroyed-tenant")
    async with wire.factory.sessions.begin() as session:
        siblings = (await session.scalars(select(ApiKey).where(
            ApiKey.tenant_id == "destroyed-tenant"))).all()
        for sibling in siblings:
            if sibling.key_hash == hashlib.sha256(destroyed_key.encode()).hexdigest():
                sibling.subscription_state = "cancelled"
                sibling.cancelled_at = cutoff
            else:
                sibling.is_active = False
                sibling.subscription_state = None
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        for sibling in siblings:
            tombstone = await fresh.get(ApiKey, sibling.id)
            assert tombstone is not None and tombstone.subscription_state == "cleaned_up"
            transition = await fresh.scalar(select(TransitionLog).where(
                TransitionLog.key_id == sibling.id,
                TransitionLog.source == "scheduler",
                TransitionLog.new_state == "cleaned_up"))
            assert transition is not None
            assert await fresh.scalar(select(LifecycleNotice.event_id).where(
                LifecycleNotice.event_id == transition.event_id)) is not None
    await wire.request("POST", "/v1/admin/api-keys", status=409,
                       headers={"X-Admin-Key": "harness-admin"},
                       json={"tenant_id": "destroyed-tenant", "tenant_name": "Closed"})


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_retryable_billing_delivery_applies_after_subscription_exists(wire: Wire):
    start = datetime.now(timezone.utc)
    intent = await wire.paddle_intent("professional", "txn_retryable")
    base = {"id": "sub-retryable", "customer_id": "ctm-retryable",
            "items": [{"product": {"name": "DLJ Professional"}}]}
    premature = {"event_type": "subscription.updated", "event_id": "evt-retryable-update",
                 "occurred_at": (start + timedelta(seconds=2)).isoformat(),
                 "data": {**base, "status": "past_due"}}
    created = {"event_type": "subscription.created", "event_id": "evt-retryable-create",
               "occurred_at": (start + timedelta(seconds=1)).isoformat(),
               "data": {**base, "status": "active", "custom_data": intent,
                        "transaction_id": "txn_retryable"}}
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json=premature)
    # Simulate a receipt persisted by a pre-fix build for this rejected attempt.
    async with wire.factory.sessions.begin() as session:
        session.add(PaddleWebhookEvent(event_id=premature["event_id"]))
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=created)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=premature)
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=premature)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "past_due"
        assert await fresh.scalar(select(TransitionLog.event_id).where(
            TransitionLog.event_id == "evt-retryable-update")) is not None
        notices = (await fresh.scalars(select(LifecycleNotice).where(
            LifecycleNotice.event_id == "evt-retryable-update"))).all()
        assert len(notices) == 1


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_current_checkout_binding_does_not_gain_historical_exemption(wire: Wire, db_engine, monkeypatch):
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.tier = "professional"
        key.subscription_state = "active"
        key.paddle_customer_id = "ctm-modern"
        key.paddle_subscription_id = "sub-modern"
        session.add(SubscriptionBinding(subscription_id="sub-modern", payer=key.id,
                                        customer_id="ctm-modern"))
        key_id = key.id
    monkeypatch.setattr(db_migrate, "engine", db_engine)
    await db_migrate.migrate()
    if db_engine.dialect.name == "postgresql":
        async with db_engine.connect() as connection:
            names = await connection.run_sync(lambda sync: {
                row["name"] for row in inspect(sync).get_unique_constraints("api_keys")})
            assert "uq_key_owner" in names
    async with wire.factory.sessions() as fresh:
        assert await fresh.get(ProviderRepairManifest, key_id) is None
    await wire.request("POST", "/v1/billing/webhook", status=409,
                       omit_api_key=True, json={
                           "event_type": "subscription.created", "event_id": "evt-modern-no-intent",
                           "occurred_at": datetime.now(timezone.utc).isoformat(),
                           "data": {"id": "sub-modern-other", "status": "active",
                                    "customer_id": "ctm-modern",
                                    "transaction_id": "txn_modernother",
                                    "items": [{"product": {"name": "DLJ Professional"}}]},
                       })


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_invitation_claim_is_single_use_with_concurrent_acceptances(wire: Wire, monkeypatch, db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locking is the concurrency oracle")
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Shared", "public_domain_id": "claim-once",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    member_key = await wire.factory.user("invite-recipient")
    async with wire.factory.sessions.begin() as session:
        member = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(member_key.encode()).hexdigest()))
        assert member is not None
        member.signup_email = "recipient@example.test"
        member.email_verified_at = datetime.now(timezone.utc)
    sent: list[str] = []
    async def capture(address: str, subject: str, html: str) -> bool:
        sent.append(html)
        return True
    monkeypatch.setattr(projects_router, "send_email", capture)
    invite = (await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                                 json={"email": "recipient@example.test", "role": "reviewer"})).json()
    token = re.search(r"Invitation code: ([a-f0-9]{64})", sent[0])
    assert token is not None
    path = f"/v1/projects/{project}/invites/{invite['id']}/accept"
    responses = await asyncio.gather(*(
        wire.client.post(path, headers={"X-Api-Key": member_key}, json={"token": token.group(1)})
        for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [200, 403]
    async with wire.factory.sessions() as fresh:
        members = (await fresh.scalars(select(ProjectMember).where(
            ProjectMember.project_id == UUID(project),
            ProjectMember.member_tenant_id == "invite-recipient"))).all()
        assert len(members) == 1


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_invitation_revoked_while_acceptance_waits_is_refused(wire: Wire, monkeypatch, db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locking is the concurrency oracle")
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Replace invite", "public_domain_id": "replace-invite",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    member_key = await wire.factory.user("replacement-recipient")
    async with wire.factory.sessions.begin() as session:
        member = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(member_key.encode()).hexdigest()))
        assert member is not None
        member.signup_email = "replacement@example.test"
        member.email_verified_at = datetime.now(timezone.utc)
    sent: list[str] = []
    async def capture(address: str, subject: str, html: str) -> bool:
        sent.append(html)
        return True
    monkeypatch.setattr(projects_router, "send_email", capture)
    old = (await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                              json={"email": "replacement@example.test", "role": "reviewer"})).json()
    token = re.search(r"Invitation code: ([a-f0-9]{64})", sent[0])
    assert token is not None
    entered = asyncio.Event()
    release = asyncio.Event()
    original_lock = projects_router.lock_tenant
    recipient_hash = hashlib.sha256(member_key.encode()).hexdigest()
    async def paused_lock(session, tenant_id):
        if session.info.get("api_key_hash") == recipient_hash:
            entered.set()
            await asyncio.wait_for(release.wait(), 5)
        await original_lock(session, tenant_id)
    monkeypatch.setattr(projects_router, "lock_tenant", paused_lock)
    pending = asyncio.create_task(wire.client.post(
        f"/v1/projects/{project}/invites/{old['id']}/accept",
        headers={"X-Api-Key": member_key}, json={"token": token.group(1)}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                           json={"email": "replacement@example.test", "role": "annotator"})
    finally:
        release.set()
    assert (await pending).status_code == 403
    async with wire.factory.sessions() as fresh:
        old_invite = await fresh.get(ProjectInvite, UUID(old["id"]))
        assert old_invite is not None and old_invite.revoked_at is not None
        members = (await fresh.scalars(select(ProjectMember).where(
            ProjectMember.project_id == UUID(project),
            ProjectMember.member_tenant_id == "replacement-recipient"))).all()
        assert members == []


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_null_project_patch_is_validation_error_without_mutation(wire: Wire):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Patch", "public_domain_id": "patch-null",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    original = (await wire.request("GET", f"/v1/projects/{project}")).json()
    for field in ("automation_enabled", "confidence_floor"):
        await wire.request("PATCH", f"/v1/projects/{project}", status=422,
                           headers={"If-Match": str(original["settings_version"])},
                           json={field: None})
    current = (await wire.request("GET", f"/v1/projects/{project}")).json()
    assert current["settings_version"] == original["settings_version"]
    assert current["automation_enabled"] == original["automation_enabled"]
    assert current["confidence_floor"] == original["confidence_floor"]


def test_startup_does_not_echo_invalid_database_authority():
    canary = "dlj-startup-secret"
    environment = dict(os.environ, DATABASE_URL=f"postgresql+asyncpg://user:{canary}@[bad/db")
    result = subprocess.run([sys.executable, "-c", "import db.connection"],
                            capture_output=True, text=True, env=environment, timeout=15)
    assert result.returncode != 0
    assert canary not in result.stderr
    assert "Database URL is invalid" in result.stderr


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_archive_before_admin_grant_revalidates_under_guard(wire: Wire, db_engine, monkeypatch):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locking is the concurrency oracle")
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Guarded", "public_domain_id": "guarded",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })).json()["id"]
    admin_key = await wire.factory.user("admin-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201,
                       json={"member_tenant_id": "admin-tenant", "role": "admin"})
    await wire.factory.user("new-member")
    waiting = asyncio.Event()
    original_lock = projects_router.lock_tenant

    async def observed_lock(session, tenant_id):
        waiting.set()
        await original_lock(session, tenant_id)

    monkeypatch.setattr(projects_router, "lock_tenant", observed_lock)
    async with wire.factory.sessions.begin() as owner_session:
        await lock_tenant(owner_session, wire.factory.tenant)
        grant = asyncio.create_task(wire.client.post(
            f"/v1/projects/{project_id}/members",
            headers={"X-Api-Key": admin_key},
            json={"member_tenant_id": "new-member", "role": "reviewer"}))
        await asyncio.wait_for(waiting.wait(), 5)
        project = await owner_session.get(Domain, UUID(project_id), with_for_update=True)
        assert project is not None
        project.status = "archived"
    result = await asyncio.wait_for(grant, 5)
    assert result.status_code == 409, result.text

    second_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Demotion", "public_domain_id": "demotion",
        "factors": ["quality", "difficulty"], "categories": ["A"],
    })).json()["id"]
    await wire.request("POST", f"/v1/projects/{second_id}/members", status=201,
                       json={"member_tenant_id": "admin-tenant", "role": "admin"})
    waiting.clear()
    async with wire.factory.sessions.begin() as owner_session:
        await lock_tenant(owner_session, wire.factory.tenant)
        grant = asyncio.create_task(wire.client.post(
            f"/v1/projects/{second_id}/members",
            headers={"X-Api-Key": admin_key},
            json={"member_tenant_id": "new-member", "role": "reviewer"}))
        await asyncio.wait_for(waiting.wait(), 5)
        member = await owner_session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == UUID(second_id),
            ProjectMember.member_tenant_id == "admin-tenant").with_for_update())
        assert member is not None
        member.role = "reviewer"
    result = await asyncio.wait_for(grant, 5)
    assert result.status_code == 403, result.text


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_sandbox_webhook_requires_signature_and_secret(wire: Wire, monkeypatch):
    event = {"event_type": "subscription.created", "event_id": "unsigned-event",
             "occurred_at": datetime.now(timezone.utc).isoformat(),
             "data": {"id": "sub-unsigned", "customer_id": "ctm-unsigned",
                      "custom_data": {"tenant_id": wire.factory.tenant},
                      "items": [{"product": {"name": "DLJ Professional"}}]}}
    response = await wire.client.post("/v1/billing/webhook", json=event)
    assert response.status_code == 401
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", "")
    response = await wire.client.post("/v1/billing/webhook", json=event)
    assert response.status_code == 503
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.subscription_state == "trial"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_same_state_tier_update_versions_entitlement_and_notifies(wire: Wire):
    first = {"event_type": "subscription.created", "event_id": "evt-tier-create",
             "occurred_at": datetime.now(timezone.utc).isoformat(),
             "data": {"id": "sub-tier", "customer_id": "ctm-tier",
                      "transaction_id": "txn_tier", "status": "active",
                      "custom_data": await wire.paddle_intent("starter", "txn_tier"),
                      "items": [{"product": {"name": "DLJ Starter"}}]}}
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=first)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        before_version = key.state_version
    updated = {"event_type": "subscription.updated", "event_id": "evt-tier-update",
               "occurred_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
               "data": {"id": "sub-tier", "status": "active",
                        "items": [{"product": {"name": "DLJ Professional"}}]}}
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json=updated)
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        log = await fresh.get(TransitionLog, "evt-tier-update")
        notice = await fresh.get(LifecycleNotice, ("evt-tier-update", "entitlement_changed"))
        assert key is not None and key.tier == "professional"
        assert key.state_version == before_version + 1
        assert log is not None and log.key_version == key.state_version
        assert notice is not None


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_oversized_path_rejected_before_project_lookup(wire: Wire, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession
    original_scalar = AsyncSession.scalar
    async def watched_scalar(self, statement, *args, **kwargs):
        if "FROM domains" in str(statement):
            raise AssertionError("oversized path reached project lookup")
        return await original_scalar(self, statement, *args, **kwargs)
    monkeypatch.setattr(AsyncSession, "scalar", watched_scalar)
    await wire.request("POST", f"/v1/labels/{'D' * 201}/tasks", status=422,
                       json={"label_id": "L1", "text": "Example"})


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_expired_trial_summary_agrees_with_scoring_before_scheduler(wire: Wire):
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(
            ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.created_at = datetime.now(timezone.utc) - timedelta(days=15)
    summary = await wire.request("GET", "/v1/account")
    assert summary.json()["subscription_state"] == "trial_expired"
    assert summary.json()["usage"]["daily_cap"] == 0
    await wire.request("POST", "/v1/labels/ingest", status=402, json={
        "domain_id": "expired", "label_id": "L1", "category": "A",
        "factors": {"quality": .8, "difficulty": .2}})


def test_connection_option_diagnostic_does_not_echo_secret():
    with pytest.raises(ValueError) as error:
        normalize_database_url(
            "postgresql+asyncpg://user:password@localhost/db?sslmode=secret-canary")
    assert "secret-canary" not in str(error.value)


@pytest.mark.parametrize("event,old,new,accepted", [
    ("subscription.created", "trial", "active", True),
    ("subscription.created", "cancelled", "active", True),
    ("subscription.updated", "active", "past_due", True),
    ("subscription.updated", "past_due", "active", True),
    ("subscription.updated", "active", "paused", True),
    ("subscription.updated", "paused", "active", True),
    ("subscription.canceled", "active", "cancelled", True),
    ("subscription.updated", "cancelled", "active", False),
    ("subscription.updated", "trial", "active", False),
    ("subscription.created", "cleaned_up", "active", False),
    ("subscription.canceled", "trial", "cancelled", False),
])
def test_provider_event_transition_matrix(event, old, new, accepted):
    if accepted:
        billing._validate_transition(event, old, new)
    else:
        with pytest.raises(HTTPException) as error:
            billing._validate_transition(event, old, new)
        assert error.value.status_code == 409


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_domain_upgrade_restores_validation(db_engine, monkeypatch):
    names = {"ck_domain_status", "ck_domain_confidence_floor",
             "ck_domain_settings_version"}
    if db_engine.dialect.name == "postgresql":
        async with db_engine.begin() as connection:
            for name in names:
                await connection.execute(text(f"ALTER TABLE domains DROP CONSTRAINT {name}"))
    monkeypatch.setattr(db_migrate, "engine", db_engine)
    await db_migrate.migrate()
    async with db_engine.connect() as connection:
        if db_engine.dialect.name == "postgresql":
            found = await connection.run_sync(lambda sync: {
                row["name"] for row in inspect(sync).get_check_constraints("domains")})
            assert names <= found
        else:
            found = set((await connection.scalars(text(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='domains'"))).all())
            assert all(f"{name}_insert" in found and f"{name}_update" in found
                       for name in names)
