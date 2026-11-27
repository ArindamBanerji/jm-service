# R4 unified review — project export, predictions and webhook delivery

26 November 2026 · main · deployment target: fresh PostgreSQL on Railway

## Decision

**PASS for the fresh PostgreSQL gate.** The review found and fixed **10 P1 and 9 P2** issues, with **0 P3** findings. No launch-scope P1 or P2 remains open in the reviewed D/E paths. Findings that affected more than one adapter are counted once.

| Check | Final result |
|---|---|
| PostgreSQL, requested name filter | 207 passed, 1 deselected, 0 failed |
| PostgreSQL, complete `tests/` discovery | 208 passed, 0 skipped, 0 failed |
| Additional root CI regression selection on PostgreSQL | 427 passed, 1 SQLite-specific skip, 33 SQLite-only cases deselected, 0 failed |
| SQLite advisory harness | 189 passed, 3 PostgreSQL-only skips |
| Focused PostgreSQL export, prediction and delivery contracts | 23 passed |
| Static checks and frontend | mypy clean on all 24 changed Python files. TypeScript and Vite build passed. |
| Standalone Playwright | Prior baseline of 124 passed. Backend-only review, suite not rerun. |

## Findings and fixes

Locations refer to the reviewed working tree. Contract numbers are 1 for eligibility, 2 for locking and transaction boundaries, 3 for validation before access, and 4 for observable scenario behavior.

| ID | Severity | Contract and location | Failure and fix |
|---|---|---|---|
| R4-01 | P1 | 2/4 · `db/repository.py:50` | Dispatch-time fan-out reconstructed subscriptions after the producer committed. A rotation could lose an obligation or deliver an older event to a changed destination. The producer now records one delivery per subscribed active endpoint, with its destination version, in the business transaction. Test sends target one endpoint. Workers claim existing deliveries. |
| R4-02 | P1 | 3 · `webhook_security.py:59`, `scheduler.py:150` | Validating resolved addresses and then connecting by hostname allowed the connection to resolve independently. Delivery connects to a validated public address, retains the original authority and TLS server name, disables environment proxies and redirects, and signs the stored UTF-8 body. DNS and response headers share a ten-second wall-clock budget. |
| R4-03 | P1 | 2 · `scheduler.py:184` | An abandoned durable attempt could leave the delivery counter behind, permitting a fifth send. Finalization also needed the same endpoint-first lock order as rotation. The worker checks the durable attempt ledger and current fence, renews a live lease before sending, and terminates exhausted deliveries. A stale worker cannot finalize a replacement lease. |
| R4-04 | P1 | 1/2 · `projects_router.py:220`, `db/repository.py:40` | Closing a project left pending or leased deliveries eligible. The lifecycle transaction fences affected destinations under ordered locks and cancels their open work. Archive also disables endpoints. Completion cancels old work while preserving subscriptions for a later reopen. An HTTP request already sent cannot be recalled. |
| R4-05 | P1 | 2/4 · `labeling_router.py:1183`, `labeling_router.py:1315` | Paging selected rows still allowed the exporter to materialize project-wide ancestry and the encoded result in memory. JSONL and CSV now traverse UUID keysets in pages of 500, fetch reachable ancestors, and spool before sending. Caps fail before success headers. Response cleanup closes the spool and releases the matching token on completion, failure and disconnect. |
| R4-06 | P1 | 1/2 · `labeling_router.py:1183` | Role checks and the export data read were separated by the slot-claim commit. A revoked reviewer could begin a data snapshot after revocation. The read-only PostgreSQL REPEATABLE READ transaction now checks the actual credential and current membership within that same snapshot. |
| R4-07 | P1 | 2/4 · `db/repository.py:29`, `labeling_router.py:528`, `label_studio.py:590` | Generic verify, edit and connector paths could leave a prediction pointing at a predecessor or leave a finished prediction in the pending queue. HTTP and connector verification attach human review to the current revision with an unknown model assessment. Edits advance the pointer/version, queue paging excludes completed predictions, and generic review never certifies model spans. |
| R4-08 | P1 | 2/4 · `labeling_router.py:1594` | Reopen needed to fence both revision and decision version and preserve the imported score. It now compares both under lock and creates a pending successor without scoring, learning or quota reservation. The original label, machine timestamp, stored recommendation and verified predecessor survive. |
| R4-09 | P1 | 1/4 · `labeling_router.py:1444` | A paid tier string could survive cancellation, and category eligibility alone could overlook a paused scorer. Automation now requires an active eligible payer, project opt-in, the model floor, an approve recommendation at the scored threshold, autonomous tier, passing conservation and an eligible named annotator. Machine approval emits an event and leaves human evidence empty. |
| R4-10 | P1 | 3/4 · `labeling_router.py:1542` | Human assessment of model output could train an arbitrary alternative action, including when the model recommendation already was rejection. Review accepts a project action and separate human outcome. The standard approve/reject defaults follow the human outcome. Unknown model assessments do not train through this endpoint. |
| R4-11 | P2 | 2 · `scheduler.py:58`, `db/models.py:242` | Cancelled deliveries lacked a terminal time for 30-day pruning. Cancellation now records it. Cleanup prunes bounded batches, retains sibling delivery history, and uses endpoint-first locking when tenant retention removes delivery children. |
| R4-12 | P2 | 4 · `db/models.py:253`, `scheduler.py:150`, `db/migrate.py:23` | After rotation, an attempt could no longer be attributed to its signing-key version. Each new attempt records the version used and the sender supplies it as a header. Migration adds nullable audit columns repeatably. |
| R4-13 | P2 | 3 · `labeling_router.py:1080`, `labeling_router.py:1444` | Malformed structured predictions or schema mismatches could reach scoring before rejection. DTO validation checks content type, incompatible fields, span text, bounds and overlap. The project schema check runs for the entire batch before the first score. |
| R4-14 | P2 | 3/4 · `labeling_router.py:1183`, `labeling_router.py:1286` | Export mixed unscored items into pending, applied ambiguous date semantics, and treated the browser fallback cap as a general download limit. Queries now distinguish unclassified, pending, overridden and verified states, use a half-open UTC scoring interval, and apply 32 MiB only for the explicit browser fallback. DocBin selects eligible NER records and checks human adjudication and strict tokenizer alignment. |
| R4-15 | P2 | 1 · `webhook_router.py:76` | Webhook history reads took a write-entitlement path, and PATCH could start destination resolution before establishing administrative access. Reads require visible owner/admin membership. A URL change performs role authorization before DNS, then revalidates payer, project and membership under lock before mutation. |
| R4-16 | P2 | 4 · `labeling_router.py:1636` | Project prediction statistics loaded full prediction records, including model content, to compute small counts. The database now groups scoped rows by state, source and assessment. Accuracy excludes unknowns and is null for an empty denominator. |
| R4-17 | P2 | 4 · `.github/workflows/harness.yml:51` | The required root regression job still collected hard-coded modern SQLite fixtures. The PostgreSQL job now deselects explicitly marked SQLite-only tests; the advisory job runs them. Dialect-capable regressions stay in the PostgreSQL job. Health probes exercise its selected DB. Both jobs exclude the standalone live Paddle script from test discovery. |
| R4-18 | P2 | 3/4 · `scheduler.py:49` | Permanent 4xx rejections and redirects consumed the same retry budget as transient failures. The worker now ends those deliveries on the first response and retries 408, 429, server errors, DNS and transport failures. A regression reads back the terminal state and attempt number. |
| R4-19 | P2 | 4 · `test_bulk_review.py:32`, `test_resweep_fixes.py:144`, `test_sweep3_fixes.py:69`, `test_round6_fixes.py:74` | The older regression job still expected implicit human truth, connector file writes and success for a different payload reusing the same receipt. Updated the tests to exercise explicit truth, independent database readback, conflict on key reuse, an unseen older event and exact replay. |

