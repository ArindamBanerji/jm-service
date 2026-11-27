# DLJ R3 unified review · Wave 3

25 November 2026. Scope is a fresh PostgreSQL installation, both Wave 3 adapters and the Wave 2 regression suite. The review uses the B/C contract in the architecture plan and the four contracts established in R2. Historical repair and SQLite locking retain their existing risk classifications.

## Review decision

**Gate verdict: PASS for fresh PostgreSQL. Prompts D and E may start in parallel.** The four R2 contracts hold under their documented definitions, all five B findings and eight C findings are closed, the C schema matches §4, and all five cross-path checks are verified. All 27 scenarios pass on PostgreSQL, with zero weak or skipped scenario IDs. The review added no historical deferrals. PostgreSQL passed 167 tests in each run, SQLite passed 164 with three advisory skips, and Playwright passed 124 twice.

## Four R2 contracts

| Contract | Verdict | Callers and evidence |
|---|---|---|
| One eligibility rule | VERIFIED | `db/entitlement.py:49–88` computes eligibility and resolves the payer. In `auth.py::require_project_tenant`, owner writes and collaborator writes choose the appropriate purpose, re-read the project and retain the authenticated actor separately. This covers ingest, batch, sample, tasks, verify/bulk, relabel, content, guidelines and their project aliases. Connector configure, setup when it materializes a domain, predict and webhook use the same resolver. Checkout, invitations and settings retain A’s checks. The project chooser lists visible projects, which may be read-only. The server checks eligibility again on each mutation. The role-by-payer matrix now exercises both bulk import aliases as well as classification and verification. |
| Lock order and revalidation | VERIFIED | A write takes the tenant guard and locks affected keys in UUID order before mutable project rows. The member path reloads active membership, role and project status. Settings checks the caller’s version under this guard. Domain insertion with conflict handling occurs within the guarded transaction. First-engine creation rechecks under the domain lock. Connector corrective learning locks the bound label chain before updating engine state. Bulk prelocks existing labels in row-ID order and retains these locks through all verified outcomes and the single commit. Calls that revisit the same payer/domain within the transaction already hold its lock. Retention reads candidates separately and rechecks the full sibling set under the tenant guard. S10–12 and S22–25 inspect independently committed outcomes. |
| Validation before access | VERIFIED under the R2 definition | The body preflight and `WebhookEnvelope` reject malformed dispatch, identifiers, result shape and malformed source timestamps. Resolving a configured truth field requires reading that tenant’s connector config. Checking historical task assignment requires reading that tenant’s binding. Both checks precede payer resolution, domain creation, receipt replay, quota use and learning in `label_studio.py::webhook`. Replay cannot make a mismatched task valid. **These two state-dependent checks do perform database reads**. A literal zero-query assignment check is impossible with server-owned bindings. S5 rejects malformed envelopes before config access and disallowed truths before payer lookup, then checks durable state. The browser checks response shapes before route rendering and has a recoverable route boundary. |
| Scenario oracles | VERIFIED | All 27 retained scenario IDs have executable bodies. The table below identifies the observation supporting each result. Timed gates coordinate competing work; fresh sessions inspect database effects. Browser cases use the real service, with controlled response delays and failures at the specific boundary under test. |

## Prompt B closure

| Finding | Verdict | Evidence |
|---|---|---|
| R3-01 · stale signup | CLOSED | Account generation changes on same-tab and cross-tab rotation. A late confirmation cannot write a bearer or relabel the old receipt as owned by the new account. S28 checks the active credential and receipt. |
| R3-02 · upload residue | CLOSED | Upload aborts active readers/requests, clears file, analysis, draft and progress, and ignores previous completions. A committed prefix remains attributable to its original project. S29 reloads the browser and checks both accounts’ rows. |
| R3-03 · lost review edits | CLOSED | Review and category mutations share a lock. Tag/span edits are gated while a category change is pending. A canonical successor can preserve the intended draft, a 409 reloads server state with notice, and the data-router blocker handles link and history navigation. S31 holds a real save open and checks the draft after cancellation of navigation and after completion. |
| R3-08 · malformed success or missing chunk | CLOSED | The API decoder distinguishes list/detail routes by path and method and checks nested project, label and dashboard data. Scoped error handling leaves navigation available. S32 recovers from both an incompatible queue body and a failed Dashboard chunk. |
| F7-01 · private history | CLOSED | Queue links carry project/label identity. Review reads current detail. S30 inspects history state and delays old-project search, detail and bulk responses while switching between projects with duplicated public names. |

## Prompt C closure

