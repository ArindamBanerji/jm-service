# DLJ Post-Track 2: Product Table-Stakes Design
**Date:** November 24, 2026 · **Version:** v1
**Status:** Design document — for Astra review, then Codex prompts
**Repo:** ArindamBanerji/jm-service
**Depends on:** Track 2 (Phases A–D) complete — annotation UI, NER, bulk review, search, settings, IAA

---

## 1. Context

Track 2 delivers the annotation UI and core labeling workflow. After it ships, DLJ
has: sample data, text/NER display, signup, queue with pagination/sort/search,
settings, inline relabeling, span editor, tags, image classification (read-only),
keyboard shortcuts, guidelines, IAA, and bulk review.

**What's still missing to compete:** DLJ is a single-user tool with no concept of
projects, no data export, no programmatic API beyond scoring, no pre-labeling, and
no pipeline integration. Every competitor — Label Studio, Labelbox, Cleanlab, Encord,
Prodigy — has these. Without them, DLJ is a demo, not a product.

This document designs the five capabilities that close the gap, in priority order.

---

## 2. Current Data Model (after Track 2)

```
api_keys
  id, key_hash, tenant_id, tenant_name, tier, contact_email,
  daily_label_count, daily_label_reset, created_at

domains
  id, name, tenant_id, description, created_at

label_log
  id, label_id, domain_id, tenant_id, category, annotator_id,
  verified_outcome, factors (JSON), score, tier,
  text, spans (JSON), tags (JSON), content_type,
  created_at, updated_at

label_corrections (from Track 2 relabel)
  id, label_id, old_category, new_category, corrected_by, created_at

annotator_profiles
  id, annotator_id, domain_id, labels_reviewed, accuracy, ...
```

Key observations:
- **No "project" entity** — domains serve as the grouping unit but have no team, settings, or export config
- **No user accounts beyond API keys** — a "user" is a tenant_id with one API key
- **No invitation or role model** — single-user only
- **No export format config** — data can be queried but not exported in standard ML formats
- **No webhook/callback infrastructure** — no event system at all

---

## 3. Feature 1: Projects + Multi-User (P1, ~4 days)

### 3.1 Why first

Without projects and teams, every customer is isolated. They can't:
- Organize different labeling jobs separately
- Invite annotators or reviewers
- Share results with their ML team

### 3.2 Data model additions

