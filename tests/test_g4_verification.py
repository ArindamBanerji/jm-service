"""Regression contracts for media admission, modality policy, diagnostics and replay."""
import asyncio
import base64
import logging
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

import jm_service
import media_intake
import modality
from db.models import ApiKey, LabelContent, LabelLog, ProjectRequest
from tests.harness.conftest import db_engine, factory, wire
from tests.harness.fixtures.factory import Wire
from tests.test_modality_ingest import PNG, URL, anyio_backend, batch, detail, enable_images, frame, inline, project, submit

pytestmark = pytest.mark.anyio


async def test_permit_after_downstream_exit(monkeypatch):
    # Occupy one slot, so a single leak suffices to reject the next request.
    monkeypatch.setattr(media_intake, "MIB", 4)
    entered = asyncio.Event()
    mode = "success"

    async def downstream(scope, receive, send):
        assert (await receive())["body"] == b"payload"
        if mode == "cancel":
            entered.set()
            await asyncio.Event().wait()
        if mode == "scoring":
            raise ValueError("synthetic scoring failure")
        if mode == "database":
            raise SQLAlchemyError("synthetic transaction failure")
        await Response(status_code=422 if mode == "validation" else 204)(scope, receive, send)

    intake = media_intake.MediaIntake(downstream)
    async with intake.slots, httpx.AsyncClient(transport=httpx.ASGITransport(app=intake),
                                               base_url="http://fixture") as client:
        async def send_one():
            return await client.post("/v1/labels/ingest", content=b"payload")

        for mode, error in (("scoring", ValueError), ("database", SQLAlchemyError)):
            with pytest.raises(error, match="synthetic"):
                await send_one()
        mode = "validation"
        assert (await send_one()).status_code == 422
        mode = "cancel"
        pending = asyncio.create_task(send_one())
        try:
            await asyncio.wait_for(entered.wait(), 2)
        finally:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        mode = "success"
        assert (await send_one()).status_code == 204


async def test_prediction_correction_has_intake_policy(wire: Wire):
    # The same dispatch supplies the encoding, byte limit and admission policy.
    route = "/v1/projects/{domain_id}/predictions/{prediction_id}/review"
    assert "post" in jm_service.app.openapi()["paths"][route]
    path = route.format(domain_id=UUID(int=1), prediction_id=UUID(int=2))
    assert any(layer.cls is media_intake.MediaIntake for layer in jm_service.app.user_middleware)
    response = await wire.client.post(path, json={}, headers={"Content-Encoding": "gzip"})
    assert response.status_code == 415
    assert response.json()["detail"] == "Unsupported request content encoding"


async def test_external_reference_contract():
    signed = "?X-Amz-Signature=example%2Bvalue&x=1&x=2"
    for suffix in ("JpG", "JPEG", "pNg", "WeBp", "GIF"):
        url = "https://pictures.example.test/file." + suffix + signed
        assert modality.validate_image_url(url, strict=True) == url
    prefix = "https://pictures.example.test/"
    boundary = prefix + "a" * (2048 - len(prefix) - 4) + ".png"
    assert modality.validate_image_url(boundary, True) == boundary
    for invalid in ("", boundary + "x", "ftp://example.test/a.jpg", "file:///image.png",
                    "javascript:void(0)", inline(PNG), prefix + "a.html", prefix + "a.svg",
                    "https://user:example@example.test/a.jpg", prefix + "a\x01.png"):
        with pytest.raises(HTTPException) as rejected:
            modality.validate_image_url(invalid, True)
        assert (rejected.value.status_code, rejected.value.detail) == (422, "Invalid image HTTPS URL")


async def test_inline_reference_signatures():
    formats = {"jpeg": b"\xff\xd8", "png": PNG, "webp": b"RIFF\x04\0\0\0WEBP",
               "gif": b"GIF89a"}
    for mime, signature in formats.items():
        raw = signature + bytes(50_001)  # cross the 65,536-character decoder block
        uri = "data:image/" + mime + ";base64," + base64.b64encode(raw).decode()
        assert modality.validate_data_uri(uri) == (uri, len(raw))
    for uri in ("data:image/png;charset=utf-8;base64,AAAA", inline(PNG)[:25] + "\n" + inline(PNG)[25:],
                "data:image/webp;base64," + base64.b64encode(b"RIFF1234FAKE").decode()):
        with pytest.raises(HTTPException) as rejected:
            modality.validate_data_uri(uri)
        assert (rejected.value.status_code, rejected.value.detail) == (422, "Invalid embedded image")


