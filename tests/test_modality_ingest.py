"""MM-02 transport, policy and receipt contracts against the real ASGI app and PostgreSQL."""
from __future__ import annotations

import asyncio
import base64
import json
import socket
import sys
from typing import Any

import pytest
from sqlalchemy import func, select

from db.models import ApiKey, LabelLog, Prediction, ProjectRequest
from tests.harness.conftest import db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio
MIB = 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n"
URL = "https://cdn.example/archive/frame%2042.PNG?sig=a%2Bb&expires=3"


@pytest.fixture
def anyio_backend():
    # This module lives outside the harness conftest's Windows loop-policy hook.
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture(autouse=True)
def enable_images(monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    monkeypatch.setenv("DLJ_INLINE_IMAGES_ENABLED", "true")


async def project(wire: Wire, mode: str = "image", name: str = "camera") -> str:
    axes = {"content_type": mode} if mode != "legacy" else {}
    response = await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name, "categories": ["A", "B"],
        "actions": ["approve", "reject"], "factors": ["quality", "difficulty"], **axes})
    return "/v1/projects/" + response.json()["id"]


def frame(label: str = "frame", **fields) -> dict:
    return {"label_id": label, "category": "A", "factors": {"quality": .8, "difficulty": .2}, **fields}


def batch(*items: dict, key: str = "frozen") -> dict:
    return {"request_key": key, "items": list(items)}


def inline(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


async def detail(wire: Wire, path: str, label: str = "frame") -> dict:
    return (await wire.request("GET", f"{path}/labels/items/{label}")).json()


async def submit(wire: Wire, path: str, item: dict, status: int = 200):
    return await wire.request("POST", path + "/labels", json=item, status=status,
                              headers={"Idempotency-Key": item["label_id"]})


async def test_oversized_body_rejected(wire: Wire):
    path = await project(wire)
    body = b"{}".ljust(21 * MIB)
    declarations: list[dict[str, str]] = [{}, {"Content-Length": "100"}]
    for headers in declarations:
        response = await wire.request("POST", path + "/labels/batch", content=body, status=413,
                                      headers={"Content-Type": "application/json", **headers})
        assert response.json() == {"detail": "Media request exceeds 20 MiB"}

    async def chunks():
        for _ in range(21):
            yield b" " * MIB
    response = await wire.request("POST", path + "/predictions", content=chunks(), status=413)
    assert response.json()["detail"] == "Media request exceeds 20 MiB"


async def test_normal_body_accepted(wire: Wire):
    path = await project(wire)
    data = json.dumps(batch(frame(item_media_url=URL))).encode().ljust(MIB)
    response = await wire.request("POST", path + "/labels/batch", content=data,
                                  headers={"Content-Type": "application/json"})
    assert response.json()["batch_size"] == 1
    assert (await detail(wire, path))["content"]["image_url"] == URL
    limit = 20 * MIB
    for size, expected in ((limit, 200), (limit + 1, 413)):
        at_boundary = await wire.request("POST", path + "/labels/batch", status=expected,
                                         content=data.ljust(size), headers={"Content-Type": "application/json"})
        assert at_boundary.json() == (response.json() if expected == 200 else
                                      {"detail": "Media request exceeds 20 MiB"})


async def test_admission_semaphore(wire: Wire):
    path = await project(wire)
    ready = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()

    async def hold(index: int):
        body = json.dumps(batch(frame(str(index), item_media_url=URL), key=str(index))).encode()
        async def stream():
            yield b" " * (MIB + 1)
            ready[index].set()
            await release.wait()
            yield body
        return await wire.client.post(path + "/labels/batch", content=stream(),
                                      headers={"Content-Type": "application/json"})

    requests = [asyncio.create_task(hold(i)) for i in range(2)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), 5)
        busy = await wire.request("POST", path + "/predictions", content=b" " * (MIB + 1), status=429)
        assert busy.json() == {"detail": "Media intake is busy"} and int(busy.headers["Retry-After"]) > 0
    finally:
        release.set()
        responses = await asyncio.gather(*requests)
    assert [r.status_code for r in responses] == [200, 200]
    # Cancellation during a chunked receive must also return both permits.
    release.clear()
    for event in ready:
        event.clear()
    cancelled = [asyncio.create_task(hold(i)) for i in range(2)]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), 5)
    finally:
        for task in cancelled:
            task.cancel()
        stopped = await asyncio.gather(*cancelled, return_exceptions=True)
        release.set()
    assert all(isinstance(result, asyncio.CancelledError) for result in stopped)
    assert (await hold(0)).json() == responses[0].json()


