# DLJ backend sweep 4 — convergence

24 November 2026 · jm-service · commit `bdc4927`

**Post-Track 2 implementation can start with the merged plan's integration harness and corrective work. Feature rollout is not ready.** Seventeen distinct P1s remain in the backend audit ledger. Fourteen need launch gates and three have explicit v1.1 risk acceptance. The normal browser bulk request still silently derives ground truth. The anonymous report service also acquired a new availability risk when admission moved ahead of multipart parsing.

| Measure | Round 4 result |
|---|---|
| Eight round 3 fixes | **4 CLOSED, 4 PARTIAL, 0 OPEN, 0 REGRESSED** against the published failure modes |
| New findings | **1 P1, 3 P2, 1 P3**. The five S4 identifiers below are counted once each. |
| Cumulative P1 closure | **21 of 40 fully closed (52.5%)**. Two additional findings fell below P1, leaving **17 open P1s**. Thus 23 of 40 (57.5%) have exited P1 priority. |
| Eleven named structural findings | **11 still P1**. Eight belong to the merged implementation waves. Three legacy findings are explicitly deferred to v1.1. |
| Verification | Five fix modules passed on SQLite and PostgreSQL, **63 passed and one expected dialect skip per database**. All 15 round 3 cases ran on each. Default collection found 423 cases. Full default run: **422 passed, 1 skipped**. |
| Evidence | Source and test review includes all files in the brief, prior ledgers, the merged plan, the browser bulk call and its test. Schema and DTO checks used the installed app libraries. No production Paddle delivery, production retention run, load test or browser re-sweep was performed. |

## 1. Round 3 fix verification

The clearest closures are sibling retention, both cancellation representations, UTC handling at quota reservation and connector centroid repair. Four targeted changes work on their positive cases but leave a documented part of the original failure or the requested boundary unresolved.

| Fix | Verdict | Current trace and residual failure |
|---|---|---|
| R14 · retention | **CLOSED** for the sibling-insert window and mutual-cancellation loop | scheduler.py:58–108 takes a PostgreSQL table writer guard or SQLite BEGIN IMMEDIATE, then re-reads all sibling rows in stable order. It checks candidate identity, subscription, active flag and cutoff under the guard. All expired active siblings retire together. Any remaining active sibling preserves the data. A writer serialized after committed cleanup cannot restore deleted history. New lock-order exposure is S4-02. The distinct N05 loop also closes here. |
| R44 · cancellation | **CLOSED** | billing.py:180–196,206–231 classifies both subscription.canceled and subscription.updated with status=canceled before product lookup. Both still require a valid subscription ID, receipt and aware event time. Created still requires a known product. An unknown product on an ordinary update continues to fail. |
| R13 · independent bulk truth | **PARTIAL** | labeling_router.py:140–145,481–488 passes explicit true **or false** through verify into repository.py:281–286. Omitted/null outcome retains the historical approve→true/reject→false rule. ScoredQueue.tsx:152 supplies only IDs/action. frontend/src/api.ts:210 generates **verified_outcome** from that action. The DTO's field is **outcome**. A direct model check with a browser-shaped body produced outcome=None. The fallback is wire-compatible but the user's independent observation never reaches learning through this UI. |
| R45 · no-op revisions | **PARTIAL** | labeling_router.py:610–648,667–688 rejects identical category, effective spans and tags with 409. A same-category genuine span change is allowed. Ordered-list comparison treats reordered multilabel tags as changed, even with identical membership. More fundamentally, a real edit supersedes the negative before replacement verification. repository.py:149–162 filters out superseded observations, so accuracy can improve without new evidence. N06's blanket same-category rejection is removed. |
| R18 · cancelled-key capacity | **CLOSED** at reservation | trial_guard.py:26–28,76–106 treats naive timestamps from SQLite as UTC and converts aware timestamps before the comparison. Effective cancellation uses the daily cap even for paid tiers. Future cancellation retains the paid policy until due. Separate metering and display gaps remain in §4. |
| R01 · connector learning | **CLOSED** for missing category centroids | label_studio.py:323–334 validates the category and calls the shared synchronizer before learning. db/repository.py:94–101,238–246 also covers a correction in the reviewer's engine. Each configured action gets a missing centroid even if the category already exists. Existing learned vectors are preserved by setdefault. |
| R03 · connector revisions | **PARTIAL** against the original content **and provenance** finding | db/repository.py:128–133,247–256 copies type, spans, tags and image URL to a separate child, plus text, source task and annotation identifiers. Copy and forward supersession share the transaction. The successor still lacks prior_revision_id, revision_actor and revision_at, unlike labeling_router.py:675–681. Evidence and forward history survive, so the remaining audit/provenance defect is **P2**. An image copy is supported by source and lacks a dedicated correction test. |
| R09 · anonymous upload admission | **PARTIAL** | label_health/api.py:72–88 reserves capacity before request.form() and immediately returns 503 when full. The old unbounded queue of already-read CSVs is gone. The 10 MiB check at lines 54–56 applies to the selected file **after** multipart spooling. It bounds analysis input but does not bound bytes admitted by the parser, aggregate parts or temporary disk use. Keep the ingress-size exposure at P1 until the effective deployment or application enforces a streaming request limit. Intake duration is the separate new finding S4-01. |

