"""Structured label content contracts, exercised on SQLite and PostgreSQL."""
import asyncio
import hashlib

from sqlalchemy import select

from db.models import ApiKey, LabelContent, LabelLog
from test_tasks import client, task


def post_content(client, spans=None, tags=None, content_type="text_ner", label_id="item-1", headers=None):
    return client.post(f"/v1/labels/medical/items/{label_id}/content", json={
        "content_type": content_type, "spans": spans or [], "tags": tags or [],
    }, headers=headers)


def span(start, end, text, label="MEDICATION"):
    return {"start": start, "end": end, "label": label, "text": text}


def test_valid_ner_spans_use_unicode_code_points(client):
    source = "😀 Aspirin e\u0301 Aspirin"
    assert task(client, category="MEDICATION", source=source).status_code == 201
    first = source.index("Aspirin")
    second = source.rindex("Aspirin")
    payload = [span(second, second + 7, "Aspirin"), span(0, 1, "😀"),
               span(first, first + 7, "Aspirin"), span(source.index("e"), source.index("e") + 2, "e\u0301")]
    response = post_content(client, spans=payload)
    assert response.status_code == 201, response.text
    assert response.json() == {"label_id": "item-1", "content_type": "text_ner", "spans_count": 4}
    stored = client.get("/v1/labels/medical/items/item-1").json()["content"]["spans"]
    assert [row["start"] for row in stored] == sorted(row["start"] for row in payload)
    assert post_content(client, spans=payload).status_code == 409
    token = client.get("/v1/labels/medical/items/item-1").json()["revision_id"]
    assert client.post("/v1/labels/medical/items/item-1/relabel", json={
        "category": "MEDICATION", "idempotency_token": token}).status_code == 200
    assert client.get("/v1/labels/medical/items/item-1").json()["content"]["spans"] == stored


def test_spans_need_source_text(client):
    body = {"domain_id": "medical", "label_id": "item-1", "category": "MEDICATION",
            "factors": {"model_confidence": 0.5, "item_difficulty": 0.5}}
    assert client.post("/v1/labels/ingest", json=body).status_code == 200
    assert post_content(client, spans=[span(0, 1, "A")]).status_code == 422


def test_overlapping_spans_rejected(client):
    assert task(client, category="MEDICATION", source="Aspirin").status_code == 201
    assert post_content(client, spans=[span(0, 4, "Aspi"), span(3, 7, "irin")]).status_code == 422


def test_out_of_range_offset_rejected(client):
    assert task(client, category="MEDICATION", source="Aspirin").status_code == 201
    assert post_content(client, spans=[span(0, 8, "Aspirin")]).status_code == 422


def test_empty_span_rejected(client):
    assert task(client, category="MEDICATION", source="Aspirin").status_code == 201
    assert post_content(client, spans=[span(2, 2, "s")]).status_code == 422


def test_detail_includes_content_and_fk_cascades(client):
    assert task(client, category="MEDICATION", source="Aspirin").status_code == 201
    assert post_content(client, spans=[span(0, 7, "Aspirin")]).status_code == 201
    detail = client.get("/v1/labels/medical/items/item-1")
    assert detail.status_code == 200
    assert detail.json()["text"] == "Aspirin"
    assert detail.json()["content"] == {
        "content_type": "text_ner", "spans": [span(0, 7, "Aspirin")],
        "tags": [], "image_url": None,
    }
    assert "content" not in client.get("/v1/labels/medical/pending").json()[0]
    async def delete_label():
        async with client.app.state.session_factory() as session:
            row = await session.scalar(select(LabelLog).where(LabelLog.label_id == "item-1"))
            assert row is not None
            await session.delete(row)
            await session.commit()
            assert await session.scalar(select(LabelContent)) is None
    asyncio.run(delete_label())


def test_multilabel_tags_use_domain_vocabulary(client):
    assert task(client, category="MEDICATION").status_code == 201
    assert task(client, label_id="item-2", category="CONDITION").status_code == 201
    response = post_content(client, content_type="text_multilabel",
                            tags=["MEDICATION", "CONDITION"])
    assert response.status_code == 201, response.text
    assert response.json()["tags_count"] == 2
    assert client.get("/v1/labels/medical/items/item-1").json()["content"]["tags"] == ["MEDICATION", "CONDITION"]
    assert post_content(client, content_type="text_multilabel", tags=["UNKNOWN"], label_id="item-2").status_code == 422
    path = "/v1/labels/medical/items/item-2/content"
    assert client.post(path, json={"content_type": "image_classification", "image_url": "data:image/png;base64,AA"}).status_code == 422
    assert client.post(path, json={"content_type": "image_classification", "image_url": "http://example.com/image.png"}).status_code == 422
    assert client.post(path, json={"content_type": "image_classification", "image_url": "https://example.com/image.png"}).status_code == 201


def test_content_is_tenant_scoped(client):
    assert task(client, category="MEDICATION", source="Aspirin").status_code == 201
    async def other_key():
        async with client.app.state.session_factory() as session:
            session.add(ApiKey(key_hash=hashlib.sha256(b"content-other").hexdigest(),
                               tenant_id="content-other", tenant_name="Other"))
            await session.commit()
    asyncio.run(other_key())
    other = {"X-Api-Key": "content-other"}
    assert post_content(client, spans=[span(0, 7, "Aspirin")], headers=other).status_code == 404
    assert client.get("/v1/labels/medical/items/item-1", headers=other).status_code == 404
    assert post_content(client, spans=[span(0, 7, "Aspirin")]).status_code == 201
    assert client.get("/v1/labels/medical/items/item-1", headers=other).status_code == 404
