# DLJ architecture redesign v2 — merged execution plan

**Executive summary**

Ship one project-based DLJ product by extending the existing labeling service and its React screens. The first deliverable is a runnable integration harness that freezes the current contracts and exposes the outstanding failures. The plan assigns 21 distinct P1s to launch gates and reserves three legacy JM findings for v1.1. Twelve merged prompts fit into seven waves over 28 working days with two engineering slots. The first paying customer can onboard after the product gates, PostgreSQL and SQLite checks, and single-instance Railway release rehearsal pass.

| Decision | Commitment |
|---|---|
| Execution authority | This document replaces **dlj_arch_redesign_v1.md** and **dlj_post_track2_design_v2.md**. Keep both as historical design references. Execute only the prompts below. |
| Launch scorecard | 21 BLOCKS LAUNCH: 5 at 02, 5 at 03, 4 at 04, 7 at 05. Three ACCEPTABLE RISK findings remain open until v1.1. Planning closes zero findings by itself. |
| Scope and estimate | All Post-Track 2 launch features. **38 engineer-days of effort, 28 elapsed working days** at two slots. The estimate assumes a small dataset and available billing/operations decision makers. |
| Deferred | Legacy JM store migration (R06, R07, R30) and the full volume/traffic cutover procedure. No launch customer should depend on the legacy JM decision API. |

## 1. P1 launch classification

The third-pass ledgers contain 20 backend and five frontend P1s. R13 and R3-07 describe the same ground-truth error. All 24 have a disposition below. “Close all” spans launch plus v1.1; the specific legacy deferral leaves **21 closures required at launch**.

**Baseline update for 00.** The table classifies the original failure and its launch impact. Later session entries DLJ-FIX-R3-BE/FE report fixes and targeted tests for several of these IDs. Import those tests and credit passing implementations; the counts above are acceptance obligations, not 21 new patches. In particular, current retention already locks across key changes and processes expired siblings. Reuse that protection during the tenant-guard migration. The health handler now checks capacity before reading UploadFile, so verify admission before framework multipart decoding as well. Bulk still needs a joint acceptance test: the current browser helper sends `verified_outcome` derived from action, while BulkVerifyRequest declares `outcome`. A green status or a field merely being present cannot establish that the reviewer supplied independent truth.