```python
# New table: projects (replaces "domain" as the user-facing concept)
class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_keys.tenant_id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Labeling config
    label_schema: Mapped[dict | None] = mapped_column(JSON)  # categories, entity types, tag options
    guidelines: Mapped[str | None] = mapped_column(Text)      # markdown instructions for annotators
    content_type: Mapped[str] = mapped_column(String(50), default="text")  # text, text_ner, text_multilabel, image_classification
    # State
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, archived, completed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

# New table: project_members (multi-user)
class ProjectMember(Base):
    __tablename__ = "project_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))  # owner, admin, reviewer, annotator
    invited_by: Mapped[str | None] = mapped_column(String(36))  # tenant_id of inviter
    # Auth: invited members get their own API key scoped to this project
    api_key_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("api_keys.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, revoked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

### 3.3 Role permissions

| Action | owner | admin | reviewer | annotator |
|---|---|---|---|---|
| Create/delete project | ✅ | ❌ | ❌ | ❌ |
| Edit project settings | ✅ | ✅ | ❌ | ❌ |
| Invite/remove members | ✅ | ✅ | ❌ | ❌ |
| Upload data | ✅ | ✅ | ✅ | ❌ |
| Annotate / relabel | ✅ | ✅ | ✅ | ✅ |
| Bulk approve/reject | ✅ | ✅ | ✅ | ❌ |
| Export data | ✅ | ✅ | ✅ | ❌ |
| View dashboard | ✅ | ✅ | ✅ | ✅ |
| View annotator profiles | ✅ | ✅ | ✅ | ❌ |
| Delete data | ✅ | ✅ | ❌ | ❌ |

### 3.4 API endpoints

```
POST   /v1/projects                        Create project
GET    /v1/projects                        List my projects
GET    /v1/projects/{id}                   Get project detail
PATCH  /v1/projects/{id}                   Update settings
DELETE /v1/projects/{id}                   Archive project
POST   /v1/projects/{id}/members           Invite member (sends email)
GET    /v1/projects/{id}/members           List members
PATCH  /v1/projects/{id}/members/{mid}     Change role
DELETE /v1/projects/{id}/members/{mid}     Remove member
POST   /v1/projects/{id}/accept-invite     Accept invitation (creates scoped API key)
```

### 3.5 Migration strategy (domain → project)

Domains already partition data by tenant. The migration:
1. Create a `projects` row for each existing `domains` row (same id, copy name/description)
2. Create a `project_members` row for each tenant (role=owner)
3. Add `project_id` column to `label_log`, backfill from `domain_id`
4. Keep `domain_id` for backward compatibility — new code uses `project_id`
5. All existing API endpoints continue to work with `domain_id` parameter
6. New project-scoped endpoints use `project_id`

This is fully backward compatible — existing integrations don't break.

### 3.6 Frontend changes

| Screen | Change |
|---|---|
| **New: Project List** (/#/projects) | Card grid of projects with name, member count, label count, status badge |
| **New: Project Settings** (/#/projects/{id}/settings) | Name, description, label schema editor, guidelines (markdown), members list with invite |
| **Sidebar** | Add project switcher dropdown at top. Current project name shown. |
| **All existing screens** | Scoped to selected project. URL pattern: /#/projects/{id}/queue, etc. |
| **Settings** | Add "Team" section — list members, invite by email |

### 3.7 Invitation flow

1. Owner/admin enters email on Project Settings → Team
2. Backend creates ProjectMember (status=pending), sends invitation email via Resend
3. Email contains link: `https://dlj.dakshineshwari.net/#/invite/{token}`
4. Recipient clicks → if no account, redirected to signup first → then accept-invite → gets project-scoped API key
5. Member appears in Team list as "active"

### 3.8 Tests target

- 12 pytest: CRUD project, invite flow, role enforcement, migration
- 4 Playwright: project list, create, settings, member invite

---

## 4. Feature 2: Export (P2, ~2 days)

### 4.1 Why second

Labeled data trapped in DLJ is worthless. ML engineers need to get it out in
formats their training pipelines accept.

### 4.2 Supported formats

| Format | Extension | Use case | Priority |
|---|---|---|---|
| **JSONL** | .jsonl | Universal ML format. One JSON object per label. | Must-have |
| **CSV** | .csv | Spreadsheet/pandas users. Flat columns. | Must-have |
| **spaCy DocBin** | .spacy | NER training with spaCy. Binary format. | Must-have (NER) |
| **CoNLL** | .conll | NER evaluation standard. Token-per-line. | Nice-to-have |
| **COCO** | .json | Image classification/detection. | Future (when image annotation ships) |
| **Label Studio JSON** | .json | Import into Label Studio for further annotation. | Nice-to-have |

### 4.3 JSONL format (the canonical export)

```jsonl
{"label_id":"L001","text":"John Smith is the CEO of Acme Corp.","category":"PERSON","annotator_id":"ann_1","verified_outcome":true,"score":0.87,"tier":"GREEN","spans":[{"start":0,"end":10,"label":"PERSON","text":"John Smith"},{"start":25,"end":34,"label":"ORG","text":"Acme Corp"}],"tags":["executive","named_entity"],"factors":{"confidence":0.92,"agreement":0.85},"created_at":"2026-11-20T10:30:00Z"}
```

### 4.4 CSV format

```csv
label_id,text,category,annotator_id,verified_outcome,score,tier,spans,tags,confidence_factor,agreement_factor,created_at
L001,"John Smith is the CEO of Acme Corp.",PERSON,ann_1,true,0.87,GREEN,"[{""start"":0,""end"":10,""label"":""PERSON""}]","[""executive""]",0.92,0.85,2026-11-20T10:30:00Z
```

### 4.5 spaCy DocBin format