## 2. Remaining structural P1s

All eleven specified structural issues still have live code paths. Retention's SQLite writer guard is a concrete improvement to R24 in one operation. Quota reservation and ordinary revisions still depend on row locking that SQLite does not provide.

| ID | Change since round 3 | Current severity | File:line, impact and disposition |
|---|---|---|---|
| R02 | UNCHANGED | P1 | billing.py:70–85,118–141. Checkout identifies the purchasing key. A pre-existing same-tenant customer match can select a different key before the purchaser UUID is considered. Resolve entitlement ownership in merged 02. |
| R04 | UNCHANGED | P1 | label_studio.py:135–144 and db/repository.py:23–31,49–66. Both writers can observe absence. First domain/engine insert conflicts still escape inconsistently by entry point. Cover creation concurrency in 05. |
| R05 | UNCHANGED | P1 | labeling_router.py:565–596 and label_studio.py:264–273,308–321. Derived task/domain/reviewer values can bypass body bounds before storage in VARCHAR(200) fields. SQLite permissiveness can mask PostgreSQL failure. Bound values at every boundary in 04. |
| R06 | UNCHANGED | P1 | jm_service.py:541–551,596–605. A legacy decision and its engine snapshot commit independently. Interrupted learning can leave contradictory durable state. Explicit v1.1 acceptance. |
| R07 | UNCHANGED | P1 | jm_service.py:64–95,436–447. Legacy bearer values persist as identity in a separate store and its backups. DLJ key hashing does not protect these legacy rows. Explicit v1.1 acceptance. |
| R08 | UNCHANGED | P1 | auth.py:47–66. The requester receives an active key that is also sent to the supplied mailbox before control is proven. Address uniqueness and rate limiting do not establish ownership. Merged 03. |
| R19 | UNCHANGED | P1 | billing.py:180–185,205–235. Three subscription event types are recognized. Unsupported events are acknowledged, and one subscription ID per key cannot represent replacement history. A later active update can clear cancellation without enabling an already retired key. Merged 02. |
| R23 | UNCHANGED | P1 | db/migrate.py:84–89,118–145. Only PostgreSQL renames legacy provider columns. A SQLite upgrade can retain old values under old names while readers use new empty columns. Historical ownership also needs reconciliation. Merged 02. |
| R24 | INCIDENTALLY IMPROVED | P1 | scheduler.py:66–76 protects SQLite cleanup. trial_guard.py:72–103 and labeling_router.py:608,679–681 still use read/modify/write without equivalent SQLite serialization or compare-and-set. Expected quota/revision guarantees remain dialect-dependent. Merged 05. |
| R29 | UNCHANGED | P1 | label_studio.py:32,165–185. Unique temporary files and a process-local lock protect one interpreter. Concurrent processes can overwrite acknowledged configuration. Merged 05. |
| R30 | UNCHANGED | P1 | jm_service.py:175–181 and jm_core.py:200–206,348–350. New legacy domains reject the separator. Existing snapshots restore their ambiguous keys without reconciliation. Explicit v1.1 acceptance. |

The plan defers **only R06, R07 and R30 to v1.1**. Its acceptance depends on isolation of the legacy service and lack of known external consumers. Smaller request volume alone does not cure any of these three failure modes. [Merged plan classifications](../design/dlj_arch_redesign_v2.md)

## 3. Regressions and compatibility

