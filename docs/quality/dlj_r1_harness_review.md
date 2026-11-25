# DLJ R1 — Prompt 00 harness review

25 November 2026 · **Prompt A NOT READY**

| Measure | Verified result |
|---|---|
| Contract coverage | **46/46 endpoints** called successfully |
| Write durability | **22/22 serial write contracts** observed a durable effect by HTTP response start. Concurrent requests can silently suppress the observation. |
| Scenario shells | **27/27** have the correct owner, marker and §5 TODO |
| Known failures | **6/6** reproduce an instance of the named defect and reach their strict expected failure. Coverage of the full closure conditions varies. |
| Existing regressions | **443 pytest passed, one skipped. Playwright 124/124 with two workers.** The requested default eight-worker runs passed 100/124 and 105/124. |
| Decision | **NOT READY**. Combined pytest discovery fails, the durability observer loses requests under overlap, and the current freeze misses identity, billing and response contracts. |

## 1. Contract completeness

I matched the mounted FastAPI application against sweep 7 §7 and the harness calls. All 46 method/path registrations matched, including the detail alias and three legal pages omitted from OpenAPI. Dashboard, detail, report and legal paths use parameterized tests. The export, predictions and project-webhook placeholders add no routes to the count.

Each write row below includes the actual success status, authentication context and independent read at response start. Paths point to functions in `tests/harness/contracts/`. The shared assertion checks the exact status at `fixtures/factory.py:62`. The callback runs before the outer ASGI send at `conftest.py:74–80`. Modern DB observers use a fresh session and connection, legacy DB observers reopen SQLite, and the config and mock-provider observers independently reopen their files.

