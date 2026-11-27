"""Analytics endpoint contracts over existing project evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from db.models import Domain, LabelLog, Prediction
from tests.harness.conftest import anyio_backend, db_engine, factory, wire  # noqa: F401
from tests.harness.fixtures.factory import Wire

pytestmark = pytest.mark.anyio


async def _project(wire: Wire, name: str) -> dict:
    return (await wire.request("POST", "/v1/projects", status=201, json={
        "name": name, "public_domain_id": name,
        "factors": ["quality", "difficulty"], "categories": ["A", "B", "C"],
        "actions": ["approve", "reject"],
    })).json()


async def _domain(wire: Wire, project: dict) -> Domain:
    async with wire.factory.sessions() as session:
        domain = await session.get(Domain, UUID(project["id"]))
        assert domain is not None
        session.expunge(domain)
        return domain


async def _labels(wire: Wire, project: dict, rows: list[dict]) -> None:
    domain = await _domain(wire, project)
    async with wire.factory.sessions.begin() as session:
        for index, values in enumerate(rows):
            defaults = {
                "domain_id": domain.domain_id, "tenant_id": domain.tenant_id,
                "label_id": f"label-{index}-{uuid4().hex[:8]}", "category": "A",
                "factors_json": {"quality": .8, "difficulty": .2},
                "recommended_action": "approve", "scored_at": datetime.now(timezone.utc),
            }
            session.add(LabelLog(**(defaults | values)))


async def test_distribution_returns_categories(wire: Wire):
    project = await _project(wire, "analytics-distribution")
    await _labels(wire, project, [{"category": "A"}, {"category": "A"},
                                  {"category": "B", "verified_at": datetime.now(timezone.utc)},
                                  {"category": "C"}])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/distribution")).json()
    assert result["total"] == 4
    assert result["categories"] == [
        {"name": "A", "count": 2, "pct": 50.0, "verified": 0, "pending": 2},
        {"name": "B", "count": 1, "pct": 25.0, "verified": 1, "pending": 0},
        {"name": "C", "count": 1, "pct": 25.0, "verified": 0, "pending": 1},
    ]


async def test_distribution_imbalance_warning(wire: Wire):
    project = await _project(wire, "analytics-imbalance")
    await _labels(wire, project, ([{"category": "A"}] * 20 + [{"category": "B"}] * 20 +
                                  [{"category": "C"}]))
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/distribution")).json()
    assert result["imbalance_warning"].startswith("C has 2.4%")


async def test_distribution_empty_project(wire: Wire):
    project = await _project(wire, "analytics-empty")
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/distribution")).json()
    assert result == {"categories": [], "total": 0, "imbalance_warning": None}


async def test_distribution_requires_auth(wire: Wire):
    project = await _project(wire, "analytics-distribution-auth")
    await wire.request("GET", f"/v1/projects/{project['id']}/analytics/distribution",
                       status=401, omit_api_key=True)


async def test_throughput_daily_counts(wire: Wire):
    project = await _project(wire, "analytics-throughput-days")
    now = datetime.now(timezone.utc)
    await _labels(wire, project, [
        {"scored_at": now, "verified_at": now},
        {"scored_at": now - timedelta(days=1), "verified_at": now - timedelta(days=1)},
        {"scored_at": now - timedelta(days=1)},
    ])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/throughput?days=2")).json()
    assert [row["labels"] for row in result["daily"]] == [2, 1]
    assert [row["verified"] for row in result["daily"]] == [1, 1]


async def test_throughput_annotator_breakdown(wire: Wire):
    project = await _project(wire, "analytics-throughput-annotators")
    now = datetime.now(timezone.utc)
    await _labels(wire, project, [
        {"annotator_id": "jchen", "scored_at": now - timedelta(seconds=20)},
        {"annotator_id": "jchen", "scored_at": now},
        {"annotator_id": "mlee", "scored_at": now},
    ])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/throughput")).json()
    assert [(row["name"], row["labels_total"]) for row in result["annotators"]] == [("jchen", 2), ("mlee", 1)]
    assert result["annotators"][0]["avg_time_sec"] == 20


async def test_throughput_days_param(wire: Wire):
    project = await _project(wire, "analytics-throughput-param")
    old = datetime.now(timezone.utc) - timedelta(days=100)
    await _labels(wire, project, [{"annotator_id": "old-user", "scored_at": old},
                                  {"annotator_id": "old-user", "scored_at": old + timedelta(seconds=10)}])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/throughput?days=3")).json()
    assert len(result["daily"]) == 3
    assert result["summary"]["avg_time_sec"] is None


async def test_throughput_requires_auth(wire: Wire):
    project = await _project(wire, "analytics-throughput-auth")
    await wire.request("GET", f"/v1/projects/{project['id']}/analytics/throughput",
                       status=401, omit_api_key=True)


async def test_confusion_matrix_diagonal(wire: Wire):
    project = await _project(wire, "analytics-confusion-diagonal")
    now = datetime.now(timezone.utc)
    await _labels(wire, project, [{"category": "A", "verified_at": now},
                                  {"category": "B", "verified_at": now}])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion?source=human")).json()
    assert result["matrix"][0][0] == 1 and result["matrix"][1][1] == 1
    assert result["top_confusions"] == []


async def _correction(wire: Wire, project: dict, *, prediction: bool = False) -> None:
    domain = await _domain(wire, project)
    now = datetime.now(timezone.utc)
    async with wire.factory.sessions.begin() as session:
        prior = LabelLog(domain_id=domain.domain_id, tenant_id=domain.tenant_id,
            label_id=f"prior-{uuid4().hex}", category="A", factors_json={},
            recommended_action="approve", scored_at=now)
        session.add(prior)
        await session.flush()
        current = LabelLog(domain_id=domain.domain_id, tenant_id=domain.tenant_id,
            label_id=f"current-{uuid4().hex}", category="B", factors_json={},
            recommended_action="approve", actual_action="approve", verified_outcome=True,
            scored_at=now, verified_at=now, prior_revision_id=str(prior.id))
        session.add(current)
        await session.flush()
        prior.superseded_by = current.label_id
        if prediction:
            session.add(Prediction(project_id=domain.id, original_label_log_id=prior.id,
                current_label_log_id=current.id, source="model", model_version="v1",
                original_content={}, original_category="A", model_confidence=.8,
                dlj_confidence=.8, tier="red", recommendation="approve", gate_snapshot={},
                decision_reason="review", state="human_reviewed", imported_at=now,
                human_reviewed_at=now, assessment="incorrect"))


async def test_confusion_with_corrections(wire: Wire):
    project = await _project(wire, "analytics-confusion-correction")
    await _correction(wire, project)
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion?source=human")).json()
    assert result["matrix"][0][1] == 1


async def test_confusion_top_pairs(wire: Wire):
    project = await _project(wire, "analytics-confusion-top")
    await _correction(wire, project); await _correction(wire, project)
    now = datetime.now(timezone.utc)
    domain = await _domain(wire, project)
    async with wire.factory.sessions.begin() as session:
        prior = LabelLog(domain_id=domain.domain_id, tenant_id=domain.tenant_id, label_id="c-prior",
                         category="C", factors_json={}, scored_at=now)
        session.add(prior); await session.flush()
        current = LabelLog(domain_id=domain.domain_id, tenant_id=domain.tenant_id, label_id="c-current",
                           category="B", factors_json={}, scored_at=now, verified_at=now,
                           prior_revision_id=str(prior.id))
        session.add(current); prior.superseded_by = current.label_id
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion?source=human")).json()
    assert result["top_confusions"][0]["count"] == 2
    assert [row["count"] for row in result["top_confusions"]] == sorted(
        [row["count"] for row in result["top_confusions"]], reverse=True)


async def test_confusion_source_filter(wire: Wire):
    project = await _project(wire, "analytics-confusion-source")
    await _correction(wire, project, prediction=True)
    now = datetime.now(timezone.utc)
    await _labels(wire, project, [{"category": "C", "verified_at": now}])
    prediction = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion?source=prediction")).json()
    human = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion?source=human")).json()
    assert prediction["matrix"][0][1] == 1 and human["matrix"][2][2] == 1
    assert sum(map(sum, prediction["matrix"])) == sum(map(sum, human["matrix"])) == 1


async def test_confusion_requires_auth(wire: Wire):
    project = await _project(wire, "analytics-confusion-auth")
    await wire.request("GET", f"/v1/projects/{project['id']}/analytics/confusion",
                       status=401, omit_api_key=True)


async def _overlap(wire: Wire, project: dict, observations: list[tuple[str, str, str, str]]) -> None:
    await _labels(wire, project, [{"source_task_id": task, "annotator_id": annotator,
        "category": category, "actual_action": action} for task, annotator, category, action in observations])


async def test_agreement_two_annotators(wire: Wire):
    project = await _project(wire, "analytics-agreement-two")
    await _overlap(wire, project, [("1", "jchen", "A", "approve"), ("1", "mlee", "A", "approve"),
                                   ("2", "jchen", "B", "approve"), ("2", "mlee", "A", "approve")])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/agreement")).json()
    assert result["annotators"] == ["jchen", "mlee"] and result["matrix"][0][1] == .5


async def test_agreement_no_overlap(wire: Wire):
    project = await _project(wire, "analytics-agreement-none")
    await _overlap(wire, project, [("1", "jchen", "A", "approve"), ("2", "mlee", "A", "approve")])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/agreement")).json()
    assert result["annotators"] == [] and result["note"].startswith("Agreement requires")


async def test_agreement_per_category(wire: Wire):
    project = await _project(wire, "analytics-agreement-category")
    await _overlap(wire, project, [("1", "jchen", "A", "approve"), ("1", "mlee", "A", "approve"),
                                   ("2", "jchen", "B", "approve"), ("2", "mlee", "C", "approve")])
    result = (await wire.request("GET", f"/v1/projects/{project['id']}/analytics/agreement")).json()
    assert result["per_category"]["A"][0][1] == 1
    assert result["per_category"]["B"][0][1] == 0
    assert result["lowest_pair"]["worst_category"] in {"B", "C"}


async def test_agreement_requires_auth(wire: Wire):
    project = await _project(wire, "analytics-agreement-auth")
    await wire.request("GET", f"/v1/projects/{project['id']}/analytics/agreement",
                       status=401, omit_api_key=True)
