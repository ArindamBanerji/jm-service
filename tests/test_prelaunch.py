"""Wire, configuration, and SDK regressions from the launch review."""
import asyncio
import base64
import hashlib
import hmac
import json
from uuid import UUID

import pytest
from sqlalchemy import event, select

import billing
import jm_service
import media_intake
from backend.static import dlj_client
from db.models import WebhookEvent
from tests.harness.browser.test_browser_contracts import origin
from tests.harness.conftest import anyio_backend, db_engine, factory, wire
from tests.harness.fixtures.factory import Wire


@pytest.mark.anyio
async def test_invalid_auth_dto_omits_private_input(wire: Wire):
    response = await wire.request("POST", "/v1/auth/register", status=422, omit_api_key=True,
                                  json={"email": "private-field-value"})
    error, = response.json()["detail"]
    assert error["loc"] == ["body", "email"]
    assert "private-field-value" not in response.text and "input" not in error
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_public_rate_window_and_cors(wire: Wire):
    allowed = {"Origin": "https://dlj.dakshineshwari.net"}
    first = await wire.request("GET", "/terms", headers=allowed)
    second = await wire.request("GET", "/terms", headers=allowed)
    assert int(second.headers["x-ratelimit-remaining"]) == int(first.headers["x-ratelimit-remaining"]) - 1
    assert second.headers["access-control-allow-origin"] == allowed["Origin"]
    assert "X-RateLimit-Reset" in second.headers["access-control-expose-headers"]
    denied = await wire.request("OPTIONS", "/terms", status=400, headers={
        "Origin": "https://unrelated.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in denied.headers
    # A valid decorated route reports its own policy as well.
    limited = await wire.request("POST", "/v1/auth/register", status=202, omit_api_key=True,
                                 json={"email": "window@example.test"})
    assert int(limited.headers["x-ratelimit-limit"]) == 5


@pytest.mark.anyio
async def test_project_list_pages_every_accessible_project(wire: Wire):
    expected = []
    for alias in ("page-a", "page-b", "page-c"):
        row = await wire.request("POST", "/v1/projects", status=201, json={
            "public_domain_id": alias, "name": alias, "categories": ["A"],
            "factors": ["quality", "difficulty"], "actions": ["approve", "reject"]})
        expected.append(row.json()["id"])
    first = await wire.request("GET", "/v1/projects?limit=2")
    assert "no-store" in first.headers["cache-control"]
    assert [row["id"] for row in first.json()] == expected[:2]
    assert first.headers["x-next-offset"] == "2"
    last = await wire.request("GET", "/v1/projects?limit=2&offset=2")
    assert [row["id"] for row in last.json()] == expected[2:] and "x-next-offset" not in last.headers
    await wire.request("GET", "/v1/projects?limit=201", status=422)


@pytest.mark.anyio
async def test_media_read_deadline_returns_permit(wire: Wire, monkeypatch):
    monkeypatch.setattr(media_intake, "INTAKE_SECONDS", 0.05)
    async def stalled():
        yield b"{"
        await asyncio.Event().wait()
    for _ in range(3):
        result = await wire.request("POST", "/v1/labels/ingest", content=stalled(), status=408)
        assert result.json()["detail"] == "Media upload timed out"


@pytest.mark.anyio
async def test_batch_uses_one_scoped_evidence_read(wire: Wire, db_engine):
    project = (await wire.request("POST", "/v1/projects", status=201, json={
        "public_domain_id": "evidence", "name": "Evidence", "categories": ["A"],
        "factors": ["quality", "difficulty"], "actions": ["approve", "reject"],
    })).json()
    path = "/v1/projects/" + project["id"] + "/labels"
    items = [{"label_id": str(i), "category": "A", "factors": {"quality": .8, "difficulty": .2}}
             for i in range(5)]
    await wire.request("POST", path + "/batch", json={"request_key": "seed", "items": items[:1]})
    await wire.request("POST", path + "/verify",
                       json={"label_id": "0", "actual_action": "approve", "verified_outcome": False})
    reads = []
    payer_locks = []

    def count_evidence(conn, cursor, statement, parameters, context, executemany):
        if "WITH RECURSIVE verified_lineage" in statement:
            reads.append(statement)
        if "FROM api_keys" in statement and "FOR UPDATE" in statement:
            payer_locks.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", count_evidence)
    try:
        result = await wire.request("POST", path + "/batch", json={"request_key": "batch", "items": items[1:]})
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", count_evidence)
    assert len(reads) == 1 and result.json()["batch_size"] == 4
    assert len(payer_locks) == 1
    for row in result.json()["results"]:
        assert row["tier_status"]["verified_count"] == 1
        assert row["tier_status"]["accuracy"] == 0


def test_signature_rotation_accepts_matching_digest():
    body = b'{"event_id":"test"}'
    digest = hmac.new(b"secret", b"123:" + body, hashlib.sha256).hexdigest()
    for signatures in (f"h1={digest};h1={'0'*64}", f"h1={'0'*64};h1={digest}"):
        assert billing.verify_paddle_signature(body, "ts=123;" + signatures, "secret")
        assert not billing.verify_paddle_signature(body + b" ", "ts=123;" + signatures, "secret")
    assert not billing.verify_paddle_signature(body, "ts=123;h1=é", "secret")


def test_production_config_names_missing_setting(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.delenv("PADDLE_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="PADDLE_WEBHOOK_SECRET"):
        jm_service.validate_production_config()


def test_sdk_chunk_size_accounts_for_wire_and_media(monkeypatch):
    monkeypatch.setattr(dlj_client, "MAX_IMAGE_BYTES", 5)
    item = {"item_media_url": "data:image/png;base64,YWJj"}
    assert list(dlj_client._upload_chunks([item, item], 100)) == [[item], [item]]
    monkeypatch.setattr(dlj_client, "MAX_JSON_BYTES", 145)
    item = {"text": "雪" * 5}
    assert list(dlj_client._upload_chunks([item, item], 100)) == [[item], [item]]
    with pytest.raises(ValueError, match="One item"):
        list(dlj_client._upload_chunks([{"text": "雪" * 100}], 100))


@pytest.mark.anyio
async def test_image_client_export_and_event_reference(wire: Wire, origin, monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    monkeypatch.setenv("DLJ_INLINE_IMAGES_ENABLED", "true")
    image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(120_000)).decode()
    key = wire.client.headers["x-api-key"]

    def use_client() -> str:
        client = dlj_client.DLJClient(origin, key)
        try:
            project = client.create_project("SDK images", ["A"], ["quality", "difficulty"], ["approve", "reject"],
                                            content_type="image", label_schema="single")
            pid = project["id"]
            result = client.upload(pid, [{"label_id": "bird 1", "category": "A", "item_media_url": image,
                                          "factors": {"quality": .2, "difficulty": .8}}])
            assert result["committed"] == 1
            client.verify(pid, "bird 1", "approve", {"verified_outcome": True})
            row, = client.export(pid, format="csv", filters={"format": "jsonl"})
            assert isinstance(row, dict) and row["image_url"] == image
            return pid
        finally:
            client.session.close()

    pid = await asyncio.to_thread(use_client)
    async with wire.factory.sessions() as session:
        body = await session.scalar(select(WebhookEvent.canonical_body).where(WebhookEvent.project_id == UUID(pid)))
    assert body and "base64" not in body
    data = json.loads(body)["data"]
    assert data["media_kind"] == "image" and data["item_detail_path"].endswith("/items/bird%201")
    response = await wire.request("GET", data["item_detail_path"])
    assert response.json()["content"]["image_url"] == image
