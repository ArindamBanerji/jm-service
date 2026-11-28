"""Project administration, team membership and invitation endpoints."""
from __future__ import annotations

import hashlib
import secrets
from html import escape
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Tenant, public_alias, scoped_domain_id
from db.connection import commit_write, get_db
from db.entitlement import require_payer_eligibility, resolve_entitlement
from db.models import (ApiKey, Domain, LabelLog, ProjectBillingOwner, ProjectInvite,
                       ProjectMember, WebhookEndpoint)
from db.repository import cancel_open_deliveries, create_domain
from db.tenant_lock import lock_tenant
from email_service import send_email
from jm_core import DomainConfig
from modality import (check_modality_locked, get_enabled_combinations,
                      inline_images_enabled, validate_project_modality)

router = APIRouter(prefix="/v1/projects", tags=["Projects"])
Session = Annotated[AsyncSession, Depends(get_db)]


async def _actor(session: AsyncSession, tenant: str) -> ApiKey:
    record = await session.scalar(select(ApiKey).where(
        ApiKey.tenant_id == tenant, ApiKey.key_hash == session.info.get("api_key_hash"),
        ApiKey.is_active.is_(True)))
    if record is None:
        raise HTTPException(401, "Invalid API key")
    return record


async def _ensure_billing_owner(session: AsyncSession, tenant: str, actor: ApiKey) -> None:
    await lock_tenant(session, tenant)
    if await session.get(ProjectBillingOwner, tenant) is not None:
        return
    siblings = (await session.scalars(select(ApiKey.id).where(
        ApiKey.tenant_id == tenant, ApiKey.is_active.is_(True)).limit(2))).all()
    if len(siblings) != 1 or siblings[0] != actor.id:
        raise HTTPException(409, "Billing payer is ambiguous; reconcile before sharing")
    session.add(ProjectBillingOwner(owner_tenant_id=tenant, billing_key_id=actor.id,
                                    trial_started_at=actor.created_at))
    await session.flush()


async def _project(session: AsyncSession, project_id: UUID, tenant: str,
                   allowed: set[str] | None = None) -> tuple[Domain, str]:
    project = await session.get(Domain, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    if allowed is not None:
        # The first read only discovers the tenant guard. Every authorization
        # input is reloaded after guard -> payer -> project/member locks.
        await lock_tenant(session, project.tenant_id)
        owner = await session.get(ProjectBillingOwner, project.tenant_id)
        if owner is None:
            raise HTTPException(409, "Project billing owner must be reconciled")
        await resolve_entitlement(project.tenant_id, session, for_update=True,
                                          purpose="write" if project.tenant_id == tenant else "member_write")
        project = await session.get(Domain, project_id, with_for_update=True,
                                    populate_existing=True)
        if project is None:
            raise HTTPException(404, "Project not found")
    if project.tenant_id == tenant:
        role = "owner"
    else:
        member_query = select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.member_tenant_id == tenant,
            ProjectMember.active.is_(True))
        if allowed is not None:
            member_query = member_query.with_for_update()
        member = await session.scalar(member_query)
        if member is None:
            raise HTTPException(404, "Project not found")
        role = member.role
    if allowed is not None and role not in allowed:
        raise HTTPException(403, "Project role does not allow this action")
    return project, role


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    public_domain_id: str = Field(min_length=1, max_length=200)
    factors: list[str] = Field(min_length=2, max_length=20)
    categories: list[str] = Field(min_length=1, max_length=20)
    actions: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    content_type: str | None = None
    label_schema: str | None = None

    @field_validator("factors", "categories")
    @classmethod
    def bounded_schema_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("schema IDs must be 1 to 200 characters")
        if len(set(values)) != len(values):
            raise ValueError("schema IDs must be unique")
        return values

    @field_validator("categories")
    @classmethod
    def valid_categories(cls, values: list[str]) -> list[str]:
        if any("|" in value for value in values):
            raise ValueError("Category names must not contain |")
        return values

    @field_validator("public_domain_id")
    @classmethod
    def public_name_is_not_uuid(cls, value: str) -> str:
        return public_alias(value)

    @field_validator("actions")
    @classmethod
    def bounded_actions(cls, values: list[str]) -> list[str]:
        if not values or len(values) > 20:
            raise ValueError("actions must contain 1 to 20 values")
        if any(not isinstance(value, str) or not value.strip() or "|" in value or len(value) > 200
               for value in values):
            raise ValueError("action IDs must be 1 to 200 characters")
        if len(set(values)) != len(values):
            raise ValueError("action IDs must be unique")
        return values


