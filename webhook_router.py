"""Project webhook administration and durable test-event creation."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import Tenant
from db.repository import cancel_open_deliveries, record_webhook_event
from db.connection import commit_write, get_db
from db.models import (Domain, WebhookAttempt, WebhookDelivery, WebhookEndpoint,
                       WebhookEvent)
from projects_router import _project
from webhook_security import encrypt_secret, validate_public_https

router = APIRouter(prefix="/v1/projects", tags=["Webhooks"])
Session = Annotated[AsyncSession, Depends(get_db)]
EVENT_TYPES = {"label.verified", "prediction.auto_approved", "webhook.test"}


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    subscribed_events: list[str] = Field(min_length=1, max_length=3)

    @field_validator("subscribed_events")
    @classmethod
    def events_are_supported(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(value not in EVENT_TYPES for value in values):
            raise ValueError("Webhook event types must be supported and unique")
        return values


class WebhookPatch(BaseModel, extra="forbid"):
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    subscribed_events: list[str] | None = Field(default=None, min_length=1, max_length=3)
    active: bool | None = None

    @field_validator("subscribed_events")
    @classmethod
    def events_are_supported(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and (
                len(values) != len(set(values)) or any(value not in EVENT_TYPES for value in values)):
            raise ValueError("Webhook event types must be supported and unique")
        return values

    @field_validator("url", "subscribed_events", "active")
    @classmethod
    def explicit_null_is_invalid(cls, value: object) -> object:
        if value is None:
            raise ValueError("Webhook updates cannot be null")
        return value

    @model_validator(mode="after")
    def update_is_not_empty(self) -> "WebhookPatch":
        if not self.model_fields_set:
            raise ValueError("At least one webhook field must be updated")
        return self


def _view(endpoint: WebhookEndpoint) -> dict:
    return {
        "id": str(endpoint.id), "project_id": str(endpoint.project_id),
        "url": endpoint.url, "subscribed_events": endpoint.subscribed_events,
        "active": endpoint.active, "key_version": endpoint.key_version,
        "destination_version": endpoint.destination_version,
        "signing_secret_masked": "dlj_whsec_****",
        # updated_at identifies a rotation only when every config change was a rotation.
        "rotated_at": (endpoint.updated_at.isoformat()
                       if endpoint.key_version > 1 and endpoint.destination_version == endpoint.key_version else None),
        "created_at": endpoint.created_at.isoformat(),
        "updated_at": endpoint.updated_at.isoformat(),
    }


async def _admin_project(session: AsyncSession, project_id: UUID, tenant: str, *,
                         write: bool = True, destination: str | None = None) -> Domain:
    project, role = await _project(session, project_id, tenant)
    if role not in {"owner", "admin"}:
        raise HTTPException(403, "Project role does not allow this action")
    if destination is not None:
        await validate_public_https(destination)
    if write:
        project, _ = await _project(session, project_id, tenant, {"owner", "admin"})
        if project.status != "active":
            raise HTTPException(409, "Project is read-only")
    return project


async def _endpoint(session: AsyncSession, project_id: UUID, endpoint_id: UUID,
                    *, lock: bool = False) -> WebhookEndpoint:
    statement = select(WebhookEndpoint).where(
        WebhookEndpoint.id == endpoint_id, WebhookEndpoint.project_id == project_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    endpoint = await session.scalar(statement)
    if endpoint is None:
        raise HTTPException(404, "Webhook endpoint not found")
    return endpoint


@router.post("/{project_id}/webhooks", status_code=201)
async def create_webhook(project_id: UUID, payload: WebhookCreate, session: Session,
                         tenant: Tenant) -> dict:
    await _admin_project(session, project_id, tenant, destination=payload.url)
    count = await session.scalar(select(func.count()).select_from(WebhookEndpoint).where(
        WebhookEndpoint.project_id == project_id, WebhookEndpoint.active.is_(True)))
    if int(count or 0) >= 5:
        raise HTTPException(422, "A project can have at most five webhook endpoints")
    now = datetime.now(timezone.utc)
    plaintext = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(
        project_id=project_id, url=payload.url,
        secret_ciphertext=encrypt_secret(plaintext), key_version=1,
        subscribed_events=payload.subscribed_events, active=True,
        destination_version=1, created_at=now, updated_at=now)
    session.add(endpoint)
    await commit_write(session)
    return {**_view(endpoint), "signing_secret": plaintext}


@router.get("/{project_id}/webhooks")
async def list_webhooks(project_id: UUID, session: Session, tenant: Tenant) -> list[dict]:
    """List webhook configuration without disclosing signing secrets."""
    await _admin_project(session, project_id, tenant, write=False)
    rows = (await session.scalars(select(WebhookEndpoint).where(
        WebhookEndpoint.project_id == project_id).order_by(
            WebhookEndpoint.created_at, WebhookEndpoint.id))).all()
    return [_view(row) for row in rows]


def _health_state(endpoint: WebhookEndpoint, delivery: WebhookDelivery | None) -> str:
    if not endpoint.active:
        return "paused"
    if delivery is None:
        return "awaiting"
    if delivery.state == "delivered":
        return "healthy"
    if delivery.state == "dead":
        return "failing"
    if delivery.state in {"pending", "leased"} and delivery.attempts > 0:
        return "retrying"
    return "healthy"


@router.get("/{project_id}/webhooks/health")
async def webhook_health(project_id: UUID, session: Session, tenant: Tenant) -> dict:
    """Return the latest durable delivery health for every project endpoint."""
    await _admin_project(session, project_id, tenant, write=False)
    endpoints = (await session.scalars(select(WebhookEndpoint).where(
        WebhookEndpoint.project_id == project_id).order_by(
            WebhookEndpoint.created_at, WebhookEndpoint.id))).all()
    ranked = select(WebhookDelivery.id, func.row_number().over(
        partition_by=WebhookDelivery.endpoint_id,
        order_by=(WebhookAttempt.started_at.desc(), WebhookAttempt.attempt_no.desc(),
                  WebhookDelivery.id.desc())).label("rank")).join(
            WebhookAttempt, WebhookAttempt.delivery_id == WebhookDelivery.id).join(
            WebhookEndpoint, WebhookEndpoint.id == WebhookDelivery.endpoint_id).where(
                WebhookEndpoint.project_id == project_id,
                WebhookEndpoint.destination_version == WebhookDelivery.destination_version).subquery()
    latest = await session.scalars(select(WebhookDelivery).join(
        ranked, ranked.c.id == WebhookDelivery.id).where(ranked.c.rank == 1))
    by_endpoint = {row.endpoint_id: row for row in latest}
    items: list[dict] = []
    for endpoint in endpoints:
        delivery = by_endpoint.get(endpoint.id)
        status = _health_state(endpoint, delivery)
        items.append({
            "webhook_id": str(endpoint.id), "status": status, "active": endpoint.active,
            "last_delivery_state": delivery.state if delivery else None,
            "last_status": delivery.last_status if delivery else None,
            "last_delivered_at": (delivery.delivered_at.isoformat()
                                  if delivery and delivery.delivered_at else None),
            "next_retry_at": (delivery.next_attempt_at.isoformat()
                              if delivery and delivery.next_attempt_at else None),
        })
    healthy = sum(item["status"] == "healthy" for item in items)
    retrying = sum(item["status"] == "retrying" for item in items)
    failing = sum(item["status"] == "failing" for item in items)
    return {"total": len(items), "healthy": healthy, "retrying": retrying,
            "failing": failing, "items": items}


@router.get("/{project_id}/webhooks/{endpoint_id}/deliveries")
async def list_deliveries(project_id: UUID, endpoint_id: UUID, session: Session,
                          tenant: Tenant, limit: int = Query(50, ge=1, le=100),
                          offset: int = Query(0, ge=0)) -> dict:
    """Return paginated deliveries plus the endpoint's latest twenty attempts."""
    await _admin_project(session, project_id, tenant, write=False)
    endpoint = await _endpoint(session, project_id, endpoint_id)
    predicate = WebhookDelivery.endpoint_id == endpoint.id
    total = int(await session.scalar(select(func.count()).select_from(
        WebhookDelivery).where(predicate)) or 0)
    rows = (await session.execute(select(WebhookDelivery, WebhookEvent).join(
        WebhookEvent, WebhookEvent.id == WebhookDelivery.event_id).where(
            predicate).order_by(WebhookEvent.created_at.desc(), WebhookDelivery.id)
        .offset(offset).limit(limit))).all()
    attempts = (await session.execute(select(
        WebhookAttempt, WebhookDelivery, WebhookEvent
    ).join(WebhookDelivery, WebhookDelivery.id == WebhookAttempt.delivery_id).join(
        WebhookEvent, WebhookEvent.id == WebhookDelivery.event_id).where(
            WebhookDelivery.endpoint_id == endpoint.id).order_by(
                WebhookAttempt.started_at.desc(), WebhookAttempt.attempt_no.desc()).limit(20))).all()
    return {
        "items": [{
            "id": str(delivery.id), "event_id": str(event.id),
            "event_type": event.event_type, "destination_version": delivery.destination_version,
            "state": delivery.state, "attempts": delivery.attempts,
            "next_attempt_at": (delivery.next_attempt_at.isoformat()
                                if delivery.next_attempt_at is not None else None),
            "delivered_at": (delivery.delivered_at.isoformat()
                             if delivery.delivered_at is not None else None),
            "last_status": delivery.last_status, "error_class": delivery.error_class,
        } for delivery, event in rows],
        "attempt_history": [{
            "delivery_id": str(delivery.id), "event_id": str(event.id),
            "event_type": event.event_type, "attempt_no": attempt.attempt_no,
            "timestamp": attempt.started_at.isoformat(), "http_status": attempt.http_status,
            "outcome": attempt.outcome,
            "response_time_ms": (max(0, int((attempt.finished_at - attempt.started_at).total_seconds() * 1000))
                                 if attempt.finished_at is not None else None),
            "next_retry_at": (delivery.next_attempt_at.isoformat()
                              if delivery.next_attempt_at is not None and attempt.attempt_no == delivery.attempts else None),
            "error_summary": (attempt.outcome if attempt.outcome not in {"success", "delivered"} else None),
        } for attempt, delivery, event in attempts],
        "total": total, "limit": limit, "offset": offset,
    }


