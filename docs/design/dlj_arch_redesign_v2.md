# DLJ architecture redesign v2 — merged execution plan

Updated to v3 — 25 November 2026

**Executive summary.** PostgreSQL is primary for development, testing, CI and production. Prompt 00 freezes existing behavior before seven delivery prompts run in six waves including the harness wave. Five independent Astra reviews gate promotion. The plan budgets 33 engineer-days over 27 working days, including 2.5 review days. Paying customers launch after all PostgreSQL, browser, product and release gates pass, with SQLite compatibility results published separately.

**Execution authority.** Execute v3 in this file. It supersedes the v2 schedule and the two historical redesign and Post-Track 2 plans. The supplied schedule names eight work packages: a standalone harness plus seven delivery prompts (A–F and 12). The 24.5 implementation days plus five half-day reviews total 27 elapsed days.

## 1. P1 launch classification

| ID | Failure | Launch class | Owner | Launch rationale |
|---|---|---|---|---|
| R02 | Customer overrides purchaser | BLOCKS LAUNCH | A | A real payment can upgrade the wrong key. Authentication alone does not identify the payer. |
| R14 | Reactivation versus deletion | BLOCKS LAUNCH | A | Cleanup can erase a paying tenant’s labels and engines. A single web instance still runs concurrent jobs. |
| R19 | Subscription lifecycle gaps | BLOCKS LAUNCH | A | Paused, past-due or replacement subscriptions can retain or lose paid capacity incorrectly. |
| R23 | Historical provider mapping | BLOCKS LAUNCH | A | Before launch, establish provider ownership and preserve historical PostgreSQL values. SQLite parity is advisory. |
| N05 | Expired sibling retention | BLOCKS LAUNCH | A | Two cancelled keys can keep each other and their data alive past the promised retention period. |
| R08 | Unverified signup | BLOCKS LAUNCH | A | The requester and an unrelated mailbox can receive the same credential. Rate limits do not prove ownership. |
| R09 | Unbounded report waiters | BLOCKS LAUNCH | A | Anonymous uploads share the process with paying users. Preserve admission before parsing and bounded waiters. |
| N02 | Driver diagnostics bypass value redaction | BLOCKS LAUNCH | A | Diagnostic fields derived from untrusted driver text can reach operator logs or error responses. |
| N03 | Malformed connector dispatch | BLOCKS LAUNCH | A | Invalid envelope types produce an unhandled failure on a supported integration. Service-token auth does not validate event shape. |
| R05 | Unbounded persisted IDs | BLOCKS LAUNCH | A | PostgreSQL can reject derived IDs that pass request validation and work in SQLite. |
| R3-01 | Late signup changes account | BLOCKS LAUNCH | B | A stale signup response can replace the key selected by a paying user. |
| R3-02 | Prior account’s upload survives rotation | BLOCKS LAUNCH | B | A stopped run can expose the previous customer’s file to the next account on a shared browser. |
| R3-03 | Save Tags, category dirty state and conflict navigation | BLOCKS LAUNCH | B | A verify or category-save response can erase newly edited spans or tags. |
| R3-08 | Invalid DTO crashes the app | BLOCKS LAUNCH | B | A successful HTTP status with the wrong JSON shape can take down the paying user’s whole route tree. |
| R01 | Connector uses stale reviewer engine | BLOCKS LAUNCH | C | A known new category can break learning only on the connector path. |
| R03 | Connector revision loses content | BLOCKS LAUNCH | C | Current detail and export can lose attached evidence and revision provenance. |
| R04 | First domain or engine creation races | BLOCKS LAUNCH | C | Valid simultaneous writes can fail inconsistently and invite duplicate retries. |
| R24 | SQLite row-lock assumptions | ACCEPTABLE RISK | v1.1 | Only concurrent SQLite writers are exposed. Production, CI release gates and supported multiwriter deployments use PostgreSQL. |
| R29 | Connector config lost update | BLOCKS LAUNCH | C | A single worker reduces the race today. Shared config is already changing with project ownership; a DB upsert also removes future worker-count dependence. |
| R45 | Revision erases negative evidence | BLOCKS LAUNCH | C | A category change can improve apparent accuracy without new human evidence, affecting automation. |
| R13 / R3-07 | Bulk action becomes ground truth | BLOCKS LAUNCH | C | Explicit UI outcome works; older callers can still train on agreement without independent truth. |
| R06 | Legacy decision and snapshot split | ACCEPTABLE RISK | v1.1 | Failure can corrupt a legacy engine; the affected store is separate from paid DLJ and no external consumer is known. |
| R07 | Legacy plaintext credentials | ACCEPTABLE RISK | v1.1 | Disclosure of legacy storage or backups exposes usable JM keys. Separate authentication bounds direct DLJ access. |
| R30 | Historical centroid-key collisions | ACCEPTABLE RISK | v1.1 | Affected pairs share learning in old JM snapshots. New legacy domains reject pipe separators. |
| B6-01 | Commit after response | CLOSED | 00 | Round 6 made commits a prerequisite for write success. Future route changes must preserve that boundary. |
| B6-02 | Stale connector redelivery | BLOCKS LAUNCH | C | A genuine correction can be silently lost when dated and undated connector updates interleave. |
| B6-03 | Billing intake unbounded | BLOCKS LAUNCH | A | Per-request byte enforcement leaves the paying service sharing capacity with stalled billing readers. |
| B7-01 | Connector task reassignment | BLOCKS LAUNCH | C | An existing verified judgment can silently move to the wrong source task. |
| F7-01 | Queue DTO in history | BLOCKS LAUNCH | B | Private label fields persist in review history after a user changes accounts. |

**Scorecard.** 24 BLOCKS LAUNCH obligations (A 11, B 5, C 8), four ACCEPTABLE RISK items, one separately CLOSED contract. These are release obligations, including previously patched behavior requiring regression coverage. The original 21 lose R24 and gain four distinct open IDs (B6-02, B6-03, B7-01, F7-01). N02 and R3-03 expand existing rows. B6-01 was outside the original 21. The sweep 7 point-in-time count of open defects remains a separate metric.

## 2. Merged prompts

