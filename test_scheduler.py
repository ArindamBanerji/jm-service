"""Scheduled trial mail and tenant retention checks."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scheduler
from db.models import Annotator, ApiKey, Base, Domain, Engine, LabelLog


@pytest.mark.sqlite_only
def test_trial_notice_sent_once(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'mail.db').as_posix()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", factory)
    recipients: list[str] = []

    async def fake_send(to: str, subject: str, html: str) -> bool:
        recipients.append(to)
        assert "2 days" in subject
        return True

    monkeypatch.setattr(scheduler, "send_email", fake_send)

    async def exercise() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(ApiKey(key_hash="1" * 64, tenant_id="trial", tenant_name="Trial",
                               tier="trial", contact_email="trial@example.com",
                               created_at=datetime.now(timezone.utc) - timedelta(days=12)))
            await session.commit()
        assert await scheduler.send_trial_expiry_emails() == 1
        assert await scheduler.send_trial_expiry_emails() == 0
        async with factory() as session:
            key = await session.scalar(select(ApiKey))
            assert key is not None and key.trial_expiring_email_sent_at is not None
        await engine.dispose()

    asyncio.run(exercise())
    assert recipients == ["trial@example.com"]


@pytest.mark.sqlite_only
def test_cleanup_cancelled_tenants(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'cleanup.db').as_posix()}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", factory)

    async def exercise() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        now = datetime.now(timezone.utc)
        async with factory() as session:
            for tenant, age in (("old", 31), ("recent", 15)):
                session.add(ApiKey(key_hash=tenant.ljust(64, "0"), tenant_id=tenant,
                                   tenant_name=tenant, tier="starter",
                                   cancelled_at=now - timedelta(days=age)))
                session.add(Domain(domain_id=tenant, tenant_id=tenant,
                                   domain_name=tenant, config_json={}))
                session.add(Engine(domain_id=tenant, tenant_id=tenant, state_json={}))
                session.add(Annotator(domain_id=tenant, tenant_id=tenant,
                                      annotator_id="reviewer"))
                session.add(LabelLog(domain_id=tenant, tenant_id=tenant, label_id="label",
                                     category="cat", factors_json={},
                                     recommended_action="review", confidence=0.5))
            await session.commit()
        assert await scheduler.cleanup_cancelled_tenants() == 1
        assert await scheduler.cleanup_cancelled_tenants() == 0
        async with factory() as session:
            keys = {key.tenant_id: key for key in (await session.scalars(select(ApiKey))).all()}
            assert not keys["old"].is_active
            assert keys["recent"].is_active
            for model, tenant_column in ((Domain, Domain.tenant_id),
                                         (Engine, Engine.tenant_id),
                                         (Annotator, Annotator.tenant_id),
                                         (LabelLog, LabelLog.tenant_id)):
                assert await session.scalar(select(func.count()).select_from(model).where(
                    tenant_column == "old")) == 0
                assert await session.scalar(select(func.count()).select_from(model).where(
                    tenant_column == "recent")) == 1
        await engine.dispose()

    asyncio.run(exercise())


def test_scheduled_task_catches_error(monkeypatch) -> None:
    async def failing_job() -> int:
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(scheduler, "send_trial_expiry_emails", failing_job)
    asyncio.run(scheduler.run_scheduled_tasks())
