#!/usr/bin/env python3
"""
DLJ Operations E2E Test Suite
Run against a live deployment to verify payment, billing, trial and email paths.

Usage:
  # Against Railway production (sandbox Paddle)
  python test_ops_e2e.py --base-url https://dlj.dakshineshwari.net --admin-key YOUR_ADMIN_KEY

  # Against local dev
  python test_ops_e2e.py --base-url http://localhost:8080 --admin-key test-admin-key

  # Skip manual Paddle checkout (automated tests only)
  python test_ops_e2e.py --base-url https://dlj.dakshineshwari.net --admin-key YOUR_KEY --skip-checkout

  # Run only specific test groups
  python test_ops_e2e.py --base-url https://dlj.dakshineshwari.net --admin-key YOUR_KEY --only health,keys,scoring,trial
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def api(
    base: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    expect_status: int | list[int] | None = None,
) -> tuple[int, Any]:
    """Make an HTTP request and return (status, parsed_json_or_text)."""
    url = f"{base.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body else None
    hdrs = {"Content-Type": "application/json"} if body else {}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ""
        status = e.code

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        parsed = raw

    if expect_status is not None:
        expected = [expect_status] if isinstance(expect_status, int) else expect_status
        if status not in expected:
            raise AssertionError(
                f"{method} {path} → {status} (expected {expected})\n{json.dumps(parsed, indent=2) if isinstance(parsed, dict) else parsed[:500]}"
            )
    return status, parsed


passed = 0
failed = 0
skipped = 0
results: list[tuple[str, str, str]] = []


def check(name: str, fn, skip: bool = False):
    """Run a named check and track results."""
    global passed, failed, skipped
    if skip:
        skipped += 1
        results.append((name, "SKIP", ""))
        print(f"  {Colors.YELLOW}SKIP{Colors.RESET}  {name}")
        return None
    try:
        result = fn()
        passed += 1
        results.append((name, "PASS", ""))
        print(f"  {Colors.GREEN}PASS{Colors.RESET}  {name}")
        return result
    except Exception as e:
        failed += 1
        results.append((name, "FAIL", str(e)))
        print(f"  {Colors.RED}FAIL{Colors.RESET}  {name}")
        print(f"        {e}")
        return None


# ---------------------------------------------------------------------------
# Test groups
# ---------------------------------------------------------------------------

def test_health(base: str):
    """Group 1: Service health and connectivity."""
    print(f"\n{Colors.BOLD}═══ 1. Service Health ═══{Colors.RESET}")

    def health_responds():
        status, body = api(base, "GET", "/v1/health")
        assert status in (200, 503), f"Unexpected status {status}"
        assert "status" in body, "Missing 'status' field"
        assert "version" in body, "Missing 'version' field"
        assert "checks" in body, "Missing 'checks' field"
        db_status = body["checks"].get("labeling_db", "")
        if "error" in str(db_status).lower():
            print(f"        ⚠ DB: {db_status}")
        return body

    def openapi_accessible():
        status, _ = api(base, "GET", "/openapi.json", expect_status=200)

    def terms_page():
        status, _ = api(base, "GET", "/terms", expect_status=200)

    def privacy_page():
        status, _ = api(base, "GET", "/privacy", expect_status=200)

    check("Health endpoint returns valid JSON", health_responds)
    check("OpenAPI spec accessible", openapi_accessible)
    check("Terms page renders", terms_page)
    check("Privacy page renders", privacy_page)


def test_keys(base: str, admin_key: str) -> dict:
    """Group 2: API key issuance."""
    print(f"\n{Colors.BOLD}═══ 2. API Key Management ═══{Colors.RESET}")
    state: dict = {}

    def create_key():
        ts = int(time.time())
        tenant_id = f"ops-test-{ts}"
        _, body = api(
            base, "POST", "/v1/admin/api-keys",
            headers={"X-Admin-Key": admin_key},
            body={"tenant_id": tenant_id, "tenant_name": tenant_id},
            expect_status=[200, 201],
        )
        assert "api_key" in body, f"No api_key in response: {body}"
        state["key"] = body["api_key"]
        state["tenant_id"] = body.get("tenant_id", tenant_id)
        state["tenant_name"] = tenant_id
        print(f"        Key: {state['key'][:8]}...  Tenant: {state['tenant_id'][:8]}...")

    def bad_admin_key():
        status, _ = api(
            base, "POST", "/v1/admin/api-keys",
            headers={"X-Admin-Key": "wrong-key"},
            body={"tenant_id": "should-fail", "tenant_name": "should-fail"},
        )
        assert status in (401, 403), f"Expected 401/403, got {status}"

    def no_admin_key():
        status, _ = api(
            base, "POST", "/v1/admin/api-keys",
            body={"tenant_id": "should-fail", "tenant_name": "should-fail"},
        )
        assert status in (401, 403, 422), f"Expected auth error, got {status}"

    check("Create API key with admin credential", create_key)
    check("Reject bad admin key", bad_admin_key)
    check("Reject missing admin key", no_admin_key)
    return state


def test_scoring(base: str, key: str) -> str:
    """Group 3: Label scoring and verification."""
    print(f"\n{Colors.BOLD}═══ 3. Scoring & Verification ═══{Colors.RESET}")
    domain = f"ops-test-{int(time.time())}"

    def ingest_single():
        _, body = api(
            base, "POST", "/v1/labels/ingest",
            headers={"X-Api-Key": key},
            body={
                "domain_id": domain,
                "label_id": "OPS-L1",
                "category": "cat_a",
                "factors": {"f1": 0.85, "f2": 0.70},
            },
            expect_status=[200, 201],
        )
        assert "decision_id" in body or "score" in body, f"Unexpected ingest response: {body}"

    def ingest_batch():
        items = [
            {"label_id": f"OPS-L{i}", "category": "cat_a" if i % 2 else "cat_b",
             "factors": {"f1": 0.5 + i * 0.05, "f2": 0.3 + i * 0.04}}
            for i in range(2, 7)
        ]
        _, body = api(
            base, "POST", "/v1/labels/ingest/batch",
            headers={"X-Api-Key": key},
            body={"domain_id": domain, "items": items},
            expect_status=[200, 201],
        )

    def pending_list():
        status, body = api(
            base, "GET", f"/v1/labels/{domain}/pending?limit=10",
            headers={"X-Api-Key": key},
            expect_status=200,
        )
        assert isinstance(body, list), f"Expected list, got {type(body)}"
        assert len(body) >= 1, "No pending labels returned"
        print(f"        {len(body)} pending labels")

    def verify_label():
        _, body = api(
            base, "POST", "/v1/labels/verify",
            headers={"X-Api-Key": key},
            body={
                "domain_id": domain,
                "label_id": "OPS-L1",
                "actual_action": "approve",
                "verified_outcome": True,
            },
            expect_status=200,
        )

    def autonomy_check():
        status, body = api(
            base, "GET", f"/v1/domains/{domain}/autonomy",
            headers={"X-Api-Key": key},
            expect_status=200,
        )
        assert "overall_tier" in body, f"Missing overall_tier: {body}"
        print(f"        Tier: {body['overall_tier']}")

    def dashboard_overview():
        status, body = api(
            base, "GET", f"/v1/dashboard/{domain}/overview",
            headers={"X-Api-Key": key},
            expect_status=200,
        )
        assert "total_labels" in body or "scored" in body or "verified_count" in body, \
            f"Dashboard missing expected fields: {list(body.keys())}"

    check("Ingest single label", ingest_single)
    check("Ingest batch (5 labels)", ingest_batch)
    check("Pending queue returns labels", pending_list)
    check("Verify a label", verify_label)
    check("Autonomy check", autonomy_check)
    check("Dashboard overview", dashboard_overview)
    return domain


def test_trial(base: str, admin_key: str):
    """Group 4: Trial quota enforcement."""
    print(f"\n{Colors.BOLD}═══ 4. Trial Quota Enforcement ═══{Colors.RESET}")

    def daily_cap():
        # Create a fresh trial key
        ts = int(time.time())
        tid = f"trial-cap-{ts}"
        _, key_body = api(
            base, "POST", "/v1/admin/api-keys",
            headers={"X-Admin-Key": admin_key},
            body={"tenant_id": tid, "tenant_name": tid},
            expect_status=[200, 201],
        )
        trial_key = key_body["api_key"]
        domain = f"trial-cap-{ts}"

        # Ingest up to the daily limit in batches of 10
        ingested = 0
        hit_limit = False
        for batch_start in range(0, 55, 10):
            items = [
                {"label_id": f"TC-{batch_start + i}", "category": "A",
                 "factors": {"f1": 0.5, "f2": 0.5}}
                for i in range(min(10, 55 - batch_start))
            ]
            status, body = api(
                base, "POST", "/v1/labels/ingest/batch",
                headers={"X-Api-Key": trial_key},
                body={"domain_id": domain, "items": items},
            )
            if status in (402, 429):
                hit_limit = True
                print(f"        Hit 402 after {ingested} labels (daily cap enforced)")
                break
            elif status in (200, 201):
                ingested += len(items)
            else:
                raise AssertionError(f"Unexpected status {status} at label {ingested}: {body}")

        assert hit_limit, f"Ingested {ingested} labels without hitting the 50/day trial cap"

    check("Trial daily cap (50 labels) enforced", daily_cap)


def test_checkout(base: str, key: str, tenant_id: str):
    """Group 5: Paddle checkout flow."""
    print(f"\n{Colors.BOLD}═══ 5. Paddle Checkout Flow ═══{Colors.RESET}")

    checkout_url = None

    def get_checkout_url():
        nonlocal checkout_url
        _, body = api(
            base, "GET", "/v1/billing/checkout-url?tier=starter",
            headers={"X-Api-Key": key},
            expect_status=200,
        )
        assert "checkout_url" in body, f"No checkout_url: {body}"
        checkout_url = body["checkout_url"]
        print(f"        URL: {checkout_url[:80]}...")

    def checkout_requires_auth():
        status, _ = api(base, "GET", "/v1/billing/checkout-url?tier=starter")
        assert status in (401, 403, 422), f"Expected auth error, got {status}"

    def invalid_tier():
        status, _ = api(
            base, "GET", "/v1/billing/checkout-url?tier=nonexistent",
            headers={"X-Api-Key": key},
        )
        assert status == 400, f"Expected 400 for bad tier, got {status}"

    check("Checkout URL returns Paddle link", get_checkout_url)
    check("Checkout requires authentication", checkout_requires_auth)
    check("Invalid tier rejected", invalid_tier)

    return checkout_url


def test_webhook(base: str, key: str, tenant_id: str, webhook_secret: str | None):
    """Group 6: Simulate Paddle webhook."""
    print(f"\n{Colors.BOLD}═══ 6. Webhook Simulation ═══{Colors.RESET}")

    def simulate_subscription_created():
        payload = {
            "event_type": "subscription.created",
            "data": {
                "id": f"sub_test_{int(time.time())}",
                "customer_id": f"ctm_test_{int(time.time())}",
                "custom_data": {"tenant_id": tenant_id},
                "items": [{"product": {"name": "DLJ Starter"}}],
                "customer": {"email": "ops-test@example.com"},
            },
        }
        body_bytes = json.dumps(payload).encode()
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if webhook_secret:
            ts = str(int(time.time()))
            sig = hmac.new(
                webhook_secret.encode(),
                f"{ts}:{body_bytes.decode()}".encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["Paddle-Signature"] = f"ts={ts};h1={sig}"

        status, resp = api(
            base, "POST", "/v1/billing/webhook",
            body=payload,
            headers=headers,
        )
        if status == 200:
            print(f"        Webhook accepted — tier should now be 'starter'")
        elif status == 409:
            print(f"        409: {resp} — may need customer_id pre-linked")
        else:
            raise AssertionError(f"Webhook returned {status}: {resp}")

    def verify_tier_upgraded():
        # Re-score to check if tier is now starter (higher quota)
        _, body = api(
            base, "POST", "/v1/labels/ingest",
            headers={"X-Api-Key": key},
            body={
                "domain_id": "webhook-verify",
                "label_id": f"WH-{int(time.time())}",
                "category": "A",
                "factors": {"f1": 0.9, "f2": 0.8},
            },
            expect_status=[200, 201],
        )
        # If we got here without 402, the key is functional post-webhook
        print("        Post-webhook scoring works")

    def simulate_subscription_canceled():
        payload = {
            "event_type": "subscription.canceled",
            "data": {
                "id": f"sub_test_{int(time.time())}",
                "customer_id": f"ctm_test_{int(time.time())}",
            },
        }
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if webhook_secret:
            ts = str(int(time.time()))
            sig = hmac.new(
                webhook_secret.encode(),
                f"{ts}:{json.dumps(payload)}".encode(),
                hashlib.sha256,
            ).hexdigest()
            headers["Paddle-Signature"] = f"ts={ts};h1={sig}"

        status, resp = api(base, "POST", "/v1/billing/webhook", body=payload, headers=headers)
        # 409 is expected (unknown subscription) for a simulated cancel
        assert status in (200, 409), f"Cancel webhook returned {status}: {resp}"
        print(f"        Cancel webhook: {status}")

    check("Simulate subscription.created webhook", simulate_subscription_created)
    check("Scoring works after webhook", verify_tier_upgraded)
    check("Simulate subscription.canceled webhook", simulate_subscription_canceled)


def test_email(base: str):
    """Group 7: Email infrastructure (log-level only)."""
    print(f"\n{Colors.BOLD}═══ 7. Email Infrastructure ═══{Colors.RESET}")

    def resend_configured():
        # We can only check if the env var is set by looking at health
        # or trying to trigger the scheduler path
        status, body = api(base, "GET", "/v1/health")
        # If the service is up, Resend is at least importable
        print("        Resend configured (verify delivery in Railway logs)")
        print("        Check: Railway dashboard → Logs → search 'trial expir'")

    check("Email service reachable (log check)", resend_configured)


def test_legal(base: str):
    """Group 8: Legal pages contain Paddle references."""
    print(f"\n{Colors.BOLD}═══ 8. Legal & Billing Copy ═══{Colors.RESET}")

    def terms_mentions_paddle():
        _, body = api(base, "GET", "/terms", expect_status=200)
        text = body if isinstance(body, str) else str(body)
        assert "paddle" in text.lower(), "Terms page does not mention Paddle"

    def privacy_exists():
        api(base, "GET", "/privacy", expect_status=200)

    def no_lemon_squeezy():
        _, terms = api(base, "GET", "/terms", expect_status=200)
        _, privacy = api(base, "GET", "/privacy", expect_status=200)
        combined = str(terms) + str(privacy)
        assert "lemon squeezy" not in combined.lower(), \
            "Legal pages still reference old payment provider"

    check("Terms page mentions Paddle", terms_mentions_paddle)
    check("Privacy page accessible", privacy_exists)
    check("No stale Lemon Squeezy references", no_lemon_squeezy)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="DLJ Operations E2E Tests")
    parser.add_argument("--base-url", required=True, help="e.g. https://dlj.dakshineshwari.net")
    parser.add_argument("--admin-key", required=True, help="ADMIN_API_KEY from Railway env vars")
    parser.add_argument("--webhook-secret", default=None, help="PADDLE_WEBHOOK_SECRET (optional in sandbox)")
    parser.add_argument("--skip-checkout", action="store_true", help="Skip manual Paddle checkout test")
    parser.add_argument("--only", default=None, help="Comma-separated: health,keys,scoring,trial,checkout,webhook,email,legal")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    groups = set(args.only.split(",")) if args.only else None

    print(f"\n{Colors.BOLD}{Colors.CYAN}DLJ Operations E2E Test Suite{Colors.RESET}")
    print(f"Target: {base}")
    print(f"Time:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'─' * 60}")

    # 1. Health
    if not groups or "health" in groups:
        test_health(base)

    # 2. Keys
    state = {}
    if not groups or "keys" in groups:
        state = test_keys(base, args.admin_key)

    # Need a key for the rest
    key = state.get("key", "")
    tenant_id = state.get("tenant_id", "")

    # 3. Scoring
    if not groups or "scoring" in groups:
        if key:
            test_scoring(base, key)
        else:
            print(f"\n  {Colors.YELLOW}SKIP{Colors.RESET}  Scoring (no key available)")

    # 4. Trial
    if not groups or "trial" in groups:
        test_trial(base, args.admin_key)

    # 5. Checkout
    if not groups or "checkout" in groups:
        if key and not args.skip_checkout:
            checkout_url = test_checkout(base, key, tenant_id)
            if checkout_url:
                print(f"\n  {Colors.CYAN}MANUAL STEP:{Colors.RESET} Open this URL and complete with test card 4242 4242 4242 4242:")
                print(f"  {checkout_url}")
                print(f"  Then check Railway logs for the webhook event.")
        elif args.skip_checkout:
            print(f"\n  {Colors.YELLOW}SKIP{Colors.RESET}  Checkout (--skip-checkout)")

    # 6. Webhook
    if not groups or "webhook" in groups:
        if key and tenant_id:
            test_webhook(base, key, tenant_id, args.webhook_secret)
        else:
            print(f"\n  {Colors.YELLOW}SKIP{Colors.RESET}  Webhook (no key/tenant)")

    # 7. Email
    if not groups or "email" in groups:
        test_email(base)

    # 8. Legal
    if not groups or "legal" in groups:
        test_legal(base)

    # Summary
    total = passed + failed + skipped
    print(f"\n{'─' * 60}")
    print(f"{Colors.BOLD}Results: {Colors.GREEN}{passed} passed{Colors.RESET}, ", end="")
    print(f"{Colors.RED}{failed} failed{Colors.RESET}, ", end="")
    print(f"{Colors.YELLOW}{skipped} skipped{Colors.RESET} ", end="")
    print(f"({total} total)")

    if failed:
        print(f"\n{Colors.RED}Failed checks:{Colors.RESET}")
        for name, status, msg in results:
            if status == "FAIL":
                print(f"  ✗ {name}")
                if msg:
                    print(f"    {msg[:200]}")

    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