@router.post("", status_code=201)
async def create_project(payload: ProjectCreate, session: Session, tenant: Tenant) -> dict:
    axes_supplied = bool({"content_type", "label_schema"} & payload.model_fields_set)
    if (("content_type" in payload.model_fields_set and payload.content_type is None) or
            ("label_schema" in payload.model_fields_set and payload.label_schema is None)):
        raise HTTPException(422, "Invalid project modality")
    content_type, label_schema = validate_project_modality(
        payload.content_type if payload.content_type is not None else "text",
        payload.label_schema if payload.label_schema is not None else "single")
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, tenant, actor)
    await resolve_entitlement(tenant, session, for_update=True, purpose="write")
    actor = await _actor(session, tenant)
    scoped = scoped_domain_id(tenant, payload.public_domain_id)
    if await session.scalar(select(Domain.id).where(Domain.domain_id == scoped)):
        raise HTTPException(409, "Project already exists")
    config = DomainConfig(scoped, payload.name, payload.factors, payload.categories, payload.actions)
    project = await create_domain(
        session, scoped, payload.name, config, tenant, payload.public_domain_id,
        content_type=content_type, label_schema=label_schema,
        modality_enforced=axes_supplied)
    session.add(ProjectMember(project_id=project.id, member_tenant_id=tenant,
                              role="admin", granted_by_key_id=actor.id,
                              created_at=datetime.now(timezone.utc)))
    await commit_write(session)
    return {"id": str(project.id), "public_domain_id": payload.public_domain_id,
            "name": payload.name, "status": project.status,
            "content_type": project.content_type, "label_schema": project.label_schema,
            "modality_enforced": project.modality_enforced, "modality_locked": False,
            "settings_version": project.settings_version}


@router.get("")
async def list_projects(session: Session, tenant: Tenant, response: Response,
                        limit: int = Query(100, ge=1, le=200),
                        offset: int = Query(0, ge=0)) -> list[dict]:
    """List accessible projects in creation order. X-Next-Offset identifies the next page."""
    rows = (await session.execute(select(Domain, ProjectMember.role).outerjoin(
        ProjectMember, and_(ProjectMember.project_id == Domain.id,
                            ProjectMember.member_tenant_id == tenant, ProjectMember.active.is_(True)))
        .where(or_(Domain.tenant_id == tenant, ProjectMember.role.is_not(None)))
        .order_by(Domain.created_at, Domain.id).offset(offset).limit(limit + 1))).all()
    if len(rows) > limit:
        response.headers["X-Next-Offset"] = str(offset + limit)
        rows = rows[:limit]
    locked = set((await session.scalars(select(LabelLog.domain_id).where(
        LabelLog.domain_id.in_([row.domain_id for row, _ in rows])).distinct())).all()) if rows else set()
    return [{"id": str(row.id), "public_domain_id": row.public_domain_id,
             "name": row.domain_name, "description": row.description, "status": row.status,
             "content_type": row.content_type, "label_schema": row.label_schema,
             "modality_enforced": row.modality_enforced,
             "modality_locked": row.domain_id in locked,
             "role": "owner" if row.tenant_id == tenant else role,
             "settings_version": row.settings_version} for row, role in rows]


@router.get("/capabilities")
async def project_capabilities(tenant: Tenant) -> dict:
    del tenant  # Authentication is the capability boundary; results are deployment-wide.
    return {
        "combinations": [
            {"content_type": content_type, "label_schema": label_schema}
            for content_type, label_schema in get_enabled_combinations()
        ],
        "inline_images_enabled": inline_images_enabled(),
    }


class ProjectSettings(BaseModel, extra="forbid"):
    settings_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=10_000)
    status: str | None = Field(default=None, pattern="^(active|archived|completed)$")
    automation_enabled: bool = False
    confidence_floor: float = Field(default=.95, ge=.80, le=.99)
    guidelines: str | None = None
    content_type: str | None = None
    label_schema: str | None = None
    modality_enforced: bool | None = None

    @field_validator("guidelines")
    @classmethod
    def bounded_guidelines(cls, value: str | None) -> str | None:
        if value is not None and len(value.encode("utf-8")) > 10 * 1024:
            raise ValueError("Guidelines must be at most 10 KiB UTF-8")
        return value


