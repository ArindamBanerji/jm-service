"""Public legal pages must win over the static frontend mount."""

import pytest
from fastapi.testclient import TestClient

from jm_service import app


@pytest.mark.parametrize("path,heading", [
    ("/terms", "Terms of Service"),
    ("/privacy", "Privacy Policy"),
    ("/attribution", "Open-Source Attribution"),
])
def test_legal_page(path: str, heading: str) -> None:
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert heading in response.text


def test_cors_allows_dlj_and_rejects_other_origin() -> None:
    client = TestClient(app)
    headers = {"Access-Control-Request-Method": "POST"}
    allowed = client.options("/v1/labels/ingest", headers={
        **headers, "Origin": "https://dlj.dakshineshwari.net"})
    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://dlj.dakshineshwari.net"
    denied = client.options("/v1/labels/ingest", headers={
        **headers, "Origin": "https://unrelated.example"})
    assert denied.status_code == 400