@router.patch("/{project_id}/webhooks/{endpoint_id}")
async def update_webhook(project_id: UUID, endpoint_id: UUID, payload: WebhookPatch,
                         session: Session, tenant: Tenant) -> dict:
    await _admin_project(session, project_id, tenant, destination=payload.url)
    endpoint = await _endpoint(session, project_id, endpoint_id, lock=True)
    if "active" in payload.model_fields_set and payload.active and not endpoint.active:
        count = await session.scalar(select(func.count()).select_from(WebhookEndpoint).where(
            WebhookEndpoint.project_id == project_id, WebhookEndpoint.active.is_(True)))
        if int(count or 0) >= 5:
            raise HTTPException(422, "A project can have at most five active webhook endpoints")
    old_version = endpoint.destination_version
    if "url" in payload.model_fields_set:
        endpoint.url = payload.url  # type: ignore[assignment]
    if "subscribed_events" in payload.model_fields_set:
        endpoint.subscribed_events = payload.subscribed_events  # type: ignore[assignment]
    if "active" in payload.model_fields_set:
        endpoint.active = payload.active  # type: ignore[assignment]
    endpoint.destination_version += 1
    endpoint.updated_at = datetime.now(timezone.utc)
    await cancel_open_deliveries(session, endpoint, old_version)
    await commit_write(session)
    return _view(endpoint)


