"""Paddle subscription webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import asyncio
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
from db.models import ApiKey, CheckoutIntent, PaddleWebhookEvent, ProjectBillingOwner, ProviderRepairQuarantine, SubscriptionBinding, TransitionLog
from db.tenant_lock import lock_tenant

router = APIRouter(prefix="/v1/billing", tags=["Billing"])
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BYTES = 64 * 1024
MAX_BILLING_READERS = 4
BILLING_READ_TIMEOUT_SECONDS = 30
_billing_reader_slots = asyncio.BoundedSemaphore(MAX_BILLING_READERS)

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

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "trial": {"active", "trial_expired"},
    "trial_expired": {"active"},
    "active": {"past_due", "paused", "cancelled"},
    "past_due": {"active", "paused", "cancelled"},
    "paused": {"active", "past_due", "cancelled"},
    "cancelled": {"active", "cleaned_up"},
    "cleaned_up": set(),
}


def _current_state(record: ApiKey) -> str:
    if record.subscription_state:
        return record.subscription_state
    if record.cancelled_at is not None:
        return "cancelled"
    return "active" if record.tier != "trial" else "trial"


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
    parts: dict[str, str] = {}
    for segment in header.split(";"):
        if "=" in segment:
            key, value = segment.split("=", 1)
            parts[key.strip()] = value.strip()
    timestamp = parts.get("ts", "")
    signature = parts.get("h1", "")
    if not timestamp or not signature:
        return False
    signed_payload = timestamp.encode() + b":" + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.get("/checkout-url")
async def get_checkout_url(tenant: Tenant, session: Session, tier: str = "starter") -> dict[str, str]:
    """Bind the Paddle transaction to the purchasing key."""
    prices = dict(pair.strip().split("=", 1) for pair in
                  os.environ.get("PADDLE_PRICE_MAP", "").split(",") if "=" in pair)
    price_id = prices.get(tier)
    if not price_id:
        raise HTTPException(400, f"Unknown tier: {tier}. Available: {list(prices)}")
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
    intent = CheckoutIntent(id=uuid4(), tenant_id=tenant, purchaser=key_id,
                            payer=payer_id, tier=tier,
                            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30))
    session.add(intent)
    await commit_write(session)
    sandbox = os.environ.get("PADDLE_SANDBOX", "true").lower() == "true"
    api_url = ("https://sandbox-api.paddle.com" if sandbox else
               "https://api.paddle.com") + "/transactions"
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
    if not isinstance(transaction_id, str) or not transaction_id.startswith("txn_"):
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


async def _checkout_key(session: AsyncSession, customer_id: str, custom: dict) -> ApiKey:
    active = select(ApiKey).where(ApiKey.is_active.is_(True)).with_for_update()
    intent_id = custom.get("checkout_intent_id")
    if intent_id is not None:
        try:
            intent = await session.get(CheckoutIntent, UUID(str(intent_id)), with_for_update=True)
        except (TypeError, ValueError):
            raise HTTPException(409, "Invalid checkout intent") from None
        if intent is None or intent.consumed_at is not None or intent.tenant_id != custom.get("tenant_id"):
            raise HTTPException(409, "Checkout intent is unavailable")
        expires = intent.expires_at if intent.expires_at.tzinfo else intent.expires_at.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(409, "Checkout intent expired")
        record = await session.scalar(active.where(ApiKey.id == intent.payer, ApiKey.tenant_id == intent.tenant_id))
        if record is None:
            raise HTTPException(409, "Billing payer is unavailable")
        intent.consumed_at = datetime.now(timezone.utc)
        return record
    record = await session.scalar(active.where(ApiKey.paddle_customer_id == customer_id))
    tenant = custom.get("tenant_id")
    if record is not None:
        if tenant is not None and record.tenant_id != tenant:
            raise HTTPException(409, "Customer belongs to a different tenant")
        return record
    if not isinstance(tenant, str) or not tenant:
        raise HTTPException(409, "No API key linked to this checkout")
    candidates = active.where(ApiKey.tenant_id == tenant, or_(
        ApiKey.paddle_customer_id.is_(None), ApiKey.paddle_customer_id == customer_id))
    if "key_id" in custom:
        try:
            key_id = UUID(str(custom["key_id"]))
        except ValueError as exc:
            raise HTTPException(409, "Invalid checkout key ID") from exc
        candidates = candidates.where(ApiKey.id == key_id)
    records = (await session.scalars(candidates.order_by(ApiKey.created_at, ApiKey.id).limit(2))).all()
    if len(records) > 1:
        raise HTTPException(409, "Billing payer is ambiguous")
    record = records[0] if records else None
    if record is None:
        raise HTTPException(409, "No API key linked to this checkout")
    return record


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


@router.post("/webhook")
async def paddle_webhook(request: Request) -> dict[str, str]:
    if _billing_reader_slots.locked():
        raise HTTPException(503, "Billing intake is busy")
    try:
        await asyncio.wait_for(_billing_reader_slots.acquire(), timeout=0.01)
    except TimeoutError:
        raise HTTPException(503, "Billing intake is busy") from None
    try:
        async with asyncio.timeout(BILLING_READ_TIMEOUT_SECONDS):
            return await _process_paddle_webhook(request)
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
        if os.environ.get("PADDLE_SANDBOX") != "true":
            raise HTTPException(503, "Webhook secret not configured")
        secret = ""
    signature = request.headers.get("Paddle-Signature", "")
    if secret and not verify_paddle_signature(body, signature, secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        data = json.loads(body)
        event_type = data.get("event_type", "")
        payload = data.get("data", {})
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(422, "Invalid webhook payload") from exc
    if not isinstance(payload, dict) or not isinstance(event_type, str):
        raise HTTPException(422, "Invalid webhook data")

    if event_type not in {"subscription.created", "subscription.updated", "subscription.canceled"}:
        return {"status": "ok"}

    is_cancellation = (event_type == "subscription.canceled" or
                       (event_type == "subscription.updated" and payload.get("status") == "canceled"))

    subscription_id = payload.get("id")
    if not isinstance(subscription_id, str) or not 0 < len(subscription_id) <= 200:
        raise HTTPException(422, "Missing subscription ID")

    # Cancellation is identified by subscription ID; line items are irrelevant.
    if is_cancellation:
        tier = None
    else:
        tier = _product_tier(payload, event_type)
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 200:
        raise HTTPException(422, "Invalid event_id")
    occurred_at = _occurred_at(data.get("occurred_at"))
    async with _billing_session() as session:
        try:
            async with session.begin_nested():
                session.add(PaddleWebhookEvent(event_id=event_id))
                await session.flush()
        except IntegrityError:
            return {"status": "ok"}

        record: ApiKey | None
        if event_type == "subscription.created":
            customer_id = payload.get("customer_id")
            if not isinstance(customer_id, str) or not 0 < len(customer_id) <= 200:
                raise HTTPException(422, "Missing customer ID")
            custom = payload.get("custom_data")
            if isinstance(custom, dict) and isinstance(custom.get("tenant_id"), str):
                tenant_id = custom["tenant_id"]
            else:
                tenant_id = await session.scalar(select(ApiKey.tenant_id).where(
                    ApiKey.paddle_customer_id == customer_id,
                    ApiKey.is_active.is_(True)))
                if tenant_id is None:
                    raise HTTPException(409, "Checkout tenant is unavailable")
                custom = {}
            await lock_tenant(session, tenant_id)
            record = await _checkout_key(session, customer_id, custom)
        else:
            tenant_id = await session.scalar(select(ApiKey.tenant_id).where(
                ApiKey.paddle_subscription_id == subscription_id))
            if tenant_id is None:
                raise HTTPException(409, "Unknown subscription ID")
            await lock_tenant(session, tenant_id)
            record = await session.scalar(select(ApiKey).where(
                ApiKey.paddle_subscription_id == subscription_id).with_for_update())
            if record is None:
                raise HTTPException(409, "Unknown subscription ID")

        # SQLite returns naive datetimes for UTC columns. PostgreSQL preserves the zone.
        for timestamp in (record.paddle_event_occurred_at, record.cancelled_at):
            if timestamp is not None:
                stored = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
                if occurred_at < stored or (occurred_at == stored and not is_cancellation):
                    return {"status": "ok"}
        old_state = _current_state(record)
        next_state = _next_state(event_type, payload, old_state)
        if next_state == "active" and await session.scalar(select(ProviderRepairQuarantine.key_id).where(
                ProviderRepairQuarantine.tenant_id == record.tenant_id)) is not None:
            raise HTTPException(409, "Historical billing ownership requires reconciliation")
        if next_state != old_state and next_state not in ALLOWED_TRANSITIONS[old_state]:
            raise HTTPException(409, "Invalid subscription transition")
        if next_state != old_state:
            record.subscription_state = next_state
            record.state_version += 1
        session.add(TransitionLog(
            event_id=event_id, key_id=record.id, subscription_id=subscription_id,
            source="paddle", actor_ref=customer_id if event_type == "subscription.created" else None,
            occurred_at=occurred_at, old_state=old_state, new_state=next_state,
            disposition="applied", key_version=record.state_version))
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
