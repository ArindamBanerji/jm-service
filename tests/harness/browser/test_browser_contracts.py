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
            if not expected_conflict:
                errors.append(message.text)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context(base_url=origin)
            key = json.dumps(wire.client.headers["x-api-key"])
            await context.add_init_script(f"localStorage.setItem('rgi-api-key', {key}); localStorage.setItem('rgi-domain', 'demo')")
            tab = await context.new_page()
            tab.on("console", record)
            tab.on("pageerror", lambda error: errors.append(str(error)))
            yield tab
            await tab.wait_for_load_state("networkidle")
            assert not errors, errors
        finally:
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
], ids=["upload", "queue", "review", "dashboard", "annotators", "health", "signup", "settings"])
async def test_screen(page: Page, route, heading, element):
    await page.goto(f"/#/{route}")
    await expect(page.get_by_role("heading", level=1)).to_contain_text(heading)
    await expect(page.locator(element).first).to_be_visible()
    await expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()


async def test_review_component_contract(page: Page):
    await page.goto("/#/review/L1")
    await expect(page.get_by_role("region", name="Source text")).to_contain_text("Sample text")
    await expect(page.get_by_role("region", name="Edit named entities")).to_be_visible()
    await expect(page.get_by_label("Choose category")).to_be_enabled()
    await expect(page.get_by_role("button", name="Save Spans")).to_be_disabled()
    await page.get_by_role("button", name="Guidelines").click()
    await expect(page.get_by_role("button", name="Guidelines")).to_have_attribute("aria-expanded", "true")


@pytest.mark.prompt_b
@pytest.mark.xfail(strict=True, raises=KnownGap, reason="R3-03: category draft must prevent a premature verification")
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
@pytest.mark.xfail(strict=True, raises=KnownGap, reason="F7-01: review history should contain identifiers only")
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