class ProjectPatch(BaseModel, extra="forbid"):
    description: str | None = Field(default=None, max_length=10_000)
    status: str | None = Field(default=None, pattern="^(active|archived|completed)$")
    automation_enabled: bool | None = None
    confidence_floor: float | None = Field(default=None, ge=.80, le=.99)
    guidelines: str | None = None
    content_type: str | None = None
    label_schema: str | None = None
    modality_enforced: bool | None = None

    @field_validator("guidelines")
    @classmethod
    def bounded_guidelines(cls, value: str | None) -> str | None:
        return ProjectSettings.bounded_guidelines(value)

    @field_validator("automation_enabled", "confidence_floor")
    @classmethod
    def reject_null_settings(cls, value: bool | float | None) -> bool | float:
        if value is None:
            raise ValueError("Project setting cannot be null")
        return value


def _version_from_header(value: str | None) -> int:
    if value is None:
        raise HTTPException(428, "If-Match settings version is required")
    try:
        version = int(value.strip('"'))
    except ValueError:
        raise HTTPException(422, "Invalid If-Match settings version") from None
    if version < 1:
        raise HTTPException(422, "Invalid If-Match settings version")
    return version


@router.get("/{project_id}")
async def get_project(project_id: UUID, session: Session, tenant: Tenant) -> dict:
    project, role = await _project(session, project_id, tenant)
    modality_locked = await check_modality_locked(project, session)
    return {"id": str(project.id), "public_domain_id": project.public_domain_id,
            "name": project.domain_name, "description": project.description,
            "status": project.status, "automation_enabled": project.automation_enabled,
            "confidence_floor": project.confidence_floor,
            "guidelines": project.guidelines,
            "guidelines_updated_at": (project.guidelines_updated_at.isoformat()
                                      if project.guidelines_updated_at else None),
            "content_type": project.content_type, "label_schema": project.label_schema,
            "modality_enforced": project.modality_enforced,
            "modality_locked": modality_locked,
            "settings_version": project.settings_version, "role": role}


