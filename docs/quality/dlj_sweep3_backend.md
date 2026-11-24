# DLJ backend sweep, round 3

24 November 2026 · jm-service at `7cb0c27`

**20 open P1, 13 P2 and 2 P3 findings. Round 2 fix verification: 5 CLOSED, 5 PARTIAL, 0 OPEN, 0 REGRESSED.** The preceding backend ledger had 23 P1s. Six no longer carry forward (R11, R12, R18, R31, R35, R44), leaving 17 inherited P1s. This pass identifies three additional P1s (N02, N03, N05). Only N05 of these three is introduced by the round 2 change. “All rounds” uses the backend ledger, including its cross-cutting browser findings. Frontend-only findings from the independent browser sweep are outside that denominator.

The scorecard grades the original failure mode. A CLOSED verdict can coexist with a separate regression elsewhere. Repeated IDs across dimensions count once. Lower-severity totals count the findings assessed in this audit. Runtime checks used isolated fixtures. Concurrency findings identify specific unprotected transaction boundaries from source, unless a test observation is stated.

### Five highest risks and fix priority

| Priority | Risk | Fix and release check |
|---|---|---|
| 1 | R14, N05 · retention can delete live data or keep cancelled tenants indefinitely | Serialize eligibility and key creation at tenant scope, distinguish active entitlement from retention eligibility, and condition deletion on the final decision. Test renewal-first, cleanup-first, new sibling and two expired siblings on both databases. |
| 2 | R08 · one active account credential can reach two people | Prove mailbox ownership before issuing the credential. Test that a requester without mailbox access cannot act on the tenant. |
| 3 | R02, R19 · payment can leave the purchasing key capped or inactive | Reconcile customer, subscription and purchaser before acknowledging entitlement. Assert subsequent scoring with the purchased key across renewal, replacement and cancellation. |
| 4 | R07, N02 · backups or logs can expose credentials or tenant data | Replace raw legacy bearer identifiers, plan key rotation and sanitize database error logging at the outer boundary. Test stored representations and emitted log records. |
| 5 | R13, R45 · review can manufacture truth or remove negative evidence | Require an independently supplied outcome in the queue and define stable metric treatment across revisions. Test agreement and correctness separately through review, revision and engine persistence. |

Next fix R23 before upgrading historical SQLite stores, then R24/R06 transaction consistency, R03/R01 connector revision and learning parity, and R09 anonymous admission. Resolve remaining crash and multi-worker data-loss paths before treating a passing regression suite as a convergence gate.

## 1. Round 2 fix verification

Five changes close their reported failure mode. Five improve a path while leaving part of the original exposure. Severity in the scorecard is the original priority. Only outstanding findings enter the current totals.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R14 | P1 | scheduler.py:58–89, billing.py:120–123,207–225 | **PARTIAL.** The deletion transaction locks the candidate key by UUID and rechecks activity, subscription identity, cancellation time and age. | A committed same-key renewal before the PostgreSQL lock is respected. The sibling lookup cannot reserve an absent sibling, and SQLite does not lock the candidate on SELECT. See §3. |
| R44 | P1 | billing.py:180–195,206–226 | **CLOSED.** Cancellation resolves by subscription ID and bypasses product mapping. | Unknown, missing or retired products no longer veto a valid cancellation. Signature, receipt and ordering checks still apply. |
| R13 | P1 | labeling_router.py:140–153,486–494, frontend/src/screens/ScoredQueue.tsx:152 | **PARTIAL.** Explicit `outcome` reaches single verify. The missing/null case logs and derives truth from action. | The normal UI always takes the deprecated branch. Agreeing with a rejection can still count an incorrect label as correct. |
| R35 | P1 | labeling_router.py:499–523 | **CLOSED** for batch-handler logs. Both database error branches log the item index, exception class and correlation ID without formatting the exception or attaching a traceback. | Duplicate-row SQL parameters stay out of this handler's logs. Independent exception boundaries are addressed in §4. |
| R30 | P1 | jm_service.py:175–181,450–475, jm_core.py:348–350,511 | **PARTIAL.** The legacy create route rejects the separator in both lists. | Restoring old snapshots directly restores ambiguous centroid keys. A historical collision is still shared by otherwise distinct category/action pairs. |
| R45 | P1 | labeling_router.py:614–624,667–682, db/repository.py:144–155 | **PARTIAL.** Exact category equality on a verified false predecessor returns 409. | A category change produces an unverified successor. Current accuracy loses the negative immediately, and editing the new row can restore the original category. |
| R18 | P1 | trial_guard.py:72–105 | **CLOSED** for paid capacity at reservation. An effective cancellation uses 50/day. | The former paid monthly allowance no longer admits chargeable work past the daily limit. The account DTO still advertises the paid limits (§2). |
| R31 | P1 | label_studio.py:147–162,257–277 | **CLOSED** for malformed result containers/entries and null annotation IDs. | Malformed result structure encountered in parsing is skipped with a warning before ingest. A missing/null ID gets 422 before conversion. Envelope validation is separate. |
| R29 | P1 | label_studio.py:32,165–185 | **PARTIAL.** Each writer uses a unique closed temporary file and replaces it while holding the read-modify-write lock. | Concurrent processes sharing the file can still publish updates based on the same old dictionary. One successful configuration disappears. |
| R11 | P1 | label_studio.py:114–132,228–233,289–301 | **CLOSED** for the two boundary failures. Conversion catches overflow and new webhook items translate Pydantic errors to 422. | Connector IDs assigned outside the model still have the independent R05 failure. |

