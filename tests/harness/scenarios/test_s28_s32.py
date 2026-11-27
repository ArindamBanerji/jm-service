"""Prompt B browser gates against real app endpoints and isolated PostgreSQL."""
import asyncio
import json
import re
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Page, Route, expect
from sqlalchemy import func, select

import auth
from db.models import ApiKey, LabelLog
from ..browser.test_browser_contracts import origin, page
from ..fixtures.factory import Wire

pytestmark = [pytest.mark.anyio, pytest.mark.prompt_b]


async def _token(wire: Wire) -> str:
    await wire.request("POST", "/v1/auth/register", status=202, omit_api_key=True,
                       json={"email": f"b-{uuid4().hex}@example.test"})
    sender = auth.send_signup_challenge_email
    assert isinstance(sender, AsyncMock) and sender.await_args is not None
    return str(sender.await_args.args[1])


async def test_s28_late_signup_after_same_tab_or_cross_tab_rotation(page: Page, wire: Wire):
    """S28. A confirmed signup cannot replace a key selected during the wait."""
    for cross_tab in (False, True):
        token = await _token(wire)
        if page.url != "about:blank":
            await page.evaluate("sessionStorage.removeItem('dlj-deferred-registration')")
        await page.goto("/#/signup")
        await page.reload()
        await page.get_by_role("button", name="I already have a code").click()
        await page.get_by_label("Confirmation code").fill(token)
        received, release, delivered = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def hold(route: Route) -> None:
            response = await route.fetch()
            assert response.status == 201
            received.set()
            await release.wait()
            await route.fulfill(response=response)
            delivered.set()

        await page.route("**/v1/auth/confirm", hold)
        click = asyncio.create_task(page.get_by_role("button", name="Confirm email").click())
        await asyncio.wait_for(received.wait(), 10)
        chosen = await wire.factory.user(f"chosen-{uuid4().hex}")
        if cross_tab:
            other = await page.context.new_page()
            await other.goto("/#/signup")
            await other.evaluate("key => localStorage.setItem('rgi-api-key', key)", chosen)
            await other.close()
        else:
            await page.evaluate("key => { localStorage.setItem('rgi-api-key', key); window.dispatchEvent(new Event('dlj-key-updated')) }", chosen)
        release.set()
        await asyncio.wait_for(delivered.wait(), 10)
        await click
        await page.unroute("**/v1/auth/confirm", hold)
        await page.wait_for_function("key => localStorage.getItem('rgi-api-key') === key", arg=chosen)
        await expect(page.get_by_label("Your API key")).to_have_count(0)
        assert await page.evaluate("sessionStorage.getItem('dlj-deferred-registration')") is None
        assert await page.evaluate("localStorage.getItem('rgi-api-key')") == chosen


async def test_s29_rotation_between_real_import_chunks_then_restart(page: Page, wire: Wire):
    """S29. The first real batch commits to the old tenant; rotation discards the file."""
    async with wire.factory.sessions.begin() as session:
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.tier, key.subscription_state = "professional", "active"
    csv = "\n".join(["label_id,category,verified_outcome,factor_quality,factor_difficulty,text"] +
                    [f"s29-{n},A,true,0.8,0.2,Sample {n}" for n in range(201)]).encode()
    await page.goto("/#/upload")
    await page.locator('input[type="file"]').set_input_files({"name": "s29.csv", "mimeType": "text/csv", "buffer": csv})
    await expect(page.get_by_text("Analysis ready", exact=False)).to_be_visible(timeout=30000)
    second, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def hold_second(route: Route) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            second.set()
            await release.wait()
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/v1/labels/ingest/batch", hold_second)
    await page.get_by_role("button", name="Start scoring these labels").click()
    await asyncio.wait_for(second.wait(), 30)
    next_key = await wire.factory.user(f"new-{uuid4().hex}")
    await page.evaluate("key => { localStorage.setItem('rgi-api-key', key); window.dispatchEvent(new Event('dlj-key-updated')) }", next_key)
    release.set()
    await expect(page.get_by_role("button", name="Start scoring these labels")).to_have_count(0)
    await expect(page.locator('input[type="file"]')).to_have_value("")
    async with wire.factory.sessions() as fresh:
        old_count = await fresh.scalar(select(func.count()).select_from(LabelLog).where(
            LabelLog.tenant_id == wire.factory.tenant, LabelLog.label_id.like("s29-%")))
        new_count = await fresh.scalar(select(func.count()).select_from(LabelLog).where(
            LabelLog.tenant_id != wire.factory.tenant, LabelLog.label_id.like("s29-%")))
    assert old_count == 100 and new_count == 0
    await page.reload()
    assert await page.evaluate("localStorage.getItem('rgi-api-key')") == next_key
    await expect(page.locator('input[type="file"]')).to_have_value("")
    await expect(page.get_by_role("button", name="Start scoring these labels")).to_have_count(0)


