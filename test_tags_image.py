"""Audited multilabel tag edits on SQLite and PostgreSQL."""
import os

import pytest

from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    with open_tasks_client(tmp_path) as result:
        yield result


def seed(client):
    response = client.post("/v1/labels/ingest", json={
        "domain_id": "medical", "label_id": "multi-1", "category": "SENTIMENT",
        "factors": {"model_confidence": 0.7, "item_difficulty": 0.2},
        "text": "The product arrived quickly."})
    assert response.status_code == 200, response.text
    return detail(client)


def detail(client):
    response = client.get("/v1/labels/medical/items/multi-1")
    assert response.status_code == 200, response.text
    return response.json()


def edit(client, revision, tags):
    return client.post("/v1/labels/medical/items/multi-1/relabel", json={
        "category": "SENTIMENT", "idempotency_token": revision, "tags": tags})


def test_relabel_with_valid_tags(client):
    before = seed(client)
    response = edit(client, before["revision_id"], ["positive", "product_quality", "urgent"])
    assert response.status_code == 200, response.text
    assert detail(client)["content"]["tags"] == ["positive", "product_quality", "urgent"]


def test_duplicate_tags_are_removed_case_insensitively(client):
    before = seed(client)
    response = edit(client, before["revision_id"], ["Urgent", "urgent", " PRODUCT_QUALITY ", "product_quality"])
    assert response.status_code == 200, response.text
    assert detail(client)["content"]["tags"] == ["Urgent", "PRODUCT_QUALITY"]


def test_more_than_twenty_tags_is_rejected(client):
    before = seed(client)
    response = edit(client, before["revision_id"], [f"tag-{index}" for index in range(21)])
    assert response.status_code == 422
    assert detail(client)["revision_id"] == before["revision_id"]


def test_tag_longer_than_fifty_characters_is_rejected(client):
    before = seed(client)
    response = edit(client, before["revision_id"], ["x" * 51])
    assert response.status_code == 422
    assert detail(client)["revision_id"] == before["revision_id"]


def test_plain_text_is_upgraded_to_multilabel_content(client):
    before = seed(client)
    assert before["content"] is None
    response = edit(client, before["revision_id"], ["positive"])
    assert response.status_code == 200, response.text
    after = detail(client)
    assert after["revision_id"] != before["revision_id"]
    assert after["content"]["content_type"] == "text_multilabel"
    assert after["content"]["spans"] == []


def test_empty_tags_clears_existing_tags(client):
    before = seed(client)
    first = edit(client, before["revision_id"], ["positive", "urgent"])
    assert first.status_code == 200, first.text
    cleared = edit(client, first.json()["revision_id"], [])
    assert cleared.status_code == 200, cleared.text
    assert detail(client)["content"]["tags"] == []