async def test_image_reference_requires_valid_hostname():
    single_dot = "https://pictures.example.test./frame.png"
    assert modality.validate_image_url(single_dot, True) == single_dot
    with pytest.raises(HTTPException) as rejected:
        modality.validate_image_url("https://pictures.example.test../frame.png", True)
    assert (rejected.value.status_code, rejected.value.detail) == (422, "Invalid image HTTPS URL")


@pytest.mark.parametrize("field,value", [
    ("tags", ["A"]), ("spans", [{"start": 0, "end": 1, "label": "A", "text": "x"}]),
])
async def test_text_single_rejects_incompatible_annotation(wire: Wire, field, value):
    path = await project(wire, "text")
    response = await wire.client.post(path + "/labels/batch", json=batch(frame(text="x", **{field: value})))
    async with wire.factory.sessions() as session:
        count = await session.scalar(select(func.count()).select_from(LabelLog))
        charges = await session.scalar(select(ApiKey.labels_today))
    assert (response.status_code, count, charges) == (422, 0, 0)
    assert response.json()["detail"] == "Item 0: Content does not match project modality"


@pytest.mark.parametrize("corruption", ["missing", "invalid_url", "invalid_inline"])
async def test_reopen_checks_existing_image_layout(wire: Wire, corruption):
    path = await project(wire)
    item = frame(item_media_url=URL, model_version="1", source="camera", annotator_id="observer", model_confidence=.8)
    initial = (await wire.request("POST", path + "/predictions", json=batch(item), status=201)).json()["results"][0]
    route = path + "/predictions/" + initial["id"]
    review = (await wire.request("POST", route + "/review", json={
        "action": "accept", "expected_revision": initial["current_label_log_id"],
        "decision_version": initial["decision_version"]})).json()
    # Explicit persisted-data fixture: can a damaged source propagate to a fresh revision?
    async with wire.factory.sessions.begin() as session:
        content = (await session.scalars(select(LabelContent).where(
            LabelContent.label_log_id == UUID(review["current_label_log_id"])))).one()
        if corruption == "missing":
            await session.delete(content)
        else:
            content.image_url = "https://pictures.example.test/data.pdf" if corruption == "invalid_url" else inline(b"not PNG")
    response = await wire.client.post(route + "/reopen", json={"expected_revision": review["current_label_log_id"],
                                                               "decision_version": review["decision_version"]})
    async with wire.factory.sessions() as session:
        old = await session.get(LabelLog, UUID(review["current_label_log_id"]))
        assert old is not None
        successor = old.superseded_by
    assert response.status_code in (409, 422)
    assert successor is None


@pytest.mark.parametrize("adapter", ["predict", "webhook"])
@pytest.mark.parametrize("aggregate", [False, True], ids=["individual", "aggregate"])
async def test_connector_inline_size_before_database(wire: Wire, db_engine, monkeypatch, adapter, aggregate):
    await project(wire)
    headers = {"X-LS-Token": "harness-ls"}
    await wire.request("POST", "/v1/label-studio/configure", headers=headers, json={
        "domain_id": "camera", "project_id": "mapped", "image_field": "data.photo",
        "factor_map": {"quality": "data.q", "difficulty": "data.d"}})
    # A tiny substitute budget exercises ordering with an ordinary small image.
    monkeypatch.setattr(modality, "MAX_INLINE", len(PNG) if aggregate else len(PNG) - 1)
    task: dict[str, Any] = {"id": "one", "data": {"category": "A", "q": .8, "d": .2, "photo": inline(PNG)}}
    payload: dict[str, Any] = ({"project": "mapped", "tasks": [task]} if adapter == "predict" else {
        "project": "mapped", "action": "ANNOTATION_CREATED", "task": task,
        "annotation": {"id": "first", "actual_action": "approve"}})
    if aggregate:
        if adapter == "predict":
            payload["tasks"].append({**task, "id": "two"})
        else:
            task["data"]["attachments"] = {"thumbnail": inline(PNG)}
    calls = 0

    def count(*args):
        nonlocal calls
        calls += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", count)
    try:
        refused = await wire.request("POST", "/v1/label-studio/" + adapter, headers=headers, json=payload, status=413)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", count)
    assert refused.json()["detail"] == "Embedded images exceed 10 MiB"
    assert calls == 0


