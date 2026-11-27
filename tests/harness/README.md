# Prompt 00 contract harness

Use the repository root. Install the service and test requirements, install Chromium with `python -m playwright install chromium`, and build the SPA with `npm ci --prefix frontend` and `npm --prefix frontend run build`. The sample seed endpoint also reads the built demo asset.

Set `DLJ_DATABASE_URL` to an async PostgreSQL test database where the test user can create schemas. The default is `postgresql+asyncpg://postgres:postgres@localhost:5432/dlj_test`. Each database-backed test creates and drops its own randomly named schema. Browser tests use real Chromium, a fresh user and a private loopback instance of the same FastAPI app. Set `DLJ_PORT` to reserve a specific free port, as in the Node Playwright config. Without an override the harness takes an available port. The existing Node suite uses the app already running at its configured port.

```sh
python -m pytest tests/harness -q --strict-markers --timeout=30
python -m pytest tests/harness --harness-sqlite -q --strict-markers --timeout=30
python -m mypy tests/harness --config-file pyproject.toml
```

The separate SQLite CI job is advisory and uses a temporary file with foreign keys enabled. A documented future dialect difference can use `@pytest.mark.sqlite_divergence("ID and expected difference")` on its test. This becomes a strict assertion-only xfail in that lane. The current endpoint contracts have no dialect-specific waivers. PostgreSQL setup failures are test errors.

## Post-check

For the release gate, run `python -m pytest tests/ -q --timeout=120` with
`DLJ_DATABASE_URL` set to PostgreSQL. This includes S13, whose test name
mentions both dialects. The separate root regression job selects
`-m "not sqlite_only"` on PostgreSQL. Root tests whose modern-store fixtures
require SQLite run in the advisory job. To exercise the compatibility lane
locally, run `python -m pytest tests/harness/ --harness-sqlite -q`.

| Contract file | Endpoints | Writes | Audited surface |
|---|---:|---:|---|
| test_auth.py | 5 | 3 | Public signup, admin key, current account, domain list and resolution. The current account is the session contract. |
| test_labels.py | 10 | 7 | Ingest, batch, verify, bulk, seed, task, pending, both guidelines methods and autonomy. |
| test_revisions.py | 4 | 2 | Both detail paths, relabel and structured content. Connector correction is exercised by the connector webhook contract. |
| test_dashboard.py | 6 | 0 | Overview including categories, corrections, annotators, factors, compounding and IAA. |
| test_billing.py | 2 | 2 | External checkout with fake provider ledger, webhook entitlement with a fresh DB read. |
| test_connector.py | 5 | 4 | Configure, setup, predict, webhook and health. Configure observes the on-disk JSON. |
| test_health.py | 7 | 0 | Service health, three anonymous report formats, three public HTML legal routes. |
| test_legacy.py | 7 | 4 | Registration, create/list domains, score, learn, diagnostics and state. Observers reopen the separate legacy SQLite file. |
| test_export.py, test_predictions.py, test_webhooks.py | 0 | 0 | Reserved for D, D and E respectively. Each currently registered operation is in one of the other modules. |
| **Total** | **46** | **22** | Verified against sweep 7 §7, including the detail alias and three legal routes excluded from OpenAPI. |

- **Fixtures.** pg_schema.py sets and checks search_path before table creation. It releases scoped connections, drops only the generated schema and disposes the admin engine in finally blocks. conftest.py runs the real app lifespan, points auth/request, billing, scheduler and health at the isolated store and redirects legacy SQLite and connector files into the test directory. Email and Paddle transport use local stand-ins. No client can charge a real customer through these tests.
- **Factories.** factory.py creates a tenant key, scoped domain, versioned engine and scored source label through service persistence helpers. The write observer runs on the ASGI response-start path before forwarding success. A separate session, file reader or external-provider test ledger must already see the write. A missing observer invocation fails the test. The contracts check required field names, wire types, format-specific bodies and headers.
- **Scenarios.** S1–14 cover identity, access and billing. S20–27 exercise shared writes, and S28–32 exercise the browser against the mounted service. All 27 are active on PostgreSQL. S15–19 are reserved for deferred legacy work.
- **Regression tests.** Connector ordering and immutable source binding, review draft protection and private history now run as ordinary assertions, alongside the diagnostic and concurrent intake checks. The joint S27 browser tests verify bulk review through both domain and project routes.
- **Browser.** Eight actual screen routes and a review-components contract exercise the built SPA. Each checks browser errors. The draft-conflict test admits the specific expected HTTP 409 console entry during its intentional conflict. Its ordinary screen contract still requires a clean console.

The R1 reviewer can use this checklist with the merged plan §2.1. Future product scenarios, an independent Astra review and live provider smoke tests have their own release gates.
