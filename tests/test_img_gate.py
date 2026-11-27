"""Image release gate: real project APIs, PostgreSQL snapshots and the built CSV importer."""
import asyncio
import base64
import csv
import io
import json
import sys
from uuid import UUID, uuid4

from playwright.async_api import Page, expect
import pytest
from sqlalchemy import update

from db.models import Domain
from tests.harness.browser.test_browser_contracts import origin, page  # noqa: F401
from tests.harness.conftest import db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio
TEXT_FIELDS = ("root_label_id current_label_id source text category annotator_id notes review_notes "
               "recommended_action actual_action verified_outcome confidence scored_at verified_at "
               "revision_at content review_state model_confidence dlj_confidence human_spans_reviewed").split()
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="


@pytest.fixture
def anyio_backend(request):
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop if "page" in request.fixturenames else asyncio.SelectorEventLoop
        return "asyncio", {"loop_factory": loop}
    return "asyncio"


@pytest.fixture(autouse=True)
def image_switches(monkeypatch):
    monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
    monkeypatch.setenv("DLJ_INLINE_IMAGES_ENABLED", "true")


async def project(wire: Wire, alias: str, kind: str | None = "image") -> str:
    axes = {"content_type": kind, "label_schema": "single"} if kind else {}
    body = {"name": alias, "public_domain_id": alias, "categories": ["A", "B"],
            "actions": ["approve", "reject"], "factors": ["quality", "difficulty"], **axes}
    return "/v1/projects/" + (await wire.request("POST", "/v1/projects", json=body, status=201)).json()["id"]


def frame(i: int, *, image: bool = True) -> dict:
    item = {"label_id": f"item-{i}", "category": "A", "text": f'Caption {i}, "detail"\nsecond line',
            "factors": {"quality": .8, "difficulty": .2}}
    if image:
        item["item_media_url"] = f"https://img.example/{i}%20fr.PNG?sig=%2B%2f&part=1&part=2"
    return item


async def ingest(wire: Wire, path: str, items: list[dict]) -> list[dict]:
    return (await wire.request("POST", path + "/labels/batch",
            json={"request_key": uuid4().hex, "items": items})).json()["results"]


async def verify(wire: Wire, path: str, item: str, outcome: bool = True):
    await wire.request("POST", path + "/labels/verify",
                       json={"label_id": item, "actual_action": "approve", "verified_outcome": outcome})


async def detail(wire: Wire, path: str, item: str) -> dict:
    return (await wire.request("GET", path + "/labels/items/" + item)).json()


async def records(wire: Wire, path: str, query: str = "") -> list[dict]:
    return [json.loads(line) for line in (await wire.request("GET", path + "/export" + query)).text.splitlines()]


def csv_rows(body: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(body, newline="")))


async def test_image_lifecycle_create_to_export(wire: Wire):
    path = await project(wire, "images")
    control = await project(wire, "control", "text")
    items = [frame(i) for i in range(5)]
    scores = await ingest(wire, path, items)
    reference, = await ingest(wire, control, [frame(0, image=False)])
    assert len(scores) == 5
    for key in ("confidence", "recommended_action", "factors_used", "tier_status", "conservation_status"):
        assert scores[0][key] == reference[key]
    urls = {item["label_id"]: item["item_media_url"] for item in items}
    for label_id, url in urls.items():
        assert (await detail(wire, path, label_id))["content"]["image_url"] == url
    await verify(wire, path, "item-0")
    assert (await detail(wire, path, "item-0"))["verified_outcome"] is True
    jsonl = await records(wire, path)
    assert {r["current_label_id"]: r["image_url"] for r in jsonl} == urls
    data = (await wire.request("GET", path + "/export?format=csv")).text
    rows = csv_rows(data)
    header = list(rows[0])
    assert header[header.index("text") + 1] == "image_url"
    assert {r["current_label_id"]: r["image_url"] for r in rows} == urls
    empty = await wire.request("GET", path + "/export?format=csv&category=absent")
    assert list(csv.reader(io.StringIO(empty.text))) == [header]


