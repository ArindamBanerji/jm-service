"""Audited NER span edits on SQLite and PostgreSQL."""
import os

import pytest

from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    with open_tasks_client(tmp_path) as result:
        yield result


def seed(client, label_id="ner-1", source="😀 John Smith joined Acme."):
    body = {"domain_id": "medical", "label_id": label_id,
            "category": "PERSON", "factors": {"model_confidence": 0.7, "item_difficulty": 0.2}}
    if source is not None:
        body["text"] = source
    response = client.post("/v1/labels/ingest", json=body)
    assert response.status_code == 200, response.text
    return client.get(f"/v1/labels/medical/items/{label_id}").json()


def edit(client, revision, spans, label_id="ner-1", category="PERSON"):
    return client.post(f"/v1/labels/medical/items/{label_id}/relabel",
                       json={"category": category, "idempotency_token": revision, "spans": spans})


def test_add_span_derives_text_and_creates_audited_revision(client):
    original = seed(client)
    response = edit(client, original["revision_id"], [{"start": 2, "end": 12, "label": "PERSON"}])
    assert response.status_code == 200, response.text
    detail = client.get("/v1/labels/medical/items/ner-1").json()
    assert detail["revision_id"] == response.json()["revision_id"] != original["revision_id"]
    assert detail["category"] == "PERSON"
    assert detail["content"]["content_type"] == "text_ner"
    assert detail["content"]["spans"] == [
        {"start": 2, "end": 12, "label": "PERSON", "text": "John Smith"}]


def test_edit_existing_spans_and_clear_them(client):
    original = seed(client)
    created = edit(client, original["revision_id"], [{"start": 2, "end": 12, "label": "PERSON"}])
    assert created.status_code == 200, created.text
    changed = edit(client, created.json()["revision_id"],
                   [{"start": 2, "end": 12, "label": "CUSTOM", "text": "John Smith"}])
    assert changed.status_code == 200, changed.text
    assert client.get("/v1/labels/medical/items/ner-1").json()["content"]["spans"][0]["label"] == "CUSTOM"
    cleared = edit(client, changed.json()["revision_id"], [])
    assert cleared.status_code == 200, cleared.text
    assert client.get("/v1/labels/medical/items/ner-1").json()["content"]["spans"] == []


@pytest.mark.parametrize("spans", [
    [{"start": 2, "end": 5, "label": "PERSON"}, {"start": 4, "end": 12, "label": "PERSON"}],
    [{"start": 2, "end": 2, "label": "PERSON"}],
    [{"start": 0, "end": 100, "label": "PERSON"}],
    [{"start": 2, "end": 12, "label": "PERSON", "text": "incorrect"}],
    [{"start": 2, "end": 12, "label": " "}],
])
def test_invalid_spans_leave_revision_unchanged(client, spans):
    original = seed(client)
    assert edit(client, original["revision_id"], spans).status_code == 422
    assert client.get("/v1/labels/medical/items/ner-1").json()["revision_id"] == original["revision_id"]


def test_missing_text_and_span_limit(client):
    original = seed(client, source=None)
    response = edit(client, original["revision_id"], [{"start": 0, "end": 1, "label": "PERSON"}])
    assert response.status_code == 422
    assert response.json()["detail"] == "Cannot edit spans without stored text"
    assert edit(client, original["revision_id"], [
        {"start": 0, "end": 1, "label": "PERSON"} for _ in range(101)]).status_code == 422


def test_stale_token_cannot_overwrite_spans(client):
    original = seed(client)
    assert edit(client, original["revision_id"], [{"start": 2, "end": 12, "label": "PERSON"}]).status_code == 200
    assert edit(client, original["revision_id"], []).status_code == 409
    assert len(client.get("/v1/labels/medical/items/ner-1").json()["content"]["spans"]) == 1