| ID | Failure | Launch class | Exposure and rationale |
|---|---|---|---|
| R02 | Customer overrides purchaser | BLOCKS LAUNCH | A real payment can upgrade the wrong key. Authentication alone does not identify the payer. |
| R14 | Reactivation versus deletion | BLOCKS LAUNCH | Cleanup can erase a paying tenant’s labels and engines. A single web instance still runs concurrent jobs. |
| R19 | Subscription lifecycle gaps | BLOCKS LAUNCH | Paused, past-due or replacement subscriptions can retain or lose paid capacity incorrectly. |
| R23 | Historical provider mapping | BLOCKS LAUNCH | Production PostgreSQL reduces the SQLite-specific exposure, but unverified ownership or lost provider links make imports and retention unsafe. |
| N05 | Expired sibling retention | BLOCKS LAUNCH | Two cancelled keys can keep each other and their data alive past the promised retention period. |
| R08 | Unverified signup | BLOCKS LAUNCH | The requester and an unrelated mailbox can receive the same credential. Rate limits do not prove ownership. |
| R09 | Unbounded report waiters | BLOCKS LAUNCH | Anonymous uploads share the Hobby process with paying users. The worker semaphore is acquired after buffering. |
| N02 | SQL values in outer logs | BLOCKS LAUNCH | Unhandled API or scheduler errors can expose customer content beyond the batch handler. |
| N03 | Malformed connector dispatch | BLOCKS LAUNCH | Invalid envelope types produce an unhandled failure on a supported integration. Service-token auth does not validate event shape. |
| R05 | Unbounded persisted IDs | BLOCKS LAUNCH | PostgreSQL can reject derived IDs that pass request validation and work in SQLite. |
| R3-01 | Late signup changes account | BLOCKS LAUNCH | A stale signup response can replace the key selected by a paying user. |
| R3-02 | Prior account’s upload survives rotation | BLOCKS LAUNCH | A stopped run can expose the previous customer’s file to the next account on a shared browser. |
| R3-03 | Review mutation discards edits | BLOCKS LAUNCH | A verify or category-save response can erase newly edited spans or tags. |
| R3-08 | Invalid DTO crashes the app | BLOCKS LAUNCH | A successful HTTP status with the wrong JSON shape can take down the paying user’s whole route tree. |
| R01 | Connector uses stale reviewer engine | BLOCKS LAUNCH | A known new category can break learning only on the connector path. |
| R03 | Connector revision loses content | BLOCKS LAUNCH | Current detail and export can lose attached evidence and revision provenance. |
| R04 | First domain or engine creation races | BLOCKS LAUNCH | Valid simultaneous writes can fail inconsistently and invite duplicate retries. |
| R24 | SQLite row-lock assumptions | BLOCKS LAUNCH | PG protects production row locks, but SQLite remains a supported migration/test lane; false parity hides quota and revision errors. |
| R29 | Connector config lost update | BLOCKS LAUNCH | A single worker reduces the race today. Shared config is already changing with project ownership; a DB upsert also removes future worker-count dependence. |
| R45 | Revision erases negative evidence | BLOCKS LAUNCH | A category change can improve apparent accuracy without new human evidence, affecting automation. |
| R13 / R3-07 | Bulk action becomes ground truth | BLOCKS LAUNCH | The current queue can train on agreement rather than correctness. This is one issue across two ledgers. |
| R06 | Legacy decision and snapshot split | ACCEPTABLE RISK | Failure can corrupt a legacy engine; the affected store is separate from paid DLJ and no external consumer is known. |
| R07 | Legacy plaintext credentials | ACCEPTABLE RISK | Disclosure of legacy storage or backups exposes usable JM keys. Separate authentication bounds direct DLJ access. |
| R30 | Historical centroid-key collisions | ACCEPTABLE RISK | Affected pairs share learning in old JM snapshots. New legacy domains reject pipe separators. |

## 2. Merged prompts

Use 00 for the standalone harness, absorbing Post-Track 2 task 01's baseline and fixtures. Preserve product IDs 02–12. This accounts for every numbered task in the checked-in product plan. The ten-prompt/21-day optimized baseline in the brief is a schedule comparison; the source document itself enumerates 01–12 and 30 engineer-days. Inherited redesign work maps P0→00, P1→03, P2→02 billing, P3→v1.1, P4→05, P5→04, P6→12. No parallel redesign backlog.

