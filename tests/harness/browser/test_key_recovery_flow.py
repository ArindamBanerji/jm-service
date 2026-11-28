"""A returning customer recovers through the real signup form and PostgreSQL API."""
import asyncio
import re
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright, expect

from ..fixtures.factory import Wire
from ..test_key_recovery import mail, signup
from .test_browser_contracts import origin

pytestmark = pytest.mark.anyio


async def test_returning_owner_recovers_from_signup_in_browser(wire: Wire, origin: str, mail: AsyncMock):
    email = "returning@example.test"
    original = await signup(wire, email)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            tab = await browser.new_page()
            await tab.goto(origin + "/#/signup")
            await tab.get_by_label("Email", exact=True).fill(email)
            await tab.get_by_role("button", name="Start Free Trial").click()
            await expect(tab.get_by_role("heading", name="Recover your API key")).to_be_visible()
            await tab.get_by_role("button", name="Recover your key").click()
            code = tab.get_by_label("Recovery code")
            await expect(code).to_be_visible()
            assert await asyncio.to_thread(mail.wait_received.wait, 10)
            assert mail.await_args and mail.await_args.args[0] == email
            token = re.search(r"<pre>([0-9a-f]{64})</pre>", mail.await_args.args[2])
            assert token
            await code.fill(token[1])
            await tab.get_by_role("button", name="Replace API key").click()
            field = tab.get_by_label("Your API key", exact=True)
            await expect(field).to_be_visible()
            replacement = await field.input_value()
            await tab.reload()
            assert await tab.evaluate("localStorage.getItem('rgi-api-key')") == replacement
            await wire.request("GET", "/v1/projects", headers={"X-Api-Key": replacement})
            await wire.request("GET", "/v1/projects", status=401, headers={"X-Api-Key": original["api_key"]})
        finally:
            await browser.close()
