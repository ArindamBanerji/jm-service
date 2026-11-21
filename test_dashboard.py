"""Dashboard contracts on the same SQLite-backed ingest and verify routes used by the review UI."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from test_labeling_router import ingest, item, open_client, verify
from dashboard_router import router
from db import repository
from db.models import LabelLog
from jm_core import DomainConfig, JudgmentMemoryEngine


BASE = "/v1/dashboard/demo"
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path):
    with open_client(tmp_path) as http:
        http.app.include_router(router)
        yield http


def row(index: int, correct: bool | None = True, *, category: str = "NER", who: str | None = None,
        original: str = "approve", actual: str = "approve", signal: float = .5) -> LabelLog:
    scored = START + timedelta(minutes=index)
    return LabelLog(domain_id="demo", label_id=str(index), category=category, annotator_id=who,
                    recommended_action=original, actual_action=actual if correct is not None else None,
                    scored_at=scored, verified_at=scored + timedelta(seconds=1) if correct is not None else None,
                    verified_outcome=correct, factors_json={"stable": .5, "signal": signal}, confidence=.5)


def seed(client, rows: list[LabelLog], *, train_project: bool = False) -> None:
    async def write():
        async with client.app.state.session_factory() as session:
            config = DomainConfig("demo", "Demo", ["stable", "signal"], ["NER", "intent"], ["approve", "reject"])
            await repository.create_domain(session, "demo", "Demo", config)
            session.add_all(rows)
            if train_project:
                engine = JudgmentMemoryEngine(config)
                for entry in rows:
                    if entry.verified_outcome is not None and entry.actual_action is not None:
                        score = engine.score(entry.factors_json, entry.category)
                        engine.learn(score.decision_id, entry.actual_action, score.recommended_action == entry.actual_action,
                                     outcome_correct=entry.verified_outcome)
                await repository.save_engine_state(session, "demo", None, engine)
            await session.commit()
    asyncio.run(write())


def get(client: TestClient, view: str) -> dict:
    response = client.get(f"{BASE}/{view}")
    assert response.status_code == 200, response.text
    return response.json()


def test_overview_basic(client):
    seed(client, [row(i, i % 5 != 0) for i in range(50)] + [row(50, None)])
    result = get(client, "overview")
    assert set(result) == {"domain_id", "overall_accuracy", "total_verified", "total_labels", "categories",
                           "inversion", "compounding_curve", "generated_at"}
    assert (result["total_labels"], result["total_verified"], result["overall_accuracy"]) == (51, 50, .8)
    assert [p["verified_count"] for p in result["compounding_curve"]] == [10, 20, 30, 40, 50]
    assert datetime.fromisoformat(result["generated_at"]).tzinfo is not None


def test_overview_empty_domain(client):
    seed(client, [])
    result = get(client, "overview")
    assert result["total_labels"] == result["total_verified"] == 0
    assert result["overall_accuracy"] is None and result["inversion"] is None
    assert result["compounding_curve"] == []
    assert [c["tier"] for c in result["categories"]] == ["red", "red"]
    for view in ("overview", "corrections", "annotators", "factors", "compounding"):
        assert client.get(f"/v1/dashboard/missing/{view}").status_code == 404
    assert get(client, "corrections")["correction_rate"] is None
    assert get(client, "compounding")["current_accuracy"] is None


def test_overview_with_inversion(client):
    seed(client, [row(i, i % 2 == 0, signal=.9 if i % 2 == 0 else .1) for i in range(50)], train_project=True)
    inversion = get(client, "overview")["inversion"]
    assert inversion["trusted_factor"] == "stable"
    assert inversion["actual_signal_factor"] == "signal"
    assert inversion["interpretation"]
    assert get(client, "factors")["inversion"] == inversion


def test_corrections_basic(client):
    seed(client, [row(i, True, actual="reject" if i < 5 else "approve") for i in range(20)] + [row(20, None)])
    result = get(client, "corrections")
    assert result["total_corrections"] == 5 and result["correction_rate"] == .25
    assert result["patterns"][0]["percentage_of_category"] == 100


def test_corrections_none(client):
    seed(client, [row(0, False)])
    result = get(client, "corrections")
    assert result["total_corrections"] == result["correction_rate"] == 0
    assert result["patterns"] == [] and result["top_pattern"] is None


def test_corrections_top_pattern(client):
    seed(client, [row(i, actual="reject") for i in range(3)] +
         [row(3, original="reject"), row(4, category="intent", actual="reject")])
    result = get(client, "corrections")
    assert result["top_pattern"] == {"category": "NER", "recommended_action": "approve",
                                     "actual_action": "reject", "count": 3}
    assert [p["percentage_of_category"] for p in result["patterns"]] == [75, 25, 100]


def test_annotators_basic(client):
    seed(client, [row(i, who="Ada") for i in range(3)] +
         [row(3, False, who="Ben"), row(4, True, category="intent", who="Ben"), row(5, None, who="Cy")])
    profiles = get(client, "annotators")["annotators"]
    assert [p["annotator_id"] for p in profiles] == ["Ada", "Ben", "Cy"]
    assert profiles[0]["weakest_category"] == profiles[0]["strongest_category"] == "NER"
    assert (profiles[1]["strongest_category"], profiles[1]["weakest_category"]) == ("intent", "NER")
    assert datetime.fromisoformat(profiles[1]["last_active"]) == START + timedelta(minutes=4, seconds=1)
    assert profiles[2]["accuracy"] is profiles[2]["weakest_category"] is profiles[2]["strongest_category"] is None
    assert get(client, "annotators?limit=2")["annotators"] == profiles[:2]
    assert client.get(f"{BASE}/annotators?limit=101").status_code == 422


def test_annotators_accuracy(client):
    seed(client, [row(i, i < 8, who="A") for i in range(10)] +
         [row(10+i, i < 3, who="B") for i in range(10)] + [row(20, None, who="A")])
    a, b = get(client, "annotators")["annotators"]
    assert (a["total_labels"], a["verified_count"], a["accuracy"]) == (11, 10, .8)
    assert (b["total_labels"], b["verified_count"], b["accuracy"]) == (10, 10, .3)


def test_annotators_no_annotator_id(client):
    seed(client, [row(0)])
    assert get(client, "annotators")["annotators"] == []


def test_factors_basic(client):
    seed(client, [row(0, signal=.2), row(1, None, signal=1)])
    result = get(client, "factors")
    assert result["factor_names"] == ["stable", "signal"] and result["inversion"] is None
    assert result["factor_stats"] == [
        {"factor": name, "mean_correct": mean, "mean_incorrect": None, "predictive_gap": None}
        for name, mean in [("stable", .5), ("signal", .2)]
    ]


def test_factors_gap_ordering(client):
    seed(client, [row(0, signal=.8), row(1, signal=1), row(2, False, signal=.1)])
    signal, stable = get(client, "factors")["factor_stats"]
    assert signal["factor"] == "signal"
    assert signal["mean_correct"] == pytest.approx(.9) and signal["mean_incorrect"] == .1
    assert signal["predictive_gap"] == pytest.approx(.8) and stable["predictive_gap"] == 0


def test_compounding_basic(client):
    seed(client, [row(i, i % 2 == 0) for i in reversed(range(100))])
    points = get(client, "compounding")["points"]
    assert [p["index"] for p in points] == list(range(10))
    assert [p["verified_count"] for p in points] == list(range(10, 101, 10))
    assert all(p["running_accuracy"] == .5 for p in points)
    assert datetime.fromisoformat(points[0]["timestamp"]) == START + timedelta(minutes=9, seconds=1)
    assert client.get(f"{BASE}/compounding?window=0").status_code == 422


def test_compounding_category_filter(client):
    seed(client, [row(i, False) for i in range(12)] + [row(12, True, category="intent")])
    result = get(client, "compounding?category=intent")
    assert result["category"] == "intent" and result["current_accuracy"] == 1
    assert result["points"][0]["verified_count"] == 1 and len(result["points"]) == 1
    assert result["baseline_accuracy"] is result["improvement"] is None


def test_compounding_improvement(client):
    seed(client, [row(i, i >= 5) for i in range(12)])
    result = get(client, "compounding?window=5")
    assert [p["verified_count"] for p in result["points"]] == [5, 10, 12]
    assert result["baseline_accuracy"] == 0 and result["current_accuracy"] == pytest.approx(7/12)
    assert result["improvement"] == pytest.approx(100 * 7/12)


def test_dashboard_after_full_loop(client):
    response = client.post("/v1/labels/ingest/batch",
                           json={"domain_id": "demo", "items": [item(label_id=str(i)) for i in range(50)]})
    assert response.status_code == 200, response.text
    for i, decision in enumerate(response.json()["results"][:30]):
        action = decision["recommended_action"]
        if i < 5:
            action = "reject" if action == "approve" else "approve"
        assert verify(client, label_id=str(i), outcome=i >= 5, action=action).status_code == 200
    result = get(client, "overview")
    assert (result["total_labels"], result["total_verified"]) == (50, 30)
    assert [p["accuracy"] for p in result["compounding_curve"]] == pytest.approx([.5, .75, 25/30])
    assert get(client, "corrections")["total_corrections"] == 5


def test_dashboard_matches_autonomy(client):
    assert ingest(client, category="NER").status_code == 200
    assert verify(client).status_code == 200
    assert ingest(client, label_id="L2", category="intent", annotator_id="Ada").status_code == 200
    response = client.get("/v1/domains/demo/autonomy")
    assert response.status_code == 200, response.text
    assert get(client, "overview")["categories"] == response.json()["categories"]