The brief describes fourteen outstanding original verdicts but names eleven R findings. Original verdicts and consolidated R findings have different denominators. The following eleven are assessed individually. R01 is also carried below. The previously cross-cutting R12 is closed for import ownership by the captured credential passed to every batch at frontend/src/screens/Upload.tsx:74–95.

| Finding | Change since round 2 | Current evidence and consequence |
|---|---|---|
| R02 | UNCHANGED | billing.py:120–141 returns the customer-bound key before resolving a conflicting purchaser key. |
| R03 | UNCHANGED | db/repository.py:228–243 copies text and source IDs but omits content and predecessor metadata. |
| R04 | UNCHANGED | label_studio.py:135–144 and db/repository.py:52–59 still use read-then-insert without a consistent conflict response. |
| R05 | INCIDENTALLY IMPROVED | label_studio.py:290–301 translates invalid new reviewer data. Existing-row reviewer/source assignments and the task public domain name remain unbounded. |
| R06 | UNCHANGED | jm_service.py:541–551,596–605 uses separate units of work for decision log and snapshot. |
| R07 | UNCHANGED | jm_service.py:64–95,436–447 persists the legacy token as identity. |
| R08 | UNCHANGED | auth.py:49–66 sends an active credential before proving control of the address. |
| R09 | UNCHANGED | label_health/api.py:45–63 admits waiters after reading their bytes. |
| R19 | UNCHANGED | billing.py:180–181,206–229 acknowledges unsupported event types and stores one subscription per key. R44 fixes an already-supported type. |
| R23 | UNCHANGED | db/migrate.py:118–145 preserves old provider values by rename only on PostgreSQL. |
| R24 | UNCHANGED | db/connection.py:37–51 adds SQLite FK enforcement but no serialization for read-modify-write. Engine versions do not protect key counters or label revisions. |

## 2. Authentication, quota and billing

The active-key dependency authenticates a tenant and saves its key digest in the session. Only paths that call the reservation function enforce trial expiry and the cancelled-key limit. The ten fixes add no new unmetered endpoint.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R19 | P1 | billing.py:180–187,205–229 | Only created, updated and canceled are dispatched. An update can clear cancellation on an inactive key without enabling it. A new creation can overwrite the previous subscription ID. | Provider and service entitlements diverge. A still-paying or reactivated customer can remain locked out, or a status change can leave paid capacity in place. |
| R20 | P2 | labeling_router.py:394–437,475–494,570–607 | Single verify and unclassified task creation never reserve. The bulk version reserves before calling verify. | At a cap or after trial expiry the same review can still learn through a single submission. This difference predates R18. |
| N01 | P2 | account.py:33–50, trial_guard.py:82–104 | Account usage selects caps from stored tier alone. | A cancelled professional account can display no daily cap and a 100,000 monthly cap while receiving daily 429s at 50. |

