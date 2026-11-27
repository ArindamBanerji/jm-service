import pytest
from sqlalchemy import select

from db.models import ConnectorConfigRow

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
        async with wire.factory.sessions() as fresh:
            row = await fresh.get(ConnectorConfigRow, ("contract-tenant", "p"))
            assert row is not None and row.config_json["domain_id"] == "studio"

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


async def test_pending_binding_and_watermark_survive_project_name_separators(wire: Wire):
    stamp = "2026-11-25T10:00:00Z"
    for project, annotation_id, task_id in (("team:one", "review", 1), ("team", "one:review", 2)):
        body = annotation(task_id=task_id, stamp=stamp)
        body["project"] = project
        body["annotation"]["id"] = annotation_id
        body["task"]["data"] = dict(body["task"]["data"], ground_truth=None)
        pending = await wire.request("POST", "/v1/label-studio/webhook", headers=HEADERS, json=body)
        assert pending.json()["status"] == "pending_ground_truth"
        body["task"]["data"]["ground_truth"] = True
        del body["annotation"]["updated_at"]
        await wire.request("POST", "/v1/label-studio/webhook", headers=HEADERS, status=409, json=body)
        body["annotation"]["updated_at"] = "2026-11-25T11:00:00Z"
        processed = await wire.request("POST", "/v1/label-studio/webhook", headers=HEADERS, json=body)
        assert processed.json()["status"] == "processed"
