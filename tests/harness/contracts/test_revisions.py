import pytest

from ..fixtures.factory import NULL, OPTIONAL_NUMBER, Wire, shape

pytestmark = pytest.mark.anyio

DETAIL = {"domain_id": str, "label_id": str, "category": (str, NULL), "annotator_id": (str, NULL),
          "factors": dict, "recommended_action": (str, NULL), "confidence": OPTIONAL_NUMBER,
          "text": (str, NULL), "actual_action": (str, NULL), "verified_outcome": (bool, NULL),
          "verified_at": (str, NULL), "revision_id": str, "previous_category": (str, NULL),
          "status": str, "content": {"content_type": str, "spans": list, "tags": [str],
                                     "image_url": (str, NULL)}}


@pytest.mark.parametrize("path", ["/v1/labels/demo/items/L1", "/v1/labels/demo/L1"])
async def test_detail(wire: Wire, path):
    await wire.factory.domain()
    await wire.factory.label()
    await wire.request("POST", "/v1/labels/demo/items/L1/content", status=201,
                       json={"content_type": "text_multilabel", "tags": ["A"]})
    body = (await wire.request("GET", path)).json()
    shape(body, DETAIL)
    assert body["content"]["tags"] == ["A"]


def test_detail_contract_rejects_missing_content_field():
    from ..fixtures.factory import shape
    import pytest

    with pytest.raises(AssertionError, match="tags"):
        shape({"content": {"content_type": "text_multilabel", "spans": [], "image_url": None}},
              {"content": DETAIL["content"]})


async def test_relabel(wire: Wire):
    await wire.factory.domain()
    await wire.factory.label()
    detail = await wire.request("GET", "/v1/labels/demo/items/L1")
    response = await wire.request("POST", "/v1/labels/demo/items/L1/relabel",
                                  json={"idempotency_token": detail.json()["revision_id"], "category": "B"},
                                  before_send=wire.committed("SELECT count(*) FROM label_log WHERE prior_revision_id IS NOT NULL"))
    shape(response.json(), {"label_id": str, "category": str, "revision_id": str, "previous_category": (str, NULL)})


async def test_content(wire: Wire):
    await wire.factory.domain()
    await wire.factory.label()
    response = await wire.request("POST", "/v1/labels/demo/items/L1/content", status=201,
                                  json={"content_type": "text_multilabel", "tags": ["A"]},
                                  before_send=wire.committed("SELECT count(*) FROM label_content WHERE content_type='text_multilabel'"))
    shape(response.json(), {"label_id": str, "content_type": str, "tags_count": int})
