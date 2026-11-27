"""Trial expiry and transactional label-volume enforcement."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey
from db.entitlement import UPGRADE_URL, entitlement_decision, expired_trial_error, require_payer_eligibility, resolve_entitlement

TRIAL_DAYS = 14
DAILY_TRIAL_CAP = 50

TIER_MONTHLY_CAPS: dict[str, int | None] = {
    "trial": None,
    "starter": 10_000,
    "professional": 100_000,
    "business": 1_000_000,
    "scale": None,
    "enterprise": None,
}


def check_trial_expiry(api_key_record: ApiKey) -> None:
    if entitlement_decision(api_key_record).state == "trial_expired":
        raise expired_trial_error()


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


async def reserve_label_capacity(session: AsyncSession, locked_payer: ApiKey | None = None) -> dict[str, str] | None:
    """Reserve one scored label in the caller's transaction, locking the API key row."""
    tenant_id = session.info.get("tenant_id")
    if not isinstance(tenant_id, str):
        raise HTTPException(401, detail="Invalid API key")
    if locked_payer is None:
        record = await resolve_entitlement(tenant_id, session, for_update=True, purpose="write")
        state = entitlement_decision(record).state
    else:
        record = locked_payer
        if record.tenant_id != tenant_id or record.id != session.info.get("payer_key_id"):
            raise HTTPException(403, "Project payer is unavailable")
        state = require_payer_eligibility(
            record, "write" if session.info.get("project_role") == "owner" else "member_write"
        ).state

    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")
    if record.labels_day_key != day_key:
        record.labels_day_key = day_key
        record.labels_today = 0
    if record.labels_month_key != month_key:
        record.labels_month_key = month_key
        record.labels_this_month = 0

    cancellation_effective = state == "cancelled"
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