| Wave / package | Merges | Depends on | Elapsed days | Deliverable and exit gate |
|---|---|---|---:|---|
| 1 / 00 Harness | baseline | current checkout | 3 | Real app, schema-per-test PostgreSQL, 46 existing contracts, 22 durable writes, browser contracts and 27 owned scenario shells. SQLite CI is advisory. No production DDL. |
| 2 / A Projects, billing, identity and access | 02+03 | R1 | 6 | Project CRUD, billing FSM, challenges, ownership, membership, invites, admission, ID validation and safe diagnostics. Both A schema blocks in §4. S1–14, historical upgrade twice, roles and payer matrix, archive and checkout tests. |
| 3 / B Project UI | 04 | R2 | 4 + joint day | Project chooser, nested hash routes, team/settings, request context, guarded edits, private-history hygiene and explicit outcome. No DDL. S28–32. |
| 3 / C Shared writes | 05 | R2 | 4 + joint day | Transaction service, typed import, HTTP and connector adapters, source binding/order, replay, quota, evidence and config. C schema. S20–27. C leads final day with B on real S27 plus S28–32. Failure blocks wave 4. |
| 4 / D Export and predictions | 06+08 | R3 | 5 parallel | Scoped JSONL/CSV/DocBin export, prediction import, model provenance, review, automation and reopen. Both D schema blocks. Reuse S21/S26 and exercise streaming/leases, accuracy, cap, rollback, replay and no learning from machine-only decisions. |
| 4 / E Webhooks | 10 | R3 | 5 parallel | Admin CRUD, outbox, durable delivery, exact signed bytes, retries, leases and rotation. E schema. Reuse S21/S24/S27, exercise restarts, two workers, egress and rollback. D/E agree event envelopes before parallel work. |
| 5 / F Guide, prediction UI and integrations | 07+09+11 | R4 | 4 | Public guide, OpenAPI, executable Python client, prediction review, integrations settings and delivery health. No DDL. S1/S23/S27–31 plus quickstart, role, keyboard, secret handling and recovery gates. |
| 6 / 12 Release | release | R5 | 1.5 | Single-instance Railway procedure in §6, all 27 green, paid checkout through signed delivery smoke, four accepted items recorded. |

A, B and C start by verifying existing fix tests pass. Build integration scenarios on that coverage.

### 2.1 Review cadence

Every development wave ends with a mandatory independent Astra review before the next prompt is sent. Read every modified file in full using /model astra /reasoning high. Cover wave fix verification, broad backend and frontend review, test health, P1 scorecard, next-wave decision and a file/endpoint self-check. Repair new P1s or regressions before promotion. Release itself ends with the operational verification in §6.

| After wave | Scope | Required evidence |
|---|---|---|
| 1 / R1 | Harness correctness, fixtures, contracts, §5 coverage | 46 contracts pass; 27 owned shells skip or xfail; no harness-introduced regression. |
| 2 / R2 | A plus harness and prior fixes | S1–14 green, contracts green, prior 443 pytest and 124 PW green on primary gates. |
| 3 / R3 | Integrated B+C, earlier gates | S20–32 and S1–14 green; real joint S27. |
| 4 / R4 | D/E plus all prior gates | Export, prediction and delivery gates and inherited scenarios green. |
| 5 / R5 | F, full regression | All 27 active scenarios, full PostgreSQL pytest and PW green. |

### Pre-existing fix credit

Credit estimates cover fixture setup and regression assertions that each owner can reuse. The five backend fix modules passed on both database lanes in the round-four verification (63 passed, one dialect-specific skip per lane). The five named browser cases also passed in that sweep, which recorded two failures elsewhere in the browser suite. A passing targeted test earns reuse credit only for the assertion shown.

**Test-file key:** A = `test_resweep_fixes.py`, B = `test_sweep3_fixes.py`, C = `test_billing_fixes.py`, D = `test_validation_fixes.py`, E = `test_migration_fixes.py`, F = `e2e/fix_round3.spec.ts` (Playwright test titles).

