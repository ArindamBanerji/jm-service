import asyncio
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import os
from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from httpx import ASGITransport, AsyncClient
from db import connection

from db import repository
from db.models import (ApiKey, ConnectorConfigRow, Domain, Engine, LabelContent,
                       LabelLog, WebhookEvent)
from auth import scoped_domain_id
from label_studio import _config
from ..fixtures.factory import Wire


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s20_http_and_connector_verification_on_an_older_reviewer_engine(wire: Wire):
    """S20. HTTP and connector verification on an older reviewer engine."""
    scoped = await wire.factory.domain()
    async with wire.factory.sessions.begin() as seed:
        domain = await seed.scalar(select(Domain).where(Domain.domain_id == scoped))
        assert domain is not None
        domain.config_json = {**domain.config_json, "categories": ["A"]}
    await wire.request("POST", "/v1/label-studio/configure", headers={"X-LS-Token": "harness-ls"},
                       json={"project_id": "p", "domain_id": "demo",
                             "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}})
    await wire.request("POST", "/v1/labels/ingest", json={"domain_id": "demo", "label_id": "old",
                       "category": "A", "factors": {"quality": .8, "difficulty": .2}})
    await wire.request("POST", "/v1/labels/verify", json={"domain_id": "demo", "label_id": "old",
                       "actual_action": "approve", "verified_outcome": True,
                       "annotator_id": "reviewer"})
    await wire.request("POST", "/v1/labels/ingest", json={"domain_id": "demo", "label_id": "new",
                       "category": "B", "factors": {"quality": .8, "difficulty": .2}})
    await wire.request("POST", "/v1/label-studio/webhook", headers={"X-LS-Token": "harness-ls"},
                       json={"project": "p", "action": "ANNOTATION_CREATED",
                             "task": {"id": "connector-b", "data": {"category": "B", "quality": .8,
                                                                     "difficulty": .2, "ground_truth": True}},
                             "annotation": {"id": "b-1", "completed_by": "reviewer",
                                            "actual_action": "approve"}})
    async with wire.factory.sessions() as fresh:
        engine = await fresh.scalar(select(Engine).where(Engine.domain_id == scoped,
                                                       Engine.annotator_id == "reviewer"))
        assert engine is not None
        assert "B" in engine.state_json["config"]["categories"]
        assert engine.state_json["conservation"]["total_verified"] == 2
        verified = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped,
                                                               LabelLog.verified_at.is_not(None)))).all()
        assert len(verified) == 2
        assert all(row.verified_by_key_id is not None for row in verified)


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s21_connector_and_http_revision_of_structured_data(wire: Wire):
    """S21. Connector and HTTP revision of structured data."""
    await wire.factory.domain()
    await wire.factory.label("structured")
    await wire.request("POST", "/v1/labels/demo/items/structured/content", status=201,
                       json={"content_type": "text_ner", "spans": [
                           {"start": 0, "end": 6, "label": "A", "text": "Sample"}]})
    await wire.request("POST", "/v1/label-studio/configure", headers={"X-LS-Token": "harness-ls"},
                       json={"project_id": "p", "domain_id": "demo",
                             "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}})

    async def deliver(action: str, stamp: str, task_id: str = "structured", status: int = 200,
                      truth: bool = True, spans: list[dict] | None = None):
        return await wire.request("POST", "/v1/label-studio/webhook", status=status,
                                  headers={"X-LS-Token": "harness-ls"}, json={
                                      "project": "p", "action": "ANNOTATION_UPDATED",
                                      "task": {"id": task_id, "data": {"category": "A", "quality": .8,
                                                                           "difficulty": .2, "ground_truth": truth}},
                                          "annotation": {"id": "structured-ann", "completed_by": "reviewer",
                                                         "actual_action": action, "updated_at": stamp,
                                                         **({"result": [{"value": {
                                                             "start": span["start"], "end": span["end"],
                                                             "labels": [span["label"]], "text": span["text"]}}
                                                             for span in spans]} if spans is not None else {})}})

    initial_spans = [{"start": 7, "end": 11, "label": "B", "text": "text"}]
    await deliver("approve", "2026-11-25T10:00:00Z", spans=initial_spans)
    first_detail = await wire.request("GET", "/v1/labels/demo/items/structured")
    assert first_detail.json()["content"]["spans"] == initial_spans
    corrected_spans = [{"start": 7, "end": 11, "label": "A", "text": "text"}]
    await deliver("reject", "2026-11-25T11:00:00Z", truth=False, spans=corrected_spans)
    replay = await deliver("reject", "2026-11-25T11:00:00Z", truth=False, spans=corrected_spans)
    assert replay.json()["status"] == "processed"
    await deliver("reject", "2026-11-25T12:00:00Z", task_id="wrong-task", status=409,
                  truth=False)
    await deliver("reject", "2026-11-25T09:00:00Z", task_id="wrong-task", status=409,
                  truth=False)
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    async with wire.factory.sessions() as fresh:
        first = await fresh.scalar(select(LabelLog).where(LabelLog.domain_id == scoped,
                                                          LabelLog.label_id == "structured"))
        assert first is not None and first.superseded_by is not None
        connector_revision = await fresh.scalar(select(LabelLog).where(
            LabelLog.domain_id == scoped, LabelLog.label_id == first.superseded_by))
        assert connector_revision is not None
        copied = await fresh.scalar(select(LabelContent).where(
            LabelContent.label_log_id == connector_revision.id))
        assert copied is not None and copied.spans_json[0]["text"] == "text"
        assert connector_revision.prior_revision_id == str(first.id)
        assert connector_revision.source_task_id == "structured"
        assert connector_revision.verified_by_key_id is not None
        assert connector_revision.revision_by_key_id is not None
        connector_events = (await fresh.scalars(select(WebhookEvent).where(
            WebhookEvent.event_type == "label.verified"))).all()
        assert len(connector_events) == 2
        connector_id = connector_revision.label_id
        token = str(connector_revision.id)
    http_revision = await wire.request("POST", f"/v1/labels/demo/items/{connector_id}/relabel",
                                       json={"category": "B", "idempotency_token": token,
                                             "spans": [{"start": 0, "end": 6, "label": "B",
                                                        "text": "Sample"}]})
    async with wire.factory.sessions() as fresh:
        latest = await fresh.get(LabelLog, UUID(http_revision.json()["revision_id"]))
        assert latest is not None and latest.prior_revision_id == token
        assert latest.source_task_id == "structured" and latest.revision_by_key_id is not None
        assert latest.source_updated_at == connector_revision.source_updated_at
        assert latest.annotation_id == "p:structured-ann" and latest.text == "Sample text"
        content = await fresh.scalar(select(LabelContent).where(LabelContent.label_log_id == latest.id))
        assert content is not None and content.spans_json[0]["text"] == "Sample"


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s22_two_first_domain_engine_writes(wire: Wire):
    """S22. Two first-domain/engine writes."""
    start = asyncio.Barrier(2)

    async def create():
        await start.wait()
        return await wire.client.post("/v1/projects", json={
            "name": "Race", "public_domain_id": "race", "factors": ["quality", "difficulty"],
            "categories": ["A"]})

    tasks = [asyncio.create_task(create()) for _ in range(2)]
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    assert sorted(response.status_code for response in results) == [201, 409]
    scoped = scoped_domain_id(wire.factory.tenant, "race")
    async with wire.factory.sessions() as fresh:
        domains = (await fresh.scalars(select(Domain).where(Domain.domain_id == scoped))).all()
        assert len(domains) == 1
        assert domains[0].config_json["categories"] == ["A"]
    start = asyncio.Barrier(2)

    async def first_score(label_id: str):
        await start.wait()
        return await wire.client.post("/v1/labels/ingest", json={
            "domain_id": "race", "label_id": label_id, "category": "A",
            "factors": {"quality": .8, "difficulty": .2}})

    tasks = [asyncio.create_task(first_score(label_id)) for label_id in ("first", "second")]
    scored = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    assert all(response.status_code in {200, 409} for response in scored)
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped))).all()
        assert len(rows) == sum(response.status_code == 200 for response in scored)
        engines = (await fresh.scalars(select(Engine).where(Engine.domain_id == scoped,
                                                     Engine.annotator_id.is_(None)))).all()
        assert len(engines) == 1


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s23_concurrent_reservations_at_49_plus_two_requests(wire: Wire):
    """S23. Concurrent reservations at 49 plus two requests."""
    await wire.factory.domain()
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    async with wire.factory.sessions.begin() as seed:
        seed.info["tenant_id"] = wire.factory.tenant
        engine = await repository.load_or_create_engine(seed, scoped)
        for index in range(49):
            await repository.score_and_persist(seed, engine, scoped, f"prior-{index}", None,
                                               "A", {"quality": .8, "difficulty": .2})
    async with wire.factory.sessions.begin() as seed:
        key = await seed.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None
        key.labels_today = 49
        key.labels_day_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key.labels_this_month = 49
        key.labels_month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    start = asyncio.Barrier(2)

    async def score(label_id: str):
        await start.wait()
        return await wire.client.post("/v1/labels/ingest", json={
            "domain_id": "demo", "label_id": label_id, "category": "A",
            "factors": {"quality": .8, "difficulty": .2}})

    tasks = [asyncio.create_task(score(label_id)) for label_id in ("fiftieth", "fifty-first")]
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    assert sorted(response.status_code for response in results) == [200, 429]
    async with wire.factory.sessions() as fresh:
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and (key.labels_today, key.labels_this_month) == (50, 50)
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped))).all()
        assert len(rows) == 50 and all(row.scored_at is not None for row in rows)


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s24_two_relabels_plus_verify_on_one_predecessor(wire: Wire):
    """S24. Two relabels plus verify on one predecessor."""
    await wire.factory.domain()
    await wire.factory.label("race-label")
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    async with wire.factory.sessions() as fresh:
        original = await fresh.scalar(select(LabelLog).where(LabelLog.domain_id == scoped,
                                                              LabelLog.label_id == "race-label"))
        assert original is not None
        token = str(original.id)
    start = asyncio.Barrier(3)

    async def relabel():
        await start.wait()
        return await wire.client.post("/v1/labels/demo/items/race-label/relabel", json={
            "category": "B", "idempotency_token": token})

    async def adjudicate():
        await start.wait()
        return await wire.client.post("/v1/labels/verify", json={
            "domain_id": "demo", "label_id": "race-label", "actual_action": "reject",
            "verified_outcome": False})

    tasks = [asyncio.create_task(relabel()) for _ in range(2)]
    tasks.append(asyncio.create_task(adjudicate()))
    results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    assert sorted(response.status_code for response in results[:2]) == [200, 409]
    assert results[2].status_code in {200, 409}
    predecessor_trained = int(results[2].status_code == 200)
    async with wire.factory.sessions() as fresh:
        successors = (await fresh.scalars(select(LabelLog).where(
            LabelLog.domain_id == scoped, LabelLog.prior_revision_id == token))).all()
        assert len(successors) == 1
        assert successors[0].verified_at is None
        successor_id = successors[0].label_id
    await wire.request("POST", "/v1/labels/verify", json={
        "domain_id": "demo", "label_id": successor_id, "actual_action": "approve",
        "verified_outcome": True})
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(LabelLog.domain_id == scoped,
                                                        LabelLog.prior_revision_id == token))).all()
        assert len(rows) == 1 and rows[0].verified_outcome is True
        engine = await fresh.scalar(select(Engine).where(Engine.domain_id == scoped,
                                                       Engine.annotator_id.is_(None)))
        assert engine is not None and engine.state_json["conservation"]["total_verified"] == 1 + predecessor_trained