async def test_unsupported_encoding(wire: Wire):
    path = await project(wire)
    for route in ("/v1/labels/ingest", "/v1/labels/ingest/batch", path + "/labels",
                  path + "/labels/batch", path + "/predictions", path + "/labels/items/a/content",
                  "/v1/labels/camera/items/a/relabel", "/v1/label-studio/predict", "/v1/label-studio/webhook"):
        response = await wire.request("POST", route, content=b"{}", headers={"Content-Encoding": "gzip"}, status=415)
        assert response.json() == {"detail": "Unsupported request content encoding"}


async def test_valid_https_image_url(wire: Wire, monkeypatch):
    lookup = socket.getaddrinfo
    def local_only(host, *args, **kwargs):
        assert host != "cdn.example", "External image validation attempted network access"
        return lookup(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_only)
    path = await project(wire)
    await submit(wire, path, frame(item_media_url=URL))
    row = await detail(wire, path)
    outsider = await wire.factory.user("unrelated-tenant")
    denied = await wire.request("GET", path + "/labels/items/frame", status=404,
                                headers={"X-Api-Key": outsider})
    assert URL not in denied.text
    for endpoint in ("/labels/pending", "/next-batch", "/predictions?origin=human"):
        summary = (await wire.request("GET", path + endpoint)).json()
        records = summary if isinstance(summary, list) else summary["items"]
        assert records[0]["media_kind"] == "image" and URL not in json.dumps(records)
    assert (row["text"], row["content"]["image_url"]) == ("frame 42.PNG", URL)
    await wire.request("POST", path + "/labels/items/frame/relabel", json={
        "idempotency_token": row["revision_id"], "category": "B"})
    revised = await detail(wire, path)
    assert revised["revision_id"] != row["revision_id"] and revised["content"] == row["content"]
    await wire.request("POST", path + "/labels/bulk-verify", json={
        "items": [{"label_id": revised["label_id"], "verified_outcome": True}], "action": "approve"})
    assert (await detail(wire, path))["content"] == row["content"]
    for i, query in enumerate(("format=webp", "fm=JPEG", "response-content-type=image%2Fgif")):
        await submit(wire, path, frame(str(i), item_text="explicit caption",
                                       item_media_url="https://cdn.example/content?" + query))
        assert (await detail(wire, path, str(i)))["text"] == "explicit caption"


async def test_http_url_rejected(wire: Wire):
    path = await project(wire)
    for url in ("http://assets.example/a.png", "https://@assets.example/a.png",
                "https://bad host/a.png", "https://assets.example/a.png#",
                "https://assets.example:99999/a.png", "https://example.org\\x/a.png"):
        response = await submit(wire, path, frame(item_media_url=url), 422)
        assert response.json() == {"detail": "Invalid image HTTPS URL"}


async def test_non_image_extension_rejected(wire: Wire):
    path = await project(wire)
    response = await wire.request("POST", path + "/labels/batch", status=422, json=batch(
        frame("first", item_media_url=URL), frame(item_media_url="https://cdn.example/b.pdf?signature=png")))
    assert response.json()["detail"] == "Item 1: Invalid image HTTPS URL"
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(LabelLog)) == 0
        assert await session.scalar(select(ApiKey.labels_today)) == 0


async def test_opaque_url_on_legacy(wire: Wire):
    path = await project(wire, "legacy")
    nested = {"content_type": "image_classification", "image_url": "https://cdn.example/opaque"}
    response = await wire.request("POST", path + "/labels/batch", json=batch(frame(content=nested)))
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(ProjectRequest.payload_digest)) == (
            "801c3824e1b6d4589077ce8da8b1bcd5e9d9f34a6ac0e5ea8ae92e0a9e41010a")
    replay = await wire.request("POST", path + "/labels/batch", json=batch(frame(item_media_url=nested["image_url"])))
    assert response.json() == replay.json()
    assert (await detail(wire, path))["content"]["image_url"] == nested["image_url"]


