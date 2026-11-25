"""Project administration, team membership and invitation endpoints."""
from __future__ import annotations

import hashlib
import secrets
from html import escape
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Tenant, scoped_domain_id
from db.connection import commit_write, get_db
from db.models import ApiKey, Domain, ProjectBillingOwner, ProjectInvite, ProjectMember
from db.repository import create_domain
from db.tenant_lock import lock_tenant
from email_service import send_email
from jm_core import DomainConfig

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
    if project.tenant_id == tenant:
        role = "owner"
    else:
        member = await session.scalar(select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.member_tenant_id == tenant,
            ProjectMember.active.is_(True)))
        if member is None:
            raise HTTPException(404, "Project not found")
        role = member.role
    if allowed is not None and role not in allowed:
        raise HTTPException(403, "Project role does not allow this action")
    if allowed is not None and role != "owner":
        owner = await session.get(ProjectBillingOwner, project.tenant_id)
        payer = (await session.get(ApiKey, owner.billing_key_id,
                                   with_for_update=True, populate_existing=True)
                 if owner is not None else None)
        if payer is None or not payer.is_active or payer.subscription_state in {
                "past_due", "paused", "cancelled", "cleaned_up", "trial_expired"}:
            raise HTTPException(403, "Project is read-only while the payer is not entitled")
    return project, role


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    public_domain_id: str = Field(min_length=1, max_length=200)
    factors: list[str] = Field(min_length=1, max_length=20)
    categories: list[str] = Field(min_length=1, max_length=20)
    actions: list[str] = Field(default_factory=lambda: ["approve", "reject"])


@router.post("", status_code=201)
async def create_project(payload: ProjectCreate, session: Session, tenant: Tenant) -> dict:
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, tenant, actor)
    if await session.scalar(select(ApiKey.id).where(
            ApiKey.tenant_id == tenant, ApiKey.subscription_state == "cleaned_up")):
        raise HTTPException(409, "Tenant has been cleaned up")
    scoped = scoped_domain_id(tenant, payload.public_domain_id)
    if await session.scalar(select(Domain.id).where(Domain.domain_id == scoped)):
        raise HTTPException(409, "Project already exists")
    config = DomainConfig(scoped, payload.name, payload.factors, payload.categories, payload.actions)
    project = await create_domain(session, scoped, payload.name, config, tenant, payload.public_domain_id)
    session.add(ProjectMember(project_id=project.id, member_tenant_id=tenant,
                              role="admin", granted_by_key_id=actor.id,
                              created_at=datetime.now(timezone.utc)))
    await commit_write(session)
    return {"id": str(project.id), "public_domain_id": payload.public_domain_id,
            "name": payload.name, "status": project.status, "settings_version": project.settings_version}


@router.get("")
async def list_projects(session: Session, tenant: Tenant) -> list[dict]:
    member_ids = select(ProjectMember.project_id).where(
        ProjectMember.member_tenant_id == tenant, ProjectMember.active.is_(True))
    rows = (await session.scalars(select(Domain).where(or_(
        Domain.tenant_id == tenant, Domain.id.in_(member_ids))).order_by(Domain.created_at, Domain.id))).all()
    return [{"id": str(row.id), "public_domain_id": row.public_domain_id,
             "name": row.domain_name, "description": row.description, "status": row.status,
             "settings_version": row.settings_version} for row in rows]


class ProjectSettings(BaseModel):
    settings_version: int = Field(ge=1)
    description: str | None = Field(default=None, max_length=10_000)
    status: str = Field(pattern="^(active|archived|completed)$")
    automation_enabled: bool = False
    confidence_floor: float = Field(default=.95, ge=.80, le=.99)


@router.put("/{project_id}/settings")
async def update_settings(project_id: UUID, payload: ProjectSettings, session: Session,
                          tenant: Tenant) -> dict:
    project, role = await _project(session, project_id, tenant, {"owner", "admin"})
    if role != "owner" and (project.status != "active" or payload.status != project.status):
        raise HTTPException(403, "Only the project owner can change lifecycle status")
    result = await session.execute(update(Domain).where(
        Domain.id == project.id, Domain.settings_version == payload.settings_version).values(
        description=payload.description, status=payload.status,
        automation_enabled=payload.automation_enabled,
        confidence_floor=payload.confidence_floor,
        settings_version=payload.settings_version + 1))
    if getattr(result, "rowcount", None) != 1:
        raise HTTPException(409, "Project settings changed; reload and retry")
    await commit_write(session)
    return {"id": str(project_id), "settings_version": payload.settings_version + 1,
            "status": payload.status}


class AddMember(BaseModel):
    member_tenant_id: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern="^(admin|reviewer|annotator)$")


@router.post("/{project_id}/members", status_code=201)
async def add_member(project_id: UUID, payload: AddMember, session: Session, tenant: Tenant) -> dict:
    project, _ = await _project(session, project_id, tenant, {"owner", "admin"})
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, project.tenant_id, actor)
    if project.status != "active":
        raise HTTPException(409, "Project is not active")
    if not await session.scalar(select(ApiKey.id).where(
            ApiKey.tenant_id == payload.member_tenant_id, ApiKey.is_active.is_(True))):
        raise HTTPException(404, "Member account not found")
    member = await session.scalar(select(ProjectMember).where(
        ProjectMember.project_id == project_id,
        ProjectMember.member_tenant_id == payload.member_tenant_id))
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
    project, _ = await _project(session, project_id, tenant, {"owner", "admin"})
    actor = await _actor(session, tenant)
    await _ensure_billing_owner(session, project.tenant_id, actor)
    if project.status != "active":
        raise HTTPException(409, "Project is not active")
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
                           expires_at=now + timedelta(days=7), mail_status="pending")
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
    actor = await _actor(session, tenant)
    if project.status != "active" or not actor.contact_email:
        raise HTTPException(403, "Invitation cannot be accepted")
    owner = await session.get(ProjectBillingOwner, project.tenant_id)
    payer = (await session.get(ApiKey, owner.billing_key_id,
                               with_for_update=True, populate_existing=True)
             if owner is not None else None)
    if payer is None or not payer.is_active or payer.subscription_state in {
            "past_due", "paused", "cancelled", "cleaned_up", "trial_expired"}:
        raise HTTPException(403, "Project is read-only while the payer is not entitled")
    invite = await session.scalar(select(ProjectInvite).where(
        ProjectInvite.id == invite_id, ProjectInvite.project_id == project_id).with_for_update())
    if (invite is None or invite.email != actor.contact_email.lower()
            or invite.token_digest != hashlib.sha256(payload.token.encode()).hexdigest()
            or invite.consumed_at is not None or invite.revoked_at is not None):
        raise HTTPException(403, "Invalid invitation")
    expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(403, "Invitation expired")
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