async def test_s30_domain_switch_with_detail_search_bulk_in_flight_duplicated_public_ids(page: Page, wire: Wire):
    """S30. Late detail cannot display in a different project with the same item ID."""
    for alias in ("one", "two"):
        await wire.factory.domain(alias)
        await wire.factory.label("shared-label", alias)
    projects = (await wire.request("GET", "/v1/projects")).json()
    assert len((await wire.request("GET", "/v1/labels/two/pending")).json()) == 1
    first = next(row for row in projects if row["public_domain_id"] == "one")
    second = next(row for row in projects if row["public_domain_id"] == "two")
    paths = {"detail": f"/v1/projects/{first['id']}/labels/items/shared-label",
             "bulk": f"/v1/projects/{second['id']}/labels/bulk-verify",
             "search": f"/v1/projects/{first['id']}/labels/pending"}
    # Delay application delivery only. Each request runs once over the browser's
    # normal HTTP connection, including the committed bulk write. Buffer the real
    # response to exercise a stale completion even if navigation aborts fetch.
    await page.add_init_script("const responsePaths = " + json.dumps(paths) + ";" + """
      const fetchResponse = window.fetch.bind(window);
      window.responseGates = {};
      window.fetch = async (...args) => {
        const response = await fetchResponse(...args);
        const url = new URL(response.url);
        const name = Object.keys(responsePaths).find(key => responsePaths[key] === url.pathname);
        if (!name || window.responseGates[name] ||
            (name === 'search' && url.searchParams.get('search') !== 'no-match')) return response;
        const bytes = await response.arrayBuffer();
        const held = new Response(bytes, {status: response.status, headers: response.headers});
        const data = await held.clone().json();
        await new Promise(release => { window.responseGates[name] = {release, data, status: response.status}; });
        return held;
      };
    """)

    async def wait_for_gate(name: str):
        await page.wait_for_function("name => Boolean(window.responseGates[name])", arg=name)
        result = await page.evaluate("name => window.responseGates[name].data", name)
        assert await page.evaluate("name => window.responseGates[name].status", name) == 200
        return result

    await page.goto(f"/#/projects/{first['id']}/review/shared-label")
    assert (await wait_for_gate("detail"))["label_id"] == "shared-label"
    await page.locator("#project-chooser").select_option(second["id"])
    await page.evaluate("window.responseGates.detail.release()")
    await expect(page).to_have_url(re.compile(f"/projects/{second['id']}/queue"))
    await expect(page.get_by_role("link", name="Review →").first).to_be_visible(timeout=20_000)
    await page.get_by_role("link", name="Review →").first.click()
    await expect(page.get_by_role("heading", name="shared-label")).to_be_visible(timeout=20_000)
    assert await page.evaluate("history.state?.usr ?? null") is None
    await page.get_by_role("link", name="Scored Queue").click()
    await page.get_by_label("Search labels").fill("shared-label")
    await expect(page.get_by_text("1 results", exact=False)).to_be_visible()
    await page.get_by_label("Select shared-label").check()
    await expect(page.get_by_text("1 selected", exact=False)).to_be_visible()
    await page.get_by_label("Bulk known outcome").select_option("correct")
    await page.get_by_role("button", name="Approve All").click()
    assert (await wait_for_gate("bulk"))["processed"] == 1
    await page.locator("#project-chooser").select_option(first["id"])
    await page.evaluate("window.responseGates.bulk.release()")
    await expect(page.get_by_role("link", name="Review →").first).to_be_visible(timeout=20_000)
    await expect(page.get_by_role("region", name="Bulk review actions")).to_have_count(0)
    assert await page.evaluate("history.state?.usr ?? null") is None
    await wire.factory.label("still-pending", "two")
    await page.get_by_label("Search labels").fill("no-match")
    assert await wait_for_gate("search") == []
    # Wait for the destination's actual read before checking the rendered rows.
    # The old search response remains in flight until after the project switch.
    destination = f"/v1/projects/{second['id']}/labels/pending?"
    async with page.expect_response(lambda response: destination in response.url, timeout=45_000) as read:
        try:
            await page.locator("#project-chooser").select_option(second["id"])
        finally:
            await page.evaluate("window.responseGates.search.release()")
    response = await read.value
    assert response.ok and [item["label_id"] for item in await response.json()] == ["still-pending"]
    await expect(page.get_by_label("Search labels")).to_have_value("")
    await expect(page.get_by_label("Select still-pending")).to_be_visible(timeout=20_000)
    for project in (first, second):
        detail = await wire.request("GET", f"/v1/projects/{project['id']}/labels/items/shared-label")
        if project == second:
            assert detail.json()["verified_outcome"] is True
        else:
            assert detail.json()["verified_at"] is None

    other_key = await wire.factory.user(f"second-tenant-{uuid4().hex}")
    created = await wire.request("POST", "/v1/projects", status=201,
        headers={"X-Api-Key": other_key}, json={
            "name": "Other tenant", "public_domain_id": "one", "factors": ["quality", "difficulty"],
            "categories": ["A"], "actions": ["approve", "reject"],
        })
    other_project = created.json()["id"]
    await wire.request("POST", f"/v1/projects/{other_project}/labels/batch",
        headers={"X-Api-Key": other_key}, json={"request_key": "s30-other", "items": [{
            "label_id": "only-other-tenant", "category": "A",
            "factors": {"quality": .8, "difficulty": .2}, "text": "Other tenant text",
        }]})
    await page.evaluate("key => { localStorage.setItem('rgi-api-key', key); window.dispatchEvent(new Event('dlj-key-updated')) }", other_key)
    await page.goto(f"/#/projects/{other_project}/queue")
    await expect(page.get_by_role("link", name="Review →").first).to_be_visible(timeout=20_000)
    assert "only-other-tenant" in await page.locator("main").inner_text()
    assert "shared-label" not in await page.locator("main").inner_text()
    # The old connector credential and its alias still resolve in the old tenant.
    await wire.request("POST", "/v1/label-studio/configure", headers={"X-LS-Token": "harness-ls"},
        json={"project_id": "same-alias", "domain_id": "one",
              "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}})
    await wire.request("POST", "/v1/label-studio/webhook", headers={"X-LS-Token": "harness-ls"},
        json={"project": "same-alias", "action": "ANNOTATION_CREATED",
              "annotation": {"id": "callback", "actual_action": "approve"},
              "task": {"id": "shared-label", "data": {"quality": .8, "difficulty": .2,
                      "category": "A", "ground_truth": True}}})
    new_detail = await wire.request("GET", f"/v1/projects/{other_project}/labels/items/only-other-tenant",
                                    headers={"X-Api-Key": other_key})
    old_detail = await wire.request("GET", f"/v1/projects/{first['id']}/labels/items/shared-label")
    assert new_detail.json()["verified_at"] is None and old_detail.json()["verified_outcome"] is True


async def test_s31_tag_draft_during_category_save_verify_and_navigation(page: Page, wire: Wire):
    """S31. Tag input and category choice remain explicit before verify/navigation."""
    await wire.request("POST", "/v1/labels/demo/items/L1/content", status=201,
                       json={"content_type": "text_multilabel", "tags": ["A"]})
    await page.goto("/#/queue")
    await page.get_by_role("link", name="Review →").first.click()
    tag = page.get_by_role("combobox", name="Add tag")
    await tag.fill("important")
    await tag.press("Enter")
    await tag.fill("next")
    await page.get_by_role("button", name="Save Tags").click()
    await expect(tag).to_have_value("next")
    await tag.fill("preserve this")
    await page.get_by_label("Choose category").select_option("B")
    await page.get_by_label("Known outcome").select_option("correct")
    await expect(page.get_by_role("button", name="Approve recommendation (A)")).to_be_disabled()
    # Capture each actual navigation guard synchronously and choose Stay.
    # Separate one-shot native-dialog listeners can consume the same event.
    await page.evaluate("""() => {
        window.discardPrompts = [];
        window.confirm = message => { window.discardPrompts.push(message); return false };
    }""")
    await page.get_by_role("link", name="Scored Queue").click()
    await page.wait_for_function("window.discardPrompts.length === 1")
    await expect(page).to_have_url(re.compile("/review/"))
    await page.evaluate("history.back()")
    await page.wait_for_function("window.discardPrompts.length === 2")
    assert await page.evaluate("window.discardPrompts") == ["Unsaved changes — discard?"] * 2
    await expect(tag).to_have_value("preserve this")
    started, release = asyncio.Event(), asyncio.Event()

    async def hold_relabel(route: Route):
        result = await route.fetch()
        started.set()
        await asyncio.wait_for(release.wait(), 10)
        await route.fulfill(response=result)

    await page.route("**/relabel", hold_relabel)
    await page.get_by_role("button", name="Relabel").click()
    await asyncio.wait_for(started.wait(), 10)
    await expect(tag).to_be_disabled()
    await expect(page.get_by_role("button", name="Approve recommendation (A)")).to_be_disabled()
    release.set()
    await expect(tag).to_be_enabled()
    await expect(tag).to_have_value("preserve this")


async def test_s32_incompatible_json_and_failed_lazy_chunk(page: Page):
    """S32. Malformed JSON and lazy chunk failures are scoped and recoverable."""
    async def malformed(route: Route) -> None:
        await route.fulfill(status=200, content_type="application/json", body='{"not_a_queue":true}')

    await page.route("**/v1/labels/demo/pending*", malformed)
    await page.goto("/#/queue")
    await expect(page.get_by_role("alert").first).to_contain_text("incompatible queue data")
    await expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()
    await page.unroute("**/v1/labels/demo/pending*", malformed)
    await page.get_by_role("button", name="Refresh").click()
    await expect(page.get_by_role("link", name="Review →").first).to_be_visible()
    async def missing_chunk(route: Route) -> None:
        await route.abort()
    await page.route("**/assets/Dashboard-*.js", missing_chunk)
    await page.goto("/#/dashboard")
    await expect(page.get_by_role("alert").first).to_contain_text("This screen could not be shown")
    await expect(page.get_by_role("navigation", name="Main navigation")).to_be_visible()
    await page.unroute("**/assets/Dashboard-*.js", missing_chunk)
    await page.get_by_role("button", name="Retry").click()
    await expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