async def test_image_export_roundtrip(wire: Wire, page: Page):
    source = await project(wire, "original")
    target = await project(wire, "copy")
    items = [frame(i) for i in range(3)]
    items[0]["text"] = "=one, two"
    items[1]["text"] = "'=literal quotation"
    await ingest(wire, source, items)
    await page.goto("/#/projects/" + source.rsplit("/", 1)[1] + "/queue")
    await expect(page.get_by_text("Export includes image URLs")).to_be_visible()
    async with page.expect_download() as download:
        await page.get_by_role("button", name="Download project CSV").click()
    saved = await (await download.value).path()
    assert saved is not None
    await page.goto("/#/projects/" + target.rsplit("/", 1)[1] + "/upload")
    await expect(page.get_by_role("button", name="Choose CSV or JSON")).to_be_visible()
    await page.locator("input[type=file]").set_input_files({
        "name": "project.csv", "mimeType": "text/csv", "buffer": saved.read_bytes()})
    await expect(page.get_by_text("3 image items ready to import")).to_be_visible()
    async with page.expect_response(lambda r: r.url.endswith(target + "/labels/batch")) as posted:
        await page.get_by_role("button", name="Import image labels").click()
    response = await posted.value
    assert response.ok and (await response.json())["batch_size"] == 3
    for item in items:
        row = await detail(wire, target, item["label_id"])
        assert (row["content"]["image_url"], row["text"], row["factors"]) == (
            item["item_media_url"], item["text"], item["factors"])


async def test_image_data_uri_lifecycle(wire: Wire):
    path = await project(wire, "inline")
    uri = "data:image/png;base64," + PNG
    score, = await ingest(wire, path, [{**frame(0), "item_media_url": uri}])
    assert 0 <= score["confidence"] <= 1
    assert (await detail(wire, path, "item-0"))["content"]["image_url"] == uri
    row, = await records(wire, path)
    assert row["content"]["image_url"] == row["image_url"] == uri
    decoded = base64.b64decode(row["image_url"].split(",", 1)[1], validate=True)
    assert decoded == base64.b64decode(PNG) and len(decoded) == 68
    # Two individually admissible references exceed the encoded download budget
    # once exported as both structured content and the flat interchange field.
    large = "data:image/png;base64," + base64.b64encode(decoded + bytes(7 * 1024**2)).decode()
    for i in (1, 2):
        await ingest(wire, path, [{**frame(i), "item_media_url": large}])
    for fmt in ("csv", "jsonl"):
        denied = await wire.request("GET", path + "/export?format=" + fmt, status=413)
        assert denied.json() == {"detail": "Export exceeds the media output cap"}
    assert await records(wire, path, "?category=missing") == []


async def test_mixed_project_export_isolation(wire: Wire):
    text = await project(wire, "words", "text")
    image = await project(wire, "pictures")
    await ingest(wire, text, [frame(0, image=False)])
    await ingest(wire, image, [frame(0)])
    plain, = await records(wire, text)
    picture, = await records(wire, image)
    assert "image_url" not in plain and picture["image_url"] == frame(0)["item_media_url"]
    plain_csv = csv_rows((await wire.request("GET", text + "/export?format=csv")).text)
    assert "image_url" not in plain_csv[0]
    outsider = await wire.factory.user("unrelated")
    denied = await wire.request("GET", image + "/export", headers={"X-Api-Key": outsider}, status=404)
    assert picture["image_url"] not in denied.text


async def test_image_export_with_predictions(wire: Wire):
    path = await project(wire, "models")
    await ingest(wire, path, [frame(1), frame(2)])
    predicted = {**frame(3), "source": "camera-model", "model_version": "v1",
                 "model_confidence": .94, "annotator_id": "model-reviewer"}
    imported = await wire.request("POST", path + "/predictions", status=201,
                                  json={"request_key": "predict", "items": [predicted]})
    saved, = imported.json()["results"]
    rows = await records(wire, path)
    assert len(rows) == 3
    prediction, = [r for r in rows if r["source"] == "camera-model"]
    assert prediction["image_url"] == prediction["content"]["image_url"] == predicted["item_media_url"]
    assert prediction["model_confidence"] == .94 and prediction["dlj_confidence"] == saved["dlj_confidence"]
    assert prediction["verified_outcome"] is None


async def test_image_export_preserves_provenance(wire: Wire):
    path = await project(wire, "lineage")
    item = frame(0)
    await ingest(wire, path, [item])
    await verify(wire, path, "item-0", False)
    original = await detail(wire, path, "item-0")
    prior, = await records(wire, path)
    assert prior["verified_outcome"] is False
    await wire.request("POST", path + "/labels/items/item-0/relabel",
                       json={"category": "B", "idempotency_token": original["revision_id"]})
    latest = await detail(wire, path, "item-0")
    row, = await records(wire, path)
    assert row["root_label_id"] == "item-0" and row["current_label_id"] == latest["label_id"] != "item-0"
    assert row["revision_history"] == ["item-0", latest["label_id"]]
    assert row["revision_at"] and row["verified_outcome"] is None and row["category"] == "B"
    assert row["image_url"] == prior["image_url"] == original["content"]["image_url"] == item["item_media_url"]


