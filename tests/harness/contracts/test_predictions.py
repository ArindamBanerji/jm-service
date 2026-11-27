"""Prompt D prediction provenance, automation and review contracts."""
from datetime import datetime, timezone
import json
from uuid import UUID

import pytest
from sqlalchemy import func, select

from auth import scoped_domain_id
from db import repository
from db.models import Annotator, ApiKey, Domain, Engine, LabelLog, Prediction, WebhookEvent
from ..fixtures.factory import Wire

pytestmark = [pytest.mark.anyio, pytest.mark.prompt_d]


def prediction(label_id: str, confidence: float = .99) -> dict:
    return {
        "label_id": label_id, "source": "model-a", "model_version": "v1",
        "category": "A", "annotator_id": "model-reviewer",
        "factors": {"quality": .9, "difficulty": .1},
        "model_confidence": confidence, "text": f"Prediction {label_id}",
    }


async def project(wire: Wire) -> str:
    return (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Predictions", "public_domain_id": "demo",
        "factors": ["quality", "difficulty"], "categories": ["A", "B"],
        "actions": ["approve", "reject"],
    })).json()["id"]


async def test_prediction_import_replay_scoring_and_boundary(wire: Wire):
    project_id = await project(wire)
    payload = {"request_key": "prediction-five",
               "items": [prediction(f"prediction-{index}") for index in range(5)]}
    imported = await wire.request("POST", f"/v1/projects/{project_id}/predictions",
                                  status=201, json=payload)
    assert imported.json()["batch_size"] == 5
    assert all(row["state"] == "pending" and isinstance(row["dlj_confidence"], float)
               for row in imported.json()["results"])
    replay = await wire.request("POST", f"/v1/projects/{project_id}/predictions",
                                status=201, json=payload)
    assert replay.json() == imported.json()
    async with wire.factory.sessions() as fresh:
        assert await fresh.scalar(select(func.count()).select_from(Prediction)) == 5
        labels = (await fresh.scalars(select(LabelLog).where(
            LabelLog.label_id.like("prediction-%")))).all()
        assert len(labels) == 5 and all(row.verified_at is None and row.verified_outcome is None for row in labels)
        engine = await fresh.scalar(select(Engine).where(
            Engine.domain_id == scoped_domain_id(wire.factory.tenant, "demo"),
            Engine.annotator_id == "model-reviewer"))
        assert engine is not None and engine.state_json["conservation"]["total_verified"] == 0
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and key.labels_today == 5
    await wire.request("POST", f"/v1/projects/{project_id}/predictions", status=422,
                       json={"request_key": "too-many",
                             "items": [prediction(f"many-{index}") for index in range(101)]})


async def seed_autonomous_project(wire: Wire, project_id: str) -> None:
    now = datetime.now(timezone.utc)
    scoped = scoped_domain_id(wire.factory.tenant, "demo")
    async with wire.factory.sessions.begin() as session:
        session.info["tenant_id"] = wire.factory.tenant
        domain = await session.get(Domain, UUID(project_id))
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert domain is not None and key is not None
        domain.automation_enabled = True
        key.tier = "professional"
        key.subscription_state = "active"
        engine = await repository.load_or_create_engine(session, scoped, "model-reviewer")
        engine.centroids["A|approve"] = [.9, .1]
        engine.centroids["A|reject"] = [.1, .9]
        for index in range(200):
            engine.conservation.update(True, "A")
            session.add(LabelLog(
                domain_id=scoped, tenant_id=wire.factory.tenant, label_id=f"evidence-{index}",
                annotator_id="model-reviewer", category="A",
                factors_json={"quality": .9, "difficulty": .1},
                recommended_action="approve", actual_action="approve",
                verified_outcome=True, confidence=.99, scored_at=now, verified_at=now))
        await repository.save_engine_state(session, scoped, "model-reviewer", engine)
        session.add(Annotator(domain_id=scoped, tenant_id=wire.factory.tenant,
                              annotator_id="model-reviewer", label_count=200, last_active=now))


