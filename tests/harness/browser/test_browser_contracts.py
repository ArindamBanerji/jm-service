"""Chromium uses a real loopback HTTP server, the built SPA and the test's isolated database."""
import asyncio
from collections.abc import AsyncIterator, Iterator
import json
import os
import re
import socket
from threading import Thread
from time import monotonic, sleep

from playwright.async_api import ConsoleMessage, Page, async_playwright, expect
import pytest
import uvicorn

from jm_service import app
from ..fixtures.factory import Wire
from ..fixtures.failures import KnownGap

pytestmark = pytest.mark.anyio


@pytest.fixture
def origin(wire: Wire) -> Iterator[str]:
    # The wire fixture already owns app lifespan. Use a private port unless DLJ_PORT is specified.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", int(os.getenv("DLJ_PORT", "0"))))
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", access_log=False, log_level="warning"))

        def serve() -> None:
            # This thread only serves TCP. Playwright's subprocess stays on the test event loop.
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                runner.run(server.serve(sockets=[listener]))

        worker = Thread(target=serve, daemon=True)
        worker.start()
        try:
            deadline = monotonic() + 5
            while not server.started:
                if not worker.is_alive() or monotonic() >= deadline:
                    raise RuntimeError("Browser contract server did not start")
                sleep(.01)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            worker.join(5)
            assert not worker.is_alive(), "Browser contract server did not stop"


@pytest.fixture
async def page(wire: Wire, origin, request) -> AsyncIterator[Page]:
    await wire.factory.domain()
    await wire.factory.label()
    errors: list[str] = []

    def record(message: ConsoleMessage) -> None:
        if message.type == "error":
            expected_conflict = (request.node.name == "test_known_failure_review_draft" and
                                 message.location["url"].endswith("/relabel") and "409" in message.text)
            expected_boundary = (request.node.name == "test_s32_incompatible_json_and_failed_lazy_chunk"
                                 and ("Dashboard" in message.text or "Failed to fetch" in message.text or "ERR_FAILED" in message.text))
            expected_abort = (request.node.name in {
                "test_s29_rotation_between_real_import_chunks_then_restart",
                "test_s30_domain_switch_with_detail_search_bulk_in_flight_duplicated_public_ids",
            } and ("ERR_FAILED" in message.text or "ERR_ABORTED" in message.text))
            if not expected_conflict and not expected_boundary and not expected_abort:
                errors.append(message.text)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context(base_url=origin)
            key = json.dumps(wire.client.headers["x-api-key"])
            await context.add_init_script(f"if (!localStorage.getItem('harness-initialized')) {{ localStorage.setItem('harness-initialized', '1'); localStorage.setItem('rgi-api-key', {key}); localStorage.setItem('rgi-domain', 'demo'); }}")
            tab = await context.new_page()
            # These screens use a real PostgreSQL service and a cold browser per test.
            # Bound render waits independently of the overall 120-second scenario.
            expect.set_options(timeout=20_000)
            tab.on("console", record)
            tab.on("pageerror", lambda error: errors.append(str(error)) if request.node.name !=
                   "test_s32_incompatible_json_and_failed_lazy_chunk" else None)
            yield tab
            await tab.wait_for_load_state("networkidle")
            assert not errors, errors
        finally:
            expect.set_options(timeout=5_000)
            await browser.close()


@pytest.mark.parametrize("route,heading,element", [
    ("upload", "Start with your labels.", "button:has-text('Try with sample data')"),
    ("queue", "Scored Queue", "#queue-search-input"),
    ("review/L1", "Review label", "select[aria-label='Override action']"),
    ("dashboard", "Dashboard", "text=Autonomy ladder"),
    ("annotators", "Annotator Profiles", "th[tabindex='0']"),
    ("health", "Label Health Report", "button:has-text('Choose CSV')"),
    ("signup", "Start your free trial.", "input[type=email]"),
    ("settings", "Settings", "button:has-text('Refresh account')"),
    ("projects", "Projects", "button:has-text('Create project')"),
], ids=["upload", "queue", "review", "dashboard", "annotators", "health", "signup", "settings", "projects"])
async def test_screen(page: Page, route, heading, element):
    await page.goto(f"/#/{route}")
    await expect(page.get_by_role("heading", level=1)).to_contain_text(heading)
    await expect(page.locator(element).first).to_be_visible()
    await expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()


async def test_review_component_contract(page: Page):
    async with page.expect_response(lambda response: response.url.endswith("/items/L1")) as received:
        await page.goto("/#/review/L1")
    detail = await received.value
    assert detail.ok and (await detail.json())["label_id"] == "L1"
    await expect(page.get_by_role("region", name="Source text")).to_contain_text("Sample text", timeout=20_000)
    await expect(page.get_by_role("region", name="Edit named entities")).to_be_visible()
    await expect(page.get_by_label("Choose category")).to_be_enabled()
    await expect(page.get_by_role("button", name="Save Spans")).to_be_disabled()
    await page.get_by_role("button", name="Guidelines").click()
    await expect(page.get_by_role("button", name="Guidelines")).to_have_attribute("aria-expanded", "true")