**Application route inventory.** T means an active DLJ tenant key, LS the service token, L a separate legacy key, and admin the admin secret. “Both” means expired trial and effectively cancelled paid keys that still authenticate. A deactivated DLJ key fails T everywhere. Framework documentation and static assets are public mounts outside these 46 method/path pairs.

| Method and path (d = domain, id = label) | File:Line | Auth | Reservation | Expired trial / cancelled paid key |
|---|---|---|---|---|
| GET /v1/domains/{d}/guidelines | labeling_router.py:54 | T | — | both accessible while active |
| PUT /v1/domains/{d}/guidelines | labeling_router.py:60 | T | — | both accessible while active |
| POST /v1/labels/ingest | labeling_router.py:380 | T | 1 | expired blocked / cancelled daily |
| POST /v1/labels/verify | labeling_router.py:394 | T | — | both accessible while active |
| POST /v1/labels/{d}/bulk-verify | labeling_router.py:440 | T | 1 per eligible label | eligible work checks expiry / daily cap with partial success |
| POST /v1/labels/ingest/batch | labeling_router.py:498 | T | 1/item, atomic | expired blocked / cancelled daily |
| POST /v1/labels/{d}/sample | labeling_router.py:526 | T | 1/missing row | expired blocks newly charged work / cancelled daily |
| POST /v1/labels/{d}/tasks | labeling_router.py:570 | T | 1 if classified | expired blocks newly charged work / cancelled daily |
| POST /v1/labels/{d}/items/{id}/relabel | labeling_router.py:610 | T | 1 if first classification | expired blocks newly charged work / cancelled daily |
| GET /v1/labels/{d}/pending | labeling_router.py:693 | T | — | both accessible while active |
| POST /v1/labels/{d}/items/{id}/content | labeling_router.py:754 | T | — | both accessible while active |
| GET /v1/labels/{d}/items/{id} | labeling_router.py:797 | T | — | both accessible while active |
| GET /v1/labels/{d}/{id} | labeling_router.py:798 | T | — | both accessible while active |
| GET /v1/domains/{d}/autonomy | labeling_router.py:823 | T | — | both accessible while active |
| POST /v1/label-studio/configure | label_studio.py:165 | T+LS | — | both accessible while active |
| POST /v1/label-studio/setup | label_studio.py:188 | LS | — | independent |
| POST /v1/label-studio/predict | label_studio.py:198 | T+LS | 1/new score | expired blocks newly charged work / cancelled daily |
| POST /v1/label-studio/webhook | label_studio.py:252 | T+LS | 1 via new ingest only | expired blocks newly charged work / cancelled daily |
| GET /v1/label-studio/health | label_studio.py:335 | public | — | independent |
| GET /v1/billing/checkout-url | billing.py:59 | T | — | both accessible while active |
| POST /v1/billing/webhook | billing.py:159 | HMAC* | — | independent |
| GET /v1/health | jm_service.py:412 | public | — | independent |
| POST /v1/register | jm_service.py:436 | public | — | independent |
| POST /v1/domains | jm_service.py:450 | L | — | independent |
| GET /v1/domains | jm_service.py:492 | L | — | independent |
| POST /v1/domains/{d}/score | jm_service.py:515 | L | — | independent |
| POST /v1/domains/{d}/learn | jm_service.py:563 | L | — | independent |
| GET /v1/domains/{d}/diagnostics | jm_service.py:617 | L | — | independent |
| GET /v1/domains/{d}/state | jm_service.py:637 | L | — | independent |
| POST /v1/auth/register | auth.py:47 | public | issues trial | independent |
| POST /v1/admin/api-keys | auth.py:106 | admin | issues key | independent |
| GET /v1/account | account.py:26 | T | — | both accessible while active |
| GET /v1/account/domains | account.py:54 | T | — | both accessible while active |
| POST /v1/account/domains/resolve | account.py:73 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/iaa | dashboard_router.py:150 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/overview | dashboard_router.py:211 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/corrections | dashboard_router.py:234 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/annotators | dashboard_router.py:258 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/factors | dashboard_router.py:296 | T | — | both accessible while active |
| GET /v1/dashboard/{d}/compounding | dashboard_router.py:320 | T | — | both accessible while active |
| POST /v1/label-health/analyze | label_health/api.py:71 | public | — | independent |
| POST /v1/label-health/report | label_health/api.py:76 | public | — | independent |
| POST /v1/label-health/report/pdf | label_health/api.py:81 | public | — | independent |
| GET /terms | legal_pages.py:128 | public | — | independent |
| GET /privacy | legal_pages.py:133 | public | — | independent |
| GET /attribution | legal_pages.py:138 | public | — | independent |

