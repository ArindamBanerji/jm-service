"""PostgreSQL regressions for project sampling, human evidence and onboarding."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from db.models import ApiKey, Domain, Engine, LabelLog
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire
from tests.test_sprint0 import _engine_state, _project, _upload

pytestmark = pytest.mark.anyio


def path(project: dict, suffix: str) -> str:
    return f"/v1/projects/{project['id']}/{suffix}"


async def read(wire: Wire, project: dict, suffix: str) -> dict:
    return (await wire.request("GET", path(project, suffix))).json()


async def verify(wire: Wire, project: dict, index: int, correct: bool) -> None:
    await wire.request("POST", path(project, "labels/verify"), json={
        "label_id": f"L{index}", "actual_action": "approve", "verified_outcome": correct})


async def test_next_batch_after_all_verified(wire: Wire):
    project = await _project(wire, "finished")
    await _upload(wire, project, 2)
    for index in range(2):
        await verify(wire, project, index, True)
    batch = await read(wire, project, "next-batch")
    assert batch["items"] == [] and batch["total_pending"] == 0


async def test_next_batch_with_one_item(wire: Wire):
    project = await _project(wire, "solo")
    await _upload(wire, project, 1)
    row, = (await read(wire, project, "next-batch"))["items"]
    assert (row["id"], row["priority_rank"], row["text_preview"]) == ("L0", 1, "Pending sample text 0")


async def test_next_batch_max_n_cap(wire: Wire):
    project = await _project(wire, "large")
    async with wire.factory.sessions.begin() as session:
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        session.add_all([LabelLog(label_id=f"item-{i}", domain_id=domain.domain_id,
            tenant_id=domain.tenant_id, category="A", confidence=.7, recommended_action="approve",
            text="x" * 110 + ("needle" if i == 200 else ""), factors_json={}) for i in range(201)])
    first = await read(wire, project, "next-batch?n=500")
    last = await read(wire, project, "next-batch?offset=200")
    assert len(first["items"]) == 200 and first["total_pending"] == 201
    assert last["items"][0]["priority_rank"] == 201
    assert len({row["id"] for row in first["items"] + last["items"]}) == 201
    found = await read(wire, project, "next-batch?search=NEEDLE")
    assert found["total_pending"] == 1 and found["items"][0]["id"] == "item-200"


async def test_next_batch_ordering_stable(wire: Wire):
    project = await _project(wire, "stable")
    await _upload(wire, project)
    for strategy in ("random", "centroid_distance"):
        first = await read(wire, project, "next-batch")
        assert first["strategy"] == strategy
        assert await read(wire, project, "next-batch") == first
        if strategy == "random":
            await _engine_state(wire, project, verified=20, accuracy=1.)


async def test_next_batch_excludes_verified(wire: Wire):
    project = await _project(wire, "exclude")
    await _upload(wire, project, 2)
    await verify(wire, project, 0, False)
    assert [row["id"] for row in (await read(wire, project, "next-batch"))["items"]] == ["L1"]


async def test_next_batch_concurrent(wire: Wire):
    project = await _project(wire, "parallel")
    await _upload(wire, project)
    results = await asyncio.gather(*(read(wire, project, "next-batch") for _ in range(3)))
    assert results[0] == results[1] == results[2]
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count(LabelLog.id))) == 5
        assert await fresh.scalar(select(func.count(LabelLog.verified_at))) == 0


async def test_next_batch_wrong_project(wire: Wire):
    project = await _project(wire, "private")
    await _upload(wire, project)
    other = await wire.factory.user("outsider")
    result = await wire.request("GET", path(project, "next-batch"), status=404, headers={"X-Api-Key": other})
    assert result.json() == {"detail": "Project not found"}


async def test_sla_after_single_verification(wire: Wire):
    project = await _project(wire, "single")
    await _upload(wire, project, 1)
    await verify(wire, project, 0, True)
    result = await read(wire, project, "sla")
    assert (result["current_accuracy"], result["verified_count"], result["gate_status"]) == (100, 1, "inactive")


async def test_sla_margin_decreases_on_bad_label(wire: Wire):
    project = await _project(wire, "margin")
    await _engine_state(wire, project, verified=50, accuracy=1.)
    await _upload(wire, project, 1)
    before = await read(wire, project, "sla")
    await verify(wire, project, 0, False)
    after = await read(wire, project, "sla")
    assert after["verified_count"] == 51 and after["current_accuracy"] == 98
    assert after["margin"] < before["margin"]


async def test_sla_gate_trips(wire: Wire):
    project = await _project(wire, "trip")
    await _engine_state(wire, project, verified=49, accuracy=0.)
    await _upload(wire, project, 1)
    assert (await read(wire, project, "sla"))["gate_status"] == "inactive"
    await verify(wire, project, 0, False)
    result = await read(wire, project, "sla")
    assert result["margin"] < 0 and result["gate_status"] == "paused" and not result["auto_approve_active"]


async def test_sla_gate_recovers(wire: Wire):
    project = await _project(wire, "recover")
    await _engine_state(wire, project, verified=50, accuracy=.46)
    await _upload(wire, project, 10)
    assert (await read(wire, project, "sla"))["gate_status"] == "paused"
    for i in range(10):
        await verify(wire, project, i, True)
    result = await read(wire, project, "sla")
    assert result["gate_status"] == "safe" and result["margin"] > 10


async def test_sla_concurrent_reads(wire: Wire):
    project = await _project(wire, "readers")
    await _engine_state(wire, project, verified=50, accuracy=.8)
    first, second = await asyncio.gather(read(wire, project, "sla"), read(wire, project, "sla"))
    assert first == second and first["current_accuracy"] == 80


async def test_sla_wrong_project(wire: Wire):
    project = await _project(wire, "restricted")
    other = await wire.factory.user("non-member")
    response = await wire.request("GET", path(project, "sla"), headers={"X-Api-Key": other}, status=403)
    assert response.json()["detail"] == "Project membership required"


async def test_quickstart_project_created(wire: Wire):
    project = await _project(wire, "quickstart-demo")
    stored = (await wire.request("GET", path(project, "").rstrip("/"))).json()
    assert stored["id"] == project["id"] and stored["role"] == "owner" and stored["name"] == "quickstart-demo"


async def test_quickstart_items_uploaded(wire: Wire):
    project = await _project(wire, "demo-items")
    await _upload(wire, project)
    await _upload(wire, project)  # Retry the identical replay key.
    result = await read(wire, project, "next-batch")
    assert result["total_pending"] == 5
    assert {row["text_preview"] for row in result["items"]} == {f"Pending sample text {i}" for i in range(5)}


async def test_missing_project_and_invalid_batch_bounds(wire: Wire):
    for resource in ("sla", "next-batch"):
        response = await wire.request("GET", f"/v1/projects/{uuid4()}/{resource}", status=404)
        assert response.json()["detail"] == "Project not found"
    project = await _project(wire, "bounds")
    for query in ("n=0", "offset=-1"):
        response = await wire.request("GET", path(project, f"next-batch?{query}"), status=422)
        assert response.json()["detail"][0]["loc"][0] == "query"


async def test_sla_expired_payer_keeps_read_access_without_automation(wire: Wire):
    project = await _project(wire, "expired")
    await _engine_state(wire, project, verified=50, accuracy=.9)
    async with wire.factory.sessions.begin() as session:
        payer = (await session.scalars(select(ApiKey))).one()
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        domain.automation_enabled = True
        payer.created_at = datetime.now(timezone.utc) - timedelta(days=16)
    result = await read(wire, project, "sla")
    assert result["gate_status"] == "safe" and result["auto_approve_active"] is False


async def test_next_batch_handles_missing_and_nonfinite_geometry(wire: Wire):
    project = await _project(wire, "geometry")
    await _upload(wire, project, 2)
    await _engine_state(wire, project, verified=20, accuracy=.9)
    async with wire.factory.sessions.begin() as session:
        row = (await session.scalars(select(Engine))).one()
        state = dict(row.state_json)
        state["centroids"] = {"A|approve": ["NaN", .2]}
        row.state_json = state
    batch = await read(wire, project, "next-batch")
    assert batch["strategy"] == "centroid_distance" and batch["total_pending"] == 2
    assert all(item["centroid_distance"] is None for item in batch["items"])


def test_nonfinite_factor_cannot_enter_distance_ordering():
    from jm_core import DomainConfig, JudgmentMemoryEngine
    from labeling_router import _nearest_centroid_distance

    engine = JudgmentMemoryEngine(DomainConfig("finite", "Finite", ["quality"], ["A"], ["approve"]))
    for value in (float("nan"), float("inf"), float("-inf")):
        assert _nearest_centroid_distance(engine, {"quality": value}, "A") is None