```python
# Generated server-side using spacy
import spacy
from spacy.tokens import DocBin
nlp = spacy.blank("en")
doc_bin = DocBin()
for label in labels:
    doc = nlp.make_doc(label.text)
    ents = []
    for span in label.spans:
        ents.append(doc.char_span(span["start"], span["end"], label=span["label"]))
    doc.ents = [e for e in ents if e is not None]
    doc_bin.add(doc)
doc_bin.to_disk("export.spacy")
```

### 4.6 API endpoints

```
GET /v1/projects/{id}/export?format=jsonl                    → streaming download
GET /v1/projects/{id}/export?format=csv                      → streaming download
GET /v1/projects/{id}/export?format=spacy                    → binary download
GET /v1/projects/{id}/export?format=jsonl&status=verified     → filter by status
GET /v1/projects/{id}/export?format=jsonl&category=PERSON     → filter by category
GET /v1/projects/{id}/export?format=jsonl&annotator=ann_1     → filter by annotator
```

Query params:
- `format` (required): jsonl, csv, spacy, conll
- `status`: all (default), verified, pending, overridden
- `category`: filter to specific category
- `annotator`: filter to specific annotator_id
- `from_date`, `to_date`: date range filter
- `include_factors`: true/false (default true) — whether to include factor scores

Response: `Content-Disposition: attachment; filename="project_name_export_2026-11-24.jsonl"`
Streaming response for large datasets (StreamingResponse with async generator).

### 4.7 Frontend

- **Export button** on Queue screen toolbar (already outlined in Track 2)
- **Export dialog**: format picker (JSONL recommended, CSV, spaCy), filter options, "Download" button
- **Project Settings → Export**: same dialog but for full project export, plus scheduled export option (future)

### 4.8 Tests target

- 8 pytest: each format correct, filters work, streaming for large datasets, auth guard
- 2 Playwright: export button visible, download triggers

### 4.9 Dependencies

- `spacy` (pip install spacy) — only for DocBin export. Use `spacy.blank("en")` — no model download needed.
- No other new dependencies.

---

## 5. Feature 3: API Documentation + Programmatic Upload/Export (P3, ~2 days)

### 5.1 Why third

ML engineers integrate labeling into their pipelines. Without documented API
endpoints and code examples, they won't adopt DLJ — they'll use Label Studio
(which has a Python SDK).

### 5.2 What to build

**A. Human-readable API guide (static page)**

Served at `/#/docs` or `/docs/guide` (separate from the auto-generated OpenAPI at `/docs`).

Sections:
1. **Quickstart** — curl examples for the full loop: register → create project → upload → score → verify → export
2. **Authentication** — X-Api-Key header, trial limits, upgrade path
3. **Endpoints reference** — grouped by resource (projects, labels, export, account), each with:
   - Method + URL
   - Request body (JSON example)
   - Response body (JSON example)
   - Error codes
   - curl + Python examples
4. **Webhooks** — event types, payload format, verification
5. **Rate limits** — per-endpoint limits, 429 handling
6. **Data formats** — CSV column spec, JSONL schema, NER spans format

**B. Python client library (dlj-python)**

Minimal SDK — thin wrapper around requests. NOT a full SDK — just convenience:

```python
# pip install dlj-python  (future — for now, ship as a single-file snippet)
from dlj import DLJClient

client = DLJClient(api_key="dlj_...", base_url="https://dlj.dakshineshwari.net")

# Create project
project = client.create_project("Medical NER", content_type="text_ner")

# Upload labels with content
client.upload(project.id, [
    {"label_id": "L001", "category": "PERSON", "annotator_id": "ann_1",
     "text": "John Smith is the CEO", "spans": [{"start": 0, "end": 10, "label": "PERSON"}]},
])

# Score
results = client.score(project.id)

# Export
client.export(project.id, format="jsonl", path="output.jsonl")
```

**For launch: ship as a downloadable `dlj_client.py` single file on the docs page.**
PyPI package is Phase 2.

**C. OpenAPI spec enhancement**

