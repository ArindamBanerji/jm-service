"""Notes and annotation-guideline contracts over the PostgreSQL harness."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from db.models import ApiKey, Domain, LabelLog, ProjectMember
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio


async def _project(wire: Wire, name: str) -> dict:
    return (await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name,
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
        "actions": ["approve", "reject"],
    })).json()


async def _label(wire: Wire, project: dict, label_id: str = "note-label",
                 notes: str | None = None) -> None:
    item = {"label_id": label_id, "category": "A", "annotator_id": "annotator-1",
            "factors": {"quality": .8, "difficulty": .2}, "text": "Example label"}
    if notes is not None:
        item["notes"] = notes
    await wire.request("POST", f"/v1/projects/{project['id']}/labels/batch", json={
        "request_key": f"import-{label_id}", "items": [item],
    })


async def _verify(wire: Wire, project: dict, label_id: str = "note-label",
                  notes: str | None = None, status: int = 200):
    body = {"label_id": label_id, "actual_action": "approve", "verified_outcome": True}
    if notes is not None:
        body["notes"] = notes
    return await wire.request("POST", f"/v1/projects/{project['id']}/labels/verify",
                              status=status, json=body)


async def test_verify_with_note(wire: Wire):
    project = await _project(wire, "verify-note")
    await _label(wire, project)
    await _verify(wire, project, notes="Check the source before reuse.")
    detail = (await wire.request(
        "GET", f"/v1/projects/{project['id']}/labels/note-label")).json()
    assert detail["review_notes"] == "Check the source before reuse."


async def test_note_in_label_detail(wire: Wire):
    project = await _project(wire, "detail-note")
    await _label(wire, project, notes="Annotator saw an ambiguous headline.")
    detail = (await wire.request(
        "GET", f"/v1/projects/{project['id']}/labels/note-label")).json()
    assert detail["notes"] == "Annotator saw an ambiguous headline."
    assert detail["review_notes"] is None


async def test_note_in_export(wire: Wire):
    project = await _project(wire, "export-note")
    await _label(wire, project, notes="source note")
    await _verify(wire, project, notes="review note")
    response = await wire.request("GET", f"/v1/projects/{project['id']}/export?format=jsonl")
    row = json.loads(response.text.strip())
    assert row["notes"] == "source note"
    assert row["review_notes"] == "review note"


async def test_note_max_length(wire: Wire):
    project = await _project(wire, "long-note")
    await _label(wire, project)
    await _verify(wire, project, notes="x" * 501, status=422)


async def test_note_optional(wire: Wire):
    project = await _project(wire, "optional-note")
    await _label(wire, project)
    await _verify(wire, project)
    detail = (await wire.request(
        "GET", f"/v1/projects/{project['id']}/labels/note-label")).json()
    assert detail["notes"] is None and detail["review_notes"] is None


async def test_review_note_separate(wire: Wire):
    project = await _project(wire, "separate-notes")
    await _label(wire, project, notes="annotator note")
    await _verify(wire, project, notes="reviewer note")
    async with wire.factory.sessions() as session:
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        row = await session.scalar(select(LabelLog).where(
            LabelLog.domain_id == domain.domain_id, LabelLog.label_id == "note-label"))
        assert row is not None
        assert (row.notes, row.review_notes) == ("annotator note", "reviewer note")


async def test_set_guidelines(wire: Wire):
    project = await _project(wire, "set-guidelines")
    await wire.request("PATCH", f"/v1/projects/{project['id']}",
                       headers={"If-Match": "1"}, json={"guidelines": "# Review carefully"})
    detail = (await wire.request("GET", f"/v1/projects/{project['id']}")).json()
    assert detail["guidelines"] == "# Review carefully"


async def test_guidelines_in_project_detail(wire: Wire):
    project = await _project(wire, "detail-guidelines")
    await wire.request("PATCH", f"/v1/projects/{project['id']}",
                       headers={"If-Match": "1"}, json={"guidelines": "- One\n- Two"})
    detail = (await wire.request("GET", f"/v1/projects/{project['id']}")).json()
    assert detail["guidelines"] == "- One\n- Two"
    assert detail["guidelines_updated_at"] is not None


async def test_guidelines_max_length(wire: Wire):
    project = await _project(wire, "long-guidelines")
    await wire.request("PATCH", f"/v1/projects/{project['id']}", status=422,
                       headers={"If-Match": "1"}, json={"guidelines": "x" * (10 * 1024 + 1)})


async def test_guidelines_requires_admin(wire: Wire):
    project = await _project(wire, "role-guidelines")
    reviewer_key = await wire.factory.user("guideline-reviewer")
    owner_digest = hashlib.sha256(wire.client.headers["x-api-key"].encode()).hexdigest()
    async with wire.factory.sessions.begin() as session:
        owner = await session.scalar(select(ApiKey).where(ApiKey.key_hash == owner_digest))
        reviewer = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(reviewer_key.encode()).hexdigest()))
        assert owner is not None and reviewer is not None
        session.add(ProjectMember(project_id=UUID(project["id"]),
            member_tenant_id=reviewer.tenant_id, role="reviewer", active=True,
            granted_by_key_id=owner.id, created_at=datetime.now(timezone.utc)))
    await wire.request("PATCH", f"/v1/projects/{project['id']}", status=403,
        headers={"If-Match": "1", "X-Api-Key": reviewer_key},
        json={"guidelines": "Reviewer must not edit"})


async def test_guidelines_markdown(wire: Wire):
    project = await _project(wire, "markdown-guidelines")
    markdown = "# Heading\n**bold** & <script>literal</script>\n```py\nprint('safe')\n```"
    await wire.request("PATCH", f"/v1/projects/{project['id']}",
                       headers={"If-Match": "1"}, json={"guidelines": markdown})
    detail = (await wire.request("GET", f"/v1/projects/{project['id']}")).json()
    assert detail["guidelines"] == markdown


async def test_guidelines_updated_at(wire: Wire):
    project = await _project(wire, "timestamp-guidelines")
    await wire.request("PATCH", f"/v1/projects/{project['id']}",
                       headers={"If-Match": "1"}, json={"guidelines": "first"})
    first = (await wire.request("GET", f"/v1/projects/{project['id']}")).json()
    await wire.request("PATCH", f"/v1/projects/{project['id']}",
                       headers={"If-Match": "2"}, json={"guidelines": "second"})
    second = (await wire.request("GET", f"/v1/projects/{project['id']}")).json()
    assert datetime.fromisoformat(second["guidelines_updated_at"]) >= datetime.fromisoformat(
        first["guidelines_updated_at"])
    assert second["guidelines"] == "second"
