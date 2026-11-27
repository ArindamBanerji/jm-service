"""Resolve the one billing payer whose state governs a tenant's operations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ApiKey, ProjectBillingOwner

UPGRADE_URL = "https://dlj.dakshineshwari.net/#/settings"


def expired_trial_error() -> HTTPException:
    return HTTPException(402, detail={"error": "trial_expired",
                                     "message": "Your 14-day free trial has ended. Upgrade to continue scoring.",
                                     "upgrade_url": UPGRADE_URL})

EntitlementPurpose = Literal["purchase", "write", "member_write", "retain"]


@dataclass(frozen=True)
class EntitlementDecision:
    state: str
    can_receive_purchase: bool
    can_write: bool
    protects_tenant: bool


def effective_state(record: ApiKey, now: datetime | None = None) -> str:
    """Compute the state seen by reads and all write gates at the same instant."""
    if record.subscription_state is not None:
        state = record.subscription_state
    elif record.cancelled_at is not None:
        state = "cancelled"
    else:
        state = "trial" if record.tier == "trial" else "active"
    current = now or datetime.now(timezone.utc)
    created = record.created_at
    if state == "trial" and created is not None:
        created_utc = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)
        if current > created_utc + timedelta(days=14):
            return "trial_expired"
    return state


def entitlement_decision(record: ApiKey, now: datetime | None = None) -> EntitlementDecision:
    """Apply the shared payer policy used by billing, writes and retention."""
    state = effective_state(record, now)
    usable_credential = record.is_active and not record.reproof_required
    can_receive_purchase = usable_credential and state != "cleaned_up"
    can_write = usable_credential and state not in {
        "past_due", "paused", "trial_expired", "cleaned_up"
    }
    protects_tenant = (
        state in {"active", "past_due", "paused"}
        or (record.is_active and state in {"trial", "cancelled"})
    )
    return EntitlementDecision(
        state=state,
        can_receive_purchase=can_receive_purchase,
        can_write=can_write,
        protects_tenant=protects_tenant,
    )


def require_payer_eligibility(record: ApiKey, purpose: EntitlementPurpose) -> EntitlementDecision:
    """Reject a payer consistently for the requested operation."""
    decision = entitlement_decision(record)
    allowed = {
        "purchase": decision.can_receive_purchase,
        "write": decision.can_write,
        "member_write": decision.can_write and decision.state != "cancelled",
        "retain": decision.protects_tenant,
    }[purpose]
    if not allowed:
        if purpose in {"write", "member_write"} and decision.state == "trial_expired":
            raise expired_trial_error()
        status = (409 if purpose == "purchase" else
                  402 if purpose in {"write", "member_write"} and decision.state in {
                      "past_due", "paused"} else 403)
        raise HTTPException(status, f"Project payer is not eligible for {purpose}")
    return decision


async def resolve_entitlement(tenant_id: str, session: AsyncSession, *,
                              for_update: bool = False, service_token: bool = False,
                              purpose: EntitlementPurpose | None = None) -> ApiKey:
    """Return the effective payer, using the authenticated key only before owner setup."""
    actor_id = session.info.get("actor_key_id") if for_update else None
    key_match = ApiKey.id == ProjectBillingOwner.billing_key_id
    if actor_id is not None:
        key_match = key_match | (ApiKey.id == actor_id)
    bound_keys = select(ApiKey, ProjectBillingOwner.billing_key_id).select_from(ApiKey).join(
        ProjectBillingOwner, key_match).where(ProjectBillingOwner.owner_tenant_id == tenant_id)
    if for_update:
        bound_keys = bound_keys.order_by(ApiKey.id).with_for_update(of=ApiKey).execution_options(
            populate_existing=True)
    bound = (await session.execute(bound_keys)).all()
    if bound:
        payer_id = bound[0].billing_key_id
        keys = {key.id: key for key, _ in bound}
    else:
        candidates = (await session.execute(select(ApiKey.id, ApiKey.key_hash).where(
            ApiKey.tenant_id == tenant_id, ApiKey.is_active.is_(True)).limit(2))).all()
        if len(candidates) != 1:
            raise HTTPException(409, "Billing payer is ambiguous; reconcile before writing")
        if not service_token and candidates[0].key_hash != session.info.get("api_key_hash"):
            raise HTTPException(403, "Project payer is unavailable")
        payer_id = candidates[0].id
        ids = {payer_id} if actor_id is None else {payer_id, actor_id}
        key_query = select(ApiKey).where(ApiKey.id.in_(ids))
        if for_update:
            key_query = key_query.order_by(ApiKey.id).with_for_update().execution_options(populate_existing=True)
        keys = {key.id: key for key in await session.scalars(key_query)}
    if actor_id is not None:
        actor = keys.get(actor_id)
        if actor is None or not actor.is_active or actor.key_hash != session.info.get("api_key_hash"):
            raise HTTPException(401, "Invalid API key")
    record = keys.get(payer_id)
    if record is None or record.tenant_id != tenant_id:
        raise HTTPException(403, "Project payer is unavailable")
    if purpose is None and not record.is_active:
        raise HTTPException(403, "Project payer is unavailable")
    if purpose is not None:
        require_payer_eligibility(record, purpose)
    session.info["payer_key_id"] = record.id
    return record
