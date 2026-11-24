"""Hourly trial notifications and cancelled-tenant cleanup."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from db.connection import AsyncSessionLocal
from db.models import Annotator, ApiKey, Domain, Engine, LabelLog
from email_service import send_email, trial_expired_email, trial_expiring_email

logger = logging.getLogger("dlj.scheduler")
TRIAL_DAYS = 14
RETENTION_DAYS = 30


async def send_trial_expiry_emails() -> int:
    """Send each trial notice once when an address is available."""
    sent = 0
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        records = (await session.scalars(select(ApiKey).where(
            ApiKey.tier == "trial", ApiKey.is_active.is_(True)))).all()
        for record in records:
            if not record.created_at:
                continue
            created = record.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            expiry = created + timedelta(days=TRIAL_DAYS)
            days_remaining = (expiry.date() - now.date()).days
            if not record.contact_email:
                if days_remaining == 2 or now >= expiry:
                    logger.info("Trial notice needs contact email for tenant %s", record.tenant_id)
                continue
            if now >= expiry and record.trial_expired_email_sent_at is None:
                subject, html = trial_expired_email()
                if await send_email(record.contact_email, subject, html):
                    record.trial_expired_email_sent_at = now
                    sent += 1
            elif days_remaining == 2 and now < expiry and record.trial_expiring_email_sent_at is None:
                subject, html = trial_expiring_email()
                if await send_email(record.contact_email, subject, html):
                    record.trial_expiring_email_sent_at = now
                    sent += 1
        if sent:
            await session.commit()
    return sent


async def cleanup_cancelled_tenants() -> int:
    """Delete only after locking and rechecking every key for the tenant."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    cleaned = 0
    async with AsyncSessionLocal() as session:
        candidates = (await session.execute(select(ApiKey.id, ApiKey.paddle_subscription_id).where(
            ApiKey.is_active.is_(True), ApiKey.cancelled_at.isnot(None),
            ApiKey.cancelled_at < cutoff))).all()
    cleaned_tenants: set[str] = set()
    for candidate_id, subscription_id in candidates:
        async with AsyncSessionLocal.begin() as session:
            key = await session.scalar(select(ApiKey).where(ApiKey.id == candidate_id)
                                       .with_for_update().execution_options(populate_existing=True))
            if key is None or key.tenant_id in cleaned_tenants:
                continue
            cancelled_at = key.cancelled_at
            if cancelled_at is not None and cancelled_at.tzinfo is None:
                cancelled_at = cancelled_at.replace(tzinfo=timezone.utc)
            if (cancelled_at is None or not key.is_active or cancelled_at >= cutoff
                    or key.paddle_subscription_id != subscription_id):
                continue
            tenant_id = key.tenant_id
            # A sibling key can still own live data, regardless of its subscription state.
            other_active = await session.scalar(select(ApiKey.id).where(
                ApiKey.tenant_id == tenant_id, ApiKey.is_active.is_(True),
                ApiKey.id != key.id).limit(1))
            if other_active is not None:
                logger.info("Skipped cleanup for tenant %s with another active key", tenant_id)
                continue
            await session.execute(delete(LabelLog).where(LabelLog.tenant_id == tenant_id))
            await session.execute(delete(Engine).where(Engine.tenant_id == tenant_id))
            await session.execute(delete(Annotator).where(Annotator.tenant_id == tenant_id))
            await session.execute(delete(Domain).where(Domain.tenant_id == tenant_id))
            key.is_active = False
            cleaned_tenants.add(tenant_id)
            cleaned += 1
            logger.info("Cleaned up cancelled tenant %s", tenant_id)
    return cleaned


async def run_scheduled_tasks() -> None:
    """Run scheduled jobs while keeping the next hourly attempt alive on error."""
    try:
        emails = await send_trial_expiry_emails()
        cleaned = await cleanup_cancelled_tenants()
        if emails or cleaned:
            logger.info("Scheduler: %d trial emails, %d tenants cleaned", emails, cleaned)
    except Exception:
        logger.exception("Scheduler error")


async def scheduler_loop() -> None:
    """Run jobs once an hour until FastAPI shuts down."""
    while True:
        await asyncio.sleep(3600)
        await run_scheduled_tasks()