| Wave / prompt | Depends on | Days | Deliverable, structural ownership and schema (§4) | Exit gate (S numbers in §5) |
|---|---|---:|---|---|
| 1 / **00 Harness and contract freeze** | Current checkout | 4 | Stand up the real-app, dual-DB and browser lanes. Freeze old HTTP/hash/CSV contracts and proposed project DTOs. Ship all 27 retained scenario definitions, fixtures and baseline results. No production DDL or feature edits. | Harness controls pass; each executable known failure has an owning ID, expected assertion and detection of unexpected passes. New routes have contract cases ready to activate. Do not require unfixed behavior to pass on day four. |
| 2 / **02 Projects and billing** | 00 | 5 | Project CRUD over Domain.id, public aliases, status/versioned settings, archive/restore, canonical owner billing. Replace the old billing subsection with the FSM below. Own project/entitlement DDL, historical repair and 5 P1s. Owner-only until 03 authorization lands. | S7–14, repeat migration, unchanged ownership/engine/label counts, account/checkout/legacy owner adapters share limits, archived project cannot mutate. |
| 3 / **03 Identity, access and admission** | 02 | 4.5 | Typed ProjectAccess, roles, invitations, verified signup, bounded report admission, ID validation and safe logging. Own challenge, membership and invite DDL and 5 P1s. | S1–6; owner/admin/reviewer/annotator/revoked/foreign allow-deny matrix; expired and replayed invites; attempts to charge a member’s private account fail. |
| 4 / **04 Project UI and request ownership** | 03 | 3.5 | Project chooser/create, nested hash routes, team/invite/settings, immutable request context and guarded edits. Add explicit outcome UI to agreed 05 contract. No DDL. Own 4 P1s. | S28–32; two browser contexts, legacy deep links and checkout return. Cross-stack explicit bulk gate closes in 05 after integration. |
| 4 / **05 Shared writes and JSON import** | 03; integrate 04 before joint closure | 4.5 | One transaction service for project, existing labeling and connector adapters, typed content batch, replay, quota, verified evidence and config. Own receipt, lineage, actor and config DDL and 7 P1s. | S20–27 including real 04 UI for S27; old CSV still posts batches, invalid middle item rolls everything back, same replay scores/charges once, changed digest returns 409. |
| 5 / **06 Project export** | 04,05 | 3 | Project export from Queue and Settings, distinct from page CSV. JSONL, CSV and spaCy DocBin. Own export lease DDL. | Reuse S21,26; round-trip Unicode, null/false, filters and revisions; bounded snapshot, strict DocBin alignment, cancellation and staging RSS tests. |
| 5 / **08 Predictions** | 03,05 | 3 | Import, immutable model provenance, opt-in automation, metrics, human review and reopen. Own prediction DDL. | Reuse S20–24,26–27; cold start, gate demotion, named annotator threshold, replay, cap and rollback; machine approval never learns. |
| 6 / **09 Prediction review UI** | 04,08 | 2 | Queue badges/filter, original vs current detail, explicit assessment, model settings, audit/reopen, dashboard by source. No DDL. | Reuse S27,30–31; human correction follows current revision, machine-only counts remain distinct, correct keyboard/role behavior. |
| 6 / **07 Guide and downloadable client** | 05,06; 08 API for prediction example | 1.5 | Public hash guide, OpenAPI, working Python client for projects, upload, verify, prediction import and streaming export. No DDL. | Reuse S1,23; execute the published quickstart against real HTTP, including chunk replay and actionable quota/error responses. |
| 6 / **10 Outgoing webhooks** | 03,05,08 | 4 | Admin CRUD/test, durable transactional events, delivery worker, signed bodies, retries and egress controls. Own endpoint/event/delivery/attempt DDL. | Reuse S21,24,27; rollback emits nothing; exercise duplicate send, two workers, lease expiry, rotation, disabled destination and failed delivery. |
| 6 / **11 Integrations UI and operations** | 04,07,10 | 1.5 | Integrations settings, delivery health and attempt log, secret rotation, receiver guide and staging delivery. No new schema. | Reuse S28,30 for ownership; only admins manage secrets, signed event reaches receiver, restart recovers pending delivery. |
| 7 / **12 Railway release** | All preceding gates | 1.5 | Single-instance release procedure in §6. Validate actual image, recorded migration version and backups. No new DDL or traffic gateway. | All 27 retained scenarios pass at their required boundaries, product gates pass, three accepted risks signed off, paid checkout → project → review/export → signed delivery smoke. |

**Product contracts to implement**

