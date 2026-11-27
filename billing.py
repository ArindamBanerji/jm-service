"""Paddle subscription webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import asyncio
import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Session, Tenant
from db.connection import AsyncSessionLocal, commit_write, sanitize_database_error
from db.entitlement import effective_state, require_payer_eligibility
from db.models import ApiKey, CheckoutIntent, LifecycleNotice, PaddleWebhookEvent, ProjectBillingOwner, ProviderRepairManifest, ProviderRepairQuarantine, SubscriptionBinding, TransitionLog
from db.tenant_lock import lock_tenant

router = APIRouter(prefix="/v1/billing", tags=["Billing"])
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_BILLING_READERS = 4
BILLING_READ_TIMEOUT_SECONDS = 30
_billing_reader_slots = asyncio.BoundedSemaphore(MAX_BILLING_READERS)
_billing_waiters = 0

TIER_VOLUME_CAPS: dict[str, int | None] = {
    "trial": 50,  # per day
    "starter": 10_000,
    "professional": 100_000,
    "business": 1_000_000,
    "scale": None,
    "enterprise": None,
}

PADDLE_TIER_MAP = {
    "DLJ Starter": "starter",
    "DLJ Professional": "professional",
    "DLJ Business": "business",
    "DLJ Scale": "scale",
}
PADDLE_TRANSACTION_RE = re.compile(r"txn_[A-Za-z0-9]+")

EVENT_TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "subscription.created": {
        state: {"active"} for state in
        ("trial", "trial_expired", "active", "past_due", "paused", "cancelled")
    },
    "subscription.updated": {
        "active": {"active", "past_due", "paused", "cancelled"},
        "past_due": {"active", "past_due", "paused", "cancelled"},
        "paused": {"active", "past_due", "paused", "cancelled"},
        "cancelled": {"cancelled"},
    },
    "subscription.canceled": {
        state: {"cancelled"} for state in ("active", "past_due", "paused", "cancelled")
    },
}


def _validate_transition(event_type: str, old: str, new: str) -> None:
    if new not in EVENT_TRANSITIONS.get(event_type, {}).get(old, set()):
        raise HTTPException(409, "Invalid subscription transition")


def _current_state(record: ApiKey) -> str:
    return effective_state(record)


def _next_state(event_type: str, payload: dict, old: str) -> str:
    if event_type == "subscription.canceled" or payload.get("status") == "canceled":
        return "cancelled"
    if event_type == "subscription.created":
        return "active"
    status = payload.get("status")
    if status is not None and not isinstance(status, str):
        raise HTTPException(422, "Invalid subscription status")
    if status in {"active", "past_due", "paused"}:
        return status
    if status is None:
        return old  # Product-only historical updates retain their entitlement state.
    raise HTTPException(422, "Unsupported subscription status")


def verify_paddle_signature(raw_body: bytes, header: str, secret: str) -> bool:
    """Verify Paddle-Signature using HMAC-SHA256(secret, timestamp:raw_body)."""
    if not header or not secret:
        return False
    timestamp = ""
    signatures = []
    for segment in header.split(";"):
        if "=" in segment:
            key, value = segment.split("=", 1)
            if key.strip() == "ts":
                if timestamp:
                    return False
                timestamp = value.strip()
            elif key.strip() == "h1" and re.fullmatch(r"[0-9a-fA-F]{64}", value.strip()):
                signatures.append(value.strip().lower())
    if not re.fullmatch(r"[0-9]+", timestamp) or not signatures:
        return False
    signed_payload = timestamp.encode() + b":" + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)


def paddle_transaction_url() -> str:
    mode = os.environ.get("PADDLE_SANDBOX", "true").strip().lower()
    if mode == "true":
        return "https://sandbox-api.paddle.com/transactions"
    if mode == "false":
        return "https://api.paddle.com/transactions"
    raise ValueError("Invalid PADDLE_SANDBOX")


def paddle_prices() -> dict[str, str]:
    prices: dict[str, str] = {}
    for pair in os.environ.get("PADDLE_PRICE_MAP", "").split(","):
        tier, separator, price = pair.strip().partition("=")
        tier, price = tier.strip(), price.strip()
        if (not separator or not tier or not price.startswith("pri_") or len(price) <= 4
                or not price[4:].isascii() or not price[4:].isalnum() or tier in prices):
            raise ValueError("Invalid PADDLE_PRICE_MAP")
        prices[tier] = price
    return prices


@router.get("/checkout-url")
async def get_checkout_url(tenant: Tenant, session: Session, tier: str = "starter") -> dict[str, str]:
    """Bind the Paddle transaction to the purchasing key."""
    try:
        prices = paddle_prices()
        api_url = paddle_transaction_url()
    except ValueError:
        raise HTTPException(503, "Checkout configuration is unavailable") from None
    price_id = prices.get(tier)
    if not price_id:
        raise HTTPException(400, "Unknown checkout tier")
    api_key = os.environ.get("PADDLE_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Paddle API key not configured")
    key_id = await session.scalar(select(ApiKey.id).where(
        ApiKey.tenant_id == tenant, ApiKey.key_hash == session.info["api_key_hash"],
        ApiKey.is_active.is_(True)))
    if key_id is None:
        raise HTTPException(401, "Invalid API key")
    await lock_tenant(session, tenant)
    if await session.scalar(select(ProviderRepairQuarantine.key_id).where(
            ProviderRepairQuarantine.tenant_id == tenant)) is not None:
        raise HTTPException(409, "Historical billing ownership requires reconciliation")
    owner = await session.get(ProjectBillingOwner, tenant)
    if owner is None:
        siblings = (await session.scalars(select(ApiKey.id).where(
            ApiKey.tenant_id == tenant, ApiKey.is_active.is_(True)).limit(2))).all()
        if len(siblings) != 1:
            raise HTTPException(400, "Billing payer is ambiguous; establish an owner first")
        payer_id = siblings[0]
        payer = await session.get(ApiKey, payer_id)
        assert payer is not None
        session.add(ProjectBillingOwner(owner_tenant_id=tenant, billing_key_id=payer_id,
                                        trial_started_at=payer.created_at))
    else:
        payer_id = owner.billing_key_id
    locked_keys = (await session.scalars(select(ApiKey).where(
        ApiKey.id.in_({key_id, payer_id}), ApiKey.tenant_id == tenant)
        .order_by(ApiKey.id).with_for_update().execution_options(populate_existing=True))).all()
    keys_by_id = {record.id: record for record in locked_keys}
    purchaser = keys_by_id.get(key_id)
    payer = keys_by_id.get(payer_id)
    if (purchaser is None or not purchaser.is_active
            or purchaser.key_hash != session.info.get("api_key_hash") or payer is None):
        raise HTTPException(409, "Billing identities changed; retry checkout")
    require_payer_eligibility(payer, "purchase")
    session.info["payer_key_id"] = payer.id
    intent = CheckoutIntent(id=uuid4(), tenant_id=tenant, purchaser=key_id,
                            payer=payer_id, tier=tier,
                            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))
    session.add(intent)
    await commit_write(session)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"items": [{"price_id": price_id, "quantity": 1}],
                      "collection_mode": "automatic",
                      "custom_data": {"tenant_id": tenant, "key_id": str(key_id),
                                      "checkout_intent_id": str(intent.id)}},
            )
            response.raise_for_status()
            transaction_id = response.json().get("data", {}).get("id")
            checkout_url = response.json().get("data", {}).get("checkout", {}).get("url")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        logger.error("Paddle checkout failed: %s", sanitize_database_error(exc))
        raise HTTPException(502, "Could not create Paddle checkout") from None
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise HTTPException(502, "Paddle did not return a checkout URL")
    if (not isinstance(transaction_id, str) or len(transaction_id) > 200
            or PADDLE_TRANSACTION_RE.fullmatch(transaction_id) is None):
        raise HTTPException(502, "Paddle did not return a transaction ID")
    intent.transaction_id = transaction_id
    await commit_write(session)
    return {"checkout_url": checkout_url, "tier": tier}


def _product_tier(payload: dict, event_type: str) -> str | None:
    items = payload.get("items", [])
    if items == [] and event_type != "subscription.created":
        return None  # Status-only notifications can omit the line items.
    first = items[0] if isinstance(items, list) and items else None
    product = first.get("product") if isinstance(first, dict) else None
    name = product.get("name") if isinstance(product, dict) else None
    if not isinstance(name, str) or name not in PADDLE_TIER_MAP:
        logger.warning("Unrecognized Paddle product type: %s", type(name).__name__)
        raise HTTPException(400, "Unknown product")
    return PADDLE_TIER_MAP[name]


def _occurred_at(value: object) -> datetime:
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is not None:
                return stamp.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            pass
    raise HTTPException(422, "Invalid occurred_at")


async def _checkout_key(session: AsyncSession, customer_id: str, custom: dict,
                        tier: str | None, transaction_id: object,
                        subscription_id: str) -> ApiKey:
    locked = select(ApiKey).with_for_update()
    intent_id = custom.get("checkout_intent_id")
    if intent_id is not None:
        try:
            intent = await session.get(CheckoutIntent, UUID(str(intent_id)), with_for_update=True)
        except (TypeError, ValueError):
            raise HTTPException(409, "Invalid checkout intent") from None
        if intent is None or intent.consumed_at is not None or intent.tenant_id != custom.get("tenant_id"):
            raise HTTPException(409, "Checkout intent is unavailable")
        if (str(intent.purchaser) != custom.get("key_id") or tier != intent.tier
                or not isinstance(transaction_id, str)
                or transaction_id != intent.transaction_id):
            raise HTTPException(409, "Checkout delivery does not match purchase")
        expires = intent.expires_at if intent.expires_at.tzinfo else intent.expires_at.replace(tzinfo=timezone.utc)
        record = await session.scalar(locked.where(
            ApiKey.id == intent.payer, ApiKey.tenant_id == intent.tenant_id))
        if record is None:
            raise HTTPException(409, "Billing payer is unavailable")
        if record.subscription_state == "cleaned_up":
            raise HTTPException(409, "Purchase requires reconciliation after retention")
        require_payer_eligibility(record, "purchase")
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(409, "Checkout intent expired")
        if record.paddle_customer_id is not None and record.paddle_customer_id != customer_id:
            raise HTTPException(409, "Checkout customer does not match payer")
        return record
    record = await session.scalar(locked.where(ApiKey.paddle_customer_id == customer_id))
    tenant = custom.get("tenant_id")
    if record is not None:
        historical = await session.get(ProviderRepairManifest, record.id)
        if (historical is None or historical.customer_id != customer_id
                or historical.subscription_id != subscription_id):
            raise HTTPException(409, "New purchases require a checkout intent")
        if await session.scalar(select(CheckoutIntent.id).where(
                or_(CheckoutIntent.payer == record.id, CheckoutIntent.purchaser == record.id)).limit(1)) is not None:
            raise HTTPException(409, "Historical billing ownership requires reconciliation")
        require_payer_eligibility(record, "purchase")
        if tenant is not None and record.tenant_id != tenant:
            raise HTTPException(409, "Customer belongs to a different tenant")
        if "key_id" in custom and str(record.id) != str(custom["key_id"]):
            raise HTTPException(409, "Checkout key conflicts with customer")
        return record
    if not isinstance(tenant, str) or not tenant:
        raise HTTPException(409, "No API key linked to this checkout")
    # Only a reconciled pre-A provider mapping may use the legacy customer path.
    raise HTTPException(409, "New purchases require a checkout intent")


async def _update_contact(session: AsyncSession, record: ApiKey, customer: object) -> None:
    email = customer.get("email") if isinstance(customer, dict) else None
    if not isinstance(email, str) or not email:
        return
    if len(email) > 200:
        logger.warning("Paddle contact email exceeds storage limit")
        return
    try:
        async with session.begin_nested():
            record.contact_email = email
            await session.flush()
    except IntegrityError:
        logger.warning("Paddle contact email conflicts with an existing API key")


@asynccontextmanager
async def _billing_session() -> AsyncIterator[AsyncSession]:
    try:
        async with AsyncSessionLocal.begin() as session:
            yield session
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Paddle database operation failed: %s", sanitize_database_error(exc))
        raise HTTPException(500, "Billing processing failed") from None


async def _record_delivery_decision(event_id: str, occurred_at: datetime,
                                    disposition: str, reason_code: str,
                                    subscription_id: str | None = None,
                                    key_id: UUID | None = None) -> None:
    """Audit an attempt without marking retryable deliveries as processed."""
    async with _billing_session() as session:
        session.add(TransitionLog(
            event_id=f"decision:{uuid4().hex}", key_id=key_id,
            subscription_id=subscription_id, source="paddle",
            actor_ref=event_id, occurred_at=occurred_at,
            old_state=None, new_state=None, disposition=disposition,
            reason_code=reason_code))


async def _receipt_was_applied(session: AsyncSession, event_id: str, *, repair: bool = False) -> bool:
    """Treat only successfully applied deliveries as terminal duplicates."""
    receipt = await session.get(PaddleWebhookEvent, event_id, with_for_update=repair,
                                populate_existing=True)
    if receipt is None:
        return False
    applied = await session.scalar(select(TransitionLog.event_id).where(
        TransitionLog.event_id == event_id,
        TransitionLog.disposition == "applied").limit(1))
    legacy_applied = await session.scalar(select(ApiKey.id).where(
        ApiKey.paddle_event_id == event_id).limit(1))
    if applied is not None or legacy_applied is not None:
        return True
    # Older builds inserted a receipt for stale/rejected attempts.  Removing
    # that non-terminal marker makes the next delivery a genuine retry.
    if repair:
        await session.delete(receipt)
        await session.flush()
    return False


@router.post("/webhook")
async def paddle_webhook(request: Request) -> dict[str, str]:
    global _billing_waiters
    if _billing_reader_slots.locked() or _billing_waiters >= MAX_BILLING_READERS:
        raise HTTPException(503, "Billing intake is busy")
    _billing_waiters += 1
    try:
        await asyncio.wait_for(_billing_reader_slots.acquire(), timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "Billing intake is busy") from None
    finally:
        _billing_waiters -= 1
    try:
        async with asyncio.timeout(BILLING_READ_TIMEOUT_SECONDS):
            return await _process_paddle_webhook(request)
    except HTTPException as exc:
        context = getattr(request.state, "billing_event", None)
        if context is not None:
            try:
                reason = {
                    "Invalid subscription transition": "invalid_transition",
                    "Checkout delivery does not match purchase": "checkout_mismatch",
                    "Checkout customer does not match payer": "customer_mismatch",
                    "Checkout key conflicts with customer": "legacy_key_conflict",
                    "New subscription is not active": "inactive_new_subscription",
                    "Historical billing ownership requires reconciliation": "provider_repair_hold",
                    "Unknown subscription ID": "unknown_subscription",
                    "Purchase requires reconciliation after retention": "purchase_after_retention",
                }.get(exc.detail, f"http_{exc.status_code}") if isinstance(exc.detail, str) else f"http_{exc.status_code}"
                await _record_delivery_decision(
                    context["event_id"], context["occurred_at"], "rejected",
                    reason, context.get("subscription_id"),
                    context.get("key_id"))
            except Exception as audit_exc:
                logger.error("Paddle rejection audit failed: %s", sanitize_database_error(audit_exc))
        raise
    except TimeoutError:
        raise HTTPException(408, "Billing request timed out") from None
    finally:
        _billing_reader_slots.release()


async def _process_paddle_webhook(request: Request) -> dict[str, str]:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > MAX_WEBHOOK_BYTES:
                raise HTTPException(413, "Webhook body too large")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length") from None
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "Webhook body too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    secret = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
    if not secret.strip():
        raise HTTPException(503, "Webhook secret not configured")
    signature = request.headers.get("Paddle-Signature", "")
    if not verify_paddle_signature(body, signature, secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        data = json.loads(body)
        event_type = data.get("event_type", "")
        payload = data.get("data", {})
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(422, "Invalid webhook payload") from exc
    if not isinstance(payload, dict) or not isinstance(event_type, str):
        raise HTTPException(422, "Invalid webhook data")

    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 200:
        raise HTTPException(422, "Invalid event_id")
    occurred_at = _occurred_at(data.get("occurred_at"))
    subscription_id = payload.get("id")
    request.state.billing_event = {
        "event_id": event_id, "occurred_at": occurred_at,
        "subscription_id": subscription_id if isinstance(subscription_id, str) and len(subscription_id) <= 200 else None}
    if event_type not in {"subscription.created", "subscription.updated", "subscription.canceled"}:
        async with _billing_session() as session:
            disposition, reason = "rejected", "unknown_event"
            if await _receipt_was_applied(session, event_id):
                disposition, reason = "duplicate", "duplicate_event"
            session.add(TransitionLog(
                event_id=f"decision:{uuid4().hex}", source="paddle", actor_ref=event_id,
                subscription_id=request.state.billing_event["subscription_id"],
                occurred_at=occurred_at, disposition=disposition, reason_code=reason))
        return {"status": "ok"}
    if not isinstance(subscription_id, str) or not 0 < len(subscription_id) <= 200:
        raise HTTPException(422, "Missing subscription ID")
    transaction_id = payload.get("transaction_id")
    if (event_type == "subscription.created"
            and (not isinstance(transaction_id, str)
                 or len(transaction_id) > 200
                 or PADDLE_TRANSACTION_RE.fullmatch(transaction_id) is None)):
        raise HTTPException(422, "Invalid provider transaction ID")

    is_cancellation = (event_type == "subscription.canceled" or
                       (event_type == "subscription.updated" and payload.get("status") == "canceled"))

    customer_id = payload.get("customer_id")
    custom = payload.get("custom_data")
    if custom is None:
        custom = {}
    if event_type == "subscription.created":
        if not isinstance(customer_id, str) or not 0 < len(customer_id) <= 200:
            raise HTTPException(422, "Missing customer ID")
        if not isinstance(custom, dict):
            raise HTTPException(422, "Invalid checkout metadata")
        if "tenant_id" in custom and (not isinstance(custom["tenant_id"], str)
                                      or not 0 < len(custom["tenant_id"]) <= 200):
            raise HTTPException(422, "Invalid checkout tenant ID")
        if "checkout_intent_id" in custom:
            try:
                UUID(str(custom["checkout_intent_id"]))
            except ValueError:
                raise HTTPException(409, "Invalid checkout intent") from None
        if payload.get("status") not in (None, "active"):
            raise HTTPException(409, "New subscription is not active")
    if event_type == "subscription.updated":
        _next_state(event_type, payload, "active")

    # Cancellation is identified by subscription ID; line items are irrelevant.
    if is_cancellation:
        tier = None
    else:
        tier = _product_tier(payload, event_type)
    async with _billing_session() as session:
        if await _receipt_was_applied(session, event_id):
            session.add(TransitionLog(
                event_id=f"decision:{uuid4().hex}", key_id=None,
                subscription_id=subscription_id, source="paddle", actor_ref=event_id,
                occurred_at=occurred_at, old_state=None, new_state=None,
                disposition="duplicate", reason_code="duplicate_event"))
            return {"status": "ok"}

        if event_type == "subscription.created":
            tenant_id = custom.get("tenant_id") or await session.scalar(select(ApiKey.tenant_id).where(
                ApiKey.paddle_customer_id == customer_id))
            if tenant_id is None:
                raise HTTPException(409, "Checkout tenant is unavailable")
        else:
            tenant_id = await session.scalar(select(ApiKey.tenant_id).where(
                ApiKey.paddle_subscription_id == subscription_id))
            if tenant_id is None:
                raise HTTPException(409, "Unknown subscription ID")
        await lock_tenant(session, tenant_id)
        if await _receipt_was_applied(session, event_id, repair=True):
            session.add(TransitionLog(event_id=f"decision:{uuid4().hex}", source="paddle",
                                      actor_ref=event_id, subscription_id=subscription_id,
                                      occurred_at=occurred_at, disposition="duplicate",
                                      reason_code="duplicate_event"))
            return {"status": "ok"}

        record: ApiKey | None
        if event_type == "subscription.created":
            assert isinstance(customer_id, str)
            record = await _checkout_key(session, customer_id, custom, tier, transaction_id, subscription_id)
        else:
            record = await session.scalar(select(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.paddle_subscription_id == subscription_id).with_for_update())
            if record is None:
                raise HTTPException(409, "Unknown subscription ID")
        request.state.billing_event["key_id"] = record.id

        # SQLite returns naive datetimes for UTC columns. PostgreSQL preserves the zone.
        for timestamp in (record.paddle_event_occurred_at, record.cancelled_at):
            if timestamp is not None:
                stored = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
                stored_event_id = record.paddle_event_id or ""
                tied = occurred_at == stored
                same_subscription = subscription_id == record.paddle_subscription_id
                # Effective cancellation takes precedence over a simultaneous status
                # update on this subscription, in either delivery order.
                if tied and same_subscription and is_cancellation != (_current_state(record) == "cancelled"):
                    stale = not is_cancellation
                else:
                    stale = (occurred_at, event_id) <= (stored, stored_event_id)
                if stale:
                    session.add(TransitionLog(
                        event_id=f"decision:{uuid4().hex}", key_id=record.id,
                        subscription_id=subscription_id, source="paddle", actor_ref=event_id,
                        occurred_at=occurred_at, old_state=_current_state(record),
                        new_state=_current_state(record), disposition="stale",
                        reason_code="older_than_watermark"))
                    return {"status": "ok"}
        old_state = _current_state(record)
        if (event_type == "subscription.created" and old_state == "cancelled"
                and record.paddle_subscription_id == subscription_id):
            raise HTTPException(409, "Resubscription requires a new subscription ID")
        next_state = _next_state(event_type, payload, old_state)
        if next_state == "active" and await session.scalar(select(ProviderRepairQuarantine.key_id).where(
                ProviderRepairQuarantine.tenant_id == record.tenant_id)) is not None:
            raise HTTPException(409, "Historical billing ownership requires reconciliation")
        _validate_transition(event_type, old_state, next_state)
        try:
            async with session.begin_nested():
                session.add(PaddleWebhookEvent(event_id=event_id))
                await session.flush()
        except IntegrityError:
            session.add(TransitionLog(
                event_id=f"decision:{uuid4().hex}", key_id=record.id,
                subscription_id=subscription_id, source="paddle", actor_ref=event_id,
                occurred_at=occurred_at, old_state=old_state, new_state=old_state,
                disposition="duplicate", reason_code="duplicate_event"))
            return {"status": "ok"}
        entitlement_changed = (next_state != old_state or
                               (tier is not None and tier != record.tier) or
                               (event_type == "subscription.created" and
                                record.paddle_subscription_id != subscription_id))
        if next_state != old_state:
            record.subscription_state = next_state
        if entitlement_changed:
            record.state_version += 1
        if event_type == "subscription.created" and isinstance(custom, dict) and custom.get("checkout_intent_id"):
            intent = await session.get(CheckoutIntent, UUID(str(custom["checkout_intent_id"])))
            assert intent is not None
            intent.consumed_at = datetime.now(timezone.utc)
        session.add(TransitionLog(
            event_id=event_id, key_id=record.id, subscription_id=subscription_id,
            source="paddle", actor_ref=customer_id if event_type == "subscription.created" else None,
            occurred_at=occurred_at, old_state=old_state, new_state=next_state,
            disposition="applied", reason_code=event_type,
            key_version=record.state_version))
        if entitlement_changed:
            await session.flush()
            session.add(LifecycleNotice(event_id=event_id, kind=(
                "cancellation_scheduled" if next_state == "cancelled" else "entitlement_changed")))
        record.paddle_event_id = event_id
        record.paddle_event_occurred_at = occurred_at
        if is_cancellation:
            record.cancelled_at = occurred_at
        else:
            if tier is not None:
                record.tier = tier
            if event_type == "subscription.created" or payload.get("status") == "active":
                record.cancelled_at = None
            if event_type == "subscription.created":
                current_binding = await session.scalar(select(SubscriptionBinding).where(
                    SubscriptionBinding.payer == record.id,
                    SubscriptionBinding.retired_at.is_(None)).with_for_update())
                if current_binding is not None and current_binding.subscription_id != subscription_id:
                    current_binding.retired_at = occurred_at
                    await session.flush()
                if current_binding is None or current_binding.subscription_id != subscription_id:
                    session.add(SubscriptionBinding(subscription_id=subscription_id,
                                                    payer=record.id, customer_id=customer_id))
                record.paddle_customer_id = customer_id
                record.paddle_subscription_id = subscription_id
                try:
                    await session.flush()
                except IntegrityError as exc:
                    raise HTTPException(409, "Customer already linked to another API key") from exc
                await _update_contact(session, record, payload.get("customer"))

    return {"status": "ok"}