| Owner | Finding | File and test | Existing evidence | Remaining integration work | Hours saved |
|---|---|---|---|---|---:|
| A | R14 · retention after renewal | A · `test_reactivation_between_scan_and_lock_prevents_cleanup`<br>A · `test_cleanup_still_cancelled_deletes_tenant`<br>B · `test_active_sibling_preserves_data_while_cancelled_key_expires` | A renewal committed between scan and recheck preserves the label. A still-cancelled sole key is cleaned; an entitled sibling preserves data. | S10–11: overlap real transactions, including sibling creation, with the new tenant guard. Check both commit orders. | 2 |
| A | N05 · expired siblings | B · `test_two_expired_cancelled_keys_clean_together` | Both keys are deactivated and the tenant’s labels and domain are deleted. | S12: repeat under the new FSM and check exactly one cleanup transition. | 1 |
| A | R02 · purchaser binding | C · `test_checkout_upgrades_specific_key` | First checkout carries the purchaser UUID and upgrades that key. The last assertion preserves the old customer-first behavior for conflicting hints. | S7: replace that conflict expectation with refusal or a reconciled payer. Verify paid capacity using the purchasing key. | 1 |
| A | R19 · billing lifecycle | C · `test_older_activation_preserves_cancellation`<br>C · `test_duplicate_event_rejected_after_intervening_update` | An older creation does not revive a cancellation; replay after another event preserves tier. The old duplicate response is 409. | S8–9: add pause, past due, resume, replacement, unknown events and the proposed idempotent acknowledgement. | 1 |
| A | R23 · provider migration (fixture credit only) | E · `test_second_migration_keeps_same_schema`<br>E · `test_postgresql_upgrade_preserves_utc_instants`<br>E · `test_sqlite_upgrade_adds_timestamp_columns` | The dialect-specific migration fixtures exercise schema repeatability and timestamp behavior. They do not assert provider ID values. | S13: seed historical IDs and ownership, verify actual values on repeat upgrade and quarantine ambiguous matches. | 1 |
| A | R44 · cancellation with absent or retired product¹ | A · `test_cancellation_ignores_product`<br>B · `test_cancel_without_items_still_sets_cancelled_at` | Unknown or retired products allow cancellation; no-items canceled events and updated events with canceled status persist a cancellation date. | S8–9: preserve these cases through FSM dispatch, receipt handling and replay. | 1 |
| A | R18 · daily cap after cancellation¹ | A · `test_cancelled_paid_key_uses_trial_daily_cap`<br>A · `test_active_paid_key_keeps_paid_cap`<br>B · `test_sqlite_naive_cancelled_timestamp_uses_daily_cap` | Cancelled paid key at 50 gets daily 429; active paid control reaches 51. The timestamp test covers SQLite’s naive UTC representation in its SQLite lane. | S14: assert effective account limits, actual reservations and UTC day/month rollover against the canonical payer. | 1 |
| A | R09 · report admission | B · `test_busy_report_worker_rejects_before_read`<br>B · `test_oversized_report_upload_is_rejected` | Busy handler never reads the file and the mounted route rejects malformed multipart while busy. Oversize yields 413 and the handler releases its slot. | S3: measure aggregate bytes/waiters under simultaneous uploads, including request parsing and disconnect. | 1 |
| A | R05 · identifier bounds | D · `test_long_label_id`<br>D · `test_long_annotator_id`<br>D · `test_long_category`<br>A · `test_connector_webhook_invalid_item_is_422` | 201-character body IDs/categories get 422; the invalid new connector item leaves no label. | S6: cover max and max+1 for derived IDs, existing-row updates and task paths on both dialects. | 1 |
| A | N02 · outer SQL logging (adjacent coverage) | A · `test_batch_conflict_log_redacts_source`<br>D · `test_batch_error_hides_sql` | A handled duplicate log omits source and factor names. The second test checks the HTTP body only. | S4: carry the sentinel checks into uncaught ASGI, scheduler and driver logs. | 1 |
| A | N03 · connector dispatch (adjacent coverage) | A · `test_malformed_connector_result_skipped`<br>A · `test_null_connector_annotation_id_is_rejected` | A malformed nested result is skipped and logged; null annotation ID is rejected before writing a label. | S5: exercise invalid top-level action types before dispatch. Nested-result tests do not reach that failure. | 1 |
| B | R3-01 · late signup | F · `late signup response keeps the credential chosen after navigation` | A delayed receipt after leaving signup does not activate its key over the selected credential. | S28: check generation changes including A→B→A and a second tab against the integrated auth flow. | 1 |
| B | R3-02 · prior-account file | F · `credential abort clears the selected CSV and upload form` | A credential change clears the file input, analysis and scoring affordance in the mocked browser flow. | S29: interrupt real chunks, inspect committed owners, then attempt restart without reselecting a file. | 1 |
| B | R3-03 · review drafts | F · `tag input survives a locked category save` | Tag entry is disabled during category save and its draft survives successor navigation. | S31: verify and relabel through the shared mutation lock, including dirty navigation and conflict handling. | 1 |
| B | R3-08 · malformed usage DTO | F · `settings renders account usage defaults when usage is absent` | Settings still renders its usage heading and defaults when the whole usage object is absent. | S32: validate malformed nested values and recover from a failed lazy import. | 1 |
| C | R01 · stale reviewer centroids | B · `test_connector_verify_syncs_missing_category_centroid` | Connector verification restores the missing NER approval centroid, including when the category is already in engine config. | S20: compare persisted engine and evidence from equivalent HTTP and connector operations. | 1 |
| C | R03 · structured revision copy | B · `test_connector_revision_copies_ner_spans`<br>B · `test_connector_revision_copies_tags` | The connector successor has the predecessor’s NER spans or tags after correction. | S21: compare both adapters, image content, provenance, actor and current revision pointer. | 2 |
| C | R04 · first-create race | D · `test_domain_creation_race_returns_conflict` | An injected domain insert IntegrityError maps to 409 on the task route. | S22: use two real sessions for first-domain and first-engine contention, and check rollback and retry. | 1 |
| C | R29 · connector config update | A · `test_concurrent_connector_config_preserves_both_projects` | Two threads in one process both return success and both tenant/project entries remain in the file. | S25: verify two processes and restart against the new transactional config store. | 1 |
| C | R45 · revisions and negative evidence | A · `test_verified_incorrect_same_category_conflicts`<br>A · `test_verified_incorrect_different_category_succeeds`<br>B · `test_identical_category_and_spans_is_noop`<br>B · `test_same_category_with_changed_spans_is_valid` | No-op revisions are rejected; a changed category or changed span can create a successor. These tests inspect revision state, not the accuracy denominator. | S26: query accuracy and learner evidence through change, reversion and subsequent human adjudication. | 1 |
| C | R13 / R3-07 · bulk truth | A · `test_bulk_explicit_false_on_recommended_reject`<br>A · `test_bulk_explicit_true_on_approve`<br>B · `test_implicit_bulk_reject_sets_false`<br>F · `bulk approval sends an explicit verified outcome` | The backend persists explicit outcome values, including false on agreement. The legacy test records the fallback. The browser test checks an outbound field derived from the action in a mocked request. | S27: run the real UI and API together, supply mixed independent outcomes and a skipped ID, then inspect rows and learning trackers. | 2 |

¹ R44 and R18 are historical regression controls. Existing credits are already included in the estimate.

| Additional fix suite | Verified coverage | Credit and remaining gate |
|---|---|---|
| test_round5_fixes.py (4) | Annotator evidence, request and scheduler diagnostic sanitization, non-string connector dispatch | A/C reuse fixtures for S4–5 and S26. |
| test_round6_fixes.py (7) | Failed/successful commit, two formatter cases, dated connector replay, two billing byte-limit cases | 00 freezes write order. A still owns intake admission and diagnostics. C still owns ambiguous deliveries. |
| e2e/fix_round5.spec.ts (3) | Cross-tab rotation, canonical draft, receipt clearing | B reruns with the project request context. |
| e2e/fix_round6.spec.ts (3) | Save Tags, whole-store clear, File handoff | B adds category dirty and private history assertions. |

Additional credit is 0.5 engineer-day each for A, B and C (1.5 total), included in the estimate. Browser tests reside in the two Playwright modules.

**Product contracts to implement**