- **02.** A project UUID is existing Domain.id; internal domain key and tenant remain unchanged. POST/GET /v1/projects, GET/PATCH/DELETE /v1/projects/{uuid}; DELETE archives. Scope every child lookup. PATCH uses settings_version/If-Match. Existing owner aliases and unclassified rows remain readable. A member's personal key identifies the actor; the owner pays. Before sharing a multi-key tenant, reconcile subscription, original trial start and matching UTC counters exactly once. Quarantine ambiguous ownership and preserve private access.
- **02 billing.** Implement one transition function and one effective-entitlement resolver for checkout, quota, account, scheduler and connector. Verified signup→trial, clock→trial_expired, verified purchase→active, effective pause/past_due→restricted, valid resumed/activated→active, effective cancellation→cancelled at 50/day, cutoff after 30 days→cleaned_up terminal. Keep existing counters and paid tier history. Confirm the proposed past-due scoring hold with billing owner before rollout. Bind purchaser, payer and provider transaction before granting capacity. Authenticate events, deduplicate by committed receipt, audit unknown/stale events without advancing the applied watermark, reconcile ties and replacements. Require a known tier only for paid grants. Tenant guard → sorted keys → domain → labels → engine is the common lock order. Serialize key creation, renewal and deletion, recheck all siblings, outstanding purchases and provider holds before deleting. On SQLite reserve the writer before relevant reads and use conditional updates/retry. Notification intent commits with the transition.
- **03.** Reviewer may verify/import/export; annotator may classify/edit; admins manage settings/team; owners alone grant admin, archive and bind billing. Return 401/403/404 for invalid credential, insufficient visible role and inaccessible project respectively. Preserve actor and payer separately across legacy *labeling* routes. Invites use a digest, 48-hour expiry, recipient proof, one-time consumption and revocation/recheck of inviter authority. Signup uses a separate short-lived mailbox challenge and issues a bearer only after confirmation commits. Migrate the old signup surface and rotate shared historical keys before closure. Limit anonymous uploads before multipart decoding, release capacity on disconnect, validate all derived IDs and sanitize outer framework, SQL and job errors.
- **04/05.** Capture credential, account generation, project UUID/public alias, operation ID and AbortSignal once per operation. Abort on rotation/unmount or project switch; verify ownership before dispatch and before all post-await storage/UI effects. Clear files, drafts, selection, receipts and caches when identity changes. Preserve old hash links, free anonymous report and sample. Keep global account checkout separate from project settings. Expose project-scoped adapters for queue, detail, bulk, verify, sample, tasks, revision/content, dashboard, autonomy, IAA and guidelines. Preserve bare pending arrays and X-Total-Count. POST project labels/batch accepts 1–100 items, 32 KiB UTF-8 text, typed content and idempotency key. Lock predecessor/engine and preserve label content, actor and lineage on every adapter. Resolve concurrency before learning. Latest verified evidence stays in accuracy until human re-adjudication. Bulk truth is per item or explicitly homogeneous; unobserved truth cannot train. Retire legacy implicit writes after callers migrate. Preserve historical bulk quota and partial-skip behavior.
- **06/07.** GET project export emits one current revision per logical item with root/current IDs, source, full text, category, annotator, action, true/false/null outcome, scores, UTC times, content/spans/tags/image, review state and optional factors. Filter by review status, category, annotator and UTC date interval. Stream JSONL/escaped CSV in a single snapshot, pages of 500, two slots/project, five-minute deadline. Preflight English tokenizer DocBin alignment and human span adjudication; cap at 5,000 documents or 16 MiB text and verify on Hobby. Browser fallback limited to 32 MiB. Guide at /#/docs, Swagger at /docs, schema at /openapi.json, client at /dlj_client.py. Client reports committed chunks, retries with the same key, and saves downloads only after completion.
- **08/09.** POST project predictions (1–100), GET stats, POST reopen/review with expected revision and decision version. Separate model confidence from scored confidence. Automation defaults off; require model floor (default .95), approve recommendation, autonomous tier, passing conservation and named-annotator eligibility. Persist the original input and decision. Machine approval never supplies a human outcome. Charge only new scored imports; human verification/reopen/replay add no scoring charge apart from existing bulk policy. Preserve machine approval history, unknown human assessments and explicit review of spans.
- **10/11.** Register project webhooks, test sends and paginated deliveries. Emit label.verified, prediction.auto_approved and webhook.test in the business transaction. Persist canonical bytes, HMAC-SHA256 of timestamp + period + body, event ID and key version. Disclose signing secret once. Five endpoints/project, ten tests/endpoint/hour. Validate public HTTPS at connection time, disable redirects, encrypt secrets. Four sends maximum with immediate/10/60/300-second schedule, 10-second timeout, 30-second fenced lease, one send/endpoint and four concurrent sends. Rotate/archive cancels stale pending/leased work; receiver deduplicates. Retain terminal metadata 30 days. No source text, bearer tokens or raw response bodies in logs.

## 3. Deferred to v1.1

