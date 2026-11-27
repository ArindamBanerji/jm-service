"""Async database engine and request-scoped sessions."""
from __future__ import annotations

import os
import re
import logging
from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

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
            raise ValueError("Unsupported database SSL mode")
        return clean_url, {"ssl": ssl_modes[-1] == "require"}
    # Railway private network: no SSL needed (self-signed cert, traffic already isolated)
    hostname = parsed.hostname or ""
    if hostname.endswith(".railway.internal"):
        return clean_url, {"ssl": False}
    if os.getenv("RAILWAY_ENVIRONMENT"):
        return clean_url, {"ssl": True}
    return clean_url, {}


def sanitize_url(url: str) -> str:
    """Hide URL userinfo and credential-like query parameters in diagnostics."""
    parsed = urlsplit(url)
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if ":" in userinfo:
            netloc = f"{userinfo.split(':', 1)[0]}:***@{host}"
    query = urlencode([(key, "***" if key.lower() in {"password", "token", "api_key"} else value)
                       for key, value in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit(parsed._replace(netloc=netloc, query=query))


def sanitize_database_error(exc: Exception) -> str:
    """Return only approved diagnostic fields, never statement values or driver detail."""
    try:
        parts = [type(exc).__name__]
        statement = getattr(exc, "statement", None)
        if isinstance(statement, str):
            operation = re.match(r"\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM|SELECT\s+FROM|ALTER\s+TABLE)\s+([A-Za-z_][\w.]*)", statement, re.I)
            if operation:
                parts.append(f"{operation.group(1).upper()} {operation.group(2)}")
        source = getattr(exc, "orig", exc)
        state = getattr(source, "sqlstate", None) or getattr(source, "pgcode", None)
        if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state, re.I):
            parts.append(f"SQLSTATE {state}")
        return "; ".join(parts)
    except Exception:
        return "Database operation failed (diagnostics withheld)"


async def commit_write(session: AsyncSession) -> None:
    """Make a database write durable before an HTTP success is returned."""
    try:
        await session.commit()
    except Exception as exc:
        try:
            await session.rollback()
        except Exception:
            pass
        raise HTTPException(500, detail=f"Database commit failed: {sanitize_database_error(exc)}") from None


try:
    DATABASE_URL, CONNECT_ARGS = normalize_database_url(
        os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/jm_labeling"))
except Exception:
    raise RuntimeError("Database URL is invalid (details withheld)") from None
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.WARNING)
try:
    engine = create_async_engine(DATABASE_URL, connect_args=CONNECT_ARGS,
                                 echo=False, hide_parameters=True,
                                 **({"pool_size": 5, "max_overflow": 10} if DATABASE_URL.startswith("postgresql") else {}))
except Exception as exc:
    raise RuntimeError(f"Database engine setup failed: {sanitize_database_error(exc)}") from None


def enable_sqlite_foreign_keys(db_engine: AsyncEngine) -> None:
    if db_engine.dialect.name == "sqlite":
        @event.listens_for(db_engine.sync_engine, "connect")
        def set_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()


enable_sqlite_foreign_keys(engine)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except SQLAlchemyError as exc:
            try:
                await session.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Database operation failed: {sanitize_database_error(exc)}") from None
        except BaseException:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
