"""Project administration contracts for Prompt A."""

import pytest
import hashlib
import re
from sqlalchemy import select

import projects_router
from db.models import ApiKey, Domain, ProjectMember
from .fixtures.factory import Wire


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_project_create_list_archive_and_version(wire: Wire):
    created = await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Review", "public_domain_id": "review",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
    })
    project_id = created.json()["id"]
    await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "review", "label_id": "before-archive", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    listed = await wire.request("GET", "/v1/projects")
    assert any(row["id"] == project_id for row in listed.json())
    archived = await wire.request("PUT", f"/v1/projects/{project_id}/settings", json={
        "settings_version": 1, "status": "archived", "description": "Closed",
    })
    assert archived.json()["settings_version"] == 2
    await wire.request("POST", "/v1/labels/ingest", status=409, json={
        "domain_id": "review", "label_id": "after-archive", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    detail = await wire.request("GET", "/v1/labels/review/items/before-archive")
    assert detail.json()["label_id"] == "before-archive"
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=409, json={
        "settings_version": 1, "status": "active",
    })
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", json={
        "settings_version": 2, "status": "active",
    })
    await wire.request("POST", "/v1/labels/ingest", json={
        "domain_id": "review", "label_id": "after-reactivate", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    async with wire.factory.sessions() as fresh:
        row = await fresh.scalar(select(Domain).where(Domain.public_domain_id == "review"))
        assert row is not None and row.status == "active"
        member = await fresh.scalar(select(ProjectMember).where(ProjectMember.project_id == row.id))
        assert member is not None and member.role == "admin"


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_project_member_cannot_edit_settings(wire: Wire):
    created = await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Review", "public_domain_id": "review",
        "factors": ["quality"], "categories": ["A", "B"],
    })
    project_id = created.json()["id"]
    other_key = await wire.factory.user("other-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201, json={
        "member_tenant_id": "other-tenant", "role": "reviewer",
    })
    listed = await wire.request("GET", "/v1/projects", headers={"X-Api-Key": other_key})
    assert len(listed.json()) == 1
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=403,
                       headers={"X-Api-Key": other_key}, json={
                           "settings_version": 1, "status": "archived",
                       })


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_project_invite_is_mailbox_bound_and_single_use(wire: Wire, monkeypatch):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Review", "public_domain_id": "review",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    member_key = await wire.factory.user("member-tenant")
    wrong_key = await wire.factory.user("wrong-tenant")
    async with wire.factory.sessions.begin() as session:
        member = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(member_key.encode()).hexdigest()))
        wrong = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(wrong_key.encode()).hexdigest()))
        assert member is not None and wrong is not None
        member.contact_email = "member@example.test"
        wrong.contact_email = "wrong@example.test"
    sent: list[str] = []

    async def capture(address: str, subject: str, html: str) -> bool:
        assert address == "member@example.test"
        sent.append(html)
        return True

    monkeypatch.setattr(projects_router, "send_email", capture)
    invite = (await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                                 json={"email": "MEMBER@example.test", "role": "annotator"})).json()
    assert invite["mail_status"] == "sent"
    token = re.search(r"Invitation code: ([a-f0-9]{64})", sent[0])
    assert token is not None
    path = f"/v1/projects/{project}/invites/{invite['id']}/accept"
    await wire.request("POST", path, status=403, headers={"X-Api-Key": wrong_key},
                       json={"token": token.group(1)})
    accepted = await wire.request("POST", path, headers={"X-Api-Key": member_key},
                                  json={"token": token.group(1)})
    assert accepted.json()["role"] == "annotator"
    await wire.request("POST", path, status=403, headers={"X-Api-Key": member_key},
                       json={"token": token.group(1)})
