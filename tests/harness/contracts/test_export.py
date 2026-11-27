"""Prompt D project export contracts."""
from datetime import datetime, timedelta, timezone
import csv
import io
import json
from uuid import UUID

import pytest
from sqlalchemy import insert, select, update

import labeling_router
from db.models import Domain, LabelLog, ProjectExportSlot, WebhookEvent
from ..fixtures.factory import Wire

pytestmark = [pytest.mark.anyio, pytest.mark.prompt_d]


async def project_with_labels(wire: Wire, count: int = 12) -> str:
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Export", "public_domain_id": "demo",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
        "actions": ["approve", "reject"],
    })).json()["id"]
    for index in range(count):
        await wire.factory.label(f"export-{index}")
    return project


async def test_jsonl_csv_filters_slots_and_empty_export(wire: Wire):
    project = await project_with_labels(wire)
    await wire.request("POST", f"/v1/projects/{project}/labels", json={
        "label_id": "=SUM(1,1)", "category": "B", "annotator_id": "export-ann",
        "factors": {"quality": .8, "difficulty": .2}, "text": "quoted, export\ntext",
    }, headers={"Idempotency-Key": "export-csv-label"})
    await wire.request("POST", f"/v1/projects/{project}/labels/verify", json={
        "label_id": "export-0", "actual_action": "approve", "verified_outcome": True})
    response = await wire.request("GET", f"/v1/projects/{project}/export?format=jsonl&review_status=verified")
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert len(rows) == 1
    assert rows[0]["root_label_id"] == rows[0]["current_label_id"] == "export-0"
    assert rows[0]["verified_outcome"] is True
    async with wire.factory.sessions() as fresh:
        event = await fresh.scalar(select(WebhookEvent).where(
            WebhookEvent.event_type == "label.verified"))
        assert event is not None
        envelope = json.loads(event.canonical_body)
        assert set(envelope) == {
            "event_id", "event_type", "project_id", "occurred_at", "schema_version", "data"}
        assert envelope["project_id"] == project and envelope["schema_version"] == 1
    csv_response = await wire.request(
        "GET", f"/v1/projects/{project}/export?format=csv&category=B&annotator=export-ann")
    csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(csv_rows) == 1
    assert csv_rows[0]["root_label_id"] == "'=SUM(1,1)"
    assert csv_rows[0]["text"] == "quoted, export\ntext"
    empty_response = await wire.request(
        "GET", f"/v1/projects/{project}/export?format=csv&category=A&annotator=missing")
    assert list(csv.DictReader(io.StringIO(empty_response.text))) == []
    docbin = await wire.client.get(f"/v1/projects/{project}/export?format=docbin&review_status=verified")
    assert docbin.status_code in {200, 501}
    if docbin.status_code == 200:
        assert docbin.headers["content-type"].startswith("application/octet-stream")
    async with wire.factory.sessions() as fresh:
        slots = (await fresh.scalars(select(ProjectExportSlot).where(
            ProjectExportSlot.project_id == UUID(project)))).all()
        assert len(slots) == 2 and all(slot.lease_token is None and slot.expires_at is None for slot in slots)


async def test_export_role_deadline_and_slot_exhaustion(wire: Wire, monkeypatch):
    project = await project_with_labels(wire, 1)
    reviewer = await wire.factory.user("export-reviewer")
    annotator = await wire.factory.user("export-annotator")
    await wire.request("POST", f"/v1/projects/{project}/members", status=201,
                       json={"member_tenant_id": "export-reviewer", "role": "reviewer"})
    await wire.request("POST", f"/v1/projects/{project}/members", status=201,
                       json={"member_tenant_id": "export-annotator", "role": "annotator"})
    await wire.request("GET", f"/v1/projects/{project}/export", headers={"X-Api-Key": reviewer})
    await wire.request("GET", f"/v1/projects/{project}/export", status=403,
                       headers={"X-Api-Key": annotator})
    monkeypatch.setattr(labeling_router, "EXPORT_TIMEOUT_SECONDS", 0.0)
    await wire.request("GET", f"/v1/projects/{project}/export", status=504)
    monkeypatch.setattr(labeling_router, "EXPORT_TIMEOUT_SECONDS", 300.0)
    monkeypatch.setattr(labeling_router, "EXPORT_BROWSER_MAX_BYTES", 1)
    await wire.request("GET", f"/v1/projects/{project}/export?browser_fallback=true", status=413)
    await wire.request("GET", f"/v1/projects/{project}/export")
    now = datetime.now(timezone.utc)
    async with wire.factory.sessions.begin() as session:
        domain = await session.get(Domain, UUID(project))
        assert domain is not None
        slots = (await session.scalars(select(ProjectExportSlot).where(
            ProjectExportSlot.project_id == domain.id))).all()
        assert len(slots) == 2
        for slot in slots:
            slot.lease_token = UUID(int=slot.slot)
            slot.expires_at = now + timedelta(minutes=5)
    await wire.request("GET", f"/v1/projects/{project}/export", status=429)


async def test_export_snapshot_across_keyset_pages_and_byte_cap(wire: Wire, db_engine, monkeypatch):
    project = await project_with_labels(wire, 0)
    async with wire.factory.sessions.begin() as session:
        domain = await session.get(Domain, UUID(project))
        assert domain is not None
        await session.execute(insert(LabelLog), [
            {"id": UUID(int=i), "label_id": f"p{i}", "domain_id": domain.domain_id,
             "tenant_id": domain.tenant_id, "category": "A", "text": "é", "factors_json": {}}
            for i in range(1, 502)])
    rows = labeling_router._export_rows

    async def interleave(*args, **kwargs):
        async for item in rows(*args, **kwargs):
            if item["current_label_id"] == "p500" and db_engine.dialect.name == "postgresql":
                async with wire.factory.sessions.begin() as writer:
                    await writer.execute(update(LabelLog).where(LabelLog.id == UUID(int=501))
                                         .values(text="committed after snapshot"))
            yield item

    monkeypatch.setattr(labeling_router, "_export_rows", interleave)
    path = f"/v1/projects/{project}/export"
    response = await wire.request("GET", path)
    records = [json.loads(line) for line in response.text.splitlines()]
    assert [row["current_label_id"] for row in records] == [f"p{i}" for i in range(1, 502)]
    assert records[-1]["text"] == "é"
    monkeypatch.setattr(labeling_router, "_export_rows", rows)
    monkeypatch.setattr(labeling_router, "EXPORT_MAX_TEXT_BYTES", 1001)
    await wire.request("GET", path, status=413)
    monkeypatch.setattr(labeling_router, "EXPORT_MAX_TEXT_BYTES", 16 * 1024 * 1024)
    monkeypatch.setattr(labeling_router, "EXPORT_MAX_DOCUMENTS", 500)
    await wire.request("GET", path, status=413)
