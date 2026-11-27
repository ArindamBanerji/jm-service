"""Project import and replay contract."""

import json
from typing import Any

import pytest
from sqlalchemy import inspect, select, text

from auth import scoped_domain_id
from db import migrate as migrations
from db.models import ApiKey, ConnectorConfigRow, LabelContent, LabelLog, ProjectRequest
from label_studio import _config
from .fixtures.factory import Wire


@pytest.mark.anyio
async def test_c_schema_upgrade_retains_project_rows(db_engine, wire: Wire, monkeypatch):
    """Exercise the Wave A -> C expansion inside a disposable harness schema."""
    await wire.factory.domain()
    await wire.factory.label("before-c")
    async with db_engine.begin() as conn:
        await conn.execute(text("DROP TABLE project_request"))
        await conn.execute(text("DROP TABLE connector_config"))
        await conn.execute(text("DROP INDEX uq_revision_predecessor"))
        # SQLite cannot drop columns used by a table-level FK. Exercise its
        # partially expanded schema and the complete pre-C schema on PostgreSQL.
        if db_engine.dialect.name == "postgresql":
            for column in ("verified_by_key_id", "revision_by_key_id"):
                await conn.execute(text(f"ALTER TABLE label_log DROP COLUMN {column}"))
    monkeypatch.setattr(migrations, "engine", db_engine)
    await migrations.migrate()
    await migrations.migrate()

    def catalog(conn):
        inspector = inspect(conn)
        idx = next(row for row in inspector.get_indexes("label_log") if row["name"] == "uq_revision_predecessor")
        assert idx["unique"] and idx["column_names"] == ["domain_id", "prior_revision_id"]
        assert "prior_revision_id IS NOT NULL" in str(idx["dialect_options"][f"{conn.dialect.name}_where"])
        assert inspector.get_pk_constraint("project_request")["constrained_columns"] == [
            "project_id", "actor_key_id", "operation", "request_key"]
        assert inspector.get_pk_constraint("connector_config")["constrained_columns"] == ["tenant_id", "project_id"]
        assert {fk["constrained_columns"][0] for fk in inspector.get_foreign_keys("label_log")
                if fk["referred_table"] == "api_keys"} >= {"verified_by_key_id", "revision_by_key_id"}

    async with db_engine.connect() as conn:
        await conn.run_sync(catalog)
        assert await conn.scalar(text("SELECT count(*) FROM label_log WHERE label_id='before-c'")) == 1


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_typed_batch_import_replays_without_second_charge(wire: Wire):
    await wire.factory.domain()
    body: dict[str, Any] = {"request_key": "import-1", "items": [
        {"label_id": "ner-1", "category": "A", "text": "Sample text",
         "factors": {"quality": .8, "difficulty": .2},
         "content": {"content_type": "text_ner", "spans": [
             {"start": 0, "end": 6, "label": "A", "text": "Sample"}]}},
        {"label_id": "tags-1", "category": "B",
         "factors": {"quality": .7, "difficulty": .3},
         "content": {"content_type": "text_multilabel", "tags": ["A", "B"]}},
    ]}
    path = "/v1/projects/demo/labels/batch"
    first = await wire.request("POST", path, json=body)
    replay = await wire.request("POST", path, json=body)
    assert replay.json() == first.json()
    changed = {**body, "items": [{**body["items"][0], "label_id": "different"}]}
    await wire.request("POST", path, status=409, json=changed)
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped))).all()
        assert len(rows) == 2
        contents = (await fresh.scalars(select(LabelContent))).all()
        assert {content.content_type for content in contents} == {"text_ner", "text_multilabel"}
        receipts = (await fresh.scalars(select(ProjectRequest))).all()
        assert len(receipts) == 1
        payer = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert payer is not None and payer.labels_today == 2


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_connector_file_import_is_fenced_and_kept_read_only(wire: Wire):
    path = wire.directory / "connector.json"
    mapping = {"quality": "data.quality", "difficulty": "data.difficulty"}
    legacy = {f"{wire.factory.tenant}\0{project}": {
        "domain_id": "studio", "project_id": project, "factor_map": mapping}
        for project in ("old-a", "old-b")}
    original_bytes = json.dumps(legacy).encode()
    path.write_bytes(original_bytes)
    await wire.request("POST", "/v1/label-studio/configure",
                       headers={"X-LS-Token": "harness-ls"}, json={
                           "project_id": "new", "domain_id": "studio", "factor_map": mapping})
    assert path.read_bytes() == original_bytes
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(ConnectorConfigRow).where(
            ConnectorConfigRow.tenant_id == wire.factory.tenant))).all()
        assert {row.project_id for row in rows} == {"old-a", "old-b", "new"}
        assert await fresh.get(ConnectorConfigRow, ("__legacy_import__", "__fence__")) is not None
    legacy[f"{wire.factory.tenant}\0late"] = {
        "domain_id": "should-not-import", "project_id": "late", "factor_map": mapping}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    async with wire.factory.sessions() as restarted:
        config = await _config(restarted, "late", wire.factory.tenant)
        assert config.domain_id == "studio"
        assert await restarted.get(ConnectorConfigRow, (wire.factory.tenant, "late")) is None


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_project_sample_replay_uses_project_uuid(wire: Wire):
    initial = await wire.request("POST", "/v1/labels/medical-ner-demo-v1/sample")
    projects = (await wire.request("GET", "/v1/projects")).json()
    project = next(row for row in projects if row["public_domain_id"] == initial.json()["domain_id"])
    replay = await wire.request("POST", f"/v1/projects/{project['id']}/labels/sample")
    assert replay.json()["created"] == 0 and replay.json()["existing"] == 12


@pytest.mark.anyio
@pytest.mark.prompt_c
async def test_project_scoped_queue_detail_verify_and_bulk(wire: Wire):
    scoped = await wire.factory.domain()
    async with wire.factory.sessions() as fresh:
        from db.models import Domain
        domain = await fresh.scalar(select(Domain).where(Domain.domain_id == scoped))
        assert domain is not None
        project_id = str(domain.id)
    base = f"/v1/projects/{project_id}/labels"
    for label_id in ("one", "two"):
        await wire.request("POST", base, headers={"Idempotency-Key": f"import-{label_id}"},
                           json={"label_id": label_id, "category": "A",
                                 "factors": {"quality": .8, "difficulty": .2}})
    pending = await wire.request("GET", base + "/pending")
    assert {row["label_id"] for row in pending.json()} == {"one", "two"}
    detail = await wire.request("GET", base + "/items/one")
    assert detail.json()["label_id"] == "one"
    overview = await wire.request("GET", f"/v1/projects/{project_id}/dashboard/overview")
    assert overview.json()["domain_id"] == project_id
    guidelines = await wire.request("PUT", f"/v1/projects/{project_id}/guidelines",
                                    json={"guidelines": "Review consistently."})
    assert guidelines.json()["guidelines"] == "Review consistently."
    await wire.request("POST", base + "/verify", json={
        "label_id": "one", "actual_action": "approve", "verified_outcome": True})
    bulk = await wire.request("POST", base + "/bulk-verify", json={
        "label_ids": ["two"], "action": "approve", "outcome": False})
    assert bulk.json()["processed"] == 1
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped))).all()
        assert {row.label_id: row.verified_outcome for row in rows} == {"one": True, "two": False}
