"""Trial expiry and transactional label-volume enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey

TRIAL_DAYS = 14
DAILY_TRIAL_CAP = 50
UPGRADE_URL = "https://dlj.dakshineshwari.net/#/settings"

TIER_MONTHLY_CAPS: dict[str, int | None] = {
    "trial": None,
    "starter": 10_000,
    "professional": 100_000,
    "business": 1_000_000,
    "scale": None,
    "enterprise": None,
}


def _utc_timestamp(value: datetime) -> datetime:
    """SQLite loads naive UTC timestamps; PostgreSQL preserves their zone."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def check_trial_expiry(api_key_record: ApiKey) -> None:
    if (api_key_record.tier or "trial") != "trial":
        return
    created = api_key_record.created_at
    if created is None:
        return
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > created + timedelta(days=TRIAL_DAYS):
        raise HTTPException(402, detail={
            "error": "trial_expired",
            "message": "Your 14-day free trial has ended. Upgrade to continue scoring.",
            "upgrade_url": UPGRADE_URL,
        })


def check_volume_cap(api_key_record: ApiKey) -> dict[str, str] | None:
    tier = api_key_record.tier or "trial"
    if tier not in TIER_MONTHLY_CAPS:
        raise HTTPException(403, detail="Unknown subscription tier")
    cap = TIER_MONTHLY_CAPS[tier]
    if cap is None:
        return None
    used = api_key_record.labels_this_month or 0
    if used >= cap:
        raise HTTPException(429, detail={
            "error": "volume_exceeded",
            "scope": "monthly",
            "message": f"Monthly volume cap ({cap:,} labels) reached for {tier} tier.",
            "upgrade_url": UPGRADE_URL,
        })
    if used >= int(cap * 0.9):
        return {"X-Volume-Warning": f"{used}/{cap} labels used this month"}
    return None


async def reserve_label_capacity(session: AsyncSession) -> dict[str, str] | None:
    """Reserve one scored label in the caller's transaction, locking the API key row."""
    key_hash = session.info.get("api_key_hash")
    if not key_hash:
        raise HTTPException(401, detail="Invalid API key")
    record = await session.scalar(select(ApiKey).where(
        ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True)).with_for_update())
    if record is None:
        raise HTTPException(401, detail="Invalid API key")

    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    if record.labels_day_key != day_key:
        record.labels_day_key = day_key
        record.labels_today = 0
    if record.labels_month_key != month_key:
        record.labels_month_key = month_key
        record.labels_this_month = 0

    cancelled = record.cancelled_at
    cancellation_effective = cancelled is not None and _utc_timestamp(cancelled) <= now
    check_trial_expiry(record)
    if (record.tier or "trial") == "trial" or cancellation_effective:
        if record.labels_today >= DAILY_TRIAL_CAP:
            raise HTTPException(429, detail={
                "error": "volume_exceeded",
                "scope": "daily",
                "message": f"Daily trial cap ({DAILY_TRIAL_CAP} labels) reached.",
                "upgrade_url": UPGRADE_URL,
            })
    else:
        check_volume_cap(record)

    record.labels_today += 1
    record.labels_this_month += 1
    warning = None
    cap = None if cancellation_effective else TIER_MONTHLY_CAPS[record.tier or "trial"]
    if cap is not None and record.labels_this_month >= int(cap * 0.9):
        warning = {"X-Volume-Warning": f"{record.labels_this_month}/{cap} labels used this month"}
    if warning:
        session.info["volume_warning"] = warning["X-Volume-Warning"]
    return warning
