"""Async database engine and request-scoped sessions."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

def normalize_database_url(url: str) -> tuple[str, dict[str, bool]]:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    if not url.startswith("postgresql+asyncpg://"):
        return url, {}
    parsed = urlsplit(url)
    options = parse_qsl(parsed.query, keep_blank_values=True)
    ssl_modes = [value for key, value in options if key == "sslmode"]
    clean_query = urlencode([(key, value) for key, value in options if key != "sslmode"])
    clean_url = urlunsplit(parsed._replace(query=clean_query))
    if ssl_modes:
        if ssl_modes[-1] not in {"require", "disable"}:
            raise ValueError(f"Unsupported sslmode: {ssl_modes[-1]}")
        return clean_url, {"ssl": ssl_modes[-1] == "require"}
    # Railway private network: no SSL needed (self-signed cert, traffic already isolated)
    hostname = parsed.hostname or ""
    if hostname.endswith(".railway.internal"):
        return clean_url, {"ssl": False}
    if os.getenv("RAILWAY_ENVIRONMENT"):
        return clean_url, {"ssl": True}
    return clean_url, {}


DATABASE_URL, CONNECT_ARGS = normalize_database_url(
    os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/jm_labeling"))
engine = create_async_engine(DATABASE_URL, connect_args=CONNECT_ARGS,
                             **({"pool_size": 5, "max_overflow": 10} if DATABASE_URL.startswith("postgresql") else {}))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