| Item | Reason and mitigation | Trigger and owner | Future effort |
|---|---|---|---|
| R06 · JM split commits | Only the legacy decision log/engine store is affected. Existing duplicate-learn checks do not make two commits atomic. Keep paying customers on DLJ routes, restrict legacy writes to identified test consumers, monitor failures and preserve a restorable snapshot. | Service owner reopens before first external JM write dependency, increased concurrency or any state/log mismatch. | ~3 engineer-days |
| R07 · plaintext JM bearer identities | Legacy and DLJ use separate credentials/stores. Raw JM credentials remain usable if the volume or its backups are disclosed. Restrict volume/backup access, omit keys from telemetry, use disposable JM test credentials and rotate them on exposure. | Security owner reopens on any external JM account, increased backup access or suspected disclosure. | ~3 engineer-days |
| R30 · legacy centroid collisions | New domain validation already rejects pipe-bearing categories/actions. Inventory historical configs, quarantine ambiguous engines from learning and keep them out of DLJ. | Engine owner reopens when a historical collision is found or an old snapshot needs production use. | ~2 engineer-days |
| Legacy migration and reconciliation | No known production client beyond scripts is the planning assumption. Verify with redacted route counts before launch; absence of consumers is not proven by repo search. Keep the distinct legacy API outside DLJ membership and billing. | Platform owner implements Option B from v1 §2, including digest mapping, atomic decision storage and migration rehearsal, if any trigger above fires. | ~2 shared days **plus** the three rows above = **10 total** |
| Full blue/green handoff | Hobby deployment has one instance and accepts a brief restart. The existing entrypoint migrates before Uvicorn. Operational acceptance requires a tested restore and a release window; a DB backup does not eliminate downtime. | Operations lead reopens before a no-downtime SLA, multi-replica rollout, active legacy traffic or migration longer than the agreed window. Historical reference: **dlj_arch_redesign_v1.md §6, Railway rollout, cutover and rollback**. | Allow up to 4 engineer-days at that time; re-estimate from traffic and data size. |

Accepted means risk is still present. The launch owner records the consumer check, controls, trigger and next review date. If a paying workflow needs legacy JM, its affected P1s become blockers before onboarding that customer.

## 4. Consolidated schema ledger

The blocks are **forward and inverse definitions** for migration authors. The inverse statements are a separate downgrade, never executed as part of upgrade. PostgreSQL uses UTC timestamptz and application-generated UUIDs. SQLite uses the existing ORM UUID representation, JSON encoding, checked text enums, UTC normalization and FK enforcement. Use versioned catalog checks, one migration runner, fresh and historical fixtures, and a second upgrade run. On SQLite use an FK-safe staged rebuild when an ALTER is unsupported; compare values and child counts and run foreign_key_check before commit. No legacy JM tables, credential audience discriminator or volume migration enter this release.

### 02 · Projects, entitlement, historical repair

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

### 03 · Challenge, team and actor authorization

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

### 05 · Shared write contract and revision history

Enables R01/R03/R04/R24/R29/R45 and R13 with 04. Existing revision columns remain authoritative. Preflight duplicate predecessor links; resolve within project before enabling the unique index. Existing rows may have unknown key attribution. Backfill lineage only from unambiguous links. Pause config writes for one fenced JSON-file import, compare all project keys, switch reader and writer together, then retain file read-only.

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

### 06 · Export slots

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

### 08 · Prediction provenance

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

### 10 · Outbound delivery

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

**00, 04, 07, 09, 11, 12 add no tables or columns.** Apply inverses in reverse dependency order on a restored copy. For production application rollback prefer keeping additive schema and data. Update retention deletion order for restrictive children as each table ships, including project_request before domains. Keep immutable billing audit on key deactivation.

## 5. Integration scenarios and release evidence

Ship the harness at 00 **before any production change**. Keep v1 scenario numbers stable. Remove only S15–19 (legacy import/auth replay, split commit, concurrent legacy learn, historical centroid conversion, fenced legacy cutover). Keep the existing legacy wire smoke suite. **27 scenarios remain**; parametrized dialects, timing orders and the product acceptance gates in §2 are additional executions.

