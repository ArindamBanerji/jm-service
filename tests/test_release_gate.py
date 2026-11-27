"""PostgreSQL release contracts. All HTTP calls use the actual application."""
import hashlib
import hmac
import json
import mailbox
import os
import re
from time import monotonic
from datetime import datetime, timezone
from email.message import EmailMessage
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import billing
import email_service
import jm_service
import scheduler
from rate_limit import access_logger
from db import connection, migrate
from db.models import Base
from tests.harness.browser.test_browser_contracts import origin
from tests.harness.fixtures.factory import Factory, Wire
from tests.harness.fixtures.pg_schema import database
from tests.test_img_gate import frame, ingest, project, records, verify

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def wire(tmp_path, monkeypatch):
    async with database(tmp_path, False) as engine:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        for module in (billing, scheduler, connection):
            monkeypatch.setattr(module, "AsyncSessionLocal", sessions)
        monkeypatch.setattr(jm_service, "labeling_engine", engine)
        monkeypatch.setattr(jm_service, "DB_PATH", str(tmp_path / "legacy.db"))
        monkeypatch.setenv("DLJ_IMAGE_PROJECTS_ENABLED", "true")
        factory = Factory(sessions)
        key = await factory.user()
        jm_service.limiter.reset()
        async with jm_service.app.router.lifespan_context(jm_service.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=jm_service.app),
                    base_url="http://release.test", headers={"X-Api-Key": key}) as client:
                yield Wire(client, factory, tmp_path)
        jm_service.limiter.reset()


async def registered(wire, monkeypatch):
    # Deliver real messages into a private disposable mailbox. The signup code
    # still generates, hashes, commits, emails and consumes the one-time proof.
    inbox = mailbox.Maildir(str(wire.directory / "mail"))
    async def deliver(to, subject, html):
        message = EmailMessage()
        message["To"], message["Subject"] = to, subject
        message.set_content(html, subtype="html")
        inbox.add(message)
        return True
    monkeypatch.setattr(email_service, "send_email", deliver)
    address = "launch@example.test"
    result = await wire.request("POST", "/v1/auth/register", omit_api_key=True,
                                json={"email": address}, status=202)
    assert "api_key" not in result.json()
    message, = inbox.values()
    assert message["To"] == address
    token, = re.findall(r"<pre>([0-9a-f]{64})</pre>", message.get_payload(decode=True).decode())
    key = await wire.request("POST", "/v1/auth/confirm", omit_api_key=True,
                             json={"token": token}, status=201)
    wire.client.headers["X-Api-Key"] = key.json()["api_key"]
    assert (await wire.request("GET", "/v1/account")).json()["tenant_id"] == key.json()["tenant_id"]


async def test_signup_to_score_text(wire, monkeypatch):
    await registered(wire, monkeypatch)
    path = await project(wire, "text-launch", "text")
    scored, = await ingest(wire, path, [frame(1, image=False)])
    assert 0 <= scored["confidence"] <= 1
    assert (await wire.request("GET", path + "/sla")).json()["verified_count"] == 0
    await verify(wire, path, "item-1")
    status = (await wire.request("GET", path + "/sla")).json()
    assert (status["verified_count"], status["current_accuracy"], status["gate_status"]) == (1, 100, "inactive")


async def test_signup_to_score_image(wire, monkeypatch):
    await registered(wire, monkeypatch)
    path = await project(wire, "image-launch")
    item = frame(1)
    score, = await ingest(wire, path, [item])
    assert score["recommended_action"] in {"approve", "reject"}
    await verify(wire, path, "item-1")
    record, = await records(wire, path)
    assert record["image_url"] == item["item_media_url"] and record["verified_outcome"] is True


async def test_webhook_hmac_verification(wire, monkeypatch):
    secret = uuid4().hex
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", secret)
    payload = {"event_type": "subscription.created", "event_id": "release-hmac",
               "occurred_at": datetime.now(timezone.utc).isoformat(), "data": {
               "id": "sub_release", "customer_id": "ctm_release", "transaction_id": "txn_release",
               "custom_data": await wire.paddle_intent("professional", "txn_release"),
               "items": [{"product": {"name": "DLJ Professional"}}]}}
    body = json.dumps(payload).encode()
    stamp = str(int(datetime.now(timezone.utc).timestamp()))
    digest = hmac.new(secret.encode(), stamp.encode() + b":" + body, hashlib.sha256).hexdigest()
    for signature, expected in [("0" * 64, 401), (digest, 200)]:
        await wire.request("POST", "/v1/billing/webhook", content=body, omit_api_key=True, status=expected,
                           headers={"Content-Type": "application/json", "Paddle-Signature": f"ts={stamp};h1={signature}"})
        account = (await wire.request("GET", "/v1/account")).json()
        assert account["tier"] == ("professional" if expected == 200 else "trial")


