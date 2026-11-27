"""Shared rate limiter for API routes."""

from math import ceil
import logging
from time import time

from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

limiter = Limiter(key_func=get_remote_address)
access_logger = logging.getLogger("uvicorn.error")


class RateLimitHeaders:
    """Apply public intake budgets and report the window that governed the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.public = {
            **{path: parse("1200/minute") for path in (
                "/", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
                "/terms", "/privacy", "/refund", "/attribution", "/dlj_client.py",
            )},
            "/v1/health": parse("120/minute"),
            **{"/v1/label-health/" + path: parse("30/minute") for path in ("analyze", "report", "report/pdf")},
            "/v1/billing/webhook": parse("600/minute"),
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"].rstrip("/") or "/"
        limit = self.public.get(path)
        client = scope.get("client")
        identity = (client[0] if client else "unknown", path)

        async def send_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # Shared caches do not treat a custom API-key header as Authorization.
                if path.startswith("/v1/") and path != "/v1/health":
                    headers.setdefault("Cache-Control", "private, no-store")
                route = getattr(scope.get("route"), "path", None)
                access_logger.info("http_response route=%s status=%d", route or "<unmatched>", message["status"])
                window = scope.get("state", {}).get("view_rate_limit") or ((limit, identity) if limit else None)
                if limiter.enabled and window is not None:
                    item, keys = window
                    reset, remaining = limiter.limiter.get_window_stats(item, *keys)
                    headers["X-RateLimit-Limit"] = str(item.amount)
                    headers["X-RateLimit-Remaining"] = str(remaining)
                    headers["X-RateLimit-Reset"] = str(ceil(reset))
                    if message["status"] == 429:
                        headers.setdefault("Retry-After", str(max(1, ceil(reset - time()))))
            await send(message)

        if limiter.enabled and limit and not limiter.limiter.hit(limit, *identity):
            await JSONResponse({"detail": "Rate limit exceeded"}, 429)(scope, receive, send_headers)
            return
        await self.app(scope, receive, send_headers)