*Billing webhook requires HMAC with a configured secret. A missing secret fails closed outside explicit sandbox. Created requires a known product. Updated allows absent items for status-only messages and validates supplied product data. Canceled ignores items, still checks subscription ID, event ID and occurrence time, and gives cancellation priority on a timestamp tie. Other event types return 200 before receipt creation. Active cancelled keys can start checkout through the same authenticated route as paid keys.*

Both UTC period keys are rolled forward independently before the capacity check. A cancelled paid key retains its stored tier, so the 14-day trial-expiry test does not expire it. Reservation 50 succeeds when usage is 49. At 50 the next eligible reservation fails. Existing usage from earlier that day counts, monthly usage continues accumulating, and monthly rollover alone cannot reopen a full day. Batch ingest rolls back on failure. Bulk commits eligible reservations up to capacity and returns per-label skips. An all-existing sample or all-skipped bulk request can complete without reserving.

Explicit bulk truth flows through VerifyRequest, verify_and_learn and engine.learn(outcome_correct=…). The row and correct/incorrect factor trackers use that value. Centroid movement targets the actual action. Engine conservation and total_correct measure recommendation agreement, whereas the category gate rebuilt from rows measures verified correctness. The two measures can disagree even when the stored explicit outcome is correct (jm_core.py:346–378, labeling_router.py:293–313).
## 3. Data integrity and concurrency

PostgreSQL serializes cleanup with a webhook locking the same existing key. It does not serialize every operation that can make a tenant eligible or ineligible. Reads followed by writes need a different guard on SQLite.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R14 | P1 | scheduler.py:63–88, auth.py:106–117 | Per-key lock held through all deletes. The sibling check is a plain existence query with no tenant lock shared by key creation. | A newly committed sibling can own a tenant whose rows cleanup is deleting. If cleanup wins first, later reactivation cannot restore the deleted rows. |
| R24 | P1 | trial_guard.py:67–99, labeling_router.py:614–618,676–681 | SQLite omits row-level locking. Key counters and predecessor links are updated from previously read values without a conditional update. | Competing writers can see stale eligibility or revision state. Depending on transaction timing they can lose an increment, fork revisions, or fail with database busy. |
| R45 | P1 | labeling_router.py:617–624,668–682, db/repository.py:149–153 | The same-category restriction applies only to a verified false current row. Category comparison and schema membership both use exact spelling. | A legitimate change removes the negative from current metrics before replacement verification. A subsequent edit to the unverified successor can restore the earlier category. Case variants work only if both exist in the schema. Historical learning persists. |
| R29 | P1 | label_studio.py:32,171–185 | Unique temp names prevent writers damaging each other's temporary file. The lock covers read through replacement in one interpreter. | Two workers sharing storage can acknowledge conflicting snapshots. Replicas with separate local files also do not share configuration. |
| R04 | P1 | label_studio.py:135–144, db/repository.py:51–65 | First creation reads before inserting, and connector calls do not consistently map insert collisions. | A competing valid request can get an unhandled database error. |
| R25 | P2 | scheduler.py:65–85, labeling_router.py:451–453,477 | Cleanup locks key then deletes labels. Bulk locks selected labels then reserves the key. Ingest may also lock a domain before reserving. | A PostgreSQL lock cycle can abort a transaction. The same-key webhook and cleanup alone have no demonstrated lock cycle. |
| R27 | P2 | labeling_router.py:538–565 | Sample replay counts the original physical labels without following revisions. | The seed response can report a superseded label as pending after the current revision was verified. |
| R28 | P2 | dashboard_router.py:140–147 | Degenerate agreement is returned as 1 when expected agreement equals 1. | A single-class overlap looks like defined perfect agreement. |
| R49 | P2 | labeling_router.py:293–311,356–365 | Scoring reads complete verified rows to rebuild per-category history on each item. | Import cost grows with historical volume, including source text irrelevant to the calculation. |
| R50 | P2 | label_studio.py:211–230 | Prediction replay uses the physical scored row. | After revision, repeat prediction can apply superseded category/confidence while detail resolves the successor. |

