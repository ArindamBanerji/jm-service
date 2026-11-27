"""Bound media JSON before FastAPI buffers it for validation and authentication."""
from __future__ import annotations

import asyncio
import re
from contextlib import ExitStack

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MIB = 1024 * 1024
MAX_BODY = 20 * MIB
INTAKE_SECONDS = 30
_MEDIA_ROUTE = re.compile(
    r"/v1/(?:projects/[^/]+/(?:predictions(?:/[^/]+/review)?|labels(?:/batch|/items/[^/]+/(?:content|relabel))?)"
    r"|labels/(?:ingest(?:/batch)?|[^/]+/items/[^/]+/(?:content|relabel))"
    r"|label-studio/(?:predict|webhook))/?"
)


class MediaIntake:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.slots = asyncio.BoundedSemaphore(2)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] != "http" or scope["method"] != "POST"
                or not _MEDIA_ROUTE.fullmatch(scope["path"])):
            await self.app(scope, receive, send)
            return

        async def reject(status: int, message: str) -> None:
            headers = {"Retry-After": "1"} if status == 429 else None
            await JSONResponse({"detail": message}, status, headers)(scope, receive, send)

        headers = Headers(scope=scope)
        if any(value.strip().lower() != "identity" for value in headers.getlist("content-encoding")):
            await reject(415, "Unsupported request content encoding")
            return
        lengths = headers.getlist("content-length")
        if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0])):
            await reject(400, "Invalid Content-Length")
            return
        digits = (lengths[0].lstrip("0") or "0") if lengths else None
        if digits is not None and (len(digits) > len(str(MAX_BODY)) or int(digits) > MAX_BODY):
            await reject(413, "Media request exceeds 20 MiB")
            return

        with ExitStack() as permits:
            reserved = False

            async def reserve() -> bool:
                nonlocal reserved
                if self.slots.locked():
                    await reject(429, "Media intake is busy")
                    return False
                await self.slots.acquire()
                permits.callback(self.slots.release)
                reserved = True
                return True

            body = bytearray()
            deadline = asyncio.get_running_loop().time() + INTAKE_SECONDS
            if (digits is None or int(digits) > MIB) and not await reserve():
                return
            while True:
                try:
                    async with asyncio.timeout_at(deadline):
                        message = await receive()
                except TimeoutError:
                    await reject(408, "Media upload timed out")
                    return
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size = len(body) + len(chunk)
                if size > MAX_BODY:
                    await reject(413, "Media request exceeds 20 MiB")
                    return
                if size > MIB and not reserved and not await reserve():
                    return
                if not message.get("more_body", False):
                    if body:
                        body.extend(chunk)
                        buffered = bytes(body)
                        body.clear()
                    else:
                        buffered = chunk
                    break
                body.extend(chunk)

            del message, chunk
            delivered = False
            async def replay() -> Message:
                nonlocal delivered, buffered
                if delivered:
                    return await receive()
                delivered = True
                data, buffered = buffered, b""
                return {"type": "http.request", "body": data, "more_body": False}

            await self.app(scope, replay, send)
