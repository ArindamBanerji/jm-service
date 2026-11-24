"""Tenant credentials and stable internal domain identities."""
from __future__ import annotations

import hashlib
import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.connection import get_db
from db.models import ApiKey
from rate_limit import limiter

Session = Annotated[AsyncSession, Depends(get_db)]
router = APIRouter(prefix="/v1/admin", tags=["Admin"])


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
