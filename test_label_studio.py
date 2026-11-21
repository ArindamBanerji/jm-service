"""Label Studio connector contracts on the labeling database."""
import asyncio

import pytest
from sqlalchemy import select

from db.models import LabelLog
from dashboard_router import router as dashboard_router
from label_studio import router as studio_router
from test_labeling_router import open_client


HEADERS = {"X-LS-Token": "test-token"}
BASE = "/v1/label-studio"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LABEL_STUDIO_TOKEN", "test-token")
    monkeypatch.setenv("LABEL_STUDIO_DOMAIN_ID", "ls-demo")
    monkeypatch.setenv("LS_CONFIG_PATH", str(tmp_path / "connector.json"))
    with open_client(tmp_path) as http:
        http.app.include_router(studio_router)
        http.app.include_router(dashboard_router)
        yield http


def task(index=1, confidence=.9, agreement=.1, truth=None):
    data = {"category": "NER", "ml_confidence": confidence, "agreement_score": agreement}
    if truth is not None:
        data["ground_truth"] = truth
    return {"id": index, "data": data}


def predict(client, tasks):
    return client.post(f"{BASE}/predict", headers=HEADERS, json={"project": "p1", "tasks": tasks})


def event(index=1, action="ANNOTATION_CREATED", actual="approve", truth="approve"):
    return {"project": {"id": "p1"}, "action": action,
            "task": task(index, truth=truth),
            "annotation": {"id": index+1000, "task": index, "completed_by": 7,
                           "result": [{"value": {"choices": [actual]}}]}}


def webhook(client, payload):
    return client.post(f"{BASE}/webhook", headers=HEADERS, json=payload)


def log_row(client, label_id):
    async def read():
        async with client.app.state.session_factory() as session:
            row = await session.scalar(select(LabelLog).where(
                LabelLog.domain_id == "ls-demo", LabelLog.label_id == str(label_id)))
            if row is None:
                row = await session.scalar(select(LabelLog).where(
                    LabelLog.domain_id == "ls-demo", LabelLog.source_task_id == str(label_id))
                    .order_by(LabelLog.scored_at, LabelLog.id))
            while row is not None and row.superseded_by is not None:
                row = await session.scalar(select(LabelLog).where(
                    LabelLog.domain_id == "ls-demo", LabelLog.label_id == row.superseded_by))
            return None if row is None else (row.actual_action, row.verified_outcome, row.annotator_id)
    return asyncio.run(read())


def test_setup_returns_model_version(client):
    response = client.post(f"{BASE}/setup", headers=HEADERS, json={"project": "p1", "schema": "<Choices/>"})
    assert response.status_code == 200
    assert response.json() == {"model_version": "jm-v1"}
    assert client.post(f"{BASE}/setup", headers=HEADERS, json={"project": "p1"}).status_code == 200


def test_predict_creates_tenant_domain_after_setup(client):
    assert client.post(f"{BASE}/setup", headers=HEADERS, json={"project": "p1"}).status_code == 200
    assert predict(client, [task()]).status_code == 200
    response = client.get("/v1/domains/ls-demo/autonomy")
    assert response.status_code == 200
    assert response.json()["categories"][0]["category"] == "default"


def test_predict_single_task(client):
    response = predict(client, [task()])
    assert response.status_code == 200, response.text
    prediction = response.json()["results"][0]
    assert set(prediction) == {"result", "score", "model_version", "eligibility"}
    assert prediction["result"] == [] and prediction["model_version"] == "jm-v1"
    assert 0 <= prediction["score"] <= 1


def test_predict_multiple_tasks(client):
    response = predict(client, [task(i) for i in range(3)])
    assert response.status_code == 200, response.text
    assert len(response.json()["results"]) == 3
    assert predict(client, [task(0)]).status_code == 200
    assert len(client.get("/v1/labels/ls-demo/pending").json()) == 3


def test_predict_persists_to_label_log(client):
    assert predict(client, [task(42)]).status_code == 200
    assert client.get("/v1/labels/ls-demo/pending").json()[0]["label_id"] == "42"


