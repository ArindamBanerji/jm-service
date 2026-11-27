# DLJ R2 unified sweep — fresh-database launch

**PASS — 25 November 2026. Prompt B and Prompt C may start in parallel.** All six launch-classified P1s are closed, all four R2 contracts are verified, and all fourteen Prompt A scenarios pass on PostgreSQL. This verdict applies to a fresh PostgreSQL installation. Importing pre-A records triggers the historical review in the session ledger.

## Phase 1 classification (recorded before implementation)

| ID | Scope | Boundary |
|---|---|---|
| N03 | LAUNCH | Connector shape, factor values and selected actions on new annotations. |
| R05 | LAUNCH | Public item-path and body-selected project boundaries. |
| F6 | LAUNCH | Current quota summary and membership eligibility. |
| F16 | LAUNCH | Reciprocal actor and payer locks. |
| F17 | LAUNCH | UUID-shaped names from current alias writers and pinned lookup. |
| R19 | LAUNCH (live edge) | Equal-time deliveries can occur on the first subscription. Existing historical event reconciliation is deferred. |
| R14, F2, F5, N10 | DEFERRED (historical edge) | Mixed legacy tombstones and historical normalization. Fresh installations need a durable distinction so redeployment cannot invoke this repair on modern rows. |
| R23, N2, N9 | DEFERRED | Historical provider ownership and manifests. |
| N11 | DEFERRED (historical edge) | Historical replay is deferred. Prospective equal-time ordering is covered by R19. |
| N1, F1 | Previously CLOSED | Only retrospective repair of old receipts or ownership is deferred. |
| N12 (P2) | LAUNCH | PATCH must reject unsupported schema edits before advancing settings_version. |

The incoming 11 partial P1s and three new P1s comprise six launch rows and eight historical rows. Historical subcases of previously closed rows do not add new launch findings.

## Contract audit

| §2 contract | Implementation and evidence |
|---|---|
| Effective entitlement | Checkout and fulfilment apply the purchase decision to the designated payer. Account and reservation use the same effective lifecycle state. A cancelled owner can use the daily allowance. Collaborator writes, including invitation acceptance, use member-write eligibility. Scheduler and issuance use the sibling protection decision under the tenant guard. S7–S12, S14 and the cancelled-owner regression exercise the differences. |
| Locks and authorization | Label and project mutations take the tenant guard, then lock payer and actor in UUID order and refresh the authenticated key. Invitation acceptance includes the issuer, checks the refreshed invite and conditionally claims it. Recipient identity comes from the verified signup mailbox. A billing contact can change independently. The mailbox test assigns the invited address as another credential’s billing contact and verifies that only the intended member can accept. Label writes pin the collaborator project found during discovery and reload role and project after locking. The reciprocal-grant test brings administrators to different tenant guards concurrently and verifies both resulting grants. Signed billing rechecks duplicate processing under the guard before testing intent consumption. |
| Validation before access | Authenticated routes preflight their declared body model and public item/domain widths. Project creation, account naming and connector configuration share UUID alias rejection. Connector dispatch checks envelope, composite ID and every supplied choice. Tenant-specific schema, truth and factor validation run after identifying the tenant and before payer or domain access. Signed billing validates creation metadata and status before the processing-session lookup. Settings refuse unsupported action changes with 422 and retain the version. S5 and S6 include independent readback. |
| §5 scenario oracles | Four previously weak tests now distinguish the required failure from an unrelated error. PostgreSQL exercises actual overlapping transactions. SQLite exercises the compatible outcomes. The individual observations are below. |

### Billing and migration boundary

Two simultaneous events on the same live subscription can arrive in either order. Cancellation takes precedence over a status update at the same timestamp. Other timestamp ties use the event ID. Both signed delivery orders end at the cancellation watermark with the same account cap and retention state.

A checkout that reaches a terminal payer after retention gets a durable rejection linked to the provider delivery. The cleanup-first test uses a new subscription and a matching transaction. It checks the rejection reason, unconsumed intent and deletion record. The renewal-first test checks the applied event, consumed intent and preserved domain.

The first migration on an empty schema creates a durable fresh-install marker in the migration transaction. A later deploy therefore skips pre-A repair and mixed-tombstone normalization even after customers have purchased. The migration regression runs twice on an isolated empty schema with witnesses that fail if either historical job runs. Existing upgrade databases retain their original repair path. S13 continues to exercise that separate path.