- **A projects.** A project UUID is existing Domain.id; internal domain key and tenant remain unchanged. POST/GET /v1/projects, GET/PATCH/DELETE /v1/projects/{uuid}; DELETE archives. Scope every child lookup. PATCH uses settings_version/If-Match. Existing owner aliases and unclassified rows remain readable. A member's personal key identifies the actor; the owner pays. Before sharing a multi-key tenant, reconcile subscription, original trial start and matching UTC counters exactly once. Quarantine ambiguous ownership and preserve private access.
- **A billing.** Implement one transition function and one effective-entitlement resolver for checkout, quota, account, scheduler and connector. Verified signup→trial, clock→trial_expired, verified purchase→active, effective pause/past_due→restricted, valid resumed/activated→active, effective cancellation→cancelled at 50/day, cutoff after 30 days→cleaned_up terminal. Keep existing counters and paid tier history. Confirm the proposed past-due scoring hold with billing owner before rollout. Bind purchaser, payer and provider transaction before granting capacity. Authenticate events, deduplicate by committed receipt, audit unknown/stale events without advancing the applied watermark, reconcile ties and replacements. Require a known tier only for paid grants. Tenant guard → sorted keys → domain → labels → engine is the common lock order. Serialize key creation, renewal and deletion, recheck all siblings, outstanding purchases and provider holds before deleting. Track equivalent SQLite writer serialization under advisory R24 in v1.1. Notification intent commits with the transition.
- **A identity.** Reviewer may verify/import/export; annotator may classify/edit; admins manage settings/team; owners alone grant admin, archive and bind billing. Return 401/403/404 for invalid credential, insufficient visible role and inaccessible project respectively. Preserve actor and payer separately across legacy *labeling* routes. Invites use a digest, 48-hour expiry, recipient proof, one-time consumption and revocation/recheck of inviter authority. Signup uses a separate short-lived mailbox challenge and issues a bearer only after confirmation commits. Migrate the old signup surface and rotate shared historical keys before closure. Limit anonymous uploads before multipart decoding, release capacity on disconnect, validate all derived IDs and sanitize outer framework, SQL and job errors.
- **B/C.** Capture credential, account generation, project UUID/public alias, operation ID and AbortSignal once per operation. Abort on rotation/unmount or project switch; verify ownership before dispatch and before all post-await storage/UI effects. Clear files, drafts, selection, receipts and caches when identity changes. Preserve old hash links, free anonymous report and sample. Keep global account checkout separate from project settings. Expose project-scoped adapters for queue, detail, bulk, verify, sample, tasks, revision/content, dashboard, autonomy, IAA and guidelines. Preserve bare pending arrays and X-Total-Count. POST project labels/batch accepts 1–100 items, 32 KiB UTF-8 text, typed content and idempotency key. Lock predecessor/engine and preserve label content, actor and lineage on every adapter. Resolve concurrency before learning. Latest verified evidence stays in accuracy until human re-adjudication. Bulk truth is per item or explicitly homogeneous; unobserved truth cannot train. Retire legacy implicit writes after callers migrate. Preserve historical bulk quota and partial-skip behavior.
- **D/F export.** GET project export emits one current revision per logical item with root/current IDs, source, full text, category, annotator, action, true/false/null outcome, scores, UTC times, content/spans/tags/image, review state and optional factors. Filter by review status, category, annotator and UTC date interval. Stream JSONL/escaped CSV in a single snapshot, pages of 500, two slots/project, five-minute deadline. Preflight English tokenizer DocBin alignment and human span adjudication; cap at 5,000 documents or 16 MiB text and verify on Hobby. Browser fallback limited to 32 MiB. Guide at /#/docs, Swagger at /docs, schema at /openapi.json, client at /dlj_client.py. Client reports committed chunks, retries with the same key, and saves downloads only after completion.
- **D/F predictions.** POST project predictions (1–100), GET stats, POST reopen/review with expected revision and decision version. Separate model confidence from scored confidence. Automation defaults off; require model floor (default .95), approve recommendation, autonomous tier, passing conservation and named-annotator eligibility. Persist the original input and decision. Machine approval never supplies a human outcome. Charge only new scored imports; human verification/reopen/replay add no scoring charge apart from existing bulk policy. Preserve machine approval history, unknown human assessments and explicit review of spans.
- **E/F delivery.** Register project webhooks, test sends and paginated deliveries. Emit label.verified, prediction.auto_approved and webhook.test in the business transaction. Persist canonical bytes, HMAC-SHA256 of timestamp + period + body, event ID and key version. Disclose signing secret once. Five endpoints/project, ten tests/endpoint/hour. Validate public HTTPS at connection time, disable redirects, encrypt secrets. Four sends maximum with immediate/10/60/300-second schedule, 10-second timeout, 30-second fenced lease, one send/endpoint and four concurrent sends. Rotate/archive cancels stale pending/leased work; receiver deduplicates. Retain terminal metadata 30 days. No source text, bearer tokens or raw response bodies in logs.

## 3. Deferred to v1.1

| Item | Reason and mitigation | Trigger and owner | Future effort |
|---|---|---|---|
| R06 · JM split commits | Only the legacy decision log/engine store is affected. Existing duplicate-learn checks do not make two commits atomic. Keep paying customers on DLJ routes, restrict legacy writes to identified test consumers, monitor failures and preserve a restorable snapshot. | Service owner reopens before first external JM write dependency, increased concurrency or any state/log mismatch. | ~3 engineer-days |
| R07 · plaintext JM bearer identities | Legacy and DLJ use separate credentials/stores. Raw JM credentials remain usable if the volume or its backups are disclosed. Restrict volume/backup access, omit keys from telemetry, use disposable JM test credentials and rotate them on exposure. | Security owner reopens on any external JM account, increased backup access or suspected disclosure. | ~3 engineer-days |
| R30 · legacy centroid collisions | New domain validation already rejects pipe-bearing categories/actions. Inventory historical configs, quarantine ambiguous engines from learning and keep them out of DLJ. | Engine owner reopens when a historical collision is found or an old snapshot needs production use. | ~2 engineer-days |
| R24 · SQLite row locking | Run compatibility CI and publish divergences. Paying and development deployments use PostgreSQL. | Storage owner must implement serialized writes before supporting concurrent production SQLite in v1.1. | Re-estimate with the advisory concurrency results. |
| Legacy migration and reconciliation | No known production client beyond scripts is the planning assumption. Verify with redacted route counts before launch; absence of consumers is not proven by repo search. Keep the distinct legacy API outside DLJ membership and billing. | Platform owner implements Option B from v1 §2, including digest mapping, atomic decision storage and migration rehearsal, if any trigger above fires. | ~2 shared days **plus** the three rows above = **10 total** |
| Full blue/green handoff | Hobby deployment has one instance and accepts a brief restart. The existing entrypoint migrates before Uvicorn. Operational acceptance requires a tested restore and a release window; a DB backup does not eliminate downtime. | Operations lead reopens before a no-downtime SLA, multi-replica rollout, active legacy traffic or migration longer than the agreed window. Historical reference: **dlj_arch_redesign_v1.md §6, Railway rollout, cutover and rollback**. | Allow up to 4 engineer-days at that time; re-estimate from traffic and data size. |

Accepted means risk is still present. The launch owner records the consumer check, controls, trigger and next review date. If a paying workflow needs legacy JM, its affected P1s become blockers before onboarding that customer.

## 4. Consolidated schema ledger

