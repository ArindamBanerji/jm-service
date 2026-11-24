"""Guidelines and agreement contracts on SQLite and PostgreSQL."""
import asyncio
import os
from datetime import datetime, timezone

import pytest
from auth import scoped_domain_id
from db import repository
from db.models import LabelLog
from dashboard_router import cohen_kappa, router as dashboard_router
from jm_core import DomainConfig
from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    with open_tasks_client(tmp_path) as http:
        http.app.include_router(dashboard_router)
        yield http


def seed(client, annotations):
    async def write():
        async with client.app.state.session_factory() as session:
            session.info["tenant_id"] = "tasks-tenant"
            key = scoped_domain_id("tasks-tenant", "medical")
            await repository.create_domain(session, key, "medical",
                DomainConfig(key, "medical", ["a", "b"], ["A", "B"], ["approve", "reject"]))
            now = datetime.now(timezone.utc)
            for index, (task, who, category) in enumerate(annotations):
                session.add(LabelLog(domain_id=key, tenant_id="tasks-tenant",
                    label_id=f"annotation-{index}", source_task_id=task, annotator_id=who,
                    category=category, factors_json={"a": .5, "b": .5},
                    recommended_action="approve", confidence=.8,
                    scored_at=now, verified_at=now, verified_outcome=True))
            await session.commit()
    asyncio.run(write())


def test_guidelines_round_trip(client):
    seed(client, [])
    payload = {"guidelines": "# Label entities\n- Preserve original text"}
    assert client.put("/v1/domains/medical/guidelines", json=payload).json() == payload
    assert client.get("/v1/domains/medical/guidelines").json() == payload


def test_guidelines_limit_is_utf8_bytes(client):
    seed(client, [])
    assert client.put("/v1/domains/medical/guidelines",
                      json={"guidelines": "é" * 6000}).status_code == 422


def test_unset_guidelines_are_null(client):
    seed(client, [])
    assert client.get("/v1/domains/medical/guidelines").json() == {"guidelines": None}


def test_two_annotators_agree(client):
    seed(client, [("t1", "ann-a", "A"), ("t1", "ann-b", "A"),
                  ("t2", "ann-a", "B"), ("t2", "ann-b", "B")])
    result = client.get("/v1/dashboard/medical/iaa").json()
    assert result["pairs"][0]["kappa"] == 1
    assert result["pairs"][0]["overlap_count"] == 2


def test_no_overlap(client):
    seed(client, [("t1", "ann-a", "A"), ("t2", "ann-b", "B")])
    assert client.get("/v1/dashboard/medical/iaa").json() == {
        "pairs": [], "overall_kappa": None, "total_overlapping_labels": 0}


def test_one_annotator(client):
    seed(client, [("t1", "ann-a", "A"), ("t2", "ann-a", "B")])
    assert client.get("/v1/dashboard/medical/iaa").json()["pairs"] == []


def test_kappa_manual_calculation(client):
    # Both marginals are 50/50, observed agreement is 3/4: kappa = (0.75 - 0.5) / 0.5.
    pairs = [("A", "A"), ("A", "A"), ("B", "B"), ("B", "A")]
    seed(client, [(f"t{i}", who, category) for i, (a, b) in enumerate(pairs)
                  for who, category in (("ann-a", a), ("ann-b", b))])
    result = client.get("/v1/dashboard/medical/iaa").json()
    assert result["pairs"][0]["kappa"] == pytest.approx(0.5)
    assert result["overall_kappa"] == pytest.approx(0.5)
    assert cohen_kappa(["A", "A"], ["A", "A"]) == 1


def test_guidelines_require_auth(client):
    seed(client, [])
    assert client.get("/v1/domains/medical/guidelines",
                      headers={"X-Api-Key": "invalid"}).status_code == 401