### Scenario evidence

| §5 | Result | Observation |
|---|---|---|
| S1 | PASS | Registration commits the challenge, mismatched mailbox fails, proof issues a usable key, replay fails. |
| S2 | PASS | Concurrent proofs reach the claim boundary. Delivery observes committed state and only one credential is issued. |
| S3 | PASS | Five report contenders reach a bounded admission path with a measured peak of two waiters. After an interrupted multipart stream, both executor callbacks overlap and both requests succeed. Billing verifies early refusal before reading, signed intake and full simultaneous recovery. |
| S4 | PASS | Driver failure, formatted ASGI exception, scheduler logs and operator startup all exclude the synthetic diagnostic value. |
| S5 | PASS | The mounted connector refuses malformed later choices, invalid factors and unknown truth before payer resolution. Fresh label, domain, engine and quota reads show zero writes. |
| S6 | PASS | The maximum action passes through project configuration and scoring. Invalid creation, oversized item lookup and unsupported settings mutation return 422. Project version and persisted rows are checked. Composite connector IDs work at the boundary on reuse. |
| S7 | PASS | Two-key ambiguity and mismatched signed fulfilment are refused. Successful checkout upgrades the designated payer. |
| S8 | PASS | Account and scoring reflect current subscription state across hold, resume, cancellation and replacement. A retired subscription cannot take control. |
| S9 | PASS | Duplicate, delayed and premature deliveries have independent receipt, watermark and notice assertions. The companion tie-order regression checks live cancellation. |
| S10 | PASS | Independent PostgreSQL transactions witness the contender at the tenant guard in both signed commit orders. Fresh reads identify the specific application or retention rejection. |
| S11 | PASS | Issuance/rotation and cleanup exercise both orders, including refusal after deletion and survival of an issued sibling. |
| S12 | PASS | Two cleaners contend at the guard. Exactly one cleans the pair and a disabled paid sibling protects tenant data. |
| S13 | PASS | The existing historical fixture covers scoped repair, conflict quarantine, rerun and conditional undo. Additional historical combinations have explicit ledger triggers. |
| S14 | PASS | Account summary and actual scoring agree at the cancelled daily and paid monthly UTC boundaries. |

### Existing closure and scope

The 19 previously closed P1 IDs are R02, N05, R08, R09, N02, B6-03, F1, F3, F4, F7, F8, F10, F12, F15, F21, N1, N3, N6 and N7. The signed intake, challenge proof, actor attribution, admission, startup diagnostic and request-durability checks continue to exercise these paths. The session ledger records the old receipt/manifest subcases of N1 and F1 separately from their live behavior.

### Final source inspection

| Files and functions | Contract check |
|---|---|
| `db/entitlement.py` · `resolve_entitlement`, `require_payer_eligibility`, `expired_trial_error` | A write locks the complete actor/payer set and rechecks the actor digest. Purchase, retention, owner write and member write share a state calculation. The expired-trial API preserves its structured 402 detail and upgrade link. |
| `account.py`, `trial_guard.py` · summary, name resolution, expiry and reservation | Display and reservation agree on the cancellation cap and use the same UTC state. Name resolution locks before persisting an alias. |
| `auth.py`, `projects_router.py` · authentication, project resolution, settings and invitation claim | Body/path limits precede resource selection. Members are pinned and revalidated. Unsupported settings fail validation. The claim checks the verified mailbox, actor digest, issuer, current role, expiry and revocation under lock before writing. |
| `billing.py` · checkout matching, receipt lookup, webhook dispatch and reconciliation | Unknown and rejected attempts retain their audit path. Applied duplicates short-circuit under the guard. A terminal payer and an expired intent produce distinguishable decisions. Signed cancellation ties cannot be superseded by a simultaneous pause. |
| `label_studio.py` · configuration, prediction and webhook envelopes, action and factor parsing | All supplied choices and typed task structures are checked, including subsequent results after a valid first action. Invalid prediction rows retain their input index without returning raw row data. Schema membership is checked before scoring or reservation. |
| `db/migrate.py` · fresh-install detection and migration dispatch | The marker is written before table creation in the same migration transaction. Production entrypoint invokes migration before starting the service. PostgreSQL and SQLite tests use separate empty schemas/databases on the first run and the same schema on redeploy. |
| `test_s01_s06.py`, `test_s07_s14.py`, `fixtures/pg_schema.py`, `test_r2_unified.py` | Tests use deadlines on contenders, independent committed-state readback and the actual scheduler/webhook entry points. The empty-schema fixture retains normal per-test teardown. |
| `test_r2_fixes.py`, `test_prompt_a_projects.py`, `test_account.py`, `test_billing_fixes.py` | Invite fixtures distinguish the confirmed identity from invoice contact. Billing fixtures send valid transaction identities, including in negative tests where another condition is under test. |