async def test_legacy_text_export_unchanged(wire: Wire):
    path = await project(wire, "legacy", None)
    await ingest(wire, path, [frame(0, image=False)])
    await verify(wire, path, "item-0")
    row, = await records(wire, path)
    assert list(row) == TEXT_FIELDS
    assert row["verified_outcome"] is True and row["content"] is None and row["text"] == frame(0)["text"]
    response = await wire.request("GET", path + "/export?format=csv")
    cell, = csv_rows(response.text)
    assert list(cell) == TEXT_FIELDS and cell["content"] == "" and cell["text"] == row["text"]
    assert cell["actual_action"] == "approve" and cell["verified_outcome"] == "True"
    empty = await wire.request("GET", path + "/export?format=csv&category=unobserved")
    assert list(csv.reader(io.StringIO(empty.text))) == [
        [field for field in TEXT_FIELDS if field not in ("notes", "review_notes")]]


async def test_image_export_empty_url_handling(wire: Wire):
    path = await project(wire, "strict")
    plain = frame(0, image=False)
    refused = await wire.request("POST", path + "/labels/batch", status=422,
                                 json={"request_key": "missing", "items": [plain]})
    assert "Image projects require item_media_url" in refused.json()["detail"]
    legacy = await project(wire, "legacy-images", None)
    # Public creation deliberately cannot issue an unenforced image policy.
    # Seed that historical policy, then use the normal HTTP write and export paths.
    async with wire.factory.sessions.begin() as db:
        await db.execute(update(Domain).where(Domain.id == UUID(legacy.rsplit("/", 1)[1]))
                         .values(content_type="image"))
    await ingest(wire, legacy, [plain])
    row, = await records(wire, legacy)
    assert row["image_url"] is None and row["content"] is None
    cell, = csv_rows((await wire.request("GET", legacy + "/export?format=csv")).text)
    assert cell["image_url"] == ""


async def test_export_metadata_includes_modality(wire: Wire):
    for kind in ("text", "image"):
        path = await project(wire, kind, kind)
        for fmt in ("csv", "jsonl"):
            response = await wire.request("GET", path + "/export?format=" + fmt)
            assert response.headers["X-DLJ-Content-Type"] == kind
            assert response.headers["X-DLJ-Label-Schema"] == "single"
            assert "no-store" in response.headers["Cache-Control"]
        refused = await wire.request("GET", path + "/export?format=docbin", status=422)
        assert refused.json()["detail"] == "DocBin requires a text NER project"
    legacy = await project(wire, "legacy", None)
    response = await wire.request("GET", legacy + "/export")
    assert response.headers["X-DLJ-Content-Type"] == response.headers["X-DLJ-Label-Schema"] == "mixed"


async def test_image_conservation_gate(wire: Wire):
    path = await project(wire, "conservation")
    items = [frame(i) for i in range(20)]
    scores = await ingest(wire, path, items)
    assert len(scores) == 20 and all(s["conservation_status"] == "warmup" for s in scores)
    for outcome, start, end in ((True, 0, 1), (False, 1, 10)):
        result = await wire.request("POST", path + "/labels/bulk-verify", json={"action": "approve" if outcome else "reject",
            "items": [{"label_id": item["label_id"], "verified_outcome": outcome} for item in items[start:end]]})
        assert result.json()["processed"] == end - start
    status = (await wire.request("GET", path + "/sla")).json()
    assert (status["verified_count"], status["current_accuracy"], status["gate_status"]) == (10, 10.0, "inactive")
    assert status["floor_pct"] is None and status["min_verified_for_sla"] == 50
    score, = await ingest(wire, path, [frame(20)])
    assert score["conservation_status"] == "warmup" and not score["auto_accepted"]
    assert 0 <= score["confidence"] <= 1

    # Continue past warmup on a paid tenant, using real classification evidence.
    custom = await wire.paddle_intent("professional", "txn_imagegate")
    await wire.request("POST", "/v1/billing/webhook", omit_api_key=True, json={
        "event_type": "subscription.created", "event_id": "image-gate-paid",
        "occurred_at": "2026-01-01T12:00:00Z", "data": {"id": "sub-image", "customer_id": "cust-image",
        "transaction_id": "txn_imagegate", "custom_data": custom,
        "items": [{"product": {"name": "DLJ Professional"}}]}})
    await ingest(wire, path, [frame(i) for i in range(21, 50)])
    adjudicated = await wire.request("POST", path + "/labels/bulk-verify", json={
        "action": "reject", "items": [{"label_id": f"item-{i}", "verified_outcome": False}
                                     for i in range(10, 50)]})
    assert adjudicated.json()["processed"] == 40
    status = (await wire.request("GET", path + "/sla")).json()
    assert (status["verified_count"], status["current_accuracy"], status["gate_status"]) == (50, 2.0, "paused")
    assert status["margin"] < 0 and not status["auto_approve_active"]
    gated, = await ingest(wire, path, [frame(50)])
    assert gated["conservation_status"] == "paused" and not gated["auto_accepted"]