The blocks are **forward and inverse definitions** for migration authors. The inverse statements are a separate downgrade, never executed as part of upgrade. PostgreSQL uses UTC timestamptz and application-generated UUIDs. SQLite uses the existing ORM UUID representation, JSON encoding, checked text enums, UTC normalization and FK enforcement. Use versioned catalog checks, one migration runner, fresh and historical fixtures, and a second upgrade run. On SQLite use an FK-safe staged rebuild when an ALTER is unsupported; compare values and child counts and run foreign_key_check before commit. No legacy JM tables, credential audience discriminator or volume migration enter this release.

### A · Projects, entitlement, historical repair

Enables R02/R14/R19/R23/N05. Add nullable lifecycle state first. New readers tolerate null during backfill; old binaries can read the additive schema. Hold destructive cleanup and keep new sharing disabled until every writer uses the new policy. A downgrade to a binary that bypasses this policy requires disabling billing mutations and retention or using a compatible rollback build.

```sql
CREATE TYPE subscription_lifecycle AS ENUM
 ('trial','trial_expired','active','past_due','paused','cancelled','cleaned_up');
ALTER TABLE api_keys ADD COLUMN subscription_state subscription_lifecycle;
ALTER TABLE api_keys ADD COLUMN state_version bigint NOT NULL DEFAULT 0;
CREATE TABLE tenant_guard (tenant_id varchar(200) PRIMARY KEY);
ALTER TABLE api_keys ADD CONSTRAINT uq_key_owner UNIQUE(tenant_id,id);
CREATE TABLE project_billing_owner (
 owner_tenant_id varchar(200) PRIMARY KEY REFERENCES tenant_guard(tenant_id),
 billing_key_id uuid NOT NULL UNIQUE, trial_started_at timestamptz NOT NULL,
 FOREIGN KEY(owner_tenant_id,billing_key_id) REFERENCES api_keys(tenant_id,id)
);
CREATE TABLE checkout_intent (
 id uuid PRIMARY KEY, tenant_id varchar(200) NOT NULL, purchaser uuid NOT NULL,
 payer uuid NOT NULL, tier varchar(20) NOT NULL, transaction_id varchar(200) UNIQUE,
 expires_at timestamptz NOT NULL, consumed_at timestamptz,
 FOREIGN KEY(tenant_id,purchaser) REFERENCES api_keys(tenant_id,id),
 FOREIGN KEY(tenant_id,payer) REFERENCES api_keys(tenant_id,id)
);
CREATE TABLE subscription_binding (
 subscription_id varchar(200) PRIMARY KEY, payer uuid NOT NULL REFERENCES api_keys(id),
 customer_id varchar(200) NOT NULL, retired_at timestamptz
);
CREATE UNIQUE INDEX one_current_sub ON subscription_binding(payer) WHERE retired_at IS NULL;
CREATE TABLE transition_log (
 event_id varchar(200) PRIMARY KEY, key_id uuid REFERENCES api_keys(id),
 subscription_id varchar(200), source varchar(32) NOT NULL,
 actor_ref varchar(200), occurred_at timestamptz NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
 old_state subscription_lifecycle, new_state subscription_lifecycle,
 disposition varchar(32) NOT NULL, reason_code varchar(64), key_version bigint
);
CREATE TABLE lifecycle_notice (
 event_id varchar(200) REFERENCES transition_log(event_id),
 kind varchar(40), delivered_at timestamptz, PRIMARY KEY(event_id,kind)
);
-- inverse, after disabling all new writers and preserving audit
DROP TABLE lifecycle_notice, transition_log, subscription_binding, checkout_intent, project_billing_owner;
DROP TABLE tenant_guard;
ALTER TABLE api_keys DROP CONSTRAINT uq_key_owner;
ALTER TABLE api_keys DROP COLUMN state_version, DROP COLUMN subscription_state;
DROP TYPE subscription_lifecycle;
```

```sql
ALTER TABLE domains ADD COLUMN description text;
ALTER TABLE domains ADD COLUMN status varchar(16) NOT NULL DEFAULT 'active'
 CHECK (status IN ('active','archived','completed'));
ALTER TABLE domains ADD COLUMN automation_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE domains ADD COLUMN confidence_floor double precision NOT NULL DEFAULT .95
 CHECK (confidence_floor BETWEEN .80 AND .99);
ALTER TABLE domains ADD COLUMN settings_version integer NOT NULL DEFAULT 1 CHECK (settings_version >= 1);
-- After all DLJ writers and reconciled rows support state:
ALTER TABLE api_keys ADD CONSTRAINT ck_dlj_state CHECK (subscription_state IS NOT NULL) NOT VALID;
ALTER TABLE api_keys VALIDATE CONSTRAINT ck_dlj_state;
-- Inverse: drop ck_dlj_state BEFORE the lifecycle inverse above.
ALTER TABLE api_keys DROP CONSTRAINT ck_dlj_state;
ALTER TABLE domains DROP COLUMN settings_version, DROP COLUMN confidence_floor,
 DROP COLUMN automation_enabled, DROP COLUMN status, DROP COLUMN description;
```

api_keys here contains only DLJ credentials; the separate JM store is untouched. Populate guards/bindings before sharing. Read historical provider columns on both dialects; conditional-copy confirmed provider IDs only where target is empty and owner/provider mapping is established. Preserve source fields; do not assume a former provider's IDs are Paddle IDs. Compare per-key UTC counters and original trial start, quarantine mismatches, and keep a protected before/after manifest. Undo a backfill only where current value/version still matches the manifest. Unmapped historical data blocks that tenant's activation. Finish the constraint only after reconciliation. Retain paddle_webhook_events for existing receipts.

### A · Challenge, team and actor authorization

Enables R08 directly. N02/N03/R05/R09 are service/input changes. Existing account and domain rows need no new membership to retain owner access. Release new confirmation/invite readers before changing registration behavior. On rollback stop issuance, drain/expire tokens and preserve audit.

```sql
CREATE TABLE signup_challenge (
  token_digest char(64) PRIMARY KEY, email varchar(200) NOT NULL,
  requested_name varchar(200), expires_at timestamptz NOT NULL, consumed_at timestamptz
);
CREATE INDEX signup_challenge_email ON signup_challenge(email);
-- inverse, after pending challenges expire
DROP TABLE signup_challenge;
```