def _connector_process(url, schema, project, credential, tenant, barrier=None):
    """Each child imports its own app and opens its own database pool."""
    async def run():
        import jm_service
        options = {"server_settings": {"search_path": schema}} if schema else {}
        engine = create_async_engine(url, connect_args=options)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        connection.AsyncSessionLocal = sessions
        try:
            if barrier is None:
                async with sessions() as fresh:
                    return [(await _config(fresh, name, tenant)).domain_id for name in ("one", "two")]
            await asyncio.to_thread(barrier.wait, 25)
            async with AsyncClient(transport=ASGITransport(app=jm_service.app),
                                   base_url="http://integration") as client:
                response = await client.post("/v1/label-studio/configure",
                    headers={"X-LS-Token": "harness-ls", "X-Api-Key": credential},
                    json={"project_id": project, "domain_id": "process-" + project,
                          "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}})
                assert response.status_code == 200, response.status_code
            return os.getpid()
        finally:
            await engine.dispose()
    return asyncio.run(run())


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s25_independent_connector_processes_configure_distinct_projects(wire: Wire, db_engine):
    """S25. Two application processes commit configs a third process can read."""
    schema = None
    if db_engine.dialect.name == "postgresql":
        async with db_engine.connect() as conn:
            schema = await conn.scalar(text("select current_schema()"))
    url = db_engine.url.render_as_string(hide_password=False)
    credential = wire.client.headers["X-Api-Key"]
    ctx = multiprocessing.get_context("spawn")
    loop = asyncio.get_running_loop()
    with ctx.Manager() as manager, ProcessPoolExecutor(2, mp_context=ctx) as writers:
        barrier = manager.Barrier(2)  # type: ignore[attr-defined]  # registered SyncManager proxy
        jobs = [loop.run_in_executor(writers, _connector_process, url, schema, project,
                                     credential, wire.factory.tenant, barrier) for project in ("one", "two")]
        pids = await asyncio.wait_for(asyncio.gather(*jobs), 50)
        assert len(set(pids)) == 2
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(ConnectorConfigRow).where(
            ConnectorConfigRow.tenant_id == wire.factory.tenant))).all()
        assert {row.project_id for row in rows} == {"one", "two"}
    with ProcessPoolExecutor(1, mp_context=ctx) as reader:
        restored = await asyncio.wait_for(loop.run_in_executor(reader, _connector_process, url, schema,
                                          None, None, wire.factory.tenant), 30)
    assert restored == ["process-one", "process-two"]


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s26_incorrect_label_corrected_twice_including_category_reversion(wire: Wire):
    """S26. Incorrect label corrected twice, including category reversion."""
    await wire.factory.domain()
    await wire.factory.label("negative")
    await wire.request("POST", "/v1/labels/verify", json={
        "domain_id": "demo", "label_id": "negative", "actual_action": "reject",
        "verified_outcome": False})
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    current_id = "negative"
    for category in ("B", "A"):
        async with wire.factory.sessions() as fresh:
            current = await fresh.scalar(select(LabelLog).where(
                LabelLog.domain_id == scoped, LabelLog.label_id == current_id))
            assert current is not None
            token = str(current.id)
        revision = await wire.request("POST", f"/v1/labels/demo/items/{current_id}/relabel",
                                      json={"category": category, "idempotency_token": token})
        async with wire.factory.sessions() as fresh:
            successor = await fresh.get(LabelLog, UUID(revision.json()["revision_id"]))
            assert successor is not None and successor.verified_outcome is None
            current_id = successor.label_id
    async with wire.factory.sessions() as fresh:
        fresh.info["tenant_id"] = wire.factory.tenant
        count, accuracy = await repository.verified_accuracy(fresh, scoped, "A")
        assert (count, accuracy) == (1, 0.0)
        original = await fresh.scalar(select(LabelLog).where(LabelLog.domain_id == scoped,
                                                              LabelLog.label_id == "negative"))
        assert original is not None and original.verified_outcome is False
    await wire.request("POST", "/v1/labels/verify", json={
        "domain_id": "demo", "label_id": current_id, "actual_action": "approve",
        "verified_outcome": True})
    async with wire.factory.sessions() as fresh:
        fresh.info["tenant_id"] = wire.factory.tenant
        count, accuracy = await repository.verified_accuracy(fresh, scoped, "A")
        assert (count, accuracy) == (1, 1.0)