def test_predict_missing_factors(client):
    incomplete = {"id": 3, "data": {"category": "NER", "ml_confidence": .9}}
    response = predict(client, [incomplete])
    assert response.status_code == 200, response.text
    assert client.get("/v1/labels/ls-demo/pending").json()[0]["factors"]["annotator_agreement"] == .5


def test_webhook_annotation_created(client):
    assert predict(client, [task()]).status_code == 200
    pending = webhook(client, event(truth=None))
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_ground_truth"
    assert log_row(client, 1) == (None, None, None)
    response = webhook(client, event())
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "processed"}
    assert log_row(client, 1) == ("approve", True, "7")
    assert client.get("/v1/labels/ls-demo/pending").json() == []


def test_webhook_annotation_updated(client):
    assert webhook(client, event()).status_code == 200
    revised = event(action="ANNOTATION_UPDATED", actual="reject", truth="reject")
    response = webhook(client, revised)
    assert response.status_code == 200, response.text
    assert log_row(client, 1) == ("reject", True, "7")
    assert webhook(client, revised).status_code == 200
    overview = client.get("/v1/dashboard/ls-demo/overview").json()
    assert overview["total_verified"] == 1


def test_webhook_unknown_action(client):
    response = webhook(client, {"project": "p1", "action": "PROJECT_UPDATED"})
    assert response.status_code == 200 and response.json()["status"] == "ignored"


def test_webhook_unseen_task(client):
    response = webhook(client, event(index=71))
    assert response.status_code == 200, response.text
    assert log_row(client, 71) == ("approve", True, "7")


def test_health_up(client):
    assert client.get(f"{BASE}/health").json() == {"status": "UP", "model_version": "jm-v1"}
    assert predict(client, [task()]).status_code == 200
    assert client.post(f"{BASE}/predict", json={"project": "p1", "tasks": [task()]}).status_code == 401


def test_configure_saves_mapping(client):
    config = {"domain_id": "ls-demo", "project_id": "p1",
              "factor_map": {"model_confidence": "data.prob", "annotator_agreement": "data.agree"},
              "category_field": "data.kind", "ground_truth_field": "data.gold"}
    response = client.post(f"{BASE}/configure", headers=HEADERS, json=config)
    assert response.status_code == 200, response.text
    response = predict(client, [{"id": 5, "data": {"kind": "NER", "prob": .8, "agree": .2}}])
    assert response.status_code == 200, response.text
    pending = client.get("/v1/labels/ls-demo/pending").json()[0]
    assert pending["factors"] == {"model_confidence": .8, "annotator_agreement": .2}


def test_ls_predict_then_webhook_learns(client):
    first_task = task()
    first_task["annotator_id"] = "7"
    first = predict(client, [first_task]).json()["results"][0]["score"]
    assert webhook(client, event()).status_code == 200
    second_task = task(2)
    second_task["annotator_id"] = "7"
    second = predict(client, [second_task]).json()["results"][0]["score"]
    assert second > first


def test_ls_dashboard_reflects_ls_data(client):
    for index in range(12):
        assert predict(client, [task(index)]).status_code == 200
        assert webhook(client, event(index=index, truth="approve" if index % 3 else "reject")).status_code == 200
    result = client.get("/v1/dashboard/ls-demo/overview")
    assert result.status_code == 200, result.text
    assert result.json()["total_verified"] == 12
    assert result.json()["compounding_curve"][-1]["verified_count"] == 12


def test_ls_predict_cold_annotator_capped(client):
    candidate = task(88)
    candidate["annotator_id"] = "new"
    response = predict(client, [candidate])
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["score"] <= .49
    assert "annotator_verified_30" in result["eligibility"]["checks_failed"]