async def test_project_creation_chooser_and_settings(page: Page, wire: Wire):
    await page.goto("/#/projects")
    await page.get_by_label("Project name").fill("Browser project")
    await page.get_by_label("Public ID").fill("browser-project")
    await page.get_by_role("button", name="Create project").click()
    await expect(page).to_have_url(re.compile(r"/projects/[0-9a-f-]+/queue"))
    await expect(page.locator("#project-chooser")).not_to_have_value("")
    await page.get_by_role("link", name="Project settings").click()
    await expect(page.get_by_role("heading", name="Project settings")).to_be_visible()
    project = await page.locator("#project-chooser").input_value()
    headers = {"X-LS-Token": "harness-ls"}
    config = {"project_id": "external", "domain_id": "browser-project",
              "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}}
    saved = await wire.request("POST", "/v1/label-studio/configure", headers=headers, json=config)
    assert saved.headers["etag"] == '"1"'
    await page.get_by_label("Description").fill("Review guidelines for this project")
    await page.get_by_role("button", name="Save project settings").click()
    await expect(page.get_by_role("status")).to_contain_text("Project settings saved")
    await wire.request("POST", "/v1/label-studio/configure", headers={**headers, "If-Match": '"0"'},
                       status=409, json=config)
    updated = await wire.request("POST", "/v1/label-studio/configure",
                       headers={**headers, "If-Match": saved.headers["etag"]}, json=config)
    assert updated.headers["etag"] == '"2"'
    fresh = (await wire.request("GET", f"/v1/projects/{project}")).json()
    assert fresh["settings_version"] == 2 and fresh["description"] == "Review guidelines for this project"
    await wire.request("POST", "/v1/label-studio/configure", headers=headers,
                       status=409, json={**config, "domain_id": "demo"})


async def test_s27_real_queue_bulk_against_shared_write_backend(page: Page, wire: Wire):
    """B/C integration: the real queue sends explicit truth and C skips stale evidence."""
    await wire.factory.label("L2")
    await page.goto("/#/queue")
    await expect(page.get_by_label("Select L2")).to_be_visible()
    await page.get_by_label("Select all on this page").check()
    await wire.request("POST", "/v1/labels/verify", json={
        "domain_id": "demo", "label_id": "L2", "actual_action": "approve",
        "verified_outcome": False,
    })
    await page.get_by_label("Bulk known outcome").select_option("correct")
    async with page.expect_request("**/v1/labels/demo/bulk-verify") as captured:
        await page.get_by_role("button", name="Approve All").click()
    sent = (await captured.value).post_data_json
    assert isinstance(sent, dict) and sent["outcome"] is True
    await expect(page.get_by_role("status")).to_contain_text("Approved 1, skipped 1")
    details = (await wire.request("GET", "/v1/labels/demo/items/L1")).json()
    assert details["verified_outcome"] is True


@pytest.mark.prompt_b
async def test_known_failure_review_draft(page: Page, wire: Wire):
    await wire.request("POST", "/v1/labels/demo/items/L1/content", status=201,
                       json={"content_type": "text_multilabel", "tags": ["A"]})
    await page.goto("/#/review/L1")
    tag = page.get_by_role("combobox", name="Add tag")
    await tag.fill("new")
    await tag.press("Enter")
    await tag.fill("next")
    await page.get_by_role("button", name="Save Tags").click()
    await expect(page).to_have_url(re.compile(r"/review/revision"))
    await expect(tag).to_have_value("next")
    await tag.fill("")
    await page.get_by_label("Choose category").select_option("B")
    await page.get_by_label("Known outcome").select_option("correct")
    approve = page.get_by_role("button", name="Approve recommendation (A)")
    category_unprotected = await approve.is_enabled()

    # Another editor saves first. Exercise the real 409 and canonical refetch.
    await page.get_by_label("Choose category").select_option("A")
    await tag.fill("local-change")
    await tag.press("Enter")
    await tag.fill("unfinished")
    path = "/v1/labels/demo/items/L1"
    current = (await wire.request("GET", path)).json()
    await wire.request("POST", path + "/relabel", json={
        "category": "A", "tags": ["A", "remote"], "idempotency_token": current["revision_id"]})
    async with page.expect_response(lambda r: r.url.endswith("/relabel") and r.request.method == "POST") as reply:
        await page.get_by_role("button", name="Save Tags").click()
    assert (await reply.value).status == 409
    await page.wait_for_load_state("networkidle")
    draft_preserved = (await tag.input_value() == "unfinished" and
                       await page.get_by_role("button", name="Remove local-change").count() == 1)
    if category_unprotected or not draft_preserved:
        raise KnownGap(f"Category guarded: {not category_unprotected}, conflict draft preserved: {draft_preserved}")


@pytest.mark.prompt_b
async def test_known_failure_queue_navigation(page: Page, wire: Wire):
    await page.goto("/#/queue")
    await page.get_by_role("link", name="Review →").first.click()
    await expect(page.get_by_role("heading", name="L1")).to_be_visible()
    # Inspect keys only. A view that refetches detail does not need the pending DTO.
    manual_has_dto = await page.evaluate("Boolean(history.state?.usr?.label)")
    await wire.factory.label("L2")
    await page.reload()
    await page.get_by_label("Known outcome").select_option("correct")
    await page.get_by_role("button", name="Approve recommendation (A)").click()
    await expect(page.get_by_role("heading", name="L2")).to_be_visible()
    next_has_dto = await page.evaluate("Boolean(history.state?.usr?.label)")
    if manual_has_dto or next_has_dto:
        raise KnownGap(f"DTO retained by manual review: {manual_has_dto}, auto-next: {next_has_dto}")
