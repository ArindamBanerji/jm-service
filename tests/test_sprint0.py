"""Sprint 0 smart sampling and quality SLA contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from db import repository
from db.models import Domain, LabelLog
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio


async def _project(wire: Wire, name: str) -> dict:
    return (await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name, "factors": ["quality", "difficulty"],
        "categories": ["A", "B"], "actions": ["approve", "reject"],
    })).json()


async def _upload(wire: Wire, project: dict, count: int = 5) -> None:
    await wire.request("POST", f"/v1/projects/{project['id']}/labels/batch", json={
        "request_key": f"batch-{project['id']}-{count}", "items": [{
            "label_id": f"L{index}", "category": "A" if index % 2 == 0 else "B",
            "factors": {"quality": index / max(count, 1), "difficulty": .2},
            "text": f"Pending sample text {index}",
        } for index in range(count)],
    })


async def _engine_state(wire: Wire, project: dict, *, verified: int, accuracy: float) -> None:
    async with wire.factory.sessions.begin() as session:
        session.info["tenant_id"] = wire.factory.tenant
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        engine = await repository.load_or_create_engine(session, domain.domain_id)
        for index in range(verified):
            session.add(LabelLog(domain_id=domain.domain_id, tenant_id=domain.tenant_id,
                label_id=f"verified-{index}", category="AB"[index % 2], factors_json={},
                verified_at=datetime.now(timezone.utc), verified_outcome=index < round(accuracy * verified)))
        engine.conservation.total_verified = verified
        engine.conservation.category_coverage = {"A": verified // 2, "B": verified - verified // 2}
        engine.conservation.rolling_accuracy = accuracy
        engine.conservation.accuracy_window = [True] * round(verified * accuracy) + [False] * (verified - round(verified * accuracy))
        await repository.save_engine_state(session, domain.domain_id, None, engine)


async def test_next_batch_returns_items(wire: Wire):
    project = await _project(wire, "sprint-items")
    await _upload(wire, project)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/next-batch")).json()
    assert result["total_pending"] == 5 and len(result["items"]) == 5
    assert {"id", "text_preview", "centroid_distance", "category", "priority_rank"} <= result["items"][0].keys()


async def test_next_batch_centroid_distance_ordering(wire: Wire):
    project = await _project(wire, "sprint-order")
    await _upload(wire, project, 4)
    async with wire.factory.sessions.begin() as session:
        session.info["tenant_id"] = wire.factory.tenant
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        engine = await repository.load_engine(session, domain.domain_id)
        assert engine is not None
        engine.conservation.total_verified = 20
        engine.conservation.category_coverage = {"A": 10, "B": 10}
        for key in engine.centroids:
            engine.centroids[key] = [0.0, 0.0]
        await repository.save_engine_state(session, domain.domain_id, None, engine)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/next-batch?n=4")).json()
    distances = [item["centroid_distance"] for item in result["items"]]
    assert result["strategy"] == "centroid_distance"
    assert distances == sorted(distances, reverse=True) and result["items"][0]["id"] == "L3"


async def test_next_batch_fallback_random(wire: Wire):
    project = await _project(wire, "sprint-random")
    await _upload(wire, project)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/next-batch")).json()
    assert result["strategy"] == "random"
    assert result["note"] == "Smart sampling activates after 20 verified labels"


async def test_next_batch_respects_n(wire: Wire):
    project = await _project(wire, "sprint-limit")
    await _upload(wire, project, 8)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/next-batch?n=3")).json()
    assert len(result["items"]) == 3 and result["total_pending"] == 8


async def test_next_batch_empty_project(wire: Wire):
    project = await _project(wire, "sprint-empty")
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/next-batch")).json()
    assert result["items"] == [] and result["total_pending"] == 0


async def test_next_batch_requires_auth(wire: Wire):
    project = await _project(wire, "sprint-auth-batch")
    await wire.request("GET", f"/v1/projects/{project['id']}/next-batch", status=401, omit_api_key=True)


async def test_sla_endpoint_safe(wire: Wire):
    project = await _project(wire, "sprint-sla-safe")
    await _engine_state(wire, project, verified=50, accuracy=.9)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/sla")).json()
    assert result["gate_status"] == "safe" and result["verified_count"] == 50


async def test_sla_endpoint_inactive(wire: Wire):
    project = await _project(wire, "sprint-sla-inactive")
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/sla")).json()
    assert result["gate_status"] == "inactive" and result["floor_pct"] is None
    assert result["min_verified_for_sla"] == 50


async def test_sla_endpoint_margin_calculation(wire: Wire):
    project = await _project(wire, "sprint-sla-margin")
    await _engine_state(wire, project, verified=50, accuracy=.8)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/sla")).json()
    assert result["margin"] == pytest.approx(result["current_accuracy"] - result["floor_pct"], abs=.01)


async def test_sla_endpoint_requires_auth(wire: Wire):
    project = await _project(wire, "sprint-auth-sla")
    await wire.request("GET", f"/v1/projects/{project['id']}/sla", status=401, omit_api_key=True)