The existing FastAPI auto-generated `/docs` already works. Enhance:
- Add `description` to every endpoint
- Add `example` to every request/response model
- Add `tags` grouping (Projects, Labels, Export, Account, Billing)
- Add `summary` one-liners

### 5.3 Programmatic upload endpoint (new)

Currently upload is CSV-only via the browser. Add a JSON batch endpoint:

```
POST /v1/projects/{id}/labels/batch
Content-Type: application/json
X-Api-Key: dlj_...

{
  "labels": [
    {
      "label_id": "L001",
      "category": "PERSON",
      "annotator_id": "ann_1",
      "text": "John Smith is the CEO of Acme Corp.",
      "content_type": "text_ner",
      "spans": [{"start": 0, "end": 10, "label": "PERSON", "text": "John Smith"}],
      "factors": {"confidence": 0.92, "agreement": 0.85}
    }
  ]
}

Response: {"ingested": 1, "errors": [], "project_id": "...", "pending_count": 1}
```

This replaces the current CSV-only ingest path for programmatic use.
The existing CSV upload endpoint stays for browser users.

### 5.4 Tests target

- 6 pytest: batch JSON upload, OpenAPI spec validates, auth on new endpoints
- 2 Playwright: docs page renders, code examples are copy-able

---

## 6. Feature 4: Pre-labeling / Model-Assisted Annotation (P4, ~3 days)

### 6.1 Why fourth

Pre-labeling is the #1 trend in data labeling (per Encord, G2, every analyst report).
Import model predictions → annotators correct instead of labeling from scratch → 3–5x
speed improvement. This is the differentiator that justifies DLJ's pricing vs. free
Label Studio.

### 6.2 How it works

```
   Model predictions        Upload to DLJ          Annotator review
   ┌──────────┐             ┌──────────┐           ┌──────────┐
   │ Your NER  │  ──JSON──> │ DLJ pre- │  ──UI──>  │ Accept / │
   │ model     │            │ labels   │           │ correct  │
   └──────────┘             └──────────┘           └──────────┘
                                  │                      │
                                  ▼                      ▼
                            Pre-labels shown       Verified outcome
                            with LOW confidence    feeds compounding
                            (not yet verified)     engine
```

### 6.3 Data model

```python
# Add to label_log or a new column
class LabelLog:
    # ... existing fields ...
    prediction_source: Mapped[str | None]    # "model_v1", "gpt-4", "rule_based", etc.
    prediction_confidence: Mapped[float | None]  # model's own confidence (0-1)
    is_prediction: Mapped[bool] = mapped_column(Boolean, default=False)
    # When is_prediction=True:
    #   - verified_outcome is NULL (not yet reviewed)
    #   - score/tier are from DLJ's own scoring of the prediction
    #   - Annotator sees it in queue with "Pre-label" badge
    #   - On accept: verified_outcome=True, counts as confirm
    #   - On override: verified_outcome=True, new_category set, counts as override
```

### 6.4 API endpoints

```
POST /v1/projects/{id}/predictions
Content-Type: application/json

{
  "source": "my_ner_model_v2",
  "predictions": [
    {
      "label_id": "L001",
      "text": "John Smith is the CEO of Acme Corp.",
      "predicted_category": "PERSON",
      "predicted_spans": [{"start": 0, "end": 10, "label": "PERSON"}],
      "model_confidence": 0.94
    }
  ]
}

Response: {"imported": 50, "scored": 50, "auto_approved": 12, "pending_review": 38}
```

**Auto-approve gate:** If DLJ's own score for the prediction exceeds the project's
conservation threshold AND the model confidence exceeds a configurable floor (default 0.95),
the prediction is auto-approved without human review. This is the **compounding intelligence
payoff** — as DLJ learns, it needs fewer human reviews.

```
GET /v1/projects/{id}/predictions/stats

{
  "total_imported": 500,
  "auto_approved": 120,
  "human_reviewed": 280,
  "pending": 100,
  "auto_approve_rate": 0.30,
  "avg_model_confidence": 0.82,
  "avg_dlj_score": 0.71,
  "source": "my_ner_model_v2"
}
```

