import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

import projects_router
from db import migrate as migrations
from db.models import ApiKey, ProjectMember, TransitionLog
from .fixtures.factory import Wire
from .fixtures.pg_schema import database

pytestmark = [pytest.mark.prompt_a, pytest.mark.anyio]


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_live_equal_time_cancellation_wins(wire: Wire, cancel_first: bool):
    now = datetime.now(timezone.utc)
    body = {"id": "sub_live", "customer_id": "ctm_live", "status": "active",
            "transaction_id": "txn_live", "items": [{"product": {"name": "DLJ Professional"}}],
            "custom_data": await wire.paddle_intent("professional", "txn_live")}
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json={
        "event_id": "created", "event_type": "subscription.created",
        "occurred_at": (now - timedelta(seconds=1)).isoformat(), "data": body})
    deliveries = [("aaa", "canceled", "canceled"), ("zzz", "updated", "paused")]
    for event_id, kind, status in deliveries if cancel_first else reversed(deliveries):
        await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json={
            "event_id": event_id, "event_type": "subscription." + kind,
            "occurred_at": now.isoformat(), "data": {"id": "sub_live", "status": status}})
    account = (await wire.request("GET", "/v1/account")).json()
    assert account["subscription_state"] == "cancelled"
    assert account["usage"]["daily_cap"] == 50
    async with wire.factory.sessions() as fresh:
        payer = await fresh.scalar(select(ApiKey))
        assert payer is not None
        assert payer.paddle_event_id == "aaa" and payer.cancelled_at is not None
        decision = await fresh.get(TransitionLog, "aaa")
        assert decision is not None and decision.disposition == "applied"


async def test_cancelled_owner_quota_agrees_and_member_invite_is_frozen(wire: Wire, monkeypatch):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Team", "public_domain_id": "team", "factors": ["a", "b"], "categories": ["A"]
    })).json()["id"]
    recipient = await wire.factory.user("recipient")
    async with wire.factory.sessions.begin() as session:
        member = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == "recipient"))
        assert member is not None
        member.signup_email = "recipient@example.test"
        member.email_verified_at = datetime.now(timezone.utc)
    codes = []
    async def mail(address, subject, html):
        codes.append(html.split("Invitation code: ")[1].split("<")[0])
        return True
    monkeypatch.setattr(projects_router, "send_email", mail)
    invite = (await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                                 json={"email": "recipient@example.test", "role": "reviewer"})).json()
    async with wire.factory.sessions.begin() as session:
        payer = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert payer is not None
        payer.created_at = datetime.now(timezone.utc) - timedelta(days=20)
        payer.subscription_state = "cancelled"
        payer.cancelled_at = datetime.now(timezone.utc)
    assert not (await wire.request("GET", "/v1/account")).json()["trial_expired"]
    await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "team", "category": "A", "label_id": "L", "factors": {"a": .4, "b": .6}})
    await wire.request("POST", f"/v1/projects/{project}/invites/{invite['id']}/accept",
                       status=403, headers={"X-Api-Key": recipient}, json={"token": codes[0]})
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(ProjectMember.id).where(
            ProjectMember.member_tenant_id == "recipient")) is None


async def test_alias_writers_reject_uuid(wire: Wire):
    alias = str(uuid4())
    await wire.request("POST", "/v1/account/domains/resolve", status=422, json={"domain_id": alias})
    await wire.request("POST", "/v1/label-studio/configure", status=422,
                       headers={"X-LS-Token": "harness-ls"}, json={"domain_id": alias,
                       "project_id": "p", "factor_map": {"a": "data.a", "b": "data.b"}})


async def test_reciprocal_admin_grants(wire: Wire, db_engine, monkeypatch):
    other = await wire.factory.user("second")
    await wire.factory.user("third")
    headers = [{}, {"X-Api-Key": other}]
    projects = [(await wire.request("POST", "/v1/projects", status=201, headers=h, json={
        "name": "Team", "public_domain_id": "team", "factors": ["a", "b"], "categories": ["A"]
    })).json()["id"] for h in headers]
    for i, tenant in enumerate(["second", wire.factory.tenant]):
        await wire.request("POST", f"/v1/projects/{projects[i]}/members", status=201,
                           headers=headers[i], json={"member_tenant_id": tenant, "role": "admin"})
    async def grant(i):
        await wire.request("POST", f"/v1/projects/{projects[i]}/members", status=201,
                           headers=headers[1-i], json={"member_tenant_id": "third", "role": "reviewer"})
    if db_engine.dialect.name == "postgresql":
        original = projects_router.lock_tenant
        seen = set()
        barrier = asyncio.Barrier(2)
        async def lock(session, tenant):
            await original(session, tenant)
            if tenant not in seen:
                seen.add(tenant)
                await asyncio.wait_for(barrier.wait(), 8)
        monkeypatch.setattr(projects_router, "lock_tenant", lock)
        await asyncio.wait_for(asyncio.gather(grant(0), grant(1)), 12)
    else:
        await grant(0)
        await grant(1)
    async with wire.factory.sessions() as fresh:
        rows = list(await fresh.scalars(select(ProjectMember).where(ProjectMember.member_tenant_id == "third")))
        assert len(rows) == 2 and all(row.role == "reviewer" for row in rows)


async def test_fresh_install_skips_historical_repairs_on_redeploy(tmp_path, monkeypatch, pytestconfig):
    def historical_job(connection):
        pytest.fail("historical job ran on a fresh installation")
    monkeypatch.setattr(migrations, "repair_provider_links", historical_job)
    monkeypatch.setattr(migrations, "normalize_historical_tombstones", historical_job)
    sqlite = pytestconfig.getoption("--harness-sqlite", default=False)
    async with database(tmp_path, sqlite, initialize=False) as engine:
        monkeypatch.setattr(migrations, "engine", engine)
        await migrations.migrate()
        await migrations.migrate()
