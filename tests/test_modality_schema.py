"""MM-01 project modality schema and policy contracts on PostgreSQL."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from db import migrate as migration
from db.models import Domain
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire
from tests.harness.fixtures.pg_schema import database

pytestmark = pytest.mark.anyio


def project_payload(name: str, **axes: object) -> dict:
    return {
        "name": name,
        "public_domain_id": name,
        "factors": ["quality", "difficulty"],
        "categories": ["A", "B"],
        "actions": ["approve", "reject"],
        **axes,
    }


async def test_fresh_migration(tmp_path, monkeypatch):
    async with database(tmp_path, False, initialize=False) as db:
        monkeypatch.setattr(migration, "engine", db)
        await migration.migrate()
        async with db.begin() as connection:
            columns = {row["name"]: row for row in await connection.run_sync(
                lambda sync: inspect(sync).get_columns("domains"))}
            assert set(columns) >= {"content_type", "label_schema", "modality_enforced"}
            assert "text" in str(columns["content_type"]["default"]).lower()
            assert "single" in str(columns["label_schema"]["default"]).lower()
            assert "false" in str(columns["modality_enforced"]["default"]).lower()
            constraints = {row["name"] for row in await connection.run_sync(
                lambda sync: inspect(sync).get_check_constraints("domains"))}
            assert "ck_domains_modality_pair" in constraints
            image_type = next(row["type"] for row in await connection.run_sync(
                lambda sync: inspect(sync).get_columns("label_content"))
                              if row["name"] == "image_url")
            assert str(image_type).upper() == "TEXT"
            await connection.execute(insert(Domain).values(
                domain_id="fresh-default", tenant_id="fresh", domain_name="Fresh",
                config_json={"domain_id": "fresh-default", "domain_name": "Fresh",
                             "factors": ["quality", "difficulty"], "categories": ["A"],
                             "actions": ["approve", "reject"]}))
            defaults = (await connection.execute(select(
                Domain.content_type, Domain.label_schema, Domain.modality_enforced).where(
                Domain.domain_id == "fresh-default"))).one()
            assert defaults == ("text", "single", False)
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(insert(Domain).values(
                        domain_id="invalid-pair", tenant_id="fresh", domain_name="Invalid",
                        config_json={"domain_id": "invalid-pair", "domain_name": "Invalid",
                                     "factors": ["quality", "difficulty"], "categories": ["A"],
                                     "actions": ["approve", "reject"]},
                        content_type="image", label_schema="ner"))


async def test_repeated_migration(wire: Wire, db_engine, monkeypatch):
    monkeypatch.setattr(migration, "engine", db_engine)
    await migration.migrate()
    await migration.migrate()
    response = await wire.request("GET", "/v1/projects/capabilities")
    assert response.json()["combinations"][0] == {
        "content_type": "text", "label_schema": "single"}


async def test_existing_data_preserved(wire: Wire, db_engine, monkeypatch):
    created = (await wire.request("POST", "/v1/projects", status=201,
                                  json=project_payload("legacy-project"))).json()
    async with db_engine.begin() as connection:
        await connection.exec_driver_sql(
            "ALTER TABLE domains DROP CONSTRAINT ck_domains_modality_pair")
        await connection.exec_driver_sql("ALTER TABLE domains DROP COLUMN modality_enforced")
        await connection.exec_driver_sql("ALTER TABLE domains DROP COLUMN label_schema")
        await connection.exec_driver_sql("ALTER TABLE domains DROP COLUMN content_type")
        await connection.exec_driver_sql(
            "ALTER TABLE label_content ALTER COLUMN image_url TYPE VARCHAR(2048)")
    monkeypatch.setattr(migration, "engine", db_engine)
    await migration.migrate()
    detail = (await wire.request("GET", f"/v1/projects/{created['id']}")).json()
    assert detail["name"] == "legacy-project"
    assert (detail["content_type"], detail["label_schema"], detail["modality_enforced"]) == (
        "text", "single", False)


async def test_create_text_single_default(wire: Wire):
    created = (await wire.request("POST", "/v1/projects", status=201,
                                  json=project_payload("default-modality"))).json()
    assert (created["content_type"], created["label_schema"], created["modality_enforced"]) == (
        "text", "single", False)
    detail = (await wire.request("GET", f"/v1/projects/{created['id']}")).json()
    listed = (await wire.request("GET", "/v1/projects")).json()
    assert detail["modality_locked"] is False
    assert next(row for row in listed if row["id"] == created["id"])["content_type"] == "text"


async def test_create_image_single_explicit(wire: Wire, monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    created = (await wire.request("POST", "/v1/projects", status=201, json=project_payload(
        "image-project", content_type="image"))).json()
    assert (created["content_type"], created["label_schema"], created["modality_enforced"]) == (
        "image", "single", True)
    settings_project = (await wire.request(
        "POST", "/v1/projects", status=201, json=project_payload("settings-image"))).json()
    updated = (await wire.request(
        "PATCH", f"/v1/projects/{settings_project['id']}",
        headers={"If-Match": "1"}, json={"content_type": "image"})).json()
    assert (updated["content_type"], updated["label_schema"], updated["modality_enforced"]) == (
        "image", "single", True)
    downgrade = await wire.request(
        "PATCH", f"/v1/projects/{settings_project['id']}", status=422,
        headers={"If-Match": "2"}, json={"modality_enforced": False})
    assert downgrade.json()["detail"] == "Project modality cannot be unenforced"


async def test_create_disabled_combination(wire: Wire, monkeypatch):
    monkeypatch.delenv("DLJ_IMAGE_PROJECTS_ENABLED", raising=False)
    response = await wire.request("POST", "/v1/projects", status=422, json=project_payload(
        "disabled-image", content_type="image", label_schema="single"))
    assert response.json()["detail"] == "Project modality is not enabled"


async def test_modality_lock_after_label(wire: Wire, monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    project = (await wire.request("POST", "/v1/projects", status=201,
                                  json=project_payload("locked-modality"))).json()
    await wire.request("POST", f"/v1/projects/{project['id']}/labels/batch", json={
        "request_key": "lock-project", "items": [{
            "label_id": "locked-label", "category": "A", "annotator_id": "ann",
            "factors": {"quality": .8, "difficulty": .2}, "text": "Example",
        }],
    })
    response = await wire.request(
        "PATCH", f"/v1/projects/{project['id']}", status=409,
        headers={"If-Match": "1"}, json={"content_type": "image"})
    assert response.json()["detail"] == "Project modality is locked after the first label"


async def test_invalid_pair_rejected(wire: Wire, monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    monkeypatch.setenv("DLJ_NER_PROJECTS_ENABLED", "true")
    response = await wire.request("POST", "/v1/projects", status=422, json=project_payload(
        "image-ner", content_type="image", label_schema="ner"))
    assert response.json()["detail"] == "Invalid project modality"
    null_axis = await wire.request("POST", "/v1/projects", status=422, json=project_payload(
        "null-axis", content_type=None))
    assert null_axis.json()["detail"] == "Invalid project modality"
    unknown = await wire.request("POST", "/v1/projects", status=422, json=project_payload(
        "unknown-axis", content_type="audio", label_schema="single"))
    assert unknown.json()["detail"] == "Unsupported content type and label schema"


async def test_capabilities_endpoint(wire: Wire, monkeypatch):
    for name in ("DLJ_IMAGE_PROJECTS_ENABLED", "DLJ_MULTILABEL_PROJECTS_ENABLED",
                 "DLJ_NER_PROJECTS_ENABLED", "DLJ_INLINE_IMAGES_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    await wire.request("GET", "/v1/projects/capabilities", status=401, omit_api_key=True)
    initial = (await wire.request("GET", "/v1/projects/capabilities")).json()
    assert initial == {"combinations": [{
        "content_type": "text", "label_schema": "single"}],
        "inline_images_enabled": False}
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    monkeypatch.setenv("DLJ_INLINE_IMAGES_ENABLED", "true")
    enabled = (await wire.request("GET", "/v1/projects/capabilities")).json()
    assert {"content_type": "image", "label_schema": "single"} in enabled["combinations"]
    assert enabled["inline_images_enabled"] is True
