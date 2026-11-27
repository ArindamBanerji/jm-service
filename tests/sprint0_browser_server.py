"""Disposable PostgreSQL app for the Sprint 0 browser journeys. EOF shuts it down."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import AsyncMock

import httpx
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker
import uvicorn

import billing
import jm_service
import scheduler
import webhook_router
from db import connection
from tests.harness.contracts.test_predictions import project, seed_autonomous_project
from tests.harness.fixtures.factory import Factory, Wire
from tests.harness.fixtures.pg_schema import database


async def serve(directory: Path) -> None:
    async with database(directory, False, pooled=True) as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        connection.AsyncSessionLocal = billing.AsyncSessionLocal = scheduler.AsyncSessionLocal = sessions
        jm_service.labeling_engine = engine
        jm_service.DB_PATH = str(directory / "legacy.db")
        factory = Factory(sessions)
        key = await factory.user()
        os.environ["WEBHOOK_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        # Only external destination resolution and network delivery are substituted.
        webhook_router.validate_public_https = AsyncMock(return_value="192.0.2.1")
        scheduler._send_webhook = AsyncMock(return_value=scheduler.DeliveryResult(204, None))

        async def dispatch() -> None:
            while True:
                await scheduler.dispatch_webhooks_once()
                await asyncio.sleep(.15)

        jm_service.scheduler_loop = dispatch
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=jm_service.app),
                                     base_url="http://fixture", headers={"X-Api-Key": key}) as client:
            wire = Wire(client, factory, directory)
            autonomous = await project(wire)
            await seed_autonomous_project(wire, autonomous)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(jm_service.app, log_level="error"))
            task = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Browser fixture exited before startup")
                    await asyncio.sleep(.02)
                print(json.dumps({"url": f"http://127.0.0.1:{sock.getsockname()[1]}",
                                  "key": key, "autonomous": autonomous}), flush=True)
                await asyncio.to_thread(sys.stdin.readline)
            finally:
                server.should_exit = True
                await task


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with tempfile.TemporaryDirectory() as directory:
        asyncio.run(serve(Path(directory)))
