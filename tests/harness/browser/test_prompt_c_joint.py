"""Prompt B queue against Prompt C's real bulk write adapter."""

import pytest
from playwright.async_api import Page, expect
from sqlalchemy import select

from db.models import LabelLog
from ..fixtures.factory import Wire
from .test_browser_contracts import origin, page


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s27_queue_ui_and_bulk_write_share_explicit_truth(page: Page, wire: Wire):
    await wire.factory.label("L2")
    projects = (await wire.request("GET", "/v1/projects")).json()
    project = next(row for row in projects if row["public_domain_id"] == "demo")
    await page.goto("/#/queue")
    await page.locator("#project-chooser").select_option(project["id"])
    await expect(page.get_by_label("Select L1")).to_be_visible()
    await page.get_by_label("Select L1").check()
    await page.get_by_label("Select L2").check()
    await page.get_by_label("Bulk known outcome").select_option("correct")
    async with page.expect_response(lambda response: response.url.endswith("/bulk-verify") and
                                    response.request.method == "POST") as submission:
        await page.get_by_role("button", name="Approve All").click()
    response = await submission.value
    assert response.status == 200
    assert f"/projects/{project['id']}/labels/bulk-verify" in response.url
    sent = response.request.post_data_json
    assert isinstance(sent, dict)
    assert sent["outcome"] is True and set(sent["label_ids"]) == {"L1", "L2"}
    assert (await response.json())["processed"] == 2
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.label_id.in_(["L1", "L2"])))).all()
        assert len(rows) == 2 and all(row.verified_outcome is True for row in rows)
        assert all(row.verified_by_key_id is not None for row in rows)
    await expect(page.get_by_role("region", name="Bulk review actions")).to_have_count(0)
