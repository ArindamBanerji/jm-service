"""Prompt D additive migration and retention ordering."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import inspect, select, text

import scheduler
from db import repository
from db import migrate as migrations
from db.models import (ApiKey, Domain, Prediction, ProjectExportSlot,
                       WebhookAttempt, WebhookDelivery, WebhookEvent)
from .contracts.test_predictions import prediction
from .fixtures.factory import Wire

pytestmark = [pytest.mark.anyio, pytest.mark.prompt_d]


async def test_d_schema_upgrade_is_repeatable(db_engine, wire: Wire, monkeypatch):
    async with db_engine.begin() as connection:
        # Prompt E references D's event table. Drop the shared dependency
        # chain in reverse FK order so this remains an additive-upgrade test.
        for model in (WebhookAttempt, WebhookDelivery, WebhookEvent,
                      Prediction, ProjectExportSlot):
            await connection.run_sync(model.__table__.drop, checkfirst=True)
    monkeypatch.setattr(migrations, "engine", db_engine)
    await migrations.migrate()
    await migrations.migrate()

    def check(connection):
        catalog = inspect(connection)
        assert {"project_export_slot", "prediction", "webhook_event"} <= set(catalog.get_table_names())
        assert catalog.get_pk_constraint("project_export_slot")["constrained_columns"] == ["project_id", "slot"]
        prediction_columns = {column["name"] for column in catalog.get_columns("prediction")}
        assert {"original_label_log_id", "current_label_log_id", "gate_snapshot",
                "decision_version", "human_spans_reviewed"} <= prediction_columns
        event_unique = catalog.get_unique_constraints("webhook_event")
        assert any(set(row["column_names"]) == {"project_id", "event_type", "transition_key"}
                   for row in event_unique)
    async with db_engine.connect() as connection:
        await connection.run_sync(check)


async def test_retention_deletes_d_children_before_project(wire: Wire):
    project_id = (await wire.request("POST", "/v1/projects", status=201, json={
        "name": "Retention", "public_domain_id": "retention-d",
        "factors": ["quality", "difficulty"], "categories": ["A"],
        "actions": ["approve", "reject"],
    })).json()["id"]
    await wire.request("POST", f"/v1/projects/{project_id}/predictions", status=201, json={
        "request_key": "retention-prediction", "items": [prediction("retention-label")]})
    await wire.request("GET", f"/v1/projects/{project_id}/export")
    async with wire.factory.sessions.begin() as session:
        domain = await session.get(Domain, UUID(project_id))
        key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert key is not None and domain is not None
        await repository.record_webhook_event(session, domain, "webhook.test", "retention", {"ok": True})
        key.tier = "starter"
        key.subscription_state = "cancelled"
        key.paddle_subscription_id = "sub_retention_d"
        key.cancelled_at = datetime.now(timezone.utc) - timedelta(days=31)
    assert await scheduler.cleanup_cancelled_tenants() == 1
    async with wire.factory.sessions() as fresh:
        assert await fresh.get(Domain, UUID(project_id)) is None
        assert await fresh.scalar(select(Prediction.id)) is None
        assert await fresh.scalar(select(ProjectExportSlot.project_id)) is None
        assert await fresh.scalar(select(WebhookEvent.id)) is None