@router.patch("/{project_id}")
async def patch_project(project_id: UUID, payload: ProjectPatch, session: Session, tenant: Tenant,
                        if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> dict:
    version = _version_from_header(if_match)
    values = payload.model_dump(exclude_unset=True)
    return await update_settings(project_id, ProjectSettings(settings_version=version, **values),
                                 session, tenant)


@router.delete("/{project_id}")
async def archive_project(project_id: UUID, session: Session, tenant: Tenant,
                          if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> dict:
    version = _version_from_header(if_match)
    return await update_settings(project_id, ProjectSettings(settings_version=version, status="archived"),
                                 session, tenant)


@router.put("/{project_id}/settings")
async def update_settings(project_id: UUID, payload: ProjectSettings, session: Session,
                          tenant: Tenant) -> dict:
    project, role = await _project(session, project_id, tenant, {"owner", "admin"})
    if "status" in payload.model_fields_set and payload.status is None:
        raise HTTPException(422, "Project status cannot be null")
    target_status = payload.status if payload.status is not None else project.status
    if role != "owner" and (project.status != "active" or target_status != project.status):
        raise HTTPException(403, "Only the project owner can change lifecycle status")
    explicit_axes = bool({"content_type", "label_schema"} & payload.model_fields_set)
    explicit_enforcement = "modality_enforced" in payload.model_fields_set
    if (("content_type" in payload.model_fields_set and payload.content_type is None) or
            ("label_schema" in payload.model_fields_set and payload.label_schema is None) or
            (explicit_enforcement and payload.modality_enforced is None)):
        raise HTTPException(422, "Invalid project modality")
    if explicit_enforcement and payload.modality_enforced is False and project.modality_enforced:
        raise HTTPException(422, "Project modality cannot be unenforced")
    modality_locked = await check_modality_locked(project, session)
    policy_change = explicit_axes or (explicit_enforcement and payload.modality_enforced is True)
    if policy_change and project.status != "active":
        raise HTTPException(409, "Project is not active")
    if policy_change and modality_locked:
        raise HTTPException(409, "Project modality is locked after the first label")
    content_type = payload.content_type if "content_type" in payload.model_fields_set else project.content_type
    label_schema = payload.label_schema if "label_schema" in payload.model_fields_set else project.label_schema
    if policy_change:
        content_type, label_schema = validate_project_modality(content_type, label_schema)
    values: dict[str, object] = {"settings_version": payload.settings_version + 1}
    for field in ("description", "status", "automation_enabled", "confidence_floor", "guidelines"):
        if field in payload.model_fields_set:
            values[field] = getattr(payload, field)
    if "guidelines" in payload.model_fields_set:
        values["guidelines_updated_at"] = datetime.now(timezone.utc)
    if explicit_axes:
        values.update(content_type=content_type, label_schema=label_schema,
                      modality_enforced=True)
    elif explicit_enforcement and payload.modality_enforced is True:
        values["modality_enforced"] = True
    result = await session.execute(update(Domain).where(
        Domain.id == project.id, Domain.settings_version == payload.settings_version).values(**values))
    if getattr(result, "rowcount", None) != 1:
        raise HTTPException(409, "Project settings changed; reload and retry")
    if payload.status in {"completed", "archived"}:
        endpoints = await session.scalars(select(WebhookEndpoint).where(
            WebhookEndpoint.project_id == project_id, WebhookEndpoint.active.is_(True)
        ).order_by(WebhookEndpoint.id).with_for_update())
        for endpoint in endpoints:
            await cancel_open_deliveries(session, endpoint, endpoint.destination_version)
            if target_status == "archived":
                endpoint.active = False
            endpoint.destination_version += 1
            endpoint.updated_at = datetime.now(timezone.utc)
    await commit_write(session)
    return {"id": str(project_id), "settings_version": payload.settings_version + 1,
            "status": target_status,
            "content_type": content_type, "label_schema": label_schema,
            "modality_enforced": bool(values.get("modality_enforced", project.modality_enforced)),
            "modality_locked": modality_locked}


class AddMember(BaseModel):
    member_tenant_id: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern="^(admin|reviewer|annotator)$")


@router.post("/{project_id}/members", status_code=201)
async def add_member(project_id: UUID, payload: AddMember, session: Session, tenant: Tenant) -> dict:
    project, actor_role = await _project(session, project_id, tenant, {"owner", "admin"})
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, project.tenant_id, actor)
    if project.status != "active":
        raise HTTPException(409, "Project is not active")
    if payload.member_tenant_id == project.tenant_id or payload.member_tenant_id == tenant:
        raise HTTPException(403, "Cannot change owner or own project role")
    if payload.role == "admin" and actor_role != "owner":
        raise HTTPException(403, "Only the project owner can grant admin access")
    if not await session.scalar(select(ApiKey.id).where(
            ApiKey.tenant_id == payload.member_tenant_id, ApiKey.is_active.is_(True))):
        raise HTTPException(404, "Member account not found")
    member = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.member_tenant_id == payload.member_tenant_id))
    if member is not None and member.role == "admin" and actor_role != "owner":
        raise HTTPException(403, "Only the project owner can change admin access")
    if member is None:
        member = ProjectMember(project_id=project_id, member_tenant_id=payload.member_tenant_id,
                               role=payload.role, granted_by_key_id=actor.id,
                               created_at=datetime.now(timezone.utc))
        session.add(member)
    else:
        member.role = payload.role
        member.active = True
        member.revoked_at = None
    await commit_write(session)
    return {"id": str(member.id), "role": member.role}


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: str = Field(pattern="^(admin|reviewer|annotator)$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


@router.post("/{project_id}/invites", status_code=201)
async def invite_member(project_id: UUID, payload: InviteRequest, session: Session,
                        tenant: Tenant) -> dict:
    project, actor_role = await _project(session, project_id, tenant, {"owner", "admin"})
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, project.tenant_id, actor)
    if project.status != "active":
        raise HTTPException(409, "Project is not active")
    if payload.role == "admin" and actor_role != "owner":
        raise HTTPException(403, "Only the project owner can grant admin access")
    if actor.signup_email and actor.signup_email.lower() == payload.email:
        raise HTTPException(403, "Cannot invite yourself")
    now = datetime.now(timezone.utc)
    pending = await session.scalar(select(ProjectInvite).where(
        ProjectInvite.project_id == project_id, ProjectInvite.email == payload.email,
        ProjectInvite.consumed_at.is_(None), ProjectInvite.revoked_at.is_(None)).with_for_update())
    if pending is not None:
        pending.revoked_at = now
        await session.flush()
    token = secrets.token_hex(32)
    invite = ProjectInvite(project_id=project_id, email=payload.email, role=payload.role,
                           issued_by_key_id=actor.id,
                           token_digest=hashlib.sha256(token.encode()).hexdigest(),
                           expires_at=now + timedelta(hours=48), mail_status="pending")
    session.add(invite)
    await commit_write(session)
    sent = await send_email(payload.email, "DLJ project invitation",
                            f"<p>Invitation code: {escape(token)}</p>")
    if sent:
        invite.mail_status = "sent"
        invite.last_mail_attempt_at = datetime.now(timezone.utc)
        await commit_write(session)
    return {"id": str(invite.id), "mail_status": invite.mail_status}


