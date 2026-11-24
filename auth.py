"""Tenant credentials and stable internal domain identities."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import ApiKey
from email_service import send_api_key_email
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


@signup_router.post("/register", status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterRequest, session: Session) -> dict[str, str]:
    existing = await session.scalar(select(ApiKey.id).where(func.lower(ApiKey.contact_email) == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    tenant_id = str(uuid4())
    plain, record = generate_api_key(tenant_id, payload.name or payload.email.split("@", 1)[0])
    record.tier = "trial"
    record.contact_email = payload.email
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    if not await send_api_key_email(payload.email, plain):
        logger.warning("API key email delivery failed for tenant %s", tenant_id)
    return {"api_key": plain, "tenant_id": tenant_id, "tier": "trial",
            "message": "Save this key — it cannot be recovered."}


def scoped_domain_id(tenant_id: str, domain_id: str) -> str:
    """Resolve the public domain name to a collision-resistant, private key."""
    return (hashlib.sha256(f"{tenant_id}\0{domain_id}".encode()).hexdigest()
            if tenant_id else domain_id)


def generate_api_key(tenant_id: str, tenant_name: str) -> tuple[str, ApiKey]:
    plain = secrets.token_hex(32)
    return plain, ApiKey(key_hash=hashlib.sha256(plain.encode()).hexdigest(),
                         tenant_id=tenant_id, tenant_name=tenant_name)


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
    plain, record = generate_api_key(payload.tenant_id, payload.tenant_name)
    session.add(record)
    await session.flush()
    return {"api_key": plain, "tenant_id": payload.tenant_id}