## Producer, dispatcher and retention

An independent-session PostgreSQL check held a producer transaction open after flushing its event and delivery. A real dispatcher claim returned immediately with zero rows. Rolling the producer back left zero events and zero deliveries. Repeating the transition and committing made exactly one matching event claimable; another worker obtained zero duplicate claims.

HTTP verify (including bulk), dedicated prediction review, connector verification and automatic approval use the same event encoder. The six envelope fields are `event_id`, `event_type`, `project_id`, `occurred_at`, `schema_version` and `data`. A project/type/transition uniqueness constraint protects the event, and endpoint/event uniqueness protects each delivery. PostgreSQL makes both visible after the successful business commit. The worker sends the stored bytes and signs `timestamp + "." + body` with HMAC-SHA256. The receiver can deduplicate on event ID if the sender loses the acknowledgement.

Claims use a short PostgreSQL advisory transaction lock for the global four-send budget, endpoint row locks with SKIP LOCKED, and token-checked updates. Network I/O occurs outside database transactions. Non-2xx responses, redirect responses, transport failures, timeouts and rejected destinations produce bounded attempt metadata. Retries use 10, 60 and 300 seconds. Fernet ciphertext is stored on endpoints. Create and rotate are the only secret-disclosure responses. The worker logs IDs, attempt number, status and error class.

Tenant cleanup revalidates the payer under the tenant lock. It removes attempts and deliveries before events and endpoints, export slots before domains, and predictions before labels. Label content cascades from label deletion. The repeatable migration uses the producer's shared event table and retains existing delivery data. Docker runs migrations before starting the HTTP server.