| Endpoint | Method | Contract file:line | Present? | Write auth, status | Effect visible before success |
|---|---|---|---|---|---|
| `/v1/account` | GET | `test_auth.py:21` | Yes | — | — |
| `/v1/account/domains` | GET | `test_auth.py:29` | Yes | — | — |
| `/v1/account/domains/resolve` | POST | `test_auth.py:36` | Yes | key, 200 | Previously unnamed domain has the submitted public name |
| `/v1/auth/register` | POST | `test_auth.py:8` | Yes | public*, 201 | New email row exists |
| `/v1/admin/api-keys` | POST | `test_auth.py:14` | Yes | admin*, 200 | New tenant key row exists |
| `/v1/billing/checkout-url` | GET | `test_billing.py:13` | Yes | key, 200 | Reopened mock provider ledger contains the purchase tenant |
| `/v1/billing/webhook` | POST | `test_billing.py:34` | Yes | sandbox*, 200 | Event-marked key has professional tier |
| `/v1/dashboard/{domain_id}/iaa` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/dashboard/{domain_id}/overview` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/dashboard/{domain_id}/corrections` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/dashboard/{domain_id}/annotators` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/dashboard/{domain_id}/factors` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/dashboard/{domain_id}/compounding` | GET | `test_dashboard.py:28` | Yes | — | — |
| `/v1/health` | GET | `test_health.py:8` | Yes | — | — |
| `/v1/register` | POST | `test_legacy.py:32` | Yes | public*, 200 | New tenant named Owner |
| `/v1/domains` | POST | `test_legacy.py:38` | Yes | legacy, 201 | One new domain |
| `/v1/domains` | GET | `test_legacy.py:45` | Yes | — | — |
| `/v1/domains/{domain_id}/score` | POST | `test_legacy.py:52` | Yes | legacy, 200 | One new decision |
| `/v1/domains/{domain_id}/learn` | POST | `test_legacy.py:60` | Yes | legacy, 200 | Decision acquired learned_at |
| `/v1/domains/{domain_id}/diagnostics` | GET | `test_legacy.py:70` | Yes | — | — |
| `/v1/domains/{domain_id}/state` | GET | `test_legacy.py:78` | Yes | — | — |
| `/v1/label-health/analyze` | POST | `test_health.py:22` | Yes | — | — |
| `/v1/label-health/report` | POST | `test_health.py:22` | Yes | — | — |
| `/v1/label-health/report/pdf` | POST | `test_health.py:22` | Yes | — | — |
| `/v1/label-studio/configure` | POST | `test_connector.py:20` | Yes | key + LS, 200 | Reopened JSON file contains tenant/project/domain binding |
| `/v1/label-studio/setup` | POST | `test_connector.py:33` | Yes | LS*, 200 | Public domain studio exists |
| `/v1/label-studio/predict` | POST | `test_connector.py:39` | Yes | key + LS, 200 | Scored label exists for task 1 |
| `/v1/label-studio/webhook` | POST | `test_connector.py:48` | Yes | key + LS, 200 | Forward correction created a linked revision |
| `/v1/label-studio/health` | GET | `test_connector.py:57` | Yes | — | — |
| `/v1/domains/{domain_id}/guidelines` | GET | `test_labels.py:67` | Yes | — | — |
| `/v1/domains/{domain_id}/guidelines` | PUT | `test_labels.py:72` | Yes | key, 200 | Domain guidelines changed to Sample |
| `/v1/labels/ingest` | POST | `test_labels.py:13` | Yes | key, 200 | New label exists |
| `/v1/labels/verify` | POST | `test_labels.py:26` | Yes | key, 200 | Previously pending label has true outcome |
| `/v1/labels/{domain_id}/bulk-verify` | POST | `test_labels.py:36` | Yes | key, 200 | Previously pending label has false outcome |
| `/v1/labels/ingest/batch` | POST | `test_labels.py:19` | Yes | key, 200 | New batch label exists |
| `/v1/labels/{domain_id}/sample` | POST | `test_labels.py:45` | Yes | key, 200 | Previously empty label table contains 12 rows |
| `/v1/labels/{domain_id}/tasks` | POST | `test_labels.py:51` | Yes | key, 201 | New task contains submitted text |
| `/v1/labels/{domain_id}/items/{label_id}/relabel` | POST | `test_revisions.py:21` | Yes | key, 200 | Successor has a predecessor reference |
| `/v1/labels/{domain_id}/pending` | GET | `test_labels.py:58` | Yes | — | — |
| `/v1/labels/{domain_id}/items/{label_id}/content` | POST | `test_revisions.py:31` | Yes | key, 201 | Multilabel content row exists |
| `/v1/labels/{domain_id}/items/{label_id}` | GET | `test_revisions.py:15` | Yes | — | — |
| `/v1/labels/{domain_id}/{label_id}` | GET | `test_revisions.py:15` | Yes | — | — |
| `/v1/domains/{domain_id}/autonomy` | GET | `test_labels.py:79` | Yes | — | — |
| `/terms` | GET | `test_health.py:15` | Yes | — | — |
| `/privacy` | GET | `test_health.py:15` | Yes | — | — |
| `/attribution` | GET | `test_health.py:15` | Yes | — | — |

Key means the seeded tenant key, legacy means the bearer value issued by the separate legacy register route and LS means the connector token. An asterisk marks calls that also carry the default valid tenant key although that credential is unnecessary. The billing notification exercises unsigned sandbox mode. Checkout's durable boundary is a local stand-in for the provider transaction. Legacy score and learn prove the decision-log effect; their separate engine snapshot commits are outside those assertions. The ledger credits the exercised successful write path, not atomicity across every effect or branch.

### Where a broken endpoint can pass

1. **Concurrent durability is a false green.** `fixtures/factory.py:55–66` stores a single mutable observer on Wire. A second request overwrites it, and the first treats None as evidence its observer ran. I paused one observed POST in a controlled local ASGI transport, completed an unobserved GET on the same real Wire and resumed the POST. Both calls passed and the POST observer ran **zero** times. This matters for S2 and the overlapping billing and retention scenarios.
2. **Auth and payer binding.** The client at `conftest.py:84–85` supplies an active key to registration, admin issuance and the billing webhook. Signup could acquire a tenant-auth dependency and its contract would still pass. Its test checks the returned key's type without authenticating it. The checkout observer at `contracts/test_billing.py:27–31` checks only the tenant even though `billing.py:89–93` sends the purchasing key ID too. The webhook contract would miss a broken signed live entry path. Existing focused signup and billing tests provide complementary coverage.
3. **DTO completeness.** `contracts/test_labels.py:58–65` omits the pending row's factors map, returned by `labeling_router.py:744–747` and required by the frontend. Both detail contracts at `contracts/test_revisions.py:7–18` see null content, so dropping all structured child fields passes. `contracts/test_dashboard.py:28–31` seeds no verified labels or annotators. Empty arrays bypass the element assertions for profiles, corrections, curves and IAA pairs.
4. **Loose success assertions.** No JSON test relies solely on status. However, the three legal pages each need only HTML and an h1, so returning the terms document for privacy would pass. The report PDF check verifies the media type and signature only. The generic shape helper permits additive fields, including a sensitive extra field on an account response. Use explicit exclusions for private fields and route-specific identities for documents.

## 2. Scenario shell quality

I compared the shell source and its collection result to §5. For each numbered function I checked the owning decorator, strict xfail reason, explicit skip message and exact TODO text. The docstring identifies the boundary in the table. S15–19 are reserved for deferred legacy work. File paths below are relative to `tests/harness/scenarios/`.

| Scenario and boundary | Owner prompt | Shell file:line | Marker and xfail owner correct? | TODO matches §5? |
|---|---|---|---|---|
| S1 · New signup and mismatched mailbox | A | `test_s01_s06.py:6` | Yes | Yes |
| S2 · Concurrent proof consumption and mail failure | A | `test_s01_s06.py:14` | Yes | Yes |
| S3 · Concurrent anonymous uploads at admission limit | A | `test_s01_s06.py:22` | Yes | Yes |
| S4 · Forced unhandled database failure through ASGI and scheduler | A | `test_s01_s06.py:30` | Yes | Yes |
| S5 · Malformed connector dispatch/results | A | `test_s01_s06.py:38` | Yes | Yes |
| S6 · Identifier limits through all create/reuse paths | A | `test_s01_s06.py:46` | Yes | Yes |
| S7 · Checkout with two keys and existing customer | A | `test_s07_s14.py:6` | Yes | Yes |
| S8 · Status sequence including past due, pause, resume and replaced subscription | A | `test_s07_s14.py:14` | Yes | Yes |
| S9 · Unknown, duplicate and delayed events amid cancellation | A | `test_s07_s14.py:22` | Yes | Yes |
| S10 · Cleanup versus reactivation on separate connections | A | `test_s07_s14.py:30` | Yes | Yes |
| S11 · Key creation and rotation during cleanup | A | `test_s07_s14.py:38` | Yes | Yes |
| S12 · Two old cancelled siblings versus one entitled sibling | A | `test_s07_s14.py:46` | Yes | Yes |
| S13 · Historical PostgreSQL provider upgrade twice (SQLite advisory) | A | `test_s07_s14.py:54` | Yes | Yes |
| S14 · Cancelled/paid UTC day and month boundaries | A | `test_s07_s14.py:62` | Yes | Yes |
| S20 · HTTP and connector verification on an older reviewer engine | C | `test_s20_s27.py:6` | Yes | Yes |
| S21 · Connector and HTTP revision of structured data | C | `test_s20_s27.py:14` | Yes | Yes |
| S22 · Two first-domain/engine writes | C | `test_s20_s27.py:22` | Yes | Yes |
| S23 · Concurrent reservations at 49 plus two requests | C | `test_s20_s27.py:30` | Yes | Yes |
| S24 · Two relabels plus verify on one predecessor | C | `test_s20_s27.py:38` | Yes | Yes |
| S25 · Independent connector processes configure distinct projects | C | `test_s20_s27.py:46` | Yes | Yes |
| S26 · Incorrect label corrected twice, including category reversion | C | `test_s20_s27.py:54` | Yes | Yes |
| S27 · Bulk approval, independent outcomes and a skipped item | C | `test_s20_s27.py:62` | Yes | Yes |
| S28 · Late signup after same-tab or cross-tab rotation | B | `test_s28_s32.py:6` | Yes | Yes |
| S29 · Rotation between real import chunks then restart | B | `test_s28_s32.py:14` | Yes | Yes |
| S30 · Domain switch with detail/search/bulk in flight, duplicated public IDs | B | `test_s28_s32.py:22` | Yes | Yes |
| S31 · Tag draft during category save/verify and navigation | B | `test_s28_s32.py:30` | Yes | Yes |
| S32 · Incompatible JSON and failed lazy chunk | B | `test_s28_s32.py:38` | Yes | Yes |

**When A ships**, activate S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12, S13 and S14. All 14 carry `prompt_a`. Remove each skip and xfail when implementing it and require 14 actual passes. B owns five shells and C eight.

**Are the TODOs enough on their own?** Each gives the intended observable outcome. Several are too terse to serve as stand-alone test recipes. S3 needs a reader budget, clock and permit-release observation. S4 needs an allowlist and both diagnostic sinks. S5–6 need endpoint/field matrices. S8–9 need ordered events and a stated expected entitlement at each step. S10–11 need named transaction barriers and independent sessions. S13 needs a historical schema and migration engine. The other scenarios also inherit §5's instructions for real authentication, fresh readback and concurrent/browser setup. This is adequate ownership scaffolding. A green collection proves nothing about future product behavior.

## 3. Known-failure reproduction

All six selected tests reached their dedicated KnownGap assertion. Their markers specify strict=True and raises=KnownGap, so an ordinary failed assertion or infrastructure exception cannot satisfy the expected failure. After an effective fix the body passes and pytest reports a strict unexpected pass until the owner removes the marker.

| P1 | Test file:line under tests/harness | Current failure reproduced? | Reason and owner | What a fix would change; gaps in the assertion |
|---|---|---|---|---|
| N02 | `test_known_failures.py:18` | Yes. A synthetic value from untrusted driver-like prose is copied into diagnostics. | Correct · A | Removing that value makes the body pass. A direct formatter call with RuntimeError misses other extraction paths and leaks in ASGI, scheduler or operator sinks. S4 needs those sinks. |
| B6-02 | `test_known_failures.py:57` | Yes. After two dated decisions, an undated reversion is acknowledged while the current row retains the prior action. | Correct · C | Applying the decision or rejecting ambiguity can pass. Any 409 returns without checking state; a 200 with another status can pass without reconciliation. Assert the setup decisions, surviving evidence on conflict, and the watermark across both revision adapters. |
| B6-03 | `test_known_failures.py:28` | Yes for the missing intake deadline. A small local body completes after the virtual clock advances an hour. | Correct for deadline · A | A handler-raised 408 passes. An effective middleware deadline is invisible to this direct call, and a deadline alone can pass with unlimited concurrent readers. S3 must exercise real admission, release and concurrency. |
| B7-01 | `test_known_failures.py:76` | Yes. An annotation already bound to task 1 acquires task 2 in the stored row. | Correct · C | A 409 with the original binding makes the body pass. Only the task ID and row cardinality are checked. Add freshness checks for the original verified evidence and lineage. |
| R3-03 | `browser/test_browser_contracts.py:108` | Yes. Successful Save Tags keeps the next typed tag. The test then examines dirty-category approval and both an unsaved chip and typed text after a real conflict. | B is correct; reason names only the category branch | Disabling approval and retaining the conflict draft can pass. Button state alone misses a correct click-time confirmation, and manual navigation is untested. S31 should assert whether a verification request escaped. |
| F7-01 | `browser/test_browser_contracts.py:146` | Yes. Manual review and automatic next put the pending DTO in the history entry. | Correct · B | Removing usr.label from both paths passes. Renaming that property or storing its private children elsewhere also passes. Assert allowed identifiers and absence of fixture text/annotator across account rotation and Back. |

There were zero unexpected passes. Six genuine reproductions do not certify six complete repair oracles. Keep sibling-path and integration coverage at the owning gates.

## 4. Infrastructure and regression evidence

**Database isolation.** `fixtures/pg_schema.py:29–52` creates a UUID-named PostgreSQL schema, sets search_path on each connection, checks current_schema and creates the ORM tables. Nested finally blocks dispose the scoped engine, drop the generated schema and dispose the admin engine. This handles normal pytest unwinding. Forced process termination can bypass teardown. The advisory lane uses a temporary SQLite file with foreign keys enabled. `conftest.py:27–38` marks advisory items and documented divergences. Its CI job uses continue-on-error; the primary job does not. Fixed names such as L1 and contract-event are scoped to independently created schemas.

**Real app and factories.** `conftest.py:57–87` runs the real application and lifespan with the request session, private billing/scheduler session factories, health engine, legacy store and connector file redirected. The factories create real tenant credentials, scoped domains, engine snapshots and scored labels. Calling user twice can supply two distinct keys for one tenant. Fresh sessions are available for independent transactions. Signup mail and checkout transport are stubbed locally. A scheduler mail scenario will need a separate stub for its own sender.

**Migration boundary.** The harness uses create_all rather than historical migrations. Production migration imports its own engine at `db/migrate.py:12,76`. Calling it unchanged from S13 would address the process-configured database instead of the private fixture schema. Set up historical DDL in a private schema and explicitly bind the migration engine there before testing the repeat upgrade.

**Combined pytest discovery is broken.** Root collection with only the four specified live/ops exclusions discovered 532 tests (444 existing plus 88 harness), then exited 1 with `ValueError: no option named 'harness_sqlite'`. The nested conftest registers its option at lines 18–19. When it loads during root discovery, the collection hook at lines 30–31 reads an option missing from the parsed namespace. The fixture repeats that lookup at line 47. Dedicated harness and baseline commands bypass the issue. There was no duplicate-module import error.

**Browser coverage.** `browser/test_browser_contracts.py:24–47,51–101` honors DLJ_PORT or binds an available loopback port. Chromium checks headings, navigation, a screen-specific control and console/page errors in the built application. Upload, Queue, Review, Dashboard, Annotators, Health, Signup and Settings account for all eight screens. A ninth test exercises text, NER, category, save and guideline controls. It samples components; the existing Node suite covers additional interactions. The initialization script at line 68 reinstalls the original key/domain on every document load. Use one-time initialization or an unseeded second context for the future rotation/reload scenarios.

**CI coverage.** The workflow builds the SPA and runs the Python browser harness plus pytest in separate jobs/commands for the two database lanes. It does not invoke the 124-test Node suite or exercise combined root collection. The browser results in this review are local measurements.

| Execution | Observed result |
|---|---|
| Full harness, PostgreSQL | 55 passed (46 HTTP and nine browser), 27 skipped, six xfailed |
| Contract directory | 46 passed on PostgreSQL; 46 passed in the explicit advisory SQLite run |
| Scenario directory | 27 skipped |
| Focused known failures | Six xfailed, zero XPASS, 82 deselected |
| Existing pytest with harness and four live/ops exclusions | 443 passed, one skipped on configured PostgreSQL |
| Existing Playwright, fresh production SPA and isolated real service | Default eight workers: 100 passed/24 failed, then 105 passed/19 failed. Two workers: 124 passed in 52.4 seconds. |
| Combined root collection with the four exclusions | 532 collected, then internal error before test execution |

The initial overlapping full-harness and existing-pytest runs also hit the 30-second timeout. Separate PostgreSQL reruns completed with the same timeout. Browser failures included ordinary page-navigation timeouts across unrelated screens. The eight-worker retry also used the Windows selector loop from the successful two-worker run. The passing lower-concurrency result establishes functional coverage on this host. The requested default configuration was not repeatably green, and these measurements do not attribute the timeouts to a specific product change.

## 5. Prompt A readiness

**NOT READY.** The database and ordinary request fixtures are sufficient for serial identity/billing setup, and A's 14 shells are correctly assigned. The following R1 gaps must be resolved before A can rely on this harness.

| Blocker | Required change and evidence |
|---|---|
| Standard pytest discovery · `conftest.py:18–19,30–31,46–48` | Register the option in an initially loaded plugin or supply a root-safe default and a tested explicit advisory invocation. Root collection and a combined primary run must exit successfully with only the four existing exclusions. Verify both explicit dialect selections still work. |
| Request-owned durability · `fixtures/factory.py:55–71`, `conftest.py:74–80` | Bind observers and invocation counts to individual ASGI requests. Overlap an observed write with a read and with another observed write. Each callback must run exactly once at its own response start. A deliberately late write must fail its own observation. Rerun the 22 serial checks. |
| Identity and billing entry contracts · `contracts/test_auth.py:8–18`, `contracts/test_billing.py:13–40` | Send signup without a credential header, issue an admin key using just its admin credential, and send a signed provider notification without a tenant key. Authenticate with the returned signup key and match the persisted tenant. Assert the purchaser's actual key ID and tenant in checkout custom data. Preserve sandbox coverage. |
| DTO freeze · `contracts/test_labels.py:58–65`, `contracts/test_dashboard.py:8–31`, `contracts/test_revisions.py:7–18` | Assert pending factors, populate the dashboard collections whose element shapes are being frozen, and check structured content keys/types through both detail aliases. Show that dropping a required field fails the relevant contract. |
| Repeatable browser baseline · `playwright.config.ts:3–16` | Establish the supported gate worker count and run all 124 against a fresh SPA and isolated service. Two workers passed here. Either adopt and enforce a reproducible runner configuration or resolve the repeated default-run timeouts before declaring that gate green. |

Prompt A owns implementation of the S1–14 scenarios, including historical migration and real concurrency. B and C own the supplemental controls alongside their findings. The six expected product failures and 27 planned skips are intentional; neither is itself a reason to block A.

The v3 plan describes **Prompt 00 plus seven delivery prompts** (A–F and 12), six waves and five reviews over 27 working days. Its two classification tables agree on 24 launch obligations, four accepted risks and one closed contract. The harness matches the PostgreSQL primary, SQLite advisory and scenario-owner decisions. The gate remains open until the corrective evidence above is recorded.