def test_ls_predict_qualified_annotator_uncapped(client):
    from datetime import datetime, timezone
    from db import repository
    from jm_core import DomainConfig
    from db.models import Engine

    assert predict(client, [task(1)]).status_code == 200
    async def qualify() -> None:
        async with client.app.state.session_factory() as session:
            domain = await repository.get_domain(session, "ls-demo")
            assert domain is not None
            config = DomainConfig.from_dict(domain.config_json)
            for who in (None, "ann"):
                engine = await repository.load_or_create_engine(session, "ls-demo", who)
                engine.centroids["NER|approve"] = [.9, .1]
                engine.centroids["NER|reject"] = [.1, .9]
                for _ in range(200):
                    engine.conservation.update(True, "NER")
                await repository.save_engine_state(session, "ls-demo", who, engine)
            session.add_all([LabelLog(domain_id="ls-demo", label_id=f"seed-{index}",
                                      category="NER", annotator_id="ann",
                                      factors_json={"model_confidence": .9, "annotator_agreement": .1},
                                      recommended_action="approve", actual_action="approve",
                                      verified_outcome=True, confidence=.9,
                                      verified_at=datetime.now(timezone.utc)) for index in range(200)])
            await session.commit()
    asyncio.run(qualify())
    candidate = task(99)
    candidate["annotator_id"] = "ann"
    response = predict(client, [candidate])
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["eligibility"]["checks_failed"] == []
    assert result["score"] >= .6


def test_webhook_update_scoped(client):
    from db.models import Engine
    assert webhook(client, event(index=55)).status_code == 200
    changed = event(index=55, action="ANNOTATION_UPDATED", actual="reject", truth="reject")
    changed["annotation"]["completed_by"] = 8
    assert webhook(client, changed).status_code == 200
    async def read():
        async with client.app.state.session_factory() as session:
            engines = (await session.scalars(select(Engine).where(Engine.domain_id == "ls-demo"))).all()
            rows = (await session.scalars(select(LabelLog).where(LabelLog.domain_id == "ls-demo"))).all()
            return {engine.annotator_id for engine in engines}, rows
    scopes, rows = asyncio.run(read())
    assert {"7", "8"} <= scopes
    assert len(rows) == 2
    assert next(row for row in rows if row.annotator_id == "7").superseded_by is not None
    assert next(row for row in rows if row.annotator_id == "8").actual_action == "reject"


def test_predicted_task_verification_binds_reviewer(client):
    from db.models import Engine

    assert predict(client, [task(88)]).status_code == 200
    assert webhook(client, event(index=88)).status_code == 200
    assert log_row(client, 88) == ("approve", True, "7")

    async def read():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(Engine).where(Engine.domain_id == "ls-demo"))).all()

    assert "7" in {engine.annotator_id for engine in asyncio.run(read())}


def test_webhook_reviewer_change_with_same_outcome_creates_revision(client):
    assert webhook(client, event(index=89)).status_code == 200
    changed = event(index=89, action="ANNOTATION_UPDATED")
    changed["annotation"]["completed_by"] = 8
    assert webhook(client, changed).status_code == 200
    assert log_row(client, 89) == ("approve", True, "8")
    assert webhook(client, changed).status_code == 200

    async def read():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(LabelLog).where(
                LabelLog.domain_id == "ls-demo", LabelLog.source_task_id == "89"))).all()

    rows = asyncio.run(read())
    assert len(rows) == 2
    assert {row.annotator_id for row in rows} == {"7", "8"}


def test_two_annotations_on_same_task_have_separate_rows(client):
    first = event(index=77)
    second = event(index=77)
    second["annotation"]["id"] = 9777
    second["annotation"]["completed_by"] = 8
    assert webhook(client, first).status_code == 200
    assert webhook(client, second).status_code == 200
    async def read():
        async with client.app.state.session_factory() as session:
            return (await session.scalars(select(LabelLog).where(
                LabelLog.domain_id == "ls-demo", LabelLog.source_task_id == "77"))).all()
    rows = asyncio.run(read())
    assert len(rows) == 2
    assert {row.annotation_id for row in rows} == {"p1:1077", "p1:9777"}
    assert {row.annotator_id for row in rows} == {"7", "8"}
