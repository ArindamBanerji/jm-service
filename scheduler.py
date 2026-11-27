"""Hourly trial notifications and cancelled-tenant cleanup."""
from __future__ import annotations

import asyncio
import logging
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import time
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, func, or_, select, text, update

from db.connection import AsyncSessionLocal, sanitize_database_error
from db.entitlement import effective_state, entitlement_decision
from db.models import (Annotator, ApiKey, CheckoutIntent, ConnectorConfigRow, Domain, Engine, LabelLog,
                       LifecycleNotice, Prediction, ProjectBillingOwner, ProjectExportSlot, ProjectRequest,
                       ProviderRepairQuarantine, TransitionLog, WebhookAttempt, WebhookDelivery,
                       WebhookEndpoint, WebhookEvent)
from db.tenant_lock import lock_tenant
from email_service import send_email, trial_expired_email, trial_expiring_email
from webhook_security import DestinationResolutionError, decrypt_secret, signature, validate_public_https

logger = logging.getLogger("dlj.scheduler")
TRIAL_DAYS = 14
RETENTION_DAYS = 30
WEBHOOK_LEASE_SECONDS = 30
WEBHOOK_SEND_LIMIT = 4
WEBHOOK_RETRY_SECONDS = (10, 60, 300)


@dataclass(frozen=True)
class ClaimedDelivery:
    delivery_id: UUID
    endpoint_id: UUID
    event_id: UUID
    lease_token: UUID


@dataclass(frozen=True)
class DeliveryResult:
    http_status: int | None
    error_class: str | None

    @property
    def delivered(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300

    @property
    def retryable(self) -> bool:
        if self.http_status is not None:
            return self.http_status in (408, 429) or self.http_status >= 500
        return self.error_class in {"timeout", "network_error", "dns_error"}


async def _claim_webhook_deliveries(limit: int = WEBHOOK_SEND_LIMIT) -> list[ClaimedDelivery]:
    """Atomically lease at most one due delivery per endpoint."""
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=WEBHOOK_LEASE_SECONDS)
    claimed: list[ClaimedDelivery] = []
    async with AsyncSessionLocal.begin() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.execute(text(
                "SELECT pg_advisory_xact_lock(hashtext('dlj-webhook-delivery-claim'))"))
        # Endpoint leases fence actual network sends even when rotation has
        # already cancelled the corresponding delivery row.
        active_leases = await session.scalar(select(func.count()).select_from(WebhookEndpoint).where(
            WebhookEndpoint.lease_until >= now))
        available = max(0, limit - int(active_leases or 0))
        cutoff = now - timedelta(days=30)
        final_attempt_is_old = exists(select(WebhookAttempt.delivery_id).where(
            WebhookAttempt.delivery_id == WebhookDelivery.id,
            WebhookAttempt.attempt_no == WebhookDelivery.attempts,
            WebhookAttempt.finished_at < cutoff))
        terminal_ids = (await session.scalars(select(WebhookDelivery.id).where(or_(
            and_(WebhookDelivery.state == "delivered", WebhookDelivery.delivered_at < cutoff),
            and_(WebhookDelivery.state == "dead", final_attempt_is_old),
            and_(WebhookDelivery.state == "cancelled", WebhookDelivery.terminal_at < cutoff),
        )).order_by(WebhookDelivery.id).limit(500))).all()
        if terminal_ids:
            await session.execute(delete(WebhookAttempt).where(
                WebhookAttempt.delivery_id.in_(terminal_ids)))
            await session.execute(delete(WebhookDelivery).where(
                WebhookDelivery.id.in_(terminal_ids)))
        await session.execute(delete(WebhookEvent).where(
            WebhookEvent.created_at < cutoff,
            ~exists(select(WebhookDelivery.id).where(
                WebhookDelivery.event_id == WebhookEvent.id))))
        if available == 0:
            return []
        due = or_(
            and_(WebhookDelivery.state == "pending",
                 or_(WebhookDelivery.next_attempt_at.is_(None),
                     WebhookDelivery.next_attempt_at <= now)),
            and_(WebhookDelivery.state == "leased", WebhookDelivery.lease_until < now),
        )
        endpoint_query = select(WebhookEndpoint.id).where(
            WebhookEndpoint.active.is_(True),
            or_(WebhookEndpoint.lease_until.is_(None), WebhookEndpoint.lease_until < now),
            exists(select(WebhookDelivery.id).where(
                WebhookDelivery.endpoint_id == WebhookEndpoint.id,
                WebhookDelivery.destination_version == WebhookEndpoint.destination_version,
            due))).order_by(WebhookEndpoint.id).limit(available * 2)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            endpoint_query = endpoint_query.with_for_update(skip_locked=True)
        endpoint_ids = (await session.scalars(endpoint_query)).all()
        for endpoint_id in endpoint_ids:
            if len(claimed) >= available:
                break
            token = uuid4()
            locked = await session.execute(update(WebhookEndpoint).where(
                WebhookEndpoint.id == endpoint_id,
                WebhookEndpoint.active.is_(True),
                or_(WebhookEndpoint.lease_until.is_(None), WebhookEndpoint.lease_until < now),
            ).values(lease_token=token, lease_until=lease_until))
            if getattr(locked, "rowcount", 0) != 1:
                continue
            endpoint = await session.get(WebhookEndpoint, endpoint_id)
            if endpoint is None:
                continue
            delivery = await session.scalar(select(WebhookDelivery).where(
                WebhookDelivery.endpoint_id == endpoint_id,
                WebhookDelivery.destination_version == endpoint.destination_version,
                due).order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id).limit(1))
            if delivery is None:
                endpoint.lease_token = None
                endpoint.lease_until = None
                continue
            previous_token = delivery.lease_token
            previous_state = delivery.state
            previous_until = delivery.lease_until
            claimed_row = await session.execute(update(WebhookDelivery).where(
                WebhookDelivery.id == delivery.id,
                WebhookDelivery.state == previous_state,
                WebhookDelivery.lease_token.is_(previous_token) if previous_token is None
                else WebhookDelivery.lease_token == previous_token,
                WebhookDelivery.lease_until.is_(previous_until) if previous_until is None
                else WebhookDelivery.lease_until == previous_until,
            ).values(state="leased", lease_token=token, lease_until=lease_until))
            if getattr(claimed_row, "rowcount", 0) != 1:
                endpoint.lease_token = None
                endpoint.lease_until = None
                continue
            claimed.append(ClaimedDelivery(delivery.id, endpoint_id, delivery.event_id, token))
    return claimed


