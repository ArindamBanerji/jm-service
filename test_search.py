"""Tenant-scoped pending search on SQLite and PostgreSQL."""
import os

import pytest

from test_tasks import open_tasks_client


@pytest.fixture
def client(tmp_path, monkeypatch):
    if url := os.getenv("DLJ_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", url)
    with open_tasks_client(tmp_path) as result:
        yield result


def seed(client, rows):
    items = [dict(label_id=label_id, category=category, annotator_id=annotator,
                  text=source, factors={"model_confidence": 0.7, "item_difficulty": 0.2})
             for label_id, category, annotator, source in rows]
    response = client.post("/v1/labels/ingest/batch",
                           json={"domain_id": "medical", "items": items})
    assert response.status_code == 200, response.text


def pending(client, **params):
    response = client.get("/v1/labels/medical/pending", params=params)
    assert response.status_code == 200, response.text
    return response


def ids(response):
    return [row["label_id"] for row in response.json()]


def test_label_id_substring(client):
    seed(client, [("alpha-one", "MEDICATION", None, None),
                  ("beta-two", "MEDICATION", None, None),
                  ("alpha-three", "MEDICATION", None, None)])
    response = pending(client, search="ALPHA", sort_by="label_id")
    assert ids(response) == ["alpha-one", "alpha-three"]
    assert response.headers["X-Total-Count"] == "2"


def test_annotator_case_insensitive(client):
    seed(client, [("one", "MEDICATION", "DrLee", None),
                  ("two", "MEDICATION", "SAM", None),
                  ("three", "MEDICATION", "drLEE", None)])
    response = pending(client, search="dRlEe", sort_by="label_id")
    assert ids(response) == ["one", "three"]
    assert response.headers["X-Total-Count"] == "2"


def test_category_substring(client):
    seed(client, [("one", "MEDICATION", None, None),
                  ("two", "CONDITION", None, None),
                  ("three", "MEDICATION", None, None)])
    response = pending(client, search="dica", sort_by="label_id")
    assert ids(response) == ["one", "three"]
    assert response.headers["X-Total-Count"] == "2"


def test_text_content_substring(client):
    seed(client, [("one", "TEST", None, "Aspirin appears in the list."),
                  ("two", "TEST", None, "A different medical note."),
                  ("three", "TEST", None, "Patient took ASPIRIN today.")])
    response = pending(client, search="aspirin", sort_by="label_id")
    assert ids(response) == ["one", "three"]
    assert response.headers["X-Total-Count"] == "2"


def test_search_paginates_after_filter_with_scoped_total(client):
    seed(client, [(f"hit-{index}", "MEDICATION" if index < 4 else "CONDITION", None, None)
                  for index in range(5)] + [("miss", "MEDICATION", None, None)])
    response = pending(client, search="HIT", category="MEDICATION", limit=2, offset=2,
                       sort_by="label_id", sort_order="desc")
    assert response.headers["X-Total-Count"] == "4"
    assert ids(response) == ["hit-1", "hit-0"]
    assert ids(pending(client, search="hit", category="MEDICATION", limit=2,
                       sort_by="label_id", sort_order="asc")) == ["hit-0", "hit-1"]


def test_empty_and_whitespace_search_are_unfiltered(client):
    seed(client, [("one", "MEDICATION", None, None),
                  ("two", "CONDITION", None, None)])
    baseline = pending(client, sort_by="label_id")
    for value in ("", "   "):
        response = pending(client, search=value, sort_by="label_id")
        assert ids(response) == ids(baseline)
        assert response.headers["X-Total-Count"] == "2"
    assert client.get("/v1/labels/medical/pending", params={"search": "x" * 201}).status_code == 422
