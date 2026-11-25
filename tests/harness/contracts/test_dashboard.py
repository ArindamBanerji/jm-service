import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from db.models import LabelLog

from ..fixtures.factory import NULL, NUMBER, OPTIONAL_NUMBER, TIER_STATUS, Wire, shape

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("route,schema", [
    ("overview", {"domain_id": str, "overall_accuracy": OPTIONAL_NUMBER, "total_verified": int,
                  "total_labels": int, "categories": [TIER_STATUS], "inversion": (dict, NULL),
                  "compounding_curve": [{"verified_count": int, "accuracy": NUMBER, "timestamp": str}], "generated_at": str}),
    ("corrections", {"domain_id": str, "total_corrections": int, "correction_rate": OPTIONAL_NUMBER,
                     "patterns": [{"category": str, "recommended_action": str, "actual_action": str,
                                   "count": int, "percentage_of_category": NUMBER}], "top_pattern": (dict, NULL)}),
    ("annotators", {"domain_id": str, "annotators": [{"annotator_id": str, "total_labels": int,
                    "verified_count": int, "accuracy": OPTIONAL_NUMBER, "strongest_category": (str, NULL),
                    "weakest_category": (str, NULL), "last_active": str}]}),
    ("factors", {"domain_id": str, "factor_names": [str], "inversion": (dict, NULL),
                 "factor_stats": [{"factor": str, "mean_correct": OPTIONAL_NUMBER,
                                   "mean_incorrect": OPTIONAL_NUMBER, "predictive_gap": OPTIONAL_NUMBER}]}),
    ("compounding", {"domain_id": str, "category": (str, NULL), "points": [
                     {"index": int, "verified_count": int, "running_accuracy": NUMBER, "timestamp": str}],
                     "baseline_accuracy": OPTIONAL_NUMBER, "current_accuracy": OPTIONAL_NUMBER,
                     "improvement": OPTIONAL_NUMBER}),
    ("iaa", {"pairs": [{"annotator_a": str, "annotator_b": str, "kappa": OPTIONAL_NUMBER, "overlap_count": int}],
             "overall_kappa": OPTIONAL_NUMBER, "total_overlapping_labels": int}),
], ids=["overview", "corrections", "annotators", "factors", "compounding", "iaa"])
async def test_dashboard(wire: Wire, route, schema):
    domain = await wire.factory.domain()
    await wire.factory.engine(domain)
    for label_id, annotator, category, outcome in (("D1", "ann-a", "A", True),
                                                   ("D2", "ann-b", "B", False)):
        await wire.factory.label(label_id)
        async with wire.factory.sessions.begin() as session:
            row = await session.scalar(select(LabelLog).where(LabelLog.label_id == label_id))
            assert row is not None
            row.annotator_id = annotator
            row.category = category
            row.source_task_id = "shared-task"
            row.actual_action = "reject"
            row.verified_outcome = outcome
            row.verified_at = datetime.now(timezone.utc)
    body = (await wire.request("GET", f"/v1/dashboard/demo/{route}")).json()
    shape(body, schema)
    collection = {"overview": "compounding_curve", "corrections": "patterns",
                  "annotators": "annotators", "compounding": "points", "iaa": "pairs"}.get(route)
    if collection is not None:
        assert body[collection], (route, collection)
