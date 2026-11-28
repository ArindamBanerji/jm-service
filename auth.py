"""Tenant credentials and stable internal domain identities."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from limits import RateLimitItemPerHour
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import commit_write, get_db
from db.models import ApiKey, Domain, ProjectBillingOwner, ProjectMember, SignupChallenge, TenantGuard
from db.entitlement import entitlement_decision, resolve_entitlement
from db.tenant_lock import lock_tenant
from email_service import send_recovery_email, send_signup_challenge_email
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
    matching = (await session.scalars(select(ApiKey).where(or_(
        func.lower(ApiKey.contact_email) == payload.email,
        func.lower(ApiKey.signup_email) == payload.email)).limit(2))).all()
    if len(matching) > 1:
        raise HTTPException(409, "Mailbox ownership requires reconciliation")
    existing = matching[0] if matching else None
    if existing is not None and (existing.is_active or not existing.reproof_required
                                 or existing.email_verified_at is not None
                                 or existing.signup_email != payload.email
                                 or existing.subscription_state == "cleaned_up"):
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


class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_mailbox(cls, value: str) -> str:
        return RegisterRequest.valid_email(value)


_recovery_rate = RateLimitItemPerHour(3)
_recovery_eligible = (
    ApiKey.is_active.is_(True), ApiKey.reproof_required.is_(False),
    ApiKey.email_verified_at.is_not(None), ApiKey.signup_email.is_not(None),
    ApiKey.subscription_state.is_distinct_from("cleaned_up"),
)


class RecoveryNotice(BaseModel):
    message: str


class RecoveredKey(RecoveryNotice):
    api_key: str
    tenant_id: str


@signup_router.post("/recover", response_model=RecoveryNotice)
@limiter.limit("30/hour")
async def recover(request: Request, payload: RecoveryRequest, background: BackgroundTasks,
                  session: Session) -> dict[str, str]:
    """Send a one-time code to the verified signup mailbox. Existing keys stay active."""
    mailbox = hashlib.sha256(payload.email.encode()).hexdigest()
    if not limiter.limiter.hit(_recovery_rate, "recover-mailbox", mailbox):
        raise HTTPException(429, "Recovery request limit reached. Try again in one hour.")
    token = secrets.token_hex(32)
    recipient = await session.scalar(update(ApiKey).where(
        *_recovery_eligible, func.lower(ApiKey.signup_email) == payload.email,
    ).values(recovery_token_hash=hashlib.sha256(token.encode()).hexdigest(),
             recovery_token_expires=datetime.now(timezone.utc) + timedelta(minutes=15))
      .returning(ApiKey.signup_email))
    await commit_write(session)
    if recipient is not None:
        background.add_task(send_recovery_email, recipient, token)
    return {"message": "Check your email for a recovery code."}


class RecoveryConfirmRequest(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def valid_code(cls, value: str) -> str:
        if len(value) != 64 or not re.fullmatch("[0-9a-f]{64}", value):
            raise HTTPException(401, "Invalid or expired recovery code")
        return value


@signup_router.post("/recover/confirm", response_model=RecoveredKey)
@limiter.limit("10/minute")
async def confirm_recovery(request: Request, payload: RecoveryConfirmRequest, session: Session) -> dict[str, str]:
    """Consume mailbox proof and replace the existing credential in the same transaction."""
    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    tenant = await session.scalar(select(ApiKey.tenant_id).where(ApiKey.recovery_token_hash == digest))
    if tenant is None:
        raise HTTPException(401, "Invalid or expired recovery code")
    await lock_tenant(session, tenant)
    plain = secrets.token_hex(32)
    rotated = await session.scalar(update(ApiKey).where(
        *_recovery_eligible, ApiKey.tenant_id == tenant, ApiKey.recovery_token_hash == digest,
        ApiKey.recovery_token_expires > datetime.now(timezone.utc),
    ).values(key_hash=hashlib.sha256(plain.encode()).hexdigest(),
             recovery_token_hash=None, recovery_token_expires=None).returning(ApiKey.tenant_id))
    if rotated is None:
        raise HTTPException(401, "Invalid or expired recovery code")
    await commit_write(session)
    return {"api_key": plain, "tenant_id": rotated, "message": "Save this key — it cannot be recovered."}


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
    matching = (await session.scalars(select(ApiKey).where(or_(
        func.lower(ApiKey.contact_email) == email,
        func.lower(ApiKey.signup_email) == email)).limit(2))).all()
    if len(matching) > 1:
        raise HTTPException(409, "Mailbox ownership requires reconciliation")
    legacy = matching[0] if matching else None
    tenant_id = legacy.tenant_id if legacy is not None else str(uuid4())
    await lock_tenant(session, tenant_id)
    if legacy is not None:
        plain = secrets.token_hex(32)
        record = await session.get(ApiKey, legacy.id, with_for_update=True, populate_existing=True)
        if (record is None or record.is_active or not record.reproof_required
                or record.email_verified_at is not None
                or record.signup_email != email
                or record.subscription_state == "cleaned_up"
                or not record.signup_email or record.signup_email.lower() != email):
            raise HTTPException(409, detail="Email already registered")
        record.key_hash = hashlib.sha256(plain.encode()).hexdigest()
        record.is_active = True
        record.email_verified_at = now
        record.reproof_required = False
    else:
        plain, record = generate_api_key(tenant_id, name or email.split("@", 1)[0])
        record.contact_email = email
        record.signup_email = email
        record.email_verified_at = now
        session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, detail="Email already registered") from exc
    await commit_write(session)
    return {"api_key": plain, "tenant_id": tenant_id, "tier": record.tier,
            "message": "Save this key — it cannot be recovered."}


def public_alias(value: str) -> str:
    try:
        UUID(value)
    except ValueError:
        return value
    raise ValueError("public names cannot be UUID format")


def scoped_domain_id(tenant_id: str, domain_id: str) -> str:
    """Resolve the public domain name to a collision-resistant, private key."""
    return (hashlib.sha256(f"{tenant_id}\0{domain_id}".encode()).hexdigest()
            if tenant_id else domain_id)


def selected_domain_id(session: AsyncSession, tenant_id: str, domain_id: str) -> str:
    """Use the immutable project selected by an authenticated UUID route."""
    if session.info.get("selected_project_id") == domain_id:
        return str(session.info["selected_domain_id"])
    return scoped_domain_id(tenant_id, domain_id)


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


async def require_tenant(request: Request, session: Session,
                         x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None) -> str:
    for name in ("domain_id", "label_id"):
        identifier = request.path_params.get(name)
        if identifier is not None and not 0 < len(identifier) <= 200:
            raise HTTPException(422, f"{name} must be 1 to 200 characters")
    # FastAPI resolves dependencies before body DTOs. Validate the declared
    # model here as well so malformed writes cannot acquire resource locks.
    body_field = getattr(request.scope.get("route"), "body_field", None)
    model = getattr(getattr(body_field, "field_info", None), "annotation", None)
    if isinstance(model, type) and issubclass(model, BaseModel):
        try:
            model.model_validate(await request.json())
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Invalid request body") from None
    digest = hashlib.sha256((x_api_key or "").encode()).hexdigest()
    actor = await session.scalar(select(ApiKey).where(
        ApiKey.key_hash == digest, ApiKey.is_active.is_(True)))
    if actor is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    session.info["tenant_id"] = actor.tenant_id
    session.info["api_key_hash"] = digest
    session.info["actor_key_id"] = actor.id
    return actor.tenant_id


Tenant = Annotated[str, Depends(require_tenant)]


async def require_project_tenant(request: Request, session: Session, actor_tenant: Tenant) -> str:
    """Resolve a member's public project alias while retaining the actor identity."""
    public_id = request.path_params.get("domain_id")
    if public_id is not None and (not isinstance(public_id, str) or not 0 < len(public_id) <= 200):
        raise HTTPException(422, "domain_id must be 1 to 200 characters")
    if public_id is None and request.method == "POST":
        try:
            body = await request.json()
            public_id = body.get("domain_id") if isinstance(body, dict) else None
        except (ValueError, UnicodeError):
            pass
    if public_id is not None and (not isinstance(public_id, str) or not 0 < len(public_id) <= 200):
        raise HTTPException(422, "domain_id must be 1 to 200 characters")
    if not isinstance(public_id, str) or not public_id:
        return actor_tenant
    write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    selected_project: Domain | None = None
    owner_guard_locked = False
    try:
        project_uuid = UUID(public_id)
    except ValueError:
        pass
    else:
        if write and session.get_bind().dialect.name == "postgresql":
            # Discover an owned UUID and acquire only its tenant guard. The
            # domain itself is still re-read and locked after the payer keys.
            owner_guard = select(TenantGuard.tenant_id).where(
                TenantGuard.tenant_id == Domain.tenant_id, Domain.tenant_id == actor_tenant
            ).correlate(Domain).with_for_update(of=TenantGuard).scalar_subquery()
            match = (await session.execute(select(Domain, owner_guard).where(Domain.id == project_uuid))).one_or_none()
            if match is not None:
                selected_project, guard = match
                owner_guard_locked = guard is not None
        else:
            selected_project = await session.get(Domain, project_uuid)
        if selected_project is None:
            raise HTTPException(404, "Project not found")
        session.info["selected_project_id"] = public_id
        session.info["selected_domain_id"] = selected_project.domain_id
        session.info["selected_project_public_id"] = selected_project.public_domain_id
    name_filter = (Domain.id == selected_project.id if selected_project is not None else
                   Domain.public_domain_id == public_id)
    if selected_project is not None:
        # UUIDs have one owner. Membership and write eligibility are checked below.
        owned = selected_project.id if selected_project.tenant_id == actor_tenant else None
        candidate_member_id = selected_project.id if owned is None else None
    else:
        member_projects = select(ProjectMember.project_id).where(
            ProjectMember.member_tenant_id == actor_tenant, ProjectMember.active.is_(True))
        matches = (await session.execute(select(Domain.id, Domain.tenant_id).where(or_(
            (Domain.tenant_id == actor_tenant) & (name_filter | (
                Domain.public_domain_id.is_(None) & (Domain.domain_id == scoped_domain_id(actor_tenant, public_id)))),
            name_filter & Domain.id.in_(member_projects))))).all()
        if len(matches) > 1:
            raise HTTPException(409, {"message": "Project name is ambiguous; use a project UUID",
                                      "project_ids": [str(row.id) for row in matches]})
        owned = matches[0].id if matches and matches[0].tenant_id == actor_tenant else None
        candidate_member_id = matches[0].id if matches and owned is None else None
    if owned is not None:
        if write and not owner_guard_locked:
            await lock_tenant(session, actor_tenant)
        owner_payer = await resolve_entitlement(actor_tenant, session, for_update=write,
                                                purpose="write" if write else None)
        if write:
            current_project = await session.get(Domain, owned, with_for_update=True,
                                                populate_existing=True)
            if current_project is None or current_project.tenant_id != actor_tenant:
                raise HTTPException(404, "Project not found")
            if current_project.status != "active":
                raise HTTPException(409, "Project is read-only")
            request.state.locked_project_write = (session.sync_session.get_transaction(), current_project, owner_payer)
        session.info["project_role"] = "owner"
        return actor_tenant
    memberships = (await session.execute(select(Domain, ProjectMember).join(
        ProjectMember, ProjectMember.project_id == Domain.id).where(
        name_filter,
        ProjectMember.member_tenant_id == actor_tenant,
        ProjectMember.active.is_(True)).limit(2))).all()
    if not memberships:
        if selected_project is not None and request.scope["route"].name == "project_sla":
            raise HTTPException(403, "Project membership required")
        if selected_project is not None or candidate_member_id is not None:
            raise HTTPException(404, "Project not found")
        if write:
            await lock_tenant(session, actor_tenant)
            await resolve_entitlement(actor_tenant, session, for_update=True, purpose="write")
        return actor_tenant
    if len(memberships) != 1:
        raise HTTPException(409, {"message": "Project name is ambiguous; use a project UUID",
                                  "project_ids": [str(project.id) for project, _ in memberships]})
    project, member = memberships[0]
    if candidate_member_id != project.id:
        raise HTTPException(409, "Project selection changed; reload and retry")
    payer: ApiKey | None = None
    if write:
        await lock_tenant(session, project.tenant_id)
        if await session.get(ProjectBillingOwner, project.tenant_id) is None:
            raise HTTPException(409, "Project billing owner must be reconciled")
        payer = await resolve_entitlement(project.tenant_id, session, for_update=True,
                                          purpose="member_write")
        project = await session.get(Domain, project.id, with_for_update=True,
                                    populate_existing=True)
        member = await session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == memberships[0][0].id,
            ProjectMember.member_tenant_id == actor_tenant,
            ProjectMember.active.is_(True)).with_for_update()
            .execution_options(populate_existing=True))
        if project is None or member is None:
            raise HTTPException(403, "Project membership changed")
        if project.status != "active":
            raise HTTPException(409, "Project is read-only")
    operation = getattr(request.scope.get("route"), "name", None)
    if member.role == "annotator" and write and operation in {
        "verify", "project_verify", "bulk_verify", "put_guidelines", "ingest_batch",
        "project_import_one", "project_import_batch", "seed_sample", "import_predictions",
        "review_prediction", "reopen_prediction",
    }:
        raise HTTPException(403, "Project role does not allow this action")
    if member.role == "reviewer" and write and request.url.path.endswith("/guidelines"):
        raise HTTPException(403, "Project role does not allow this action")
    if await session.get(ProjectBillingOwner, project.tenant_id) is None:
        raise HTTPException(409, "Project billing owner must be reconciled")
    if payer is None:
        payer = await resolve_entitlement(project.tenant_id, session)
    session.info["actor_tenant_id"] = actor_tenant
    session.info["tenant_id"] = project.tenant_id
    session.info["payer_key_id"] = payer.id
    session.info["project_role"] = member.role
    if write:
        request.state.locked_project_write = (session.sync_session.get_transaction(), project, payer)
    return project.tenant_id


