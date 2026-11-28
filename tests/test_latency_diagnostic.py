"""Time one real PostgreSQL scoring transaction at ASGI, ORM and driver boundaries."""
import asyncio
import os
import socket
import statistics
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import Response

import billing
import jm_service
import scheduler
from db import connection
from media_intake import MediaIntake
from rate_limit import RateLimitHeaders
from tests.harness.fixtures.pg_schema import database


@dataclass
class Sample:
    marks: dict[str, float] = field(default_factory=dict)
    queries: list[tuple[str, float, float]] = field(default_factory=list)

    def ms(self, start: str, end: str) -> float:
        return (self.marks[end] - self.marks[start]) * 1000


active: ContextVar[Sample | None] = ContextVar("scoring_sample", default=None)


def mark(name: str) -> None:
    sample = active.get()
    if sample is not None:
        sample.marks.setdefault(name, perf_counter())


class AuthInfo(dict):
    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if key == "actor_key_id":
            mark("T3")
        elif key == "project_role":
            mark("project_auth")


class ObservedSession(AsyncSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sync_session.info = AuthInfo(self.sync_session.info)

    async def commit(self):
        mark("commit_entry")
        await super().commit()
        mark("T7")


def instrument(app, engine, monkeypatch, samples):
    stack = app.build_middleware_stack()
    node = stack
    while hasattr(node, "app"):
        inner = node.app
        if isinstance(node, (RateLimitHeaders, MediaIntake)):
            async def boundary(scope, receive, send, inner=inner,
                               name="T1" if isinstance(node, MediaIntake) else "T2"):
                mark(name)
                await inner(scope, receive, send)
            node.app = boundary
        node = inner
    monkeypatch.setattr(app, "middleware_stack", stack)
    original_json = Request.json

    async def read_json(request):
        result = await original_json(request)
        mark("T4")
        return result

    monkeypatch.setattr(Request, "json", read_json)

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_sql(conn, cursor, statement, parameters, context, many):
        if active.get() is not None:
            mark("T5")
            context.scoring_start = perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def after_sql(conn, cursor, statement, parameters, context, many):
        sample = active.get()
        if sample is not None:
            # Log only the command verb. Bind parameters carry private input.
            sample.queries.append((statement.split(None, 1)[0], context.scoring_start, perf_counter()))

    @event.listens_for(engine.sync_engine, "commit")
    def before_driver_commit(conn):
        mark("T6")

    reply = b""

    async def observed_app(scope, receive, send):
        if scope.get("path") == "/__transport_control":
            # Match the successful POST's request and reply sizes on the same socket.
            await Request(scope, receive).body()
            await Response(reply, media_type="application/json")(scope, receive, send)
            return
        if not scope.get("path", "").endswith("/labels/batch"):
            await app(scope, receive, send)
            return
        sample = Sample()
        token = active.set(sample)
        try:
            mark("T0")

            async def observed_send(message):
                nonlocal reply
                if message["type"] == "http.response.start":
                    mark("response_start")
                await send(message)
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    mark("T8")
                    reply = message.get("body", b"")
                    samples.append(sample)

            await app(scope, receive, observed_send)
        finally:
            active.reset(token)

    return observed_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@asynccontextmanager
async def diagnostic_client(app):
    if os.getenv("DLJ_LATENCY_TRANSPORT") != "tcp":
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
        return
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(30):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Uvicorn stopped during startup")
                    await asyncio.sleep(.02)
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}") as client:
                yield client
        finally:
            server.should_exit = True
            await task


