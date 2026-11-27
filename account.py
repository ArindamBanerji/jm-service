"""Minimal authenticated account and public domain discovery."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Tenant, public_alias, scoped_domain_id
from db.connection import commit_write, get_db
from db.models import ApiKey, Domain
from db.tenant_lock import lock_tenant
from db.entitlement import entitlement_decision, resolve_entitlement
from trial_guard import DAILY_TRIAL_CAP, TIER_MONTHLY_CAPS, TRIAL_DAYS

router = APIRouter(prefix="/v1/account", tags=["Account"])
Session = Annotated[AsyncSession, Depends(get_db)]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("")
async def account(session: Session, tenant: Tenant) -> dict:
    key_hash = session.info.get("api_key_hash")
    credential = await session.scalar(select(ApiKey).where(
        ApiKey.key_hash == key_hash, ApiKey.tenant_id == tenant, ApiKey.is_active.is_(True)))
    if credential is None:
        raise HTTPException(401, detail="Invalid API key")
    record = await resolve_entitlement(tenant, session)
    now = datetime.now(timezone.utc)
    tier = record.tier or "trial"
    state = entitlement_decision(record, now).state
    created = utc(record.created_at)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    return {
        "tenant_id": record.tenant_id, "tenant_name": record.tenant_name,
        "tier": tier, "created_at": created.isoformat(), "is_active": record.is_active,
        "subscription_state": state,
        "cancelled_at": utc(record.cancelled_at).isoformat() if record.cancelled_at else None,
        "trial_expires_at": (created + timedelta(days=TRIAL_DAYS)).isoformat() if tier == "trial" else None,
        "trial_expired": state == "trial_expired",
        "usage": {
            "labels_today": record.labels_today if record.labels_day_key == day else 0,
            "labels_this_month": record.labels_this_month if record.labels_month_key == month else 0,
            "daily_cap": 0 if state == "trial_expired" else DAILY_TRIAL_CAP if state == "cancelled" or tier == "trial" else None,
            "monthly_cap": 0 if state in {"past_due", "paused", "cleaned_up", "trial_expired"} else None if state == "cancelled" else TIER_MONTHLY_CAPS.get(tier),
            "day_key": day, "month_key": month,
        },
    }


@router.get("/domains")
async def domains(session: Session, tenant: Tenant, response: Response,
                  limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)) -> list[dict[str, str | bool | None]]:
    """Page through the account's owned domains using the X-Next-Offset header."""
    rows = (await session.execute(select(Domain.id, Domain.public_domain_id).where(Domain.tenant_id == tenant)
                                  .order_by(Domain.created_at, Domain.id).offset(offset).limit(limit + 1))).all()
    if len(rows) > limit:
        response.headers["X-Next-Offset"] = str(offset + limit)
        rows = rows[:limit]
    return [{"id": str(row.id), "public_domain_id": row.public_domain_id,
             "needs_name": row.public_domain_id is None} for row in rows]


class ResolveDomain(BaseModel):
    domain_id: str = Field(min_length=1, max_length=200)

    @field_validator("domain_id")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip() or re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Enter a public domain name")
        return public_alias(value)


@router.post("/domains/resolve")
async def resolve_domain(payload: ResolveDomain, session: Session, tenant: Tenant) -> dict[str, str]:
    await lock_tenant(session, tenant)
    await resolve_entitlement(tenant, session, for_update=True, purpose="write")
    row = await session.scalar(select(Domain).where(
        Domain.domain_id == scoped_domain_id(tenant, payload.domain_id),
        Domain.tenant_id == tenant).with_for_update())
    if row is None:
        raise HTTPException(404, detail="Domain not found")
    if row.public_domain_id is not None and row.public_domain_id != payload.domain_id:
        raise HTTPException(409, detail="Domain name already recorded")
    row.public_domain_id = payload.domain_id
    await commit_write(session)
    return {"public_domain_id": row.public_domain_id}