Use pytest-asyncio with a PostgreSQL schema per scenario shared by its independent connections, plus SQLite shared-file tests with FK enforcement. Assert actual dialect and connection identity. Coordinate two writers at transaction boundaries with timed barriers and inspect committed results from a third session. Use the real mounted service and two browser contexts for identity/project changes. Stub clocks, mail and provider transport; exercise actual auth, quota, transactions, migrations and learner. At 00 freeze a per-case owner and baseline; distinguish a failing behavioral assertion from infrastructure or missing-route errors. At its assigned merge gate each scenario must be active and green. No known-failure waiver survives 12 except the explicitly removed legacy scenarios.

| Scenario | Accountable prompt | Boundary exercised | Acceptance oracle |
|---|---|---|---|
| S1 | 03 | New signup and mismatched mailbox | Only a consumed mailbox proof receives an active key, R08. |
| S2 | 03 | Concurrent proof consumption and mail failure | At most one credential, no precommit delivery, R08. |
| S3 | 03 | Concurrent anonymous uploads at admission limit | Early refusal before multipart buffering, measured total memory/queue depth remains bounded, R09. |
| S4 | 03 | Forced unhandled database failure through ASGI and scheduler | Captured server, worker and SQL logs contain no sentinel values, N02. |
| S5 | 03 | Malformed connector dispatch/results | Validate before access, controlled response and zero writes, N03/R31. |
| S6 | 03 | Identifier limits through all create/reuse paths | Same 422 and no writes on both dialects at max+1, success at max, R05/R11. |
| S7 | 02 | Checkout with two keys and existing customer | Exactly intended payer upgraded or ambiguous purchase refused before charge, R02. |
| S8 | 02 | Status sequence including past due, pause, resume and replaced subscription | Only the current subscription controls effective quota, R19. |
| S9 | 02 | Unknown, duplicate and delayed events amid cancellation | No watermark poisoning, double grant or duplicate notice, R19/R44. |
| S10 | 02 | Cleanup versus reactivation on separate connections | Renewal-first retains data, cleanup-first yields tombstone and reconciliation, R14. |
| S11 | 02 | Key creation and rotation during cleanup | One tenant-serialized decision, no live sibling loses data, R14. |
| S12 | 02 | Two old cancelled siblings versus one entitled sibling | First tenant cleaned exactly once, second preserved, N05. |
| S13 | 02 | Dual-dialect historical provider upgrade twice | Stored linkage and tenant ownership preserved or explicitly quarantined, R23. |
| S14 | 02 | Cancelled/paid UTC day and month boundaries | Summary agrees with last permitted reservation and rejection, R18. |
| S20 | 05 | HTTP and connector verification on an older reviewer engine | Same category sync, learning and conservation, R01. |
| S21 | 05 | Connector and HTTP revision of structured data | Common lineage, actor, text/NER/tags/image and current pointer, R03. |
| S22 | 05 | Two first-domain/engine writes | Consistent retry or 409, no partial records, R04. |
| S23 | 05 | Concurrent reservations at 49 plus two requests | At most one new charge and score, billing counters agree, R24. |
| S24 | 05 | Two relabels plus verify on one predecessor | One successor, stable training, controlled conflict on both dialects, R24. |
| S25 | 05 | Independent connector processes configure distinct projects | Both committed configs survive restart, R29. |
| S26 | 05 | Incorrect label corrected twice, including category reversion | Negative evidence persists until adjudication, R45. |
| S27 | 05 | Bulk approval, independent outcomes and a skipped item | Read stored action/outcome, learner trackers and counts, R13/R3-07. |
| S28 | 04 | Late signup after same-tab or cross-tab rotation | New credential still owns tab; abandoned signup cannot install a key, R3-01. |
| S29 | 04 | Rotation between real import chunks then restart | Only old owner has committed prefix; new owner has no file/draft or rows, R12/R3-02. |
| S30 | 04 | Domain switch with detail/search/bulk in flight, duplicated public IDs | Stale results cannot display, select or mutate the new project, F/P1.1, F/P1.4, S2.2. |
| S31 | 04 | Tag draft during category save/verify and navigation | Edit is blocked or explicitly preserved; no silent loss, R3-03. |
| S32 | 04 | Incompatible JSON and failed lazy chunk | Scoped error, usable navigation, recovery after retry, R3-08. |

