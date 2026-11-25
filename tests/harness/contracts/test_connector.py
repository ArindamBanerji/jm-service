import json

import pytest

from ..fixtures.factory import NULL, NUMBER, Wire, shape

pytestmark = pytest.mark.anyio

HEADERS = {"X-LS-Token": "harness-ls"}
TASK = {"id": 1, "data": {"category": "A", "quality": .8, "difficulty": .2, "ground_truth": "approve"}}


def annotation(action="approve", task_id=1, kind="ANNOTATION_CREATED", stamp=None):
    data = {"id": "ann", "completed_by": 7, "actual_action": action}
    if stamp is not None:
        data["updated_at"] = stamp
    return {"project": "p", "action": kind, "task": {**TASK, "id": task_id}, "annotation": data}


async def test_configure(wire: Wire):
    async def saved():
        data = json.loads((wire.directory / "connector.json").read_text(encoding="utf8"))
        assert data["contract-tenant\0p"]["domain_id"] == "studio"

    response = await wire.request("POST", "/v1/label-studio/configure", headers=HEADERS, before_send=saved,
                                  json={"project_id": "p", "domain_id": "studio",
                                        "factor_map": {"quality": "data.quality", "difficulty": "data.difficulty"}})
    shape(response.json(), {"project_id": str, "domain_id": str, "factor_map": dict,
                            "public_domain_id": (str, NULL), "tenant_id": str, "category_field": str,
                            "ground_truth_field": (str, NULL)})


async def test_setup(wire: Wire):
    response = await wire.request("POST", "/v1/label-studio/setup", headers=HEADERS, json={"project": "p"},
                                  before_send=wire.committed("SELECT count(*) FROM domains WHERE public_domain_id='studio'"))
    shape(response.json(), {"model_version": str})


async def test_predict(wire: Wire):
    response = await wire.request("POST", "/v1/label-studio/predict", headers=HEADERS,
                                  json={"project": "p", "tasks": [TASK]},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE label_id='1'"))
    assert response.json()["results"]
    shape(response.json(), {"results": [{"result": list, "score": NUMBER, "model_version": str,
                                        "eligibility": {"checks_passed": [str], "checks_failed": [str]}}]})


async def test_webhook(wire: Wire):
    # A true forward correction exercises revision creation at the existing webhook endpoint.
    await wire.request("POST", "/v1/label-studio/webhook", headers=HEADERS, json=annotation())
    response = await wire.request("POST", "/v1/label-studio/webhook", headers=HEADERS,
                                  json=annotation("reject", kind="ANNOTATION_UPDATED"),
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE prior_revision_id IS NOT NULL"))
    shape(response.json(), {"status": str})


async def test_health(wire: Wire):
    shape((await wire.request("GET", "/v1/label-studio/health")).json(), {"status": str, "model_version": str})