async def test_data_uri_accepted(wire: Wire, monkeypatch):
    path = await project(wire)
    image = inline(PNG + bytes(10 * MIB - len(PNG)))
    await submit(wire, path, frame(item_media_url=image))
    row = await detail(wire, path)
    assert row["text"] == "Image" and row["content"]["image_url"] == image
    # A complete 1x1 PNG complements the synthetic maximum-length signature fixture.
    small = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
             "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    prediction = frame("pred", item_media_url=small, model_version="v1", source="camera",
                       annotator_id="ann", model_confidence=.9)
    created = (await wire.request("POST", path + "/predictions", json=batch(prediction), status=201)).json()["results"][0]
    async with wire.factory.sessions() as session:
        pred = (await session.scalars(select(Prediction))).one()
        assert pred.original_content["content"]["image_url"]["content_ref"] == str(pred.original_label_log_id)
        assert small not in json.dumps(pred.original_content)
    assert (await detail(wire, path, "pred"))["prediction"]["original_content"]["content"]["image_url"] == small
    queue = (await wire.request("GET", path + "/predictions")).json()["items"]
    assert queue[0]["media_kind"] == "image" and small not in json.dumps(queue)
    # Historical media can be reviewed and reopened after new inline intake is switched off.
    monkeypatch.setenv("DLJ_INLINE_IMAGES_ENABLED", "false")
    prediction_path = path + "/predictions/" + created["id"]
    reviewed = (await wire.request("POST", prediction_path + "/review", json={
        "action": "correct", "category": "B", "decision_version": created["decision_version"],
        "expected_revision": created["current_label_log_id"]})).json()
    await wire.request("POST", prediction_path + "/reopen", json={
        "decision_version": reviewed["decision_version"], "expected_revision": reviewed["current_label_log_id"]})
    current = await detail(wire, path, "pred")
    assert current["content"]["image_url"] == current["prediction"]["original_content"]["content"]["image_url"] == small
    await submit(wire, path, frame(item_media_url=image))
    denied = await submit(wire, path, frame("disabled", item_media_url=small), 422)
    assert denied.json()["detail"] == "Embedded images are not enabled"


async def test_data_uri_too_large(wire: Wire):
    path = await project(wire)
    for items in ([frame(item_media_url=inline(PNG + bytes(11 * MIB)))],
                  [frame(item_media_url=inline(PNG + bytes(10 * MIB + 1 - len(PNG))))],
                  [frame(str(i), item_media_url=inline(PNG + bytes(5 * MIB))) for i in range(2)]):
        response = await wire.request("POST", path + "/labels/batch", json=batch(*items), status=413)
        assert response.json() == {"detail": "Embedded images exceed 10 MiB"}


async def test_data_uri_wrong_signature(wire: Wire):
    path = await project(wire)
    for uri in (inline(b"\xff\xd8jpeg"), inline(PNG) + " ", "data:image/svg+xml;base64,AAAA",
                "data:image/png;name=secret;base64,AAAA", inline(PNG + b"ab")[:-3] + "x=="):
        response = await submit(wire, path, frame(item_media_url=uri), 422)
        assert response.json() == {"detail": "Invalid embedded image"}


async def test_image_project_requires_media(wire: Wire):
    path = await project(wire)
    missing = await submit(wire, path, frame(), 422)
    assert missing.json() == {"detail": "Image projects require item_media_url"}
    for invalid in (frame(item_media_url=URL, tags=["A"]), frame(content={
            "content_type": "image_classification", "image_url": URL, "tags": ["A"]})):
        bad = await submit(wire, path, invalid, 422)
        assert bad.json()["detail"] == "Content does not match project modality"
    headers = {"X-LS-Token": "harness-ls"}
    await wire.request("POST", "/v1/label-studio/configure", headers=headers, json={
        "domain_id": "camera", "project_id": "mapped", "image_field": "data.photo",
        "factor_map": {"quality": "data.q", "difficulty": "data.d"}})
    task: dict[str, Any] = {"id": "task", "data": {"q": .8, "d": .2, "category": "A"}}
    predict = {"project": "mapped", "tasks": [task]}
    rejected = await wire.request("POST", "/v1/label-studio/predict", headers=headers, json=predict, status=422)
    assert "require item_media_url" in rejected.json()["detail"]
    task["data"]["photo"] = URL
    await wire.request("POST", "/v1/label-studio/predict", headers=headers, json=predict)
    assert (await detail(wire, path, "task"))["content"]["image_url"] == URL
    task["data"]["photo"] = "https://cdn.example/replacement.jpg"
    conflict = await wire.request("POST", "/v1/label-studio/predict", headers=headers, json=predict, status=409)
    assert conflict.json()["detail"] == "Task image changed after scoring"
    task["data"].pop("photo")
    task["data"]["ground_truth"] = "approve"
    event = {"action": "ANNOTATION_CREATED", "project": "mapped", "task": task,
             "annotation": {"id": "source", "actual_action": "approve"}}
    await wire.request("POST", "/v1/label-studio/webhook", headers=headers, json=event)
    event.update(action="ANNOTATION_UPDATED", annotation={"id": "source", "actual_action": "reject"})
    await wire.request("POST", "/v1/label-studio/webhook", headers=headers, json=event)
    revised = await detail(wire, path, "task")
    assert revised["label_id"] != "task" and revised["content"]["image_url"] == URL
    task["data"]["photo"] = "https://cdn.example/reassigned.jpg"
    rebound = {**event, "action": "ANNOTATION_CREATED", "annotation": {"id": "second", "actual_action": "approve"}}
    refused = await wire.request("POST", "/v1/label-studio/webhook", headers=headers, json=rebound, status=409)
    assert refused.json()["detail"] == "Task image changed after scoring"