| Finding | Verdict | Evidence |
|---|---|---|
| R01 · category sync | CLOSED | S20 creates an old reviewer engine, introduces category B over HTTP and adjudicates B over the connector. Persisted categories, two conservation events and verification actors agree. |
| R03 · revision provenance/content | CLOSED | HTTP and connector retain text, typed content, source IDs, predecessor and revision metadata. Each verified revision records the verifying key. S21 reads first-adjudication spans and then both adapters’ successors from independent sessions. |
| R04 · first writers | CLOSED | Domain conflict handling, scoped uniqueness and the domain lock around engine creation converge. S22 checks the two create responses, the durable domain, first scores and single engine. |
| R29 · lost connector configuration | CLOSED | The database owns configuration by tenant and external project. Versioned updates reject stale preconditions; a binding cannot silently switch domains. S25 uses independent spawned processes and a subsequent reader after restart. |
| R45 · lost evidence | CLOSED | The successor starts unadjudicated. The recursive evidence predicate retains the last verified predecessor until replacement evidence exists. S26 checks category reversion and the accuracy projections. |
| R13/R3-07 · manufactured bulk truth | CLOSED | Strict booleans enter single-item learning independently of the action. Unknown truth is skipped; mixed correct/incorrect outcomes update opposite learner trackers. The browser requires a truth choice for its homogeneous selection. S27 checks both the database and the UI wire payload. |
| B6-02 · stale redelivery | CLOSED | A project/actor/operation receipt binds digest and result. A source watermark also protects pending events, including across a changed payload. Older deliveries cannot undo a later adjudication; a missing timestamp cannot supersede a timestamped event. |
| B7-01 · source reassignment | CLOSED | Under the tenant guard, the durable annotation/task binding is checked before entitlement and replay. Conflicting bindings return 409. Separate project/annotation pairs containing separator characters retain distinct identities. |

## Schema and cross-path checks

**§4 C schema MATCHES.** `db/models.py:61` defines the partial unique index on `(domain_id, prior_revision_id)` for non-null predecessors on both dialects. The migration groups non-null predecessors and refuses duplicates before issuing the index DDL (`db/migrate.py:350–359`). The two nullable UUID actor columns reference `api_keys.id`. `connector_config` has a tenant/external-project composite primary key, required JSON configuration and a BIGINT version defaulting to one. `project_request` has a project/actor/operation/request composite key, project and actor FKs, CHAR(64) digest, required JSON result and timezone-aware expiration (`db/models.py:114–131`). The PostgreSQL upgrade regression starts with a populated project and removes the C schema additions, runs migration twice and inspects the columns, foreign keys, index and surviving data. Schema-per-test bootstrap also exercises fresh installs.

| B+C path | Verdict | Observable result |
|---|---|---|
| Project chooser → label write | VERIFIED | The real chooser selects a UUID, the queue targets that UUID’s labels endpoint, and an independent session sees both outcomes and verification actors. |
| Bulk UI → shared learner | VERIFIED | Browser checks submitted action/outcome, counts and removal of processed rows. The companion API case supplies mixed and unknown outcomes and checks pending evidence and learner counters. |
| Project settings → connector configuration | VERIFIED | These are independently versioned resources. Browser settings PATCH advances the project version. The connector rejects a stale If-Match, accepts its current ETag, and refuses rebinding to another domain. |
| Credential rotation → delayed connector callback | VERIFIED | S30 switches owner/project with a duplicate alias, completes old requests and checks tenant-scoped storage. The connector authenticates its own actor independently of browser state. |
| S27 joint build | VERIFIED | Both the legacy-domain and project-scoped real queue cases exercise the mounted C backend, including a stale item. The homogeneous UI and mixed-item API are tested separately. |

## Scenario evidence

Each entry is active on PostgreSQL. The files under `tests/harness/scenarios` group S1–6, S7–14, S20–27 and S28–32 respectively. The browser contracts and `test_prompt_c_joint.py` add observations to S27 and S31. The three advisory SQLite skips are PostgreSQL locking checks.

