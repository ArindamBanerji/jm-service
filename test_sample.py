"""Sample fixture and quota-aware demo seeding."""
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from db.models import ApiKey, LabelLog
from test_labeling_router import client, set_key_usage


DOMAIN = "medical-ner-demo-v1"
URL = f"/v1/labels/{DOMAIN}/sample"
FIXTURE = Path(__file__).resolve().parent / "frontend/public/demo/sample_data.json"


def usage(client):
    async def read():
        async with client.app.state.session_factory() as session:
            key = await session.scalar(select(ApiKey).where(ApiKey.tenant_id == ""))
            return key.labels_today, key.labels_this_month
    return asyncio.run(read())


def test_fixture_contract():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = data["rows"]
    assert data["domain_id"] == DOMAIN
    assert len(rows) == 500
    assert [row["label_id"] for row in rows] == [f"med-{i:04d}" for i in range(1, 501)]
    assert Counter(row["category"] for row in rows) == {"MEDICATION": 167, "CONDITION": 167, "TEST": 166}
    assert Counter(row["verified_outcome"] for row in rows) == {True: 320, False: 80, None: 100}
    assert {row["annotator_id"] for row in rows} == {f"demo-ann-{i}" for i in range(1, 5)}
    for row in rows:
        assert row["text"]
        assert all(0 <= row[name] <= 1 for name in ("factor_model_confidence", "factor_item_difficulty"))
        span = row["span"]
        assert row["text"][span["start"]:span["end"]]
        assert span["label"] == row["category"]


def test_missing_api_key_returns_401(client):
    assert client.post(URL, headers={"X-Api-Key": ""}).status_code == 401


def test_success_creates_twelve_pending(client):
    response = client.post(URL)
    assert response.status_code == 200, response.text
    assert response.json() == {"domain_id": DOMAIN, "created": 12, "existing": 0, "pending": 12}
    pending = client.get(f"/v1/labels/{DOMAIN}/pending").json()
    assert len(pending) == 12
    assert {row["label_id"] for row in pending} == {f"med-{1 + i * 41:04d}" for i in range(12)}
    assert client.get(f"/v1/labels/{DOMAIN}/med-0001").json()["text"] == "Aspirin appears in the medication list."
    assert usage(client) == (12, 12)


def test_replay_preserves_counts_and_quota(client):
    assert client.post(URL).status_code == 200
    async def clear_text():
        async with client.app.state.session_factory() as session:
            row = await session.scalar(select(LabelLog).where(LabelLog.label_id == "med-0001"))
            row.text = None
            await session.commit()
    asyncio.run(clear_text())
    before = usage(client)
    response = client.post(URL)
    assert response.status_code == 200, response.text
    assert response.json() == {"domain_id": DOMAIN, "created": 0, "existing": 12, "pending": 12}
    assert usage(client) == before
    assert client.get(f"/v1/labels/{DOMAIN}/med-0001").json()["text"] == "Aspirin appears in the medication list."


def test_insufficient_quota_rolls_back(client):
    set_key_usage(client, daily=49)
    response = client.post(URL)
    assert response.status_code == 429, response.text
    assert usage(client)[0] == 49
    assert client.get(f"/v1/labels/{DOMAIN}/pending").status_code == 404
