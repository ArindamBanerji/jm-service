"""Exercise the real migration on a disposable SQLite file or a private PostgreSQL schema."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import DateTime, MetaData, delete, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from db import migrate as migration
from db.connection import enable_sqlite_foreign_keys, normalize_database_url
from db.models import ApiKey, Base, Domain, LabelContent, LabelLog


pytestmark = pytest.mark.asyncio
TIMESTAMPS = {
    "label_log": ("revision_at",),
    "api_keys": ("cancelled_at", "trial_expiring_email_sent_at", "trial_expired_email_sent_at",
                 "paddle_event_occurred_at", "email_verified_at"),
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    url = os.getenv("DLJ_DATABASE_URL", "")
    if url.startswith(("postgres:", "postgresql:", "postgresql+asyncpg:")):
        url, options = normalize_database_url(url)
        schema = f"migration_test_{uuid4().hex}"
        admin = create_async_engine(url, connect_args=options, poolclass=NullPool)

        async def schema_ddl(statement):
            async with admin.begin() as conn:
                await conn.exec_driver_sql(statement)

        asyncio.run(schema_ddl(f"CREATE SCHEMA {schema}"))
        engine = create_async_engine(url, poolclass=NullPool, connect_args={
            **options, "server_settings": {"search_path": schema, "timezone": "America/Los_Angeles"},
        })
    else:
        admin = None
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'migration.db').as_posix()}")
        enable_sqlite_foreign_keys(engine)
    monkeypatch.setattr(migration, "engine", engine)
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())
        if admin is not None:
            try:
                asyncio.run(schema_ddl(f"DROP SCHEMA {schema} CASCADE"))
            finally:
                asyncio.run(admin.dispose())


async def install_legacy(db, *, strict=True):
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    labels = metadata.tables["label_log"]
    for name in ("category", "recommended_action", "confidence", "scored_at"):
        labels.c[name].nullable = not strict
    async with db.begin() as conn:
        await conn.run_sync(metadata.create_all)
        for table_name, columns in TIMESTAMPS.items():
            for name in columns:
                await conn.exec_driver_sql(f"ALTER TABLE {table_name} DROP COLUMN {name}")


async def seed_labels(db):
    ids = [uuid4() for _ in range(3)]
    async with db.begin() as conn:
        await conn.execute(Domain.__table__.insert().values(domain_id="old", domain_name="old", config_json={}))
        for i, label in enumerate(ids):
            await conn.execute(LabelLog.__table__.insert().values(
                id=label, label_id=f"label-{i}", domain_id="old", category="test", factors_json={},
                recommended_action="approve", confidence=0.8))
    return ids


async def content_rows(db):
    async with db.connect() as conn:
        return (await conn.execute(select(LabelContent.__table__).order_by(LabelContent.id))).all()


def schema_types(conn, *, semantic=False):
    inspector = inspect(conn)
    result = {}
    for table in inspector.get_table_names():
        for column in inspector.get_columns(table):
            datatype = column["type"]
            # SQLite reflects ORM DATETIME and migration TIMESTAMP as different names
            # for the same datetime affinity. PostgreSQL must match time-zone semantics exactly.
            if semantic and conn.dialect.name == "sqlite" and isinstance(datatype, DateTime):
                type_name = "DATETIME"
            else:
                type_name = datatype.compile(dialect=conn.dialect)
            result[table, column["name"]] = type_name
    return result


async def test_postgresql_upgrade_preserves_utc_instants(db):
    if db.dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL")
    await install_legacy(db)
    await migration.migrate()
    instant = datetime(2026, 7, 1, 8, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    labels = await seed_labels(db)
    async with db.begin() as conn:
        types = await conn.run_sync(schema_types)
        await conn.execute(ApiKey.__table__.insert().values(key_hash="test", tenant_id="old", tenant_name="old"))
        for table, columns in TIMESTAMPS.items():
            model = Base.metadata.tables[table]
            for name in columns:
                assert types[table, name] == "TIMESTAMP WITH TIME ZONE"
                await conn.execute(update(model).values({name: instant}))
                assert await conn.scalar(select(model.c[name])) == instant
                # Simulate a database already upgraded by the earlier UTC-naive DDL.
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ALTER COLUMN {name} TYPE TIMESTAMP USING {name} AT TIME ZONE 'UTC'")
    await migration.migrate()
    async with db.connect() as conn:
        types = await conn.run_sync(schema_types)
        for table, columns in TIMESTAMPS.items():
            for name in columns:
                assert types[table, name] == "TIMESTAMP WITH TIME ZONE"
                assert await conn.scalar(select(Base.metadata.tables[table].c[name])) == instant
        assert len((await conn.scalars(select(LabelLog.id))).all()) == len(labels)


async def test_sqlite_upgrade_adds_timestamp_columns(db):
    if db.dialect.name != "sqlite":
        pytest.skip("requires SQLite")
    await install_legacy(db, strict=False)  # Exercise ADD COLUMN without the parent rebuild.
    await migration.migrate()
    async with db.connect() as conn:
        types = await conn.run_sync(schema_types)
    for table, columns in TIMESTAMPS.items():
        for name in columns:
            assert types[table, name] == "TIMESTAMP"


async def test_upgrade_preserves_existing_structured_content(db):
    await install_legacy(db)
    labels = await seed_labels(db)
    async with db.begin() as conn:
        for parent, kind, spans, tags, url in (
            (labels[0], "text_ner", [{"start": 0, "end": 1, "text": "α", "label": "TEST"}], [], None),
            (labels[1], "text_multilabel", [], ["a", "b"], None),
            (labels[2], "image_classification", [], [], "https://example.org/image.jpg"),
        ):
            await conn.execute(LabelContent.__table__.insert().values(
                label_log_id=parent, content_type=kind, spans_json=spans, tags_json=tags, image_url=url))
    before = await content_rows(db)
    if db.dialect.name == "sqlite":
        async with db.begin() as conn:
            assert await conn.scalar(text("PRAGMA foreign_keys")) == 1
            await conn.exec_driver_sql("CREATE TRIGGER skip_restore BEFORE INSERT ON label_content "
                                       "BEGIN SELECT RAISE(IGNORE); END")
        with pytest.raises(RuntimeError, match="Label content count changed"):
            await migration.migrate()
        assert await content_rows(db) == before  # The failed restore rolled the rebuild back.
        async with db.begin() as conn:
            await conn.exec_driver_sql("DROP TRIGGER skip_restore")
    await migration.migrate()
    assert await content_rows(db) == before
    async with db.connect() as conn:
        columns = await conn.run_sync(lambda sync: inspect(sync).get_columns("label_log"))
        assert all(col["nullable"] for col in columns if col["name"] in
                   {"category", "recommended_action", "confidence", "scored_at"})


def schema_snapshot(conn):
    if conn.dialect.name == "sqlite":
        return conn.exec_driver_sql(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name").all()
    inspector = inspect(conn)
    return {table: ([{**col, "type": col["type"].compile(dialect=conn.dialect)}
                     for col in inspector.get_columns(table)], inspector.get_indexes(table),
                    inspector.get_foreign_keys(table), inspector.get_unique_constraints(table))
            for table in inspector.get_table_names()}


async def test_second_migration_keeps_same_schema(db):
    await install_legacy(db)
    await migration.migrate()
    async with db.connect() as conn:
        first = await conn.run_sync(schema_snapshot)
    await migration.migrate()
    async with db.connect() as conn:
        second = await conn.run_sync(schema_snapshot)
    assert second == first


async def test_fresh_and_upgraded_column_types_match(db):
    await migration.migrate()
    async with db.begin() as conn:
        fresh = await conn.run_sync(lambda sync: schema_types(sync, semantic=True))
        await conn.run_sync(Base.metadata.drop_all)  # Only the private test schema/file.
    await install_legacy(db)
    await migration.migrate()
    async with db.connect() as conn:
        upgraded = await conn.run_sync(lambda sync: schema_types(sync, semantic=True))
    assert fresh == upgraded


async def test_rebuilt_parent_enforces_foreign_key_and_cascade(db):
    await install_legacy(db)
    labels = await seed_labels(db)
    await migration.migrate()
    async with db.begin() as conn:
        insert_child = LabelContent.__table__.insert().values(content_type="text_multilabel", tags_json=["ok"])
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(insert_child.values(label_log_id=uuid4()))
        for parent in labels[:2]:
            await conn.execute(insert_child.values(label_log_id=parent))
        await conn.execute(delete(LabelLog).where(LabelLog.id == labels[0]))
        assert (await conn.scalars(select(LabelContent.label_log_id))).all() == [labels[1]]


async def test_historical_unproved_email_key_is_revoked_once(db):
    await migration.migrate()
    async with db.begin() as conn:
        await conn.exec_driver_sql("ALTER TABLE api_keys DROP COLUMN email_verified_at")
        await conn.exec_driver_sql("ALTER TABLE api_keys DROP COLUMN reproof_required")
    key_id = uuid4()
    async with db.begin() as conn:
        await conn.execute(ApiKey.__table__.insert().values(
            id=key_id, key_hash="a" * 64, tenant_id="legacy-signup",
            tenant_name="Legacy", contact_email="legacy@example.test",
            is_active=True, subscription_state="trial"))
    await migration.migrate()
    await migration.migrate()
    async with db.connect() as conn:
        active, digest, reproof = (await conn.execute(select(
            ApiKey.is_active, ApiKey.key_hash, ApiKey.reproof_required).where(
            ApiKey.id == key_id))).one()
        assert active is False
        assert digest == "a" * 64
        assert reproof is True
    async with db.begin() as conn:
        await conn.execute(update(ApiKey).where(ApiKey.id == key_id).values(
            is_active=True, email_verified_at=datetime.now(timezone.utc)))
    await migration.migrate()
    async with db.connect() as conn:
        active = await conn.scalar(select(ApiKey.is_active).where(ApiKey.id == key_id))
        assert active is True
