"""Database isolation shared by independent application and observer connections."""
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from db.connection import enable_sqlite_foreign_keys, normalize_database_url
from db.models import Base


@asynccontextmanager
async def database(directory: Path, sqlite: bool) -> AsyncIterator[AsyncEngine]:
    if sqlite:
        engine = create_async_engine(f"sqlite+aiosqlite:///{(directory / 'modern.db').as_posix()}", poolclass=NullPool)
        enable_sqlite_foreign_keys(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            yield engine
        finally:
            await engine.dispose()
        return

    url, options = normalize_database_url(os.getenv(
        "DLJ_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/dlj_test"))
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("The primary harness requires PostgreSQL. Select the SQLite advisory option explicitly.")
    schema = "harness_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool, connect_args=options)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        try:
            engine = create_async_engine(url, poolclass=NullPool, connect_args={
                **options, "server_settings": {"search_path": schema}})
            try:
                async with engine.begin() as conn:
                    assert await conn.scalar(text("SELECT current_schema()")) == schema
                    await conn.run_sync(Base.metadata.create_all)
                yield engine
            finally:
                await engine.dispose()
        finally:
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await admin.dispose()