```sql
CREATE TABLE project_member (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
 member_tenant_id varchar(200) NOT NULL, role varchar(16) NOT NULL CHECK(role IN ('admin','reviewer','annotator')),
 active boolean NOT NULL DEFAULT true, granted_by_key_id uuid NOT NULL REFERENCES api_keys(id),
 created_at timestamptz NOT NULL, revoked_at timestamptz, UNIQUE(project_id,member_tenant_id)
);
CREATE TABLE project_invite (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
 email varchar(200) NOT NULL, role varchar(16) NOT NULL CHECK(role IN ('admin','reviewer','annotator')),
 issued_by_key_id uuid NOT NULL REFERENCES api_keys(id), token_digest char(64) NOT NULL UNIQUE,
 expires_at timestamptz NOT NULL, consumed_at timestamptz, revoked_at timestamptz,
 accepted_by_key_id uuid REFERENCES api_keys(id), accepted_member_id uuid REFERENCES project_member(id),
 mail_status varchar(16) NOT NULL, last_mail_attempt_at timestamptz
);
CREATE UNIQUE INDEX uq_open_project_invite ON project_invite(project_id,email)
 WHERE consumed_at IS NULL AND revoked_at IS NULL;
-- Inverse
DROP TABLE project_invite, project_member;
```

Normalize email before insert, revoke expired pending invites on resend, and check matching authenticated account, project status and inviter authority on accept. Do not include account credentials in mail.

### C · Shared write contract and revision history

Enables R01/R03/R04/R29/R45, B6-02/B7-01 and R13 with B. Existing revision columns remain authoritative. Preflight duplicate predecessor links; resolve within project before enabling the unique index. Existing rows may have unknown key attribution. Backfill lineage only from unambiguous links. Pause config writes for one fenced JSON-file import, compare all project keys, switch reader and writer together, then retain file read-only.

```sql
CREATE UNIQUE INDEX uq_revision_predecessor ON label_log(domain_id,prior_revision_id)
 WHERE prior_revision_id IS NOT NULL;
CREATE TABLE connector_config (
 tenant_id varchar(200) NOT NULL, project_id varchar(200) NOT NULL,
 config_json json NOT NULL, version bigint NOT NULL DEFAULT 1,
 PRIMARY KEY(tenant_id,project_id)
);
CREATE TABLE project_request (
 project_id uuid NOT NULL REFERENCES domains(id), actor_key_id uuid NOT NULL REFERENCES api_keys(id),
 operation varchar(40) NOT NULL, request_key varchar(200) NOT NULL,
 payload_digest char(64) NOT NULL, result_json json NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(project_id,actor_key_id,operation,request_key)
);
-- inverse after draining writers, reconciling config and retaining replay receipts through expiry
DROP TABLE project_request, connector_config;
DROP INDEX uq_revision_predecessor;
```

```sql
ALTER TABLE label_log ADD COLUMN verified_by_key_id uuid REFERENCES api_keys(id);
ALTER TABLE label_log ADD COLUMN revision_by_key_id uuid REFERENCES api_keys(id);
-- Inverse
ALTER TABLE label_log DROP COLUMN revision_by_key_id, DROP COLUMN verified_by_key_id;
```

Disable new writers before contraction. Returning to file-backed config requires exporting **current** DB config under a write fence. Keep replay receipts to expiry. Old route adapters must share role, quota, archive and evidence checks before enabling collaborators.

### D · Export slots

Product schema. Expiring conditional claims protect the process and project snapshot. Old binaries ignore the table. Drain active exports before downgrade.

```sql
CREATE TABLE project_export_slot (
 project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
 slot smallint NOT NULL CHECK(slot IN (1,2)), lease_token uuid, expires_at timestamptz,
 PRIMARY KEY(project_id,slot)
);
-- Inverse
DROP TABLE project_export_slot;
```

### D · Prediction provenance

Product schema supports the R03/R45 evidence guarantees. Leave existing labels valid without predictions. New readers join optionally. Stop imports and retain original payloads/decisions before downgrade.

```sql
CREATE TABLE prediction (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES domains(id),
 original_label_log_id uuid NOT NULL UNIQUE REFERENCES label_log(id),
 current_label_log_id uuid NOT NULL UNIQUE REFERENCES label_log(id),
 source varchar(200) NOT NULL, model_version varchar(200) NOT NULL, original_content json NOT NULL,
 original_category varchar(200) NOT NULL, model_confidence double precision NOT NULL CHECK(model_confidence BETWEEN 0 AND 1),
 dlj_confidence double precision NOT NULL, tier varchar(32) NOT NULL, recommendation varchar(200) NOT NULL,
 gate_snapshot json NOT NULL, decision_reason varchar(64) NOT NULL,
 state varchar(20) NOT NULL CHECK(state IN ('pending','auto_approved','human_reviewed')),
 decision_version integer NOT NULL DEFAULT 1, imported_at timestamptz NOT NULL,
 machine_approved_at timestamptz, human_reviewed_at timestamptz, reviewer_key_id uuid REFERENCES api_keys(id),
 assessment varchar(12) CHECK(assessment IN ('correct','incorrect','unknown')),
 human_spans_reviewed boolean NOT NULL DEFAULT false
);
CREATE INDEX ix_prediction_scope ON prediction(project_id,source,imported_at);
-- Inverse
DROP TABLE prediction;
```

Validate both revision pointers belong to the project under the write lock. Delete dependent predictions before label rows in tenant retention.

### E · Outbound delivery

Product schema. Commit event creation with the business transition. Enable consumers only after producers and secret configuration are ready; keep Paddle receipt IDs independent. Drain or preserve leases and retained delivery history before any inverse.

```sql
CREATE TABLE webhook_endpoint (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
 url varchar(2048) NOT NULL, secret_ciphertext bytea NOT NULL, key_version integer NOT NULL,
 subscribed_events json NOT NULL, active boolean NOT NULL, destination_version integer NOT NULL,
 lease_token uuid, lease_until timestamptz, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE TABLE webhook_event (
 id uuid PRIMARY KEY, project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
 event_type varchar(64) NOT NULL, transition_key varchar(200) NOT NULL,
 schema_version integer NOT NULL, canonical_body text NOT NULL, created_at timestamptz NOT NULL,
 UNIQUE(project_id,event_type,transition_key)
);
CREATE TABLE webhook_delivery (
 id uuid PRIMARY KEY, endpoint_id uuid NOT NULL REFERENCES webhook_endpoint(id) ON DELETE CASCADE,
 event_id uuid NOT NULL REFERENCES webhook_event(id) ON DELETE CASCADE, destination_version integer NOT NULL,
 state varchar(16) NOT NULL CHECK(state IN ('pending','leased','delivered','dead','cancelled')),
 attempts integer NOT NULL DEFAULT 0, next_attempt_at timestamptz, lease_token uuid, lease_until timestamptz,
 delivered_at timestamptz, last_status integer, error_class varchar(100), UNIQUE(endpoint_id,event_id)
);
CREATE INDEX ix_delivery_due ON webhook_delivery(state,next_attempt_at);
CREATE INDEX ix_delivery_lease ON webhook_delivery(state,lease_until);
CREATE TABLE webhook_attempt (
 delivery_id uuid NOT NULL REFERENCES webhook_delivery(id) ON DELETE CASCADE, attempt_no integer NOT NULL,
 started_at timestamptz NOT NULL, finished_at timestamptz, outcome varchar(24), http_status integer,
 PRIMARY KEY(delivery_id,attempt_no)
);
-- Inverse
DROP TABLE webhook_attempt, webhook_delivery, webhook_event, webhook_endpoint;
```