@pytest.mark.anyio
async def test_latency_diagnostic(tmp_path, monkeypatch):
    admin = uuid4().hex
    monkeypatch.setenv("ADMIN_API_KEY", admin)
    monkeypatch.setenv("WEBHOOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    samples: list[Sample] = []
    async with database(tmp_path, False, pooled=True) as engine:
        sessions = async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False)
        for module in (connection, scheduler, billing):
            monkeypatch.setattr(module, "AsyncSessionLocal", sessions)
        monkeypatch.setattr(jm_service, "DB_PATH", str(tmp_path / "legacy.db"))
        monkeypatch.setattr(jm_service, "labeling_engine", engine)
        app = instrument(jm_service.app, engine, monkeypatch, samples)
        async with diagnostic_client(app) as client:
            issued = await client.post("/v1/admin/api-keys", headers={"X-Admin-Key": admin},
                                       json={"tenant_id": uuid4().hex, "tenant_name": "Timing"})
            issued.raise_for_status()
            client.headers["X-Api-Key"] = issued.json()["api_key"]
            project = await client.post("/v1/projects", json={
                "name": "Release timing", "public_domain_id": "release-timing", "categories": ["A", "B"],
                "factors": ["quality", "difficulty"], "actions": ["approve", "reject"]})
            project.raise_for_status()
            path = "/v1/projects/" + project.json()["id"]
            for i in range(31):
                started = perf_counter()
                response = await client.post(path + "/labels/batch", json={
                    "request_key": uuid4().hex, "items": [{"label_id": f"score-{i}", "category": "A",
                    "text": "Timing", "factors": {"quality": .8, "difficulty": .2}}]})
                response.raise_for_status()
                samples[-1].marks.update(client_start=started, client_end=perf_counter())
                assert response.json()["batch_size"] == 1
            pending = await client.get(path + "/next-batch")
            assert pending.json()["total_pending"] == 31
            if os.getenv("DLJ_LATENCY_TRANSPORT") == "tcp":
                controls = []
                for _ in range(30):
                    started = perf_counter()
                    control = await client.post("/__transport_control", content=response.request.content,
                                                headers={"Content-Type": "application/json"})
                    controls.append((perf_counter() - started) * 1000)
                    assert control.content == response.content
                print(f"Transport-only POST median={statistics.median(controls):.2f}ms "
                      f"p95={sorted(controls)[28]:.2f}ms")

    assert len(samples) == 31
    samples = samples[1:]  # The release gate also excludes the cold write.
    # Rate middleware encloses media intake. JSON parsing precedes dependency resolution,
    # and the actor lookup is itself the first database operation.
    layers = [
        ("rate_limit (includes outer middleware)", "T0", "T2"),
        ("media_intake", "T2", "T1"), ("body_parse", "T1", "T4"),
        ("pre_db_logic", "T4", "T5"), ("auth (includes actor SQL)", "T5", "T3"),
        ("db_operations (includes project authorization and flush)", "T3", "T6"),
        ("commit", "T6", "T7"), ("post_commit", "T7", "T8"), ("TOTAL", "T0", "T8")]
    print("\nOffset from ASGI entry (ms), T0 T1 T2 T3 T4 T5 T6 T7 T8")
    for i, s in enumerate(samples, 1):
        assert all(s.ms(start, end) >= 0 for _, start, end in layers)
        assert s.marks["T7"] <= s.marks["response_start"] <= s.marks["T8"]
        assert s.queries and s.queries[-1][2] <= s.marks["T6"]
        print(f"{i:02d}", " ".join(f"{s.ms('T0', f'T{j}'):.2f}" for j in range(9)))
    print("LAYER BREAKDOWN (median of 30 writes)")
    for label, start, end in layers:
        print(f"{label}: {statistics.median(s.ms(start, end) for s in samples):.2f}ms")
    print("Project authorization after actor lookup:",
          f"{statistics.median(s.ms('T3', 'project_auth') for s in samples):.2f}ms")
    print("Driver wall time:",
          f"{statistics.median(sum(end - start for _, start, end in s.queries) * 1000 for s in samples):.2f}ms")
    print("Median statements:", statistics.median(len(s.queries) for s in samples))
    print("ASGI p95:", f"{sorted(s.ms('T0', 'T8') for s in samples)[28]:.2f}ms")
    for label, start, end in (("client to ASGI", "client_start", "T0"),
                              ("ASGI to client", "T8", "client_end"),
                              ("HTTP round trip", "client_start", "client_end")):
        durations = sorted(s.ms(start, end) for s in samples)
        print(f"{label}: median={statistics.median(durations):.2f}ms p95={durations[28]:.2f}ms")
