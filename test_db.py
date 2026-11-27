"""Persistence contract tests against isolated in-memory SQLite."""
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm.exc import StaleDataError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import repository as repo
from db import connection as db_connection
from db.models import Base, Engine, LabelLog
from jm_core import DomainConfig, JudgmentMemoryEngine

pytestmark = pytest.mark.sqlite_only


@asynccontextmanager
async def database():
    database_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with database_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(database_engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await database_engine.dispose()


def config(domain_id="d"):
    return DomainConfig(domain_id, "Demo", ["confidence", "difficulty"], ["NER", "other"], ["approve", "reject"])


async def domain(session, domain_id="d"):
    await repo.create_domain(session, domain_id, "Demo", config(domain_id))


@pytest.mark.asyncio
async def test_session_creates(monkeypatch):
    async with database() as session:
        monkeypatch.setattr(db_connection, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
        dependency = cast(AsyncGenerator, db_connection.get_db())
        provided = await anext(dependency)
        assert await provided.scalar(text("SELECT 1")) == 1
        with pytest.raises(StopAsyncIteration):
            await anext(dependency)


@pytest.mark.asyncio
async def test_session_rollback_on_error(monkeypatch):
    async with database() as session:
        monkeypatch.setattr(db_connection, "AsyncSessionLocal", async_sessionmaker(session.bind, expire_on_commit=False))
        dependency = cast(AsyncGenerator, db_connection.get_db())
        provided = await anext(dependency)
        await domain(provided)
        with pytest.raises(RuntimeError):
            await dependency.athrow(RuntimeError("rollback"))
        assert await repo.get_domain(session, "d") is None


@pytest.mark.asyncio
async def test_create_domain():
    async with database() as session:
        await domain(session)
        row = await repo.get_domain(session, "d")
        assert row is not None and row.config_json["factors"] == ["confidence", "difficulty"]


@pytest.mark.asyncio
async def test_duplicate_domain():
    async with database() as session:
        await domain(session)
        with pytest.raises(Exception):
            await domain(session)


@pytest.mark.asyncio
async def test_list_domains():
    async with database() as session:
        for name in ("a", "b", "c"):
            await domain(session, name)
        assert len(await repo.list_domains(session)) == 3


@pytest.mark.asyncio
async def test_save_and_load_engine():
    async with database() as session:
        await domain(session)
        source = JudgmentMemoryEngine(config())
        source.score({"confidence": .8, "difficulty": .2}, "NER")
        await repo.save_engine_state(session, "d", None, source)
        loaded = await repo.load_engine(session, "d")
        assert loaded is not None and loaded.export_state() == source.export_state()


@pytest.mark.asyncio
async def test_load_or_create_fresh():
    async with database() as session:
        await domain(session)
        engine = await repo.load_or_create_engine(session, "d")
        assert engine.config.factors == ["confidence", "difficulty"]
        assert engine.total_decisions == 0


@pytest.mark.asyncio
async def test_version_increment():
    async with database() as session:
        await domain(session)
        engine = JudgmentMemoryEngine(config())
        await repo.save_engine_state(session, "d", None, engine)
        stale = await repo.load_engine(session, "d")
        saved = await repo.save_engine_state(session, "d", None, engine)
        assert saved.version == 2
        assert stale is not None
        with pytest.raises(StaleDataError):
            await repo.save_engine_state(session, "d", None, stale)


@pytest.mark.asyncio
async def test_per_annotator_engine():
    async with database() as session:
        await domain(session)
        engine = JudgmentMemoryEngine(config())
        await repo.save_engine_state(session, "d", "alex", engine)
        assert await repo.load_engine(session, "d") is None
        loaded = await repo.load_engine(session, "d", "alex")
        assert loaded is not None and loaded.export_state() == engine.export_state()


@pytest.mark.asyncio
async def test_record_score():
    async with database() as session:
        await domain(session)
        await repo.record_score(session, "d", "L1", "alex", "NER", {"confidence": .8}, "approve", .7)
        rows = await repo.get_label_log(session, "d")
        assert len(rows) == 1 and rows[0].confidence == .7


@pytest.mark.asyncio
async def test_record_verification():
    async with database() as session:
        await domain(session)
        await repo.record_score(session, "d", "L1", None, "NER", {"confidence": .8}, "approve", .7)
        row = await repo.record_verification(session, "d", "L1", "reject", False)
        assert row.actual_action == "reject" and row.verified_outcome is False and row.verified_at


@pytest.mark.asyncio
async def test_get_label_log_filtered():
    async with database() as session:
        await domain(session)
        for index in range(10):
            await repo.record_score(session, "d", f"L{index}", "alex", "NER" if index % 2 else "other",
                                    {"confidence": .8}, "approve", .7)
        rows = await repo.get_label_log(session, "d", category="NER", annotator_id="alex", limit=3)
        assert len(rows) == 3 and all(row.category == "NER" for row in rows)


@pytest.mark.asyncio
async def test_score_and_persist():
    async with database() as session:
        await domain(session)
        engine = JudgmentMemoryEngine(config())
        result = await repo.score_and_persist(
            session, engine, "d", "L1", None, "NER", {"confidence": .8, "difficulty": .2}
        )
        assert (await repo.get_label_log(session, "d"))[0].recommended_action == result.recommended_action
        loaded = await repo.load_engine(session, "d")
        assert loaded is not None and loaded.total_decisions == 1


@pytest.mark.asyncio
async def test_verify_and_learn():
    async with database() as session:
        await domain(session)
        engine = JudgmentMemoryEngine(config())
        await repo.score_and_persist(
            session, engine, "d", "L1", None, "NER", {"confidence": .8, "difficulty": .2}
        )
        loaded = await repo.load_engine(session, "d")
        assert loaded is not None
        await repo.verify_and_learn(session, loaded, "d", "L1", "approve", True)
        assert (await repo.get_label_log(session, "d", verified_only=True))[0].actual_action == "approve"
        restored = await repo.load_engine(session, "d")
        assert restored is not None and restored.conservation.total_verified == 1


@pytest.mark.asyncio
async def test_upsert_annotator():
    async with database() as session:
        await domain(session)
        await repo.upsert_annotator(session, "d", "alex")
        await repo.upsert_annotator(session, "d", "alex")
        annotator = await repo.get_annotator(session, "d", "alex")
        assert annotator is not None and annotator.label_count == 2
