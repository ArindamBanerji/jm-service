"""Paddle subscription webhooks."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Session, Tenant
from db.connection import AsyncSessionLocal
from db.models import ApiKey, PaddleWebhookEvent

router = APIRouter(prefix="/v1/billing", tags=["Billing"])
logger = logging.getLogger(__name__)

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
                      "custom_data": {"tenant_id": tenant, "key_id": str(key_id)}},
            )
            response.raise_for_status()
            checkout_url = response.json().get("data", {}).get("checkout", {}).get("url")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Could not create Paddle checkout") from exc
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise HTTPException(502, "Paddle did not return a checkout URL")
    return {"checkout_url": checkout_url, "tier": tier}


def _product_tier(payload: dict, event_type: str) -> str | None:
    items = payload.get("items", [])
    if items == [] and event_type != "subscription.created":
        return None  # Status-only notifications can omit the line items.
    first = items[0] if isinstance(items, list) and items else None
    product = first.get("product") if isinstance(first, dict) else None
    name = product.get("name") if isinstance(product, dict) else None
    if not isinstance(name, str) or name not in PADDLE_TIER_MAP:
        logger.warning("Unrecognized Paddle product: %r", name[:200] if isinstance(name, str) else type(name).__name__)
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
    record = await session.scalar(candidates.order_by(ApiKey.created_at, ApiKey.id).limit(1))
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


@router.post("/webhook")
async def paddle_webhook(request: Request) -> dict[str, str]:
    body = await request.body()
    secret = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
    if not secret.strip():
        if os.environ.get("PADDLE_SANDBOX") != "true":
            raise HTTPException(503, "Webhook secret not configured")
        secret = ""
    signature = request.headers.get("Paddle-Signature", "")
    if secret and not verify_paddle_signature(body, signature, secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        data = await request.json()
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
    async with AsyncSessionLocal.begin() as session:
        session.add(PaddleWebhookEvent(event_id=event_id))
        try:
            await session.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "Webhook event already processed") from exc

        record: ApiKey | None
        if event_type == "subscription.created":
            customer_id = payload.get("customer_id")
            if not isinstance(customer_id, str) or not 0 < len(customer_id) <= 200:
                raise HTTPException(422, "Missing customer ID")
            custom = payload.get("custom_data")
            record = await _checkout_key(session, customer_id, custom if isinstance(custom, dict) else {})
        else:
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
                record.paddle_customer_id = customer_id
                record.paddle_subscription_id = subscription_id
                try:
                    await session.flush()
                except IntegrityError as exc:
                    raise HTTPException(409, "Customer already linked to another API key") from exc
                await _update_contact(session, record, payload.get("customer"))

    return {"status": "ok"}
