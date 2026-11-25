import pytest

from ..fixtures.factory import NULL, NUMBER, OPTIONAL_NUMBER, TIER_STATUS, Wire, shape

pytestmark = pytest.mark.anyio

ITEM = {"label_id": "new", "category": "A", "factors": {"quality": .8, "difficulty": .2}}
INGEST = {"label_id": str, "decision_id": str, "recommended_action": str, "confidence": NUMBER,
          "factors_used": dict, "category": str, "conservation_status": str, "tier": str,
          "action_policy": str, "tier_status": TIER_STATUS, "auto_accepted": bool}


async def test_ingest(wire: Wire):
    response = await wire.request("POST", "/v1/labels/ingest", json={"domain_id": "demo", **ITEM},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE label_id='new'"))
    shape(response.json(), INGEST)


async def test_batch(wire: Wire):
    response = await wire.request("POST", "/v1/labels/ingest/batch", json={"domain_id": "demo", "items": [ITEM]},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE label_id='new'"))
    assert response.json()["results"]
    shape(response.json(), {"batch_size": int, "results": [INGEST]})


async def test_verify(wire: Wire):
    await wire.factory.domain()
    await wire.factory.label()
    response = await wire.request("POST", "/v1/labels/verify", json={"domain_id": "demo", "label_id": "L1",
                                  "actual_action": "approve", "verified_outcome": True},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE verified_outcome IS TRUE"))
    shape(response.json(), {"label_id": str, "action_taken": str, "was_correct": bool, "engine_updated": bool,
                            "new_accuracy": OPTIONAL_NUMBER})


async def test_bulk(wire: Wire):
    await wire.factory.domain()
    await wire.factory.label()
    response = await wire.request("POST", "/v1/labels/demo/bulk-verify",
                                  json={"label_ids": ["L1"], "action": "approve", "outcome": False},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE verified_outcome IS FALSE"))
    shape(response.json(), {"processed": int, "skipped": int, "errors": [{"label_id": str, "error": str}]})


async def test_sample(wire: Wire):
    response = await wire.request("POST", "/v1/labels/medical-ner-demo-v1/sample",
                                  before_send=wire.committed("SELECT count(*) FROM label_log", 12))
    shape(response.json(), {"domain_id": str, "created": int, "existing": int, "pending": int})


async def test_task(wire: Wire):
    response = await wire.request("POST", "/v1/labels/demo/tasks", status=201,
                                  json={"label_id": "task", "text": "Synthetic source"},
                                  before_send=wire.committed("SELECT text FROM label_log WHERE label_id='task'", "Synthetic source"))
    shape(response.json(), {"label_id": str, "status": str, "category": (str, NULL)})


async def test_pending(wire: Wire):
    await wire.factory.domain()
    await wire.factory.label()
    response = await wire.request("GET", "/v1/labels/demo/pending")
    assert response.headers["x-total-count"].isdigit() and response.json()
    shape(response.json(), [{"label_id": str, "category": str, "annotator_id": (str, NULL),
                             "confidence": NUMBER, "recommended_action": str, "text_preview": (str, NULL),
                             "factors": dict}])
    assert any(isinstance(value, (int, float)) for value in response.json()[0]["factors"].values())


async def test_get_guidelines(wire: Wire):
    await wire.factory.domain()
    shape((await wire.request("GET", "/v1/domains/demo/guidelines")).json(), {"guidelines": (str, NULL)})


async def test_put_guidelines(wire: Wire):
    await wire.factory.domain()
    response = await wire.request("PUT", "/v1/domains/demo/guidelines", json={"guidelines": "Sample"},
                                  before_send=wire.committed("SELECT guidelines FROM domains", "Sample"))
    shape(response.json(), {"guidelines": str})


async def test_autonomy(wire: Wire):
    await wire.factory.domain()
    response = await wire.request("GET", "/v1/domains/demo/autonomy")
    shape(response.json(), {"domain_id": str, "overall_tier": str, "categories": [TIER_STATUS]})