@pytest.mark.prompt_c
@pytest.mark.anyio
async def test_s27_bulk_approval_independent_outcomes_and_a_skipped_item(wire: Wire):
    """S27. Bulk approval, independent outcomes and a skipped item."""
    await wire.factory.domain()
    for label_id in ("right", "wrong", "unknown"):
        await wire.factory.label(label_id)
    await wire.request("POST", "/v1/labels/demo/bulk-verify", status=422, json={
        "action": "approve", "items": [{"label_id": "unknown", "verified_outcome": "yes"}]})
    response = await wire.request("POST", "/v1/labels/demo/bulk-verify", json={
        "action": "approve", "items": [
            {"label_id": "right", "verified_outcome": True},
            {"label_id": "wrong", "verified_outcome": False},
            {"label_id": "unknown"},
        ]})
    assert response.json()["processed"] == 2
    assert response.json()["skipped"] == 1
    assert response.json()["errors"] == [{"label_id": "unknown", "error": "outcome_required"}]
    async with wire.factory.sessions() as fresh:
        rows = (await fresh.scalars(select(LabelLog).where(
            LabelLog.label_id.in_(["right", "wrong", "unknown"])))).all()
        by_id = {row.label_id: row for row in rows}
        assert by_id["right"].verified_outcome is True
        assert by_id["wrong"].verified_outcome is False
        assert by_id["unknown"].verified_at is None
        assert by_id["right"].actual_action is not None
        assert by_id["wrong"].actual_action is not None
        fresh.info["tenant_id"] = wire.factory.tenant
        count, accuracy = await repository.verified_accuracy(
            fresh, scoped_domain_id(wire.factory.tenant, "demo"), "A")
        assert (count, accuracy) == (2, .5)
        engine = await fresh.scalar(select(Engine).where(
            Engine.domain_id == scoped_domain_id(wire.factory.tenant, "demo"),
            Engine.annotator_id.is_(None)))
        assert engine is not None
        assert engine.state_json["correct_trackers"]["quality"]["count"] == 1
        assert engine.state_json["incorrect_trackers"]["quality"]["count"] == 1