async def _send_webhook(url: str, ciphertext: bytes, canonical_body: str, key_version: int) -> DeliveryResult:
    """Send exact stored bytes with a signature; never expose response content."""
    try:
        async with asyncio.timeout(10):
            address = await validate_public_https(url)
            target = httpx.URL(url)
            timestamp = str(int(time()))
            digest = signature(decrypt_secret(ciphertext), timestamp, canonical_body)
            headers = {
                "Host": target.netloc.decode("ascii"),
                "Paddle-Signature": f"ts={timestamp};h1={digest}",
                "X-Webhook-Key-Version": str(key_version),
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client:
                async with client.stream(
                    "POST", target.copy_with(host=address), headers=headers,
                    content=canonical_body.encode("utf-8"),
                    extensions={"sni_hostname": target.raw_host.decode("ascii")},
                ) as response:
                    status = response.status_code
            return DeliveryResult(status, None if 200 <= status < 300 else "http_error")
    except DestinationResolutionError:
        return DeliveryResult(None, "dns_error")
    except HTTPException as exc:
        return DeliveryResult(None, "signing_unavailable" if exc.status_code == 503 else "unsafe_destination")
    except (TimeoutError, httpx.TimeoutException):
        return DeliveryResult(None, "timeout")
    except httpx.HTTPError:
        return DeliveryResult(None, "network_error")
    except Exception:
        return DeliveryResult(None, "delivery_error")


async def _deliver_claim(claim: ClaimedDelivery) -> None:
    """Record one durable attempt and finalize only the lease this worker owns."""
    started = datetime.now(timezone.utc)
    async with AsyncSessionLocal.begin() as session:
        endpoint = await session.get(WebhookEndpoint, claim.endpoint_id, with_for_update=True)
        delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.id == claim.delivery_id,
            WebhookDelivery.state == "leased",
            WebhookDelivery.lease_token == claim.lease_token).with_for_update())
        if delivery is None or endpoint is None:
            if endpoint is not None and endpoint.lease_token == claim.lease_token:
                endpoint.lease_token = None
                endpoint.lease_until = None
            return
        if (not endpoint.active or endpoint.destination_version != delivery.destination_version
                or endpoint.lease_token != claim.lease_token):
            delivery.state = "cancelled"
            delivery.terminal_at = started
            delivery.lease_token = None
            delivery.lease_until = None
            if endpoint.lease_token == claim.lease_token:
                endpoint.lease_token = None
                endpoint.lease_until = None
            return
        # A delayed worker must claim again once its fence has expired.
        now = datetime.now(timezone.utc)
        if endpoint.lease_until is None or endpoint.lease_until.replace(tzinfo=timezone.utc) <= now:
            return
        endpoint.lease_until = delivery.lease_until = now + timedelta(seconds=WEBHOOK_LEASE_SECONDS)
        event = await session.get(WebhookEvent, delivery.event_id)
        if event is None:
            delivery.state = "dead"
            delivery.error_class = "event_missing"
            delivery.lease_token = None
            delivery.lease_until = None
            endpoint.lease_token = None
            endpoint.lease_until = None
            return
        prior_attempt = await session.scalar(select(func.max(WebhookAttempt.attempt_no)).where(
            WebhookAttempt.delivery_id == delivery.id))
        attempt_no = max(delivery.attempts, int(prior_attempt or 0)) + 1
        if attempt_no > 4:
            delivery.state = "dead"
            delivery.error_class = "attempt_limit"
            delivery.attempts = 4
            delivery.lease_token = endpoint.lease_token = None
            delivery.lease_until = endpoint.lease_until = None
            last = await session.get(WebhookAttempt, (delivery.id, 4))
            if last is not None and last.finished_at is None:
                last.finished_at = started
                last.outcome = "lease_expired"
            return
        session.add(WebhookAttempt(
            delivery_id=delivery.id, attempt_no=attempt_no, started_at=started,
            key_version=endpoint.key_version))
        url = endpoint.url
        ciphertext = endpoint.secret_ciphertext
        canonical_body = event.canonical_body
        key_version = endpoint.key_version
    result = await _send_webhook(url, ciphertext, canonical_body, key_version)
    finished = datetime.now(timezone.utc)
    async with AsyncSessionLocal.begin() as session:
        endpoint = await session.get(WebhookEndpoint, claim.endpoint_id, with_for_update=True)
        delivery = await session.scalar(select(WebhookDelivery).where(
            WebhookDelivery.id == claim.delivery_id).with_for_update())
        attempt = await session.get(WebhookAttempt, (claim.delivery_id, attempt_no))
        if attempt is not None:
            attempt.finished_at = finished
            attempt.outcome = "delivered" if result.delivered else result.error_class
            attempt.http_status = result.http_status
        if delivery is not None and delivery.state == "leased" and delivery.lease_token == claim.lease_token:
            delivery.attempts = attempt_no
            delivery.last_status = result.http_status
            delivery.error_class = result.error_class
            delivery.lease_token = None
            delivery.lease_until = None
            if result.delivered:
                delivery.state = "delivered"
                delivery.delivered_at = finished
                delivery.next_attempt_at = None
            elif attempt_no >= 4 or not result.retryable:
                delivery.state = "dead"
                delivery.next_attempt_at = None
            else:
                delivery.state = "pending"
                delivery.next_attempt_at = finished + timedelta(
                    seconds=WEBHOOK_RETRY_SECONDS[attempt_no - 1])
        if endpoint is not None and endpoint.lease_token == claim.lease_token:
            endpoint.lease_token = None
            endpoint.lease_until = None
    logger.info(
        "Webhook delivery event=%s endpoint=%s attempt=%d status=%s error=%s finished_at=%s",
        claim.event_id, claim.endpoint_id, attempt_no, result.http_status,
        result.error_class, finished.isoformat())


