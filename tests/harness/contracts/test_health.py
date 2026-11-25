import pytest

from ..fixtures.factory import NULL, NUMBER, OPTIONAL_NUMBER, Wire, shape

pytestmark = pytest.mark.anyio


async def test_service_health(wire: Wire):
    response = await wire.request("GET", "/v1/health")
    shape(response.json(), {"status": str, "version": str,
                            "checks": {"labeling_db": str, "legacy_db": str, "engine_hash": str}})


@pytest.mark.parametrize("path", ["/terms", "/privacy", "/attribution"])
async def test_legal_html(wire: Wire, path):
    response = await wire.request("GET", path, headers={"X-Api-Key": ""})
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1" in response.text.lower()


@pytest.mark.parametrize("route", ["analyze", "report", "report/pdf"])
async def test_anonymous_report(wire: Wire, route):
    rows = ["label_id,category,verified_outcome,factor_one,factor_two"]
    rows.extend(f"L{i},C{i%2},{int(i%3 != 0)},{(i%5)/5},{(i%7)/7}" for i in range(200))
    files = {"file": ("sample.csv", "\n".join(rows).encode(), "text/csv")}
    response = await wire.request("POST", f"/v1/label-health/{route}", headers={"X-Api-Key": ""}, files=files)
    if route == "analyze":
        shape(response.json(), {"report_version": str, "metadata": {"row_count": int, "verified_count": int,
              "category_count": int, "factor_count": int, "analysis_time_ms": NUMBER}, "overall_accuracy": OPTIONAL_NUMBER, "category_risks": list,
              "inversion": (dict, NULL), "annotator_profiles": (list, NULL), "silent_risks": list,
              "cost_projection": (dict, NULL), "factor_names": [str], "warnings": [str], "message": (str, NULL)})
    elif route == "report":
        assert response.headers["content-type"].startswith("text/html") and "<title>" in response.text
    else:
        assert response.headers["content-type"] == "application/pdf" and response.content.startswith(b"%PDF")
