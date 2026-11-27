"""Real single-worker service on an isolated PostgreSQL schema for release journeys and latency."""
import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import httpx
import uvicorn
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

import billing
import jm_service
import scheduler
from db import connection
from tests.harness.fixtures.factory import Factory
from tests.harness.fixtures.pg_schema import database


async def measure(url: str, key: str) -> None:
    async with httpx.AsyncClient(base_url=url, headers={"X-Api-Key": key}) as client:
        project = await client.post("/v1/projects", json={
            "name": "Release timing", "public_domain_id": "release-timing", "categories": ["A", "B"],
            "factors": ["quality", "difficulty"], "actions": ["approve", "reject"]})
        project.raise_for_status()
        path = "/v1/projects/" + project.json()["id"]
        samples = []
        for i in range(31):
            started = perf_counter()
            response = await client.post(path + "/labels/batch", json={"request_key": uuid4().hex,
                "items": [{"label_id": f"score-{i}", "category": "A", "text": "Timing",
                           "factors": {"quality": .8, "difficulty": .2}}]})
            elapsed = (perf_counter() - started) * 1000
            response.raise_for_status()
            assert response.json()["batch_size"] == 1
            if i:
                samples.append(elapsed)
        pending = await client.get(path + "/next-batch")
        assert pending.json()["total_pending"] == 31
        median, p95 = statistics.median(samples), sorted(samples)[28]
        print(f"30 committed scoring writes over HTTP: median={median:.2f}ms p95={p95:.2f}ms", flush=True)
        assert median < 50 and p95 < 100, "Release latency budget exceeded"


async def serve(directory: Path) -> None:
    async with database(directory, False, pooled=True) as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        connection.AsyncSessionLocal = billing.AsyncSessionLocal = scheduler.AsyncSessionLocal = sessions
        jm_service.labeling_engine = engine
        jm_service.DB_PATH = str(directory / "legacy.db")
        os.environ["WEBHOOK_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        key = await Factory(sessions).user()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            server = uvicorn.Server(uvicorn.Config(jm_service.app, log_level="error"))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Release fixture startup failed")
                    await asyncio.sleep(.02)
                if "--measure" in sys.argv:
                    await measure(url, key)
                elif "--playwright" in sys.argv:
                    env = {**os.environ, "DLJ_PORT": str(listener.getsockname()[1])}
                    command = [
                        "node", "node_modules/@playwright/test/cli.js", "test", "--reporter=list",
                        *sys.argv[sys.argv.index("--playwright") + 1:]]
                    await asyncio.to_thread(lambda: subprocess.run(command, env=env, check=True))
                else:
                    print(json.dumps({"url": url, "key": key}), flush=True)
                    await asyncio.to_thread(sys.stdin.readline)
            finally:
                server.should_exit = True
                await task


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with tempfile.TemporaryDirectory() as root:
        asyncio.run(serve(Path(root)))
