"""Pending queue pagination and server-side ordering."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from auth import scoped_domain_id
from db.models import LabelLog
from test_labeling_router import client, item, tenant_key


def seed_rows(client, rows, *, tenant="", key="test-key"):
    for index, category in enumerate(sorted({row.get("category", "NER") for row in rows})):
        assert client.post("/v1/labels/ingest", json=item(label_id=f"__setup_{index}", category=category),
                           headers={"X-Api-Key": key}).status_code == 200

    async def write():
        scoped = scoped_domain_id(tenant, "demo")
        async with client.app.state.session_factory() as session:
            await session.execute(delete(LabelLog).where(LabelLog.domain_id == scoped,
                                                         LabelLog.tenant_id == tenant))
            session.add_all([LabelLog(
                domain_id=scoped, tenant_id=tenant, label_id=row["label_id"],
                category=row.get("category", "NER"), annotator_id=row.get("annotator_id"),
                confidence=row.get("confidence", .5), recommended_action="approve",
                text=row.get("text"), factors_json={"confidence": .5, "difficulty": .5},
                scored_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index),
            ) for index, row in enumerate(rows)])
            await session.commit()
    asyncio.run(write())


def test_legacy_defaults(client):
    seed_rows(client, [{"label_id": f"p-{i:03d}", "confidence": (60 - i) / 100} for i in range(60)])
    response = client.get("/v1/labels/demo/pending")
    assert response.status_code == 200
    assert isinstance(response.json(), list) and len(response.json()) == 50
    assert response.headers["X-Total-Count"] == "60"
    assert response.json()[0]["label_id"] == "p-059"
    assert [row["confidence"] for row in response.json()] == sorted(row["confidence"] for row in response.json())


def test_second_page_and_total(client):
    source = 'Quoted, "multiline"\n' + 'é' * 90
    seed_rows(client, [{"label_id": f"page-{i:03d}", "text": source if i == 204 else None}
                       for i in range(205)])
    response = client.get("/v1/labels/demo/pending?limit=200&offset=200&sort_by=label_id")
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "205"
    assert [row["label_id"] for row in response.json()] == [f"page-{i:03d}" for i in range(200, 205)]
    assert response.json()[-1]["text_preview"] == source[:80]
    assert client.get("/v1/labels/demo/page-204").json()["text"] == source


def test_sort_across_pages_and_nulls(client):
    rows = [{"label_id": f"tie-{i:03d}", "confidence": .5,
             "annotator_id": None if i % 10 == 0 else "ann"} for i in range(211)]
    rows.extend([{"label_id": '=SUM(1,2)', "confidence": .5},
                 {"label_id": 'quote,"line\nbreak', "confidence": .5}])
    seed_rows(client, rows)
    for order, expected in (("asc", sorted(str(row["label_id"]) for row in rows)),
                            ("desc", sorted((str(row["label_id"]) for row in rows), reverse=True))):
        first = client.get(f"/v1/labels/demo/pending?sort_by=label_id&sort_order={order}&limit=200").json()
        second = client.get(f"/v1/labels/demo/pending?sort_by=label_id&sort_order={order}&limit=200&offset=200").json()
        assert [row["label_id"] for row in first + second] == expected
    tied_first = client.get("/v1/labels/demo/pending?sort_by=confidence&limit=200").json()
    tied_second = client.get("/v1/labels/demo/pending?sort_by=confidence&limit=200&offset=200").json()
    assert len({row["label_id"] for row in tied_first + tied_second}) == len(rows)
    for order in ("asc", "desc"):
        response = client.get(f"/v1/labels/demo/pending?sort_by=annotator_id&sort_order={order}&limit=200")
        assert [row["annotator_id"] for row in response.json()[:10]] == ["ann"] * 10


def test_invalid_sort_order_offset(client):
    seed_rows(client, [{"label_id": "one"}])
    for query in ("sort_by=text", "sort_order=sideways", "offset=-1", "limit=201", "limit=0"):
        assert client.get(f"/v1/labels/demo/pending?{query}").status_code == 422


def test_category_scoped_total(client):
    rows = [{"label_id": f"cat-{i:03d}", "category": "A" if i < 70 else "B"} for i in range(120)]
    seed_rows(client, rows)
    response = client.get("/v1/labels/demo/pending?category=B&limit=20&offset=20")
    assert response.headers["X-Total-Count"] == "50"
    assert len(response.json()) == 20
    assert {row["category"] for row in response.json()} == {"B"}
    empty = client.get("/v1/labels/demo/pending?category=missing")
    assert empty.headers["X-Total-Count"] == "0" and empty.json() == []


def test_tenant_isolation_and_out_of_range(client):
    a, b = tenant_key(client, "queue-a"), tenant_key(client, "queue-b")
    seed_rows(client, [{"label_id": "private-a"}], tenant="queue-a", key=a["X-Api-Key"])
    seed_rows(client, [{"label_id": "private-b"}], tenant="queue-b", key=b["X-Api-Key"])
    first = client.get("/v1/labels/demo/pending", headers=a)
    assert first.headers["X-Total-Count"] == "1"
    assert [row["label_id"] for row in first.json()] == ["private-a"]
    beyond = client.get("/v1/labels/demo/pending?offset=200", headers=a)
    assert beyond.status_code == 200 and beyond.json() == []
    assert beyond.headers["X-Total-Count"] == "1"
    assert [row["label_id"] for row in client.get("/v1/labels/demo/pending", headers=b).json()] == ["private-b"]
