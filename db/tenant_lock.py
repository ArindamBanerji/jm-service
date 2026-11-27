"""Serialize billing, key issuance and retention for one DLJ tenant."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TenantGuard


async def lock_tenant(session: AsyncSession, tenant_id: str) -> None:
    guard = select(TenantGuard.tenant_id).where(TenantGuard.tenant_id == tenant_id).with_for_update()
    if session.get_bind().dialect.name == "postgresql" and await session.scalar(guard) is not None:
        return
    await session.execute(text(
        "INSERT INTO tenant_guard (tenant_id) VALUES (:tenant) ON CONFLICT DO NOTHING"),
        {"tenant": tenant_id})
    await session.scalar(guard)