**00, B, F and 12 add no tables or columns.** Apply inverses in reverse dependency order on a restored copy. For production application rollback prefer keeping additive schema and data. Update retention deletion order for restrictive children as each table ships, including project_request before domains. Keep immutable billing audit on key deactivation.

## 5. Integration scenarios and release evidence

Ship the harness at 00 **before any production change**. Keep v1 scenario numbers stable. Remove only S15–19 (legacy import/auth replay, split commit, concurrent legacy learn, historical centroid conversion, fenced legacy cutover). Keep the existing legacy wire smoke suite. **27 scenarios remain**; parametrized dialects, timing orders and the product acceptance gates in §2 are additional executions.

Use asynchronous pytest fixtures on the asyncio backend with one PostgreSQL schema per test, shared by independent connections. Run the same compatible cases in a separately selected, non-blocking SQLite CI job with FK enforcement. Assert actual dialect and connection identity. Coordinate two writers at transaction boundaries with timed barriers and inspect committed results from a third session. Use the real mounted service and two browser contexts for identity/project changes. Stub clocks, mail and provider transport; exercise actual auth, quota, transactions, migrations and learner. At 00 freeze a per-case owner and baseline; distinguish a failing behavioral assertion from infrastructure or missing-route errors. At its assigned merge gate each scenario must be active and green. All launch scenarios must pass on PostgreSQL at 12. The four accepted risks are tracked separately.

| Scenario | Accountable prompt | Boundary exercised | Acceptance oracle |
|---|---|---|---|
| S1 | A | New signup and mismatched mailbox | Only a consumed mailbox proof receives an active key, R08. |
| S2 | A | Concurrent proof consumption and mail failure | At most one credential, no precommit delivery, R08. |
| S3 | A | Concurrent anonymous uploads at admission limit | Early refusal, bounded time and concurrent readers for reports and signed billing intake, R09/B6-03. |
| S4 | A | Forced unhandled database failure through ASGI and scheduler | Only trusted metadata reaches diagnostic sinks, N02. |
| S5 | A | Malformed connector dispatch/results | Validate before access, controlled response and zero writes, N03/R31. |
| S6 | A | Identifier limits through all create/reuse paths | PostgreSQL 422 and no writes at max+1, success at max, R05/R11. |
| S7 | A | Checkout with two keys and existing customer | Exactly intended payer upgraded or ambiguous purchase refused before charge, R02. |
| S8 | A | Status sequence including past due, pause, resume and replaced subscription | Only the current subscription controls effective quota, R19. |
| S9 | A | Unknown, duplicate and delayed events amid cancellation | No watermark poisoning, double grant or duplicate notice, R19/R44. |
| S10 | A | Cleanup versus reactivation on separate connections | Renewal-first retains data, cleanup-first yields tombstone and reconciliation, R14. |
| S11 | A | Key creation and rotation during cleanup | One tenant-serialized decision, no live sibling loses data, R14. |
| S12 | A | Two old cancelled siblings versus one entitled sibling | First tenant cleaned exactly once, second preserved, N05. |
| S13 | A | Historical PostgreSQL provider upgrade twice (SQLite advisory) | Stored linkage and tenant ownership preserved or explicitly quarantined, R23. |
| S14 | A | Cancelled/paid UTC day and month boundaries | Summary agrees with last permitted reservation and rejection, R18. |
| S20 | C | HTTP and connector verification on an older reviewer engine | Same category sync, learning and conservation, R01. |
| S21 | C | Connector and HTTP revision of structured data | Common lineage, actor, source identity, ordered corrections and structured content, R03/B6-02/B7-01. |
| S22 | C | Two first-domain/engine writes | Consistent retry or 409, no partial records, R04. |
| S23 | C | Concurrent reservations at 49 plus two requests | At most one new charge and score, billing counters agree, R24. |
| S24 | C | Two relabels plus verify on one predecessor | One successor, stable training, controlled conflict on PostgreSQL, R24. |
| S25 | C | Independent connector processes configure distinct projects | Both committed configs survive restart, R29. |
| S26 | C | Incorrect label corrected twice, including category reversion | Negative evidence persists until adjudication, R45. |
| S27 | C | Bulk approval, independent outcomes and a skipped item | Read stored action/outcome, learner trackers and counts, R13/R3-07. |
| S28 | B | Late signup after same-tab or cross-tab rotation | New credential still owns tab; abandoned signup cannot install a key, R3-01. |
| S29 | B | Rotation between real import chunks then restart | Only old owner has committed prefix; new owner has no file/draft or rows, R12/R3-02. |
| S30 | B | Domain switch with detail/search/bulk in flight, duplicated public IDs | Stale results cannot display, select or mutate the new project. Review navigation carries identifiers only, F7-01. |
| S31 | B | Tag draft during category save/verify and navigation | Edit is blocked or explicitly preserved; no silent loss, R3-03. |
| S32 | B | Incompatible JSON and failed lazy chunk | Scoped error, usable navigation, recovery after retry, R3-08. |

Each owner also runs existing affected tests. For parallel B/C integration, C owns S27 on the real B UI and C backend. Later prompts rerun inherited scenarios listed in §2 plus their feature-specific gates. A reviewer other than the author checks shared-file diffs, SQL lock order and a normal caller before a wave is promoted.

## 6. Timeline and critical path

| Phase | Elapsed working days | Work |
|---|---|---|
| Wave 1 | 0–3 | 00 |
| R1 | 3–3.5 | Harness review |
| Wave 2 | 3.5–9.5 | A |
| R2 | 9.5–10 | Billing, projects and access review |
| Wave 3 | 10–15 | B and C in parallel, last day integrated |
| R3 | 15–15.5 | B+C review |
| Wave 4 | 15.5–20.5 | D and E in parallel |
| R4 | 20.5–21 | Export, predictions and delivery review |
| Wave 5 | 21–25 | F |
| R5 | 25–25.5 | Full regression review |
| Wave 6 | 25.5–27 | 12 release |