Each owner also runs existing affected tests. For parallel 04/05 integration, merge backend and browser contract changes into one release candidate before signing off S27. Later prompts rerun inherited scenarios listed in §2 plus their feature-specific gates. A reviewer other than the author checks shared-file diffs, SQL lock order and a normal caller before a wave is promoted.

## 6. Timeline and critical path

Elapsed days below are working days counted from zero. A slot includes implementation, focused tests and review fixes. Sequential work within a slot is shown in order. The second slot is available for review or triage during serial waves; idle capacity has no assumed throughput.

| Wave | Elapsed interval | Slot A | Slot B | Exit |
|---|---:|---|---|---|
| 1 | 0–4 | 00 harness and baseline (4) | Review baseline | Runnable harness published |
| 2 | 4–9 | 02 projects + FSM (5) | Review billing/migration | One payer and tested retention |
| 3 | 9–13.5 | 03 access + admission (4.5) | Review identity/roles | Team, signup and limits ready |
| 4 | 13.5–18 | 05 shared writes (4.5) | 04 project UI (3.5), then integrate | Shared contract and real bulk UI pass |
| 5 | 18–21 | 08 predictions (3) | 06 export (3) | Both APIs usable |
| 6 | 21–26.5 | 10 webhook backend (4), then 11 integrations (1.5) | 09 review UI (2), then 07 guide/client (1.5) | 11 starts at day 25 with 07 and 10 complete |
| 7 | 26.5–28 | 12 release (1.5) | Independent release review | Paying-customer gate |

**Critical path:** 00 → 02 → 03 → 05 → 08 → 10 → 11 → 12 = **28 working days**. Export and predictions finish together, but the guide has half a day of slack before 11. Total assigned prompt effort is 38 engineer-days across two slots. Day 29 is available for contingency while staying below 30 elapsed days. The estimate assumes the existing features and fixtures are reused, no material historical billing conflicts in the launch cohort, and both engineers have access to staging. An unresolved destructive migration or identity failure blocks launch even if the date slips.

| Program | Planning measure | What it delivers |
|---|---|---|
| Post-Track 2 alone | ~21 elapsed days per optimized baseline supplied; checked-in design estimates 30 engineer-days | Product features with no explicit structural P1 closure program |
| Redesign v1 alone | 47 engineer-days; previously estimated 24–30 elapsed days with three engineers | Structural redesign without the full product feature set |
| **Merged** | **38 engineer-days / 28 elapsed working days with two slots** | Full launch feature set, 21 structural closures and 3 documented v1.1 risks |

**Single-instance Railway release.** Before release, confirm a restorable pre-upgrade backup of the labeling DB and access to the existing legacy/config volume backup. This is a recovery prerequisite; a post-release backup cannot undo a bad migration. Agree on the restart window, inhibit cleanup during reconciliation and record the previous compatible image and schema version.

1. **Deploy.** Build the actual Dockerfile image, confirm SPA assets, dependencies, secrets and volume paths in staging, then deploy one Hobby instance.
2. **Run migration.** Use the existing entrypoint’s migration before readiness, once per deployment with repeat-safe schema inspection. Rehearse upgrade twice on a restored DB. Do not run competing migration processes.
3. **Verify.** Check domain/key/label/content counts, billing mapping, UTC quota, project isolation, old hash routes, public signup confirmation, signed test webhook, export and pending delivery recovery. Run a controlled checkout using sandbox/staging before production and inspect deployment health. If validation fails, hold deletes and external delivery, roll back to a schema-compatible image, preserve acknowledged writes and reconcile. Restore an earlier DB only under an explicit recovery decision.
4. **Back up.** After verification take a new database backup, record timestamp/schema/image and confirm restorability. Resume protected jobs only when entitlement and retention checks pass. A short restart is accepted at current scale.

## 7. Updated P1 closure map