class AcceptInvite(BaseModel):
    token: str = Field(min_length=64, max_length=64)


@router.post("/{project_id}/invites/{invite_id}/accept")
async def accept_invite(project_id: UUID, invite_id: UUID, payload: AcceptInvite,
                        session: Session, tenant: Tenant) -> dict:
    project = await session.get(Domain, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    initial_invite = await session.get(ProjectInvite, invite_id)
    if initial_invite is None or initial_invite.project_id != project_id:
        raise HTTPException(403, "Invalid invitation")
    await lock_tenant(session, project.tenant_id)
    if tenant == project.tenant_id:
        raise HTTPException(403, "Project owner cannot accept a membership invitation")
    actor = await _actor(session, tenant)
    owner = await session.get(ProjectBillingOwner, project.tenant_id)
    if owner is None:
        raise HTTPException(403, "Project billing owner is unavailable")
    key_ids = sorted({owner.billing_key_id, initial_invite.issued_by_key_id, actor.id})
    locked_keys = (await session.scalars(select(ApiKey).where(ApiKey.id.in_(key_ids))
        .order_by(ApiKey.id).with_for_update().execution_options(populate_existing=True))).all()
    keys_by_id = {key.id: key for key in locked_keys}
    locked_actor = keys_by_id.get(actor.id)
    if (locked_actor is None or not locked_actor.is_active
            or locked_actor.key_hash != session.info.get("api_key_hash")
            or locked_actor.email_verified_at is None or not locked_actor.signup_email):
        raise HTTPException(403, "Invitation cannot be accepted")
    actor = locked_actor
    actor_email = actor.signup_email
    assert actor_email is not None
    payer = keys_by_id.get(owner.billing_key_id)
    if payer is None:
        raise HTTPException(403, "Project is read-only while the payer is not entitled")
    require_payer_eligibility(payer, "member_write")
    issuer = keys_by_id.get(initial_invite.issued_by_key_id)
    if issuer is None or not issuer.is_active:
        raise HTTPException(403, "Invitation issuer is no longer authorized")
    project = await session.get(Domain, project_id, with_for_update=True, populate_existing=True)
    if project is None or project.status != "active":
        raise HTTPException(409, "Project is not active")
    invite = await session.scalar(select(ProjectInvite).where(
        ProjectInvite.id == invite_id, ProjectInvite.project_id == project_id).with_for_update()
        .execution_options(populate_existing=True))
    if (invite is None or invite.email != actor_email.lower()
            or invite.issued_by_key_id != issuer.id
            or invite.token_digest != hashlib.sha256(payload.token.encode()).hexdigest()
            or invite.consumed_at is not None or invite.revoked_at is not None):
        raise HTTPException(403, "Invalid invitation")
    if issuer.tenant_id != project.tenant_id:
        issuer_member = await session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.member_tenant_id == issuer.tenant_id,
            ProjectMember.active.is_(True)).with_for_update())
        if issuer_member is None or issuer_member.role != "admin" or invite.role == "admin":
            raise HTTPException(403, "Invitation issuer is no longer authorized")
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(403, "Invitation expired")
    claimed = await session.execute(update(ProjectInvite).where(
        ProjectInvite.id == invite_id, ProjectInvite.consumed_at.is_(None),
        ProjectInvite.revoked_at.is_(None)).values(consumed_at=datetime.now(timezone.utc)))
    if getattr(claimed, "rowcount", None) != 1:
        raise HTTPException(403, "Invalid invitation")
    member = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.member_tenant_id == tenant))
    if member is None:
        member = ProjectMember(project_id=project_id, member_tenant_id=tenant,
                               role=invite.role, granted_by_key_id=invite.issued_by_key_id,
                               created_at=datetime.now(timezone.utc))
        session.add(member)
        await session.flush()
    else:
        member.active = True
        member.role = invite.role
        member.revoked_at = None
    invite.consumed_at = datetime.now(timezone.utc)
    invite.accepted_by_key_id = actor.id
    invite.accepted_member_id = member.id
    await commit_write(session)
    return {"project_id": str(project_id), "role": member.role}