async def test_text_project_forbids_image(wire: Wire):
    path = await project(wire, "text")
    response = await submit(wire, path, frame(item_media_url=URL), 422)
    assert response.json()["detail"] == "Content does not match project modality"
    result = await wire.request("POST", "/v1/labels/ingest", json=frame(domain_id="camera", item_media_url=URL),
                                status=422)
    assert result.json() == response.json()


async def test_legacy_project_allows_mixed(wire: Wire):
    path = await project(wire, "legacy")
    plain = await wire.request("POST", path + "/labels/batch", json=batch(frame()))
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(ProjectRequest.payload_digest)) == (
            "7d4a48985d2121e1e49e901836663753b7764305b63fa265c2256d4a856c5d09")
    assert (await wire.request("POST", path + "/labels/batch", json=batch(frame()))).json() == plain.json()
    await submit(wire, path, frame("pic", item_media_url=URL))
    assert (await detail(wire, path))["content"] is None
    assert (await detail(wire, path, "pic"))["content"]["image_url"] == URL
    # The pre-notes serializer omitted only the notes member. Reuse its persisted receipt.
    async with wire.factory.sessions.begin() as session:
        receipt = (await session.scalars(select(ProjectRequest).where(ProjectRequest.request_key == "frozen"))).one()
        receipt.payload_digest = "3345147f0ef2943e888e4dc2104a610428d53de7ef4fa4acbb6ef5de2d5f0add"
    old = await wire.request("POST", path + "/labels/batch", json=batch(frame()))
    assert old.json() == plain.json()
    await wire.request("POST", path + "/labels/batch", json=batch(frame(notes="changed")), status=409)


async def test_score_parity_text_vs_image(wire: Wire):
    text = await project(wire, "text", "text-control")
    image = await project(wire, "image", "image-control")
    scores = [(await submit(wire, text, frame(text="caption"))).json(),
              (await submit(wire, image, frame(item_media_url=URL))).json()]
    independent_fields = {"decision_id"}
    assert {k: v for k, v in scores[0].items() if k not in independent_fields} == {
        k: v for k, v in scores[1].items() if k not in independent_fields}
    assert scores[0]["factors_used"] == {"quality": .8, "difficulty": .2}


async def test_replay_with_media(wire: Wire):
    path = await project(wire)
    first = await wire.request("POST", path + "/labels/batch", json=batch(frame(item_media_url=URL, item_text="A")))
    replay = await wire.request("POST", path + "/labels/batch", json=batch(frame(text="A", content={
        "content_type": "image_classification", "image_url": URL})))
    assert replay.json() == first.json()
    for nested in (None, {"image_url": URL}):
        same = await wire.request("POST", path + "/labels/batch", json=batch(
            frame(item_text="A", item_media_url=URL, content=nested)))
        assert same.json() == first.json()
    async with wire.factory.sessions() as session:
        assert await session.scalar(select(ApiKey.labels_today)) == 1
        assert await session.scalar(select(func.count()).select_from(LabelLog)) == 1


async def test_replay_different_media(wire: Wire):
    path = await project(wire)
    await submit(wire, path, frame(item_media_url=URL))
    changed = await submit(wire, path, frame(item_media_url=URL + "0"), 409)
    assert changed.json()["detail"] == "Request key was used with different content"
    conflicts: list[dict] = [{"text": "other", "item_text": "caption"},
                  {"content": {"content_type": "image_classification", "image_url": URL + "0"}},
                  {"content": {"content_type": "text_ner"}}]
    for other in conflicts:
        conflict = await submit(wire, path, frame(item_media_url=URL, **other), 422)
        assert conflict.json()["detail"] == "Conflicting values for text or image URL"