async def test_automation_review_reopen_stats_and_events(wire: Wire):
    project_id = await project(wire)
    await seed_autonomous_project(wire, project_id)
    imported = await wire.request("POST", f"/v1/projects/{project_id}/predictions", status=201,
                                  json={"request_key": "automation", "items": [
                                      prediction("auto-high"), prediction("auto-low", .20)]})
    high, low = imported.json()["results"]
    assert high["state"] == "auto_approved" and high["machine_approved_at"]
    assert low["state"] == "pending" and low["decision_reason"] == "model_confidence"
    async with wire.factory.sessions() as fresh:
        high_row = await fresh.get(LabelLog, UUID(high["current_label_log_id"]))
        assert high_row is not None and high_row.verified_outcome is None and high_row.verified_at is None
        engine = await fresh.scalar(select(Engine).where(
            Engine.domain_id == scoped_domain_id(wire.factory.tenant, "demo"),
            Engine.annotator_id == "model-reviewer"))
        assert engine is not None and engine.state_json["conservation"]["total_verified"] == 200
        event = await fresh.scalar(select(WebhookEvent).where(
            WebhookEvent.event_type == "prediction.auto_approved"))
        assert event is not None
        envelope = json.loads(event.canonical_body)
        assert set(envelope) == {"event_id", "event_type", "project_id", "occurred_at", "schema_version", "data"}
        assert envelope["event_type"] == "prediction.auto_approved" and envelope["schema_version"] == 1
    queue = (await wire.request("GET", f"/v1/projects/{project_id}/labels/pending?search=auto-")).json()
    assert [entry["label_id"] for entry in queue] == ["auto-low"]
    await wire.request("POST", f"/v1/projects/{project_id}/predictions/{high['id']}/reopen",
                       status=409, json={"decision_version": 1, "expected_revision": low["current_label_log_id"]})
    reviewed = await wire.request(
        "POST", f"/v1/projects/{project_id}/predictions/{high['id']}/review", json={
            "assessment": "correct", "human_spans_reviewed": True,
            "expected_revision": high["current_label_log_id"],
            "decision_version": high["decision_version"]})
    assert reviewed.json()["state"] == "human_reviewed" and reviewed.json()["assessment"] == "correct"
    assert reviewed.json()["decision_version"] == 2
    async with wire.factory.sessions() as fresh:
        row = await fresh.get(LabelLog, UUID(high["current_label_log_id"]))
        assert row is not None and row.verified_outcome is True
        events = (await fresh.scalars(select(WebhookEvent))).all()
        assert {event.event_type for event in events} == {"prediction.auto_approved", "label.verified"}
    reopened = await wire.request(
        "POST", f"/v1/projects/{project_id}/predictions/{high['id']}/reopen",
        json={"expected_revision": high["current_label_log_id"], "decision_version": 2})
    assert reopened.json()["state"] == "pending"
    assert reopened.json()["decision_version"] == 3
    assert reopened.json()["current_label_log_id"] != high["current_label_log_id"]
    stats = (await wire.request("GET", f"/v1/projects/{project_id}/predictions/stats")).json()
    assert stats["total"] == 2 and stats["by_state"] == {"pending": 2}
    async with wire.factory.sessions() as fresh:
        saved = await fresh.get(Prediction, UUID(high["id"]))
        assert saved and saved.machine_approved_at and saved.recommendation == high["recommendation"]
        key = await fresh.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key and key.labels_today == 2


async def test_pending_prediction_revision_keeps_provenance(wire: Wire):
    project_id = await project(wire)
    base = f"/v1/projects/{project_id}"
    pred = (await wire.request("POST", base + "/predictions", status=201, json={
        "request_key": "edit", "items": [prediction("edit-me")]})).json()["results"][0]
    revision = (await wire.request("POST", base + "/labels/items/edit-me/relabel", json={
        "idempotency_token": pred["current_label_log_id"], "category": "B"})).json()
    detail = (await wire.request("GET", base + "/labels/items/edit-me")).json()
    assert detail["prediction"]["id"] == pred["id"]
    assert detail["prediction"]["original_category"] == "A"
    assert detail["prediction"]["current_label_log_id"] == revision["revision_id"]
    assert detail["prediction"]["decision_version"] == 2
    await wire.request("POST", base + "/labels/verify", json={
        "label_id": detail["label_id"], "actual_action": "approve", "verified_outcome": True})
    stats = (await wire.request("GET", base + "/predictions/stats")).json()
    assert stats["by_state"] == {"human_reviewed": 1} and stats["accuracy"] is None
