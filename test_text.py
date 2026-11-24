"""Source-text persistence, isolation, migration, and preview contracts."""
import asyncio
import hashlib
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect, select, text as sql_text
from sqlalchemy.ext.asyncio import create_async_engine

import db.migrate as migration
from db.models import ApiKey, Base, LabelLog
from test_labeling_router import client, item, tenant_key


def detail(client, domain="demo", label="L1", headers=None):
    return client.get(f"/v1/labels/{domain}/{label}", headers=headers)


@pytest.mark.asyncio
async def test_old_schema_migration_repeats(tmp_path, monkeypatch):
    db_path = Path(tmp_path) / "old.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(sql_text("ALTER TABLE label_log DROP COLUMN text"))
    await engine.dispose()
    for _ in range(2):
        monkeypatch.setattr(migration, "engine", create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}"))
        await migration.migrate()
    check = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with check.begin() as connection:
        columns = await connection.run_sync(lambda sync: [c["name"] for c in inspect(sync).get_columns("label_log")])
    await check.dispose()
    assert columns.count("text") == 1


def test_legacy_ingest_has_null_text(client):
    assert client.post("/v1/labels/ingest", json=item()).status_code == 200
    response = detail(client)
    assert response.status_code == 200
    assert response.json()["text"] is None


def test_single_detail_preserves_whitespace_unicode(client):
    source = "  Aspirin ☃️\n<b>literal</b>  "
    payload = item()
    payload["text"] = source
    assert client.post("/v1/labels/ingest", json=payload).status_code == 200
    body = detail(client).json()
    assert body["text"] == source
    assert body["verified_at"] is None
    assert body["factors"] == payload["factors"]


def test_batch_round_trip_and_blank_semantics(client):
    rows = [item(label_id="a"), item(label_id="b")]
    rows[0]["text"] = "Line one\nLine two"
    rows[1]["text"] = ""
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "demo", "items": rows})
    assert response.status_code == 200, response.text
    assert detail(client, label="a").json()["text"] == rows[0]["text"]
    assert detail(client, label="b").json()["text"] is None


def test_oversized_text_rejects_whole_batch(client):
    rows = [item(label_id="a"), item(label_id="b")]
    rows[0]["text"] = "okay"
    rows[1]["text"] = "é" * 16385
    response = client.post("/v1/labels/ingest/batch", json={"domain_id": "demo", "items": rows})
    assert response.status_code == 422
    assert client.get("/v1/labels/demo/pending").status_code == 404
    async def usage():
        async with client.app.state.session_factory() as session:
            key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hashlib.sha256(b"test-key").hexdigest()))
            return key.labels_today
    assert asyncio.run(usage()) == 0


def test_anonymous_health_ignores_numeric_text(client):
    frame = pd.DataFrame([{"label_id": str(i), "category": "NER", "verified_outcome": True,
                           "factor_a": .4, "factor_b": .6, "text": "123"} for i in range(200)])
    response = client.post("/v1/label-health/analyze", files={"file": ("labels.csv", frame.to_csv(index=False))},
                           headers={"X-Api-Key": ""})
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["factor_count"] == 2


def test_detail_tenant_and_domain_isolation(client):
    alice = tenant_key(client, "alice")
    bob = tenant_key(client, "bob")
    payload = item()
    payload["text"] = "private"
    assert client.post("/v1/labels/ingest", json=payload, headers=alice).status_code == 200
    assert detail(client, headers=alice).json()["text"] == "private"
    assert detail(client, headers=bob).status_code == 404
    assert detail(client, domain="other", headers=alice).status_code == 404


def test_deep_detail_and_bounded_preview(client):
    payload = item(label_id="first")
    payload["text"] = "😀" * 81 + "<b>"
    assert client.post("/v1/labels/ingest", json=payload).status_code == 200
    async def seed():
        async with client.app.state.session_factory() as session:
            session.add_all([LabelLog(domain_id="demo", tenant_id="", label_id=f"deep-{i}",
                category="NER", factors_json={"confidence": .5, "difficulty": .5},
                recommended_action="approve", confidence=.1, text=f"deep text {i}") for i in range(201)])
            await session.commit()
    asyncio.run(seed())
    rows = client.get("/v1/labels/demo/pending", params={"limit": 200}).json()
    assert len(rows) == 200
    assert all(row["label_id"] != "first" for row in rows)
    assert detail(client, label="first").json()["text"] == payload["text"]
    async def change_confidence():
        async with client.app.state.session_factory() as session:
            row = await session.scalar(select(LabelLog).where(LabelLog.label_id == "first"))
            row.confidence = 0.0
            await session.commit()
    asyncio.run(change_confidence())
    preview = client.get("/v1/labels/demo/pending", params={"limit": 1}).json()[0]
    assert preview["text_preview"] == "😀" * 80
    assert "text" not in preview