| ID | Verdict | Acceptance observation |
|---|---|---|
| S1 | PASS | A mismatched mailbox cannot obtain a key. A consumed proof issues an active credential. |
| S2 | PASS | Concurrent proof consumers produce at most one bearer; delivery failure and commit ordering are checked. |
| S3 | PASS | Saturated report and signed billing intake refuse further readers; deadlines release capacity. |
| S4 | PASS | ASGI and scheduler failures expose only trusted diagnostic metadata. |
| S5 | PASS | Invalid connector shape and configured truth fail at the expected boundary with no label, engine, domain or charge. |
| S6 | PASS | Boundary-width identifiers succeed, overlong IDs fail with no writes. Modern schema names also reject the reserved centroid separator. |
| S7 | PASS | Two tenant keys plus an existing provider customer cannot misdirect the purchase. |
| S8 | PASS | Replacement IDs, past due, pause and resume affect only the current subscription’s effective capacity. |
| S9 | PASS | Duplicate, unknown and delayed deliveries preserve the watermark, grant and notification counts. |
| S10 | PASS | Both cleanup/renewal commit orders use independent connections; the late path preserves data or records reconciliation as appropriate. |
| S11 | PASS | Issuance and rotation contend with cleanup. The committed survivor or tombstone determines the result. |
| S12 | PASS | Old cancelled siblings trigger a single cleanup. An entitled sibling preserves its tenant. C receipts and configurations follow the same disposition. |
| S13 | PASS | The existing provider fixture is migrated twice and checked for preserved evidence or explicit quarantine. The earlier historical risk ledger still governs broader repairs. |
| S14 | PASS | Clock-controlled UTC day/month boundaries give the same cap in the account summary and reservation path. |
| S20 | PASS | Fresh reads find B in the old reviewer engine and exactly two verified learning events. |
| S21 | PASS | Changed spans survive the first adjudication, ordered connector revision and subsequent HTTP correction. Replays and wrong-task requests leave the lineage intact. |
| S22 | PASS | Competing creates yield one domain. Simultaneous first scoring yields one engine and as many committed scores as successful responses. |
| S23 | PASS | At 49 used, two contenders produce one success and one 429. Both counters and scored-row count end at 50. |
| S24 | PASS | Two relabels and verification race on one predecessor. One successor exists. Adjudicating it leaves exactly the number of learner events corresponding to successful verifications. |
| S25 | PASS | Two independently initialized service processes persist different configurations. A newly started reader retrieves both from the database. |
| S26 | PASS | An incorrect predecessor remains evidence through A→B→A until the current revision is verified. |
| S27 | PASS | Correct, incorrect and unknown truth are distinguished in stored outcomes, skipped items and learner updates. Joint browser cases check the actual queue submission. |
| S28 | PASS | A delayed signup across same-tab and cross-tab rotation leaves the replacement credential in control. |
| S29 | PASS | Identity rotates between real chunks. The committed prefix belongs only to the first owner; reload cannot restore the file for the second. |
| S30 | PASS | Identical aliases do not mix projects. Delayed detail/search/bulk and an old-owner callback cannot affect the replacement view or rows. |
| S31 | PASS | Unsaved text survives a real category-save boundary. Verify is disabled, and cancelling Back or sidebar navigation preserves the draft. |
| S32 | PASS | Malformed success and missing lazy chunk each give a scoped error; navigation and retry work. |

## Launch findings fixed during review

| Severity | Finding and change | Regression evidence |
|---|---|---|
| P1 | Project receipts could block retention on the project FK. Cleanup now deletes tenant-owned C records before parent rows in the guarded transaction. | S12 |
| P1 | A superseded signup could expose its bearer through deferred storage after rotation. Deferred ownership now follows the signup’s captured account generation. | S28 |
| P1 | History Back could bypass draft protection and a concurrent category change could discard editor input. Browser navigation and all editors now share the guard. | S31 and the real 409 browser contract |
| P1 | First connector adjudication could drop edited spans, pending deliveries could lose their source watermark, and composite external IDs could collide. They now survive the full write/replay path. | S21 and connector contract |
| P1 | Member imports were permitted for the annotator role. Both import adapters now check the registered operation, including UUID routes; legacy individual classification remains permitted. | Twelve role/payer combinations |
| P2 | UUID sample replay could fail alias validation. Connector config lacked an external stale-version check and could be rebound. | Sample replay and browser project configuration contracts |
| P2 | Stale operations could affect upload controls, queue selection or settings feedback. Route changes now abort requests owned by the departed route. The chooser retains its current project list during a same-account refresh, so a newly mounted queue can resolve its project immediately. | S29–31 and project-scoped joint S27 |
| P2 | Shape validation omitted nested fields, reserved names could enter a modern project schema, and bulk input coerced string truth. | API decoder, S6, S27 and S32 |
| P2 | Earlier scenario evidence missed a real browser restart, a three-way revision race, independent process restart and a populated A→C upgrade. Browser fixture credential initialization could also mask rotation on reload. | Strengthened harness, migration and browser tests |
| P3 | The harness README still described thirteen skipped shells and four expected failures. It now identifies the active browser and connector regressions. | Harness collection |

## Verification

| Command | Phase 1, before fixes | Phase 8, final tree |
|---|---|---|
| PostgreSQL, `python -m pytest tests/ -q --timeout=120` | 164 passed | 167 passed in 286.34 s |
| PostgreSQL, standalone `tests/harness/` | 164 passed | 167 passed in 298.61 s |
| SQLite, standalone with `--harness-sqlite` | 161 passed, 3 skipped | 164 passed, 3 PostgreSQL-locking skips in 260.73 s |
| Playwright, two full consecutive runs | 124 passed twice | 124 passed in 45.0 s and 124 passed in 44.4 s, two workers, zero retries |
| Frontend TypeScript and Vite build | Passed | Passed |
| Changed Python and browser test types | — | mypy clean on 14 changed Python files; E2E TypeScript clean |

During intermediate verification the browser exposed an overbroad route cancellation and a race between two test dialog handlers. The final code cancels requests owned by the previous route. The test records both browser confirmation decisions synchronously, and the render checks allow up to 20 seconds for the real service. The recovery assertions still require the requested label or dashboard to render.

R1 durability and contract tests and R2 entitlement, billing, membership and concurrency tests ran within the PostgreSQL harness. The full and standalone Python counts overlap. The separate Node Playwright suite uses the existing local frontend and mocked API flows. The pre-existing server on port 8080 reported a database authentication failure during preflight; its health probe is not evidence of working live writes. The schema-isolated Chromium tests in pytest provided the real authenticated B+C database checks. The review covers the local build and fresh PostgreSQL deployment model.