async def dispatch_webhooks_once() -> int:
    """Claim and concurrently deliver one bounded batch."""
    claims = await _claim_webhook_deliveries()
    if claims:
        await asyncio.gather(*(_deliver_claim(claim) for claim in claims))
    return len(claims)


async def expire_trial_keys() -> int:
    """Record clock-driven trial expiry under the tenant billing lock."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=TRIAL_DAYS)
    async with AsyncSessionLocal() as session:
        candidates = (await session.execute(select(ApiKey.id, ApiKey.tenant_id).where(
            ApiKey.is_active.is_(True), ApiKey.subscription_state == "trial",
            ApiKey.created_at < cutoff))).all()
    expired = 0
    for key_id, tenant_id in candidates:
        async with AsyncSessionLocal.begin() as session:
            await lock_tenant(session, tenant_id)
            record = await session.get(ApiKey, key_id, with_for_update=True)
            if record is None or not record.is_active or record.subscription_state != "trial":
                continue
            created = record.created_at
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            if created + timedelta(days=TRIAL_DAYS) > now:
                continue
            record.subscription_state = "trial_expired"
            record.state_version += 1
            session.add(TransitionLog(
                event_id=f"trial-expired:{record.id}", key_id=record.id,
                subscription_id=None, source="scheduler", occurred_at=now,
                old_state="trial", new_state="trial_expired", disposition="applied",
                reason_code="trial_period_elapsed",
                key_version=record.state_version))
            await session.flush()
            session.add(LifecycleNotice(event_id=f"trial-expired:{record.id}",
                                        kind="entitlement_changed"))
            expired += 1
    return expired


async def send_trial_expiry_emails() -> int:
    """Send each trial notice once when an address is available."""
    sent = 0
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        records = (await session.scalars(select(ApiKey).where(
            ApiKey.tier == "trial", ApiKey.is_active.is_(True),
            or_(ApiKey.subscription_state.is_(None),
                ApiKey.subscription_state.in_(("trial", "trial_expired")))))).all()
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
        candidates = (await session.execute(select(ApiKey.id, ApiKey.paddle_subscription_id, ApiKey.tenant_id).where(
            ApiKey.is_active.is_(True), ApiKey.cancelled_at.isnot(None),
            ApiKey.cancelled_at < cutoff))).all()
    cleaned_tenants: set[str] = set()
    for candidate_id, subscription_id, tenant_id in candidates:
        if tenant_id in cleaned_tenants:
            continue
        async with AsyncSessionLocal.begin() as session:
            await lock_tenant(session, tenant_id)
            # One ordered lock acquisition covers every key in this tenant.
            siblings = (await session.scalars(select(ApiKey).where(
                ApiKey.tenant_id == tenant_id).order_by(ApiKey.id)
                .with_for_update().execution_options(populate_existing=True))).all()
            key = next((sibling for sibling in siblings if sibling.id == candidate_id), None)
            if key is None:
                continue
            cancelled_at = key.cancelled_at
            if cancelled_at is not None and cancelled_at.tzinfo is None:
                cancelled_at = cancelled_at.replace(tzinfo=timezone.utc)
            if (cancelled_at is None or not key.is_active or cancelled_at >= cutoff
                    or key.paddle_subscription_id != subscription_id):
                continue
            now = datetime.now(timezone.utc)
            pending_purchase = await session.scalar(select(CheckoutIntent.id).where(
                CheckoutIntent.tenant_id == tenant_id,
                CheckoutIntent.consumed_at.is_(None), CheckoutIntent.expires_at > now).limit(1))
            repair_hold = await session.scalar(select(ProviderRepairQuarantine.key_id).where(
                ProviderRepairQuarantine.tenant_id == tenant_id).limit(1))
            if pending_purchase is not None or repair_hold is not None:
                continue
            expired = []
            retained = False
            for sibling in siblings:
                stamp = sibling.cancelled_at
                if stamp is not None and stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                if sibling.is_active and stamp is not None and stamp < cutoff:
                    expired.append(sibling)
                elif entitlement_decision(sibling, now).protects_tenant:
                    retained = True
            if not expired:
                continue
            for sibling in expired:
                sibling.is_active = False
                sibling.subscription_state = "cleaned_up"
                sibling.state_version += 1
            for expired_key in expired:
                event_id = f"retention:{hashlib.sha256(tenant_id.encode()).hexdigest()}:{expired_key.id}"
                session.add(TransitionLog(
                    event_id=event_id, key_id=expired_key.id,
                    subscription_id=expired_key.paddle_subscription_id,
                    source="scheduler", occurred_at=datetime.now(timezone.utc),
                    old_state="cancelled", new_state="cleaned_up", disposition="applied",
                    reason_code="retention_elapsed", key_version=expired_key.state_version))
            await session.flush()
            for expired_key in expired:
                event_id = f"retention:{hashlib.sha256(tenant_id.encode()).hexdigest()}:{expired_key.id}"
                session.add(LifecycleNotice(event_id=event_id, kind="entitlement_changed"))
            cleaned += len(expired)
            cleaned_tenants.add(tenant_id)
            if retained:
                owner = await session.get(ProjectBillingOwner, tenant_id, with_for_update=True)
                if owner is not None and any(sibling.id == owner.billing_key_id for sibling in expired):
                    entitled_payers = [sibling for sibling in siblings
                                       if entitlement_decision(sibling, now).protects_tenant]
                    live_payers = [sibling for sibling in siblings if sibling.is_active]
                    replacement = (entitled_payers[0] if len(entitled_payers) == 1 else
                                   live_payers[0] if len(live_payers) == 1 else None)
                    if replacement is not None:
                        owner.billing_key_id = replacement.id
                        owner.trial_started_at = replacement.created_at
                logger.info("Expired %d cancelled keys for tenant %s; retained key keeps data", len(expired), tenant_id)
                continue
            # A deleted tenant has one terminal state across every sibling.
            # Revoked credentials cannot later make an emptied tenant look live.
            terminal_notices: list[str] = []
            for sibling in siblings:
                if sibling not in expired and sibling.subscription_state != "cleaned_up":
                    previous_state = effective_state(sibling, now)
                    sibling.is_active = False
                    sibling.subscription_state = "cleaned_up"
                    sibling.state_version += 1
                    event_id = f"retention:{hashlib.sha256(tenant_id.encode()).hexdigest()}:{sibling.id}"
                    session.add(TransitionLog(
                        event_id=event_id, key_id=sibling.id,
                        subscription_id=sibling.paddle_subscription_id,
                        source="scheduler", occurred_at=now,
                        old_state=previous_state, new_state="cleaned_up",
                        disposition="applied", reason_code="tenant_retention_elapsed",
                        key_version=sibling.state_version))
                    terminal_notices.append(event_id)
            await session.flush()
            for event_id in terminal_notices:
                session.add(LifecycleNotice(event_id=event_id, kind="entitlement_changed"))
            project_ids = select(Domain.id).where(Domain.tenant_id == tenant_id)
            # Fence claims/finalization before taking locks on their children.
            await session.execute(select(WebhookEndpoint.id).where(
                WebhookEndpoint.project_id.in_(project_ids)
            ).order_by(WebhookEndpoint.id).with_for_update())
            endpoint_ids = select(WebhookEndpoint.id).where(
                WebhookEndpoint.project_id.in_(project_ids))
            delivery_ids = select(WebhookDelivery.id).where(
                WebhookDelivery.endpoint_id.in_(endpoint_ids))
            await session.execute(delete(WebhookAttempt).where(
                WebhookAttempt.delivery_id.in_(delivery_ids)))
            await session.execute(delete(WebhookDelivery).where(
                WebhookDelivery.endpoint_id.in_(endpoint_ids)))
            await session.execute(delete(ProjectRequest).where(ProjectRequest.project_id.in_(project_ids)))
            await session.execute(delete(WebhookEvent).where(WebhookEvent.project_id.in_(project_ids)))
            await session.execute(delete(WebhookEndpoint).where(
                WebhookEndpoint.project_id.in_(project_ids)))
            await session.execute(delete(ProjectExportSlot).where(ProjectExportSlot.project_id.in_(project_ids)))
            await session.execute(delete(Prediction).where(Prediction.project_id.in_(project_ids)))
            await session.execute(delete(ConnectorConfigRow).where(ConnectorConfigRow.tenant_id == tenant_id))
            await session.execute(delete(LabelLog).where(LabelLog.tenant_id == tenant_id))
            await session.execute(delete(Engine).where(Engine.tenant_id == tenant_id))
            await session.execute(delete(Annotator).where(Annotator.tenant_id == tenant_id))
            await session.execute(delete(Domain).where(Domain.tenant_id == tenant_id))
            logger.info("Cleaned up cancelled tenant %s and %d keys", tenant_id, len(expired))
    return cleaned


async def run_scheduled_tasks() -> None:
    """Run scheduled jobs while keeping the next hourly attempt alive on error."""
    try:
        await expire_trial_keys()
        emails = await send_trial_expiry_emails()
        cleaned = await cleanup_cancelled_tenants()
        if emails or cleaned:
            logger.info("Scheduler: %d trial emails, %d expired keys cleaned", emails, cleaned)
    except Exception as exc:
        try:
            logger.error("Scheduler error: %s", sanitize_database_error(exc))
        except Exception:
            logger.error("Scheduler error: %s (details withheld)", type(exc).__name__)


async def scheduler_loop() -> None:
    """Dispatch webhooks every two seconds and run maintenance hourly."""
    loop = asyncio.get_running_loop()
    next_maintenance = loop.time() + 3600
    while True:
        await asyncio.sleep(2)
        try:
            await dispatch_webhooks_once()
        except Exception as exc:
            try:
                logger.error("Webhook dispatcher error: %s", sanitize_database_error(exc))
            except Exception:
                logger.error("Webhook dispatcher error: %s (details withheld)", type(exc).__name__)
        if loop.time() >= next_maintenance:
            await run_scheduled_tasks()
            next_maintenance = loop.time() + 3600
