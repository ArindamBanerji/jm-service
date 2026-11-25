"""Clock and retention checks for the Prompt A billing lifecycle."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import scheduler
from db.models import ApiKey, TransitionLog
from .fixtures.factory import Wire


@pytest.mark.prompt_a
@pytest.mark.anyio
async def test_trial_expiry_is_logged_once_and_blocks_scoring(wire: Wire):
    async with wire.factory.sessions.begin() as session:
        record = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == wire.factory.tenant))
        assert record is not None
        record.created_at = datetime.now(timezone.utc) - timedelta(days=15)
        key_id = record.id
    assert await scheduler.expire_trial_keys() == 1
    assert await scheduler.expire_trial_keys() == 0
    async with wire.factory.sessions() as fresh:
        record = await fresh.get(ApiKey, key_id)
        event = await fresh.get(TransitionLog, f"trial-expired:{key_id}")
        assert record is not None and record.subscription_state == "trial_expired"
        assert record.state_version == 1 and event is not None
    summary = await wire.request("GET", "/v1/account")
    assert summary.json()["subscription_state"] == "trial_expired"
    response = await wire.client.post("/v1/labels/ingest", json={
        "domain_id": "expired", "label_id": "one", "category": "A",
        "factors": {"quality": .8, "difficulty": .2},
    })
    assert response.status_code == 402