| P1 ID | Description | Launch class | Merged prompt | Closes when |
|---|---|---|---|---|
| R02 | Customer overrides purchaser | BLOCKS LAUNCH | 02 | A two-key purchase upgrades only the recorded payer, or checkout refuses the ambiguity before billing. |
| R14 | Reactivation versus deletion | BLOCKS LAUNCH | 02 | Renewal, sibling issuance and cleanup serialize by tenant. Renewal-first preserves data and deletion-first leaves a terminal tombstone. |
| R19 | Subscription lifecycle gaps | BLOCKS LAUNCH | 02 | Provider status, checkout, account summary and scoring agree across replacement, replay and cancellation. |
| R23 | Historical provider mapping | BLOCKS LAUNCH | 02 | Both migration lanes preserve verified historical values and owners. Unattributable tenants remain private, protected and held from destructive cleanup until reconciled. |
| N05 | Expired sibling retention | BLOCKS LAUNCH | 02 | Two expired siblings clean exactly once. A genuinely entitled sibling protects the tenant. |
| R08 | Unverified signup | BLOCKS LAUNCH | 03 | A single-use mailbox proof precedes issuance. Previously shared keys are rotated or revoked. |
| R09 | Unbounded report waiters | BLOCKS LAUNCH | 03 | Admission before multipart parsing bounds simultaneous bytes and waiters under overload and disconnect. |
| N02 | SQL values in outer logs | BLOCKS LAUNCH | 03 | Canaries from forced SQL failures are absent from server, worker and driver logs. |
| N03 | Malformed connector dispatch | BLOCKS LAUNCH | 03 | All dispatch inputs are validated before lookup, returning a documented result with no writes on invalid input. |
| R05 | Unbounded persisted IDs | BLOCKS LAUNCH | 03 | Path, body and connector-derived IDs get the same controlled boundary checks before persistence. |
| R3-01 | Late signup changes account | BLOCKS LAUNCH | 04 | Leaving signup or rotating identity prevents the old response changing storage, route or scope. |
| R3-02 | Prior account’s upload survives rotation | BLOCKS LAUNCH | 04 | Rotation discards file, analysis and drafts. Restart requires a new selection and cannot write old input. |
| R3-03 | Review mutation discards edits | BLOCKS LAUNCH | 04 | All mutation paths share one lock. Dirty navigation requires a decision and no accepted edit silently disappears. |
| R3-08 | Invalid DTO crashes the app | BLOCKS LAUNCH | 04 | Runtime decoding and a recoverable route boundary preserve navigation on malformed JSON DTOs and chunk failures. |
| R01 | Connector uses stale reviewer engine | BLOCKS LAUNCH | 05 | Connector and HTTP verify synchronize categories and persist equivalent learning. |
| R03 | Connector revision loses content | BLOCKS LAUNCH | 05 | Both adapters preserve text, structured content, source IDs, predecessor, actor and timestamp. |
| R04 | First domain or engine creation races | BLOCKS LAUNCH | 05 | Competing creates converge or return a retryable conflict, with no partial writes. |
| R24 | SQLite row-lock assumptions | BLOCKS LAUNCH | 05 | Two independent connections conserve quota and produce one valid successor on both dialects. |
| R29 | Connector config lost update | BLOCKS LAUNCH | 05 | Two independent writers preserve both tenant/project configs across restart. |
| R45 | Revision erases negative evidence | BLOCKS LAUNCH | 05 | Changing or reverting category preserves latest verified evidence until a new human adjudication. |
| R13 / R3-07 | Bulk action becomes ground truth | BLOCKS LAUNCH | 05 | 04’s queue and 05’s server require independent truth for learning, including mixed outcomes and skipped labels. |
| R06 | Legacy decision and snapshot split | ACCEPTABLE RISK | v1.1 | One transaction commits decision and engine, with parity after interruption and retry. |
| R07 | Legacy plaintext credentials | ACCEPTABLE RISK | v1.1 | Only digests are authoritative and bearer values in retained backups have expired or been rotated. |
| R30 | Historical centroid-key collisions | ACCEPTABLE RISK | v1.1 | Historical keys are unambiguously converted, or affected owners explicitly resolve unrecoverable collisions. |

The release record must carry the result and evidence link for each blocker. Accepting R06, R07 and R30 records ownership and a trigger; it does not mark them fixed.
