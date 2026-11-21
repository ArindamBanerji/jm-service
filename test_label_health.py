import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd
from fastapi import FastAPI
from starlette.testclient import TestClient
from label_health.ingest import validate_csv, infer_config
from label_health.analyze import run_analysis
from label_health.render import render_html_report, render_pdf
from label_health.api import router


def sample(n=300, k=2, m=2, verified=300, annotators=False):
    rows = []
    for i in range(n):
        row: dict[str, object] = {"label_id": f"L{i}", "category": f"C{i % k}",
               "verified_outcome": (i % 5 != 0) if i < verified else None}
        for j in range(m): row[f"factor_{j}"] = (i % 10) / 10
        if annotators: row["annotator_id"] = f"A{i % 3}"
        rows.append(row)
    return pd.DataFrame(rows)


def analyzed(df=None):
    frame = sample() if df is None else df
    return run_analysis(frame, infer_config(frame))


def client():
    app = FastAPI(); app.include_router(router); return TestClient(app)


def upload(df):
    return {"file": ("labels.csv", df.to_csv(index=False).encode(), "text/csv")}


def test_validate_minimum_rows():
    result = validate_csv(sample(n=100))
    assert not result.is_valid and "200" in str(result.errors)


def test_validate_minimum_factors():
    assert not validate_csv(sample(m=1)).is_valid


def test_validate_minimum_verified():
    result = validate_csv(sample(verified=40))
    assert result.is_valid and result.warnings


def test_infer_categories():
    assert len(infer_config(sample(k=3)).categories) == 3


def test_infer_factors():
    df = sample(); df = df.rename(columns={"factor_0":"model_confidence", "factor_1":"annotator_agreement"})
    assert infer_config(df).factors == ["model_confidence", "annotator_agreement"]


def test_infer_actions_default():
    assert infer_config(sample()).actions == ["approve", "reject"]


def test_analysis_basic():
    report = analyzed()
    assert {"metadata","overall_accuracy","category_risks","inversion","annotator_profiles","silent_risks","cost_projection","factor_names"} <= report.keys()
    assert 0 <= report["overall_accuracy"] <= 1


def test_analysis_inversion_detected():
    df = sample()
    df["factor_0"] = 0.5
    df["factor_1"] = [0.9 if x else 0.1 for x in df["verified_outcome"]]
    assert analyzed(df)["inversion"] is not None


def test_analysis_no_inversion():
    df = sample()
    df["factor_0"] = [0.55 if x else 0.45 for x in df["verified_outcome"]]
    df["factor_1"] = [0.1 if (i // 5) % 2 else 0.9 for i in range(len(df))]
    assert analyzed(df)["inversion"] is None


def test_analysis_annotator_profiles():
    assert len(analyzed(sample(annotators=True))["annotator_profiles"]) == 3


def test_analysis_no_annotator():
    assert analyzed()["annotator_profiles"] is None


def test_analysis_silent_risks():
    df = sample(); df.loc[df.index >= 20, "category"] = "MAIN"; df.loc[df.index < 20, "category"] = "THIN"
    assert any(row["category"] == "THIN" for row in analyzed(df)["silent_risks"])


def test_cost_projection_non_negative():
    report = analyzed()
    assert all(value >= 0 for value in report["cost_projection"].values() if isinstance(value, (int, float)))


def test_render_html_contains_layers():
    html = render_html_report(analyzed())
    assert "Category" in html and "RGI Data Label Judgment" in html


def test_render_inversion_card():
    report = analyzed(); report["inversion"] = {"trusted_factor": "factor_0", "actual_signal_factor": "factor_1"}
    assert "factor_0" in render_html_report(report)


def test_render_pdf_bytes():
    assert render_pdf(render_html_report(analyzed())).startswith(b"%PDF")


def test_api_analyze_valid():
    frame = sample()
    frame["proposed_action"] = "approve"
    frame["actual_action"] = frame["verified_outcome"].map({True: "approve", False: "reject"})
    frame["verified"] = True
    frame = frame.drop(columns="verified_outcome")
    response = client().post("/v1/label-health/analyze", files=upload(frame))
    assert response.status_code == 200, response.text
    assert response.json()["overall_accuracy"] == 0.8
    assert response.json()["factor_names"] == ["0", "1"]


def test_api_analyze_invalid():
    assert client().post("/v1/label-health/analyze", files=upload(sample(n=50))).status_code == 422


def test_api_report_pdf():
    response = client().post("/v1/label-health/report/pdf", files=upload(sample()))
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"


def test_api_malformed_csv():
    response = client().post("/v1/label-health/analyze", files={"file": ("bad.csv", b"not,a\x00csv", "text/csv")})
    assert response.status_code == 422


def test_api_empty_upload():
    response = client().post("/v1/label-health/analyze", files={"file": ("empty.csv", b"", "text/csv")})
    assert response.status_code == 422


def test_api_single_action():
    response = client().post("/v1/label-health/analyze", files=upload(sample().assign(action="approve")))
    assert response.status_code == 200, response.text


def test_zero_verified():
    response = client().post("/v1/label-health/analyze", files=upload(sample(verified=0)))
    assert response.status_code == 200
    assert response.json()["overall_accuracy"] is None
    assert response.json()["cost_projection"] is None
    assert "No verified labels" in response.json()["message"]
    assert "Insufficient data" in render_html_report(response.json())


def test_duplicate_headers():
    raw = sample().to_csv(index=False).replace("factor_1", "factor_0", 1).encode()
    response = client().post("/v1/label-health/analyze", files={"file": ("duplicate.csv", raw, "text/csv")})
    assert response.status_code == 422


def test_analysis_exact_category_accuracy():
    frame = sample(n=200, k=2)
    frame["verified_outcome"] = None
    frame.loc[frame.index[:20], "verified_outcome"] = [True] * 8 + [False] * 2 + [True] * 3 + [False] * 7
    frame.loc[frame.index[:20], "category"] = ["A"] * 10 + ["B"] * 10
    frame.loc[frame.index[20:], "category"] = "A"
    result = analyzed(frame)
    by_category = {row["category"]: row["accuracy"] for row in result["category_risks"]}
    assert by_category == {"A": 0.8, "B": 0.3}
