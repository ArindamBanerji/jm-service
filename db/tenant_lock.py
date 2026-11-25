"""Serialize billing, key issuance and retention for one DLJ tenant."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantGuard


async def lock_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(text(
        "INSERT INTO tenant_guard (tenant_id) VALUES (:tenant) ON CONFLICT DO NOTHING"),
        {"tenant": tenant_id})
    await session.scalar(select(TenantGuard).where(
        TenantGuard.tenant_id == tenant_id).with_for_update())