## Regression evidence and database gate

The previous session recorded 198 passing tests. The first local invocations reported 196 passed, one failed and one deselected with the name filter, and 197 passed and one failed without it. Those runs overlapped editing: S25's Windows child process imported an intermediate syntax error. They do not establish a clean pre-change baseline. The final tree adds four R4 regression cases and includes six experiment tests added independently during this review.

Intermediate overlapping browser-backed runs also hit startup/render timeouts. Complete reruns passed without changing the browser assertions or extending their timeouts. The final PostgreSQL runs include S1–S14 and S20–S32; only the explicitly name-filtered run omits S13. Counts in the table overlap and should not be added.

The combined HTTP/dispatcher regression verifies two real labels, compares the delivered canonical body against a fresh session, leases the second delivery, archives the project and checks that the sender was invoked once. A separate crash test starts from a durable fourth attempt. The export regression writes the 501st row from another session while the first page is being exported and checks that the second page retains its original value. It also checks the document and UTF-8 byte caps. Prediction regressions cover replay charge, machine-only evidence, model provenance through a category edit, stale reopen, queue visibility and human review.

PostgreSQL is the sole database gate. The harness default requires PostgreSQL and creates a schema per test. SQLite requires `--harness-sqlite`; its CI job already has `continue-on-error`. The three SQLite skips cover concurrent invitation acceptance, revocation while an acceptance waits, and archive during a grant. These cases execute on PostgreSQL. The `-k "not sqlite"` spelling also deselects S13 because its name mentions the advisory lane. Full PostgreSQL discovery covers S13. The SQLite file used internally by the isolated legacy API is independent of the modern database lane.

The eight historical deferrals remain R14, F2, F5, N10, R23, N2, N9 and N11. The separate four accepted risks remain R06, R07, R24 and R30. This review uses fresh PostgreSQL and does not change their disposition.

## Verification boundary

A disposable PostgreSQL 17.11 schema held exactly 5,000 synthetic documents containing 16,777,216 UTF-8 text bytes. The authenticated JSONL request returned HTTP 200, 5,000 records and 18,980,002 encoded bytes in 1.23 seconds on this machine. Increasing text by one byte returned 413. A separate request with 5,001 documents below the byte ceiling also returned 413. A fresh session found zero outstanding leases afterward.

The tests exercise local PostgreSQL and a controlled outbound transport. The frontend build passed. No frontend code changed. The last recorded standalone Playwright result is 124 passed. The Python discovery runs include the real Chromium harness. This environment exercised the optional DocBin dependency's 501 response because spaCy was absent. Railway Hobby memory and throughput at the maximum export size require a staging measurement. No deployment or external webhook delivery was performed.

## Code and schema cross-check

The checkout is on `main` at `569813f`. D and E are present in a mixed working tree. Review scope was established from the two session entries, file status, route registration and call sites. The independent experiment changes are excluded from the findings.

| Surface | Final checks |
|---|---|
| `auth.py`, `projects_router.py`, `db/entitlement.py` | Project writes resolve actor and payer separately under the tenant guard. Review/import/export use reviewer-or-higher access. Endpoint configuration requires admin-or-owner access. Archive uses the same guard as event production. |
| `labeling_router.py` | Single and bulk verification call the learner with human truth. Bulk reserves only for eligible decisions. Import persists the score, original content, decision and receipt atomically. Dedicated review and reopen check revision and decision version. Export predicates and UUID keysets use bound parameters. |
| `db/repository.py`, `label_studio.py` | Connector receipt matching precedes learning. HTTP and connector paths preserve content across revisions, update current prediction provenance and record each first human verification in the same transaction. The repository never commits the producer's transaction. |
| `db/models.py`, `db/migrate.py` | The two-slot primary key, scoped prediction index, revision foreign keys, unique event transition, unique endpoint/event and attempt composite primary key provide the database constraints. The repeatable E expansion also handles the new terminal timestamp and signing-version columns. |
| `webhook_router.py`, `webhook_security.py`, `scheduler.py` | Admin CRUD, rotation and test sends share project authorization. Only the target endpoint gets a test delivery. Claim, send, completion and retention use separate transaction scopes. Destination changes fence older claims. Logs omit request/response bodies and signing material. |
| `jm_service.py`, `requirements.txt`, `docker-entrypoint.sh` | Webhook and project routers precede the static mount. Lifespan supervises the scheduler. The container installs cryptography and runs the migration before serving. |
| Harness contracts, fixtures and regression jobs | DDL retest, retention, producer rollback boundaries, D/E exact-body delivery, quota, role, replay, stale revisions and S21/S24/S26/S27 were checked against the merged contract. Both the harness dialect selection and the older root CI collection were inspected. |