async def test_rate_limiting_enforced(wire):
    path = await project(wire, "quota", "text")
    await ingest(wire, path, [frame(i, image=False) for i in range(50)])
    await wire.request("POST", path + "/labels/batch", status=429, json={
        "request_key": uuid4().hex, "items": [frame(50, image=False)]})
    assert (await wire.request("GET", path + "/next-batch")).json()["total_pending"] == 50
    assert (await wire.request("GET", "/v1/account")).json()["usage"]["labels_today"] == 50


async def test_export_streaming_not_buffered(wire, origin):
    path = await project(wire, "stream", "text")
    items = [{**frame(i, image=False), "text": str(i) + "x" * 3000} for i in range(50)]
    await ingest(wire, path, items)
    async with httpx.AsyncClient(base_url=origin, headers=wire.client.headers) as client:
        async with client.stream("GET", path + "/export") as response:
            response.raise_for_status()
            assert response.headers["transfer-encoding"] == "chunked"
            rows = [json.loads(line) async for line in response.aiter_lines()]
    assert {r["current_label_id"]: r["text"] for r in rows} == {i["label_id"]: i["text"] for i in items}


async def test_migration_fresh_database(tmp_path, monkeypatch):
    async with database(tmp_path, False, initialize=False) as engine:
        monkeypatch.setattr(migrate, "engine", engine)
        await migrate.migrate()
        def schema(conn):
            view = inspect(conn)
            assert set(Base.metadata.tables) <= set(view.get_table_names())
            for name, table in Base.metadata.tables.items():
                assert view.get_pk_constraint(name)["constrained_columns"] == list(table.primary_key.columns.keys())
                checks = {check["name"] for check in view.get_check_constraints(name)}
                uniques = {tuple(key["column_names"]) for key in view.get_unique_constraints(name)}
                indexes = {index["name"] for index in view.get_indexes(name)}
                assert {index.name for index in table.indexes} <= indexes, name
                for constraint in table.constraints:
                    if isinstance(constraint, CheckConstraint) and constraint.name:
                        assert constraint.name in checks, (name, constraint.name)
                    if isinstance(constraint, UniqueConstraint):
                        assert tuple(constraint.columns.keys()) in uniques, name
                actual = {(tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in view.get_foreign_keys(name)}
                assert all((tuple(fk.column_keys), fk.referred_table.name) in actual for fk in table.foreign_key_constraints)
            index, = [i for i in view.get_indexes("label_log") if i["name"] == "uq_revision_predecessor"]
            assert index["unique"] and index["dialect_options"]["postgresql_where"]
        async with engine.connect() as conn:
            await conn.run_sync(schema)


async def test_migration_repeat_safe(tmp_path, monkeypatch):
    async with database(tmp_path, False, initialize=False) as engine:
        monkeypatch.setattr(migrate, "engine", engine)
        await migrate.migrate()
        factory = Factory(async_sessionmaker(engine, expire_on_commit=False))
        await factory.user()
        await factory.domain()
        await migrate.migrate()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM api_keys")) == 1
            assert await conn.scalar(text("SELECT public_domain_id FROM domains")) == "demo"


async def test_billing_checkout_url_generation(wire, monkeypatch):
    # Live acceptance uses a sandbox-only transaction and independently reads
    # its price from Paddle. Checkout links are opaque transaction links.
    if os.getenv("DLJ_TEST_PADDLE_CHECKOUT") == "1":
        assert billing.paddle_transaction_url() == "https://sandbox-api.paddle.com/transactions"
        price = billing.paddle_prices()["starter"]
        checkout = (await wire.request("GET", "/v1/billing/checkout-url?tier=starter")).json()
        assert checkout["checkout_url"].startswith("https://")
        async with wire.factory.sessions() as session:
            transaction = await session.scalar(text("SELECT transaction_id FROM checkout_intent"))
        assert transaction and transaction in checkout["checkout_url"]
        async with httpx.AsyncClient() as client:
            receipt = await client.get(billing.paddle_transaction_url() + "/" + transaction,
                                       headers={"Authorization": "Bearer " + os.environ["PADDLE_API_KEY"]})
            receipt.raise_for_status()
        assert receipt.json()["data"]["items"][0]["price"]["id"] == price
        return
    monkeypatch.setenv("PADDLE_PRICE_MAP", " starter = pri_release1 , professional=pri_release2")
    monkeypatch.setenv("PADDLE_SANDBOX", "true")
    assert billing.paddle_prices()["starter"] == "pri_release1"
    assert billing.paddle_transaction_url() == "https://sandbox-api.paddle.com/transactions"
    await wire.request("GET", "/v1/billing/checkout-url?tier=unlisted", status=400)
    monkeypatch.setenv("PADDLE_SANDBOX", "tru")
    await wire.request("GET", "/v1/billing/checkout-url?tier=starter", status=503)
    async with wire.factory.sessions() as session:
        assert await session.scalar(text("SELECT count(*) FROM checkout_intent")) == 0


async def test_guide_page_accessible(wire):
    result = await wire.request("GET", "/#/docs", omit_api_key=True)
    assert result.headers["content-type"].startswith("text/html")
    script, = re.findall(r'<script[^>]+src="([^"]+\.js)"', result.text)
    assert (await wire.request("GET", script, omit_api_key=True)).content


async def test_export_roles_in_project_list(wire):
    path = await project(wire, "roles", "text")
    assert (await wire.request("GET", "/v1/projects")).json()[0]["role"] == "owner"
    key = await wire.factory.user("release-annotator")
    await wire.request("POST", path + "/members", status=201,
                       json={"member_tenant_id": "release-annotator", "role": "annotator"})
    headers = {"X-Api-Key": key}
    summary, = (await wire.request("GET", "/v1/projects", headers=headers)).json()
    assert summary["id"] == path.rsplit("/", 1)[1] and summary["role"] == "annotator"
    await wire.request("GET", path + "/export", status=403, headers=headers)


async def test_account_domains_pages_are_bounded_and_isolated(wire):
    first = await project(wire, "first", "text")
    second = await project(wire, "second", "text")
    page = await wire.request("GET", "/v1/account/domains?limit=1")
    assert [row["id"] for row in page.json()] == [first.rsplit("/", 1)[1]]
    assert page.headers["X-Next-Offset"] == "1"
    last = await wire.request("GET", "/v1/account/domains?limit=1&offset=1")
    assert [row["id"] for row in last.json()] == [second.rsplit("/", 1)[1]]
    assert "X-Next-Offset" not in last.headers
    other = await wire.factory.user("release-separate")
    assert (await wire.request("GET", "/v1/account/domains", headers={"X-Api-Key": other})).json() == []
    await wire.request("GET", "/v1/account/domains?limit=201", status=422)


async def test_scoring_minute_limit(wire):
    legacy = (await wire.request("POST", "/v1/register", json={"name": "release"})).json()["api_key"]
    headers = {"X-Api-Key": legacy}
    config = {"name": "Release rate", "factors": ["quality", "difficulty"], "categories": ["A"],
              "actions": ["approve", "reject"]}
    result = await wire.request("POST", "/v1/domains", headers=headers, json=config, status=201)
    path = "/v1/domains/" + result.json()["domain_id"] + "/score"
    ids = set()
    for _ in range(30):
        result = await wire.request("POST", path, headers=headers, json={"category": "A", "factors": {"quality": .7, "difficulty": .2}})
        ids.add(result.json()["decision_id"])
    assert len(ids) == 30
    refused = await wire.request("POST", path, headers=headers, status=429, json={"category": "A", "factors": {"quality": .7, "difficulty": .2}})
    assert int(refused.headers["retry-after"]) > 0


async def test_health_endpoint_reports_status(wire):
    result = await wire.request("GET", "/v1/health", omit_api_key=True)
    assert result.json()["status"] == "healthy"
    assert result.json()["checks"] == {"legacy_db": "connected", "labeling_db": "connected", "engine_hash": "verified"}


async def test_access_log_uses_route_template(wire, caplog):
    path = await project(wire, "private-project", "text")
    # A Uvicorn server in an earlier test may own the parent logger's handlers.
    access_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("INFO", logger=access_logger.name):
            await wire.request("GET", path + "/next-batch?search=private-review-text")
    finally:
        access_logger.removeHandler(caplog.handler)
    entries = [entry.getMessage() for entry in caplog.records if entry.name == "uvicorn.error"]
    assert any("/next-batch status=200" in entry for entry in entries)
    assert all("private-review-text" not in entry and path.rsplit("/", 1)[1] not in entry for entry in entries)


async def test_health_reports_pool_saturation_before_container_timeout(wire, monkeypatch):
    engine = create_async_engine(jm_service.labeling_engine.url, pool_size=1, max_overflow=0, pool_timeout=10)
    try:
        async with engine.connect():
            monkeypatch.setattr(jm_service, "labeling_engine", engine)
            started = monotonic()
            response = await wire.request("GET", "/v1/health", status=503, omit_api_key=True)
            assert monotonic() - started < 3
            assert response.json()["checks"]["labeling_db"] == "error: TimeoutError"
        assert (await wire.request("GET", "/v1/health")).json()["status"] == "healthy"
    finally:
        await engine.dispose()


async def test_production_preflight_validates_advertised_prices(wire, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    for name in ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    from cryptography.fernet import Fernet
    for name in ("DATABASE_URL", "ADMIN_API_KEY", "RESEND_API_KEY", "PADDLE_API_KEY", "PADDLE_WEBHOOK_SECRET"):
        monkeypatch.setenv(name, "fixture")
    monkeypatch.setenv("WEBHOOK_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("PADDLE_SANDBOX", "true")
    monkeypatch.setenv("PADDLE_PRICE_MAP", "starter=pri_release")
    with pytest.raises(RuntimeError, match="Missing checkout tiers"):
        jm_service.validate_production_config()
    monkeypatch.setenv("PADDLE_PRICE_MAP", ",".join(t + "=pri_" + t for t in ("starter", "professional", "business", "scale")))
    jm_service.validate_production_config()
