"""Project administration contracts for Prompt A."""

import pytest
import hashlib
import re
from uuid import UUID
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
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
    })
    project_id = created.json()["id"]
    other_key = await wire.factory.user("other-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201, json={
        "member_tenant_id": "other-tenant", "role": "reviewer",
    })
    listed = await wire.request("GET", "/v1/projects", headers={"X-Api-Key": other_key})
    assert len(listed.json()) == 1
    await wire.request("POST", "/v1/labels/ingest", headers={"X-Api-Key": other_key}, json={
        "domain_id": "review", "label_id": "member-score", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    detail = await wire.request("GET", "/v1/labels/review/items/member-score",
                                headers={"X-Api-Key": other_key})
    assert detail.json()["label_id"] == "member-score"
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=403,
                       headers={"X-Api-Key": other_key}, json={
                           "settings_version": 1, "status": "archived",
                       })


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_only_owner_can_archive_or_reactivate(wire: Wire):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Review", "public_domain_id": "review",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    admin_key = await wire.factory.user("admin-tenant")
    await wire.request("POST", f"/v1/projects/{project_id}/members", status=201, json={
        "member_tenant_id": "admin-tenant", "role": "admin",
    })
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=403,
                       headers={"X-Api-Key": admin_key}, json={
                           "settings_version": 1, "status": "archived",
                       })
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=200, json={
        "settings_version": 1, "status": "archived",
    })
    await wire.request("PUT", f"/v1/projects/{project_id}/settings", status=403,
                       headers={"X-Api-Key": admin_key}, json={
                           "settings_version": 2, "status": "active",
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


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_invite_rechecks_issuer_authority(wire: Wire, monkeypatch):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Review", "public_domain_id": "review",
        "factors": ["quality"], "categories": ["A"],
    })).json()["id"]
    admin_key = await wire.factory.user("admin-tenant")
    recipient_key = await wire.factory.user("recipient-tenant")
    async with wire.factory.sessions.begin() as session:
        recipient = await session.scalar(select(ApiKey).where(
            ApiKey.key_hash == hashlib.sha256(recipient_key.encode()).hexdigest()))
        assert recipient is not None
        recipient.contact_email = "recipient@example.test"
    await wire.request("POST", f"/v1/projects/{project}/members", status=201, json={
        "member_tenant_id": "admin-tenant", "role": "admin",
    })
    sent: list[str] = []

    async def capture(address: str, subject: str, html: str) -> bool:
        sent.append(html)
        return True

    monkeypatch.setattr(projects_router, "send_email", capture)
    invite = (await wire.request("POST", f"/v1/projects/{project}/invites", status=201,
                                 headers={"X-Api-Key": admin_key}, json={
                                     "email": "recipient@example.test", "role": "reviewer",
                                 })).json()
    token = re.search(r"Invitation code: ([a-f0-9]{64})", sent[0])
    assert token is not None
    await wire.request("POST", f"/v1/projects/{project}/members", status=201, json={
        "member_tenant_id": "admin-tenant", "role": "reviewer",
    })
    await wire.request("POST", f"/v1/projects/{project}/invites/{invite['id']}/accept",
                       status=403, headers={"X-Api-Key": recipient_key},
                       json={"token": token.group(1)})


@pytest.mark.prompt_a
@pytest.mark.anyio
@pytest.mark.parametrize("role", ["owner", "admin", "reviewer", "annotator"])
@pytest.mark.parametrize("payer_state", ["trial", "active", "cancelled"])
async def test_roles_by_payer_access_matrix(wire: Wire, role: str, payer_state: str):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Matrix", "public_domain_id": "matrix",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
    })).json()["id"]
    for label_id in ("verify-me", "bulk-me"):
        await wire.request("POST", "/v1/labels/ingest", json={
            "domain_id": "matrix", "label_id": label_id, "category": "A",
            "factors": {"quality": .8, "difficulty": .2},
        })
    headers = {}
    if role != "owner":
        member_key = await wire.factory.user(f"{role}-tenant")
        await wire.request("POST", f"/v1/projects/{project_id}/members", status=201,
                           json={"member_tenant_id": f"{role}-tenant", "role": role})
        headers = {"X-Api-Key": member_key}
    async with wire.factory.sessions.begin() as session:
        owner = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert owner is not None
        owner.subscription_state = payer_state
        owner.tier = "professional" if payer_state != "trial" else "trial"
        owner.cancelled_at = owner.created_at if payer_state == "cancelled" else None
    member_write = payer_state != "cancelled" or role == "owner"
    score = await wire.client.post("/v1/labels/ingest", headers=headers, json={
        "domain_id": "matrix", "label_id": f"score-{role}-{payer_state}", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    assert score.status_code == (200 if member_write else 403), score.text
    verify = await wire.client.post("/v1/labels/verify", headers=headers, json={
        "domain_id": "matrix", "label_id": "verify-me",
        "actual_action": "approve", "verified_outcome": True,
    })
    can_review = member_write and role != "annotator"
    assert verify.status_code == (200 if can_review else 403), verify.text
    bulk = await wire.client.post("/v1/labels/matrix/bulk-verify", headers=headers, json={
        "label_ids": ["bulk-me"], "action": "approve", "outcome": True,
    })
    assert bulk.status_code == (200 if can_review else 403), bulk.text
    settings = await wire.client.put(f"/v1/projects/{project_id}/settings", headers=headers,
                                     json={"settings_version": 1, "status": "active"})
    can_admin = role in {"owner", "admin"} and member_write
    assert settings.status_code == (200 if can_admin else 403), settings.text
    read = await wire.client.get("/v1/labels/matrix/pending", headers=headers)
    assert read.status_code == 200, read.text
    async with wire.factory.sessions() as fresh:
        project = await fresh.get(Domain, UUID(project_id))
        assert project is not None and project.tenant_id == wire.factory.tenant
        if role != "owner" and score.status_code == 200:
            payer = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
            assert payer is not None and payer.labels_today >= 3
