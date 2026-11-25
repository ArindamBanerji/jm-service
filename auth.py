"""Tenant credentials and stable internal domain identities."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import commit_write, get_db
from db.models import ApiKey, Domain, ProjectBillingOwner, ProjectMember, SignupChallenge
from db.tenant_lock import lock_tenant
from email_service import send_signup_challenge_email
from rate_limit import limiter

Session = Annotated[AsyncSession, Depends(get_db)]
router = APIRouter(prefix="/v1/admin", tags=["Admin"])
signup_router = APIRouter(prefix="/v1/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Invalid email address")
        return email

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


@signup_router.post("/register", status_code=202)
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterRequest, session: Session) -> dict[str, str]:
    existing = await session.scalar(select(ApiKey.id).where(func.lower(ApiKey.contact_email) == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    token = secrets.token_hex(32)
    session.add(SignupChallenge(
        token_digest=hashlib.sha256(token.encode()).hexdigest(), email=payload.email,
        requested_name=payload.name,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30)))
    await commit_write(session)
    if not await send_signup_challenge_email(payload.email, token):
        logger.warning("Signup challenge email delivery failed")
        raise HTTPException(503, detail="Could not send confirmation email; please try again")
    return {"message": "Check your email for a confirmation code."}


class ConfirmRequest(BaseModel):
    token: str = Field(min_length=64, max_length=64)


@signup_router.post("/confirm", status_code=201)
@limiter.limit("10/minute")
async def confirm(request: Request, payload: ConfirmRequest, session: Session) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    claimed = await session.execute(
        update(SignupChallenge).where(
            SignupChallenge.token_digest == digest,
            SignupChallenge.consumed_at.is_(None), SignupChallenge.expires_at > now,
        ).values(consumed_at=now).returning(
            SignupChallenge.email, SignupChallenge.requested_name))
    proof = claimed.one_or_none()
    if proof is None:
        raise HTTPException(400, detail="Invalid or expired confirmation code")
    email, name = proof
    tenant_id = str(uuid4())
    plain, record = generate_api_key(tenant_id, name or email.split("@", 1)[0])
    record.contact_email = email
    await lock_tenant(session, tenant_id)
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, detail="Email already registered") from exc
    await commit_write(session)
    return {"api_key": plain, "tenant_id": tenant_id, "tier": "trial",
            "message": "Save this key — it cannot be recovered."}


def scoped_domain_id(tenant_id: str, domain_id: str) -> str:
    """Resolve the public domain name to a collision-resistant, private key."""
    return (hashlib.sha256(f"{tenant_id}\0{domain_id}".encode()).hexdigest()
            if tenant_id else domain_id)


def generate_api_key(tenant_id: str, tenant_name: str) -> tuple[str, ApiKey]:
    plain = secrets.token_hex(32)
    return plain, ApiKey(key_hash=hashlib.sha256(plain.encode()).hexdigest(),
                         tenant_id=tenant_id, tenant_name=tenant_name,
                         subscription_state="trial")


async def verify_api_key(key: str, session: AsyncSession) -> str | None:
    digest = hashlib.sha256(key.encode()).hexdigest()
    record = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest,
                                                       ApiKey.is_active.is_(True)))
    return record.tenant_id if record else None


async def require_tenant(session: Session,
                         x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None) -> str:
    tenant = await verify_api_key(x_api_key or "", session)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    session.info["tenant_id"] = tenant
    session.info["api_key_hash"] = hashlib.sha256((x_api_key or "").encode()).hexdigest()
    return tenant


Tenant = Annotated[str, Depends(require_tenant)]


async def require_project_tenant(request: Request, session: Session, actor_tenant: Tenant) -> str:
    """Resolve a member's public project alias while retaining the actor identity."""
    public_id = request.path_params.get("domain_id")
    if public_id is None and request.method == "POST":
        try:
            body = await request.json()
            public_id = body.get("domain_id") if isinstance(body, dict) else None
        except (ValueError, UnicodeError):
            pass
    if not isinstance(public_id, str) or not public_id:
        return actor_tenant
    owned = await session.scalar(select(Domain.id).where(
        Domain.tenant_id == actor_tenant,
        Domain.public_domain_id == public_id).limit(1))
    if owned is not None:
        owner = await session.get(ProjectBillingOwner, actor_tenant)
        if owner is not None:
            write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
            payer = await session.get(ApiKey, owner.billing_key_id,
                                      with_for_update=write, populate_existing=write)
            if payer is None or not payer.is_active:
                raise HTTPException(403, "Project payer is unavailable")
            if write and payer.subscription_state in {"past_due", "paused", "cleaned_up", "trial_expired"}:
                raise HTTPException(403, "Project is read-only while the payer is not entitled")
            session.info["payer_key_id"] = payer.id
            session.info["project_role"] = "owner"
        return actor_tenant
    memberships = (await session.execute(select(Domain, ProjectMember).join(
        ProjectMember, ProjectMember.project_id == Domain.id).where(
        Domain.public_domain_id == public_id,
        ProjectMember.member_tenant_id == actor_tenant,
        ProjectMember.active.is_(True)).limit(2))).all()
    if not memberships:
        return actor_tenant
    if len(memberships) != 1:
        raise HTTPException(409, "Project name is ambiguous; use a project-specific route")
    project, member = memberships[0]
    write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    if write and project.status != "active":
        raise HTTPException(409, "Project is read-only")
    if write and member.role == "annotator" and (
            "verify" in request.url.path or request.url.path.endswith("/guidelines")):
        raise HTTPException(403, "Project role does not allow this action")
    if write and member.role == "reviewer" and request.url.path.endswith("/guidelines"):
        raise HTTPException(403, "Project role does not allow this action")
    owner = await session.get(ProjectBillingOwner, project.tenant_id)
    if owner is None:
        raise HTTPException(409, "Project billing owner must be reconciled")
    payer = await session.get(ApiKey, owner.billing_key_id,
                              with_for_update=write, populate_existing=write)
    if payer is None or not payer.is_active:
        raise HTTPException(403, "Project payer is unavailable")
    if write and payer.subscription_state in {"past_due", "paused", "cancelled", "cleaned_up", "trial_expired"}:
        raise HTTPException(403, "Project is read-only while the payer is not entitled")
    session.info["actor_tenant_id"] = actor_tenant
    session.info["tenant_id"] = project.tenant_id
    session.info["payer_key_id"] = payer.id
    session.info["project_role"] = member.role
    return project.tenant_id


ProjectTenant = Annotated[str, Depends(require_project_tenant)]


class CreateKey(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    tenant_name: str = Field(min_length=1, max_length=200)


@router.post("/api-keys")
@limiter.limit("10/minute")
async def create_key(request: Request, payload: CreateKey, session: Session,
                     x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None) -> dict[str, str]:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key, expected):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    await lock_tenant(session, payload.tenant_id)
    tombstone = await session.scalar(select(ApiKey.id).where(
        ApiKey.tenant_id == payload.tenant_id,
        ApiKey.subscription_state == "cleaned_up").limit(1))
    if tombstone is not None:
        raise HTTPException(409, detail="Tenant has been cleaned up")
    plain, record = generate_api_key(payload.tenant_id, payload.tenant_name)
    session.add(record)
    await session.flush()
    await commit_write(session)
    return {"api_key": plain, "tenant_id": payload.tenant_id}
