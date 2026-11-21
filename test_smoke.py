#!/usr/bin/env python3
"""HTTP smoke test for the deployed RGI Data Label Judgment service.

From the parent claude_projects directory:
    docker compose -f jm-service/docker-compose.yml --project-directory jm-service up -d --build
    python jm-service/test_smoke.py
    docker compose -f jm-service/docker-compose.yml --project-directory jm-service down

SMOKE_BASE_URL defaults to http://localhost:8000. ADMIN_API_KEY defaults to the
development-only value in docker-compose.yml. The script never prints a key.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

BASE = os.getenv("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_KEY = os.getenv("ADMIN_API_KEY", "test-admin-key-for-smoke")
HEALTH_TIMEOUT = 60


def wait_for_health() -> bool:
    """Wait for the container, migration, and both health checks to finish."""
    deadline = time.monotonic() + HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{BASE}/v1/health", timeout=5)
            if response.status_code == 200 and response.json().get("status") in {"healthy", "degraded"}:
                print(f"Health ready: {response.json()['status']} - {response.json().get('checks')}")
                return True
        except (httpx.RequestError, ValueError):
            pass
        time.sleep(2)
    return False


def make_csv(rows: int = 300, categories: int = 3, factors: int = 2) -> bytes:
    """Return a valid, fully local CSV for all three anonymous report routes."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["label_id", "category", "verified_outcome"] +
                    [f"factor_{index}" for index in range(factors)])
    for index in range(rows):
        writer.writerow([f"SMOKE_CSV_{index}", f"CAT_{index % categories}",
                         0 if index % 5 == 0 else 1] +
                        [round((index + offset) % 10 / 10, 1) for offset in range(factors)])
    return buffer.getvalue().encode("utf-8")


def _json(response: httpx.Response | None) -> dict[str, Any]:
    if response is None:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def run_smoke() -> bool:
    """Exercise the deployed HTTP boundary and print one result per check."""
    results: list[tuple[str, bool]] = []
    csv_data = make_csv()
    upload = {"file": ("smoke.csv", csv_data, "text/csv")}

    def request(method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        try:
            return httpx.request(method, f"{BASE}{path}", **kwargs)
        except httpx.RequestError as exc:
            print(f"  {method} {path}: {type(exc).__name__}: {exc}")
            return None

    def check(name: str, response: httpx.Response | None,
              valid: Callable[[httpx.Response], bool]) -> bool:
        try:
            passed = response is not None and valid(response)
        except (ValueError, TypeError, KeyError):
            passed = False
        results.append((name, passed))
        status = response.status_code if response is not None else "no response"
        detail = _json(response).get("detail") if not passed else None
        print(f"  {'PASS' if passed else 'FAIL'} {name}: {status}" +
              (f" - {detail}" if detail is not None else ""))
        return passed

    print("1. Health")
    check("Health", request("GET", "/v1/health", timeout=10),
          lambda r: r.status_code == 200 and _json(r).get("status") in {"healthy", "degraded"})

    print("2. Anonymous Label Health JSON")
    check("Label Health JSON", request("POST", "/v1/label-health/analyze", files=upload, timeout=60),
          lambda r: r.status_code == 200 and "overall_accuracy" in _json(r))

    print("3. Anonymous Label Health HTML")
    check("Label Health HTML", request("POST", "/v1/label-health/report", files=upload, timeout=60),
          lambda r: r.status_code == 200 and "RGI Data Label Judgment" in r.text)

    print("4. Anonymous Label Health PDF")
    check("Label Health PDF", request("POST", "/v1/label-health/report/pdf", files=upload, timeout=60),
          lambda r: r.status_code == 200 and
          r.headers.get("content-type", "").startswith("application/pdf") and r.content.startswith(b"%PDF"))

    print("5. Admin API key")
    issued = request("POST", "/v1/admin/api-keys",
                     json={"tenant_id": "smoke_test", "tenant_name": "Smoke Test"},
                     headers={"X-Admin-Key": ADMIN_KEY}, timeout=10)
    key_ok = check("Create API Key", issued,
                   lambda r: r.status_code == 200 and bool(_json(r).get("api_key")))
    api_key = str(_json(issued).get("api_key", "")) if key_ok else ""

    if api_key:
        headers = {"X-Api-Key": api_key}
        domain_id = f"smoke_{uuid.uuid4().hex[:12]}"
        label_id = "SMOKE_1"
        print("6. Authenticated ingest")
        check("Ingest", request("POST", "/v1/labels/ingest",
                                json={"domain_id": domain_id, "label_id": label_id,
                                      "category": "NER", "factors": {"factor_0": 0.8, "factor_1": 0.6}},
                                headers=headers, timeout=10),
              lambda r: r.status_code == 200 and bool(_json(r).get("recommended_action")))

        print("7. Authenticated verify")
        check("Verify", request("POST", "/v1/labels/verify",
                                json={"domain_id": domain_id, "label_id": label_id,
                                      "actual_action": "approve", "verified_outcome": True},
                                headers=headers, timeout=10),
              lambda r: r.status_code == 200 and _json(r).get("engine_updated") is True)

        print("8. Dashboard overview")
        check("Dashboard", request("GET", f"/v1/dashboard/{domain_id}/overview",
                                   headers=headers, timeout=10),
              lambda r: r.status_code == 200 and "overall_accuracy" in _json(r))

        print("9. Autonomy status")
        check("Autonomy", request("GET", f"/v1/domains/{domain_id}/autonomy",
                                  headers=headers, timeout=10),
              lambda r: r.status_code == 200 and isinstance(_json(r).get("categories"), list))
    else:
        print("  API key unavailable; authenticated checks cannot run")
        results.extend((name, False) for name in ("Ingest", "Verify", "Dashboard", "Autonomy"))
        for name in ("Ingest", "Verify", "Dashboard", "Autonomy"):
            print(f"  FAIL {name}: no API key")

    passed = sum(ok for _, ok in results)
    print(f"\nSMOKE TEST: {passed}/{len(results)} passed")
    return passed == len(results)


if __name__ == "__main__":
    print("RGI Data Label Judgment - deployed HTTP smoke test")
    if not wait_for_health():
        print(f"FAIL: service at {BASE} did not become healthy within {HEALTH_TIMEOUT}s")
        sys.exit(1)
    sys.exit(0 if run_smoke() else 1)