ProjectTenant = Annotated[str, Depends(require_project_tenant)]


class CreateKey(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=200)
    tenant_name: str = Field(min_length=1, max_length=200)


class ReconcileSignupOwner(BaseModel):
    signup_email: str = Field(min_length=3, max_length=200)
    evidence_reference: str = Field(min_length=1, max_length=200)

    @field_validator("signup_email")
    @classmethod
    def valid_signup_email(cls, value: str) -> str:
        return RegisterRequest.valid_email(value)


@router.post("/api-keys/{key_id}/reconcile-signup-owner")
async def reconcile_signup_owner(key_id: UUID, payload: ReconcileSignupOwner, session: Session,
                                 x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None) -> dict[str, str]:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid admin key")
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "Key not found")
    await lock_tenant(session, key.tenant_id)
    key = await session.get(ApiKey, key_id, with_for_update=True, populate_existing=True)
    if key is None or key.is_active or not key.reproof_required:
        raise HTTPException(409, "Key is not awaiting owner reconciliation")
    conflicting = await session.scalar(select(ApiKey.id).where(
        func.lower(ApiKey.signup_email) == payload.signup_email,
        ApiKey.id != key_id).limit(1))
    if conflicting is not None:
        raise HTTPException(409, "Signup owner email is already assigned")
    key.signup_email = payload.signup_email
    key.signup_reconciliation_reference = payload.evidence_reference
    logger.info("Signup owner reconciled for key %s", key_id)
    await commit_write(session)
    return {"status": "reconciled"}


