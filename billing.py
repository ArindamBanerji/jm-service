"""Lemon Squeezy subscription webhooks."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from db.connection import AsyncSessionLocal
from db.models import ApiKey

router = APIRouter(prefix="/v1/billing", tags=["Billing"])

TIER_VOLUME_CAPS: dict[str, int | None] = {
    "trial": 50,  # per day
    "starter": 10_000,
    "professional": 100_000,
    "business": 1_000_000,
    "scale": None,
    "enterprise": None,
}

LEMON_SQUEEZY_TIER_MAP = {
    "DLJ Starter": "starter",
    "DLJ Professional": "professional",
    "DLJ Business": "business",
    "DLJ Scale": "scale",
}


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def lemon_squeezy_webhook(request: Request) -> dict[str, str]:
    secret = os.environ.get("LEMON_SQUEEZY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(500, "Webhook secret not configured")
    body = await request.body()
    signature = request.headers.get("X-Signature", "")
    if not verify_webhook_signature(body, signature, secret):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        data = await request.json()
        meta = data.get("meta", {})
        event_name = meta.get("event_name", "")
        resource = data.get("data", {})
        attrs = resource.get("attributes", {})
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(422, "Invalid webhook payload") from exc
    if not isinstance(attrs, dict):
        raise HTTPException(422, "Invalid webhook attributes")

    if event_name not in {"subscription_created", "subscription_updated", "subscription_cancelled"}:
        return {"status": "ok"}

    subscription_id = str(resource.get("id") or "")
    if not subscription_id:
        raise HTTPException(422, "Missing subscription ID")
    tier = None
    if event_name != "subscription_cancelled":
        tier = LEMON_SQUEEZY_TIER_MAP.get(attrs.get("product_name", ""))
        if tier is None:
            raise HTTPException(422, "Unknown subscription product")

    async with AsyncSessionLocal() as session:
        if event_name == "subscription_created":
            customer_id = str(attrs.get("customer_id") or "")
            if not customer_id:
                raise HTTPException(422, "Missing customer ID")
            record = await session.scalar(select(ApiKey).where(
                ApiKey.lemon_squeezy_customer_id == customer_id,
                ApiKey.is_active.is_(True)))
            if record is None:
                raise HTTPException(409, "No API key linked to this checkout")
            record.lemon_squeezy_customer_id = customer_id
            record.lemon_squeezy_subscription_id = subscription_id
            record.tier = tier or "trial"
            record.cancelled_at = None

        else:
            record = await session.scalar(select(ApiKey).where(
                ApiKey.lemon_squeezy_subscription_id == subscription_id))
            if record is None:
                raise HTTPException(409, "Unknown subscription ID")
            if event_name == "subscription_updated":
                record.tier = tier or record.tier
            else:
                record.cancelled_at = datetime.now(timezone.utc)
        await session.commit()

    return {"status": "ok"}