@router.delete("/{project_id}/webhooks/{endpoint_id}")
async def delete_webhook(project_id: UUID, endpoint_id: UUID, session: Session,
                         tenant: Tenant) -> dict:
    await _admin_project(session, project_id, tenant)
    endpoint = await _endpoint(session, project_id, endpoint_id, lock=True)
    old_version = endpoint.destination_version
    endpoint.active = False
    endpoint.destination_version += 1
    endpoint.updated_at = datetime.now(timezone.utc)
    await cancel_open_deliveries(session, endpoint, old_version)
    await commit_write(session)
    return _view(endpoint)


@router.post("/{project_id}/webhooks/{endpoint_id}/rotate")
async def rotate_webhook(project_id: UUID, endpoint_id: UUID, session: Session,
                         tenant: Tenant) -> dict:
    await _admin_project(session, project_id, tenant)
    endpoint = await _endpoint(session, project_id, endpoint_id, lock=True)
    old_version = endpoint.destination_version
    plaintext = secrets.token_urlsafe(32)
    endpoint.secret_ciphertext = encrypt_secret(plaintext)
    endpoint.key_version += 1
    endpoint.destination_version += 1
    endpoint.updated_at = datetime.now(timezone.utc)
    await cancel_open_deliveries(session, endpoint, old_version)
    await commit_write(session)
    return {**_view(endpoint), "signing_secret": plaintext}


@router.post("/{project_id}/webhooks/{endpoint_id}/test", status_code=201)
async def test_webhook(project_id: UUID, endpoint_id: UUID, session: Session,
                       tenant: Tenant) -> dict:
    project = await _admin_project(session, project_id, tenant)
    endpoint = await _endpoint(session, project_id, endpoint_id, lock=True)
    if not endpoint.active:
        raise HTTPException(409, "Webhook endpoint is inactive")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    count = await session.scalar(select(func.count()).select_from(WebhookDelivery).join(
        WebhookEvent, WebhookEvent.id == WebhookDelivery.event_id).where(
            WebhookDelivery.endpoint_id == endpoint.id,
            WebhookEvent.event_type == "webhook.test",
            WebhookEvent.created_at >= cutoff))
    if int(count or 0) >= 10:
        raise HTTPException(429, "Webhook test limit reached")
    now = datetime.now(timezone.utc)
    event_id = uuid4()
    event = await record_webhook_event(session, project, "webhook.test", str(event_id),
                                       {"endpoint_id": str(endpoint.id)})
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id, event_id=event.id,
        destination_version=endpoint.destination_version,
        state="pending", attempts=0, next_attempt_at=now)
    session.add(delivery)
    await commit_write(session)
    return {"event_id": str(event.id), "delivery_id": str(delivery.id)}