Critical path: 00 → R1 → A → R2 → C (with B integration) → R3 → D/E → R4 → F → R5 → 12. Two engineering slots, approximately 33 engineer-days including reviews; parallel wave windows are elapsed budgets. Previous merged estimate: 37 engineer-days / 29 elapsed. PostgreSQL failures block promotion; SQLite compatibility runs in CI and reports divergences separately.

**Single-instance Railway release.** Before release, confirm a restorable pre-upgrade backup of the labeling DB and access to the existing legacy/config volume backup. This is a recovery prerequisite; a post-release backup cannot undo a bad migration. Agree on the restart window, inhibit cleanup during reconciliation and record the previous compatible image and schema version.

1. **Deploy.** Build the actual Dockerfile image, confirm SPA assets, dependencies, secrets and volume paths in staging, then deploy one Hobby instance.
2. **Run migration.** Use the existing entrypoint’s migration before readiness, once per deployment with repeat-safe schema inspection. Rehearse upgrade twice on a restored DB. Do not run competing migration processes.
3. **Verify.** Check domain/key/label/content counts, billing mapping, UTC quota, project isolation, old hash routes, public signup confirmation, signed test webhook, export and pending delivery recovery. Run a controlled checkout using sandbox/staging before production and inspect deployment health. If validation fails, hold deletes and external delivery, roll back to a schema-compatible image, preserve acknowledged writes and reconcile. Restore an earlier DB only under an explicit recovery decision.
4. **Back up.** After verification take a new database backup, record timestamp/schema/image and confirm restorability. Resume protected jobs only when entitlement and retention checks pass. A short restart is accepted at current scale.

## 7. P1 closure map

| ID | Failure | Launch class | Owner | Acceptance obligation |
|---|---|---|---|---|
| R02 | Customer overrides purchaser | BLOCKS LAUNCH | A | A two-key purchase upgrades only the recorded payer, or checkout refuses the ambiguity before billing. |
| R14 | Reactivation versus deletion | BLOCKS LAUNCH | A | Renewal, sibling issuance and cleanup serialize by tenant. Renewal-first preserves data and deletion-first leaves a terminal tombstone. |
| R19 | Subscription lifecycle gaps | BLOCKS LAUNCH | A | Provider status, checkout, account summary and scoring agree across replacement, replay and cancellation. |
| R23 | Historical provider mapping | BLOCKS LAUNCH | A | PostgreSQL upgrades preserve provider ownership and values, ambiguous records are quarantined. SQLite results are advisory. |
| N05 | Expired sibling retention | BLOCKS LAUNCH | A | Two expired siblings clean exactly once. A genuinely entitled sibling protects the tenant. |
| R08 | Unverified signup | BLOCKS LAUNCH | A | A single-use mailbox proof precedes issuance. Previously shared keys are rotated or revoked. |
| R09 | Unbounded report waiters | BLOCKS LAUNCH | A | Admission before multipart parsing bounds simultaneous bytes and waiters under overload and disconnect. |
| N02 | Driver diagnostics bypass value redaction | BLOCKS LAUNCH | A | Canaries from forced SQL failures are absent from server, worker and driver logs. |
| N03 | Malformed connector dispatch | BLOCKS LAUNCH | A | All dispatch inputs are validated before lookup, returning a documented result with no writes on invalid input. |
| R05 | Unbounded persisted IDs | BLOCKS LAUNCH | A | Path, body and connector-derived IDs get the same controlled boundary checks before persistence. |
| R3-01 | Late signup changes account | BLOCKS LAUNCH | B | Leaving signup or rotating identity prevents the old response changing storage, route or scope. |
| R3-02 | Prior account’s upload survives rotation | BLOCKS LAUNCH | B | Rotation discards file, analysis and drafts. Restart requires a new selection and cannot write old input. |
| R3-03 | Save Tags, category dirty state and conflict navigation | BLOCKS LAUNCH | B | All mutation paths share one lock. Dirty navigation requires a decision and no accepted edit silently disappears. |
| R3-08 | Invalid DTO crashes the app | BLOCKS LAUNCH | B | Runtime decoding and a recoverable route boundary preserve navigation on malformed JSON DTOs and chunk failures. |
| R01 | Connector uses stale reviewer engine | BLOCKS LAUNCH | C | Connector and HTTP verify synchronize categories and persist equivalent learning. |
| R03 | Connector revision loses content | BLOCKS LAUNCH | C | Both adapters preserve text, structured content, source IDs, predecessor, actor and timestamp. |
| R04 | First domain or engine creation races | BLOCKS LAUNCH | C | Competing creates converge or return a retryable conflict, with no partial writes. |
| R24 | SQLite row-lock assumptions | ACCEPTABLE RISK | v1.1 | SQLite advisory concurrency tests pass before production SQLite is supported. |
| R29 | Connector config lost update | BLOCKS LAUNCH | C | Two independent writers preserve both tenant/project configs across restart. |
| R45 | Revision erases negative evidence | BLOCKS LAUNCH | C | Changing or reverting category preserves latest verified evidence until a new human adjudication. |
| R13 / R3-07 | Bulk action becomes ground truth | BLOCKS LAUNCH | C | B’s queue and C’s server require independent truth for learning, including mixed outcomes and skipped labels. |
| R06 | Legacy decision and snapshot split | ACCEPTABLE RISK | v1.1 | One transaction commits decision and engine, with parity after interruption and retry. |
| R07 | Legacy plaintext credentials | ACCEPTABLE RISK | v1.1 | Only digests are authoritative and bearer values in retained backups have expired or been rotated. |
| R30 | Historical centroid-key collisions | ACCEPTABLE RISK | v1.1 | Historical keys are unambiguously converted, or affected owners explicitly resolve unrecoverable collisions. |
| B6-01 | Commit after response | CLOSED | 00 | Keep the commit-before-success contract on all writes. |
| B6-02 | Stale connector redelivery | BLOCKS LAUNCH | C | Source order and ambiguous updates reconcile without false learning. |
| B6-03 | Billing intake unbounded | BLOCKS LAUNCH | A | Bound bytes, time and concurrency while preserving signed bytes. |
| B7-01 | Connector task reassignment | BLOCKS LAUNCH | C | An established source task remains bound after inconsistent input. |
| F7-01 | Queue DTO in history | BLOCKS LAUNCH | B | Navigation and auto-next retain identifiers only. |

Release attaches evidence per ID. R06, R07, R30 and R24 remain owned by v1.1.
