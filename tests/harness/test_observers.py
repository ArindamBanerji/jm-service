"""The response-start witness belongs to one request, even during overlap."""
import asyncio
from pathlib import Path

import httpx
import pytest

from .fixtures.factory import Wire

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("second_observed", [False, True])
async def test_overlapping_observers(second_observed):
    first_waiting = asyncio.Event()
    resume_first = asyncio.Event()
    calls = {"first": 0, "second": 0}
    wire: Wire

    async def app(scope, receive, send):
        if scope["path"] == "/first":
            first_waiting.set()
            await resume_first.wait()
        request_id = dict(scope["headers"]).get(b"x-harness-request-id")
        if request_id is not None:
            await wire.observe(request_id.decode())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def first_observer():
        calls["first"] += 1

    async def second_observer():
        calls["second"] += 1

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://harness.test") as client:
        wire = Wire(client, None, Path("."))
        first = asyncio.create_task(wire.request("POST", "/first", before_send=first_observer))
        await first_waiting.wait()
        try:
            await wire.request("POST", "/second",
                               before_send=second_observer if second_observed else None)
        finally:
            resume_first.set()
        await first
    assert calls == {"first": 1, "second": int(second_observed)}
    assert wire.observers == {}


async def test_write_without_response_start_observation_fails():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def committed():
        raise AssertionError("The observer should never run")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://harness.test") as client:
        wire = Wire(client, None, Path("."))
        with pytest.raises(AssertionError, match="Missing ASGI response-start observation"):
            await wire.request("POST", "/late", before_send=committed)
        assert wire.observers == {}
