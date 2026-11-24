"""Paddle subscription webhooks."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_, select

from auth import Tenant
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
async def get_checkout_url(tenant: Tenant, tier: str = "starter") -> dict[str, str]:
    """Create a Paddle transaction carrying the authenticated tenant ID."""
    prices = dict(pair.strip().split("=", 1) for pair in
                  os.environ.get("PADDLE_PRICE_MAP", "").split(",") if "=" in pair)
    price_id = prices.get(tier)
    if not price_id:
        raise HTTPException(400, f"Unknown tier: {tier}. Available: {list(prices)}")
    api_key = os.environ.get("PADDLE_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "Paddle API key not configured")
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
                      "custom_data": {"tenant_id": tenant}},
            )
            response.raise_for_status()
            checkout_url = response.json().get("data", {}).get("checkout", {}).get("url")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "Could not create Paddle checkout") from exc
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise HTTPException(502, "Paddle did not return a checkout URL")
    return {"checkout_url": checkout_url, "tier": tier}


@router.post("/webhook")
async def paddle_webhook(request: Request) -> dict[str, str]:
    body = await request.body()
    secret = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
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

    if not event_type.startswith("subscription."):
        return {"status": "ok"}

    subscription_id = str(payload.get("id") or "")
    if not subscription_id:
        raise HTTPException(422, "Missing subscription ID")

    customer_id = str(payload.get("customer_id") or "")
    items = payload.get("items", [])
    product_name = ""
    if isinstance(items, list) and items:
        product = items[0].get("product", {}) if isinstance(items[0], dict) else {}
        product_name = product.get("name", "") if isinstance(product, dict) else ""
    tier = PADDLE_TIER_MAP.get(product_name)

    async with AsyncSessionLocal() as session:
        if event_type == "subscription.created":
            if not customer_id:
                raise HTTPException(422, "Missing customer ID")
            record = await session.scalar(select(ApiKey).where(
                ApiKey.paddle_customer_id == customer_id,
                ApiKey.is_active.is_(True)))
            if record is None:
                custom_data = payload.get("custom_data") or {}
                tenant_id = custom_data.get("tenant_id", "") if isinstance(custom_data, dict) else ""
                if isinstance(tenant_id, str) and tenant_id:
                    record = await session.scalar(select(ApiKey).where(
                        ApiKey.tenant_id == tenant_id,
                        ApiKey.is_active.is_(True),
                        or_(ApiKey.paddle_customer_id.is_(None),
                            ApiKey.paddle_customer_id == customer_id)))
                    if record is not None:
                        record.paddle_customer_id = customer_id
            if record is None:
                raise HTTPException(409, "No API key linked to this checkout")
            customer = payload.get("customer")
            customer_email = customer.get("email", "") if isinstance(customer, dict) else ""
            if isinstance(customer_email, str) and customer_email:
                record.contact_email = customer_email
            record.paddle_subscription_id = subscription_id
            record.tier = tier or "starter"
            record.cancelled_at = None

        elif event_type == "subscription.updated":
            record = await session.scalar(select(ApiKey).where(
                ApiKey.paddle_subscription_id == subscription_id))
            if record is None:
                raise HTTPException(409, "Unknown subscription ID")
            if tier:
                record.tier = tier
            if payload.get("status") == "active":
                record.cancelled_at = None

        elif event_type == "subscription.canceled":
            record = await session.scalar(select(ApiKey).where(
                ApiKey.paddle_subscription_id == subscription_id))
            if record is None:
                raise HTTPException(409, "Unknown subscription ID")
            record.cancelled_at = datetime.now(timezone.utc)

        else:
            return {"status": "ok"}
        await session.commit()

    return {"status": "ok"}