A scan result is only a candidate. Inside a fresh transaction the key UUID, current subscription, activity and UTC cancellation cutoff are checked before the first delete. LabelContent cascades from LabelLog. Engine, annotator, domain deletion and key disable commit together for one tenant. Each subsequent tenant has its own transaction. On SQLite a plain selection does not exclude a billing writer between recheck and first delete.

The Windows test used a closed temporary file in the destination directory and read the final map after both writes. Successful replacement publishes a complete file. Sharing/permission errors can still fail replacement and the test does not establish crash durability or simultaneous reader behavior. [Python os.replace documentation](https://docs.python.org/3/library/os.html#os.replace)

**Write boundaries.** DLJ ingest, batch, bulk, seed, verify, task, relabel, content, guidelines and domain-name resolution share request commit/rollback (db/connection.py:55–62). Connector score/relearn use this session too. Engine updates check a version, but initial inserts and predecessor links use different guards. Billing receipts and key changes share a transaction, and optional email changes have a savepoint. Checkout creates a remote transaction. Signup and scheduler mail send before local commit, so a failed commit can leave a delivered credential or duplicate notice. File configuration commits outside SQL. Legacy score and learn save their engine separately (§6).
## 4. Input validation and errors

The only new request field is optional and its OpenAPI name is `outcome`. The batch handler now redacts database errors locally. The service still lacks equivalent protection at its uncaught-exception boundary.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R05 | P1 | labeling_router.py:591–600, label_studio.py:292–316 | A task path can become public_domain_id without the body limit. Existing-row source/reviewer IDs bypass new-item model validation. | PostgreSQL can reject a value that the API accepts. SQLite permits it, masking the failure. |
| R30 | P1 | jm_service.py:175–181, jm_core.py:200–206,348–350,511 | The single public legacy creation model validates names. Old persisted states load their original centroid dictionary. | Previously ambiguous keys continue to mix learning. Existing snapshots need collision detection and a recovery policy. |
| N02 | P1 | db/connection.py:38–40,55–62, scheduler.py:100–101, label_studio.py:299–306 | The engine does not suppress SQL parameters. The request dependency reraises unhandled DB exceptions, and scheduler exception logging includes tracebacks. | Framework/server traceback logging can include bound row values on an unhandled write. The batch duplicate test cannot establish a global logging guarantee. No production log disclosure was observed. |
| N03 | P1 | label_studio.py:253–256 | Webhook dispatch checks set membership on an unconstrained JSON value before validating its type. | A nonhashable action raises an uncaught TypeError for the request before the new result guard runs. This predates the parser change. |
| R32 | P2 | labeling_router.py:68–73,693–702, label_studio.py:48–55,199–208 | Factor maps and names, connector task counts and several path/query values lack practical upper bounds. | An accepted request can allocate disproportionate memory or exceed a database parameter range. |
| R33 | P2 | labeling_router.py:189–247,636–648,772–788 | Content creation and revision have different list, tag and vocabulary checks. | Existing content can be valid to create but impossible to resave without discarding or shortening data. |
| R36 | P2 | labeling_router.py:508–519,585–587 | Broad exception translation maps operational failures to validation errors and multiple integrity failures to a duplicate. | Clients can abandon a retryable request or report an input conflict that did not occur. |

**Request model review.** Auth RegisterRequest/CreateKey and account.ResolveDomain bound identity lengths. The legacy RegisterRequest display name is unbounded. CreateDomainRequest bounds the domain name and collection counts. The latter validates range pairs and category/action separators, but individual list elements and range-map cardinality are not comparably bounded. Legacy ScoreRequest/LearnRequest accept free strings and a map, then validate against engine state. Billing checkout uses a query string, and the webhook uses a raw dictionary. There is no CheckoutRequest body model.

GuidelinesPayload applies a UTF-8 byte limit. IngestItem/IngestRequest bound IDs and source bytes and require finite [0,1] factors. IngestBatchRequest limits the list to 100. VerifyRequest bounds IDs/reason but actual_action has only a minimum before membership checking. BulkVerifyRequest bounds IDs to 200 unique bounded strings, enumerates action, and permits null or Pydantic-coercible boolean outcome. Omission and null both use legacy derivation. Unknown fields are ignored by default: a client sending single-verify's `verified_outcome` can silently enter that branch. TextTaskRequest bounds source bytes. RelabelRequest, EditableNerSpan, NerSpan and LabelContentRequest combine model checks with stored-text offset and URL validation. Editable span mention text has no independent byte cap before comparison. ConnectorConfig checks field mapping syntax with little size bounding. Dashboard and legacy response DTOs do not validate inbound requests. The health routes accept multipart files directly.

New conflicts use 409 detail strings. Missing annotation ID and conversion or IngestItem failures use 422, as do legacy model validation failures (FastAPI detail list). Skipped malformed connector results return 200 with a status object and server warning. Daily exhaustion returns 429 with a structured detail, and partial bulk success returns 200 with per-item errors. A missing action *inside an otherwise well-shaped annotation result* still gives 422. Neither a skipped response nor a 422 learns the annotation. Batch SQL failures use the indexed detail object. Handled 422 exception chaining does not by itself print a traceback.
## 5. Coverage of the 19 new regression cases

The four fix modules passed together on default SQLite and in reverse module order on PostgreSQL at localhost:5433. Each run returned **48 passed, 1 skipped** including all 19 round 2 cases. The skip belongs to a dialect-specific migration check. The collection baseline with the four requested exclusions was **408**.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R39 | P2 | test_resweep_fixes.py:84–113,237–252 | Retention ordering is injected before the transaction, and config contention is tested with threads in one process. | Tests can pass without testing row-lock exclusion, a sibling insert, multi-worker publication or a reverse lock order. |
| N04 | P2 | test_resweep_fixes.py:122–151,198–214 | Tests assert stored booleans and day counters but omit learning trackers and the account response. | A learning or customer-visible quota regression can pass all four relevant truth/quota paths. |

| Case and test_resweep_fixes.py line | What the assertion establishes | Blind spot / alternative reason for passing |
|---|---|---|
| 1 · reactivation, 84 | Injects an actual committed cancellation clear before begin, verifies live key and label. | Would pass with a fresh unlocked read. No overlapping transaction. |
| 2 · still cancelled, 108 | Checks count cleaned, disabled key, empty labels/domains. | No sibling, new subscription, structured child or rollback injection. |
| 3 · unknown product, 115 | Creates subscription, cancels with unknown name, reads persisted cancelled_at. | Unsigned sandbox fixture, no exact event time or watermark assertion. |
| 4 · retired product, 115 | Same state assertion with a second unmapped name. | Same branch as case 3. Distinction is business history only. |
| 5 · explicit false, 122 | Sets a rejection recommendation, accepts it, checks processed and stored false. Distinguishes override from legacy true. | Does not check actual action, tracker direction or conservation. |
| 6 · explicit true, 136 | Approves and reads back true. | Default branch yields the same value. Explicit true with reject would distinguish it. |
| 7 · implicit outcome, 144 | Reject without outcome stores false and emits warning. | No null or alternate-field spelling, and no tracker assertion. |
| 8 · log redaction, 153 | Real duplicate returns 422, one indexed log has exception class and a 32-character correlation ID, source/factor name absent. | No second request to test correlation uniqueness, non-integrity error, outer logger or configured formatter. |
| 9 · category separator, 166 | Model validation raises the specific separator error. | No HTTP 422 or historical snapshot exercised. |
| 10 · action separator, 166 | Exercises the other validated field with a valid category list. | Same model-only boundary. |
| 11 · same-category correction, 177 | Checks 409, exact detail and unchanged revision. | No structured-only correction or historical accuracy assertion. |
| 12 · changed category, 188 | Materializes another category and reads back new current category after 200. | Does not follow another revision or compare accuracy. |
| 13 · cancelled quota, 198 | Paid key at 50 receives a daily-scope 429. | No 49-to-50 success, day rollover, future cancellation or unchanged counters after denial. |
| 14 · paid quota, 207 | Active paid key goes from 50 to 51. | Does not prove monthly enforcement at its boundary. |
| 15 · malformed result, 221 | Checks 200/skipped, warning and zero labels. | Only one malformed entry, no mixed entries or envelope types. |
| 16 · null annotation ID, 230 | Checks 422 and zero labels. | Does not assert reason, so another 422 could satisfy it. |
| 17 · config race, 237 | Checks both responses and exact saved tenant/project keys. | Thread scheduling can serialize requests even without contention. No independent processes or controlled interleaving. |
| 18 · overflow, 254 | Calls predict with an integer too large for float and expects 422. | Status only. An unrelated 422 would pass. Check factor detail and rollback. |
| 19 · invalid webhook item, 261 | Submits overlength category, checks 422 and zero label rows. | Does not check task index, domain rollback or key counters. |

The fixture translates DLJ_DATABASE_URL to DATABASE_URL for the task client, uses monkeypatch for module factories, sandbox and connector config, and isolates each DB case by temporary file or unique PostgreSQL schema (test_resweep_fixes.py:19–33, test_tasks.py:21–71). Two separator cases are pure model tests on either run. The tested orders show no observed interference. No test races a real renewal against deletion after the check. A two-connection barrier test, a two-process config test, and assertions on actual learned state would discriminate the important remaining paths.
## 6. Remaining P1s from earlier rounds

All eight specifically requested carryovers still meet the P1 criteria. Each has a persistence, ownership or capacity boundary that the round 2 changes do not enforce. The last row records a ninth backend carryover from the prior P1 ledger.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R02 | P1 | billing.py:70–85,120–141, test_billing_fixes.py:93–112 | **Still P1.** Checkout identifies the purchaser, but webhook customer matching returns another active same-tenant key first. | Payment upgrades one credential while the purchaser's scoring limit stays at trial. A passing test endorses this precedence. |
| R03 | P1 | db/repository.py:217–243, labeling_router.py:802–821 | **Still P1.** Connector correction copies scalar source fields but omits LabelContent, prior revision UUID, actor and revision time. | The current detail loses annotations and traceability. The old content can remain physically present. |
| R06 | P1 | jm_service.py:541–551,582–605 | **Still P1.** Legacy decision insert/learn update and engine save each commit independently. | An interrupted save or concurrent snapshot overwrite leaves an acknowledged decision and persisted model out of agreement. |
| R07 | P1 | jm_service.py:64–95,310–322,440–447 | **Still P1.** Legacy tenants, domains and decisions contain a reusable bearer identity. | Read access to the store or its backup grants usable credentials. DLJ hashing covers the other store. |
| R08 | P1 | auth.py:49–66, email_service.py:29–49 | **Still P1.** Public registration issues a key to the requester and emails the same key to an unverified address. | Two people can unknowingly control the same account and its future source data. |
| R09 | P1 | label_health/api.py:15–19,45–65 | **Still P1.** Anonymous report requests hold their upload bytes while waiting for two computation slots. | Concurrent waiting bodies have no aggregate memory budget. The 60-second timeout bounds time only. |
| R23 | P1 | db/migrate.py:84–89,118–145 | **Still P1.** SQLite creates empty Paddle columns alongside historical provider fields. Legacy unscoped ownership also defaults to an empty string. | Old values may remain on disk while live billing lookup fails or authenticated users cannot discover their records. |
| R24 | P1 | db/connection.py:37–51, trial_guard.py:67–99, labeling_router.py:676–681 | **Still P1.** Lock syntax without a SQLite writer guard cannot guarantee conditional updates. | Counters or revision ownership can diverge under competing successful writes. The timing-dependent busy-error alternative does not guarantee correctness. |
| R01 | P1 | label_studio.py:325–332, labeling_router.py:417–432, jm_core.py:349–350 | Connector verification still bypasses HTTP verify's synchronization of newly configured category centroids. | An existing reviewer engine can lack the row category and fail during learning. |

## 7. Regressions and compatibility

Round 2 introduces a retention liveness problem and exposes a conflict between substantive annotation corrections and the new same-category rule. Product dispatch and connector validation preserve the successful happy paths covered by the tests. The remaining danger in bulk review comes from the maintained compatibility behavior.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| N05 | P1 | scheduler.py:75–86, legal_pages.py:47–48,83 | Any other is_active key vetoes deletion even if every subscription is cancelled and every key is past retention. No skipped key is retired. | Two expired siblings keep each other active indefinitely. Tenant data outlives the advertised 30 days and both credentials can still authenticate. |
| N06 | P2 | labeling_router.py:617–641 | The category-equality guard precedes comparison of actual span or tag edits. | A reviewer cannot correct a genuine entity boundary or tag error on a verified-incorrect row while preserving its correct category. |
| R25 | P2 | scheduler.py:65–85, labeling_router.py:451–453,477 | The new key-first deletion lock conflicts with label-first bulk reservation. | A DB victim abort can postpone cleanup or fail legitimate review. Transaction rollback prevents partial deletion for that tenant. |

Compatibility by change: R44 changes only the canceled branch. R13 preserves old payloads and responses, but the TypeScript helper lacks the new field and omitted outcomes warn per request. R18 affects paid keys only once cancellation is effective and a reservation is attempted. It leaves actual trial expiry and active paid monthly charging in place. R30 limits category/action values on new legacy domains, including previously accepted human-readable values containing a pipe. It does not reject a pipe in the display name or migrate saved state. R45 newly blocks structured-only edits as described above.

R31 retains explicit actual_action precedence and the first recognized choice. Null IDs newly fail. A formerly ignored irregular value before a usable result can now cause the entire annotation to be skipped. Empty well-formed results still lack an action. R29 retains the config file format and R11 retains successful numeric conversions and normal prediction responses. Existing fix modules passed alongside the new tests. This round collected the full suite and ran the four fix modules. The session's earlier full execution reported 407 passed and one skipped.
## 8. Deployment, observability and documentation

The Dockerfile builds the SPA with npm ci and npm run build and copies the stage's dist into the Python runtime. The ten fixes require neither new environment variables nor new database columns. The entrypoint runs the existing migration before serving traffic, so the historical SQLite data issue in R23 still matters for upgrades.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R38 | P3 | scheduler.py:70–89, billing.py:213–235, trial_guard.py:82–104 | Retention logs sibling skips and deletion before commit. Billing and effective quota transitions have no corresponding durable outcome log. | An operator cannot reconstruct the interleaving from success logs. A rolled-back cleanup can look complete. |
| N07 | P3 | labeling_router.py:140–145,444–445, frontend/src/api.ts:210, account.py:41–50 | OpenAPI exposes a nullable outcome without explaining its difference from action, the compatibility default, or the effective quota displayed after cancellation. | SDK users can record agreement as truth. Operators lack a consistent explanation for daily 429s on a paid tier. |

The HMAC configuration, price mapping, DATABASE_URL and writable LS_CONFIG_PATH retain their previous meanings. Temporary connector files are adjacent to that path and require write/replace permission. Dockerfile:1–6,25 and .dockerignore exclude dependence on the developer's dist. docker-entrypoint.sh:5–16 runs the migration and then starts Uvicorn. Image startup and live Paddle delivery were outside the executed tests.

Malformed annotation skips and implicit outcomes warn. Batch exception logs carry a request ID in LogRecord.extra, but the response does not expose that ID and a plain formatter can omit it. Most expected validation conflicts and cancellations have no transition-level telemetry. Record committed retention decisions with key/subscription identity, eligibility result and timestamp, and expose the applied quota policy in the account contract. Document `outcome` as independently observed correctness with an example where it differs from agreement.

### Review inventory

35 distinct repository files contributed source or evidence. The inventory excludes files merely enumerated during pytest collection.

`docs/session_state.md`, `docs/quality/dlj_resweep_backend.md`, `docs/quality/dlj_resweep_frontend.md`, `billing.py`, `scheduler.py`, `trial_guard.py`, `auth.py`, `labeling_router.py`, `label_studio.py`, `jm_service.py`, `jm_core.py`, `db/models.py`, `db/migrate.py`, `db/connection.py`, `db/repository.py`, `account.py`, `dashboard_router.py`, `email_service.py`, `policy_engine.py`, `rate_limit.py`, `label_health/api.py`, `label_health/analyze.py`, `legal_pages.py`, `test_resweep_fixes.py`, `test_billing_fixes.py`, `test_migration_fixes.py`, `test_validation_fixes.py`, `Dockerfile`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/api.ts`, `frontend/src/screens/Upload.tsx`, `test_tasks.py`, `docker-entrypoint.sh`, `.dockerignore`, `test_scheduler.py`.
