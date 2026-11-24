"""Minimal authenticated account and public domain discovery."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Tenant, scoped_domain_id
from db.connection import get_db
from db.models import ApiKey, Domain
from trial_guard import DAILY_TRIAL_CAP, TIER_MONTHLY_CAPS, TRIAL_DAYS

router = APIRouter(prefix="/v1/account", tags=["Account"])
Session = Annotated[AsyncSession, Depends(get_db)]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("")
async def account(session: Session, tenant: Tenant) -> dict:
    key_hash = session.info.get("api_key_hash")
    record = await session.scalar(select(ApiKey).where(
        ApiKey.key_hash == key_hash, ApiKey.tenant_id == tenant, ApiKey.is_active.is_(True)))
    if record is None:
        raise HTTPException(401, detail="Invalid API key")
    now = datetime.now(timezone.utc)
    tier = record.tier or "trial"
    created = utc(record.created_at)
    day = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    return {
        "tenant_id": record.tenant_id, "tenant_name": record.tenant_name,
        "tier": tier, "created_at": created.isoformat(), "is_active": record.is_active,
        "cancelled_at": utc(record.cancelled_at).isoformat() if record.cancelled_at else None,
        "trial_expires_at": (created + timedelta(days=TRIAL_DAYS)).isoformat() if tier == "trial" else None,
        "trial_expired": tier == "trial" and now > created + timedelta(days=TRIAL_DAYS),
        "usage": {
            "labels_today": record.labels_today if record.labels_day_key == day else 0,
            "labels_this_month": record.labels_this_month if record.labels_month_key == month else 0,
            "daily_cap": DAILY_TRIAL_CAP if tier == "trial" else None,
            "monthly_cap": TIER_MONTHLY_CAPS.get(tier),
            "day_key": day, "month_key": month,
        },
    }


@router.get("/domains")
async def domains(session: Session, tenant: Tenant) -> list[dict[str, str | bool | None]]:
    rows = (await session.scalars(select(Domain).where(Domain.tenant_id == tenant)
                                  .order_by(Domain.created_at, Domain.id))).all()
    return [{"id": str(row.id), "public_domain_id": row.public_domain_id,
             "needs_name": row.public_domain_id is None} for row in rows]


class ResolveDomain(BaseModel):
    domain_id: str = Field(min_length=1, max_length=200)

    @field_validator("domain_id")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip() or re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Enter a public domain name")
        return value


@router.post("/domains/resolve")
async def resolve_domain(payload: ResolveDomain, session: Session, tenant: Tenant) -> dict[str, str]:
    row = await session.scalar(select(Domain).where(
        Domain.domain_id == scoped_domain_id(tenant, payload.domain_id),
        Domain.tenant_id == tenant).with_for_update())
    if row is None:
        raise HTTPException(404, detail="Domain not found")
    if row.public_domain_id is not None and row.public_domain_id != payload.domain_id:
        raise HTTPException(409, detail="Domain name already recorded")
    row.public_domain_id = payload.domain_id
    return {"public_domain_id": row.public_domain_id}