The changes preserve ordinary explicit and legacy bulk payloads, populated connector evidence, and valid CSV analysis while capacity is available. Moving admission earlier changes the lifetime of a worker permit, the PostgreSQL retention guard introduces a lock-order risk, and the raw Request signature changes the public API description.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S4-01 | P1 | label_health/api.py:62–78 | A shared computation permit now covers multipart intake. The 60-second timeout starts only after parsing, selected-file read and executor submission. There is no application intake deadline. | Stalled transfers can occupy all report capacity for an unbounded interval, returning 503 to healthy callers while compute workers are idle. This regression concerns occupancy even for small requests. R09 concerns bytes spooled. Enforce a bounded intake phase and demonstrate permit release on timeout/disconnect. Deployment-level mitigation was not verified. |
| S4-02 | P2 | scheduler.py:66–76 · billing.py:208–231 · trial_guard.py:72–103 | Cleanup takes a table lock compatible with a row-locking SELECT but incompatible with the later UPDATE. Other writers can already own the row cleanup needs and then need the stronger table lock to flush. | PostgreSQL can abort a transaction for deadlock. Even unrelated key writes can wait during tenant deletion. Ordered sibling IDs solve only the cleanup-to-cleanup ordering. This is a source-based concurrency finding, with no live deadlock observed. Use a common tenant-first guard and bounded transaction retry. [PostgreSQL lock compatibility](https://www.postgresql.org/docs/current/explicit-locking.html#TABLE-LOCK-COMPATIBILITY) |
| S4-03 | P2 | label_health/api.py:91–103 | Reading multipart through Request removed the FastAPI File parameter and its OpenAPI metadata. | All three generated POST operations lack requestBody in the installed app. Swagger and generated SDKs cannot discover the required multipart file, although existing clients using that field still work. Declare the request schema while retaining early admission. |
| S4-04 | P2 | labeling_router.py:641–648,682–689 | No-content and explicitly empty structured content compare as the same pair of empty lists. The comparison omits the intended content type. | For an existing plain-text row, changing to explicitly empty NER or multilabel content with the same category returns 409. Previously the revision could establish that content type. A separate content-creation API exists, but it does not preserve the relabel call's revision semantics. |

**Other regression checks.** The changed cancellation classifier affects the updated/canceled status case, including equal-timestamp priority, and ordinary creation/activation still uses product validation. Bulk's fallback results are unchanged, though the previous deprecation warning was deliberately removed and the adjusted test now asserts silence. The centroid helper fills missing values without replacing existing learned values. Correction writes still follow a tenant-scoped forward chain and copy the child inside the same transaction. A rollback covers both the successor and the predecessor pointer. General SQLite chain races are tracked under R24. Valid small CSVs can receive immediate 503 under contention, which is the new admission policy. JSON, HTML and PDF still share the same validation/analysis path.

## 4. Authentication and billing lifecycle

DLJ authenticates an active key by digest and records its tenant and key scope in the session. Trial expiry and capacity are enforced when work calls reserve_label_capacity. The stored tier, active flag, cancellation time and latest subscription event jointly determine effective access.

| Transition | Implemented behavior | Remaining exposure |
|---|---|---|
| Signup → trial | auth.py:49–66,75–95 generates and stores a digest, returns the key and attempts delivery by email. ApiKey defaults to active/trial. Trial scoring expires after 14 days and is limited to 50/day. | R08. An expired trial can still authenticate for routes without a reservation. |
| Trial → paid | billing.py:59–89 attaches tenant plus authenticated key UUID to checkout. A recognized, authenticated creation event binds customer/subscription and updates tier. Provider event receipt and mutation share a transaction. | R02 customer precedence, R19 subscription replacement. Duplicate event IDs return 409. Unknown products on creations reject the transaction. |
| Paid → amended/renewed | billing.py:180–235 checks subscription identity and occurrence time. Older updates are ignored. A newer active status clears cancellation. Contact-email conflicts are isolated by savepoint. | Unsupported event types return success before receipt persistence. Status-only updates can leave the old paid tier. Cancellation wins a timestamp tie. |
| Paid → cancelled, still active | Cancellation records provider occurrence time. Once effective, trial_guard.py:87–106 applies 50/day, preserves history/counters and bypasses the paid monthly allowance. Prior usage that UTC day counts. | account.py:33–50 still advertises caps based on stored tier (N01). A future cancellation date is not effective yet. A paid cancelled key does not acquire a new 14-day trial. |
| Cancelled → retired/cleaned | scheduler.py:58–108 revisits active keys more than 30 days past cancellation hourly. A same-key renewal or changed subscription visible before the protected recheck vetoes stale cleanup. A fresh active sibling, including one still within its retention period, preserves data. Multiple expired siblings retire together. Inactive siblings do not veto deletion. With no retained active key, labels/content, engines, annotators and domains are removed. Key and event records survive. | A key inserted after the cleanup transaction commits cannot recover history. A later active event against an inactive key does not restore access/data. An active trial sibling without cancelled_at still protects data even after its scoring trial expires. The code tests active-key status, not paid entitlement. |
| Administrative/other auth | auth.py:106–116 issues sibling keys under the admin secret. The Label Studio connector also checks its integration token. Legacy routes use a separate store. Signed webhook ingress fails closed without its configured secret outside explicitly enabled sandbox. | Sandbox signature bypass must remain scoped to sandbox. A sibling key has independent counters. Account-wide quotas would require different ownership. |

**Quota coverage.** _ingest reserves per newly scored item, covering single/batch ingestion, missing sample rows, initially classified tasks, first classification on relabel and new connector scores. Bulk reserves once per eligible row and reports skips at the limit. Single verify, existing connector verification/corrections, already-scored relabel, unclassified task creation, label-content writes, guidelines, reads and checkout do not reserve. An all-skipped bulk or all-existing sample need not charge. UTC day/month rollovers are independent. Thus R18 closes for metered paths, while single and bulk review can still learn under different quota/expiry policies (prior R20). Authentication rejects a retired key on subsequent requests. [Reservation logic](../../trial_guard.py) · [Label routes](../../labeling_router.py)

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S4-05 | P3 | scheduler.py:97–99,109–119 | cleanup_cancelled_tenants now returns the number of keys retired. Its caller logs that number as tenants cleaned. | One expired key with a retained sibling is counted as a tenant cleanup despite preserving all data. Two retired keys on one tenant are reported as two tenants. Track keys retired and datasets deleted separately. |

## 5. Test coverage after three fix rounds

The request names five fix modules. Running all five together produced 64 collected cases per database, with zero failures and one expected migration skip each. Each of the eight fixes has dedicated coverage for some behavior, but several tests leave the important cross-component or concurrency condition unstated.

| Fix and tests in test_sweep3_fixes.py | Exercised | Remaining test gate |
|---|---|---|
| R14 · 38,48 | Two old siblings retire together and delete rows. A retained active sibling preserves data while the old key retires. test_resweep_fixes.py:84 injects renewal between scan and transaction. | Actual simultaneous sibling insertion, renewal/cleanup in both commit orders, a still-in-grace sibling, lock contention/retry and deletion of every child table. The injected renewal completes before locking. |
| R44 · 62 (two cases) | Both cancellation representations with no items. Earlier resweep covers unknown/retired products on the explicit cancel event. | updated/canceled with nonempty unknown items and equal-time competing status, including a committed duplicate receipt. |
| R13 · 69,76 | Legacy approve/reject persist the historical booleans. test_resweep_fixes.py:122–151 separately checks explicit false/true. | Browser-shaped request through the real DTO into label and learning state, with recommendation agreement differing from observed truth. e2e/fix_round3.spec.ts:25–37 asserts the incompatible field against a mock. |
| R45 · 92,103 | Identical category/spans returns 409 and preserves revision. Genuine same-category span change succeeds. | Unordered tag equivalence, no-content versus empty structured type, and verified-count/accuracy throughout a correction chain. |
| R18 · 115 | Paid key with an effective timestamp at the daily cap gets a daily 429. SQLite round-trip covers the naive timestamp path. | Future cancellation, account DTO parity and concurrent boundary reservations. Calling the same test on PostgreSQL covers an aware timestamp. |
| R01 · 126 (two cases) | Connector loads a deliberately old snapshot, learns, persists a missing category/action centroid, including when the category itself is already present. | Verify existing trained values, all actions, reviewer scope and learned outcome on the correction branch. Existing connector suite covers ordinary predict/verify/update. |
| R03 · 182,188 | NER and multilabel correction fetch the successor via the stored forward pointer and read back its independent content row. | Image URL/typed-empty content, predecessor unchanged, complete provenance on successor and atomic rollback on a copy failure. |
| R09 · 193,209 | Busy admission rejects without reading and returns 503 before malformed multipart parsing. Oversize selected file is rejected through helper and HTTP, and the helper releases the slot. | Streaming total-byte limit, elapsed intake deadline/cleanup, multipart schema, and exact boundary acceptance across formats. test_label_health.py:116–138 covers normal analysis/PDF and invalid input. |

**Module overlap.** Billing (10) checks webhook identity/order and contact behavior. Migration (6) uses historical table fixtures and private PostgreSQL schemas or disposable SQLite files. Validation (14) checks API boundary/error behavior. Resweep (19) revisits the fixes at API/storage boundaries. Sweep3 (15) extends them. Overlap in cancellation, trial cap, revisions and legacy bulk fallback is intentional. The existing checkout test's customer precedence and the no-warning compatibility test can pass while R02 and R13 remain. None of the five modules failed due to ordering in the executed runs.

**Execution details.** PostgreSQL used private test schemas on localhost:5433. SQLite was explicitly selected for both DLJ_DATABASE_URL and DATABASE_URL so fixtures used temporary SQLite files. The ambient shell default selected PostgreSQL on an initial run. The SQLite run skipped only the PostgreSQL timestamp test at test_migration_fixes.py:106, and PostgreSQL skipped only the SQLite timestamp test at line 135. Both ran all applicable migration checks. Collection and the full default run excluded the three docker_live modules and test_ops_e2e.py. The browser count of 112 is the prior session baseline, outside this backend execution.

## 6. Cumulative P1 scorecard and decision

The sequence 26 → 30 → 25 mixes backend and frontend report snapshots and includes shared issues such as bulk truth. For convergence this report follows the round 2 backend ledger's published crosswalk and counts distinct failure identities once. Its open-P1 series is **25 → 23 → 20 → 17** (round 1 published 26 IDs, with F/P1.2 and F/P1.6 subsequently consolidated as R12).

| Review checkpoint and fix round credited | New distinct P1s | Fully closed at this checkpoint | Reclassified below P1 | Open P1s |
|---|---:|---|---|---:|
| Sweep 1, before fixes | 25 | — | — | 25 |
| Sweep 2, fixes round 1 | 11 | 12: B/P1.1, .3, .4, .6, .10, .15, .16, .17 and F/P1.1, .3, .4, .5 | 1: B/P1.18 → R10 (intentional anonymous service, P3 documentation) | 23 |
| Sweep 3, fixes round 2 | 3: N02, N03, N05 | 6: R11, R12, R18, R31, R35, R44 | — | 20 |
| Sweep 4, fixes round 3 | 1: S4-01 | 3: R01, R14, N05 | 1: R03 (structured evidence preserved, revision provenance still P2) | 17 |
| **Cumulative** | **40** | **21 fully closed** | **2** | **17** |

The eleven new round 2 identities are R14, R18, R19, R23, R24, R29, R30, R31, R35, R44 and R45. Initial B/P1.2, .5, .7, .8, .9, .11, .12, .13, .14 and .19 map to R01–R09 and R11 respectively. Initial F/P1.7 maps to R13. The five independent round 3 frontend findings belong to a separate ledger. Its shared bulk issue appears here only as R13. For a narrower backend-only historical reporting view, dropping the four closed FE-only guards and closed cross-key CSV identity gives 16 fully closed of 35, two reclassified and the same 17 open.

**All 17 outstanding P1s**

| Disposition | IDs | Count |
|---|---|---:|
| Structural launch gates already in merged 02–05 | R02, R04, R05, R08, R19, R23, R24, R29 | 8 |
| Other inherited launch gates | R09 (bytes before spooling), R13 (bulk truth), R45 (negative evidence), N02 (unredacted outer SQL errors, db/connection.py:37–62), N03 (untyped connector action dispatch, label_studio.py:253–256) | 5 |
| Add to the report-admission gate in merged 04 | S4-01 (unbounded permit occupancy during request intake) | 1 |
| Accepted legacy risk, still P1 and deferred to v1.1 | R06, R07, R30 | 3 |

**Decision: no to unrestricted feature implementation or launch. Yes to starting merged prompt 00 now.** No P1 must be fixed before building the disposable integration harness. Use that harness to close R02/R19/R23 before extending paid entitlement or migrating historical tenants. Close R08 before relying on registration for project membership. Close R13/R45 before pre-label automation consumes review outcomes, and verify R03 provenance before promising revision-complete exports. Gate supported concurrent writes on R04/R24/R29, public/connector exposure on R05/R09/N02/N03/S4-01, and retain the R14/N05 interleaving checks. With these fixes sequenced inside the merged plan, the team can begin engineering without treating a passing suite as launch approval.