### 6.5 Frontend changes

| Screen | Change |
|---|---|
| **Queue** | Pre-labeled items show a "Pre-label" badge. Sortable by prediction_confidence. Filter: "pre-labels only" / "human only" / "all" |
| **ReviewCard** | For pre-labeled items: show model's prediction vs. DLJ's assessment side by side. "Accept prediction" button (shortcut: P). "Correct" opens the existing relabel flow. |
| **Dashboard** | New card: "Pre-label Stats" — auto-approve rate, human review rate, model accuracy vs. DLJ accuracy |
| **Project Settings** | Auto-approve threshold slider (0.80–0.99, default 0.95). Conservation gate still applies. |

### 6.6 Compounding intelligence integration

Pre-labeling is where DLJ's compounding engine really shines:

1. **Day 1:** Import 500 predictions from your NER model. DLJ scores them all. 0% auto-approve (DLJ hasn't learned yet).
2. **Day 3:** Annotators have verified 200. DLJ's centroids are forming. Auto-approve rate rises to 15%.
3. **Day 7:** 400 verified. Conservation is GREEN. Auto-approve rate is 35%.
4. **Day 14:** New batch of 500 predictions imported. DLJ auto-approves 180 (36%) immediately. Annotators only need to review 320.

This is the **$1.62M/yr headline** for data labeling: 3x fewer human reviews within 2 weeks.

### 6.7 Tests target

- 10 pytest: import predictions, auto-approve gate, scoring of predictions, stats endpoint
- 3 Playwright: pre-label badge, accept prediction, stats card

---

## 7. Feature 5: Webhooks + Pipeline Integration (P5, ~1.5 days)

### 7.1 Why fifth

When labeling is done or a batch is auto-approved, downstream pipelines need to know.
Without webhooks, teams poll or manually trigger exports — that's not a product.

### 7.2 Event types

| Event | Fires when | Payload includes |
|---|---|---|
| `label.verified` | A label is verified (approved or overridden) | label_id, project_id, outcome, score, tier |
| `label.batch_complete` | All labels in an upload batch are verified | batch_id, project_id, total, approved, overridden |
| `project.export_ready` | An async export finishes | project_id, export_url (signed, 24h expiry), format, count |
| `prediction.auto_approved` | A pre-label passes auto-approve gate | label_id, project_id, model_confidence, dlj_score |
| `conservation.threshold` | Conservation status changes (GREEN→AMBER→RED) | project_id, old_status, new_status, verified_count |

### 7.3 Data model

```python
class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("api_keys.tenant_id"))
    url: Mapped[str] = mapped_column(String(2048))
    secret: Mapped[str] = mapped_column(String(64))  # for HMAC-SHA256 signing
    events: Mapped[list] = mapped_column(JSON)  # ["label.verified", "project.export_ready"]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    endpoint_id: Mapped[str] = mapped_column(String(36), ForeignKey("webhook_endpoints.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

### 7.4 API endpoints

```
POST   /v1/webhooks                         Register webhook endpoint
GET    /v1/webhooks                         List my webhooks
GET    /v1/webhooks/{id}                    Get webhook detail + recent deliveries
PATCH  /v1/webhooks/{id}                    Update URL, events, active status
DELETE /v1/webhooks/{id}                    Delete webhook
POST   /v1/webhooks/{id}/test               Send a test event to verify connectivity
GET    /v1/webhooks/{id}/deliveries          List delivery attempts with status
```

### 7.5 Delivery mechanics

- **Signing:** HMAC-SHA256 of the JSON payload using the webhook secret. Header: `X-DLJ-Signature: sha256=<hex>`
- **Timeout:** 10 seconds per delivery attempt
- **Retries:** 3 attempts with exponential backoff (10s, 60s, 300s)
- **Delivery log:** Last 100 deliveries stored per endpoint, viewable via API
- **Implementation:** Background task using asyncio (no Celery/Redis needed at this scale)

### 7.6 Webhook payload format

```json
{
  "id": "evt_abc123",
  "type": "label.verified",
  "created_at": "2026-11-24T10:30:00Z",
  "data": {
    "label_id": "L001",
    "project_id": "proj_xyz",
    "category": "PERSON",
    "verified_outcome": true,
    "score": 0.87,
    "tier": "GREEN"
  }
}
```

### 7.7 Frontend changes

| Screen | Change |
|---|---|
| **Project Settings → Integrations** | Webhook management: add URL, select events, test button, delivery log |
| **Dashboard** | Webhook health indicator: green if recent deliveries succeed, yellow if retrying, red if failing |

### 7.8 Tests target

- 8 pytest: register, delivery, signing verification, retry logic, test event, auth guard
- 2 Playwright: webhook settings UI, test button

---

## 8. Implementation Order + Effort

| # | Feature | Effort | Codex Prompts | Dependencies |
|---|---|---|---|---|
| **P1** | Projects + Multi-User | 4 days | 2–3 | Track 2 complete |
| **P2** | Export | 2 days | 1–2 | P1 (project scoping) |
| **P3** | API Docs + Programmatic Upload | 2 days | 1–2 | P1 (project endpoints) |
| **P4** | Pre-labeling | 3 days | 2 | P1 + P2 |
| **P5** | Webhooks | 1.5 days | 1 | P1 |
| **Total** | | **~12.5 days** | **7–10** | |

### Prompt breakdown (tentative)

| Prompt | Content | Model |
|---|---|---|
| DLJ-P1a | Projects model, migration, CRUD endpoints, project list UI | Spark+high |
| DLJ-P1b | Members model, invitation flow, role enforcement, team UI | Spark+high |
| DLJ-P1c | URL routing migration (/#/projects/{id}/...), project switcher | Spark+medium |
| DLJ-P2 | Export endpoints (JSONL, CSV, spaCy), export dialog UI | Spark+high |
| DLJ-P3a | Batch JSON upload endpoint, OpenAPI enhancements | Spark+medium |
| DLJ-P3b | API guide page (/#/docs), downloadable Python client snippet | Spark+medium |
| DLJ-P4a | Predictions model, import endpoint, auto-approve gate | Spark+high |
| DLJ-P4b | Pre-label UI (badge, accept, stats card, threshold setting) | Spark+high |
| DLJ-P5 | Webhooks model, CRUD, delivery engine, settings UI | Spark+high |

---

## 9. Database Migration Strategy

All migrations go through `db/migrate.py` (idempotent, same pattern as Track 2).

### Migration order:
1. `projects` table (copy from domains)
2. `project_members` table
3. `label_log` add `project_id` column, backfill
4. `label_log` add `prediction_source`, `prediction_confidence`, `is_prediction`
5. `webhook_endpoints` table
6. `webhook_deliveries` table

### Backward compatibility:
- `domain_id` parameter continues to work on all existing endpoints
- `project_id` is the new canonical parameter
- If `project_id` is not provided, falls back to `domain_id`
- New endpoints only accept `project_id`

### DATABASE RULE (standing):
Every prompt tests on BOTH SQLite (Codex default) AND PostgreSQL (local dlj_dev on port 5433).
PostgreSQL test command: `DLJ_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/dlj_dev" python -m pytest <test_file> -q --timeout=30`

---

## 10. Frontend Architecture Notes

### Routing migration

Current: `/#/upload`, `/#/queue`, etc.
New: `/#/projects/{id}/upload`, `/#/projects/{id}/queue`, etc.

Default behavior:
- If user has 1 project → auto-select, redirect to `/#/projects/{id}/upload`
- If user has 0 projects → redirect to `/#/projects/new` (create first project)
- If user has 2+ projects → show `/#/projects` (project list)
- Old routes (`/#/upload`) → redirect to default project

### Project switcher

Dropdown in sidebar header:
```
┌─────────────────────┐
│ ▾ Medical NER       │  ← current project
│   Clinical Notes    │
│   Drug Interactions │
│   + New project     │
└─────────────────────┘
```

### Shared components (from Track 2 — reuse)

- TextViewer, NERViewer, NEREditor, TagSelector, CategorySelector
- ReviewCard, ScoredQueue, Dashboard, AnnotatorProfiles
- Settings (extend with Team, Integrations, Export sections)

---

## 11. Competitive Positioning After P1–P5

| Feature | Label Studio (OSS) | Labelbox | DLJ (after P5) |
|---|---|---|---|
| Project organization | ✅ | ✅ | ✅ |
| Multi-user teams | ✅ | ✅ | ✅ |
| Standard format export | ✅ | ✅ | ✅ |
| REST API | ✅ | ✅ | ✅ |
| Python SDK | ✅ | ✅ | ✅ (single-file) |
| Pre-labeling | ✅ (manual) | ✅ | ✅ + auto-approve |
| Webhooks | ✅ | ✅ | ✅ |
| Quality scoring | Add-on | ✅ | ✅ (core) |
| Compounding intelligence | ❌ | ❌ | ✅ (unique) |
| Conservation safety gate | ❌ | ❌ | ✅ (unique) |
| Auto-approve from learning | ❌ | ❌ | ✅ (unique) |
| Free label health report | ❌ | ❌ | ✅ (unique) |
| Image annotation | ✅ | ✅ | Read-only |
| Video annotation | ✅ | ✅ | ❌ |
| Active learning | ✅ (with model) | ✅ | Planned |
| Self-hosted option | ✅ (OSS) | ❌ | ❌ |
| Price | Free (OSS) / $299/mo | $2,500/mo+ | $99–$849/mo |

### DLJ's pitch after P5

"Label Studio is free but dumb — it doesn't learn. Labelbox learns but costs $2,500/mo.
DLJ learns from every verification, auto-approves predictions as it gets smarter,
and costs $99/mo. After 2 weeks, you need 3x fewer human reviewers."

---

## 12. What's NOT in This Design (Phase 2+)

| Feature | Why deferred |
|---|---|
| **Image bounding box / polygon annotation** | Text is the launch market. Add when first image customer asks. |
| **Video / audio annotation** | Different product entirely. |
| **Active learning (uncertainty sampling)** | Needs model integration. Pre-labeling import covers 80% of the need. |
| **SSO / SAML** | Enterprise gate. Build when first enterprise prospect asks. |
| **Data versioning / snapshots** | Nice-to-have. Git-style versioning is complex. Export + timestamp covers 80%. |
| **Custom annotation templates** | Label Studio's space. DLJ offers fixed, polished templates. |
| **LLM-as-judge integration** | DLJ's scoring engine IS this. Marketing needs to make the connection. |
| **S3/GCS direct integration** | Webhooks + export cover the pipeline need. Direct S3 is polish. |
| **Scheduled exports / cron** | Webhooks trigger on events. Scheduled = polling = wrong pattern. |
| **PyPI package (dlj)** | Single-file client first. Package when >10 users. |

---

## 13. Astra Review Checklist

Astra should verify:
1. **Data model completeness** — are there missing columns or relationships?
2. **Migration safety** — does the domain→project migration preserve all data?
3. **Role enforcement** — are there permission gaps in the matrix?
4. **Export format correctness** — do JSONL/CSV/spaCy formats match what ML pipelines expect?
5. **Pre-labeling auto-approve** — does the conservation gate integrate correctly?
6. **Webhook delivery** — is the retry logic sound? Should we use a queue instead of asyncio tasks?
7. **Frontend routing** — does the project-scoped URL scheme break any existing deep links?
8. **Test coverage** — are there missing edge cases?
9. **Backward compatibility** — does anything break for existing users?
10. **Effort estimates** — are they realistic given the codebase complexity?

---

*DLJ Post-Track 2 Design v1 · November 24, 2026*
*5 features: Projects, Export, API Docs, Pre-labeling, Webhooks*
*~12.5 days, 7–10 Codex prompts*
*After this: DLJ competes with Label Studio and Labelbox on features,*
*and beats them on intelligence (compounding + auto-approve + conservation).*
