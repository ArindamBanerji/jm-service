# DLJ Product Design

**Version:** v1 (consolidated)  
**Date:** 2026-11-26  
**Status:** Authoritative product design — single source of truth

DLJ helps labeling teams decide which judgments need human review, record what the reviewer actually observed, and measure how that evidence changes the next decision. For current integrations use the schema in §3 and the mounted route catalog in §4. For the next product increment use the strict-modality contracts in §§3–5, 8 and 10 and the MM-01–07 execution gates in §14.

**How to read this specification.** ✅ Shipped means implemented in the checkout with completion evidence. ⏳ In pipeline denotes integration or operational verification outstanding. **Designed** specifies approved future behavior. **Roadmap** identifies a conditional investment. Historical acceptance records explain the origin of a constraint or test and have no authority over the current wire catalog. This distinction matters for labels: a legacy typed image row works today, while creating a project that enforces image inputs is designed. All release counts below are recorded evidence, not results of a new regression run.

[1. Product Overview](#chapter-1) · [2. Architecture](#chapter-2) · [3. Data Model](#chapter-3) · [4. API Contract](#chapter-4) · [5. Frontend](#chapter-5) · [6. Quality Engine Integration](#chapter-6) · [7. Predictions and Automation](#chapter-7) · [8. Export and Integration](#chapter-8) · [9. Billing and Access](#chapter-9) · [10. Multi-Modality](#chapter-10) · [11. Analytics](#chapter-11) · [12. Quality of Life](#chapter-12) · [13. Deployment](#chapter-13) · [14. Test Strategy](#chapter-14) · [15. Design Scenarios](#chapter-15) · [16. Gaps and Open Questions](#chapter-16)

<a id="chapter-1"></a>

## 1. Product Overview

✅ **Shipped.** A labeling lead creates a project, invites annotators or reviewers, imports work with numeric factors and a proposed category, and reviews a ranked queue. Reviewers can classify unscored text, correct a revision, and record an observed outcome. A data engineer can import model outputs, export a consistent training set and subscribe an integration to verified transitions. An evaluator can try the public CSV health report without creating an account. Each path measures a different thing: confidence is a model score, verification is human evidence, and agreement measures consistency between annotators.

| Plan displayed by the application | Price shown | Capacity |
|---|---:|---|
| Trial | Free for 14 days | 50 daily |
| Starter | $99/month | 10,000 monthly |
| Professional | $299/month | 100,000 monthly |
| Business | $799/month | 1,000,000 monthly |
| Scale | Custom | Unlimited monthly |

These are the values in `Pricing.tsx` and `trial_guard.py`; provider prices are selected using the deployment's Paddle mapping. Enterprise is also recognized internally as uncapped. There is no corresponding Enterprise price on that screen. Autonomy tiers (§6) are earned by human evidence and are independent of subscription tiers (§9). The competitive comparison below is attributed to the source review and makes no current market-share or exclusivity claim.

<a id="anno-2"></a>

### Roadmap · Competitive landscape

| Product | Documented comparison | Implication for DLJ |
|---|---|---|
| Label Studio | Its NER template supports overlapping spans, and annotations can be exported. [NER template](https://labelstud.io/templates/named_entity) · [Export](https://labelstud.io/guide/export) | Start with readable text and explicit offset semantics. Overlap support and template authoring would broaden the editor substantially. |
| Labelbox | Its text annotation import guide defines text entities and classifications. [Text annotations](https://docs.labelbox.com/horizon/developer-guides/import-text-annotations) | Interchange needs both the source string and the label geometry. An approve/reject action alone cannot reconstruct either. |
| Cleanlab Studio | Multi-label curation ranks suspected issues, suggests labels, supports correction and export for image, text and tabular data. [Multi-label workflow](https://help.cleanlab.ai/studio/tutorials/cleanlab-studio-web/multilabel/) | DLJ currently ranks pending decisions by confidence. Its chart measures the fraction of human-verified labels marked correct, not issue-detection precision or a controlled comparison with Cleanlab. |
| Encord | Its document editor supports PDF regions, text attributes and classifications. [Document editor](https://docs.encord.com/platform-documentation/Annotate/annotate-label-editor/annotate-documents) | PDF geometry and plain-text character spans require different representations. |
| DLJ at comparison date | Domain-scoped queue, profiles, gate, conditional inversion alert, verify-and-learn path and anonymous report. At the comparison date native authoring was absent; see the current capability matrix in Chapter 10. | Differentiate through evidence gathered during review. Show a real verified observation before promising compounding. |

The earlier comparison’s checkmarks for bulk workflows, plan availability, analytics equivalence, collaboration, media coverage and universal competitive absences lack like-for-like evidence. Treat these as unverified across editions. The sources above support the named capabilities. They do not establish exclusivity of DLJ’s gate, free report or learning loop.

<a id="chapter-2"></a>

## 2. Architecture

✅ **Shipped · service boundaries.** `jm_service.py` assembles the FastAPI app. Most Python modules are at repository root; `backend/static/` contains the downloadable SDK. PostgreSQL stores DLJ tenants' keys, projects, revision chains, receipts, predictions, exports, notices and delivery jobs. The original JM API uses a separate SQLite database and separate keys. Similar URL prefixes do not grant access across these stores.

```text
React hash SPA / Python SDK / project integrations
  → FastAPI router → credential and input checks → actor + project + payer
  → tenant guard → ordered keys → domain/member → ordered labels → engine
  → one commit for domain writes, receipts and outbound events → response
Paddle → authenticated billing intake → entitlement transition / notices
Label Studio → connector token and account binding → shared score/revision/verify services
Scheduled work → retention, lifecycle mail and durable delivery → provider/receiver
Legacy JM client → legacy credential lookup → SQLite domain snapshot and decision log
```

The shared write transaction is the durability boundary. Reads and presentation use separate projections; downloads hold a read snapshot and a fenced slot. Requests carry account generation, project UUID or public alias, operation ID and AbortSignal in the browser. Verify ownership before dispatch and after awaits. The frozen engine contract is detailed in §6; the locked rollout and recovery contract in §13.

**Wave contract and acceptance intent**

- **A projects.** A project UUID is existing Domain.id; internal domain key and tenant remain unchanged. POST/GET /v1/projects, GET/PATCH/DELETE /v1/projects/{uuid}; DELETE archives. Scope every child lookup. PATCH uses settings_version/If-Match. Existing owner aliases and unclassified rows remain readable. A member's personal key identifies the actor; the owner pays. Before sharing a multi-key tenant, reconcile subscription, original trial start and matching UTC counters exactly once. Quarantine ambiguous ownership and preserve private access.

<a id="mm-1"></a>

### ✅ Shipped baseline / Designed extensions · Service boundaries for modality support

| Boundary | Current implementation | Design consequence |
|---|---|---|
| Project identity & access | `projects_router.py` implements `ProjectCreate`, `create_project`, `list_projects`, `get_project`, `ProjectPatch`, `ProjectSettings` and `update_settings`. `Domain.id` is the project UUID. `Domain.domain_id` is the scoped string used by labels. A public alias is resolved within an account. | Extend the existing project DTOs. Select by authorized project, then use its scoped key for label queries. A matching public alias is insufficient. |
| Revision content | In `db/models.py`, `LabelLog.text` holds text; `LabelContent.label_log_id` is a unique cascading FK to the label revision UUID. `LabelContent` already stores `image_url`, `spans_json`, `tags_json` and an item discriminator. `copy_label_content` in `db/repository.py` copies them to a successor. | One media source per revision. Preserve existing text, typed content, audit attribution and prediction provenance. A project modality and an item discriminator have different meanings. |
| Upload | `labeling_router.py:project_import_batch` accepts a typed `ProjectImportBatch`; `project_import_one` wraps it. Bulk import currently calls `_ingest` before checking all content. Root-level `auth.py` also validates certain bodies. | Validate cheap shape and bounded input first. Validate all items against the locked project before charging or scoring any. Normalize once for request identity and storage. |
| Engine | `db/repository.py:score_and_persist` calls `JudgmentMemoryEngine.score(factors, category)`. The frozen `jm_core.py` has no `item_text` source field. Learning uses the stored decision ID, actual action, agreement and explicit outcome. Project/annotator select the engine; timestamps and source content belong to the surrounding application. | Supply the same configured numeric factors for every modality. Existing text-task convenience can synthesize neutral 0.5 factors. Do not call it to infer image difficulty or use caption length, URL length, resolution, pixels or spans as inputs. |
| Review | React hash routes select the project in `App.tsx`. `DomainContext` currently holds identifiers. `ScoredQueue` renders pending/smart summaries. `ReviewCard` already dispatches to `TextViewer`, `ImageViewer`, `NEREditor`, `TagSelector` and `CategorySelector`. | Extend the existing detail and editor paths. Fetch private content only on demand using the captured account/project context. |
| Export & events | `labeling_router.py:_export_rows` yields current revisions; `export_project` spools the selected encoding before streaming. Existing exports already include nested `content.image_url`. `db.repository.record_webhook_event` persists a canonical signed-delivery envelope in the transition transaction. | Preserve snapshots, export leases, nested DTOs and exact bytes of historical events. Add metadata to the appropriate representations only. |

**Engine invariant.** Verify SHA-256 `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09` for root `jm_core.py` before and after each prompt. Compare confidence, recommendation, distances, conservation and human-learning tracker deltas with identical initial state and numeric inputs. Generated decision IDs and timestamps are opaque.

<a id="chapter-3"></a>

## 3. Data Model

✅ **Shipped · PostgreSQL dictionary.** The following definitions were compiled from the 26 mapped tables in `db/models.py` using the PostgreSQL dialect. They describe the checkout's model, not a proposed bootstrap script. Named indexes are shown separately. SQL defaults apply on the server; additional SQLAlchemy insert defaults are enumerated per table. Application-only checks and transaction rules belong to §§4, 7–9. The historical upgrade/inverse record later in this chapter is for migration reasoning; use the dictionary for current names and nullability.

The most important distinction is between the public project UUID, public alias and internal tenant-scoped domain string. LabelLog records a decision or revision; LabelContent owns optional typed content per revision; Prediction links original and current revision IDs. ApiKey identifies an actor while ProjectBillingOwner identifies the payer. A webhook event can own multiple independent deliveries, each with attempts. The separate JM SQLite schema and the planned modality extension are explicitly labeled below.

### ✅ Annotator · `annotators`

```sql
CREATE TABLE annotators (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  domain_id VARCHAR(200) NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  annotator_id VARCHAR(200) NOT NULL, 
  label_count INTEGER NOT NULL, 
  last_active TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_annotator_domain_external UNIQUE (domain_id, annotator_id), 
  FOREIGN KEY(domain_id) REFERENCES domains (domain_id)
);
CREATE INDEX ix_annotators_domain_id ON annotators (domain_id);
CREATE INDEX ix_annotators_tenant_id ON annotators (tenant_id);
```

ORM insert defaults: `id=uuid4`, `tenant_id=`, `label_count=0`.

### ✅ ApiKey · `api_keys`

```sql
CREATE TABLE api_keys (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  key_hash VARCHAR(64) NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  tenant_name VARCHAR(200) NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  is_active BOOLEAN NOT NULL, 
  tier VARCHAR(20) DEFAULT 'trial' NOT NULL, 
  subscription_state subscription_lifecycle, 
  state_version BIGINT DEFAULT 0 NOT NULL, 
  paddle_customer_id VARCHAR(200), 
  paddle_subscription_id VARCHAR(200), 
  paddle_event_id VARCHAR(200), 
  paddle_event_occurred_at TIMESTAMP WITH TIME ZONE, 
  contact_email VARCHAR(200), 
  signup_email VARCHAR(200), 
  signup_reconciliation_reference VARCHAR(200), 
  email_verified_at TIMESTAMP WITH TIME ZONE, 
  reproof_required BOOLEAN DEFAULT false NOT NULL, 
  trial_expiring_email_sent_at TIMESTAMP WITH TIME ZONE, 
  trial_expired_email_sent_at TIMESTAMP WITH TIME ZONE, 
  cancelled_at TIMESTAMP WITH TIME ZONE, 
  labels_this_month INTEGER DEFAULT 0 NOT NULL, 
  labels_month_key VARCHAR(7) DEFAULT '' NOT NULL, 
  labels_today INTEGER DEFAULT 0 NOT NULL, 
  labels_day_key VARCHAR(10) DEFAULT '' NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_key_owner UNIQUE (tenant_id, id)
);
CREATE UNIQUE INDEX ix_api_keys_key_hash ON api_keys (key_hash);
CREATE INDEX ix_api_keys_tenant_id ON api_keys (tenant_id);
CREATE UNIQUE INDEX uq_api_keys_contact_email ON api_keys (lower(contact_email)) WHERE contact_email IS NOT NULL;
CREATE UNIQUE INDEX uq_api_keys_paddle_customer_id ON api_keys (paddle_customer_id) WHERE paddle_customer_id IS NOT NULL;
CREATE UNIQUE INDEX uq_api_keys_signup_email ON api_keys (lower(signup_email)) WHERE signup_email IS NOT NULL;
```

ORM insert defaults: `id=uuid4`, `is_active=True`, `tier=trial`, `labels_this_month=0`, `labels_month_key=`, `labels_today=0`, `labels_day_key=`.

### ✅ CheckoutIntent · `checkout_intent`

```sql
CREATE TABLE checkout_intent (
  id UUID NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  purchaser UUID NOT NULL, 
  payer UUID NOT NULL, 
  tier VARCHAR(20) NOT NULL, 
  transaction_id VARCHAR(200), 
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  consumed_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (id), 
  FOREIGN KEY(tenant_id, purchaser) REFERENCES api_keys (tenant_id, id), 
  FOREIGN KEY(tenant_id, payer) REFERENCES api_keys (tenant_id, id), 
  UNIQUE (transaction_id)
);
```

ORM insert defaults: `id=uuid4`.

### ✅ ConnectorConfigRow · `connector_config`

```sql
CREATE TABLE connector_config (
  tenant_id VARCHAR(200) NOT NULL, 
  project_id VARCHAR(200) NOT NULL, 
  config_json JSON NOT NULL, 
  version BIGINT DEFAULT 1 NOT NULL, 
  PRIMARY KEY (tenant_id, project_id)
);
```

### ✅ Domain · `domains`

```sql
CREATE TABLE domains (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  domain_id VARCHAR(200) NOT NULL, 
  public_domain_id VARCHAR(200), 
  tenant_id VARCHAR(200) NOT NULL, 
  domain_name VARCHAR(200) NOT NULL, 
  config_json JSON NOT NULL, 
  guidelines TEXT, 
  guidelines_updated_at TIMESTAMP WITH TIME ZONE, 
  description TEXT, 
  status VARCHAR(16) DEFAULT 'active' NOT NULL, 
  automation_enabled BOOLEAN DEFAULT false NOT NULL, 
  confidence_floor FLOAT DEFAULT 0.95 NOT NULL, 
  settings_version INTEGER DEFAULT 1 NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT ck_domain_status CHECK (status IN ('active','archived','completed')), 
  CONSTRAINT ck_domain_confidence_floor CHECK (confidence_floor BETWEEN 0.80 AND 0.99), 
  CONSTRAINT ck_domain_settings_version CHECK (settings_version >= 1)
);
CREATE UNIQUE INDEX ix_domains_domain_id ON domains (domain_id);
CREATE INDEX ix_domains_tenant_id ON domains (tenant_id);
```

ORM insert defaults: `id=uuid4`, `tenant_id=`.

### ✅ Engine · `engines`

```sql
CREATE TABLE engines (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  domain_id VARCHAR(200) NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  annotator_id VARCHAR(200), 
  state_json JSON NOT NULL, 
  version INTEGER NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_engine_domain_annotator UNIQUE (domain_id, annotator_id), 
  FOREIGN KEY(domain_id) REFERENCES domains (domain_id)
);
CREATE INDEX ix_engines_domain_id ON engines (domain_id);
CREATE INDEX ix_engines_tenant_id ON engines (tenant_id);
CREATE UNIQUE INDEX uq_engine_project ON engines (domain_id) WHERE annotator_id IS NULL;
```

ORM insert defaults: `id=uuid4`, `tenant_id=`, `version=1`.

### ✅ LabelContent · `label_content`

```sql
CREATE TABLE label_content (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  label_log_id UUID NOT NULL, 
  content_type VARCHAR(32) NOT NULL, 
  spans_json JSON NOT NULL, 
  tags_json JSON NOT NULL, 
  image_url VARCHAR(2048), 
  PRIMARY KEY (id), 
  FOREIGN KEY(label_log_id) REFERENCES label_log (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_label_content_label_log_id ON label_content (label_log_id);
```

ORM insert defaults: `id=uuid4`, `spans_json=list`, `tags_json=list`.

### ✅ LabelLog · `label_log`

```sql
CREATE TABLE label_log (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  domain_id VARCHAR(200) NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  superseded_by VARCHAR(200), 
  label_id VARCHAR(200) NOT NULL, 
  annotation_id VARCHAR(200), 
  source_task_id VARCHAR(200), 
  source_updated_at TIMESTAMP WITH TIME ZONE, 
  annotator_id VARCHAR(200), 
  category VARCHAR(200), 
  factors_json JSON NOT NULL, 
  text TEXT, 
  notes TEXT, 
  review_notes TEXT, 
  recommended_action VARCHAR(200), 
  actual_action VARCHAR(200), 
  verified_outcome BOOLEAN, 
  confidence FLOAT, 
  scored_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
  verified_at TIMESTAMP WITH TIME ZONE, 
  verified_by_key_id UUID, 
  verification_reason VARCHAR(1000), 
  prior_revision_id VARCHAR(200), 
  revision_actor VARCHAR(200), 
  revision_by_key_id UUID, 
  revision_at TIMESTAMP WITH TIME ZONE, 
  idempotency_token VARCHAR(200), 
  PRIMARY KEY (id), 
  CONSTRAINT uq_label_log_domain_label UNIQUE (domain_id, label_id), 
  CONSTRAINT ck_label_log_recommended_action_length CHECK (recommended_action IS NULL OR length(recommended_action) <= 200), 
  CONSTRAINT ck_label_log_actual_action_length CHECK (actual_action IS NULL OR length(actual_action) <= 200), 
  FOREIGN KEY(domain_id) REFERENCES domains (domain_id), 
  FOREIGN KEY(verified_by_key_id) REFERENCES api_keys (id), 
  FOREIGN KEY(revision_by_key_id) REFERENCES api_keys (id)
);
CREATE INDEX ix_label_log_category ON label_log (category);
CREATE INDEX ix_label_log_domain_category_verified ON label_log (domain_id, category, verified_at);
CREATE INDEX ix_label_log_domain_id ON label_log (domain_id);
CREATE INDEX ix_label_log_tenant_id ON label_log (tenant_id);
CREATE UNIQUE INDEX uq_revision_predecessor ON label_log (domain_id, prior_revision_id) WHERE prior_revision_id IS NOT NULL;
```

ORM insert defaults: `id=uuid4`, `tenant_id=`.

### ✅ LifecycleNotice · `lifecycle_notice`

```sql
CREATE TABLE lifecycle_notice (
  event_id VARCHAR(200) NOT NULL, 
  kind VARCHAR(40) NOT NULL, 
  delivered_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (event_id, kind), 
  FOREIGN KEY(event_id) REFERENCES transition_log (event_id)
);
```

### ✅ PaddleWebhookEvent · `paddle_webhook_events`

```sql
CREATE TABLE paddle_webhook_events (
  event_id VARCHAR(200) NOT NULL, 
  PRIMARY KEY (event_id)
);
```

### ✅ Prediction · `prediction`

```sql
CREATE TABLE prediction (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  project_id UUID NOT NULL, 
  original_label_log_id UUID NOT NULL, 
  current_label_log_id UUID NOT NULL, 
  source VARCHAR(200) NOT NULL, 
  model_version VARCHAR(200) NOT NULL, 
  original_content JSON NOT NULL, 
  original_category VARCHAR(200) NOT NULL, 
  model_confidence FLOAT NOT NULL, 
  dlj_confidence FLOAT NOT NULL, 
  tier VARCHAR(32) NOT NULL, 
  recommendation VARCHAR(200) NOT NULL, 
  gate_snapshot JSON NOT NULL, 
  decision_reason VARCHAR(64) NOT NULL, 
  state VARCHAR(20) NOT NULL, 
  decision_version INTEGER DEFAULT 1 NOT NULL, 
  imported_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  machine_approved_at TIMESTAMP WITH TIME ZONE, 
  human_reviewed_at TIMESTAMP WITH TIME ZONE, 
  reviewer_key_id UUID, 
  assessment VARCHAR(12), 
  human_spans_reviewed BOOLEAN DEFAULT false NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT ck_prediction_model_confidence CHECK (model_confidence BETWEEN 0 AND 1), 
  CONSTRAINT ck_prediction_state CHECK (state IN ('pending','auto_approved','human_reviewed')), 
  CONSTRAINT ck_prediction_assessment CHECK (assessment IS NULL OR assessment IN ('correct','incorrect','unknown')), 
  FOREIGN KEY(project_id) REFERENCES domains (id), 
  UNIQUE (original_label_log_id), 
  FOREIGN KEY(original_label_log_id) REFERENCES label_log (id), 
  UNIQUE (current_label_log_id), 
  FOREIGN KEY(current_label_log_id) REFERENCES label_log (id), 
  FOREIGN KEY(reviewer_key_id) REFERENCES api_keys (id)
);
CREATE INDEX ix_prediction_scope ON prediction (project_id, source, imported_at);
```

ORM insert defaults: `id=uuid4`.

### ✅ ProjectBillingOwner · `project_billing_owner`

```sql
CREATE TABLE project_billing_owner (
  owner_tenant_id VARCHAR(200) NOT NULL, 
  billing_key_id UUID NOT NULL, 
  trial_started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (owner_tenant_id), 
  FOREIGN KEY(owner_tenant_id, billing_key_id) REFERENCES api_keys (tenant_id, id), 
  FOREIGN KEY(owner_tenant_id) REFERENCES tenant_guard (tenant_id), 
  UNIQUE (billing_key_id)
);
```

### ✅ ProjectExportSlot · `project_export_slot`

```sql
CREATE TABLE project_export_slot (
  project_id UUID NOT NULL, 
  slot SMALLINT NOT NULL, 
  lease_token UUID, 
  expires_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (project_id, slot), 
  CONSTRAINT ck_project_export_slot_number CHECK (slot IN (1,2)), 
  FOREIGN KEY(project_id) REFERENCES domains (id) ON DELETE CASCADE
);
```

### ✅ ProjectInvite · `project_invite`

```sql
CREATE TABLE project_invite (
  id UUID NOT NULL, 
  project_id UUID NOT NULL, 
  email VARCHAR(200) NOT NULL, 
  role VARCHAR(16) NOT NULL, 
  issued_by_key_id UUID NOT NULL, 
  token_digest VARCHAR(64) NOT NULL, 
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  consumed_at TIMESTAMP WITH TIME ZONE, 
  revoked_at TIMESTAMP WITH TIME ZONE, 
  accepted_by_key_id UUID, 
  accepted_member_id UUID, 
  mail_status VARCHAR(16) NOT NULL, 
  last_mail_attempt_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (id), 
  CONSTRAINT ck_project_invite_role CHECK (role IN ('admin','reviewer','annotator')), 
  FOREIGN KEY(project_id) REFERENCES domains (id) ON DELETE CASCADE, 
  FOREIGN KEY(issued_by_key_id) REFERENCES api_keys (id), 
  UNIQUE (token_digest), 
  FOREIGN KEY(accepted_by_key_id) REFERENCES api_keys (id), 
  FOREIGN KEY(accepted_member_id) REFERENCES project_member (id)
);
CREATE UNIQUE INDEX uq_open_project_invite ON project_invite (project_id, email) WHERE consumed_at IS NULL AND revoked_at IS NULL;
```

ORM insert defaults: `id=uuid4`.

### ✅ ProjectMember · `project_member`

```sql
CREATE TABLE project_member (
  id UUID NOT NULL, 
  project_id UUID NOT NULL, 
  member_tenant_id VARCHAR(200) NOT NULL, 
  role VARCHAR(16) NOT NULL, 
  active BOOLEAN DEFAULT true NOT NULL, 
  granted_by_key_id UUID NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  revoked_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_project_member_tenant UNIQUE (project_id, member_tenant_id), 
  CONSTRAINT ck_project_member_role CHECK (role IN ('admin','reviewer','annotator')), 
  FOREIGN KEY(project_id) REFERENCES domains (id) ON DELETE CASCADE, 
  FOREIGN KEY(granted_by_key_id) REFERENCES api_keys (id)
);
```

ORM insert defaults: `id=uuid4`.

### ✅ ProjectRequest · `project_request`

```sql
CREATE TABLE project_request (
  project_id UUID NOT NULL, 
  actor_key_id UUID NOT NULL, 
  operation VARCHAR(40) NOT NULL, 
  request_key VARCHAR(200) NOT NULL, 
  payload_digest CHAR(64) NOT NULL, 
  result_json JSON NOT NULL, 
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (project_id, actor_key_id, operation, request_key), 
  FOREIGN KEY(project_id) REFERENCES domains (id), 
  FOREIGN KEY(actor_key_id) REFERENCES api_keys (id)
);
```

### ✅ ProviderRepairManifest · `provider_repair_manifest`

```sql
CREATE TABLE provider_repair_manifest (
  key_id UUID NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  customer_id VARCHAR(200) NOT NULL, 
  subscription_id VARCHAR(200) NOT NULL, 
  state_version BIGINT NOT NULL, 
  trial_started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  labels_day_key VARCHAR(10) NOT NULL, 
  labels_today INTEGER NOT NULL, 
  labels_month_key VARCHAR(7) NOT NULL, 
  labels_this_month INTEGER NOT NULL, 
  owner_created BOOLEAN NOT NULL, 
  binding_created BOOLEAN NOT NULL, 
  repaired_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (key_id), 
  FOREIGN KEY(key_id) REFERENCES api_keys (id)
);
```

### ✅ ProviderRepairQuarantine · `provider_repair_quarantine`

```sql
CREATE TABLE provider_repair_quarantine (
  key_id UUID NOT NULL, 
  tenant_id VARCHAR(200) NOT NULL, 
  reason_code VARCHAR(64) NOT NULL, 
  quarantined_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (key_id), 
  FOREIGN KEY(key_id) REFERENCES api_keys (id)
);
CREATE INDEX ix_provider_repair_quarantine_tenant_id ON provider_repair_quarantine (tenant_id);
```

### ✅ SignupChallenge · `signup_challenge`

```sql
CREATE TABLE signup_challenge (
  token_digest VARCHAR(64) NOT NULL, 
  email VARCHAR(200) NOT NULL, 
  requested_name VARCHAR(200), 
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  consumed_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (token_digest)
);
CREATE INDEX ix_signup_challenge_email ON signup_challenge (email);
```

### ✅ SubscriptionBinding · `subscription_binding`

```sql
CREATE TABLE subscription_binding (
  subscription_id VARCHAR(200) NOT NULL, 
  payer UUID NOT NULL, 
  customer_id VARCHAR(200) NOT NULL, 
  retired_at TIMESTAMP WITH TIME ZONE, 
  PRIMARY KEY (subscription_id), 
  FOREIGN KEY(payer) REFERENCES api_keys (id)
);
CREATE UNIQUE INDEX one_current_sub ON subscription_binding (payer) WHERE retired_at IS NULL;
```

### ✅ TenantGuard · `tenant_guard`

```sql
CREATE TABLE tenant_guard (
  tenant_id VARCHAR(200) NOT NULL, 
  PRIMARY KEY (tenant_id)
);
```

### ✅ TransitionLog · `transition_log`

```sql
CREATE TABLE transition_log (
  event_id VARCHAR(200) NOT NULL, 
  key_id UUID, 
  subscription_id VARCHAR(200), 
  source VARCHAR(32) NOT NULL, 
  actor_ref VARCHAR(200), 
  occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  recorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
  old_state subscription_lifecycle, 
  new_state subscription_lifecycle, 
  disposition VARCHAR(32) NOT NULL, 
  reason_code VARCHAR(64), 
  key_version BIGINT, 
  PRIMARY KEY (event_id), 
  FOREIGN KEY(key_id) REFERENCES api_keys (id)
);
```

### ✅ WebhookAttempt · `webhook_attempt`

```sql
CREATE TABLE webhook_attempt (
  delivery_id UUID NOT NULL, 
  attempt_no INTEGER NOT NULL, 
  key_version INTEGER, 
  started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  finished_at TIMESTAMP WITH TIME ZONE, 
  outcome VARCHAR(24), 
  http_status INTEGER, 
  PRIMARY KEY (delivery_id, attempt_no), 
  FOREIGN KEY(delivery_id) REFERENCES webhook_delivery (id) ON DELETE CASCADE
);
```

### ✅ WebhookDelivery · `webhook_delivery`

```sql
CREATE TABLE webhook_delivery (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  endpoint_id UUID NOT NULL, 
  event_id UUID NOT NULL, 
  destination_version INTEGER NOT NULL, 
  state VARCHAR(16) NOT NULL, 
  attempts INTEGER DEFAULT 0 NOT NULL, 
  next_attempt_at TIMESTAMP WITH TIME ZONE, 
  lease_token UUID, 
  lease_until TIMESTAMP WITH TIME ZONE, 
  delivered_at TIMESTAMP WITH TIME ZONE, 
  terminal_at TIMESTAMP WITH TIME ZONE, 
  last_status INTEGER, 
  error_class VARCHAR(100), 
  PRIMARY KEY (id), 
  CONSTRAINT uq_webhook_delivery_endpoint_event UNIQUE (endpoint_id, event_id), 
  CONSTRAINT ck_webhook_delivery_state CHECK (state IN ('pending','leased','delivered','dead','cancelled')), 
  FOREIGN KEY(endpoint_id) REFERENCES webhook_endpoint (id) ON DELETE CASCADE, 
  FOREIGN KEY(event_id) REFERENCES webhook_event (id) ON DELETE CASCADE
);
CREATE INDEX ix_delivery_due ON webhook_delivery (state, next_attempt_at);
CREATE INDEX ix_delivery_lease ON webhook_delivery (state, lease_until);
```

ORM insert defaults: `id=uuid4`.

### ✅ WebhookEndpoint · `webhook_endpoint`

```sql
CREATE TABLE webhook_endpoint (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  project_id UUID NOT NULL, 
  url VARCHAR(2048) NOT NULL, 
  secret_ciphertext BYTEA NOT NULL, 
  key_version INTEGER NOT NULL, 
  subscribed_events JSON NOT NULL, 
  active BOOLEAN NOT NULL, 
  destination_version INTEGER NOT NULL, 
  lease_token UUID, 
  lease_until TIMESTAMP WITH TIME ZONE, 
  created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (id), 
  FOREIGN KEY(project_id) REFERENCES domains (id) ON DELETE CASCADE
);
```

ORM insert defaults: `id=uuid4`.

### ✅ WebhookEvent · `webhook_event`

```sql
CREATE TABLE webhook_event (
  id UUID DEFAULT gen_random_uuid() NOT NULL, 
  project_id UUID NOT NULL, 
  event_type VARCHAR(64) NOT NULL, 
  transition_key VARCHAR(200) NOT NULL, 
  schema_version INTEGER NOT NULL, 
  canonical_body TEXT NOT NULL, 
  created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_webhook_event_transition UNIQUE (project_id, event_type, transition_key), 
  FOREIGN KEY(project_id) REFERENCES domains (id) ON DELETE CASCADE
);
```

ORM insert defaults: `id=uuid4`.

### ✅ Isolated legacy SQLite tables

```sql
CREATE TABLE IF NOT EXISTS tenants (
    api_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS domains (
    domain_id TEXT PRIMARY KEY,
    tenant_key TEXT NOT NULL,
    config_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (tenant_key) REFERENCES tenants(api_key)
);
CREATE TABLE IF NOT EXISTS decision_log (
    decision_id TEXT PRIMARY KEY,
    domain_id TEXT NOT NULL,
    tenant_key TEXT NOT NULL,
    factors_json TEXT NOT NULL,
    category TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    confidence REAL NOT NULL,
    actual_action TEXT,
    confirmed INTEGER,
    scored_at REAL NOT NULL,
    learned_at REAL,
    FOREIGN KEY (domain_id) REFERENCES domains(domain_id)
);
```

<a id="arch-4"></a>

### Design record · Consolidated schema ledger

**Disposition.** Forward/inverse migration design record, with enablement and rollback rationale. Do not apply this planning SQL against a running database; db/migrate.py and the schema dictionary above govern actual upgrades.

<details>
<summary>Architecture decision detail and acceptance history</summary>

The blocks are **forward and inverse definitions** for migration authors. The inverse statements are a separate downgrade, never executed as part of upgrade. PostgreSQL uses UTC timestamptz and application-generated UUIDs. SQLite uses the existing ORM UUID representation, JSON encoding, checked text enums, UTC normalization and FK enforcement. Use versioned catalog checks, one migration runner, fresh and historical fixtures, and a second upgrade run. On SQLite use an FK-safe staged rebuild when an ALTER is unsupported; compare values and child counts and run foreign_key_check before commit. No legacy JM tables, credential audience discriminator or volume migration enter this release.

#### A · Projects, entitlement, historical repair

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

#### A · Challenge, team and actor authorization

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

#### C · Shared write contract and revision history

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

#### D · Export slots

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

#### D · Prediction provenance

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

#### E · Outbound delivery

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

</details>

<a id="anno-3"></a>

### Design record · Annotation architecture

**Disposition.** The first five-table snapshot and its staged migration rationale are retained for existing data. Shipped columns are in the ORM dictionary; future strict storage is specified separately.

<details>
<summary>Annotation decision detail and acceptance history</summary>

#### Existing persistence

The early SQLAlchemy baseline comprised five tables; these are the fields present at that baseline. The full current dictionary is above. The legacy service separately owns SQLite tenants, domains and decision_log.

| Model / table | Existing columns | Identity and meaning |
|---|---|---|
| Domain / domains | id, domain_id, tenant_id, domain_name, config_json, created_at, updated_at | UUID primary key and unique internal domain_id. Labeling scopes the public ID using a hash of tenant and ID. Config holds categories, actions and factors. |
| Engine / engines | id, domain_id, tenant_id, annotator_id, state_json, version, created_at, updated_at | Serialized JM state and optimistic version. One project engine with NULL annotator per domain and separate annotator engines. |
| LabelLog / label_log | id, domain_id, tenant_id, superseded_by, label_id, annotation_id, source_task_id, annotator_id, category, factors_json, recommended_action, actual_action, verified_outcome, confidence, scored_at, verified_at | UUID row ID. Unique (domain_id, label_id). Label Studio can create revisions. Review action and correctness are distinct. |
| Annotator / annotators | id, domain_id, tenant_id, annotator_id, label_count, last_active | Unique (domain_id, annotator_id). Per-category accuracy comes from verified logs. |
| ApiKey / api_keys | id, key_hash, tenant_id, tenant_name, created_at, is_active, tier, paddle_customer_id, paddle_subscription_id, contact_email, trial_expiring_email_sent_at, trial_expired_email_sent_at, cancelled_at, labels_this_month, labels_month_key, labels_today, labels_day_key | Hash unique, tenant ID indexed. Usage and billing fields belong to the key row. Plaintext cannot be recovered from the DB. |

**Decision.** Phase A adds one NEW nullable SQL TEXT field, LabelLog.text. One optional source string arrives with one scored label, can be written in the same transaction, and follows the existing 30-day cleanup. Queue reads should select a prefix only. A second table and join buy little for this first use case. A foreign key to label_id alone would be invalid across domains.

Phase B/C can add a NEW optional one-to-one LabelContent keyed by label_log.id (UUID FK, unique, ON DELETE CASCADE) for structured fields only: NEW content_type, spans JSON array, tags JSON array and image_url. Keep canonical text on the log. Defer free-form metadata. Define server-side schemas and size limits before accepting each type. Retain authenticated tenant/domain lookup through the parent. Store a bounded approved HTTPS image reference, with a policy for expirations and allowed hosts, never base64 in list responses.

**Correction semantics.** Keep the original scored category, factors, decision and text immutable for audit. Phase B records the proposed/selected annotation as a NEW revision with actor, prior revision, timestamp and idempotency token. Reject stale versions. Class labels, span labels and tag sets belong to the annotation schema. The engine actions remain approve/reject. Editing a span must never silently count as independent ground truth or train twice. A first-pass labeling flow needs an unscored work item with source content and a NEW configured category vocabulary. The annotator chooses a class before the normal scoring handoff. Keep unassigned items outside accuracy and quota counts until scored. Persist reviewed outcomes through the existing verification transaction.

#### CSV contract, from drop to retrieval

1. Upload posts multipart file to anonymous analysis before offering scoring. The service checks .csv, 10 MiB limit, UTF-8/BOM, unique nonempty headers, 200+ rows, unique non-null label IDs, 1–20 categories and at least two finite numeric factor columns in [0,1]. Legacy requires verified_outcome (blank outcomes allowed). The alternate format requires proposed_action, actual_action and verified together, derives correctness from equality for verified rows, and prohibits an actual action on unverified rows. Few verified rows yield a warning. Report analysis runs in memory.
2. On “Start scoring” the browser parses the file again. PapaParse requires label_id, category, at least one data row and two distinct factors. It trims IDs, rejects duplicate IDs, empty factors, nonfinite/out-of-range numbers and malformed headers/rows. If factor_ columns exist it uses those and strips the prefix. Otherwise it uses all columns except label_id, category, annotator_id, proposed_action, actual_action, verified, verified_outcome, action, timestamp and existing_label. Health inference instead considers numeric nonreserved columns. Today text may be discarded or misinterpreted as a factor.
3. Browser sends JSON in independent 100-row batches; single-label ingest also exists. The server validates identifiers (no blank or pipe), factors and domain schema. First ingest creates a scoped domain and engine, subsequent categories can grow to 20. It reserves key capacity, scores, stores factors and recommendation on LabelLog and persists engine state. A failed batch rolls back its transaction; earlier committed batches remain. CSV ground truth is used in the report only. Pending reads return identifiers, factors, recommendation and confidence.
4. **NEW A2** reserves text in *both* parsers, even for numeric-looking text. Preserve decoded source exactly, including whitespace and Unicode; map absent/empty text to NULL. Extend IngestItem in TypeScript and Pydantic, both ingest paths, repository insert and scoped detail DTO. Limit text to 32 KiB UTF-8 per item, return a row-specific validation error, never log raw content. Treat it as inert React text. Direct label detail ([§4](#anno-5)) removes ReviewCard’s first-page dependency. Keep report-only input ephemeral. Example scoring CSV header: `label_id,category,annotator_id,verified_outcome,factor_model_confidence,factor_item_difficulty,text`. A two-row snippet can exercise the parser but cannot pass anonymous analysis. Add structured spans later via JSON.

#### Migration and rollback

Run the existing db/migrate.py before deploying writers. Within engine.begin inspect label_log and add the nullable text column only if missing; create_all handles fresh DBs but cannot alter an existing table. No default or bulk rewrite. Repeat on PostgreSQL and SQLite, including a populated pre-change table. Old integrations keep sending factors only. Legacy and Label Studio rows display “Source text unavailable” while review still works. Roll out readers before writers; rollback reverts app/dist, retains additive columns and existing content. Only a separate, approved migration after backup may remove captured data. Apply the same expand-first order to structured content, verify cleanup with FK enforcement, and retain original rows when rolling back an editor.

</details>

<a id="track-2"></a>

### Design record · Persistence and ownership

**Disposition.** The following logical field/ownership specification explains the design. The PostgreSQL ORM dictionary above governs actual columns; original proposed columns without a physical counterpart remain design history.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Use SQLAlchemy Uuid(as_uuid=True) and uuid4 for new UUIDs, timezone-aware UTC instants, bounded strings, database uniqueness and FK enforcement on both dialects. Use ordinary relational fields for values needed in authorization, filtering and claims.

| Entity | Keys, values and constraints |
|---|---|
| Domain, exposed as Project | Keep existing PK, tenant, internal key, optional public alias, name, config_json and timestamps. Add nullable description, status with server default active and allowed active/archived/completed, automation_enabled default false and confidence_floor default .95 checked in [.80,.99]. Completed is read-only until reopened. Reuse Track 2 guidelines and content vocabulary once verified. Config categories, factors and actions remain authoritative. Never serialize a raw owner credential or internal hash |
| Project creation | Require name, immutable public alias and engine schema with validated factors/categories/actions. Use the existing DomainConfig serializer and domain creation path. A preset must expand to that same valid schema. Reject duplicate owner/alias with 409. Display-name edits preserve the key. Reject schema edits that invalidate existing centroids, content or historical factor vectors |
| ProjectBillingOwner | owner_tenant_id VARCHAR(200) PK, billing_key_id UUID UNIQUE FK api_keys.id with restrictive deletion. Validate matching tenant. One binding for all shared projects of that owner. Keep the current per-key billing row and its Paddle state. Bind automatically only for an unambiguous single active owner key. Require explicit account reconciliation for multiple active keys or conflicting subscriptions before enabling sharing; existing private workflows remain available |
| ProjectMember | UUID PK, project_id UUID FK domains.id ON DELETE CASCADE, member_tenant_id VARCHAR(200), role enum admin/reviewer/annotator, active flag, granted_by_key_id UUID FK api_keys.id, created_at and revoked_at. UNIQUE(project_id, member_tenant_id). Use the existing authenticated tenant identity for a member account. Before granting, disclose that all active keys of that account exercise its role. Owner is implicit from Domain.tenant_id. Empty legacy tenant rows are accessible only via their existing credentials and require explicit attribution before sharing |
| ProjectInvite | UUID PK, project_id UUID FK domains.id CASCADE, normalized_email up to 200, role, issued_by_key_id UUID FK api_keys.id, unique token_digest, expires_at, consumed_at, revoked_at and mail delivery status. Unique open invite per project/email using a partial index on unused/unrevoked rows. On resend invalidate the earlier token first. Accept under a row lock or conditional update with valid bearer token and active account whose contact email matches. The token delivered to the mailbox proves possession. One transaction activates membership and consumes the token. No API key in the URL or new credential on acceptance. Use a short expiry and rate limits; on retry after success show existing membership to that recipient |
| ProjectRequest | UUID PK, project_id FK domains.id, actor_key_id UUID FK api_keys.id, operation, idempotency key, payload digest, completed result and expiry. UNIQUE(project_id, actor_key_id, operation, key). Record in the import transaction. Same payload returns saved result, changed payload gets 409. Keep label uniqueness after replay records expire. Bound result size and retention |
| Prediction | UUID PK, project_id UUID FK domains.id, original_label_log_id UUID unique FK label_log.id, current_label_log_id UUID unique FK label_log.id, source/version, original category and spans JSON, model_confidence checked in [0,1], scored confidence/tier/gate snapshot, decision reason, imported_at, machine_approved_at, human_reviewed_at, reviewer_key_id UUID FK api_keys.id, human assessment correct/incorrect/unknown. Maintain revision pointers on relabel and external connector supersession. Original confidence and categories remain immutable. Machine approval audit survives later human review. Validate parent labels belong to this project. Index project/source/imported_at |
| WebhookEndpoint | UUID PK, project_id UUID FK domains.id CASCADE, URL, encrypted signing key and key version, subscribed event names, active flag, destination version, created_at/updated_at. Owner/admin only. Test deliveries use the same destination policy |
| WebhookEvent | UUID PK, project_id UUID FK domains.id CASCADE, event type, distinct source transition key, bounded immutable payload, created_at. UNIQUE(project_id, event type, transition key). Publish label ID/current revision, actual action, known outcome and stored confidence. Supply tier only if captured with the change. Omit label text and factors by default |
| WebhookDelivery | UUID PK, endpoint_id and event_id UUID FKs with cleanup on deletion, destination version, state pending/leased/delivered/dead/cancelled, attempts, next_attempt_at, lease_token, lease_until, delivered_at, last_status and bounded error class. UNIQUE(endpoint_id,event_id), indexes on state/due time and lease expiry. Store bounded per-attempt metadata keyed by delivery and attempt number for delivery history |

Additional fields needed by the write paths follow. Introduce them in the prompt that owns their first writer. Apply ON DELETE CASCADE only to owned children and retain actor attribution on credential deactivation.

| Table | Columns / rules |
|---|---|
| domains | settings_version integer ≥1 with server default 1. Use conditional updates for competing settings edits |
| label_log | verified_by_key_id nullable UUID FK api_keys.id for new human decisions; historical actors may be unknown. Preserve verification_reason and existing revision_actor semantics. Add revision_by_key_id nullable UUID FK for project-scoped edits |
| project_invites | accepted_by_key_id nullable UUID FK, accepted_member_id nullable UUID FK and last_mail_attempt_at; return existing membership on token replay only to its still-authorized recipient |
| project_billing_owners | trial_started_at nullable UTC timestamp; canonical key and normalized current period counters are the source for volume limits |
| predictions | state, decision_version default 1, human_spans_reviewed default false, normalized original content JSON, original model version and recommendation snapshot. Foreign keys for both revision pointers participate in the same transaction as label writes |
| project_export_slots | Composite PK (project_id UUID FK, slot small integer restricted to 1 or 2), lease_token UUID, expires_at UTC. Claim/release conditionally. A crashed reader's slot expires at the download deadline |
| webhook_endpoints and webhook_events | endpoint lease_token and lease_until for claim serialization; event schema_version integer, canonical_body text for signing. Endpoint deletion cancels claims and removes owned attempt metadata |

Scope billing reads and updates consistently. For a bound tenant, owner legacy ingest, project ingest, Label Studio scoring, account usage, checkout and Paddle reconciliation must use the same billing key for the tenant's work. An invitee's private project still uses their own account. Preserve caller identity for audit. On cutover reconcile current UTC counters and provider IDs under lock, preserve trial age and tier, explicitly resolve conflicting entitlements, and prevent additional keys or route aliases from gaining another allowance. Fail closed on a stale binding. Cleanup operates on owning accounts, cascades project children and revokes orphaned invitations. Removing a member leaves their independent account intact.

#### Export and workflow predicates

Apply owner/project and current-revision predicates first. Use all for every current item, pending for scored work awaiting review (excludes machine-completed), unclassified for unscored work, verified for a human-observed outcome with verified_at, auto_approved for machine-only completion and overridden for human-verified rows with actual_action different from recommended_action. Expose category revision history separately from action overrides. For predictions, human_reviewed counts distinct adjudicated predictions; pending, machine-only and human-reviewed are disjoint. auto_approved_ever is historical and may overlap human-reviewed. Use an explicit source filter and label denominators in the dashboard.

A JSONL record for plain text after human verification follows. The corresponding CSV stores the factors object and both empty arrays in individual cells using standard CSV quoting.

```json
{"label_id":"L001","revision_label_id":"L001","revision_id":"b5131403-3d03-4328-8b18-11a5f468a57b","source_task_id":null,"annotation_id":null,"annotator_id":"ann_1","category":"billing","text":"Refund requested","recommended_action":"approve","actual_action":"approve","verified_outcome":true,"confidence":0.87,"factors":{"agreement":0.85,"clarity":0.92},"scored_at":"2026-11-20T10:30:00Z","verified_at":"2026-11-20T11:00:00Z","revision_at":null,"content_type":null,"spans":[],"tags":[],"image_url":null,"review_state":"verified"}
```

</details>

<a id="mm-3"></a>

### Designed · Storage, migration and rollback

The repository uses SQLAlchemy mapped classes and the inspector-driven `db/migrate.py:migrate` transaction, followed by `Base.metadata.create_all`. There is no Alembic revision directory to populate. Follow the existing domain settings column/check upgrade and outbound delivery schema patterns. For existing tables inspect types, columns and named constraints; for fresh databases put identical definitions in metadata. Startup uses `docker-entrypoint.sh` → `run_migration`. Test fresh install, populated upgrade, repeat upgrade and rollback rehearsal in disposable PG schemas.

**IMG upgrade** (reference PostgreSQL SQL; run the constraint addition only when absent):
~~~sql
ALTER TABLE domains ADD COLUMN IF NOT EXISTS content_type varchar(20) NOT NULL DEFAULT 'text';
ALTER TABLE domains ADD COLUMN IF NOT EXISTS label_schema varchar(20) NOT NULL DEFAULT 'single';
ALTER TABLE domains ADD COLUMN IF NOT EXISTS modality_enforced boolean NOT NULL DEFAULT false;
ALTER TABLE domains ADD CONSTRAINT ck_domains_modality_pair CHECK (
  (content_type='text' AND label_schema IN ('single','multi','ner')) OR
  (content_type='image' AND label_schema IN ('single','multi'))
) NOT VALID;
ALTER TABLE domains VALIDATE CONSTRAINT ck_domains_modality_pair;
ALTER TABLE label_content ALTER COLUMN image_url TYPE text;
~~~

Keep the last alteration guarded by reflected type. In the ORM use non-null `Mapped[str]` + `String(20)` with Python and SQL **server** defaults, non-null `Boolean` with false defaults, named `CheckConstraint`, and nullable `Mapped[str | None]` + `Text` for `image_url`. Keep the current unique label-content FK/index and scoped label indexes. Neither large media nor axes need a search index. Search captions through the existing text predicate. No second item-type column, media URL or generic JSONB bag on label_log. The migration permits future supported pairs; application gates determine which writers are enabled. SQLite remains advisory: follow dialect inspection, SQLite TEXT affinity and equivalent fresh-schema checks; PostgreSQL alone gates rollout.

**Deployment and rollback.** Before enabling features take a restorable backup and verify available storage, request limits and export spool space on Railway. Use short lock_timeout for the ALTERs, retry startup migration on contention, validate large-table checks outside the brief expand lock if needed, and run it twice on a populated staging copy. Deploy additive schema first, then all readers/writers, then enable new project creation; old binaries can omit all new columns during expansion. Rehearse a representative 10 MiB import/detail/export under the deployment's real memory and request limits. Disable new modality creation/writes and drain in-flight jobs for application rollback. Continue serving existing modality projects with the last compatible reader/writer; do not route strict projects to unaware old writers. Restore service forward if already-written data depends on new semantics.

Physical downgrade is optional and offline. Under a write fence, require zero enforced projects, zero later-phase rows, and no image_url longer than 2048 characters. Compare label, content and receipt counts and representative hashes against the backup. Abort if any precondition fails; never truncate media or discard adjudication to roll back. After reversing later phases in dependency order:
~~~sql
ALTER TABLE label_content ALTER COLUMN image_url TYPE varchar(2048);
ALTER TABLE domains DROP CONSTRAINT IF EXISTS ck_domains_modality_pair;
ALTER TABLE domains DROP COLUMN modality_enforced, DROP COLUMN label_schema, DROP COLUMN content_type;
~~~

<a id="chapter-4"></a>

## 4. API Contract

✅ **Shipped · mounted service.** This catalog covers every registered FastAPI method/path pair including compatibility aliases, plus framework and static routes. Route parameters in braces are required. Most project workflows accept the selected UUID and resolve the internal domain string; management paths declaring a UUID require a valid UUID. JSON property names below are wire names. Optional query and body fields have a trailing question mark. Named DTOs are defined after the routes. A bare JSON array and a paginated object are different contracts.

| Authorization in the catalog | Meaning |
|---|---|
| Public | No tenant credential. Anonymous health reports have separate byte, concurrency and time limits. |
| JM | Legacy X-Api-Key looked up in the isolated SQLite store. |
| Key | Active hashed DLJ X-Api-Key. Project and account lookups still enforce scope. |
| Project | DLJ key, owner or active member, selected project and effective payer. Project role restrictions in §9 apply to aliases too. |
| Admin / LS / Paddle | X-Admin-Key, configured X-LS-Token, or byte-exact signed Paddle event, respectively. |

Rate column lists explicit SlowAPI requests per remote address, plus specified business limits. A dash means no explicit handler rate decorator; upload slots, deadlines, quotas, DB locks and export slots remain separate controls. Error column lists handler-specific statuses; add 422 for invalid schemas/parameters, 401 for invalid credentials, 403 for insufficient role, 404 for an inaccessible scoped object, 409 on stale write/ambiguous alias, 402 for an ineligible paying write and 429 for a rate/quota limit where applicable. In particular, nonmember UUID access to project SLA returns 403. Errors normally use JSON `detail`, which may be text, a validation list or structured quota information. Browser clients decode each shape. The legal and download routes return their actual media types even where OpenAPI exposes an untyped response.


### ✅ label_health.api · 3 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/label-health/analyze` | multipart/form-data: file (CSV) | 200 ReportJSON | Public | 2 analysis slots | 400, 408, 413, 422, 503, 504 |
| `POST /v1/label-health/report` | multipart/form-data: file (CSV) | 200 text/html | Public | 2 analysis slots | 400, 408, 413, 422, 503, 504 |
| `POST /v1/label-health/report/pdf` | multipart/form-data: file (CSV) | 200 application/pdf attachment | Public | 2 analysis slots | 400, 408, 413, 422, 503, 504 |

### ✅ labeling_router · 36 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/labels/ingest` | IngestRequest | 200 IngestResponse | Project | — | 409 |
| `POST /v1/labels/verify` | VerifyRequest | 200 VerifyResponse | Project/reviewer | — | 404, 409, 422 |
| `POST /v1/labels/{domain_id}/bulk-verify` | BulkVerifyRequest | 200 {processed, skipped, errors} | Project/reviewer | 10/minute | 404, 422 |
| `POST /v1/labels/ingest/batch` | IngestBatchRequest | 200 IngestBatchResponse | Project/reviewer | — | 422 |
| `POST /v1/labels/{domain_id}/sample` | — | 200 {domain_id, created, existing, pending} | Project/reviewer | — | 404, 409 |
| `POST /v1/labels/{domain_id}/tasks` | TextTaskRequest | 201 {label_id, status, category} | Project | — | 409, 422 |
| `POST /v1/labels/{domain_id}/items/{label_id}/relabel` | RelabelRequest | 200 {label_id, category, revision_id, previous_category} | Project | — | 401, 409, 422 |
| `GET /v1/labels/{domain_id}/pending` | query category?: string \| null; query limit?: integer [minimum=1, maximum=200, default=50]; query offset?: integer [minimum=0, default=0]; query sort_by?: label_id/category/annotator_id/confidence/recommended_action/scored_at \| null; query sort_order?: asc/desc; query search?: string [maxLength=200] \| null | 200 list of {label_id, category, annotator_id, confidence, recommended_action, factors, text_preview, notes, review_notes} | Project | 60/minute | 404 |
| `POST /v1/labels/{domain_id}/items/{label_id}/content` | LabelContentRequest | 201 {label_id,content_type,spans_count or tags_count} | Project | — | 404, 409, 422 |
| `GET /v1/labels/{domain_id}/{label_id}` | — | 200 {additional fields, domain_id, label_id, category, annotator_id, factors, recommended_action, confidence, text, actual_action, notes, review_notes, verified_outcome, verified_at, revision_id, previous_category, status, content} | Project | 60/minute | — |
| `GET /v1/labels/{domain_id}/items/{label_id}` | — | 200 {additional fields, domain_id, label_id, category, annotator_id, factors, recommended_action, confidence, text, actual_action, notes, review_notes, verified_outcome, verified_at, revision_id, previous_category, status, content} | Project | 60/minute | — |
| `POST /v1/projects/{domain_id}/labels/batch` | ProjectImportBatch | 200 {results: IngestResponse[], batch_size: int} | Project/reviewer | — | 401, 404, 409, 422 |
| `POST /v1/projects/{domain_id}/labels` | ProjectImportItem; header Idempotency-Key: string | 200 IngestResponse | Project/reviewer | — | 422 |
| `POST /v1/projects/{domain_id}/labels/verify` | ProjectVerifyInput | 200 VerifyResponse | Project/reviewer | — | — |
| `POST /v1/projects/{domain_id}/labels/bulk-verify` | BulkVerifyRequest | 200 {processed, skipped, errors} | Project/reviewer | 10/minute | 404, 422 |
| `GET /v1/projects/{domain_id}/labels/pending` | query category?: string \| null; query limit?: integer [minimum=1, maximum=200, default=50]; query offset?: integer [minimum=0, default=0]; query sort_by?: label_id/category/annotator_id/confidence/recommended_action/scored_at \| null; query sort_order?: asc/desc; query search?: string [maxLength=200] \| null | 200 list of {label_id, category, annotator_id, confidence, recommended_action, factors, text_preview, notes, review_notes} | Project | 60/minute | 404 |
| `POST /v1/projects/{domain_id}/labels/sample` | — | 200 {domain_id, created, existing, pending} | Project/reviewer | — | 404, 409 |
| `POST /v1/projects/{domain_id}/labels/tasks` | TextTaskRequest | 200 {label_id, status, category} | Project | — | 409, 422 |
| `POST /v1/projects/{domain_id}/labels/items/{label_id}/relabel` | RelabelRequest | 200 {label_id, category, revision_id, previous_category} | Project | — | 401, 409, 422 |
| `POST /v1/projects/{domain_id}/labels/items/{label_id}/content` | LabelContentRequest | 200 {label_id,content_type,spans_count or tags_count} | Project | — | 404, 409, 422 |
| `GET /v1/projects/{domain_id}/labels/items/{label_id}` | — | 200 {additional fields, domain_id, label_id, category, annotator_id, factors, recommended_action, confidence, text, actual_action, notes, review_notes, verified_outcome, verified_at, revision_id, previous_category, status, content} | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/labels/{label_id}` | — | 200 {additional fields, domain_id, label_id, category, annotator_id, factors, recommended_action, confidence, text, actual_action, notes, review_notes, verified_outcome, verified_at, revision_id, previous_category, status, content} | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/next-batch` | query strategy?: string [maxLength=50, default=centroid_distance]; query n?: integer [minimum=1, default=50]; query offset?: integer [minimum=0, default=0]; query category?: string [maxLength=200] \| null; query search?: string [maxLength=200] \| null | 200 NextBatchResponse | Project | — | 400 |
| `GET /v1/projects/{domain_id}/sla` | — | 200 SlaResponse | Project | — | — |
| `GET /v1/projects/{domain_id}/export` | query format?: jsonl/csv/docbin; query review_status?: pending/verified/auto_approved/human_reviewed/unclassified/overridden \| null; query category?: string [maxLength=200] \| null; query annotator?: string [maxLength=200] \| null; query date_from?: string(date-time) \| null; query date_to?: string(date-time) \| null; query include_factors?: boolean [default=False]; query browser_fallback?: boolean [default=False] | 200 attachment: application/x-ndjson, text/csv or application/octet-stream | Project/reviewer | — | 403, 404, 413, 422, 429, 501, 504 |
| `POST /v1/projects/{domain_id}/predictions` | PredictionImportRequest | 201 {results: PredictionDecision[], batch_size: int} | Project/reviewer | — | 401, 409, 422 |
| `POST /v1/projects/{domain_id}/predictions/{prediction_id}/review` | PredictionReviewRequest | 200 PredictionDecision | Project/reviewer | — | 409, 422 |
| `POST /v1/projects/{domain_id}/predictions/{prediction_id}/reopen` | PredictionReopenRequest | 200 PredictionDecision | Project/reviewer | — | 409 |
| `GET /v1/projects/{domain_id}/predictions` | query prediction_state?: pending_review/accepted/corrected/reopened/unknown \| null; query origin?: all/human/prediction; query source?: string [maxLength=200] \| null; query sort_by?: text/category/action/confidence/prediction_state/scored_at; query sort_order?: asc/desc; query limit?: integer [minimum=1, maximum=200, default=50]; query offset?: integer [minimum=0, default=0] | 200 {items, total, limit, offset} | Project | — | — |
| `GET /v1/projects/{domain_id}/predictions/stats` | — | 200 {total, by_state, by_source, reviewed_known, accuracy} | Project | — | — |
| `GET /v1/projects/{domain_id}/autonomy` | — | 200 {domain_id, categories, overall_tier} | Project | 60/minute | 404 |
| `GET /v1/projects/{domain_id}/guidelines` | — | 200 GuidelinesPayload | Project | — | — |
| `PUT /v1/projects/{domain_id}/guidelines` | GuidelinesPayload | 200 GuidelinesPayload | Owner/admin | — | — |
| `GET /v1/domains/{domain_id}/guidelines` | — | 200 GuidelinesPayload | Project | — | — |
| `PUT /v1/domains/{domain_id}/guidelines` | GuidelinesPayload | 200 GuidelinesPayload | Owner/admin | — | — |
| `GET /v1/domains/{domain_id}/autonomy` | — | 200 {domain_id, categories, overall_tier} | Project | 60/minute | 404 |

### ✅ dashboard_router · 12 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /v1/dashboard/{domain_id}/iaa` | — | 200 Agreement | Project | 60/minute | — |
| `GET /v1/dashboard/{domain_id}/overview` | — | 200 Overview | Project | 60/minute | — |
| `GET /v1/dashboard/{domain_id}/corrections` | — | 200 Corrections | Project | 60/minute | — |
| `GET /v1/dashboard/{domain_id}/annotators` | query limit?: integer [minimum=1, maximum=100, default=50] | 200 Annotators | Project (see §16) | 60/minute | — |
| `GET /v1/dashboard/{domain_id}/factors` | — | 200 Factors | Project | 60/minute | — |
| `GET /v1/dashboard/{domain_id}/compounding` | query window?: integer [minimum=1, maximum=2147483647, default=10]; query category?: string \| null | 200 Compounding | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/iaa` | — | 200 Agreement | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/overview` | — | 200 Overview | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/corrections` | — | 200 Corrections | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/annotators` | query limit?: integer [minimum=1, maximum=100, default=50] | 200 Annotators | Project (see §16) | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/factors` | — | 200 Factors | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/dashboard/compounding` | query window?: integer [minimum=1, maximum=2147483647, default=10]; query category?: string \| null | 200 Compounding | Project | 60/minute | — |

### ✅ analytics_router · 4 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /v1/projects/{domain_id}/analytics/distribution` | — | 200 DistributionResponse | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/analytics/throughput` | query days?: integer [minimum=1, maximum=90, default=7] | 200 ThroughputResponse | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/analytics/confusion` | query source?: human/prediction/all | 200 ConfusionResponse | Project | 60/minute | — |
| `GET /v1/projects/{domain_id}/analytics/agreement` | — | 200 AgreementResponse | Project | 60/minute | — |

### ✅ label_studio · 5 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/label-studio/configure` | ConnectorConfig; header If-Match?: string \| null | 200 ConnectorConfig | LS + Key | — | 409, 422 |
| `POST /v1/label-studio/setup` | object | 200 {model_version} | LS | — | — |
| `POST /v1/label-studio/predict` | PredictionEnvelope | 200 list of {results} | LS + Key | — | 404, 409, 422 |
| `POST /v1/label-studio/webhook` | WebhookEnvelope | 200 {status} | LS + Key | — | 409, 422 |
| `GET /v1/label-studio/health` | — | 200 {status,model_version} | Public | 60/minute | — |

### ✅ auth · 5 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/admin/api-keys/{key_id}/reconcile-signup-owner` | ReconcileSignupOwner | 200 {status} | Admin | — | 401, 404, 409 |
| `POST /v1/admin/api-keys/{key_id}/rotate` | — | 200 {api_key, tenant_id} | Admin | — | 401, 404, 409 |
| `POST /v1/admin/api-keys` | CreateKey | 200 {api_key, tenant_id} | Admin | 10/minute | 401, 409 |
| `POST /v1/auth/register` | auth__RegisterRequest | 202 {message} | Public | 5/minute | 409, 503 |
| `POST /v1/auth/confirm` | ConfirmRequest | 201 {api_key, tenant_id, tier, message} | Public | 10/minute | 400, 409 |

### ✅ account · 3 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /v1/account` | — | 200 {tenant_id, tenant_name, tier, created_at, is_active, subscription_state, cancelled_at, trial_expires_at, trial_expired, usage} | Key | — | 401 |
| `GET /v1/account/domains` | — | 200 list of {id, public_domain_id, needs_name} | Key | — | — |
| `POST /v1/account/domains/resolve` | ResolveDomain | 200 {public_domain_id} | Key | — | 404, 409 |

### ✅ billing · 2 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /v1/billing/checkout-url` | query tier?: string [default=starter] | 200 {checkout_url, tier} | Key | — | 400, 401, 409, 502, 503 |
| `POST /v1/billing/webhook` | raw signed JSON: event_id, event_type, occurred_at, data; Paddle-Signature | 200 {status: string} | Paddle | 4 readers | 400, 401, 408, 409, 413, 422, 503 |

### ✅ projects_router · 9 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/projects` | ProjectCreate | 201 {id, public_domain_id, name, status, settings_version} | Key | — | 409 |
| `GET /v1/projects` | — | 200 list of {id, public_domain_id, name, description, status, settings_version} | Key | — | — |
| `GET /v1/projects/{project_id}` | — | 200 {id, public_domain_id, name, description, status, automation_enabled, confidence_floor, guidelines, guidelines_updated_at, settings_version, role} | Key | — | — |
| `PATCH /v1/projects/{project_id}` | ProjectPatch; header If-Match?: string \| null | 200 {id, settings_version, status} | Owner/admin | — | — |
| `DELETE /v1/projects/{project_id}` | header If-Match?: string \| null | 200 {id, settings_version, status} | Owner | — | — |
| `PUT /v1/projects/{project_id}/settings` | ProjectSettings | 200 {id, settings_version, status} | Owner/admin | — | 403, 409, 422 |
| `POST /v1/projects/{project_id}/members` | AddMember | 201 {id, role} | Owner/admin | — | 403, 404, 409 |
| `POST /v1/projects/{project_id}/invites` | InviteRequest | 201 {id, mail_status} | Owner/admin | — | 403, 409 |
| `POST /v1/projects/{project_id}/invites/{invite_id}/accept` | AcceptInvite | 200 {project_id, role} | Key + invitation | — | 403, 404, 409 |

### ✅ webhook_router · 8 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `POST /v1/projects/{project_id}/webhooks` | WebhookCreate | 201 WebhookPublic + signing_secret | Owner/admin | — | 422 |
| `GET /v1/projects/{project_id}/webhooks` | — | 200 WebhookPublic[] | Owner/admin | — | — |
| `GET /v1/projects/{project_id}/webhooks/health` | — | 200 {total, healthy, retrying, failing, items} | Owner/admin | — | — |
| `GET /v1/projects/{project_id}/webhooks/{endpoint_id}/deliveries` | query limit?: integer [minimum=1, maximum=100, default=50]; query offset?: integer [minimum=0, default=0] | 200 {items, attempt_history, total, limit, offset} | Owner/admin | — | — |
| `PATCH /v1/projects/{project_id}/webhooks/{endpoint_id}` | WebhookPatch | 200 WebhookPublic | Owner/admin | — | 422 |
| `DELETE /v1/projects/{project_id}/webhooks/{endpoint_id}` | — | 200 WebhookPublic | Owner/admin | — | — |
| `POST /v1/projects/{project_id}/webhooks/{endpoint_id}/rotate` | — | 200 WebhookPublic + signing_secret | Owner/admin | — | — |
| `POST /v1/projects/{project_id}/webhooks/{endpoint_id}/test` | — | 201 {event_id, delivery_id} | Owner/admin | 10/endpoint/hour | 409, 429 |

### ✅ legal_pages · 4 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /terms` | — | 200 text/html | Public | — | — |
| `GET /privacy` | — | 200 text/html | Public | — | — |
| `GET /refund` | — | 200 text/html | Public | — | — |
| `GET /attribution` | — | 200 text/html | Public | — | — |

### ✅ jm_service · 9 mounted operations

| Method and path | Body and other inputs | Success response | Access | Rate | Other handler errors |
|---|---|---|---|---|---|
| `GET /v1/health` | — | 200 {status,version,checks} | Public | — | 503 |
| `POST /v1/register` | jm_service__RegisterRequest \| null | 200 {api_key, name} | Public | 10/minute | — |
| `POST /v1/domains` | CreateDomainRequest | 201 {domain_id, name, centroids_initialized, state_size_bytes, factors, categories, actions} | JM | — | — |
| `GET /v1/domains` | — | 200 DomainListResponse | JM | 60/minute | — |
| `POST /v1/domains/{domain_id}/score` | ScoreRequest | 200 ScoreResponse | JM | 30/minute | — |
| `POST /v1/domains/{domain_id}/learn` | LearnRequest | 200 LearnResponse | JM | — | — |
| `GET /v1/domains/{domain_id}/diagnostics` | — | 200 engine diagnostics (totals, accuracy, noise_fingerprint, conservation, gate_status, centroid_count, state_size_bytes) | JM | 60/minute | — |
| `GET /v1/domains/{domain_id}/state` | — | 200 engine state (config, centroids, trackers, conservation, decisions) | JM | 60/minute | — |
| `GET /dlj_client.py` | — | 200 text/x-python attachment | Public | — | 404 |

### ✅ Framework, static mount and shared response types

GET/HEAD /openapi.json (JSON), /docs (Swagger HTML), /docs/oauth2-redirect (HTML), /redoc (HTML), and the final GET/HEAD / static mount (SPA HTML and built assets) are public with no explicit route rate decorator. Browser fragments do not become FastAPI paths. A missing static file can return 404. Only the four FastAPI docs routes are framework routes; the root mount is conditional on a built dist. `/docs` and `/#/docs` have different audiences.

ReportJSON includes report_version, metadata, overall_accuracy, category_risks, inversion, annotator_profiles, silent_risks, cost_projection, factor_names, warnings and message. WebhookPublic includes id, project_id, url, subscribed_events, active, key_version, destination_version, signing_secret_masked, rotated_at (nullable), created_at, updated_at. PredictionDecision contains id, state, current_label_log_id, source, model_version, model_confidence, dlj_confidence, tier, recommendation, decision_reason, decision_version, machine_approved_at, human_reviewed_at, assessment and human_spans_reviewed. Detail can also include original_category and original_content. Delivery history returns the paged deliveries separately from the endpoint's last 20 attempts; each attempt includes event and delivery IDs, type, number, timestamp, HTTP status, outcome, elapsed ms, next retry and bounded error summary.

### ✅ Examples for current clients

These payloads illustrate the mounted contract. Send X-Api-Key on each project request and use the project UUID returned by creation.

| Operation | Example JSON body | Expected effect |
|---|---|---|
| POST /v1/projects | `{"name":"Triage","public_domain_id":"support","factors":["clarity","difficulty"],"categories":["refund","other"]}` | 201, project UUID and initial settings version. |
| POST project labels/batch | `{"request_key":"upload-01","items":[{"label_id":"L1","category":"refund","factors":{"clarity":0.9,"difficulty":0.2},"text":"Refund requested"}]}` | 200 with results and batch_size. Replay the identical body/key to recover the committed chunk. |
| POST project labels/verify | `{"label_id":"L1","actual_action":"approve","verified_outcome":true}` | Record a human-observed outcome; the recommended action alone supplies no ground truth. |
| POST project predictions | `{"request_key":"model-run-01","items":[{"label_id":"P1","source":"triage","model_version":"v1","annotator_id":"ann-1","category":"refund","factors":{"clarity":0.9,"difficulty":0.2},"model_confidence":0.97,"text":"Refund requested"}]}` | 201, one provenance-bearing decision per scored input. |
| POST project webhooks | `{"url":"https://receiver.example.org/events","subscribed_events":["label.verified"]}` | Owner/admin receives signing_secret once. A deployment requires a reachable and permitted receiver. |

Anonymous report admission checks the multipart file before expensive analysis: a 10 MiB file bound, request framing allowance of 64 KiB, two slots, short bounded wait, 30-second upload deadline and 60-second processing timeout. Missing file/invalid CSV is 422; refusal at capacity is 503. Never reuse the anonymous historical outcome rows as live training evidence.

### ✅ DTO field dictionary

A question mark means the JSON property may be omitted. A union with null means an explicit null is representable. Default factories, additional cross-field constraints and role checks run in Python. A generated dictionary schema does not imply an unbounded user-editable object. The media/notes extensions preserve the historical input contract where specified.

| DTO | Field, type and declared constraints |
|---|---|
| `AcceptInvite` | token: string [minLength=64, maxLength=64] |
| `AddMember` | member_tenant_id: string [minLength=1, maxLength=200], role: string [pattern=^(admin\|reviewer\|annotator)$] |
| `Agreement` | pairs: list[AgreementPair], overall_kappa: number \| null, total_overlapping_labels: integer |
| `AgreementPair` | annotator_a: string, annotator_b: string, kappa: number \| null, overlap_count: integer |
| `AgreementResponse` | annotators: list[string], matrix: list[list[number]], per_category: map[list[list[number]]], lowest_pair: LowestAgreement \| null, note?: string \| null |
| `AnnotatorProfile` | annotator_id: string, total_labels: integer, verified_count: integer, accuracy: number \| null, strongest_category: string \| null, weakest_category: string \| null, last_active: string(date-time) |
| `AnnotatorThroughput` | id: string, name: string, labels_total: integer, labels_today: integer, avg_time_sec: number \| null |
| `Annotators` | domain_id: string, annotators: list[AnnotatorProfile] |
| `AutonomyTier` | red/amber/green/autonomous |
| `BulkVerifyItem` | label_id: string [minLength=1, maxLength=200], verified_outcome?: boolean \| null |
| `BulkVerifyRequest` | label_ids?: list[string] [maxItems=200], items?: list[BulkVerifyItem] [maxItems=200] \| null, action: approve/reject, reason?: string [maxLength=1000] \| null, outcome?: boolean \| null |
| `Compounding` | domain_id: string, category: string \| null, points: list[DetailedPoint], baseline_accuracy: number \| null, current_accuracy: number \| null, improvement: number \| null |
| `ConfirmRequest` | token: string [minLength=64, maxLength=64] |
| `ConfusionResponse` | categories: list[string], matrix: list[list[integer]], top_confusions: list[map[string \| integer \| number]] |
| `ConnectorConfig` | tenant_id?: string \| null, domain_id: string [minLength=1, maxLength=200], public_domain_id?: string [minLength=1, maxLength=200] \| null, project_id: string [minLength=1, maxLength=200], factor_map: map[string] [minProperties=2], category_field?: string [default=data.category], ground_truth_field?: string \| null, actions?: list[string] [minItems=1, maxItems=20] |
| `Correction` | category: string, recommended_action: string, actual_action: string, count: integer |
| `CorrectionPattern` | category: string, recommended_action: string, actual_action: string, count: integer, percentage_of_category: number |
| `Corrections` | domain_id: string, total_corrections: integer, correction_rate: number \| null, patterns: list[CorrectionPattern], top_pattern: Correction \| null |
| `CreateDomainRequest` | name: string [minLength=1, maxLength=200], factors: list[string] [minItems=1, maxItems=50], categories: list[string] [minItems=1, maxItems=20], actions: list[string] [minItems=2, maxItems=10], factor_ranges?: map[list[number]] |
| `CreateKey` | tenant_id: string [minLength=1, maxLength=200], tenant_name: string [minLength=1, maxLength=200] |
| `CurveSample` | verified_count: integer, accuracy: number, timestamp: string(date-time) |
| `DailyThroughput` | date: string, labels: integer, verified: integer, avg_time_sec: number \| null |
| `DetailedPoint` | index: integer, verified_count: integer, running_accuracy: number, timestamp: string(date-time) |
| `DistributionCategory` | name: string, count: integer, pct: number, verified: integer, pending: integer |
| `DistributionResponse` | categories: list[DistributionCategory], total: integer, imbalance_warning: string \| null |
| `DomainListResponse` | domains: list[DomainSummary] |
| `DomainSummary` | domain_id: string, name: string, created_at: number, updated_at: number |
| `EditableNerSpan` | start: integer [minimum=0], end: integer [minimum=1], label: string [minLength=1, maxLength=200], text?: string \| null |
| `ErrorResponse` | detail: string |
| `FactorStat` | factor: string, mean_correct: number \| null, mean_incorrect: number \| null, predictive_gap: number \| null |
| `Factors` | domain_id: string, factor_names: list[string], inversion: Inversion \| null, factor_stats: list[FactorStat] |
| `GuidelinesPayload` | guidelines?: string \| null, guidelines_updated_at?: string(date-time) \| null |
| `HTTPValidationError` | detail?: list[ValidationError] |
| `IngestBatchRequest` | domain_id: string [minLength=1, maxLength=200], items: list[IngestItem] [minItems=1, maxItems=100] |
| `IngestBatchResponse` | results: list[IngestResponse], batch_size: integer |
| `IngestItem` | label_id: string [minLength=1, maxLength=200], category: string [minLength=1, maxLength=200], annotator_id?: string [maxLength=200] \| null, factors: map[number] [minProperties=2, maxProperties=20], text?: string \| null, notes?: string [maxLength=500] \| null |
| `IngestRequest` | label_id: string [minLength=1, maxLength=200], category: string [minLength=1, maxLength=200], annotator_id?: string [maxLength=200] \| null, factors: map[number] [minProperties=2, maxProperties=20], text?: string \| null, notes?: string [maxLength=500] \| null, domain_id: string [minLength=1, maxLength=200] |
| `IngestResponse` | label_id: string, decision_id: string, recommended_action: string, confidence: number, factors_used: map[number], category: string, conservation_status: string, tier: string, action_policy: string, tier_status: object, auto_accepted: boolean |
| `Inversion` | trusted_factor: string, actual_signal_factor: string, interpretation: string |
| `InviteRequest` | email: string [minLength=3, maxLength=200], role: string [pattern=^(admin\|reviewer\|annotator)$] |
| `LabelContentRequest` | content_type: text_ner/text_multilabel/image_classification, spans?: list[NerSpan] [maxItems=1000], tags?: list[string] [maxItems=20], image_url?: string [maxLength=2048] \| null |
| `LearnRequest` | decision_id: string, actual_action: string, confirmed?: boolean [default=True] |
| `LearnResponse` | decision_id: string, centroid_moved: boolean, old_distance: number, new_distance: number, learning_rate_used: number, gate_status: string |
| `LowestAgreement` | a: string, b: string, agreement: number, worst_category: string \| null |
| `NerSpan` | start: integer [minimum=0], end: integer [minimum=0], label: string [minLength=1, maxLength=200], text: string [minLength=1, maxLength=32768] |
| `NextBatchItem` | id: string, text_preview: string, centroid_distance: number \| null, category: string, priority_rank: integer, annotator_id?: string \| null, recommended_action: string, confidence: number, notes?: string \| null, review_notes?: string \| null |
| `NextBatchResponse` | items: list[NextBatchItem], strategy: centroid_distance/random, total_pending: integer, note?: string \| null |
| `Overview` | domain_id: string, overall_accuracy: number \| null, total_verified: integer, total_labels: integer, categories: list[TierStatus], inversion: Inversion \| null, compounding_curve: list[CurveSample], generated_at: string(date-time) |
| `PredictionEnvelope` | project: object, tasks: list[object] |
| `PredictionImportRequest` | request_key: string [minLength=1, maxLength=200], items: list[PredictionItem] [minItems=1, maxItems=100] |
| `PredictionItem` | label_id: string [minLength=1, maxLength=200], source: string [minLength=1, maxLength=200], model_version: string [minLength=1, maxLength=200], category: string [minLength=1, maxLength=200], annotator_id: string [minLength=1, maxLength=200], factors: map[number] [minProperties=2, maxProperties=20], model_confidence: number [minimum=0, maximum=1], text?: string \| null, content?: LabelContentRequest \| null |
| `PredictionReopenRequest` | expected_revision: string(uuid), decision_version: integer [minimum=1] |
| `PredictionReviewRequest` | assessment?: correct/incorrect/unknown \| null, action?: accept/correct \| null, category?: string [minLength=1, maxLength=200] \| null, actual_action?: string [minLength=1, maxLength=200] \| null, verified_outcome?: boolean \| null, human_spans_reviewed?: boolean [default=False], expected_revision: string(uuid), decision_version: integer [minimum=1], notes?: string [maxLength=500] \| null |
| `ProjectCreate` | name: string [minLength=1, maxLength=200], public_domain_id: string [minLength=1, maxLength=200], factors: list[string] [minItems=1, maxItems=20], categories: list[string] [minItems=1, maxItems=20], actions?: list[string] |
| `ProjectImportBatch` | request_key: string [minLength=1, maxLength=200], items: list[ProjectImportItem] [minItems=1, maxItems=100] |
| `ProjectImportItem` | label_id: string [minLength=1, maxLength=200], category: string [minLength=1, maxLength=200], annotator_id?: string [maxLength=200] \| null, factors: map[number] [minProperties=2, maxProperties=20], text?: string \| null, notes?: string [maxLength=500] \| null, content?: LabelContentRequest \| null |
| `ProjectPatch` | description?: string [maxLength=10000] \| null, status?: string [pattern=^(active\|archived\|completed)$] \| null, automation_enabled?: boolean \| null, confidence_floor?: number [minimum=0.8, maximum=0.99] \| null, guidelines?: string \| null |
| `ProjectSettings` | settings_version: integer [minimum=1], description?: string [maxLength=10000] \| null, status?: string [pattern=^(active\|archived\|completed)$] \| null, automation_enabled?: boolean [default=False], confidence_floor?: number [minimum=0.8, maximum=0.99, default=0.95], guidelines?: string \| null |
| `ProjectVerifyInput` | label_id: string [minLength=1, maxLength=200], actual_action: string [minLength=1, maxLength=200], verified_outcome: boolean, annotator_id?: string [maxLength=200] \| null, reason?: string [maxLength=1000] \| null, notes?: string [maxLength=500] \| null |
| `ReconcileSignupOwner` | signup_email: string [minLength=3, maxLength=200], evidence_reference: string [minLength=1, maxLength=200] |
| `RelabelRequest` | category: string [minLength=1, maxLength=200], idempotency_token: string [minLength=1, maxLength=200], spans?: list[EditableNerSpan] [maxItems=100] \| null, tags?: list[string] [maxItems=20] \| null, notes?: string [maxLength=500] \| null |
| `ResolveDomain` | domain_id: string [minLength=1, maxLength=200] |
| `ScoreRequest` | factors: map[number], category: string |
| `ScoreResponse` | decision_id: string, recommended_action: string, confidence: number, all_scores: map[number], gate_status: string, category: string |
| `SlaResponse` | floor_pct: number \| null, current_accuracy: number, margin: number \| null, gate_status: safe/warning/critical/paused/inactive, auto_approve_active: boolean, verified_count: integer, min_verified_for_sla: integer |
| `TextTaskRequest` | label_id: string [minLength=1, maxLength=200], text: string [minLength=1], category?: string [maxLength=200] \| null |
| `ThroughputResponse` | daily: list[DailyThroughput], annotators: list[AnnotatorThroughput], summary: ThroughputSummary |
| `ThroughputSummary` | total_labels: integer, avg_per_day: number, avg_time_sec: number \| null |
| `TierStatus` | tier: AutonomyTier, category: string, verified_count: integer, accuracy: number \| null, conservation_gate_pass: boolean, conservation_reason: string \| null, next_tier: AutonomyTier \| null, next_tier_requirements: string \| null, recommended_action_policy: string |
| `ValidationError` | loc: list[string \| integer], msg: string, type: string, input?: object, ctx?: object |
| `VerifyRequest` | domain_id: string [minLength=1, maxLength=200], label_id: string [minLength=1, maxLength=200], actual_action: string [minLength=1, maxLength=200], verified_outcome: boolean, annotator_id?: string [maxLength=200] \| null, reason?: string [maxLength=1000] \| null, notes?: string [maxLength=500] \| null |
| `VerifyResponse` | label_id: string, action_taken: string, was_correct: boolean, engine_updated: boolean, new_accuracy: number \| null |
| `WebhookCreate` | url: string [minLength=1, maxLength=2048], subscribed_events: list[string] [minItems=1, maxItems=3] |
| `WebhookEnvelope` | object |
| `WebhookPatch` | url?: string [minLength=1, maxLength=2048] \| null, subscribed_events?: list[string] [minItems=1, maxItems=3] \| null, active?: boolean \| null |
| `auth__RegisterRequest` | email: string [minLength=3, maxLength=200], name?: string [maxLength=200] \| null |
| `jm_service__RegisterRequest` | name?: string [default=default] |

<a id="anno-5"></a>

### Design record · Backend endpoints

**Disposition.** Historic scope covers early label-only endpoints. The 100-operation catalog above governs current status and wire names; planned strict endpoints follow separately.

<details>
<summary>Annotation decision detail and acceptance history</summary>

FastAPI also supplies public GET/HEAD /openapi.json, /docs, /docs/oauth2-redirect and /redoc. The final StaticFiles mount at / serves built assets over GET/HEAD when dist exists. Neither framework surface has an explicit rate decorator. There is no /v1/labeling/score route. Legacy registration does not issue the key required by the review UI.

**Original acceptance criteria (actual method/path and status in the route catalog above).** All additions below require T and tenant-scoped domain resolution wherever a domain appears. No label-only route can safely identify a row. Register before the static mount.

| Phase | NEW or extended contract | Result |
|---|---|---|
| A1 | NEW POST /v1/labels/{domain_id}/sample | Demo-only seed result with public domain ID and created/existing counts |
| A2 | Extend existing single/batch ingest; NEW GET /v1/labels/{domain_id}/items/{label_id} | Exact-label detail with nullable text, verification status and existing signals; tenant mismatch is 404 |
| A3 | Extend existing pending | Optional offset, allowlisted sort_by/sort_order; preserve bare list and default limit=50 (max 200). Expose filtered total in X-Total-Count. NEW optional text_preview. Browser CSV exports the displayed page. |
| A4 | NEW GET /v1/account; NEW GET /v1/account/domains | Key-scoped summary and usable public domain list |
| B | NEW POST /v1/labels/{domain_id}/items/{label_id}/relabel; NEW POST /v1/labels/{domain_id}/items/{label_id}/content | Versioned human edits; validate source/spans against the exact row |
| B | NEW POST /v1/labels/{domain_id}/verify/batch; extend pending with search | Bounded explicit decisions, per-item known outcome, atomic commit; scoped label/annotator/text search |
| B | NEW POST /v1/labels/{domain_id}/tasks | Create bounded text work items. Initial category selection materializes a scored label through ordinary ingest in one transaction. |
| C | NEW POST /v1/labels/{domain_id}/content/batch | Validated structured content import by scoped label identity |
| Deferred | NEW GET /v1/labels/{domain_id}/export | Full filtered CSV/JSON including verified rows; separate from A3 page download |

</details>

<a id="track-3"></a>

### Design record · HTTP surface and legacy adapters

**Disposition.** Historical interfaces compared during review. This is a compatibility and unshipped-requirements record, not a second client specification. Use the mounted catalog and concrete DTOs in this chapter for requests and responses.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Below, P means /v1/projects/{project_id}, with a UUID path parameter. Child IDs always resolve inside P. Legacy label routes below are relative to /v1/labels. All new authenticated project requests use X-Api-Key. Project creation and access never accept an overriding tenant or domain_id in the body. Reject conflicting or unexpected scope fields with 422.

| Resource | Revised method/path | Existing behavior, reuse and differences |
|---|---|---|
| Create/list projects | POST, GET /v1/projects | New collection. List owned and active memberships with pagination. /v1/account/domains returns owner discovery. Legacy JM GET/POST /v1/domains uses a different store and credential |
| Detail, update, archive | GET, PATCH, DELETE P | UUID maps to Domain.id. PATCH only allowed mutable settings. DELETE archives idempotently. Owner can restore via PATCH |
| Invite, list members | POST P/members, GET P/members | New. Return pending invite identifier and delivery status. List distinguishable invite/member records. Revoke pending via DELETE P/invites/{invite_id}. Resend via POST P/invites/{invite_id}/resend |
| Role update, remove | PATCH, DELETE P/members/{member_id} | New. Check role hierarchy, project ownership and revocation under lock |
| Accept invite | POST /v1/project-invites/accept with token in body | Replaces P/accept-invite. Token identifies project. Existing /v1/auth/register creates an independent account; after signup resume acceptance. Existing /v1/admin/api-keys remains admin-header protected |
| Export, all format/filter variants | GET P/export | One operation. Required format=jsonl/csv/spacy, status per predicates above, category, annotator mapped to annotator_id, include_factors, from_date inclusive/to_date exclusive on scored_at in UTC. Null scored times excluded when time-filtered. Reject inverted dates and unsupported formats. Specify DocBin-only restrictions in guide |
| JSON batch | POST P/labels/batch | Adapt existing POST /ingest/batch, body items (1–100), with optional typed content per item and atomic validation. Return results and batch_size, with per-item scoring details. Reject duplicate IDs. Retain indexed errors, cap headers and idempotent retry. V1's labels array, pending_count and separate score call would change semantics |
| Prediction import and metrics | POST P/predictions, GET P/predictions/stats | New API over existing scoring and policy services. Bounded predictions array (1–100), common source/version, original category/spans, factors, confidence. Return imported/scored/auto_approved/pending counts after one transaction. Stats accept optional source. Extend scoped pending filters and sort whitelist, supply badge and original prediction in detail |
| Webhook create/list, detail/update/delete | POST, GET P/webhooks and GET, PATCH, DELETE P/webhooks/{webhook_id} | Replace all v1 tenant-wide /v1/webhooks CRUD. Test is POST P/webhooks/{webhook_id}/test (202). Attempts via GET P/webhooks/{webhook_id}/deliveries (paginated). Existing /v1/billing/webhook and /v1/label-studio/webhook receive provider callbacks and stay distinct |
| API reference, guide and client | GET /openapi.json, /docs, frontend /#/docs, GET /dlj_client.py | Existing FastAPI reference, new hash guide and public static file. Static routes must follow API registration or live in frontend public assets. Examples cover 401/403/404/409/422/402/429 |

**Shared project workflow routes.** Frontend calls the UUID form for collaborators. Implement as adapters to services taking an authorized project context. Keep legacy decorators, request models and OpenAPI contracts.

| Existing operation | Project-scoped adapter |
|---|---|
| POST /ingest and /ingest/batch with body domain_id | POST P/labels/batch handles one or many |
| POST /verify with body domain_id,label_id,actual_action,verified_outcome | POST P/labels/verify with the same decision fields, optional reason and expected_revision_id for concurrent edits |
| POST /{domain_id}/sample and /{domain_id}/tasks | POST P/labels/sample and P/labels/tasks |
| GET /{domain_id}/pending | GET P/labels/pending. Preserve array plus X-Total-Count, sort/filter/offset/limit and Track 2 search when landed |
| GET /{domain_id}/items/{label_id} and legacy GET /{domain_id}/{label_id} | GET P/labels/items/{label_id}. Keep static pending before legacy catch-all. New reserved words export/stats never become label IDs in this namespace |
| POST /{domain_id}/items/{label_id}/content and /relabel | POST P/labels/items/{label_id}/content and /relabel. Reuse revision token, content validation and actor-aware auditing |
| POST /{domain_id}/bulk-verify | POST P/labels/bulk-verify. Preserve the B3 body, cap behavior and processed/skipped/errors result for human review |
| Track 2 C structured content batch | POST P/labels/content/batch. Reuse the merged Track 2 validator, revision checks and response schema |
| GET /v1/dashboard/{domain_id}/{overview,corrections,annotators,factors,compounding} and /v1/domains/{domain_id}/autonomy | GET P/dashboard/{overview,corrections,annotators,factors,compounding} and P/autonomy. Reuse aggregation, enforce role on individual profiles. Expose the Track 2 IAA calculation as GET P/dashboard/iaa and guidelines via GET/PATCH P/settings/guidelines, adapting their final storage and validation |

Do not alias /v1/register, /v1/domains/{id}/score, /learn, /diagnostics or /state into these routes. The legacy state export serializes an engine, whereas P/export returns annotation records.

#### Request and response contracts

Project DTOs use snake_case, UUID strings and RFC 3339 UTC timestamps. JSON examples below are valid request bodies. Keep existing legacy schemas verbatim. Add OpenAPI operation IDs and typed error examples for every new operation.

| Method and route | Input | Success |
|---|---|---|
| POST /v1/projects | CreateProject below; name and public_domain_id 1–200 characters, description up to 4 KiB. Require unique nonempty factor/category names, 2–20 factors, 1–20 categories. Launch projects use approve/reject actions. Retain existing domains' own actions on read | 201 Project |
| GET /v1/projects; GET P | List supports limit 1–100 (default 50), offset ≥0, optional status. Sort by created_at then id | 200 list {items,total} or one Project |
| PATCH P; DELETE P | PATCH accepts name, description, status, automation_enabled, confidence_floor and append-only categories. Supply If-Match with the project settings version. DELETE archives | 200 updated Project; 204 on archive including repeat |
| POST P/members; GET P/members | Invite body {"email":"reviewer@example.org","role":"reviewer"}. Owner/admin can list members and outstanding invites using the collection pagination | 201 {invite_id,role,expires_at,mail_status}; 200 {items,total} with kind=owner/member/invite |
| PATCH/DELETE P/members/{member_id}; POST/DELETE invite routes above | PATCH {"role":"annotator"}. Resend has empty body. Accept body {"token":"<mailbox token>"} | 200 member on role change or accept; 204 on removal/revocation; 201 replacement invite on resend |
| POST P/labels/batch | Batch below. Keep IngestItem validation, including 32 KiB of UTF-8 text and engine-matching factor names. Validate content against the exact scored text and project vocabulary | 200 {results:[IngestResponse],batch_size}. One transaction for up to 100 scores and content writes |
| POST P/labels/verify | label_id, expected_revision_id (current row UUID), actual_action, verified_outcome, optional reason (≤1,000 characters) and optional annotator_id | 200 existing VerifyResponse. Store the authenticated actor separately from annotator_id. Stale/already verified is 409 |
| POST P/labels/bulk-verify | {"label_ids":["L1","L2"],"action":"approve","reason":"Reviewed source text"}. Require 1–200 unique IDs | 200 {processed,skipped,errors}. Check scope of all IDs before changes. Preserve quota-limited partial success and per-item skip reasons. Wrong project yields 404 before writes |
| POST P/predictions; GET P/predictions/stats | PredictionImport below. Optional exact source/version filter for stats | 200 {imported,scored,auto_approved,pending_review}. Stats return the counters and rates defined in [§7](#track-6) |
| POST P/webhooks; GET/PATCH/DELETE P/webhooks/{webhook_id} | Create {"url":"https://receiver.example.org/dlj","events":["label.verified"]}. PATCH accepts url, events and active | 201 {id,url,events,active,secret}; detail/patch returns public fields and last_delivery_at, last_status; delete 204 |
| POST P/webhooks/{webhook_id}/rotate-secret; POST .../test; GET .../deliveries | Rotation and test have empty body. Delivery list uses limit and offset | 200 {secret,version} once; 202 {event_id,delivery_id}; 200 {items,total}. Each item has event_id,state,attempts,next_attempt_at,last_status and bounded attempt history |

A Project contains id, public_domain_id (nullable), name, description, status, schema, role, member_count, label_count, settings_version and automation settings. Count current labels and active people including the owner. Add domains.settings_version INTEGER NOT NULL DEFAULT 1. Increment on settings changes using a conditional UPDATE. Return ETag on detail and PATCH; require If-Match for settings updates (428 missing, 412 stale). Restrict display/schema edits to admin or owner and lifecycle changes to owner. Keep project-level defaults in a dedicated settings field if Track 2 already has one. Use a single writable source for guidelines and vocabulary.

**Superseded nested CreateProject example (do not submit)**

```json
{"name":"Support triage","public_domain_id":"support-2026","description":"Review refund requests","schema":{"categories":["refund","account"],"factors":["clarity","agreement"],"actions":["approve","reject"]}}
```

**Early batch example (now also requires request_key)**

```json
{"items":[{"label_id":"L1","category":"refund","annotator_id":"ann-1","text":"Refund requested","factors":{"clarity":0.92,"agreement":0.85}}]}
```

**Superseded prediction example (see PredictionImportRequest in the current catalog)**

```json
{"source":"triage","version":"2026-11","predictions":[{"label_id":"L2","text":"Please refund this","predicted_category":"refund","model_confidence":0.97,"factors":{"clarity":0.90,"agreement":0.86}}]}
```

Each batch/prediction item can include optional content using the existing LabelContentRequest (content_type, spans, tags, image_url). Validate offsets, substring, uniqueness and content type before commit. The normalized original prediction includes that content. Set the request limit to 4 MiB for either endpoint and reject oversize payloads with 413.

Require Idempotency-Key (1–128 printable characters) on these two new import operations. Hash the validated body serialized as canonical UTF-8 JSON with sorted keys and stable array order. Insert the unique request record within the write transaction. A competing request waits for the first commit or retries after its rollback. Read the committed result on identical replay, return 409 on digest mismatch, and prune completed records after 24 hours. Reauthorize before replay. Use 422 with item_index for invalid items, 409 for a stored label ID conflict, 402 for expired trials and 429 for caps or throttling. Preserve the existing legacy ingest error mapping. Expose X-Volume-Warning and Content-Disposition via CORS alongside X-Total-Count.

</details>

<a id="mm-4"></a>

### Designed · Image import, validation and replay

**Public DTO contract.** Extend `ProjectImportItem(IngestItem)` and `PredictionItem`; batch is still `ProjectImportBatch(request_key, items)`. The canonical caption field is **text**. Accept `item_text` as an input alias for text and `item_media_url` as a convenience alias for nested `content.image_url`. Use a Pydantic *before* normalizer that can detect conflicting supplied fields and constructs `LabelContentRequest(content_type="image_classification", image_url=..., spans=[], tags=[])`. Equal duplicates are allowed. Null aliases mean absent unless a conflicting non-null value was explicitly supplied under the other spelling. Never silently drop an incompatible content discriminator. Extend the existing `LabelContentRequest.valid_image_url`; its current 2,048-character Field cap must become branch-specific. OpenAPI must describe both content shapes and their limits. `PredictionItem` retains its own required source, model_version, annotator_id and model_confidence.

~~~json
{"request_key":"camera-import-001","items":[{"label_id":"frame-42","category":"bird","annotator_id":"ann","factors":{"clarity":0.9,"difficulty":0.2},"text":"Bird on a branch","item_media_url":"https://assets.example.org/images/42.jpg"}]}
~~~

`POST /v1/projects/{project_id}/labels/batch` → 200 `{batch_size:int, results:IngestResponse[]}`. Single import uses `POST .../labels` with `Idempotency-Key` header and returns the existing single `IngestResponse`. The batch key is in the JSON body. Existing limits apply: 1–100 items, key 1–200 chars, distinct label IDs, 2–20 finite [0,1] factors compatible with the project, text up to 32 KiB UTF-8. Imports require credentials and the existing project write role/entitlement. Media is an input to content storage only. The ingest response and replay receipt contain score results, not media bytes. Use the endpoint’s existing score result fields: label_id, decision_id, recommended_action, confidence, factors_used, category, conservation_status, tier, action_policy, tier_status, auto_accepted.

| Input | Validation decision |
|---|---|
| External image | 1–2,048 characters; parse HTTPS, require a host and valid optional port, reject userinfo, whitespace/control characters, backslashes and fragments. On strict image projects accept a case-insensitive path suffix jpg/jpeg/png/webp/gif or a query key `format`/`fm` with one of those values, or `response-content-type` equal to image/jpeg, image/png, image/webp or image/gif after query decoding. No substring matching. Preserve original accepted bytes/order for signed URLs. Opaque extensionless legacy HTTPS URLs still work through the old nested contract on legacy projects. |
| Embedded image | Exact `data:image/{jpeg,png,webp,gif};base64,` followed by canonical, strictly padded standard base64; no whitespace, extra parameters or SVG. Before decoding check encoded length ≤13,981,016; then check decoded length 1–10,485,760 bytes and **sum** of decoded inline lengths ≤10,485,760 per request. Decode in bounded chunks and check JPEG/PNG/GIF/WebP signature against MIME; a signature is not a full image decoder. External URLs are never fetched or probed by DLJ. |
| Caption | Keep supplied text verbatim, with the existing text validation. For empty/missing caption use the safe final decoded URL path segment, stripping controls/separators and limiting to 200 Unicode code points. Exclude query, credentials and fragment. For data or missing basename use “Image”. Derive for storage after receipt canonicalization. |
| Strict project rules | image/single requires media, forbids tags/spans; text/single forbids typed image, tags and spans. Invalid or unsupported pairs fail closed. Legacy item discriminators still govern old projects. Format-only URL checks cannot guarantee reachability. Recommend remote images under 2 MB and 2048×2048 for comfortable browser review. |

**Bounded intake.** For all JSON routes that accept media, install one ASGI receive-layer byte limit before FastAPI buffers/parses or `require_tenant` calls `request.json()`. Include project and legacy aliases, content creation, connector callbacks and predictions. Reject declared or cumulatively received JSON bodies over **20 MiB** with 413, including chunked requests; refuse unsupported request Content-Encoding with 415. Apply this published request cap to these routes even on text imports, split large batches in clients, and retain independent limits for anonymous reports and billing. Enforce per-item and aggregate decoded limits before DB access, without echoing Pydantic's raw `input`, URL queries, base64, SQL params or request bodies in errors/logs. If inline intake is disabled, return 422 `Embedded images are not enabled` for new embedded writes; historical detail/replay remains readable. Keep low-memory validation: cap receive concurrency using the existing deployment admission pattern, e.g. two large-body permits per worker, immediate 429 with Retry-After on saturation; reserve for unknown lengths and declared bodies above 1 MiB, release on every exit. Load-test the worker-wide peak including concurrent detail and export before enabling inline input. If the hosting limit is lower, keep inline disabled and expose that capability in project detail until the 10 MiB acceptance test passes.

**Transaction and idempotency.** Phase-independent syntax checks precede DB access. Authorize, acquire tenant/payer/project locks, resolve a replay receipt by `(project.id, actor_key_id, "import_batch", request_key)`, compare digest, then on a miss validate the entire batch against the current project and reserve quota before writes. Retain row-level and optimistic guards in the normal shared write path. Commit labels, content, engine updates and receipt together via `commit_write`. Failure on item N rolls back the whole chunk. New strict requests hash the normalized **input** (including media, preserving item order), using the existing sorted compact JSON convention. Normalized flat/nested forms have identical digests. Missing aliases must disappear from the hash, preserving the exact old `payload.model_dump(mode="json")` shape including its historical nulls/defaults. Freeze sample digests from the old serializer, including nested opaque HTTPS and no content. For old receipts check the legacy digest for representable old input; never ignore a new media value to produce a match. Different bytes under the same key → 409, no second charge. Retry against the original project/account only. Preserve prediction receipts' own operation/key scheme.

**Quota and scoring.** The batch preflight must not add a second debit to `_ingest`. Either reserve the total once and pass the reservation to the shared write service, or perform the existing individual debits inside the single locked transaction after preflight. Roll back all debits on failure. `_prepare_engine` currently extends classification categories within the configured cap; preserve that behavior for single classification. Check strict multi membership and NER entity names against the locked vocabulary before any category-expansion path.

**All writers.** Use a shared modality validator from project batch/single, typed content creation, relabel and prediction import. Legacy ingest/ingest-batch and connectors must resolve the same authorized domain and apply its policy. Extend mapped image connector input with optional `image_field` (project configuration mapping a task-data field); require it on new strict image scores. Existing bound-image events may reuse stored media; an attempted source replacement requires a new logical item. Keep task binding, timestamp/replay checks, atomic config and structured successor copies. Legacy routes incapable of supplying required content return 422 before scoring rather than creating incomplete strict images. Text-task and synthetic text sample endpoints are available for compatible projects only. Bulk verify, predict, correct, reopen and both detail aliases must preserve media and attribution across revision changes. Never replace the original prediction snapshot when the human label changes. For new inline predictions store `{content_ref:<original_label_log_id>,sha256:<media digest>}` in the image portion of `Prediction.original_content`; reconstruct the existing original_content detail DTO from the immutable original LabelContent. Keep historical inline/nested JSON readers working. Keep stored media out of general prediction-list queries (select narrow columns); use the original revision FK to resolve large source content on detail without embedding another copy in every projection.

**New error contract.** Single-item errors have `{"detail":"<message>"}`; per-item semantic errors in a batch use `Item {i}: <message>` (zero-based). Existing unrelated validation errors and auth statuses retain their shape. Bind FastAPI/Pydantic handlers on the new validation paths to these messages, including parser failures, without reflecting the input.

| Status | Condition → exact detail |
|---|---|
| 422 | Invalid axes/null → `Invalid project modality`; recognized pair not shipped → `Project modality is not enabled`; unsupported pair → `Unsupported content type and label schema`. |
| 409 | Attempt to change policy after the first label → `Project modality is locked after the first label`; stale settings → existing `Project settings changed; reload and retry`. |
| 422 | Conflicting aliases → `Conflicting values for text or image URL`; missing image → `Image projects require item_media_url`; incompatible typed content → `Content does not match project modality`; unsupported adapter shape → `This operation does not support the project modality`. |
| 422 | HTTPS syntax/format fails → `Invalid image HTTPS URL`; bad embedded encoding, media type or signature → `Invalid embedded image`. |
| 413 / 415 / 429 | HTTP bytes → `Media request exceeds 20 MiB`; decoded cap → `Embedded images exceed 10 MiB`; encoding → `Unsupported request content encoding`; saturated → `Media intake is busy`. |
| 409 / 422 | Changed replay → existing `Request key was used with different content`; duplicate IDs → existing `Duplicate label ID in batch`. |

<a id="chapter-5"></a>

## 5. Frontend

✅ **Shipped · screen and component map.** HashRouter → application shell → Domain.Provider → RouteBoundary → Suspense → active screen. Global navigation owns identity and active project; individual mutations belong to a captured operation. A failed DTO or lazy chunk yields a scoped error and leaves navigation available. URL/history contains identifiers; direct navigation refetches current detail. The following inventory is drawn from App.tsx and both UI directories.

| Hash path | Rendered screen |
|---|---|
| `/#/` | Navigate → /upload |
| `/#/upload` | Upload |
| `/#/queue` | ScoredQueue |
| `/#/review/:labelId` | ReviewCard |
| `/#/dashboard` | Dashboard |
| `/#/annotators` | AnnotatorProfiles |
| `/#/health` | HealthReport |
| `/#/signup` | Signup |
| `/#/pricing` | Pricing |
| `/#/settings` | Settings |
| `/#/docs` | GuidePage |
| `/#/quickstart` | QuickstartPage |
| `/#/projects` | Projects |
| `/#/projects/:projectId/upload` | Upload |
| `/#/projects/:projectId/queue` | ScoredQueue |
| `/#/projects/:projectId/review/:labelId` | ReviewCard |
| `/#/projects/:projectId/dashboard` | Dashboard |
| `/#/projects/:projectId/analytics` | AnalyticsPage |
| `/#/projects/:projectId/annotators` | AnnotatorProfiles |
| `/#/projects/:projectId/settings` | ProjectSettings |
| `/#/projects/:projectId/predictions` | PredictionReviewPage |
| `/#/projects/:projectId/integrations` | IntegrationsSettingsPage |
| `/#*` | Navigate → /upload |

| Component family | Files and responsibility |
|---|---|
| Source and editing | TextViewer, ImageViewer, NERViewer, NEREditor, TagSelector, CategorySelector and PredictionReviewCard handle display or guarded edits. ReviewCard owns mutation lock and source of truth. |
| Navigation and upload | CsvDropzone, SignupBanner, KeyboardShortcuts and ShortcutsModal; focus-scoped actions, guarded drop and route recovery. |
| Metrics and project evidence | ConfidenceIndicator, FactorBar, TierBadge, SLABadge, MetricCard, IAAPanel, DistributionPanel, ThroughputPanel and GuidelinesPanel. |
| Operations and feedback | DeliveryHealthIndicator, ErrorBanner and LoadingSpinner distinguish empty/loading/error/terminal states. |

**Wave contract and acceptance intent**

- **B/C.** Capture credential, account generation, project UUID/public alias, operation ID and AbortSignal once per operation. Abort on rotation/unmount or project switch; verify ownership before dispatch and before all post-await storage/UI effects. Clear files, drafts, selection, receipts and caches when identity changes. Preserve old hash links, free anonymous report and sample. Keep global account checkout separate from project settings. Expose project-scoped adapters for queue, detail, bulk, verify, sample, tasks, revision/content, dashboard, autonomy, IAA and guidelines. Preserve bare pending arrays and X-Total-Count. POST project labels/batch accepts 1–100 items, 32 KiB UTF-8 text, typed content and idempotency key. Lock predecessor/engine and preserve label content, actor and lineage on every adapter. Resolve concurrency before learning. Latest verified evidence stays in accuracy until human re-adjudication. Bulk truth is per item or explicitly homogeneous; unobserved truth cannot train. Retire legacy implicit writes after callers migrate. Preserve historical bulk quota and partial-skip behavior.

<a id="anno-1"></a>

### Design record · Early annotation baseline

**Disposition.** Historical six-screen measurements and early package baseline. Current routes and shipped components are above.

<details>
<summary>Annotation decision detail and acceptance history</summary>

The original six-screen baseline was verified before implementation. Physical lines include imports, blank lines and JSX. Routes below are React paths under HashRouter, so a browser deep link looks like `/#/queue`. The root and wildcard redirect to Upload. Five sidebar links omit the item-specific review screen. FastAPI serves the compiled frontend at the final root mount.

| Existing screen | React path | Lines | What actually works |
|---|---|---:|---|
| Upload | `/upload` | 45 | Drops a CSV into free health analysis. A successful report enables scoring with an active domain. |
| ScoredQueue | `/queue` | 30 | Lowest confidence first, category selector, 30-second refresh. Status is a disabled “Unverified only” selector. Count and category options come from returned rows. |
| ReviewCard | `/review/:labelId` | 72 | Finds the label within the first 200 pending rows. Shows factor bars, recommendation, confidence, autonomy tier and gate. A accepts the recommendation and O submits the chosen override, both requiring a known outcome. E displays a notice and leaves the item pending. |
| Dashboard | `/dashboard` | 35 | Verified accuracy, verified/total labels, category ladder, sampled cumulative accuracy chart, conditional inversion and correction patterns. |
| AnnotatorProfiles | `/annotators` | 27 | Sortable summary of up to 100 annotators. Expansion explains the lack of per-category breakdown. |
| HealthReport | `/health` | 30 | Anonymous CSV analysis rendered as sandboxed report HTML, downloadable PDF. |
| **Total** | | **239** | Excludes shell, components, CSS, client and parser. |

The dark sidebar, mobile toggle, light cards, keyboard review, four autonomy badges, Recharts curve and factor bars are implemented. “Red” through “autonomous” describe review policy. Billing tiers such as trial and starter are separate. A verified outcome can leave centroids unchanged. Neither a rising chart nor an accuracy gain is guaranteed.

At the pre-Track 2 baseline the following ten gaps were recorded: no bundled interactive demo, content view, bulk decisions, queue download, source text, span display, inline relabel, page navigation, search or Settings. Existing alternatives have narrower scope: report PDF, legacy engine-state JSON, Label Studio integration, a password-style key input and an authenticated Paddle checkout API. Informational escalation is also a workflow gap. No persistent label-detail API backs deep links.

**Build contract.** Declared ranges in frontend/package.json: React and React DOM ^19.3.1, react-router-dom ^7.18.6, Recharts ^3.11.0, PapaParse ^5.7.1, Tailwind and its Vite plugin ^4.3.5, Vite ^8.3.6, React plugin ^6.3.0, TypeScript ~7.0.2. Build runs `tsc && vite build`; ES2023, no emit, unused bindings checked. Vite proxies /v1 to localhost:8000. The client uses fetch, JSON or multipart, a browser-stored key (dev env fallback) and skips the auth header for health reports. Deployment copies frontend/dist. Package scripts cover dev/build/preview.

**Baseline.** 277 pytest cases collect with the three standalone Docker clients excluded. A bare collection exits inside test_jm_docker_live.py after a partial count of 72. See [§14](#anno-10) for reproducible commands. This audit measured collection.

</details>

<a id="anno-4"></a>

### Design record · Frontend components

**Disposition.** The original workflow acceptance details follow. Modern identity, billing, detail fetching and project ownership supersede the initial key-scoped settings notes.

<details>
<summary>Annotation decision detail and acceptance history</summary>

All six existing screens take no explicit props. They use the context or router inputs shown below. Common busy/error state is local to each screen. The shared visual components make no API calls.

| Existing component | Inputs, state and calls | Render / reusable behavior |
|---|---|---|
| App | No props. Domain ID, API key and mobile-open state. Persists domain and key in localStorage. No fetch. | Sidebar, password input, active-domain input, navigation, Suspense; mounts lazy Dashboard. Domain.Provider exposes domainId/setDomainId. main.tsx mounts the app in StrictMode/HashRouter. |
| Upload | Domain context. File, report, progress, busy/error. uploadForAnalysis, parseIngestCsv, ingestBatch. | Drop, report warnings, batch progress, queue navigation or File passed to HealthReport. Reuse the report preview for samples. |
| ScoredQueue | Domain, items, category, busy/error. getPending(limit=200), refresh timer. | Table, confidence bar, filters, manual refresh, encoded review link. Move sort/filter before server pagination. |
| ReviewCard | Domain and labelId. Item, loaded domain/ref, pending list, tier, known outcome, override, busy/error/message. getPending, getAutonomy, verifyLabel. | Factor/recommendation panels, shortcuts and next-item navigation. Put source beside factors and preserve explicit correctness. |
| Dashboard | Domain, overview, corrections, curve, busy/error. Parallel getOverview/getCorrections/getCompounding. | Metric cards, ladder, chart, correction patterns and inversion alert. Chart uses overview.compounding_curve; separate curve response supplies baseline/current. |
| AnnotatorProfiles | Domain, items, sort key/direction, expanded ID, busy/error. getAnnotators(limit=100). | Click/Enter sortable headers, expandable summary table. Reuse header interactions in Queue, delegate ordering to query. |
| HealthReport | Optional location.state.file, current file, HTML, busy/error. uploadForReport/downloadReportPdf. | Sandboxed srcDoc iframe, PDF Blob download with URL revocation; reuse download mechanics for CSV. |
| ConfidenceIndicator | value number; stateless | Percent and clamped bar. |
| CsvDropzone | onFile(File), optional busy; drag-active state and hidden input ref | File picker and drag/drop. Guard both entry paths when adding sample loading. |
| TierBadge | tier (autonomy enum); stateless | Uppercase policy badge. Use a separate billing-plan label in Settings. |
| MetricCard | value (ReactNode), label, optional detail; stateless | Labeled metric with optional explanation. |
| ErrorBanner | nullable message; stateless | Alert or nothing. Extend API error formatting for structured quota details. |
| FactorBar | factor, value; stateless | Human labels and ranges for four canonical factors; fallback for arbitrary names. |
| LoadingSpinner | No props or state | Accessible loading status. |

**NEW component sequence.** A2 TextViewer renders escaped pre-wrapped text or the missing-content state. B adds CategorySelector and read-only NERViewer. C adds NEREditor, TagSelector with domain vocabulary and ImageViewer (fit/zoom; image classification choice stays separate from drawing). Keep verification controls reachable on mobile. Disable A/O/E shortcuts while focus is in the annotation editor, text inputs or editable regions.

**NER decision.** Use native React fragments and mark elements with visible entity names for the first viewer. Define half-open Unicode code-point offsets into the exact stored string. In JavaScript slice Array.from(text); in Python slice the original str. For “Aspirin was recorded.”, [0,7) yields “Aspirin”. Sort validated spans, emit intervening plain text and preserve newlines. Reject out-of-range, empty, overlapping and unknown-label spans in the first contract. Cover emoji, combining characters and repeated substrings. Provide a textual entity list and keyboard focus for selecting a highlight. No DOM selection is needed to read a label.

react-text-annotate offers text and token annotation controls. Its upstream 0.3.0 package declares React/React DOM ^16.8.0 peers; this project declares ^19.3.1. Popularity is unverified and does not establish compatibility. Before C, prototype drag selection across elements, convert browser UTF-16 positions to code points, test keyboard-only range editing, undo and focus on touch. Adopt a library only if it passes those cases on this stack. [Upstream project](https://github.com/mcamac/react-text-annotate) · [Package manifest](https://raw.githubusercontent.com/mcamac/react-text-annotate/master/package.json)

#### Sample experience (NEW A1)

Bundle a single public fixture at frontend/public/demo/sample_data.json, emitted by Vite under frontend/dist/demo so the service and browser can read identical bytes. Generate deterministically at development time and commit the generated fixture. No API credential, patient record or external dataset. Use fictional medical note fragments; the exercise is identifying mentions, not providing clinical advice.

| Fixture property | Contract |
|---|---|
| Domain and keys | Reserved demo domain medical-ner-demo-v1 scoped per tenant. 500 unique med-0001…med-0500 IDs. Four rotating fictional annotators demo-ann-1…4. |
| Categories | 167 MEDICATION, 167 CONDITION, 166 TEST, rotating by index. |
| Text / target mentions | “Aspirin appears in the medication list.” → Aspirin; “The note mentions asthma.” → asthma; “A glucose test is listed.” → glucose test. Vary synonyms and sentence frames from a bounded template bank. Each row records the exact mention start/end and class as fixture metadata for B. |
| Factors | CSV columns factor_model_confidence and factor_item_difficulty. Generate reproducible decimals in [0,1] with variation within each category, e.g. 0.92/0.18 for an explicit mention and 0.42/0.81 for an ambiguous one. JSON ingest strips factor_. |
| Evidence | Of 500 rows give 400 a synthetic known verified_outcome (e.g. 320 true, 80 false spread across categories), other 100 blank. Select 12 interleaved examples for the live queue. Clearly mark historical outcomes and sample origin. |

On Upload, “Try with sample data” loads the fixture, projects report columns with Papa.unparse, creates a CSV File and runs existing anonymous analysis. Visitors can inspect the report/PDF without a key. “Score 12 sample labels” shows quota cost and requires a DLJ labeling key; a missing key leaves the report available. On success switch to the returned public demo domain and open Queue. Never replace the user’s working domain on a failed request. Only explicit verification of a queued item changes the live dashboard. The 500-row report can show historical accuracy immediately.

The NEW sample endpoint accepts only the reserved domain and server-owned fixture, in one transaction through the existing scoring/quota path. Reject an unrelated pre-existing domain at that name; mark provenance in a NEW namespaced config_json entry without disturbing DomainConfig serialization. Lock/serialize creation per scoped demo, use stable IDs, handle concurrent insert conflicts by re-reading committed state, and on retry return the original result without charging or resurrecting reviewed items. No quota bypass. A1 can ship before text persistence; after A2 the same seed writer passes text, with an idempotent content-only fill for already seeded sample rows.

#### Settings experience (NEW A4)

* Account reads the authenticated key’s tenant ID/name, tier and created date. Mask a locally entered credential, show “key configured” when appropriate, and offer replace/clear local credential. Never return key_hash, plaintext or a synthetic last-four from the server. Copy can only use the locally held secret after explicit user action; omit copy if unavailable.
* Usage reads labels_today and labels_this_month on the authenticated key. Present zero when period keys differ from current UTC day/month. Show trial duration (created_at + 14 days), 50/day, paid monthly cap (10k/100k/1M) or unlimited Scale/Enterprise. Label these **key** counters. Cumulative rows, verified count and accuracy per domain are available via overview. Historical usage by billing cycle, invoices and a billing portal link require new integrations.
* Upgrade button requests existing checkout-url for a configured tier. Disable repeated clicks, show configuration/upstream failures, redirect to checkout_url, and surface “awaiting confirmation” on return. Reload account on focus or bounded polling. Paddle’s signed subscription.created links the active key by customer ID or tenant fallback and sets tier; updates/cancellation follow their handlers. Signature checking currently depends on PADDLE_WEBHOOK_SECRET. Never grant access from redirect parameters.
* Domain picker needs a tenant-scoped public-ID list. Domain.domain_id can be irreversible and domain_name can equal that same hash. NEW nullable Domain.public_domain_id plus additive migration; populate from public input on ingest/connector configuration before hashing. For old rows, resolve a user-entered name with scoped_domain_id and record it only on a tenant-matched lookup. Show unresolved rows as needing a name; never feed a hash back through scoping. Entering a new ID selects it; first valid labeling ingest creates the domain. Team-wide export and destructive domain deletion are separate future work.
* Settings lives at NEW hash route /settings (public link /#/settings). Fix existing bare /settings links in trial_guard, email templates and other backend messages. Update legal copy about stored content/localStorage before enabling capture; present current data handling accurately.

</details>

<a id="track-5"></a>

### Design record · Frontend and developer interface

**Disposition.** The SDK lives in backend/static. The mounted route table above supersedes proposed /projects/new and /invite/:token. Additional list counts and role displays were requirements, not guaranteed response fields.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Keep HashRouter. Add /projects, /projects/new and /projects/:projectId with nested upload, queue, review/:labelId, dashboard, annotators and settings. Mount one authorized project provider there and reuse screens through a scope-aware API adapter. Make links and post-action navigation relative to that scope, encoding IDs once. Keep /signup, /health, /docs, /invite/:token and account /settings global. Preserve every old hash entry including review ID, query and intended destination. Retain the legacy upload flow for anonymous/sample or new-domain work. For authenticated aliases match the saved public name to an accessible project first. If ambiguous, use a chooser with a return target. Never open a same-named label from another project. A missing or revoked explicit UUID gets a scoped error. On key change clear selection/cached data. Cancel in-flight requests or discard stale responses, reset pagination on switch. Keep project settings separate from account checkout.

`frontend/src/api.ts` prefixes /v1, reads X-Api-Key and generally decodes JSON with exceptions for PDF/HTML. Add an authenticated download method with blob/stream handling, preserve error decoding and pending X-Total-Count. Avoid placing keys in download URLs. Keep page-CSV and whole-project export clearly labeled. Use existing NERViewer, CategorySelector, Settings and ReviewCard. Bind later editors only once their Track 2 contracts exist.

**Guide and downloadable client.** Serve /#/docs for humans, /docs for Swagger, /openapi.json for tooling and /dlj_client.py from the static build. Include the client as a source-controlled frontend public asset. Its constructor takes base_url and api_key. Expose create_project, upload, verify, import_predictions and export. POST upload scores within the call. Chunk uploads at 100 items, use one replay key per chunk, and return which chunks committed if a later chunk fails. Stream export bytes to a temporary file and rename after success. Apply request timeouts, surface HTTP status and structured detail, and retry imports only with the same payload and key. Publish a runnable quickstart and test it through actual HTTP with a fresh trial account.

**Screen ownership.** Project List shows status, effective role, current label count and active member count. The authenticated home opens its sole accessible project or the chooser when several exist; zero projects offers Create and the legacy upload flow. Project Settings owns members, guidelines, automation, integrations and export. Global Settings owns API keys, account usage and checkout. Queue keeps separate page-CSV and project-export actions. Show read-only reasons on closed projects. Disable actions the caller cannot perform. Server authorization applies independently.

</details>

<a id="mm-5"></a>

### Designed · What reviewers see

~~~text
App → project route → Domain.Provider (project UUID, alias, axes, enforcement, capabilities)
  Projects → creation form → content selector + allowed schema selector
  ProjectSettings → versioned settings form → editable axes until first label
  Upload → authenticated project CSV/JSON import → chunk summary → ScoredQueue
  ScoredQueue → compact row (caption, media kind, score) → identifiers-only navigation
    ReviewCard → ImageViewer or TextViewer → category / set / span editor → verify
  PredictionReviewPage → focused PredictionReviewCard → same source preview and correction controls
~~~

Extend `frontend/src/api.ts` types **and runtime decode** for project, pending, smart-queue, prediction-list and detail. Proposed public typings:

~~~ts
type Modality = { content_type: 'text'|'image'; label_schema: 'single'|'multi'|'ner'; modality_enforced: boolean }
type ProjectMediaSettings = Modality & { modality_locked: boolean; inline_images_enabled: boolean }
type MediaSummary = { media_kind: 'text'|'image' }
type ImageDetail = { content_type: 'image_classification'; image_url: string; spans: []; tags: [] }
~~~

Summary/list/create return `Modality`; detail additionally returns both flags. Settings response returns axes + version; refresh detail after updates. `modality_locked` is informational; the server rechecks every write. Resolve context from GET project for a UUID route (resolve old alias first); clear on switch, abort previous request and reject late completions. While loading show skeleton; on incompatible DTO show the existing recoverable route error. No fallback to a previous project's mode. Legacy per-row media takes precedence over project default. Queue/detail transport uses `media_kind` on summaries and existing `content.image_url` on detail; no large URL/bytes in summaries, localStorage, history.state, analytics events, receipts or toasts.

* **Create/edit.** In the existing inline `Projects.tsx` form put “Content type” and “Label schema” after categories. Default Text / Single; show enabled combinations only. Help text: “Choose what reviewers will label. This locks after the first item.” The settings screen shows locked values and handles a stale version or a concurrent first import by refetching. Quickstart explicitly creates text/single and keeps the original sample experience.
* **Import.** `Upload.tsx` currently analyzes a file as an anonymous health report before project scoring. Add a direct authenticated project-import branch for modality files, accepting 1–100 items per chunk. Never post media CSV/JSON to free report analysis. Keep anonymous text-report upload and sample behavior. `csv.ts:parseIngestCsv` must reserve `item_media_url`, `item_text` and modality-specific columns before inferring numeric factors. Both explicit `factor_*` and unprefixed factors work. Show row-indexed validation locally, count/byte chunk by the server rules, reuse exact chunk/key on retry, display committed prefix on failure. Rotate account/project or unmount → abort; erase file input, preview and chunk state, never carry a file in history.
* **Queue/detail.** Row shows caption and “Image”; selecting the row opens the existing review screen. Center the preview above category buttons, max height 400px, max width 100%, object-fit contain. Render an escaped caption even if remote loading is declined. `ImageViewer({imageUrl, altText, category, readOnly:true})` uses lazy decoding/loading, no-referrer, a new keyed instance on revision/URL changes, and a visible loading state. Escape text in JSX. “Image not available” shows a sanitized host/basename or “Embedded image”; preserve buttons and keyboard focus. Cross-origin display requires an anonymously viewable HTTPS resource; hotlink policy, expiration or remote availability can still prevent display. Do not attach API credentials or fetch an image on the server. A browser request discloses the reviewer's IP to the remote host; disclose this at import and offer “Load external image” before first remote display per project/session. Local data URI needs no network consent. Account switch clears consent. Canvas pixel access is outside this release.
* **Edits.** Strict image/single shows category/action/explicit outcome only. Strict text/single suppresses NER/tag editing; legacy detail keeps today's per-item dispatch. Multi and NER editors below inherit `ReviewCard` mutation lock, dirty navigation, 409 reload and ownership checks after every await. The prediction card loads detail on focus/selection with cancellation; shortcuts ignore text inputs and unfocused cards. Smart ranking, SLA and dashboard accuracy use the existing score/evidence for image/single; the preview never supplies a human outcome.

<a id="chapter-6"></a>

## 6. Quality Engine Integration

✅ **Shipped · from factors to a decision.** The ordered coordinates are the project's configured numeric factors in [0,1]. Public ingest validates keys, finiteness, range and schema. `JudgmentMemoryEngine.score(factors, category)` constructs a vector in config order (internal missing-factor fallback 0.5). For category c and action a the centroid starts at [0.5,…,0.5]. Distance is Euclidean. The softmax over −distance²/τ (default τ=0.1) yields action scores; take the largest as recommendation/confidence. Scoring records the decision and increments the decision count. Read-only scoring and smart ranking do not train. Payload text, pixels, image URLs, spans, notes and UI state never enter this computation.

**Learning.** A human supplies the actual action and independent verified outcome. Update the selected category/action centroid toward the stored factor vector: new = old + η(vector − old), with default confirm/override rates 0.05/0.01. Agreement with a recommendation and correctness of a label are distinct. Welford trackers and conservation use human evidence; model-only approval does not populate correctness. Preserve negative evidence across revisions until human re-adjudication. Compare confidence, recommendation, distances and tracker deltas from identical initial state when verifying engine parity. SHA-256 of frozen root `jm_core.py`: `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

**Conservation & displayed floor.** V = verified count, α = fraction of configured categories covered, q = rolling accuracy over up to 400 human outcomes. The engine uses the calibrated constant 23.53 in θ_min = 23.53/max(αV,0.001) and tests αqV ≥ θ_min after V ≥ 50. Below 50 it returns warmup. With positive baseline established at the first full window, L2 guards rolling accuracy against 0.70 × baseline; L3 guards the most recent 20 outcomes against 0.85 × baseline. The checked-in implementation fixes the coefficient at 23.53. The four design sources and engine do not supply an empirical derivation of that coefficient; retain it as a frozen input. No service-level probability guarantee follows from it. At ordinary positive coverage the engine inequality rearranges to q ≥ 23.53/(αV)². The project SLA endpoint separately displays 100 × 23.53/max(αV,0.001); its percentage is not the algebraic rearrangement of the engine test.

**Autonomy.** Failed gate, missing accuracy or fewer than 30 observed outcomes yields red/human_review; otherwise amber/confirm until at least 100 and .80 accuracy qualify for green/confirm. At least 200 with the autonomous threshold (default .85) qualify for auto_accept. Demotion thresholds are .83 and .75; a gate failure returns red. Policy output is still subject to §7 before a model prediction is approved.

**Smart sampling.** `next_batch` considers current, scored, unverified pending rows including eligible pending predictions. Filters apply before ranking. At 20 verified engine observations across the project, rank farthest from the nearest compatible action centroid, with a deterministic project/label hash tie-break. Invalid/unavailable geometry ranks last. Before activation use stable hash order reported as random. n defaults to 50, caps at 200; offset is nonnegative. Unsupported strategy returns 400. Ranking returns a preview and uses no training or quota.

**SLA badge.** One SQL statement snapshots effective verified evidence and engine states. Below 50, floor and margin are null, status inactive. Above warmup, current accuracy uses the latest 400 observations; margin is percentage points above the project floor. A failed engine gate or negative margin pauses, >10 points is safe, 5–10 warning, 0–<5 critical. Displayed automation additionally requires an active, opted-in project and eligible active paid payer. This descriptive badge is not a contractual service-level guarantee.

<a id="chapter-7"></a>

## 7. Predictions and Automation

✅ **Shipped.** Store original model source, version, category, content and model confidence separately from DLJ confidence, tier, recommendation, gate snapshot and decision reason. Import DTOs and 201 response are in §4. The five decision gates, after project opt-in and active paid entitlement, are (1) model confidence ≥ configured floor (.95 default, .80–.99), (2) DLJ confidence ≥ .80 and recommendation approve, (3) autonomous tier, (4) passing conservation, (5) eligible named annotator with ≥30 verified and ≥.80 scoped accuracy. A machine approval sets state and timestamp, produces its outbox event in the same transaction and supplies no verified outcome.

The database states are pending, auto_approved and human_reviewed. The review queue separately projects pending_review, reopened, accepted, corrected or unknown. Read the original assessment alongside action and explicit observed outcome. Compare both current revision and decision version on review/reopen; 409 prompts reload. Reopen can return a completed decision to pending and increments its version; retain machine history. Dedicated human review, identical replay and reopen have no scoring charge. Overrides must distinguish a corrected category from the observation of the model's original answer. Keyboard handlers on the focused review card handle a/c/r/n/p, arrows and Escape, ignore inputs/modifiers, and release on blur or unmount.

**Wave contract and acceptance intent**

- **D/F predictions.** POST project predictions (1–100), GET stats, POST reopen/review with expected revision and decision version. Separate model confidence from scored confidence. Automation defaults off; require model floor (default .95), approve recommendation, autonomous tier, passing conservation and named-annotator eligibility. Persist the original input and decision. Machine approval never supplies a human outcome. Charge only new scored imports; human verification/reopen/replay add no scoring charge apart from existing bulk policy. Preserve machine approval history, unknown human assessments and explicit review of spans.

<a id="track-6"></a>

### Design record · Prediction review and quota accounting

**Disposition.** Use the actual success DTO in §4. The original reopen-only-after-machine-approval restriction was expanded to completed human reviews. Counts and filters below distinguish original acceptance targets from the shipped stats.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

1. Validate the project, role (reviewer or higher), active status, replay key, unique label IDs, schema, content and confidence. Insert immutable input and score each item through the same service as labeling_router._ingest. Reserve owner capacity in the same transaction as label creation. Persist DLJ confidence, recommended action, tier and gate result as returned at scoring time. Preserve the model's confidence independently. A failed item rolls back all item scores, engine changes, quota reservations and outbox records.
2. Automation defaults off. A machine approval requires project opt-in, model confidence ≥ floor (default .95, configurable .80–.99), an approve recommendation, an unpaused engine, autonomous tier, passing conservation checks and the existing named-annotator eligibility test. Reuse evaluate_domain and _ingest's eligibility result. Autonomous normally requires at least 200 human outcomes at the default .85 accuracy threshold; rolling demotion can override it. Named annotators require 30 verified at ≥.80 accuracy in scope. Attach a stable reason such as disabled, below_model_floor, policy_requires_review, action_requires_review or approved to each decision.
3. Add Prediction.state with checked values pending, auto_approved, human_reviewed and a monotonically increasing decision_version. A machine decision sets state and machine_approved_at only. It neither sets verified_at nor calls verify_and_learn. Queue predicates exclude machine-completed items from ordinary pending; machine audit and prediction-only filters include them explicitly. Preserve the original snapshot on all revision paths. Clarify to reviewers that accepting an annotation and observing whether the DLJ action was correct are separate inputs.
4. Implement POST P/predictions/{prediction_id}/reopen for reviewers. Require expected decision_version, return 200 with incremented version and pending state after a machine approval; return 409 for other states or stale version. Preserve machine_approved_at for history. POST P/predictions/{prediction_id}/review takes expected_revision_id, decision_version, assessment (correct/incorrect/unknown), actual_action, verified_outcome and optional corrected category/content and reason. Lock the prediction and current revision, apply any edits through shared revision services, verify the final row once and update provenance in the same transaction. A human correction through the annotation UI alone updates the current pointer and returns to pending. Competing review/revision loses with 409. Store the actor's key UUID, human_reviewed_at and explicit assessment of the original output. Return prediction_id, state, revision_id, decision_version. Project and legacy human verify paths that lack a model assessment record unknown; bulk human approval alone cannot certify predicted NER spans for DocBin. Persist a human_spans_reviewed boolean default false, set only on explicit span adjudication.
5. Charge one unit on each newly scored import item using the owner binding or current legacy billing principal. Single human verification, dedicated prediction adjudication, reopening and identical import replays incur zero additional scoring units. **B3 bulk review has its own existing quota behavior:** both legacy and project bulk adapters reserve one unit per processed bulk decision, skip already-verified/ineligible rows, and return partial success at the cap. Keep this separate from atomic import. At 49/50, a two-item import commits zero; two eligible B3 bulk decisions process one and report the skipped one. Do not route prediction adjudication through bulk.

**Metrics and UI.** GET stats returns total_imported, pending, machine_only, human_reviewed, auto_approved_ever, auto_approve_rate, assessed_count, model_accuracy, avg_model_confidence and avg_dlj_confidence. Count each prediction once for the selected project/source/version. pending + machine_only + human_reviewed = total_imported. auto_approve_rate uses auto_approved_ever / total_imported. model_accuracy uses correct / (correct + incorrect) among human assessments. Return null for a zero denominator. DLJ action accuracy remains the existing human-outcome measure. Show both denominators. Add prediction ID, state, original model output, revision and decision version to authorized item detail. Queue adds origin=all/human/prediction, optional prediction_state, and prediction_confidence sorting with nulls last and row-ID tiebreaker. ReviewCard offers Accept, Correct and Reopen according to state/role. Keyboard actions must yield focus to the active Track 2 editor.

</details>

<a id="chapter-8"></a>

## 8. Export and Integration

✅ **Shipped · interchange on the wire.** Project export uses format=jsonl/csv/docbin, review_status, category, annotator, date_from/date_to, include_factors and browser_fallback. It selects current revisions using a snapshot, spools before response headers, then streams the attachment. The implemented row keys are root_label_id, current_label_id, source, text, category, annotator_id, recommended_action, actual_action, verified_outcome, confidence, scored_at, verified_at, revision_at, content, review_state, model_confidence, dlj_confidence, human_spans_reviewed and optional factors. The notes extension adds notes and review_notes. Content nests content_type, spans, tags, image_url. Null outcome and false have different meanings. Two leases per project, 500-row cursor pages, five-minute deadline, 5,000 docs/16 MiB source text, 32 MiB fallback. Empty CSV has a header; JSONL can be empty. A missing optional spaCy dependency returns 501.

Webhook transactions create immutable event bytes and an eligible delivery per subscribed active endpoint. Envelope fields are event_id, event_type, project_id, occurred_at, schema_version and data. Sign UTF-8 timestamp + period + canonical_body with HMAC-SHA256 and send `Paddle-Signature: ts=<timestamp>;h1=<hex>`. This outbound contract is separate from inbound Paddle verification. No redirects; public HTTPS validated again at connect; Fernet protects stored signing secrets. Timeout 10 s, retries at 10/60/300 s after the initial try; 30 s fenced lease, bounded parallelism. Network/DNS/timeouts and retryable HTTP responses are recorded, terminal failures stop retries. Receivers deduplicate event_id. Rotate increments key/destination version and fences old deliveries. Only create/rotate reveal the signing secret; subsequent GET list exposes the mask.

**Delivered event data.** Human verification carries label_id, revision_id, actual_action and verified_outcome; prediction adjudication can also include prediction_id. Machine approval carries prediction_id, label_id, model_version, model_confidence and dlj_confidence. Treat delivery as at least once. Retry HTTP 408, 429 and 5xx as well as timeout/network/DNS errors; other HTTP non-2xx results are terminal. The exact secret issued to the subscriber is the UTF-8 HMAC key. The request also carries X-Webhook-Key-Version.

Serve the executable requests-based SDK from `backend/static/dlj_client.py`. DLJClient exposes create_project, upload, verify, import_predictions, export, save_export, get_status and list_webhooks. Upload carries a generated replay key per chunk, reports committed prefixes on failure and retries transient failures with bounded backoff. Default timeout is 30 seconds. verify requires an observed boolean via its metadata argument. Save downloads atomically; never redirect a credential to another host. The public hash guide, FastAPI Swagger and machine schema are different surfaces.

**Wave contract and acceptance intent**

- **D/F export.** GET project export emits one current revision per logical item with root/current IDs, source, full text, category, annotator, action, true/false/null outcome, scores, UTC times, content/spans/tags/image, review state and optional factors. Filter by review status, category, annotator and UTC date interval. Stream JSONL/escaped CSV in a single snapshot, pages of 500, two slots/project, five-minute deadline. Preflight English tokenizer DocBin alignment and human span adjudication; cap at 5,000 documents or 16 MiB text and verify on Hobby. Browser fallback limited to 32 MiB. Guide at /#/docs, Swagger at /docs, schema at /openapi.json, client at /dlj_client.py. Client reports committed chunks, retries with the same key, and saves downloads only after completion.

**Wave contract and acceptance intent**

- **E/F delivery.** Register project webhooks, test sends and paginated deliveries. Emit label.verified, prediction.auto_approved and webhook.test in the business transaction. Persist canonical bytes, HMAC-SHA256 of timestamp + period + body, event ID and key version. Disclose signing secret once. Five endpoints/project, ten tests/endpoint/hour. Validate public HTTPS at connection time, disable redirects, encrypt secrets. Four sends maximum with immediate/10/60/300-second schedule, 10-second timeout, 30-second fenced lease, one send/endpoint and four concurrent sends. Rotate/archive cancels stale pending/leased work; receiver deduplicates. Retain terminal metadata 30 days. No source text, bearer tokens or raw response bodies in logs.

<a id="track-4"></a>

### Design record · Project export

**Disposition.** Field proposals, optional counters, browser download UX and resource acceptance history. Use the shipped row dictionary above; excluded/count headers, staging resource targets and optional packaging are design targets until evidenced.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Export one **current revision** per logical item, scoped by owner tenant and internal domain. Filter superseded_by IS NULL and left join label_content on label_log_id = label_log.id. The following dictionary was the original field proposal. The actual keys and encodings are in the current interchange contract at the start of this chapter. The CSV header uses the same field names. Nullable CSV scalars are empty, and structured values use JSON inside quoted CSV cells.

| Export key | Source and semantics |
|---|---|
| label_id, revision_label_id, revision_id | Original label_id at the root of this revision chain, current row.label_id, current row.id UUID. Follow prior_revision_id or the reverse superseded_by link within the same domain for older connector revisions. source_task_id and annotation_id are separate grouping fields. Emit one row per current revision even when a task has multiple annotations |
| source_task_id, annotation_id, annotator_id, category, text | Nullable stored values. Text is the full stored string |
| recommended_action, actual_action, verified_outcome | Direct fields. False is a recorded negative outcome. Null represents unknown |
| confidence, factors | Nullable DLJ confidence and factors_json. Factor names are project-specific. Use confidence as the wire name. Omit historical tier and label creation time because neither is stored |
| scored_at, verified_at, revision_at | Distinct nullable times, UTC ISO 8601. No fabricated creation time for unclassified tasks |
| content_type, spans, tags, image_url | Optional LabelContent fields content_type, spans_json, tags_json, image_url. Return null type/URL and empty lists when absent. Preserve exact code-point offsets and stored text |
| review_state | Derived current workflow state as defined below. Keep machine decisions distinct from known outcomes |

JSONL is UTF-8, one object plus newline per row. CSV quotes commas, quotes and embedded newlines and escapes formula-leading text cells, as the page export already does. Offer JSONL for exact unescaped strings. include_factors=false omits the field/column. Use a single DB snapshot with ordered, bounded fetches and an independent read-only session closed on disconnect. Document cost and concurrency limits. Validate filters before headers. Use a safe generated filename, attachment disposition and explicit media type. The existing queue CSV exports only the visible page.

For DocBin require text_ner and eligible current records, default to human-reviewed training data, and report excluded non-NER records in the dialog. Use a declared tokenizer/language (English blank tokenizer for v1), strict char_span alignment and nonoverlapping entities. Preflight the snapshot before download, returning 422 with bounded row/span diagnostics for unrepresentable data. Preserve valid empty entity lists. Enforce a measured document/byte cap and clean temporary files on cancellation. Round-trip DocBin with the same vocabulary and test emoji and punctuation. Pin spaCy in the Railway build and measure image/startup/RSS. CoNLL, COCO and Label Studio JSON remain deferred.

**Wire format and resource limits.** Use application/x-ndjson, text/csv; charset=utf-8 and application/octet-stream respectively. Set Cache-Control: no-store. Use a project UUID and UTC date in the download filename. For JSONL/CSV read in 500-row pages in one consistent transaction (PostgreSQL read-only REPEATABLE READ; SQLite explicit read transaction). Use a keyset ordered by immutable row UUID. The authorization check is part of opening the snapshot. Bound download lifetime to five minutes and close cursors on cancellation. On browser downloads request File System Access streaming when available. For the Blob fallback, read response chunks with a 32 MiB ceiling, cancel above it and display the equivalent authenticated client command with an API-key placeholder. Release object URLs after saving. Support two simultaneous exports per project via expiring database slots keyed by project and slot number. Return 429 if both are taken. Stable snapshots are per download; a subsequent download can include intervening edits.

Use an explicit English tokenizer for launch DocBin files. Start with a 5,000-document or 16 MiB combined source-text cap, whichever is reached first. Return 413 before headers, with the matching count or byte bound and the available narrower filters. Validate RSS and duration for the launch caps on the staging Railway service. Reduce configuration caps if the measured peak exceeds half the container memory budget. Include processed document count in X-Export-Count for DocBin, expose it via CORS and show excluded-type counts separately. CSV includes a header on empty output; empty JSONL is zero records. A valid empty DocBin decodes to zero documents.

For format=spacy accept verified or overridden; reject other explicit status values with 422. Default status to verified, restrict to text_ner and require a human-adjudicated entity set. Track 2 human NER annotations that are verified qualify. Imported predictions qualify only after an explicit human assessment of the final spans. Report non-NER exclusions via X-Export-Excluded; apply the same authorization, query and snapshot to both counts. Unreviewed model spans never enter a training download by default. For JSONL/CSV, review_state precedence is verified, auto_approved, pending, unclassified. The overridden filter selects a subset of verified records. Snapshot the stored model source/decision in prediction stats and detail; the public export schema remains the versioned dictionary in this section.

</details>

<a id="track-7"></a>

### Design record · Project webhooks

**Disposition.** Delivery protocol updated to the implemented header/envelope. Timing jitter, monitoring and deployment-level rekeying require operational evidence; tables use the singular names in §3.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Store events and deliveries in the labeling database. In the transaction that changes the label, enqueue one immutable event and one delivery per active subscribed endpoint. Use the human verification transition for label.verified, the new prediction decision for prediction.auto_approved, and a fresh request UUID for webhook.test. Emit after a successful row transition from every entry point including bulk and connector verification. A replay or rolled-back change yields no extra event. Schema additions include webhook_attempts(delivery_id, attempt_no, started_at, finished_at, outcome, http_status) with a composite primary key. Persist the event's exact UTF-8 body bytes or its canonical JSON string once at creation.

| Event | Transition key | data fields |
|---|---|---|
| label.verified | Current revision UUID + first human verification | label_id, revision_id, actual_action, verified_outcome, confidence |
| prediction.auto_approved | Prediction UUID + decision_version | prediction_id, label_id, revision_id, model_confidence, dlj_confidence, tier |
| webhook.test | Unique test request ID | test=true |

The shipped envelope is event_id, event_type, project_id, occurred_at, schema_version and data. POST application/json. Send Paddle-Signature (ts/h1) and X-Webhook-Key-Version. The HMAC key is the UTF-8 encoded secret as issued. Compare the HMAC over timestamp, period and exact received bytes in constant time; a receiver can enforce a ±300-second freshness window and must durably deduplicate the event ID. Duplicate delivery is possible after a receiver commits and before the sender records success. The original id/type/created_at fields, X-DLJ headers and base64-decoding instruction have been retired.

Extend jm_service.lifespan to supervise a separate dispatcher alongside the hourly scheduler. Poll every two seconds, claim up to four due rows, allow four concurrent sends and at most one in flight per endpoint. PostgreSQL uses row locks with SKIP LOCKED plus an endpoint lease; local SQLite uses one dispatcher with conditional state updates. Commit claims and attempt numbers before I/O. Use 30-second leases, 10-second total timeout and a fenced completion UPDATE matching the current lease token and destination version. Reclaim an expired attempt as uncertain and consume its retry budget. Four sends maximum, immediate then 10/60/300 seconds with bounded jitter. Retry timeouts, 408, 429 and 5xx. Treat 2xx as delivered and other statuses as terminal. Backoff and leases survive restarts. Stop claiming on shutdown, cancel/await sends within the shutdown deadline and let unacknowledged leases expire. Record dead outcomes after the fourth attempt. Delivery order is unspecified.

Allow at most five endpoints per project and ten test sends per endpoint per hour. Enforce public HTTPS destinations, valid TLS, no redirects and an egress policy bound to the actual destination address. Reject embedded credentials and unsupported URL schemes. Encrypt signing material with authenticated encryption and a versioned deployment secret. Disable sends if decryption or destination validation fails. On edit of URL, disable, rotation or closure, increment destination version and cancel pending/leased deliveries for the old version; a send already accepted remotely cannot be recalled. Keep terminal event/delivery/attempt metadata for 30 days and retain pending work until terminal. Purge event payloads once every delivery has expired. Dashboard shows delivery state and age, and admins can inspect attempt metadata. Exclude raw server response bodies, tokens and annotation text from logs.

The launch subscribable events are the two persisted business transitions above. Reject unsupported names with 422. Batch completion needs durable batch membership, export-ready needs async artifact storage and expiry, and conservation changes need persisted per-category transitions. Schedule those event types only with the corresponding producers.

</details>

<a id="mm-6"></a>

### Designed · Export, events and SDK

Reviewer-or-higher export keeps the PostgreSQL REPEATABLE READ snapshot, two fenced leases per project, five-minute deadline, 500-key cursor pages, 5,000 documents, 16 MiB UTF-8 text and 32 MiB browser fallback. Preserve filters, current-revision selection, root ID and prediction provenance. First page only lightweight keys/byte lengths; fetch heavy content one admissible row at a time or in byte-bounded subpages within the same snapshot. Do not materialize 500 inline images or prediction original-content JSONs together. Add a separate **32 MiB encoded-output cap for media-bearing exports**, count both nested and flat copies including CSV escaping, reject before returning HTTP headers. Precheck PG octet lengths, bound each serialization/write and discard/release spool on overflow, cancel or timeout. Stream successful spools as today. Existing text-only output limits remain.

JSONL adds `item_media_url: string|null` and per-record `content_type: "image"|"text"`; keep `text` and existing `content`. CSV appends the same columns after existing fields (including optional factors); null becomes blank, use current safe CSV escaping. Both empty and populated CSV must use the identical explicit field list. Expose project axes with `X-DLJ-Content-Type: image|text|mixed` (mixed means per-item legacy policy) and `X-DLJ-Label-Schema: single|multi|ner|mixed`; add these to CORS expose_headers. The HTTP Content-Type remains the selected file encoding. Strict image/multi DocBin requests fail 422 `DocBin requires a text NER project`; preserve older legacy NER-only export and current spaCy 501. Over media output cap → 413 `Export exceeds the media output cap`. Exports are authorized downloads that may contain signed URLs or embedded bytes; mark no-store.

For image transitions in `label.verified` and `prediction.auto_approved`, add `data.media_kind="image"` and `data.item_detail_path` (relative canonical authenticated project/label detail route with escaped identifiers). This deliberately replaces v2's proposal to copy raw media URLs into webhook bodies: recipients can receive events without ever having permission to download private media. An authorized consumer resolves `content.image_url` from that path. Retain event names, envelope schema/version, deterministic transition keys, signing, retries, delivery history and old canonical bodies unchanged. No raw signed URL/base64 in event, dispatch logging, or test-send. No additional event just for viewing media.

In `backend/static/dlj_client.py` extend `DLJClient.create_project` with optional keyword-only axes (omit absent values). `upload` already accepts item dictionaries: document the per-item field, preserve generated replay keys and the existing UploadError resume semantics, split before exceeding decoded or JSON budgets, and reject an oversized single item locally. Pass through old uploads. Guide includes URL/inline examples, label verification and export, a broken-link example, shared-browser privacy and retention/storage cost of inline data; never embed a real customer URL in examples.

<a id="chapter-9"></a>

## 9. Billing and Access

✅ **Shipped · access and payment.** Public registration returns a challenge acknowledgement (202). Only mailbox confirmation mints a usable key (201). Persist digests and UTC expiries; commit before key delivery. Admin issuance and rotation use X-Admin-Key. DLJ keys are hashed; JM has a distinct credential store. A project belongs to an account, a key authenticates an actor, and a canonical payer is locked for quota. A collaborator's personal key never changes the payer. For purchase, write, member_write and retention use the shared entitlement resolver. No implicit tie-breaking among ambiguous payer keys.

Owners can change lifecycle and grant admin. Owners/admins manage settings, integrations, invitations and project roles. Annotators can read/request classifications and edit eligible content. Reviewer-level work includes typed import, verification, bulk, exports and prediction adjudication. Guidelines writes require admin/owner. Account checkout uses the authenticated account. Preserve exact handler-level exceptions in §4 (including legacy ingest); UI visibility does not grant authority.

UTC day/month counters update in the scoring transaction. Trial and effective cancelled payer get 50/day; active paid plans use §1 monthly caps, with warning near 90%. Expired trial, past_due, paused and cleaned_up restrict writes. A cancelled payer does not fund a collaborator's shared write. Unused quota is never fabricated on upgrade. Paddle intake requires a configured secret and valid signature, bounded 64 KiB streamed body and at most four active billing readers. Dispatches subscription.created, subscription.updated and subscription.canceled; state/status inside an update selects transitions. Audit unknown events without advancing the applied watermark. New paid grants require matched purchase intent/transaction/payer/product; cancellation of the bound subscription does not require a current product name. Recheck tenant guard, sibling protection, provider holds and purchase intents before retention deletes rows at its cutoff.

**Wave contract and acceptance intent**

- **A billing.** Implement one transition function and one effective-entitlement resolver for checkout, quota, account, scheduler and connector. Verified signup→trial, clock→trial_expired, verified purchase→active, effective pause/past_due→restricted, valid resumed/activated→active, effective cancellation→cancelled at 50/day, cutoff after 30 days→cleaned_up terminal. Keep existing counters and paid tier history. The implementation holds past-due writes; confirm customer communication before rollout. Bind purchaser, payer and provider transaction before granting capacity. Authenticate events, deduplicate by committed receipt, audit unknown/stale events without advancing the applied watermark, reconcile ties and replacements. Require a known tier only for paid grants. Tenant guard → sorted keys → domain → labels → engine is the common lock order. Serialize key creation, renewal and deletion, recheck all siblings, outstanding purchases and provider holds before deleting. Track equivalent SQLite writer serialization under advisory R24 in v1.1. Notification intent commits with the transition.

**Wave contract and acceptance intent**

- **A identity.** Reviewer may verify/import/export; annotator may classify/edit; admins manage settings/team; owners alone grant admin, archive and bind billing. Return 401/403/404 for invalid credential, insufficient visible role and inaccessible project respectively. Preserve actor and payer separately across legacy *labeling* routes. Invites use a digest, 48-hour expiry, recipient proof, one-time consumption and revocation/recheck of inviter authority. Signup uses a separate short-lived mailbox challenge and issues a bearer only after confirmation commits. Migrate the old signup surface and rotate shared historical keys before closure. Limit anonymous uploads before multipart decoding, release capacity on disconnect, validate all derived IDs and sanitize outer framework, SQL and job errors.

<a id="track-1"></a>

### Design record · Identity, access and project lifecycle

**Disposition.** The legacy design anticipated member CRUD, invitation management and additional throttles. Only the mounted operations in §4 are callable. Membership/PII gaps are recorded in §16.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

**Three identifiers serve three callers.** The browser and new API use Domain.id (UUID). Legacy callers submit public_domain_id or their original public name. Engine, label and annotator rows continue referencing the unique internal domains.domain_id string. For legacy requests use auth.scoped_domain_id(authenticated_tenant, supplied_name), including its existing empty-tenant behavior. Resolve new UUID paths directly, without rehashing. The separate JM decision API continues using its own SQLite credential store. An old project missing its public name is usable by UUID. Its owner may record a matching name through POST /v1/account/domains/resolve.

**Request boundary.** Authenticate the active API key and retain its UUID and account tenant. Project lookup yields a typed ProjectAccess containing project UUID, owner tenant, internal domain key, actor key, role and billing binding. Authorize the operation before resolving label or webhook IDs. Pass this explicit scope into the shared label, dashboard and engine services. Keep the request actor intact through account operations, audit and quota accounting. Return 401 for invalid credentials, 404 for an inaccessible resource and 403 for an insufficient role in a visible project.

| Capability | Minimum authority |
|---|---|
| Create a project / archive it | Authenticated account acting for itself / owning tenant |
| Configure schema, model gate, integrations, manage invitations | Project admin or owner |
| Grant or revoke admin | Owner only. Admin can manage reviewers and annotators only |
| Read queue/detail, submit classification/content revision | Annotator |
| Verify an observed outcome, bulk review, upload, export, view individual profiles | Reviewer |
| Project dashboard aggregates | All members. Suppress restricted profile details |
| Account, Paddle checkout, billing identity, cancellation | Owning account on its existing account surface |

Higher roles include lower-role project capabilities. Ownership follows the domain tenant and cannot be removed by editing a membership. Archive is reversible via owner update, stops writes through both namespaces and pauses deliveries. Permit authorized historical reads and export. Preserve old active projects by default.

#### Team and billing transitions

1. A newly registered account owns its own projects. The owner's account-level keys retain historical access. A grant to an invited account covers that account's active keys. The invite screen names the recipient email and role, and discloses this scope. A tenant with no attributable owner or ambiguous billing binding can still use its legacy private workflows.
2. Owner/admin submits email and permitted role. Normalize email as in auth.py. Generate 32 random bytes, store SHA-256 digest, expire in 48 hours. Persist pending invite before calling Resend. Deliver the token once via a hash link. Keep it only in memory during that send. On timeout or process interruption the admin can resend. Resend locks and revokes the old invite, issues a fresh token, and sends after commit. Return mail state pending/sent/failed to admins. Limit issue/resend to 10 per actor/project/hour and acceptance attempts to 10 per IP/minute.
3. The browser exchanges the mailbox token using an authenticated account with matching contact email. Retain it in tab session storage only while signup is in progress, erase it and replace the hash after completion. Acceptance rechecks project active status, inviter authority and allowed target role under lock. Atomically consume the token and create or reactivate membership. Prevent self-grants, owner edits and admin escalation. Invalidate pending grants issued by a demoted/revoked inviter. Revocation takes effect on the next authorized request.
4. Bind a single active owner key on the first shared write. For a multi-key tenant, provide a dry-run and apply operator command accepting owner tenant and canonical active key ID. Before applying, lock the tenant binding and affected keys, sum usage for matching UTC periods, retain the oldest applicable trial start and preserve verified subscription terms. Require a unique matching subscription or an operator-confirmed Paddle reconciliation. Refuse an ambiguous mapping and leave that tenant private. Persist the binding atomically. Make reruns return the existing binding without adding usage again. Route key creation, Paddle callbacks, checkout, quota, usage display and cancellation through that binding for shared accounts. A subsequent key rotation must transfer billing state and binding together. Persist trial_started_at on ProjectBillingOwner and consult it for expiry, reminders and account display. Set it to the applicable original UTC trial start at binding; keep ApiKey.created_at as credential creation time.
5. Lock/check project status and active membership for each mutation. Stale UI writes return 409 for a closed project or 404 after access loss. Completion and archival stop edits/imports across project, legacy and connector paths. Stop fan-out on closure and cancel queued deliveries. Owner reopening resumes new work. Account cleanup deletes child delivery, prediction and invite data before parent labels/domains; cover FK-restricting links with an explicit deletion order.

</details>

<a id="chapter-10"></a>

## 10. Multi-Modality

**Designed · scope of the next releases.** Item-level typed content is shipped. The project axes, policies, migrations and MM release switches below are planned. Stable image classification comes first. Multi-label introduces genuine independent decisions and grouped review. Strict NER adds source identity, explicit adjudication and span agreement. Follow the import contract in §4, viewer in §5, export rules in §8, migrations in §3 and the owned prompt sequence in §14. Existing opaque HTTPS image URLs and mixed legacy projects retain their applicable contract.

<a id="anno-7"></a>

### Roadmap · Scope boundary

The launch covers text classification, flat named entities and multi-label text, followed by image classification. Keep bounding boxes/polygons, video/audio, real-time co-editing, model training/AutoML, active-learning sampling, drag-and-drop template design, assignments and deadlines outside A–D. Use the existing Label Studio connector for teams with those workflows. A3 exports a queue page. Account-wide export/deletion and billing portal management need separate contracts and permissions.

<a id="mm-2"></a>

### Designed · Project matrix and compatibility

| Project axes | First writer | Contract |
|---|---|---|
| text / single | IMG | Normal category, optional text, no typed media on strict projects. |
| image / single | IMG | Exactly one image reference and one category per scored item; caption optional. |
| text / multi, image / multi | ML | One logical item, one independent decision per selected category. |
| text / ner | NER | Immutable source text, half-open character spans, explicit human span adjudication. |
| image / ner | None | Reject the pair. Bounding boxes are a different geometry. |

Add `content_type`, `label_schema` and a compatibility bit `modality_enforced` to `Domain`. Old rows and creations by clients omitting both axes report text/single **defaults** with enforcement false. Their typed rows may contain images, tags or spans; the per-row discriminator remains authoritative. Existing legacy imports, connector callbacks, detail views and old-format replay receipts keep working. Never mass-classify a populated project from its first row. New UI sends both axes explicitly (default text/single); explicitly supplying either axis opts the project into enforcement and the missing axis takes its default. The server alone writes the enforcement bit. New clients must display “Legacy · per-item content” for an unenforced project.

Support `POST /v1/projects` with the current required `name, public_domain_id, factors, categories`, optional `actions`, and the two optional axes. Example:

~~~json
{"name":"Field photos","public_domain_id":"field-photos","factors":["clarity","difficulty"],"categories":["bird","other"],"actions":["approve","reject"],"content_type":"image","label_schema":"single"}
~~~

201 retains all current fields and adds the three project fields. GET list/detail include them. PATCH uses the existing `If-Match` settings version; PUT settings uses its body version. Both return the effective fields along with the current response. Reject explicit nulls. A same-value retry with the current version is harmless; stale versions follow existing 409 semantics. Only an owner/admin of an active project may change axes or opt in, only while **no** LabelLog exists for its tenant + scoped domain, including unscored tasks, revisions and prediction imports. Archive/reactivation does not unlock axes. A populated legacy project may retain its policy or export/import into a new project. Disallow client downgrade to unenforced.

Use the existing tenant → payer/key → project/member → label → engine order in both settings and first-write paths. Under the same project lock re-read role, entitlement, lifecycle, settings version and label existence. Test both commit orders with independent PG sessions. Authenticated members see only permitted projects; preserve existing 401/403/404 distinctions and existing 428 for missing If-Match. Release controls: only enable creation of a strict combination after its backend, UI and export gates pass. Unknown combinations get 422 even if a client bypasses the selector.

<a id="mm-7"></a>

### Designed · Multi-label classification (ML)

Enable strict text/multi and image/multi together after IMG. Existing `text_multilabel` tags on legacy labels remain one historical decision with descriptive tags. No retroactive scoring, synthetic negatives or rebilling. A strict set selects **1–20 distinct configured categories**; display configured order and compare sets independent of request order. Each selected category receives a real scored decision using the supplied factors; absence means “not selected”, never “human verified false”.

**Wire and storage.** Extend the typed project import union with `MultiImportItem{label_id, categories:string[], factors, annotator_id?, text?, item_media_url?}`. Require categories instead of singular category; duplicate/unknown values → 422 `Invalid multi-label category set`. Use the same atomic batch endpoint and replay protocol. Return a discriminated result `{kind:"multi",label_id,group_version,decisions:[{category,...IngestResponse fields}]}` for strict multi projects only. Store one unscored LabelLog anchor (external label ID, null scored_at, immutable source, LabelContent containing tags of the initial assignment and optional image). New item discriminator for the image variant is `image_multilabel`. Child decisions are normal scored label_log rows, assigned opaque internal IDs and the anchor's tenant/project/annotator. Place generated child IDs under a reserved prefix `dlj-ml-` forbidden for strict multi external IDs (422 `Reserved multi-label item ID`). Resolve public lookups through the group anchor; block direct child mutation through the old single/bulk/connector routes.

Add two mapped tables and repeat-safe creation in the existing migrator. PostgreSQL reference DDL:
~~~sql
CREATE TABLE multilabel_group (
  anchor_id uuid PRIMARY KEY REFERENCES label_log(id) ON DELETE CASCADE,
  version integer NOT NULL DEFAULT 1 CHECK(version >= 1)
);
CREATE TABLE multilabel_member (
  anchor_id uuid NOT NULL REFERENCES multilabel_group(anchor_id) ON DELETE CASCADE,
  category varchar(200) NOT NULL,
  added_version integer NOT NULL CHECK(added_version >= 1),
  removed_version integer CHECK(removed_version > added_version),
  first_decision_id uuid NOT NULL UNIQUE REFERENCES label_log(id) ON DELETE CASCADE,
  PRIMARY KEY(anchor_id,category,added_version)
);
CREATE UNIQUE INDEX uq_multilabel_active ON multilabel_member(anchor_id,category)
 WHERE removed_version IS NULL;
~~~
An active membership points to the root of a normal decision lineage. Resolve current/effective successors with existing revision/evidence semantics. The anchor owns the single source; hydrate child detail by joining its anchor. Do not copy 10 MiB into N child rows. Historical sets are reconstructed at version V via added_version ≤ V and (removed_version null or > V). The membership history is authoritative for strict sets; compose detail/export tags from it. Foreign keys plus same-scoped-row lookup under the project lock prevent cross-project attachments. Retention removes group/membership before label cleanup inside the same transaction; verify both FK cascade paths. Downgrade only when both tables are empty and new writes are fenced: drop `multilabel_member`, then `multilabel_group`; retain any populated tables on app rollback.

**Edits and evidence.** On existing project relabel accept `{categories:[...], expected_group_version:int}` for strict multi. Lock parent and active children deterministically, compare version (409 `Multi-label set changed; reload and retry`). Preserve unchanged member IDs, close removed memberships, create a fresh scored decision for each newly selected category including re-additions. A same-set request is a no-op. For import reserve N score units and for edits reserve only newly scored categories; if the balance cannot cover all, return the normal quota error atomically, no partial group. Preserve prior verified evidence in immutable logs; changing selection cannot train or erase negative evidence. Reuse S26's effective-evidence rule per child lineage. Use existing verify semantics with a new group route `POST /v1/projects/{id}/labels/items/{label_id}/verify-set`: `{expected_group_version, decisions:[{category,expected_revision,actual_action,verified_outcome:boolean}]}`, nonempty distinct current members only. Require all named revisions current; stale → 409 above; duplicate or missing outcome → 422 `Supply one explicit outcome per selected decision`. Verify named pending decisions atomically via shared learner; identical retries are readbacks, conflicting already-verified results return 409. Return group version and per-decision status. Emit existing human verification event once per verified child with group label ID and category in data. No outcome from checkboxes.

**Views and adapters.** One queue/search/export row per anchor, one checkbox per configured category. Pending = at least one active pending decision; confidence = minimum pending confidence; use existing smart priority's highest-priority active member as the group's ranking, tie-break by anchor ID. Show decision breakdown and partial-review counts. CSV `categories` and `decisions` are JSON-encoded arrays; JSONL uses arrays. Scalar category/verified_outcome on group export are null (different children may disagree). Category filter matches active membership. Group dashboards report logical item counts separately from decision counts; SLA, conservation and accuracy denominators count human-evidenced decisions only. Exclude anchors from unclassified/task and engine metrics, including analytics queries. Ordinary pending/smart counts must agree with pagination. Prediction automation and connector creation on strict multi are explicitly unsupported in ML-1: return the [§4](#mm-4) unsupported-operation 422 before scoring, direct imports/reviews through the set contracts. The UI hides those actions for this combination. Adding per-category model confidence or connector set mapping is a separate product decision.

<a id="mm-8"></a>

### Designed · Text NER and agreement (NER)

Enable text/ner only. Extend typed project import and prediction content using existing `LabelContentRequest`, `NerSpan{start,end,label,text}`, `EditableNerSpan` and `LabelLog.source_task_id`. Require immutable nonempty UTF-8 source text (existing 32 KiB cap). For strict NER require `source_task_id` (1–200 chars, same identifier rules as label_id), a named annotator, configured document category and entity types. Add a versioned project setting `entity_types` for NER using the existing domain config JSON with a distinct key; validate 1–20 unique nonblank names ≤200 characters, no pipe. Keep entity vocabulary and document categories independent; persist extra config through all `DomainConfig.to_dict` rewrite paths without changing jm_core (merge validated extra keys in repository/config update code). Lock entity types after first label like axes. Preserve existing category-derived types for unenforced NER. Missing/incompatible vocabulary → 422 `Invalid NER entity types`. Old clients never opt into this contract implicitly.

Strict NER import requires `content_type:"text_ner"`, spans (empty allowed), no tags/media. Use one validator for import, typed content creation, relabel and connector edits. Store 0-based **Unicode code-point** offsets, half-open [start,end), original text without normalization. Require 0 ≤ start < end ≤ length, exact substring echo (derive it for edit DTOs without text), allowed label, no duplicates/overlap, touching endpoints allowed. Sort deterministically; cap strict imports **and edits at 100 spans**; leave old project limits intact. Validation → 422 `Invalid NER span set`. NEREditor and NERViewer render from code points; translate DOM UTF-16 offsets at selection boundaries and test astral characters, combining marks, repeated text, keyboard edit and cancellation. Strict UI removes custom entity names and adds explicit “Spans reviewed” with an accessible empty-set action. Category and span changes use the shared mutation lock; review of category alone never asserts span adjudication.

**Evidence.** Introduce `ner_adjudication` keyed by revision (one immutable review per revision) and one project-scoped source binding for reproducible cross-annotator agreement:
~~~sql
CREATE TABLE ner_source (
  project_id uuid NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
  source_task_id varchar(200) NOT NULL, text_sha256 char(64) NOT NULL,
  PRIMARY KEY(project_id,source_task_id)
);
CREATE TABLE ner_adjudication (
  label_log_id uuid PRIMARY KEY REFERENCES label_log(id) ON DELETE CASCADE,
  reviewer_key_id uuid REFERENCES api_keys(id) ON DELETE SET NULL,
  reviewed_at timestamptz NOT NULL
);
~~~
Insert-or-compare SHA-256 of the exact UTF-8 source under the project lock; source reuse with different text → 409 `NER source text differs for this task`. Revisions preserve source and spans, keep earlier evidence, and start unadjudicated. Add reviewer-or-higher `POST /v1/projects/{id}/labels/items/{label_id}/spans/review` with `{expected_revision:uuid}`; return 200 `{revision_id,human_spans_reviewed:true,reviewed_at}`. Compare against current revision under lock; stale → 409 `Label revision changed; reload and retry`; exact repeat returns the saved result. Use the existing reviewer/owner/admin checks and tenant → payer → project → label locks. Require an existing human-verified current document, else 409 `Verify the label before adjudicating spans`. Human prediction review with spans reviewed may create the same audit record in the same commit on an explicitly verified document; unknown/machine-only assessment cannot. Snapshot and explicit audit govern DocBin eligibility in strict projects, including intentionally empty spans. Keep strict English tokenizer alignment and dependency check. Preserve old legacy export semantics. Add empty-table guarded rollback: drop `ner_adjudication`, then `ner_source`; keep already-used project config and history for compatible readers.

**Agreement contract.** Keep the existing category Cohen's kappa in `dashboard_router.py:agreement` intact. Add project-scoped `GET /v1/projects/{id}/dashboard/ner-agreement` using the existing dashboard access dependency. For each project/task/annotator choose the latest adjudicated, human-verified evidence by reviewed_at then revision UUID; a pending successor does not displace it. Partition by comparable source identity, never merely by repeated label text. For every unordered annotator pair on shared tasks, align spans of equal entity type one-to-one. Exact match requires identical endpoints. Partial match requires character intersection/union ≥ **0.5**, inclusive. Maximize match count first, sum of IoU second; deterministic tie-break by ordered start/end/label. With nonoverlapping sorted spans, dynamic programming over the two sequences suffices. Compute exact and partial matches separately. Return `{pairs:[{annotator_a,annotator_b,tasks,empty_pairs,spans_a,spans_b,exact_matches,partial_matches,exact_f1,partial_f1}],micro_exact_f1,micro_partial_f1}`. F1 = 2·matches/(spans_a+spans_b); an empty/nonempty pair scores 0, both-empty increments coverage but contributes zero denominator; an all-zero denominator returns null. Aggregate counts before division. Any disagreement affects this report only; it cannot call learn, charge quota or change SLA. Page source IDs in bounded batches with project filters; add an index on (domain_id,source_task_id,annotator_id) for the scoped evidence query if absent, included in NER migration/rollback under the name `ix_label_log_ner_source` with predicate source_task_id IS NOT NULL. On rollback drop only the index introduced by this upgrade. Report counts independently of page boundaries.

<a id="mm-9"></a>

### Roadmap · Product boundaries and release triggers

Publish “text and image single-label classification” after the IMG gate, “single- and multi-label classification” after ML, and “text NER with span adjudication and agreement” after NER. Positioning refers to observed capability; competitor parity and buyer-objection ranking require customer evidence. Quickstart, numeric factors, human-outcome policy and conservation remain common to all phases.

Hosted uploads, proxy thumbnails and broken-link polling require a customer need for durable managed assets, a storage/egress budget and a retention/deletion design. Bounding boxes need a coordinate schema and an image-origin/canvas access contract. Audio/time segments, video/frame identity and document page/layout each need a customer workflow plus a separate annotation geometry and export design. None is a hidden dependency of image classification. No automatic media parsing, model inference or marketplace integration is part of these releases.

<a id="chapter-11"></a>

## 11. Analytics

✅ **Shipped · latest completed feature in the recorded Analytics gate.** All four project analytics endpoints resolve project membership, filter tenant and internal domain ID, and have a 60/minute decorator. The distribution and throughput panels appear on Dashboard. The project Analytics page handles confusion and agreement. Their DTOs are in §4.

| View | Population and calculation | Boundary or empty result |
|---|---|---|
| Distribution | Current (unsuperseded), categorized labels. Count per configured or observed category, percent of total, verified and pending; order descending count then name. | Empty project returns empty categories. Warn if the smallest count is below 10% of the mean across represented/configured names. |
| Throughput | UTC daily score and verification counts over 1–90 days (default 7). Include separate current-day and lifetime per-annotator counts. Time estimates use consecutive scores by the same annotator with a positive gap ≤300s. | Zero-fill days; no eligible intervals means null mean. Throughput counts activity, including earlier revisions; distribution counts current items. |
| Confusion | Rows original category, columns current category. Human pairs come from verified current nonprediction rows and their roots. Prediction pairs require human review. Filters human/prediction/all. | Top three off-diagonal pairs ranked by count; pct uses the original category's row total. |
| Agreement | For current annotated shared source tasks compare (category, actual action or recommendation) per annotator; sorted annotators, diagonal 1, symmetric agreement fractions, per-category slices and lowest overlapping pair. | Fewer than two overlapping annotators returns empty arrays and an explanation. Off-diagonal cells with no shared observations are 0 and excluded from lowest-pair selection. |

The separate dashboard IAA endpoint computes Cohen's kappa on effective verified categories for shared source IDs. Neither metric is the future NER span-overlap F1 (§10). Analytics are descriptive; they do not mutate learning state or reserve quota.

<a id="chapter-12"></a>

## 12. Quality of Life

✅ **Shipped · reviewer conveniences.** The public guide at /#/docs covers getting started, data upload, scoring and verification, predictions, exports, webhooks, Python client and billing. It includes mobile navigation and the client download. Quickstart at /#/quickstart has five steps: create project → upload sample → inspect a score → verify or revise → choose a next destination. It uses explicit review evidence. The anonymous health fixture and twelve-label authenticated seed have different persistence and billing behavior. Smart queue, shortcut help, mobile navigation, theme and SLA shield are described in §§5–6.

**Guidelines.** Project guidelines are nullable text, bounded to 10 KiB UTF-8, readable in review and editable subject to the project role. Escape stored text. The working checkout also returns guidelines_updated_at.

⏳ **Notes and guidelines extension.** The checkout exposes nullable annotator notes and review_notes on LabelLog, up to 500 characters on note-bearing inputs, shows the original note in review, and carries notes into queue/detail/export and the API client. Treat this as integration work until its own completion entry is recorded. Notes are neither a score factor nor proof of correctness. Preserve phase-specific account/project ownership for notes and drafts.

<a id="chapter-13"></a>

## 13. Deployment

✅ **Shipped · deployment configuration.** Node 22 slim builds the Vite bundle using npm ci. Python 3.12 slim installs the service, rendering libraries, routers and db package, copies the built frontend and executable SDK, and starts via docker-entrypoint.sh. The entrypoint runs the inspector-driven DB migration before Uvicorn. Railway uses Dockerfile and /v1/health with a 120 s healthcheck timeout and ON_FAILURE restart. The internal Docker probe uses the configured PORT. Legacy JM uses a persistent volume for its SQLite store. PG alone gates paid deployment.

GET /v1/health checks SELECT 1 in each store and verifies the frozen engine hash. PostgreSQL failure or mismatched hash returns 503 unhealthy. Legacy-only failure reports degraded with 200. Sentry when configured, sanitized diagnostics, lifecycle notices, delivery attempts and the event/transition ledgers are operator evidence. A recorded R5 PASS unblocks Prompt 12; it is not proof of a production release. Validate restore, staging resource caps, provider secrets and post-deploy smoke on the target environment.

The configured CORS origins are the DLJ and RGI production HTTPS sites and localhost ports 5173 and 8100. The current expose_headers list contains X-Total-Count. New download metadata is proposed in §8 and must be exposed before cross-origin browser clients depend on it.

### ✅ Runtime configuration and observability

| Setting | Consumer and purpose |
|---|---|
| DATABASE_URL, RAILWAY_ENVIRONMENT | Async engine; normalize PostgreSQL URL/TLS. DLJ_DATABASE_URL is used by the harness. Check actual dialect before collecting gate evidence. |
| PORT, JM_DB_PATH, LS_CONFIG_PATH | Listener (container default 8000), legacy JM database, historical connector-config source. Connector mappings live in PostgreSQL after import. |
| ADMIN_API_KEY, RESEND_API_KEY | Administrative credential and outbound email provider. Never return these in public diagnostics. |
| PADDLE_API_KEY, PADDLE_PRICE_MAP, PADDLE_SANDBOX, PADDLE_WEBHOOK_SECRET | Checkout API, tier-to-price map, provider environment and required callback authentication. Sandbox selection controls checkout host. |
| WEBHOOK_ENCRYPTION_KEY | Fernet key for outbound endpoint secrets. Different purpose from Paddle authentication. |
| LABEL_STUDIO_TOKEN, LABEL_STUDIO_TENANT_ID, LABEL_STUDIO_DOMAIN_ID, LS_FACTOR_MAP | Connector admission, service account binding and mapping defaults. |
| SENTRY_DSN, ENVIRONMENT | Optional monitoring destination and environment tag. |
| DLJ_PORT, VITE_API_KEY | Browser test base port and development-only API-key fallback. Never embed a production account key in frontend assets. |

Monitor readiness, bounded report/billing intake, quota refusals, transaction and audit dispositions, worker attempt outcomes, backlog age, snapshot duration, spool use and resident memory. Historical alert targets (oldest due >60 s for 5 minutes, dead >5% over 15 minutes with ≥20 attempts) are proposed operator thresholds; repository inspection cannot establish configured monitoring.

<a id="arch-3"></a>

### Roadmap · Deferred to v1.1

| Item | Reason and mitigation | Trigger and owner | Future effort |
|---|---|---|---|
| R06 · JM split commits | Only the legacy decision log/engine store is affected. Existing duplicate-learn checks do not make two commits atomic. Keep paying customers on DLJ routes, restrict legacy writes to identified test consumers, monitor failures and preserve a restorable snapshot. | Service owner reopens before first external JM write dependency, increased concurrency or any state/log mismatch. | ~3 engineer-days |
| R07 · plaintext JM bearer identities | Legacy and DLJ use separate credentials/stores. Raw JM credentials remain usable if the volume or its backups are disclosed. Restrict volume/backup access, omit keys from telemetry, use disposable JM test credentials and rotate them on exposure. | Security owner reopens on any external JM account, increased backup access or suspected disclosure. | ~3 engineer-days |
| R30 · legacy centroid collisions | New domain validation already rejects pipe-bearing categories/actions. Inventory historical configs, quarantine ambiguous engines from learning and keep them out of DLJ. | Engine owner reopens when a historical collision is found or an old snapshot needs production use. | ~2 engineer-days |
| R24 · SQLite row locking | Run compatibility CI and publish divergences. Paying and development deployments use PostgreSQL. | Storage owner must implement serialized writes before supporting concurrent production SQLite in v1.1. | Re-estimate with the advisory concurrency results. |
| Legacy migration and reconciliation | No known production client beyond scripts is the planning assumption. Verify with redacted route counts before launch; absence of consumers is not proven by repo search. Keep the distinct legacy API outside DLJ membership and billing. | Platform owner implements Option B from v1 [§14](#arch-2), including digest mapping, atomic decision storage and migration rehearsal, if any trigger above fires. | ~2 shared days **plus** the three rows above = **10 total** |
| Full blue/green handoff | Hobby deployment has one instance and accepts a brief restart. The existing entrypoint migrates before Uvicorn. Operational acceptance requires a tested restore and a release window; a DB backup does not eliminate downtime. | Operations lead reopens before a no-downtime SLA, multi-replica rollout, active legacy traffic or migration longer than the agreed window. Full cutover reference: Chapter 13 recovery protocol and the rollback trigger in this row. | Allow up to 4 engineer-days at that time; re-estimate from traffic and data size. |

Accepted means risk is still present. The launch owner records the consumer check, controls, trigger and next review date. If a paying workflow needs legacy JM, its affected P1s become blockers before onboarding that customer.

<a id="arch-6"></a>

### ⏳ Release gate · Timeline and critical path

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

<a id="track-8"></a>

### Design record · Database upgrade, rollout and recovery

**Disposition.** Staging and restore acceptance criteria. PostgreSQL alone gates production; the merged fresh-install decision and conditional historical repairs override earlier required two-dialect cutover.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

| Stage | Action | Evidence required to advance |
|---|---|---|
| Inventory | Capture domain UUIDs, owner/internal/public mappings, configs and engine state hashes; label/revision/content counts by tenant; API-key eligibility and current billing periods. Use the SQLAlchemy store. The JM_DB_PATH SQLite decision service has its own domains table | Baseline includes same-name tenants, null public names, empty legacy tenant, two-key accounts, superseded and unscored rows |
| Expand | Serialize db/migrate.py on Railway using a single release runner or transaction-scoped PostgreSQL migration lock. Complete historical migrations first. Inspect child tables before any SQLite rebuild. For a populated legacy layout with children, back up rows to staging tables, rebuild parent and children with original UUIDs, recreate indexes and FK constraints, restore rows, validate and commit as one migration | Run twice on fresh and upgraded SQLite and PostgreSQL. Verify FK integrity, exact old counts/IDs/config/state/history and bulk verification_reason. Exercise interruption/retry. Test restore before deployment |
| Bind | Deploy compatible readers and writers with sharing, prediction automation and delivery disabled. Enable project reads for an internal tenant. Use the tenant reconciliation procedure in [§9](#track-1) before sharing | Old and new paths return the same current revision and owner usage. One shared score charges the owning tenant. Existing public-name recovery and Paddle checkout still work |
| Canary | Enable project writes/team access, then export/batch/guide, then prediction review. Enable automation per project only after an owner/admin opts in. Enable webhook dispatch last with a real staging receiver | No unauthorized cross-account access; current revision survives edit/export; machine evidence stays out of human metrics; process restart recovers durable deliveries. Verify health, DB pool usage, export RSS and retry lag |
| Operate / roll back | Disable failing feature at its writer and UI. Pause automation or the webhook dispatcher independently. Preserve queued deliveries and committed history. Roll back only to a build that understands project status, billing binding and machine disposition once live shared writes have begun. Otherwise stop writes and use the tested restore/reconciliation procedure | Compare post-rollback sample exports and quota totals. Document the last restorable point and replay/reconcile post-backup writes before reopening |

Use deployment configuration for the invitation provider, public app origin, webhook key ring/active key version and service feature switches. Store secrets in Railway environment configuration. Record structured project ID, event ID, retry outcome and oldest due age. Alert if oldest due age exceeds 60 seconds for five minutes or dead deliveries exceed 5% over 15 minutes with at least 20 attempts. Move the same dispatcher to a dedicated worker when sustained delivery lag or API latency exceeds the deployment budget. Keep one enqueuing transaction regardless of worker placement.

**Test harness.** Extend test_labeling_router.open_client and related fixtures with multiple authenticated tenants, distinct browser contexts and transactionally isolated schemas. Enable SQLite foreign keys on every test engine. Use DATABASE_URL for the common PostgreSQL lane; set DLJ_DATABASE_URL consistently for test_bulk_review.py if present. Assert the actual dialect. Include migration fixtures older than create_all, two independent sessions for competing approvals/edits and worker leases, controlled time, captured mail and an injected HTTP transport. Start the built frontend and isolated backend on port 8080 for Playwright. Compare streamed downloads with decoded records. Target 60–85 backend cases and 12–16 browser journeys; prioritize invariant coverage over case counts.

</details>

<a id="chapter-14"></a>

## 14. Test Strategy

✅ **Shipped · regression gates.** The latest recorded completed Analytics run had 268 PG passes with 16 experiment tests deselected, and 167 Playwright passes on clean rerun; mypy, frontend and E2E TypeScript and the production build passed. At R5 the counts had been 222 PG and 138 PW; Sprint 0 then 232/142, Sprint 0 hardening 251/160. Counts are tied to the selection and checkout. Use isolated PG schemas and real app/auth, test across independent transactions and browser contexts, inject controlled time or transports, read back durable results and keep existing contract suites green. SQLite remains opt-in advisory.

From the repo root run `python -m pytest tests/ -q --timeout=120 -k "not exp_dlj"`, separately `python -m pytest tests/ -q -k exp_dlj`, and `npx playwright test` with a built app on DLJ_PORT. Typecheck changed Python modules using pyproject.toml, run frontend tsc/build and E2E tsc. These commands describe the implementation gate. The current document consolidation ran introspection and documentation checks only.

### ✅ Experiment isolation and operating envelope

- Date: 2026-11-25.
- experiments/__init__.py (empty).
- experiments/active_learning_harness.py — shared active learning harness.
- experiments/exp_dlj_01_active_learning.py — centroid distance versus uncertainty sampling.
- experiments/exp_dlj_02_transfer.py — cross-project transfer efficacy.
- experiments/generate_charts.py — four publication charts.
- tests/test_exp_dlj.py — 10 infrastructure tests.
- experiments/results/exp_dlj_01_results.json — EXP-DLJ-01 PASS on deterministic synthetic fallback; centroid distance reached 85% in 200–250 labels across five seeds.
- experiments/results/exp_dlj_02_results.json — EXP-DLJ-02 PASS on deterministic synthetic fallback; cold-start mean 335 labels, transfer mean 0 labels to 80%.
- experiments/results/charts/ — four PNG charts.
- Test count: baseline 188 collected + 10 new = 198 passed in the final full suite.
- mypy: clean on five new Python files.
- No changes to jm_core.py or existing production code.

#### Parameter sweep (completed)

- Date: 2026-11-26.
- experiments/exp_dlj_sweep.py — configurable synthetic data generator and both parameter sweeps.
- experiments/generate_sweep_charts.py — seven line and heatmap sweep charts.
- tests/test_exp_dlj_sweep.py — six generator and sweep smoke tests.
- experiments/results/exp_dlj_01_sweep_results.json — 24 unique cells across noise, dimensions, categories, batch size, pool size and the noise × dimensions grid.
- experiments/results/exp_dlj_02_sweep_results.json — 19 unique cells across source size, similarity, dimensions and the source size × similarity grid.
- experiments/results/charts/ — seven new sweep charts plus four prior charts, 11 total.
- Test count: 201 selected baseline + six new = 207 passed, one unrelated SQLite test deselected; 16 experiment tests passed in isolation.
- mypy: clean on six experiment and test modules.
- Operating envelope: DLJ-01 centroid advantage +10.0 pp at default; still +5.5 pp at 20% training-label noise and +5.5 pp at ten factors. At a 500-item pool it loses by 0.8 pp. No noise or dimensionality breakdown was observed in the tested range.
- Operating envelope: DLJ-02 transfer reduction 100% at full rule similarity. At 75% similarity, no transfer seed reached 80% within 500 labels; the negative reduction values in censored cells use a 525-label cap and are estimates.
- All sweep results use deterministic synthetic data; AG News was not cached.
- Baseline collection repair: relocated misplaced webhook `terminal_at` lines in db/models.py and db/migrate.py and the connector prediction guard in label_studio.py.

<a id="arch-1"></a>

### Design record · P1 launch classification

**Disposition.** Point-in-time launch classification. Use §15 for scenario evidence and §16 for historical-only deferrals.

<details>
<summary>Architecture decision detail and acceptance history</summary>

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

</details>

<a id="arch-2"></a>

### Design record · Merged prompts

**Disposition.** Completion status is 00/A–F and R1–R5 recorded; operational release remains a separate gate. Retain wave ownership, fix-credit test functions and estimates for regression review.

<details>
<summary>Architecture decision detail and acceptance history</summary>

| Wave / package | Merges | Depends on | Elapsed days | Deliverable and exit gate |
|---|---|---|---:|---|
| 1 / 00 Harness | baseline | current checkout | 3 | Real app, schema-per-test PostgreSQL, 46 existing contracts, 22 durable writes, browser contracts and 27 owned scenario shells. SQLite CI is advisory. No production DDL. |
| 2 / A Projects, billing, identity and access | 02+03 | R1 | 6 | Project CRUD, billing FSM, challenges, ownership, membership, invites, admission, ID validation and safe diagnostics. Both A schema blocks in [§3](#arch-4). S1–14, historical upgrade twice, roles and payer matrix, archive and checkout tests. |
| 3 / B Project UI | 04 | R2 | 4 + joint day | Project chooser, nested hash routes, team/settings, request context, guarded edits, private-history hygiene and explicit outcome. No DDL. S28–32. |
| 3 / C Shared writes | 05 | R2 | 4 + joint day | Transaction service, typed import, HTTP and connector adapters, source binding/order, replay, quota, evidence and config. C schema. S20–27. C leads final day with B on real S27 plus S28–32. Failure blocks wave 4. |
| 4 / D Export and predictions | 06+08 | R3 | 5 parallel | Scoped JSONL/CSV/DocBin export, prediction import, model provenance, review, automation and reopen. Both D schema blocks. Reuse S21/S26 and exercise streaming/leases, accuracy, cap, rollback, replay and no learning from machine-only decisions. |
| 4 / E Webhooks | 10 | R3 | 5 parallel | Admin CRUD, outbox, durable delivery, exact signed bytes, retries, leases and rotation. E schema. Reuse S21/S24/S27, exercise restarts, two workers, egress and rollback. D/E agree event envelopes before parallel work. |
| 5 / F Guide, prediction UI and integrations | 07+09+11 | R4 | 4 | Public guide, OpenAPI, executable Python client, prediction review, integrations settings and delivery health. No DDL. S1/S23/S27–31 plus quickstart, role, keyboard, secret handling and recovery gates. |
| 6 / 12 Release | release | R5 | 1.5 | Single-instance Railway procedure in [§13](#arch-6), all 27 green, paid checkout through signed delivery smoke, four accepted items recorded. |

A, B and C start by verifying existing fix tests pass. Build integration scenarios on that coverage.

#### 2.1 Review cadence

Every development wave ends with a mandatory independent Astra review before the next prompt is sent. Read every modified file in full using /model astra /reasoning high. Cover wave fix verification, broad backend and frontend review, test health, P1 scorecard, next-wave decision and a file/endpoint self-check. Repair new P1s or regressions before promotion. Release itself ends with the operational verification in [§13](#arch-6).

| After wave | Scope | Required evidence |
|---|---|---|
| 1 / R1 | Harness correctness, fixtures, contracts, [§15](#arch-5) coverage | 46 contracts pass; 27 owned shells skip or xfail; no harness-introduced regression. |
| 2 / R2 | A plus harness and prior fixes | S1–14 green, contracts green, prior 443 pytest and 124 PW green on primary gates. |
| 3 / R3 | Integrated B+C, earlier gates | S20–32 and S1–14 green; real joint S27. |
| 4 / R4 | D/E plus all prior gates | Export, prediction and delivery gates and inherited scenarios green. |
| 5 / R5 | F, full regression | All 27 active scenarios, full PostgreSQL pytest and PW green. |

#### Pre-existing fix credit

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

</details>

<a id="anno-6"></a>

### Design record · Implementation phases

**Disposition.** Historical delivery record. Distinct from later Post-Track 2 A–F packages.

<details>
<summary>Annotation decision detail and acceptance history</summary>

| Phase | Deliverable | Acceptance |
|---|---|---|
| A · Foundation | Sample report + quota-aware demo queue, optional text ingest/detail, queue sort/pagination/preview/page CSV, account settings | Anonymous visitor opens the sample report. Authenticated reviewer scores the sample, reads source text, verifies a label, exports a page and sees current key usage. |
| B · Annotation | First-pass text classification and audited relabel, structured content + read-only NER, scoped search, explicit bulk review | A reviewer assigns a class to an unscored text, corrects a prior annotation, inspects spans, filters across pages and records known outcomes once. |
| C · Rich annotation | NER range editing, multi-label tags, batch content import, read-only image display with class selection | Text/spans/tags round-trip. A reviewer can classify a displayed image. |
| D · Polish | Keyboard navigation, per-domain guidelines, inter-annotator agreement, theme toggle, mobile queue | Keyboard and mobile review complete the same task; agreement names its unit and denominator. |

</details>

<a id="anno-8"></a>

### Design record · Effort summary

**Disposition.** Historical budget. Recorded for lineage; current evidence in §14.

<details>
<summary>Annotation decision detail and acceptance history</summary>

Planning estimates include implementation and local verification, exclude production rollout, and assume an available test tenant and sandbox price map for checkout acceptance.

| Phase | Prompts | Estimated engineer-days | New pytest cases | Cumulative target |
|---|---:|---:|---:|---:|
| Baseline | — | — | — | 277 collected |
| A | 4 | 3–5 | 23 | 300 |
| B | 4 | 5–8 | 28 | 328 |
| C | 3 | 5–8 | 18 | 346 |
| D | 2 | 3–5 | 8 | 354 |
| **Total** | **13** | **16–26** | **77** | **354** |

Counts are concrete planning budgets for pytest cases. Browser checks/builds are additional gates. Rebaseline against newly merged work before implementation and record any change in the delta.

</details>

<a id="anno-9"></a>

### Design record · Risk assessment

**Disposition.** Shipped controls and ongoing regression oracles. Overlap §15.

<details>
<summary>Annotation decision detail and acceptance history</summary>

Three risks and corresponding controls per Phase A prompt:

| Prompt | First risk → control | Second risk → control | Third risk → control |
|---|---|---|---|
| A1 | A 500-label seed exceeds the trial cap → analyze 500 anonymously, explicitly score only 12 under quota. | Retry/concurrent clicks or a user-owned colliding domain → reserved scope, persistent provenance and atomic idempotent seed. | Sample “history” contaminates learning → fixture outcomes feed only the report; live review begins pending. |
| A2 | Text gets parsed as a factor → reserve it in both parsers; test numeric-looking content and prefixed/unprefixed CSV. | Label IDs collide across tenants or domains → scoped parent lookup and 404 isolation tests. | Oversized/sensitive/markup content → byte cap, no payload logs, escaped rendering, update data-handling copy before enablement. |
| A3 | Local sorting hides high-priority items on later pages → database sort before limit, stable tie-breaker. | Polls race filter changes or removals → reset/clamp offsets, ignore stale responses, label page count accurately. | Spreadsheet formulas or false “all data” export → neutralize dangerous cells, quote via Papa.unparse, name download “Export this page”. |
| A4 | DB key disclosure or old-period usage → minimal DTO, hash-scoped lookup, compare UTC period keys. | Wrong database or double-hashed domain selection → labeling list and lazy verified public-name mapping. | Stale subscription state or broken bare links → server-confirmed tier refresh, bounded retries and hash-route links. |

For B, stale human corrections require version checks, repeat submissions require idempotency, and bulk approval requires known outcomes for every selected item. For C, range offsets and overlap need one shared contract; restrict image origins and validate batch sizes. For D, inter-annotator agreement needs a stable common source-task identity and independently observed labels; missing pairs must remain “insufficient evidence”.

</details>

<a id="anno-10"></a>

### Design record · Execution plan

**Disposition.** Archived work packages, verification commands and test budgets describe implementation history. The applicable current commands are in this chapter; neither the old suite exclusions nor the dual-dialect gate supersede them.

<details>
<summary>Annotation decision detail and acceptance history</summary>

Run every implementation prompt from **jm-service**. Each block includes its own pre-check, acceptance tests and final session entry. The common gate below is part of every block. Use local test data and stub outbound Paddle requests in automated tests.

#### Shared verification commands

PowerShell from jm-service, after each prompt:

~~~powershell
python -m pytest --co -q --ignore=test_jm_docker_live.py --ignore=test_jm_docker_live_v2.py --ignore=test_jm_docker_live_v3.py
python -m pytest -q --timeout=30 --ignore=test_jm_docker_live.py --ignore=test_jm_docker_live_v2.py --ignore=test_jm_docker_live_v3.py
python -m mypy jm_service.py db/models.py --config-file pyproject.toml
npm --prefix frontend run build
~~~

Also run mypy on each changed Python module/test with the same config. Build the assets served from dist and open the built UI in a browser for the prompt-specific checks. The three exclusions are live HTTP scripts that execute on import and interpret pytest arguments as their URL. Treat them as a separate live-service smoke gate. Keep the frozen engine intact and the static mount last.

#### DLJ-A1 · Sample Data + Demo Mode

~~~text
/model spark
/reasoning high
Target jm-service. Deliver the sample experience in [§5](#anno-4).

STEP -1. Read docs/session_state.md, this design [§3](#anno-3)–[§4](#anno-5), Upload.tsx, HealthReport.tsx, csv.ts, api.ts, label_health/ingest.py, labeling_router.py, auth.py, trial_guard.py, db/repository.py and Dockerfile. Collect the baseline with the shared command. Check the label quota before designing the seed transaction.

Implement the versioned 500-row fixture and static packaging in [§5](#anno-4). Use the same asset in the browser and the seed endpoint. Keep text/spans in the fixture even when A2 is absent. Public preview works without any domain or key. Offer the separately labeled 12-row scoring action with key, remaining-capacity failures and a link to the pending queue. Use ordinary scoring for quota, state and policy. Never import sample ground truth as user verification. Return counts on replay. Account for parallel requests and conflicts without charging twice.

Add exactly 5 pytest cases covering (1) fixture dimensions/vocabulary and acceptance by the real report parser, (2) missing credential rejection, (3) successful tenant-isolated 12-row seed with counters and pending results, (4) replay with stable results and counters, (5) insufficient remaining capacity rolls back the whole seed. Exercise simultaneous clicks and reserved-domain collision in acceptance. Expected standalone total 282.

Verify: python -m pytest test_label_health.py test_labeling_router.py -q --timeout=30 (include any new sample test module); run [§14](#anno-10) shared commands. Open /#/upload with no key, view the sample report, then use a test labeling key, seed, repeat, and verify the queue and usage. Inspect the fixture inside the built dist.

FINAL STEP. Append DLJ-A1, date, changed files, fixture version, report/seed counts, tests, mypy/build and browser results to docs/session_state.md.
~~~

#### DLJ-A2 · Text column and content display

~~~text
/model spark
/reasoning high
Target jm-service. Deliver the source-text round trip in [§3](#anno-3) and [§5](#anno-4).

STEP -1. Read docs/session_state.md, this design, both CSV parsers, Upload.tsx, ReviewCard.tsx, api.ts, labeling_router.py, db/models.py, db/migrate.py, db/repository.py, label_studio.py and legal_pages.py. Trace a batch through quota reservation and rollback. Collect baseline and inspect the exact pending DTO.

Add nullable LabelLog.text and repeatable migration. Thread optional text through browser parser, both request models and repository transaction. Exclude text from both factor inference paths. Set limits and blank/null semantics from [§3](#anno-3). Add the scoped single-item detail route, render NEW TextViewer, and use detail even outside the first 200 pending rows. Keep next-item navigation independent of detail lookup. Disable verification for already reviewed items; refetch on conflict. Provide text_preview in the existing pending DTO as an optional first 80 code points, without sending full text. If A1 is present, attach and backfill only server-owned sample text when seeding again. If it merges later, its seed must use this same optional text contract. Review privacy/terms describing stored text.

Add exactly 8 pytest cases: old-schema repeated migration; legacy ingest without text; single detail round trip with whitespace/Unicode; batch round trip; invalid oversized text with batch rollback; anonymous health ignores numeric-looking text as a factor; tenant/domain detail isolation; deep detail and bounded preview beyond row 200. Test browser parser with prefixed and unprefixed CSV in acceptance. Expected standalone 285, sequential after A1 290.

Verify: python -m pytest test_db.py test_labeling_router.py test_label_health.py test_legal_pages.py -q --timeout=30; run [§14](#anno-10) shared commands. In browser upload a valid 200+ row report CSV with quoted multiline text and literal HTML, score it, open the label by ID, verify, and open a legacy row. Inspect that markup appears as text.

FINAL STEP. Append DLJ-A2, date, schema/API deltas, rollback/read behavior, tests, mypy/build and browser results to docs/session_state.md.
~~~

#### DLJ-A3 · Queue sorting, pagination and page export

~~~text
/model spark
/reasoning high
Target jm-service. Deliver a usable queue beyond 200 pending labels.

STEP -1. Read docs/session_state.md, this design, ScoredQueue.tsx, AnnotatorProfiles.tsx, HealthReport.tsx, api.ts, labeling_router.py and test_labeling_router.py. Record default sort/filter/list shape, response headers and collection baseline.

Extend pending with offset >= 0, existing 1–200 limit, whitelisted sort keys label_id/category/annotator_id/confidence/recommended_action and asc/desc. Use explicit null ordering and unique ID tie-breaker; preserve confidence/scored_at/id defaults and bare-array response. Count with identical tenant/category/pending filters and expose X-Total-Count (including CORS exposure when cross-origin). Do not infer a total from rows.length. Refresh without jumping to page one, reset on changed filters/sort/domain and clamp if last item disappears. Header click/Enter changes server order. Offer 50/100/200 and previous/next, an optional preview cell, and page CSV with escaped spreadsheet formula prefixes. Render a placeholder if A2 has not landed. Populate filter choices independently of a filtered page, e.g. from existing autonomy categories. Search and bulk decisions are B features.

Add exactly 6 pytest cases: legacy defaults; second page plus total; sorting across page boundaries with ties; invalid sort/order/offset; category-scoped total; tenant isolation and empty/out-of-range page. Expected standalone 283, sequential 296.

Verify: python -m pytest test_labeling_router.py -q --timeout=30; run [§14](#anno-10) shared commands. With 201+ labels, sort both directions, change category/domain during refresh, visit last page, export and compare row order/count. Include commas, quotes, line breaks and a formula-looking ID. Once A2 lands, confirm preview length and detail navigation for a later-page row.

FINAL STEP. Append DLJ-A3, date, API defaults, export scope, test count, mypy/build and browser results to docs/session_state.md.
~~~

#### DLJ-A4 · Settings and subscription

~~~text
/model spark
/reasoning high
Target jm-service. Deliver Settings as specified in [§5](#anno-4).

STEP -1. Read docs/session_state.md, this design, App.tsx, api.ts, domain.tsx, auth.py, billing.py, trial_guard.py, email_service.py, db/models.py, db/repository.py, db/migrate.py and label_studio.py. Inspect how domain IDs are scoped, how keys authenticate and all upgrade links. Collect baseline.

Implement the minimal authenticated summary and public domain list in [§4](#anno-5). Query the active key from the request, honor period keys, never return hashes or credentials. Implement public_domain_id mapping and backward-compatible migration from [§5](#anno-4). Add sidebar link and hash-routed settings, display key status and usage, handle missing key, unpaid trial, unlimited and cancelled states. Allow public-name entry and domain switching. Use existing Paddle checkout endpoint. Show confirmation pending on return and refresh from the backend. Update settings links and handle a missing checkout URL. Keep transaction creation and webhook signature policy in billing.py.

Add exactly 4 pytest cases: unauthenticated account/domains; minimal tenant-owned summary and correct UTC counters/caps; public-domain list with legacy name resolution, migration repeat and cross-tenant isolation; checkout-to-webhook-to-refreshed-tier integration using mocked Paddle. Expected standalone 281, sequential 300.

Verify: python -m pytest test_billing.py test_deployment.py test_jm_service.py -q --timeout=30; run [§14](#anno-10) shared commands. In browser open /#/settings from a pasted upgrade link, change domain, replace/clear local key and verify a checkout error and pending/confirmed return using sandbox or a stub. Record which system was exercised.

FINAL STEP. Append DLJ-A4, date, account fields and exclusions, public-ID migration, billing checks, test count, mypy/build and browser results to docs/session_state.md.
~~~

#### Phase B outlines and later work

| Outline | Depends on | Scope and acceptance | New pytest target |
|---|---|---|---:|
| B1 · Text task and revision | A2 | NEW task intake and CategorySelector for first classification. A scoped task ID can be resolved by the proposed item relabel route to create its first scored label. Preserve revisions on later edits. Transactionally score once and verify separately. | 8 |
| B2 · NER read view | A2 | Structured content migration, bounded content POST, detail extension, offset validation and read-only highlights with legend. | 8 |
| B3 · Bulk review | A3 | Select current page/explicit IDs, confirm action and known outcomes, handle stale rows without partial learning. | 7 |
| B4 · Search | A2, A3 | Parameterized scoped search over ID, annotator and text; reset page, filter before sorting/counting and verify query cost. | 5 |

Phase C items only: C1 span editor; C2 tag selection and batch content; C3 image display and classification.
Phase D items only: D1 shortcuts, theme and mobile queue; D2 guidelines and inter-annotator agreement.

#### Dependency graph and integration order

~~~mermaid
flowchart LR
  Base --> A1
  Base --> A2
  Base --> A3
  Base --> A4
  A2 --> B1
  A2 --> B2
  A3 --> B3
  A2 --> B4
  A3 --> B4
  B2 --> C1
  B1 --> C2
  B2 --> C2
  B1 --> C3
~~~

A1 can ship first. All four A prompts can start on the baseline. A3 displays a placeholder until A2 supplies previews; later-page review needs A2 detail. A1 retains source text until A2 can store it. On merge, the later prompt owner verifies both seams. A2 and A4 both touch model/migration code, and multiple prompts extend api.ts and routing. Merge additive changes by hand and rerun the shared gate on the integrated tree. Independent delivery totals are baseline plus each prompt’s delta. The sequential targets 282 → 290 → 296 → 300 assume A1 through A4 merge in order.

</details>

<a id="track-9"></a>

### Design record · Delivery estimate

**Disposition.** Historical budget. Replaced by six integrated waves.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

| Work | v1 days | Revised days | Cost driver |
|---|---:|---:|---|
| Projects and members, including baseline | 4 | 11 | Account scope, old/new route parity, quotas, invites and UI |
| Export | 2 | 3 | Revision-aware snapshot, streaming and DocBin QA |
| API/batch and guide | 2 | 4 | Typed content, downloadable client and executable examples |
| Predictions | 3 | 5 | Provenance, quota atomicity and human-only evidence |
| Webhooks | 1.5 | 6 | Leases, egress controls, retry, deployment and integrations UI |
| Release rehearsal | — | 1 | Dual-DB migration, compatibility and staging recovery |
| **Total** | **12.5** | **30** | Largest uncertainty is reconciling legacy multi-key billing |

</details>

<a id="track-10"></a>

### Design record · Ordered implementation prompts and release gates

**Disposition.** Historical delivery lineage. 00 + A–F + 12 superseded the unmerged plan.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Run these prompts in order. Dependencies identify required artifacts even when intervening prompts are independent. Days include implementation and verification by one engineer. High tier denotes a high-reasoning coding model for authorization, persistence and concurrency. Medium tier is sufficient for bounded UI and guide work. For **every** prompt run applicable backend regression/contracts against SQLite and real PostgreSQL, record actual dialects and results, and run TypeScript/build and browser checks for changed screens. Treat each gate as an exit condition before handing its artifacts to the next prompt.

| # | Depends | Tier | Days | Prompt to execute and expected output | Gate |
|---|---|---|---:|---|---|
| 01 | Current labeling checkout | High | 1 | Inventory the merged ORM, mounted OpenAPI and hash routes. Freeze legacy request/response fixtures, content/guideline/IAA semantics, roles and quota paths. Add isolated multi-tenant and migration fixtures. | Both DB lanes identified. Record any outstanding B4–D2 dependencies and gate the affected adapters at integration. Baseline exceptions recorded independently of new tests |
| 02 | 01 | High | 3 | Expose projects over domains. Implement additive DDL, UUID CRUD, archive/read-only checks, reconciliation report and billing binding. Integrate account, Paddle and cleanup with the chosen billing identity. | Upgrade twice from legacy and fresh DB. Same engine state, labels, content, owner keys and legacy reads. Ambiguous subscriptions cannot enable sharing. No second quota through a route or key |
| 03 | 02 | High | 4 | Implement actor/project access dependencies, shared services and scoped adapters, membership/invite lifecycle, role hierarchy, mail delivery and audit. Include connector and bulk paths in permission inventory. | Owner, admin, reviewer, annotator, revoked and foreign callers pass allow/deny matrix. Token replay/expiry/race, email mismatch and inviter demotion tested. Invitee's key has zero access to owner's account through legacy routes |
| 04 | 03 | Medium | 3 | Add nested HashRouter layout, access provider, switcher, projects, team, invitation return and project settings. Reuse existing screens. Keep old routes and account checkout. | Deep-link refresh, back, key replacement, two projects with identical label IDs, revoke while open, invite through signup, old review URL and Paddle return exercised in two browser contexts |
| 05 | 03 | High | 2 | Extend shared JSON batch service with typed content, bounded idempotency, quota ownership, documented responses and errors. Register new OpenAPI models and preserve browser CSV flow. | Identical replay has one score and charge. Changed payload, invalid middle item, duplicate and concurrent limit hit roll back. Old CSV and legacy batch still return original contract |
| 06 | 04,05 | High | 3 | Implement export predicates, streaming JSONL/CSV, bounded DocBin and both dialog entry points. Add dependency to image and test downloadable artifacts. | Round-trip Unicode spans and CSV, validate null and false, revisions and filtering, enforce role and concurrent snapshot isolation. Invalid alignment fails before download. Measure memory on representative maximum |
| 07 | 05,06 | Medium | 2 | Deliver public guide, OpenAPI examples and single-file Python client. Run register/create/upload/verify/download against a seeded service. Include human-readable auth, limits, errors and format dictionary. | Guide accessible without key. Executed curl/Python match actual server contract. Client streams files and surfaces retryable failures. Published spec contains unique route/method pairs |
| 08 | 03,05 | High | 3 | Implement prediction provenance and revision linking, import, opt-in policy, stats and human adjudication. Route all scoring through the shared capacity reservation. | Cold start, demotion, paused/negative recommendation, annotator minimum, confidence floor, replay, concurrent import and 49+2 cap cases pass. Machine decision never increments verified counts or learns |
| 09 | 04,08 | Medium | 2 | Extend queue, detail, settings and dashboard for original prediction, manual correction, machine-only audit/reopen and source stats. Bind final Track 2 shortcuts and editors. | Human accept/correct and later audit work on current revision. Sorting/filtering, role gating, stats denominators and stale revision conflicts verified in browser |
| 10 | 03,08 | High | 4 | Implement endpoint, event and delivery schema, transactional producers, signing, egress policy, claim/lease worker and lifespan supervision. Implement admin CRUD, test dispatch and attempt history. | Commit/rollback, crash before/after send, duplicate receipt, two workers, expired lease fencing, retry schedule, signature checks and blocked destinations pass using deterministic transport and clocks |
| 11 | 04,07,10 | High | 2 | Build integrations settings, health indicator and delivery log. Publish signing examples. Wire encryption keys, retention, monitoring, cleanup and staging delivery check. | Only authorized admins manage endpoints. Secret shown once. Rotation, archive and destination change suppress prior pending deliveries. Signed staging event received and recoverable restart demonstrated |
| 12 | 01–11 | High | 1 | Rehearse Railway upgrade on a restored copy, exercise old-key and member workflows, compare DB invariants, run dual-DB suite and browser journeys. Record regressions, rollback rehearsal and rollout decision. | Approve release only after parity, quota, isolation, export, human-evidence and durable-delivery gates pass. Separate unrelated smoke failures from release evidence |

#### Implementation handoff

For each row, give Codex the repository root, this file, the row number and the preceding gate evidence. Implement only that row’s feature slice. Deliver code, any schema upgrade, relevant automated coverage and the commands/results for its gate. Register project routes before the final StaticFiles mount. Keep production rollout under the release gate.

| Prompts | Primary code and deliverables |
|---|---|
| 01–03 | Extend db/models.py, db/migrate.py, auth.py, db/repository.py, trial_guard.py, billing.py, account.py, scheduler.py and email_service.py. Add project routing and register it in jm_service.py. Produce the reconciliation command with dry-run output and dual-DB integrity comparisons |
| 04 | Update frontend/src/App.tsx, domain.tsx and api.ts. Add the project provider, Team and Invite screens, and adapt Upload, ScoredQueue, ReviewCard, Dashboard and Settings |
| 05–07 | Share ingest and structured content validation from labeling_router.py. Add export serialization and the authenticated download adapter. Ship frontend public client, guide, Docker dependency and contract fixtures. At 06 test human-only baseline exports. At 07 ship only client methods backed by live routes |
| 08–09 | Add prediction persistence/adjudication, propagate revision pointers and metadata in every writer, including Label Studio, and extend the queue, policy tests, exports, docs and client. Add import_predictions to the client and execute it here. Re-run export tests with machine and human predictions |
| 10–11 | Add event/delivery repository, dispatcher, webhook router, settings UI and receiver example. Wire lifespan and deployment configuration. Add producers to every shared verification path and prediction approval. Re-run client/guide contracts for final events |
| 12 | Rehearse docker-entrypoint.sh migration/startup and restoration on an isolated copy. Rebuild frontend/dist from frontend sources, serve the full app, run two-role browser journeys, exercise signed events on staging and record a go/no-go decision |

**Gate commands.** From jm-service run the following PowerShell baseline in a fresh test shell, followed by each prompt's new pytest files. Use the isolated schema fixture for PostgreSQL. The PostgreSQL lane must print its actual dialect. For frontend gates start the built application against isolated fixture data on port 8080 before Playwright. Run the deployment rehearsal against staging only.

```powershell
$env:DATABASE_URL = 'sqlite+aiosqlite:///:memory:'
$env:DLJ_DATABASE_URL = $env:DATABASE_URL
python -m pytest test_labeling_router.py test_tasks.py test_content.py test_queue.py test_bulk_review.py -q
$env:DATABASE_URL = 'postgresql+asyncpg://postgres:postgres@localhost:5433/dlj_dev'
$env:DLJ_DATABASE_URL = $env:DATABASE_URL
python -m pytest test_labeling_router.py test_tasks.py test_content.py test_queue.py test_bulk_review.py -q
npm --prefix frontend run build
npx playwright test --config=playwright.config.ts
```

**Acceptance boundary.** The five launch features comprise projects/team access, authenticated record export, a runnable API guide/client, model prediction review with gated automation, and durable project webhooks. A production release needs measured export limits and worker lag, a tested owner-billing binding and staging evidence. The release owner records the result of prompt 12 before enabling these features for all accounts.

</details>

<a id="mm-11"></a>

### Designed · Ordered Codex prompts and verification

**Planning estimate:** seven prompts, **83 new PostgreSQL cases + 33 new Playwright cases = 116**. These are new behavioral cases, not counts obtained by collecting the same test twice. The image gate comprises MM-01 through MM-04 (36 PG + 12 PW). Multi-label and NER are later product releases, not prerequisites for Prompt 12. Estimate image delivery at 5–7 working days with two implementation slots and review; ML at 4–6 days; NER and final integration at 2–3 weeks including annotation QA. Replace estimates with observed counts in the session log at each gate. Keep the architecture authority's R1–R5 checks and 27 scenarios in the suite.

**Preflight P (every prompt, repo root).** Read this contract, architecture and scenarios in Chapters 2 and 15, latest session state and current diffs. Inspect touched callers before editing. Point DLJ_DATABASE_URL at an isolated PostgreSQL test database; verify its dialect with the harness. Record the engine hash and run the following commands. Use the project's normal built-app fixture/test server at DLJ_PORT for Playwright, reuse its test identities and isolated schema, and preserve both workers. Do not use production data. Commands below are PowerShell-friendly; run frontend commands from the indicated directory.
~~~powershell
Get-FileHash jm_core.py -Algorithm SHA256
python -m pytest tests/ -q --timeout=120 -k "not exp_dlj"
npx playwright test --reporter=list
~~~

**Exit V (every prompt).** Rerun P's hash, PostgreSQL and browser checks. Run `python -m mypy <all changed Python modules> --config-file pyproject.toml` with the actual paths, `npx tsc --noEmit` and `npm run build` from frontend, and `npx tsc --noEmit -p e2e/tsconfig.json` from root for browser specs. Rebuild frontend before browser verification. Run each prompt's named tests explicitly too. Every new write test reads committed state from a fresh session. Use independent sessions, barriers and timeouts for concurrency. Browser tests must exercise the real API; intercept only external image loads, injected failures or deliberate timing boundaries. SQLite can be run separately for compatibility. Each prompt records files, counts, hash and residual issues in `docs/session_state.md`.

**File manifest and prompt briefs.** Paths below are repository-relative; “new” signifies a proposed file. Paths repeated across prompts are integration boundaries with a single merge owner. Existing operation-context infrastructure, core, billing/entitlement, anonymous report service, legacy JM store, Dockerfile and Playwright discovery configuration require no feature edits.

| Prompt / owner | Depends on | Target delta PG / PW | Pre-check and exit |
|---|---|---:|---|
| MM-01 · Project schema & policy · Sol/high | Reviewed design | 9 / 0 | P; inspect actual startup DDL and existing nested typed fixtures. V + schema suite. |
| MM-02 · Atomic media ingestion · Astra/high | MM-01 | 17 / 0 | P; capture old receipt fixtures and connector/prediction samples. V + ingest suite, S21/S23/S26. |
| MM-03 · Image project workflows · Sol/high | MM-01; freeze [§4](#mm-4) DTOs with MM-02 | 0 / 9 | P; exercise old aliases and direct vs report uploads. V + image UI suite on integrated MM-02 backend. |
| MM-04 · Export, SDK, delivery & IMG gate · Astra/high | MM-02 + MM-03 | 10 / 3 | P; inspect spool/lease and canonical event bytes. V + output suite, IMG release rehearsal. |
| MM-05 · Independently scored category sets · Astra/high | IMG gate | 19 / 7 | P; measure legacy tag evidence and replay. V + set suite and S20–S32. |
| MM-06 · NER editing, adjudication & IAA · Astra/high | IMG gate; merge after MM-05 | 23 / 11 | P; snapshot legacy span exports and Unicode editor behavior. V + NER suite and S20–S32. |
| MM-07 · Combined release verification · Astra/high | MM-05 + MM-06 | 5 / 3 | P; read merged diffs in full. V + all 27 scenarios and release smoke suite. |

**MM-01 — establish the project contract.** Modify `db/models.py`, `db/migrate.py`, `projects_router.py`, `db/repository.py` for [§10](#mm-2)/[§3](#mm-3); add `modality.py` (capability matrix, shared policy/error definitions) and `tests/test_modality_schema.py`. Runtime switches are `DLJ_IMAGE_PROJECTS_ENABLED`, `DLJ_INLINE_IMAGES_ENABLED`, `DLJ_MULTILABEL_PROJECTS_ENABLED`, `DLJ_NER_PROJECTS_ENABLED` (default false; set true explicitly after the relevant gate). Switches gate newly enabled creation/writes, not reads of already stored content; strict text/single is always available. Publish enabled combinations to authenticated project-creation UI via additive `GET /v1/projects/capabilities` declared before the UUID route, returning `{combinations:[{content_type,label_schema}],inline_images_enabled:boolean}`. Include capability DTO + route/role tests in schema suite. Verify fresh/upgraded/repeated migration, old mixed project, defaults, invalid combination, role/version conflicts, both first-write interleavings. Register policy on existing writes before enabling strict axes.

**MM-02 — accept images once.** Modify `modality.py`, `jm_service.py`, `auth.py`, `labeling_router.py`, `label_studio.py`, `db/repository.py`; add `media_intake.py` (bounded ASGI receive and image-reference validator), `tests/test_modality_ingest.py`. Implement [§4](#mm-4) including all alias routes, source bindings, replay and immutable prediction original-content resolution. Scope feature checks to the selected project. Add lightweight media summaries without fetching blobs (EXISTS/projection) and keep detail shape compatible. For authenticated inline detail apply Cache-Control: private, no-store. Tests cover exact and +1 byte boundaries, cumulative cap, chunked/no-length, declared size mismatch, permit release, invalid/opaque URL, balanced factors/engine parity, role isolation, atomic rollback/charge, pre-upgrade replay, source copies under relabel and connector/prediction outcomes. Explicitly test no server-side remote image access.

**MM-03 — build the image workflow.** Modify `frontend/src/App.tsx`, `frontend/src/domain.tsx`, `frontend/src/api.ts`, `frontend/src/csv.ts`, `frontend/src/screens/Projects.tsx`, `ProjectSettings.tsx`, `Upload.tsx`, `ScoredQueue.tsx` and `ReviewCard.tsx` (the last four also under `frontend/src/screens/`), `frontend/src/components/ImageViewer.tsx`, `frontend/src/components/PredictionReviewCard.tsx`, `frontend/src/pages/PredictionReviewPage.tsx`, `frontend/src/pages/QuickstartPage.tsx` and `frontend/src/index.css`. Add `tests/e2e/modality_image.spec.ts`. Build [§5](#mm-5); configure a real fixture project, assert caption and score at detail, corrupt/unreachable image fallback, announced loading and keyboard verify, no-referrer remote consent, smart queue → successor, image prediction correction, mobile layout, stale project/account response, no media in history or free-report request. Use the capability endpoint for selectable options and project detail for locked settings. Respect existing account-generation guards.

**MM-04 — finish image output and release.** Modify `labeling_router.py`, `db/repository.py`, `jm_service.py`, `backend/static/dlj_client.py`, `frontend/src/pages/GuidePage.tsx`; add `tests/test_modality_output.py` and `tests/e2e/modality_output.spec.ts`. Freeze [§8](#mm-6) export/SDK/event schemas; SDK retries reuse the generated key for that chunk (including manual resume via the existing UploadError request_key/items). Test empty/populated CSV headers, inline round-trip/size refusal, snapshot and expired lease cleanup, DocBin refusal, current vs original after revision, stable signed event on retry, signed query/body exclusion and client byte splitting. Run image-create → upload → classify → export through the browser, a broken link through verification, and quickstart text regression. Stage upgrade → run twice → enable image → 10 MiB smoke → simulate rollback fence and recovery. Independent review signs off IMG before Prompt 12.

**MM-05 — ship group semantics.** Modify `db/models.py`, `db/migrate.py`, `db/repository.py`, `scheduler.py`, `modality.py`, `auth.py`, `projects_router.py`, `labeling_router.py`, `label_studio.py`, `dashboard_router.py`, `analytics_router.py`, `backend/static/dlj_client.py`, `frontend/src/api.ts`, `frontend/src/csv.ts`, `frontend/src/screens/{Projects,ProjectSettings,Upload,ReviewCard,ScoredQueue}.tsx`, `frontend/src/pages/{GuidePage,PredictionReviewPage}.tsx`. Add `multilabel.py` (group transaction/read projection), `frontend/src/components/MultiLabelDecisions.tsx` (controlled checkboxes and outcome rows), `tests/test_modality_multi.py`, `tests/e2e/modality_multi.spec.ts`. Keep the legacy TagSelector contract. CSV categories are a JSON array cell; reserve it from factor inference. Cover add/remove/re-add, quota exhaustion, rollbacks, two writers/stale version, replay, mixed outcomes, no-op, evidence, legacy tags, both media types, project isolation, direct-child mutation refusal, stats and one-row export. Gate creation after integrated role, queue, editor and export tests.

**MM-06 — ship text NER.** Modify `db/models.py`, `db/migrate.py`, `db/repository.py`, `scheduler.py`, `modality.py`, `auth.py`, `projects_router.py`, `labeling_router.py`, `label_studio.py`, `dashboard_router.py`, `frontend/src/api.ts`, `frontend/src/csv.ts`, `frontend/src/screens/{Projects,ProjectSettings,Upload,ReviewCard,AnnotatorProfiles}.tsx`, `frontend/src/components/{NEREditor,NERViewer,PredictionReviewCard}.tsx`, `frontend/src/pages/GuidePage.tsx`. Add `ner_agreement.py` (pure matching/counts), `tests/test_modality_ner.py`, `tests/e2e/modality_ner.spec.ts`. Expose entity vocabulary in project detail/settings; strict CSV accepts source_task_id and JSON spans cells excluded from factors. Connectors must provide source/annotator/text/spans under the same validator, or fail before writing. On strict NER permit a substantive span-only correction through relabel with expected revision, including corrections to verified spans: create a successor, copy source identity, preserve prior effective evidence and require fresh span adjudication. Identical content never manufactures a revision. Test Unicode, offsets, sorting, overlap, source digest mismatch, no-double-count revision, empty sets, two annotators, one-to-one match/tie, exact threshold, pair micro F1, roles, DocBin alignment, predictor vs human evidence and correction/re-export. UI renders the agreement table with sample sizes and null as “Insufficient overlap”.

**MM-07 — close the combined gate.** Add `tests/test_modality_release.py` and `tests/e2e/modality_release.spec.ts`; record results in session state. Verify mixed legacy/strict tenants, concurrent settings vs writes, repeated upgrade/guarded downgrade rehearsal, retention with all FK children and an engine-parity journey across phases. Verify browser account switch with media open, grouped revision export and an adjudicated span revision. Reuse the existing suites first; no duplicate shallow smoke cases. Attach observed storage/peak memory and latency for maximal import/export, cleanup counts and PG/PW totals to the gate decision.

**Release assets.** The Dockerfile builds the frontend. Follow the repository's tracked `frontend/dist/index.html` convention for a release build; regenerate it once at each integrated UI gate, never hand-edit it in parallel. The launch sequence is Analytics/Notes integration → IMG gate → Prompt 12. Post-launch scope remains independently releasable.

**Parallel ownership.** The Analytics completion entry landed during this review. Preserve its distribution, throughput, confusion and agreement contracts; MM-05 must distinguish logical items from independent decisions in those projections. MM-02 backend and MM-03 frontend can run concurrently after MM-01; MM-04 owns their integration. After IMG, the pure NER matcher and Unicode fixtures can be prototyped while ML ships. Serialize shared router, migration, UI decoder and queue changes; MM-06 rebases on MM-05 before integration. Analytics and Notes/Guidelines are not assumed disjoint: coordinate `projects_router.py`, `labeling_router.py`, `frontend/src/api.ts`, settings and review screens with their owners before merging. Each phase enables only combinations whose integrated PG/PW and independent review have passed.

Run targeted gates from repo root (all backend commands use the test PG URL):
~~~powershell
python -m pytest tests/test_modality_schema.py -q --timeout=120
python -m pytest tests/test_modality_ingest.py tests/harness/scenarios/test_s20_s27.py -q --timeout=120
npx playwright test tests/e2e/modality_image.spec.ts
python -m pytest tests/test_modality_output.py -q --timeout=120
npx playwright test tests/e2e/modality_output.spec.ts
python -m pytest tests/test_modality_multi.py tests/harness/scenarios/ -q --timeout=120
npx playwright test tests/e2e/modality_multi.spec.ts
python -m pytest tests/test_modality_ner.py tests/harness/scenarios/ -q --timeout=120
npx playwright test tests/e2e/modality_ner.spec.ts
python -m pytest tests/test_modality_release.py tests/harness/scenarios/ -q --timeout=120
npx playwright test tests/e2e/modality_release.spec.ts
~~~

<a id="chapter-15"></a>

## 15. Design Scenarios

✅ **Shipped · scenario gates.** The 27 active scenarios are S1–S14 and S20–S32. R5 recorded 27/27 passing. S15–S19 were deliberately reserved for deferred legacy migration and are excluded from the launch denominator. Stable IDs, result predicates and owners below identify test obligations. Prompt 00's initial skip/xfail stage is historical; it is not an acceptable present-day outcome. The 24 launch obligations are regression obligations, not 24 known open production defects.

### ✅ Evidence locations

| Cases | Current automated location | Owner at implementation |
|---|---|---|
| S1–S6 | tests/harness/scenarios/test_s01_s06.py | A identity/admission |
| S7–S14 | tests/harness/scenarios/test_s07_s14.py | A billing/lifecycle |
| S20–S27 | tests/harness/scenarios/test_s20_s27.py, tests/harness/browser/test_prompt_c_joint.py | C writes; S27 with B UI |
| S28–S32 | tests/harness/scenarios/test_s28_s32.py | B browser ownership |

The following oracles are independent of historical prompt effort estimates. Coverage of the 24 launch obligations is scoped to a fresh PostgreSQL installation; historical data exceptions follow §16.

<a id="arch-5"></a>

### ✅ Shipped · Integration scenarios and release evidence

The 00 harness preceded production changes. Keep v1 scenario numbers stable. Remove only S15–19 (legacy import/auth replay, split commit, concurrent legacy learn, historical centroid conversion, fenced legacy cutover). Keep the existing legacy wire smoke suite. **27 scenarios remain**; parametrized dialects, timing orders and the product acceptance gates in [§14](#arch-2) are additional executions.

Use asynchronous pytest fixtures on the asyncio backend with one PostgreSQL schema per test, shared by independent connections. Run the same compatible cases in a separately selected, non-blocking SQLite CI job with FK enforcement. Assert actual dialect and connection identity. Coordinate two writers at transaction boundaries with timed barriers and inspect committed results from a third session. Use the real mounted service and two browser contexts for identity/project changes. Stub clocks, mail and provider transport; exercise actual auth, quota, transactions, migrations and learner. 00 froze a per-case owner and baseline; distinguish a failing behavioral assertion from infrastructure or missing-route errors. At its assigned merge gate each scenario must be active and green. All launch scenarios must pass on PostgreSQL at 12. The four accepted risks are tracked separately.

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

Each owner also runs existing affected tests. For parallel B/C integration, C owns S27 on the real B UI and C backend. Later prompts rerun inherited scenarios listed in [§14](#arch-2) plus their feature-specific gates. A reviewer other than the author checks shared-file diffs, SQL lock order and a normal caller before a wave is promoted.

<a id="arch-7"></a>

### ✅ Shipped · P1 closure map

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

<a id="chapter-16"></a>

## 16. Gaps and Open Questions

**Designed / roadmap · decision register.** Use the following register when an old proposal and a shipped wire or persistence contract disagree. An unmounted route in a historical acceptance record is not a route that clients can call. Known historical migration risks remain outside the fresh PostgreSQL scope until their stated triggers apply.

### Resolved contradictions (17)

| Decision | Authority and disposition |
|---|---|
| C1 · Database gate | Older annotation and Post-Track 2 gates ran both dialects. The merged architecture and R4/R5 make PG the release gate; SQLite compatibility stays advisory. |
| C2 · Schema baseline | The annotation inventory counted five DLJ models. The current ORM has 26; use §3 for types, defaults, partial indexes and FKs. JM still has three separate SQLite tables. |
| C3 · Project identity | Retain Domain.id UUID, scoped internal string and account-specific alias. Do not build a second project table or replace LabelLog.domain_id with a project UUID. |
| C4 · Project HTTP DTO | Create uses flat factors/categories/actions; list returns a bare array without count pagination. PATCH uses If-Match, stale is 409, DELETE archives and returns 200. The proposed nested schema, enriched list wrapper, 412 and archive 204 are retired. |
| C5 · Team resources | POST members grants/updates a known tenant; POST invites sends a mailbox code; accept is scoped by project and invite ID. The proposed global acceptance path, list/remove/resend/revoke endpoints and invite hash route are absent. |
| C6 · Credentials and billing | Mailbox proof precedes key issuance. The purchaser/intent/payer binding and configured webhook secret supersede arbitrary tenant selection, optional signature verification and claims that the redirect grants a tier. |
| C7 · Bulk truth | Actual /bulk-verify takes items with verified_outcome or homogeneous label_ids plus outcome. An unknown outcome skips the row, not a negative result. Only processed rows consume the legacy bulk quota. |
| C8 · Batch replay | Typed batch import/prediction import use body request_key (1–200), canonical digest and scoped receipts; single project label import accepts Idempotency-Key. The earlier 1–128 header-only contract and 24-hour batch receipt target are superseded by the implemented 30-day import receipts. |
| C9 · Project export | format=docbin, review_status, date_from/date_to, root_label_id/current_label_id and nested content are shipped. The old spacy spelling, flat export columns and proposed count headers are not current wire guarantees. |
| C10 · Webhook operations | List/patch/soft-delete, /rotate, /test (201) and deliveries/health are mounted. Use subscribed_events and signing_secret, a single configured encryption key and a fenced destination version. No standalone endpoint-detail GET in the catalog. Outbound signing uses Paddle-Signature with ts/h1 and the literal issued secret, replacing the proposed X-DLJ-* headers and base64-decoding step. |
| C11 · Prediction actions | Import uses per-item model_version/source and body items; review/reopen compare expected_revision and decision_version. Reopen covers machine and human decisions; the UI projects its display states independently of the stored enum. |
| C12 · Annotation scope | Flat tags, existing NER editor and HTTPS image detail shipped. The MM plan owns strict project axes, bounded inline images, independent multi-label decisions and adjudicated span metrics. Legacy mixed projects must remain readable. |
| C13 · Frontend model | Current router has the inline /projects create form and scoped analytics, predictions and integrations routes. Earlier six-screen maps, proposed /projects/new and timing estimates describe design history. |
| C14 · Scheduling and evidence | The original prompt numbers and budgets were consolidated into 00 plus A–F and 12, six waves/five reviews. R5 passed; without a Prompt 12 release record it remains an operational gate. Historical case counts never substitute for today’s test selection. |
| C15 · Sampling and metrics | The annotation plan excluded active sampling; Sprint 0 shipped centroid-distance priority with deterministic warmup. Category kappa, category/action agreement heatmap, SLA floor and designed span F1 each have distinct denominators. |
| C16 · Deployment history | R2–R4 narrowed launch to fresh PG. Preserve the eight historical and four legacy deferrals; dual-dialect historical upgrades and a blue/green cutover are conditional work, not launch procedure. |
| C17 · Data exposure | The multimodal contract replaces the older suggestion to send raw media in webhooks. Only an authorized future detail read resolves media. The SDK is served from backend/static, not a frontend public file. |

### Superseded instructions removed from the live specification

The following remain identifiable in historical decision evidence, so audits can explain why an old client or runbook disagrees. They are retired as implementation instructions.

| Retired instruction | Current destination |
|---|---|
| Start with the old annotation or Post-Track 2 prompt 01; use their original case counts as a release gate | Wave and experiment selections in §14; scenario evidence in §15 |
| Model the project in another store; use the five-table snapshot or early forward/inverse sketch as the deployed schema | Current PostgreSQL metadata and independent JM schema in §3 |
| Promise project list wrappers, unmounted member lifecycle endpoints, direct webhook detail, or an invite-token hash route | Exact route/method/role catalog in §4 and readiness gaps in this chapter |
| Infer correctness from accepting a recommendation or assume all tag sets are independent decisions | Shared review truth in §§6–7 and designed strict sets in §10 |
| Use old prediction/import bodies, generic tenant/customer purchase fallback or an unsigned callback | Current request DTOs in §4 and payer binding in §9 |
| Sign outbound callbacks using the old X-DLJ header family or round-trip a receiver secret through list APIs | Interchange contract in §8 |
| Treat the browser queue CSV as a complete project export, require a `spacy` format parameter, or assume a response count header | Three current download formats and caps in §8 |
| Reinterpret historical mixed-content projects as strict text, add parallel media columns, or expose signed media URLs in webhooks | Compatibility bit, revision ownership and private media policy in §§3–5, 8 and 10 |
| Require SQLite parity or historic dual-instance cutover for the fresh PostgreSQL launch | PG gate, restore evidence and conditional v1.1 risks in §§13–16 |
| Read synthetic experiment scores, old fixture totals or an unblocked gate as measured customer results or proof of deployment | Product/analytics boundaries in §§1, 6 and 11; dated gate evidence in §§13–15 |

### Consolidation audit inputs

| Input (repository filename) | Bytes | Second-level sections | All headings below the title |
|---|---:|---:|---:|
| dlj_arch_redesign_v2.md (internally v3) | 54,150 | 7 | 15 |
| dlj_annotation_ui_design_v2.md | 43,681 | 10 | 22 |
| dlj_post_track2_design_v2.md | 61,359 | 11 | 16 |
| dlj_multimodal_design_v3.md | 59,117 | 11 | 11 |

The section inventory below locates all 39 second-level units, including their tables, algorithms, migration rationale, acceptance cases, prompt ownership and review history. The PostgreSQL schema, route catalog, actual screen tree, Sprint 0 logic and Analytics definitions were checked against source in addition to the four documents. [Design lineage](SUPERSEDED.md).

### Documentation gaps filled during consolidation (5)

| Area | As-built behavior now specified | Evidence and destination |
|---|---|---|
| G11 · Sampling | The first 20 verified engine observations enable centroid-distance ranking. Warmup order is deterministic, and scoring previews do not train. | `next_batch`, §6 |
| G12 · SLA semantics | Project accuracy uses effective evidence across annotators. Displayed percentage floor and the engine's algebraic gate threshold have different denominators. The coefficient's empirical provenance is not supplied. | `project_sla` and `ConservationState.check_gate`, §6 |
| G13 · Analytics definitions | Activity days, session-gap cutoff, original/current confusion and fraction-agreement differ from a human-only accuracy or kappa measure. | `analytics_router.py`, §11 |
| G14 · Current system surface | The earlier static inventories omitted later routes, ORM fields and screen families. The verified catalog covers 100 mounted application operations, 77 OpenAPI DTOs, 26 mapped tables with 238 columns, plus framework/static and legacy storage. | FastAPI and SQLAlchemy metadata, §§3–5 |
| G15 · Guided onboarding | The five-step authenticated quickstart, free report and quota-consuming demo seed are distinct workflows. Their counts, persistence and human-evidence boundaries now have separate descriptions. | QuickstartPage, GuidePage, Upload and sample handler, §§5, 12 |

### Remaining product or evidence gaps (10)

| Area | Open decision or acceptance evidence |
|---|---|
| G1 · Team lifecycle | Member listing/removal, invitation listing/revocation, session-resume invite links and the proposed per-inviter rate budget lack complete mounted contracts. Decide the supported administration surface before advertising it. |
| G2 · Profile visibility | The design reserves individual profiles for reviewers, while dashboard annotators uses the generic project reader and analytics responses can identify annotators. Decide which fields each role may read and freeze role-specific tests. |
| G3 · Schema documentation | Loose dict returns and manually decoded multipart/provider bytes leave parts of the generated OpenAPI schema unspecified. Use the §4 concrete shapes until handlers have typed response models. |
| G4 · Admission and transport | The old 4 MiB typed-import transport ceiling is a design target, not a universal current byte guard. Implement and load-test the new 20 MiB/10 MiB media policy before allowing inline strict projects. |
| G5 · Operational acceptance | Repository evidence does not establish live production release, measured Railway peak RSS/export duration, receiver lag alerts, restore drills, or ownership of on-call thresholds. Attach runtime evidence at release. |
| G6 · Webhook key lifecycle | Rotation fences unfinished deliveries and currently depends on one Fernet configuration key. A versioned at-rest key ring and migration for changing the deployment key need an explicit operator runbook. |
| G7 · Notes and guidelines | Track note data provenance, role visibility, revision copying and exported private notes across all adapters. Verify the separate feature completion before crediting new note-specific regression counts. |
| G8 · Prediction/statistics UX | Stats/list filters, coverage denominators and empty states must follow the actual DTO, not the old aspirational accuracy/risk summaries. Validate customer-facing interpretation of machine approvals vs observed human accuracy. |
| G9 · Product evidence | Competitor comparisons, synthetic transfer gains and an SLA-style badge do not prove customer accuracy, parity or legal service levels. Record representative data, cohort size, and deployment measurements before making those claims. |
| G10 · Beyond current releases | Managed assets/CDN, bounding boxes, audio/video/document geometry, SSO, cross-project transfer, real-time co-editing, staffing/assignment and formal operational SLAs still require triggers, owners or separate contracts; see §10. |

### Roadmap · accepted historical risk and reopening criteria

The launch installation starts with an empty PostgreSQL schema. A marker recorded in the first migration keeps historical repair jobs off subsequent fresh-install deploys. Before importing a legacy snapshot, reopen the affected rows below. Estimates are engineering estimates for shared work packages and overlap across related IDs.

| Item | Reason and mitigation | Trigger and owner | Future effort |
|---|---|---|---|
| N1 · old rejected receipts | An old receipt can lack trustworthy disposition history. Keep the existing retry/readback checks and preserve source events for reconciliation. New deliveries use applied receipts. | Billing owner, before importing any old receipt table or replaying unclassified deliveries. | 1–2 days |
| N2 · erroneous existing manifests | A pre-existing manifest can associate a modern key with historical ownership. Preserve an audited snapshot and quarantine ambiguous mappings. | Storage owner, before importing manifests or unblocking a quarantined payer. | 2 days with R23 |
| N9 · repair followed by checkout | A later valid checkout can make historical repair quarantine a previously reconciled payer. Keep historical repair off fresh redeploys. | Billing and storage owners, before rerunning repair on a previously repaired tenant with checkout activity. | 2 days with N2 |
| R23 · provider ownership repair | Ambiguous pre-A provenance requires operator evidence before activation. Preserve the existing before/after manifest and conditional undo. | Migration owner, on the first proposed pre-A provider import. | 2–3 days with N2/N9 |
| F1 · historical intent exemption | An old customer/subscription mapping may have insufficient provenance. New grants require a purchaser, payer and provider transaction bound to an intent. | Billing owner, before accepting an intent-free historical creation. | 1 day with R23 |
| N10 · old mixed tombstones with a pending purchase | Historical normalization can override an outstanding intent. Keep those rows out of the launch database and preserve them for reconciliation. | Storage owner, before processing mixed historical keys or restoring such a backup. | 2–3 days with R14/F2/F5 |
| R14 · historical terminalization | Replaying old terminal states requires guarded reconciliation and per-key version checks. Modern retention runs under the tenant guard. | Lifecycle owner, before admitting historical tombstones. | 1–2 days with N10 |
| F2 · legacy cleanup holds | Historical rows can have mixed payer, intent and repair holds. Inventory holds before normalization. | Retention owner, when importing historical siblings with nonterminal obligations. | 1 day with N10 |
| F5 · legacy audit gaps | Historical normalization can change state without a contemporaneous transition or notice. Preserve original versions and reconcile them offline. | Billing owner, before historical transitions feed notices or support tooling. | 1 day with N10 |
| N11 · historical simultaneous events | Existing watermarks may encode a prior arrival-order decision. Preserve signed history for offline reconciliation. Current deliveries have a deterministic cancellation tie rule. | Billing owner, before replaying an old event stream with ties. | 1–2 days with R19 |
| R19 · retrospective lifecycle reconciliation | Previously persisted state may disagree with a replay of equal-time events. Compare payer state, notice history, quota and retention before cutover. | Billing owner, before a historical payer or watermark enters service. | 1 day with N11 |

### Source coverage and overlap inventory

The four inputs below contribute 39 second-level units in total. Every named subheading belongs to its parent row and is carried into that destination. “Arch” is the v3 update in the v2 filename. Original prompt estimates, earlier fixture counts and proposals are identified as historical review evidence; current instructions are labeled in the chapter introductions.

| Source section | Subject | Implementation status | Overlap or precedence | Merged location |
|---|---|---|---|---|
| Arch · 1. P1 launch classification | Release obligations | Shipped in fresh-PG scope; eight historical cases/review holds tracked separately | S15 register and implementation history in §15; v1.1 exceptions in §16 | [§14](#arch-1) |
| Arch · 2. Merged prompts | Wave ownership, gates, reusable regressions | 00 and A–F shipped; 12 is a release gate | Supersedes Post-Track 2 ordering; the specific product contracts are distributed to §§2,5,7–9 | [§14](#arch-2) |
| Arch · 3. Deferred to v1.1 | Deferred work | Roadmap | Legacy single-writer, credential, centroid, cutover risks; overlaps deployment | [§13](#arch-3) |
| Arch · 4. Consolidated schema ledger | Schema and downgrade ledger | Shipped for fresh install; historical repair conditional | Physical schema in §3 wins over earlier DDL sketches | [§3](#arch-4) |
| Arch · 5. Integration scenarios and release evidence | Scenario gates | Shipped | Current status from R5; PG is primary | [§15](#arch-5) |
| Arch · 6. Timeline and critical path | Timeline and operational release | R1–R5 shipped; release evidence outstanding | Original cost retained as historical estimate | [§13](#arch-6) |
| Arch · 7. P1 closure map | P1 closure oracles | Shipped for fresh-PG scope | §16 records exceptions | [§15](#arch-7) |
| Annotation · §1 Current state | Early workflow baseline | Shipped later; old screen/route counts historical | Replaced by scoped screens and typed detail | [§5](#anno-1) |
| Annotation · §2 Competitive landscape | Competitive observations | Design rationale | Capability claims limited by §10 | [§1](#anno-2) |
| Annotation · §3 Annotation architecture | Persistence, CSV and text migration | Shipped for per-row types | §3 physical catalog and §10 strict projects take precedence | [§3](#anno-3) |
| Annotation · §4 Frontend components | Annotation screens, sample and settings | Shipped foundation; project workflows extended | Project context §5 and payer policy §9 supersede early assumptions | [§5](#anno-4) |
| Annotation · §5 Backend endpoints | Annotation HTTP adapters | Shipped under actual names; proposed variants retired | §4 contains exact mounted paths | [§4](#anno-5) |
| Annotation · §6 Implementation phases | Phases A–D | Historical delivery record | Distinct from later Post-Track 2 A–F packages | [§14](#anno-6) |
| Annotation · §7 Scope boundary | Excluded annotation formats | Roadmap | §10 supersedes initial sampling and modality boundaries | [§10](#anno-7) |
| Annotation · §8 Effort summary | Annotation estimates | Historical budget | Recorded for lineage; current evidence in §14 | [§14](#anno-8) |
| Annotation · §9 Risk assessment | Implementation risks | Shipped controls and ongoing regression oracles | Overlap §15 | [§14](#anno-9) |
| Annotation · §10 Execution plan | Prompt briefs, tests and ordering | Completed historical handoff | Current next-feature prompts are MM-01–07 | [§14](#anno-10) |
| Post-Track · 1. Identity, access and project lifecycle | Actor, payer, projects and team | Shipped core; additional team management designed | Role and contract differences C4–C6 | [§9](#track-1) |
| Post-Track · 2. Persistence and ownership | Persistence, ownership and predicates | Shipped core, historical migrations conditional | Actual keys and constraints §3 | [§3](#track-2) |
| Post-Track · 3. HTTP surface and legacy adapters | Resource design and sample DTOs | Partially shipped; superseded wire forms identified | Use live catalog and C4–C11 | [§4](#track-3) |
| Post-Track · 4. Project export | Export | Shipped core; optional UI counters/headers remain proposals | Current §8 and designed media output §8 | [§8](#track-4) |
| Post-Track · 5. Frontend and developer interface | Developer and browser UX | Shipped core; original extra routes are not mounted | §5 mounted paths and §8 SDK | [§5](#track-5) |
| Post-Track · 6. Prediction review and quota accounting | Prediction review and accounting | Shipped | Wire contract and reopen behavior use §4/§7 | [§7](#track-6) |
| Post-Track · 7. Project webhooks | Durable outbound webhooks | Shipped core; canonical protocol in §8 | Historical delivery header names superseded | [§8](#track-7) |
| Post-Track · 8. Database upgrade, rollout and recovery | Deployment and recovery | Designed operations; runtime readiness requires evidence | §13 merged release protocol wins | [§13](#track-8) |
| Post-Track · Delivery estimate | Delivery estimate | Historical budget | Replaced by six integrated waves | [§14](#track-9) |
| Post-Track · 9. Ordered implementation prompts and release gates | Prompt order, implementation handoff, optimized schedule | Historical delivery lineage | 00 + A–F + 12 superseded the unmerged plan | [§14](#track-10) |
| Post-Track · Appendix A. Traceability to the v1 Astra review | Traceability and baseline | Historical review evidence | §14 latest regression status | [§16](#track-11) |
| MM · 1. What exists and what must change | As-built boundaries | Shipped baseline; strict extension designed | Consolidates project/content/engine contract | [§2](#mm-1) |
| MM · 2. Project matrix and compatibility | Project axes | Designed | Legacy typed rows remain distinct | [§10](#mm-2) |
| MM · 3. Storage, migration and rollback | Migration and rollback | Designed | Extends current schema; no physical columns yet | [§3](#mm-3) |
| MM · 4. Image import, validation and replay | Typed media ingest and replay | Designed | Extends current HTTP adapters | [§4](#mm-4) |
| MM · 5. What reviewers see | Image authoring and review | Designed | Reuses shipped viewer | [§5](#mm-5) |
| MM · 6. Export, events and SDK | Media export/events/SDK | Designed | New media policy is deliberately additive | [§8](#mm-6) |
| MM · 7. Multi-label classification (ML) | Independent category-set scoring | Designed | Distinct from shipped descriptive tags | [§10](#mm-7) |
| MM · 8. Text NER and agreement (NER) | Strict NER and span IAA | Designed | Distinct from existing editors/category metrics | [§10](#mm-8) |
| MM · 9. Product boundaries and release triggers | Release triggers | Roadmap | Replaces unsupported parity claims | [§10](#mm-9) |
| MM · 10. Review ledger | Multimodal review findings | Designed resolutions | Source discrepancies and planned changes tracked separately | [§16](#mm-10) |
| MM · 11. Ordered Codex prompts and verification | MM prompt gates | Designed | Estimates separated from executed tests | [§14](#mm-11) |

<a id="track-11"></a>

### Design record · Appendix A. Traceability to the v1 Astra review

**Disposition.** Historical review evidence. §14 latest regression status.

<details>
<summary>Post-Track 2 decision detail and acceptance history</summary>

Verdicts describe the reviewed v1. Sections 1–9 contain the replacement design. The earlier review listed ten items. Items 11–13 cover additional requests from the review brief.

| # | Finding against v1 | Implemented design decision |
|---|---|---|
| 1 · BLOCKER | db/models.py has UUID primary keys and a nonunique ApiKey.tenant_id. The proposed tenant FK cannot be enforced | Use Domain as project, proper UUID FKs and explicit billing binding ([§9](#track-1)–[§3](#track-2)) |
| 2 · BLOCKER | Domain.id cannot backfill label_log.domain_id. Old SQLite rebuild can drop child data | Preserve internal keys and rehearse additive migration ([§13](#track-8)) |
| 3 · BLOCKER | require_tenant would give an invitee with an owner credential tenant-wide access | Authorize the actor, project role and billing principal independently ([§9](#track-1)) |
| 4 · ISSUE | LabelLog has no stored historical tier or created_at. Structured content belongs to a revision | Export the joined current revision and real timestamps ([§3](#track-2), [§8](#track-4)) |
| 5 · BLOCKER | _ingest reports advisory autonomy. Treating approval as verification feeds the decision back into training | Persist machine disposition and human evidence separately ([§7](#track-6)) |
| 6 · ISSUE | Scheduler sleeps hourly. Request tasks lose delayed deliveries on restart | Commit events and delivery rows with the mutation; use leased workers ([§8](#track-7)) |
| 7 · ISSUE | Flat NavLinks, rgi-domain and the catch-all would lose the selected project | Nested HashRouter scope, explicit aliases and saved-target handling ([§5](#track-5)) |
| 8 · ISSUE | create_all and empty-tenant fixtures miss upgrades and cross-account cases | Old-schema fixtures, distinct actors, two database lanes and browser journeys ([§13](#track-8)–[§14](#track-10)) |
| 9 · BLOCKER | Hash/public name/UUID fallback can resolve the wrong engine | Each namespace has one resolver and both call the same data services ([§9](#track-1), [§4](#track-3)) |
| 10 · ISSUE | 12.5 days omits access, billing reconciliation, export memory and retry recovery | 30 engineering days, sequenced and gated ([§14](#track-10)) |
| 11 · ISSUE | Browser CSV already calls JSON batch ingest; old label detail catches dynamic path segments | Version project DTOs under a new prefix and share the scorer ([§4](#track-3)) |
| 12 · PASS | FastAPI reference and hash guide coexist | Publish a tested client and quickstart alongside OpenAPI ([§5](#track-5)) |
| 13 · ISSUE | Member cleanup, secret rotation, rollout and operational signals were unspecified | Specify lifecycles, retention, canary and rollback ([§9](#track-1), [§8](#track-7)–[§13](#track-8)) |


#### Baseline evidence

On 24 November, test_content.py, test_tasks.py, test_queue.py and test_labeling_router.py passed **56/56 on SQLite and 56/56 on PostgreSQL** on port 5433. These runs establish the existing labeling baseline. The implementation-design update also exercised all eight test_bulk_review.py cases on each database. The requested test_jm_docker_live_v3.py found no listener on its default localhost:8000 (0/14). Against an isolated local Uvicorn instance backed by temporary SQLite stores it passed 12/14. The script expects the old health response (status=ok and a service field), and its compounding loop received a response without decision_id. That loop did not record the response status, so its failure cause remains unconfirmed. The script exercises the original JM API. No Railway deployment or new feature was exercised.

</details>

<a id="mm-10"></a>

### Designed · Review ledger

P1 would prevent safe implementation or change the meaning of stored decisions. P2 would ship an incomplete workflow or contract. P3 affects clarity or planning. Each row identifies the original design location, the source evidence and the normative resolution.

| ID | v2 section and source | Finding → resolution |
|---|---|---|
| P1-01 | Earlier design, db/models.py | A second URL/metadata store could diverge across revisions. Use LabelContent and its cascading FK; widen its existing URL field ([§3](#mm-3)). |
| P1-02 | Earlier design, labeling_router.py | Existing typed/mixed projects cannot all be reinterpreted as text/single. Record opt-in enforcement and preserve per-item history ([§10](#mm-2)). |
| P1-03 | Earlier design, projects_router.py, auth.py | Nullable defaults and an unlocked first-label check permit invalid policies or races. Enforce the DB matrix and serialize every ingress with settings ([§10](#mm-2)–[§4](#mm-4)). |
| P1-04 | Earlier design, labeling_router.py | An item validator alone cannot bound a buffered batch; large embedded input can appear in errors. Bound transport, concurrency, encoded/decoded size and diagnostic output ([§4](#mm-4)). |
| P1-05 | Earlier design, project_import_batch | New DTO defaults or caption normalization could invalidate old receipts or admit changed input. Freeze old digests and canonicalize aliases before charge ([§4](#mm-4)). |
| P1-06 | Earlier design, label_studio.py, labeling_router.py | Predictions, aliases, separate content creation and task/sample routes can bypass policy or lose content at revision. Apply one invariant to every writer ([§4](#mm-4)). |
| P1-07 | Earlier design, _export_rows, record_webhook_event | Inline or signed media would multiply across pages/spools and leave private content in outbound deliveries. Budget exports and deliver authenticated references ([§8](#mm-6)). |
| P1-08 | Earlier design, db/repository.py | Existing tags do not represent N decisions. Define group/member identity, charging, revisions and explicit per-child truth ([§10](#mm-7)). |
| P1-09 | Earlier design, dashboard_router.py | Category kappa cannot measure spans; ordinary verification cannot prove they were reviewed. Bind sources, record explicit adjudication, define one-to-one agreement ([§10](#mm-8)). |
| P2-01 | Earlier design, jm_core.py | Proposed engine inputs conflate content, engine selection and scoring. Freeze the actual signature/hash and compare numeric outputs ([§2](#mm-1)). |
| P2-02 | Earlier design, db/migrate.py | A standalone SQL file lacks startup wiring, mixed-version rollout and a data-preserving downgrade. Specify inspector, defaults, repeat and rollback gates ([§3](#mm-3)). |
| P2-03 | Earlier design, ProjectImportItem, frontend/src/csv.ts | Wrong caption name, ambiguous media forms and CSV factor inference break import. Define aliases, parser exclusions, direct import, errors and byte-aware chunking ([§4](#mm-4)–[§5](#mm-5)). |
| P2-04 | Earlier design, Projects.tsx, domain.tsx, ReviewCard.tsx | Form, context, smart queue, prediction card and viewer behavior were underspecified. Define loading/ownership, component props and failure UI ([§5](#mm-5)). |
| P2-05 | Earlier design, export_project, backend/static/dlj_client.py | “Export header” and “unchanged client” leave empty CSV, DocBin, SDK and content visibility ambiguous. Freeze formats, headers, methods and examples ([§8](#mm-6)). |
| P2-06 | Earlier design, NEREditor.tsx, labeling_router.py | Span coordinate system, supported entity vocabulary and limits differ across editing/import. Define Unicode offsets, strict bounds and shared validation ([§10](#mm-8)). |
| P2-07 | Earlier design, [§10](#mm-2) of architecture authority | Assumed disjoint files and a single small image prompt omit integration, migration rehearsal and review. Assign file ownership, deltas and gates ([§14](#mm-11)). |
| P3-01 | [§2](#mm-1),[§10](#mm-8) | Competitive rankings are unsubstantiated by this repository. Publish capability-specific positioning gated by tests ([§10](#mm-9)). |
| P3-02 | [§4](#mm-4),[§10](#mm-7)–[§10](#mm-8) | Hosted assets and other annotation geometries had no adoption criteria or consistent sequencing. Give each a product trigger and order releases by dependencies ([§10](#mm-9),[§14](#mm-11)). |