N12 is a P2 closed by rejecting unsupported project settings and checking the unchanged version. The PostgreSQL ownership constraint inverse, explicit-null settings validation and queue search/page reset retain their prior coverage. Signup still uses mailbox confirmation. Settings uses the checkout response from the billing API. The two-worker Playwright suite exercises the built frontend.

## R2 disposition

| Disposition on fresh PostgreSQL | IDs | Evidence |
|---|---|---|
| Six launch P1s closed in this sweep | N03, R05, F6, F16, F17, R19 | S5/S6 input and persistence checks, account and member entitlement test, reciprocal-grant barrier, UUID alias writers and both orders of signed live cancellation. |
| Nineteen previous closures retained | R02, N05, R08, R09, N02, B6-03, F1, F3, F4, F7, F8, F10, F12, F15, F21, N1, N3, N6, N7 | S1–S14, focused R2 regressions, contracts and mailbox-bound invitation tests. |
| Eight incoming P1 rows deferred for legacy data | R14, F2, F5, N10, R23, N2, N9, N11 | No imported pre-A rows in the launch installation. On a fresh deploy the migration excludes these repair jobs on first install and on restart. Each historical subcase has a trigger, owner and estimate in the session ledger. |

The total is 33 distinct review IDs. Retrospective subcases of F1, N1 and R19 also appear in the ledger. Their live paths are covered by signed fulfilment, retry and tie-order tests. The production gate uses PostgreSQL for concurrency and treats SQLite results as advisory.

Two related contract fixes emerged during the final check. The expired-trial response again carries its structured error and upgrade link. Invitation checks now compare the recipient against the proved signup address even when Paddle supplies a different billing contact. The browser audit also found that every screen loaded the checkout SDK synchronously. Ordinary hash routes now run independently of the provider CDN. A transaction landing page loads the SDK and initializes the sandbox overlay. The navigation test checks both paths with a local SDK fixture.

## Final verification

| Gate | Observed result |
|---|---|
| PostgreSQL 17, full `tests/` | 140 passed, 13 skipped, 4 xfailed in 197.11 s |
| PostgreSQL 17, standalone harness | 140 passed, 13 skipped, 4 xfailed in 198.03 s. These tests overlap the full run. |
| SQLite standalone advisory harness | 137 passed, 16 skipped, 4 xfailed in 189.47 s |
| Full Playwright suite, rebuilt frontend, two workers, zero retries | 124 passed in 39.1 s and 124 passed in 41.8 s, consecutively |
| Frontend build and E2E typecheck | TypeScript and Vite passed. The E2E project passed with the repository’s frontend TypeScript compiler. |
| Python typecheck | mypy passed on 21 files covering the service modules and modified harness and offline tests. |
| Supplemental offline root suite | 444 passed, 1 skipped. Root discovery collected 602 across both trees with the four live Docker/ops modules and provider-calling script excluded. |

All five requested test commands exited zero in the final sequential run. Earlier overlapping runs hit browser load and fixture timeouts. The supplemental suite also exposed outdated transaction fixtures and regressions in the structured expiry error and invalid-task index. Those were corrected before the final verification. The 13 skipped PostgreSQL scenarios and four expected failures belong to later waves. None is S1–S14. SQLite additionally skips three PostgreSQL locking checks.

**Gate decision.** R2 approves Wave 3 for the fresh-database deployment. Migration of historical customer records requires the ledger work first. The browser checkout regression uses a local Paddle SDK fixture. A live provider transaction was outside this verification.