async def test_media_error_responses_and_logs(wire: Wire, caplog):
    caplog.set_level(logging.INFO)
    path = await project(wire)
    marker = "G4_PRIVATE_EXAMPLE"
    url = "https://pictures.example.test/frame.png?signature=" + marker
    image = frame(item_media_url=url)
    await submit(wire, path, image)
    cases = [
        (path + "/labels/batch", batch(frame(item_media_url=url.replace(".png", ".html"))), 422),
        (path + "/labels/batch", batch(frame(item_media_url=url, text="one", item_text="two")), 422),
        (path + "/predictions", batch(image), 422),
        (path + "/labels/items/frame/relabel", {"item_media_url": url}, 422),
        (path + "/labels/items/frame/content", {"content_type": "image_classification", "image_url": url}, 409),
    ]
    for route, payload, status in cases:
        response = await wire.client.post(route, json=payload)
        assert response.status_code == status and "detail" in response.json()
        assert marker not in response.text
    for headers, expected in (({"Content-Encoding": "gzip"}, 415), ({"Content-Length": "bad"}, 400),
                              ({"Content-Length": str(media_intake.MAX_BODY + 1)}, 413),
                              ({"X-Api-Key": "fixture-invalid"}, 401)):
        response = await wire.client.post(path + "/labels/batch", json=batch(image), headers=headers)
        assert response.status_code == expected and marker not in response.text
    assert marker not in caplog.text


async def test_relabel_diagnostic_uses_field_metadata(wire: Wire):
    path = await project(wire)
    await submit(wire, path, frame(item_media_url=URL))
    row = await detail(wire, path)
    private_category = "retired-customer-taxonomy"
    rejected = await wire.request("POST", path + "/labels/items/frame/relabel", status=422,
                                  json={"category": private_category, "idempotency_token": row["revision_id"]})
    assert "category" in rejected.json()["detail"].lower()
    assert private_category not in rejected.text


@pytest.mark.parametrize("kind", ["labels/batch", "predictions"])
async def test_strict_receipt_rejects_unstored_annotations(wire: Wire, kind):
    path = await project(wire, "text")
    item = frame()
    status = 200
    if kind == "predictions":
        item.update(source="camera", model_version="1", model_confidence=.8, annotator_id="observer")
        status = 201
    route = path + "/" + kind
    first = await wire.request("POST", route, json=batch(item), status=status)
    invalid = await wire.request("POST", route, json=batch({**item, "tags": ["A"]}), status=422)
    assert invalid.json()["detail"] == "Item 0: Content does not match project modality"
    replay = await wire.request("POST", route, json=batch(item), status=status)
    assert replay.json() == first.json()
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(LabelLog)) == 1
        assert await session.scalar(select(ApiKey.labels_today)) == 1


async def test_old_nested_receipt_cannot_authorize_replacement(wire: Wire):
    path = await project(wire, "legacy")
    url = "https://cdn.example/opaque"
    response = await wire.request("POST", path + "/labels/batch", json=batch(frame(content={
        "content_type": "image_classification", "image_url": url})))
    async with wire.factory.sessions.begin() as session:
        receipt = (await session.scalars(select(ProjectRequest))).one()
        receipt.payload_digest = "b265dbf1cdb04449f4884b806bb8811507c5d0525cd826c9959bb5115c3b3227"
    replay = await wire.request("POST", path + "/labels/batch", json=batch(frame(item_media_url=url)))
    assert replay.json() == response.json()
    changed = await wire.request("POST", path + "/labels/batch", status=409,
                                 json=batch(frame(item_media_url=url + "?new=1")))
    assert changed.json()["detail"] == "Request key was used with different content"
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(ApiKey.labels_today)) == 1
        assert await session.scalar(select(LabelContent.image_url)) == url
