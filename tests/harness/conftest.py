from collections.abc import AsyncIterator
import asyncio
from pathlib import Path
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.types import Message, Receive, Scope, Send

import auth
import billing
import jm_service
import scheduler
from db import connection
from .fixtures.factory import Factory, Wire
from .fixtures.pg_schema import database


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    if sys.platform == "win32":
        # asyncpg's teardown can raise a late Proactor socket reset; Playwright
        # subprocesses require Proactor. Choose per test before async fixtures.
        policy = (asyncio.WindowsProactorEventLoopPolicy if "browser" in item.path.parts
                  else asyncio.WindowsSelectorEventLoopPolicy)
        asyncio.set_event_loop_policy(policy())


def pytest_addoption(parser):
    parser.addoption("--harness-sqlite", action="store_true", help="Run advisory SQLite compatibility lane")


def pytest_configure(config):
    for owner in "abc":
        config.addinivalue_line("markers", f"prompt_{owner}: owned by Prompt {owner.upper()}")
    config.addinivalue_line("markers", "sqlite_advisory: selected SQLite compatibility run")
    config.addinivalue_line("markers", "sqlite_divergence(reason): documented dialect-specific assertion")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--harness-sqlite", default=False):
        for item in items:
            if Path(__file__).parent in item.path.parents:
                item.add_marker(pytest.mark.sqlite_advisory)
                divergence = item.get_closest_marker("sqlite_divergence")
                if divergence:
                    item.add_marker(pytest.mark.xfail(reason=divergence.args[0], strict=True, raises=AssertionError))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db_engine(tmp_path, pytestconfig) -> AsyncIterator[AsyncEngine]:
    async with database(tmp_path, pytestconfig.getoption("--harness-sqlite", default=False)) as engine:
        yield engine


@pytest.fixture
async def factory(db_engine):
    return Factory(async_sessionmaker(db_engine, expire_on_commit=False))


@pytest.fixture
async def wire(factory, db_engine, tmp_path, monkeypatch) -> AsyncIterator[Wire]:
    # Keep the production dependency and its cleanup. Redirect only its backing store.
    for module in (connection, billing, scheduler):
        monkeypatch.setattr(module, "AsyncSessionLocal", factory.sessions)
    monkeypatch.setattr(jm_service, "labeling_engine", db_engine)
    monkeypatch.setattr(jm_service, "DB_PATH", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(auth, "send_signup_challenge_email", AsyncMock(return_value=True))
    for name, value in {
        "ADMIN_API_KEY": "harness-admin", "LABEL_STUDIO_TOKEN": "harness-ls",
        "LABEL_STUDIO_TENANT_ID": factory.tenant, "LABEL_STUDIO_DOMAIN_ID": "studio",
        "LS_CONFIG_PATH": str(tmp_path / "connector.json"), "PADDLE_SANDBOX": "true",
        "PADDLE_WEBHOOK_SECRET": "", "LS_FACTOR_MAP": '{"quality":"data.quality","difficulty":"data.difficulty"}',
    }.items():
        monkeypatch.setenv(name, value)
    key = await factory.user()
    app = jm_service.app

    async def observed(scope: Scope, receive: Receive, send: Send) -> None:
        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400:
                request_id = dict(scope["headers"]).get(b"x-harness-request-id")
                if request_id is not None:
                    await harness.observe(request_id.decode())
            await send(message)
        await app(scope, receive, capture)

    jm_service.limiter.reset()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=observed),
                                     base_url="http://harness.test", headers={"X-Api-Key": key}) as client:
            harness = Wire(client, factory, tmp_path)
            yield harness
    jm_service.limiter.reset()