@router.post("/api-keys/{key_id}/rotate")
async def rotate_key(key_id: UUID, session: Session,
                     x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None) -> dict[str, str]:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid admin key")
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(404, "Key not found")
    await lock_tenant(session, key.tenant_id)
    key = await session.get(ApiKey, key_id, with_for_update=True, populate_existing=True)
    if key is None or not key.is_active or key.subscription_state == "cleaned_up":
        raise HTTPException(409, "Key is unavailable for rotation")
    plain = secrets.token_hex(32)
    key.key_hash = hashlib.sha256(plain.encode()).hexdigest()
    key.recovery_token_hash = None
    key.recovery_token_expires = None
    await commit_write(session)
    return {"api_key": plain, "tenant_id": key.tenant_id}


@router.post("/api-keys")
@limiter.limit("10/minute")
async def create_key(request: Request, payload: CreateKey, session: Session,
                     x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None) -> dict[str, str]:
    expected = os.getenv("ADMIN_API_KEY")
    if not expected or not x_admin_key or not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin key")
    await lock_tenant(session, payload.tenant_id)
    siblings = (await session.scalars(select(ApiKey).where(
        ApiKey.tenant_id == payload.tenant_id).order_by(ApiKey.id).with_for_update())).all()
    tombstone = any(key.subscription_state == "cleaned_up" for key in siblings)
    protects_tenant = any(entitlement_decision(key).protects_tenant for key in siblings)
    has_domain = await session.scalar(select(Domain.id).where(
        Domain.tenant_id == payload.tenant_id).limit(1)) is not None
    if tombstone and not has_domain and not protects_tenant:
        raise HTTPException(409, detail="Tenant has been cleaned up")
    plain, record = generate_api_key(payload.tenant_id, payload.tenant_name)
    session.add(record)
    await session.flush()
    await commit_write(session)
    return {"api_key": plain, "tenant_id": payload.tenant_id}
