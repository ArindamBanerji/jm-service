# DLJ annotation UI design v2

**24 November 2026 · Design for jm-service · Implementation has not started**

Start with a specimen the reviewer can actually read. Let them identify or correct its label, record how they established correctness, and then see how verified decisions change the review queue. Today the first durable labeling operation requires a category and numeric factors. Phase A opens that workflow with a sample and visible text. Phase B introduces correction and first-pass classification. The engine continues to learn from explicit verification.

The v1 input lives in `copilot-sdk/docs/design/dlj_annotation_ui_design_v1.md`. The audit below describes the local jm-service source, not an observation of the running Railway deployment. **Existing** denotes code found here. **NEW** and **extend** denote implementation proposals. Test totals after the baseline are targets.

## §1 Current state

All six v1 screen counts and route patterns check out. Physical lines include imports, blank lines and JSX. Routes below are React paths under HashRouter, so a browser deep link looks like `/#/queue`. The root and wildcard redirect to Upload. Five sidebar links omit the item-specific review screen. FastAPI serves the compiled frontend at the final root mount.

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

All ten v1 workflow gaps persist in the review UI: no bundled interactive demo, content view, bulk decisions, queue download, source text, span display, inline relabel, page navigation, search or Settings. Existing alternatives have narrower scope: report PDF, legacy engine-state JSON, Label Studio integration, a password-style key input and an authenticated Paddle checkout API. Informational escalation is also a workflow gap. No persistent label-detail API backs deep links.

**Build contract.** Declared ranges in frontend/package.json: React and React DOM ^19.3.1, react-router-dom ^7.18.6, Recharts ^3.11.0, PapaParse ^5.7.1, Tailwind and its Vite plugin ^4.3.5, Vite ^8.3.6, React plugin ^6.3.0, TypeScript ~7.0.2. Build runs `tsc && vite build`; ES2023, no emit, unused bindings checked. Vite proxies /v1 to localhost:8000. The client uses fetch, JSON or multipart, a browser-stored key (dev env fallback) and skips the auth header for health reports. Deployment copies frontend/dist. Package scripts cover dev/build/preview.

**Baseline.** 277 pytest cases collect with the three standalone Docker clients excluded. A bare collection exits inside test_jm_docker_live.py after a partial count of 72. See §10 for reproducible commands. This audit measured collection.

## §2 Competitive landscape

| Product | Documented comparison | Implication for DLJ |
|---|---|---|
| Label Studio | Its NER template supports overlapping spans, and annotations can be exported. [NER template](https://labelstud.io/templates/named_entity) · [Export](https://labelstud.io/guide/export) | Start with readable text and explicit offset semantics. Overlap support and template authoring would broaden the editor substantially. |
| Labelbox | Its text annotation import guide defines text entities and classifications. [Text annotations](https://docs.labelbox.com/horizon/developer-guides/import-text-annotations) | Interchange needs both the source string and the label geometry. An approve/reject action alone cannot reconstruct either. |
| Cleanlab Studio | Multi-label curation ranks suspected issues, suggests labels, supports correction and export for image, text and tabular data. [Multi-label workflow](https://help.cleanlab.ai/studio/tutorials/cleanlab-studio-web/multilabel/) | DLJ currently ranks pending decisions by confidence. Its chart measures the fraction of human-verified labels marked correct, not issue-detection precision or a controlled comparison with Cleanlab. |
| Encord | Its document editor supports PDF regions, text attributes and classifications. [Document editor](https://docs.encord.com/platform-documentation/Annotate/annotate-label-editor/annotate-documents) | PDF geometry and plain-text character spans require different representations. |
| DLJ today | Domain-scoped queue, profiles, gate, conditional inversion alert, verify-and-learn path and anonymous report. Native authoring of text, NER, tags, image and video labels is absent. | Differentiate through evidence gathered during review. Show a real verified observation before promising compounding. |

V1’s checkmarks for bulk workflows, plan availability, analytics equivalence, collaboration, media coverage and universal competitive absences lack like-for-like evidence. Treat these as unverified across editions. The sources above support the named capabilities. They do not establish exclusivity of DLJ’s gate, free report or learning loop.

## §3 Annotation architecture

### Existing persistence

SQLAlchemy metadata reports five tables. Every column is listed here. The legacy service separately owns SQLite tenants, domains and decision_log.

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

### CSV contract, from drop to retrieval

1. Upload posts multipart file to anonymous analysis before offering scoring. The service checks .csv, 10 MiB limit, UTF-8/BOM, unique nonempty headers, 200+ rows, unique non-null label IDs, 1–20 categories and at least two finite numeric factor columns in [0,1]. Legacy requires verified_outcome (blank outcomes allowed). The alternate format requires proposed_action, actual_action and verified together, derives correctness from equality for verified rows, and prohibits an actual action on unverified rows. Few verified rows yield a warning. Report analysis runs in memory.
2. On “Start scoring” the browser parses the file again. PapaParse requires label_id, category, at least one data row and two distinct factors. It trims IDs, rejects duplicate IDs, empty factors, nonfinite/out-of-range numbers and malformed headers/rows. If factor_ columns exist it uses those and strips the prefix. Otherwise it uses all columns except label_id, category, annotator_id, proposed_action, actual_action, verified, verified_outcome, action, timestamp and existing_label. Health inference instead considers numeric nonreserved columns. Today text may be discarded or misinterpreted as a factor.
3. Browser sends JSON in independent 100-row batches; single-label ingest also exists. The server validates identifiers (no blank or pipe), factors and domain schema. First ingest creates a scoped domain and engine, subsequent categories can grow to 20. It reserves key capacity, scores, stores factors and recommendation on LabelLog and persists engine state. A failed batch rolls back its transaction; earlier committed batches remain. CSV ground truth is used in the report only. Pending reads return identifiers, factors, recommendation and confidence.
4. **NEW A2** reserves text in *both* parsers, even for numeric-looking text. Preserve decoded source exactly, including whitespace and Unicode; map absent/empty text to NULL. Extend IngestItem in TypeScript and Pydantic, both ingest paths, repository insert and scoped detail DTO. Limit text to 32 KiB UTF-8 per item, return a row-specific validation error, never log raw content. Treat it as inert React text. Direct label detail (§5) removes ReviewCard’s first-page dependency. Keep report-only input ephemeral. Example scoring CSV header: `label_id,category,annotator_id,verified_outcome,factor_model_confidence,factor_item_difficulty,text`. A two-row snippet can exercise the parser but cannot pass anonymous analysis. Add structured spans later via JSON.

### Migration and rollback

Run the existing db/migrate.py before deploying writers. Within engine.begin inspect label_log and add the nullable text column only if missing; create_all handles fresh DBs but cannot alter an existing table. No default or bulk rewrite. Repeat on PostgreSQL and SQLite, including a populated pre-change table. Old integrations keep sending factors only. Legacy and Label Studio rows display “Source text unavailable” while review still works. Roll out readers before writers; rollback reverts app/dist, retains additive columns and existing content. Only a separate, approved migration after backup may remove captured data. Apply the same expand-first order to structured content, verify cleanup with FK enforcement, and retain original rows when rolling back an editor.

## §4 Frontend components

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

### Sample experience (NEW A1)

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

### Settings experience (NEW A4)

* Account reads the authenticated key’s tenant ID/name, tier and created date. Mask a locally entered credential, show “key configured” when appropriate, and offer replace/clear local credential. Never return key_hash, plaintext or a synthetic last-four from the server. Copy can only use the locally held secret after explicit user action; omit copy if unavailable.
* Usage reads labels_today and labels_this_month on the authenticated key. Present zero when period keys differ from current UTC day/month. Show trial duration (created_at + 14 days), 50/day, paid monthly cap (10k/100k/1M) or unlimited Scale/Enterprise. Label these **key** counters. Cumulative rows, verified count and accuracy per domain are available via overview. Historical usage by billing cycle, invoices and a billing portal link require new integrations.
* Upgrade button requests existing checkout-url for a configured tier. Disable repeated clicks, show configuration/upstream failures, redirect to checkout_url, and surface “awaiting confirmation” on return. Reload account on focus or bounded polling. Paddle’s signed subscription.created links the active key by customer ID or tenant fallback and sets tier; updates/cancellation follow their handlers. Signature checking currently depends on PADDLE_WEBHOOK_SECRET. Never grant access from redirect parameters.
* Domain picker needs a tenant-scoped public-ID list. Domain.domain_id can be irreversible and domain_name can equal that same hash. NEW nullable Domain.public_domain_id plus additive migration; populate from public input on ingest/connector configuration before hashing. For old rows, resolve a user-entered name with scoped_domain_id and record it only on a tenant-matched lookup. Show unresolved rows as needing a name; never feed a hash back through scoping. Entering a new ID selects it; first valid labeling ingest creates the domain. Team-wide export and destructive domain deletion are separate future work.
* Settings lives at NEW hash route /settings (public link /#/settings). Fix existing bare /settings links in trial_guard, email templates and other backend messages. Update legal copy about stored content/localStorage before enabling capture; present current data handling accurately.

## §5 Backend endpoints

**Existing route inventory.** Path patterns use the source parameter names. Limits are requests per minute per remote address via SlowAPI. “—” means no endpoint decorator. Quotas, body limits, thread slots and credentials are separate controls. L = legacy SQLite X-Api-Key; T = active hashed X-Api-Key via require_tenant; S = X-LS-Token. Dashboard additionally resolves a tenant-owned domain.

| Method | Existing path | Auth | Limit | Operation |
|---|---|---|---:|---|
| GET | /v1/health | public | — | Check both databases and engine hash |
| POST | /v1/register | public | 10 | Create legacy tenant and key |
| POST | /v1/domains | L | — | Create legacy domain and engine |
| GET | /v1/domains | L | 60 | List legacy domains |
| POST | /v1/domains/{domain_id}/score | L | 30 | Score and log a legacy decision |
| POST | /v1/domains/{domain_id}/learn | L | — | Learn verified result |
| GET | /v1/domains/{domain_id}/diagnostics | L | 60 | Engine diagnostics |
| GET | /v1/domains/{domain_id}/state | L | 60 | Export engine state |
| POST | /v1/admin/api-keys | X-Admin-Key | 10 | Issue hashed DLJ credential, return plaintext once |
| POST | /v1/labels/ingest | T | — | Score and persist one label, quota enforced |
| POST | /v1/labels/ingest/batch | T | — | Score 1–100 labels atomically per request |
| POST | /v1/labels/verify | T | — | Record action and independent known outcome; update engine |
| GET | /v1/labels/{domain_id}/pending | T | 60 | Pending list, category filter and limit, confidence/time/ID order |
| GET | /v1/domains/{domain_id}/autonomy | T | 60 | Category and overall autonomy |
| GET | /v1/dashboard/{domain_id}/overview | T | 60 | Counts, accuracy, category status, inversion, curve |
| GET | /v1/dashboard/{domain_id}/corrections | T | 60 | Recommended vs actual action patterns |
| GET | /v1/dashboard/{domain_id}/annotators | T | 60 | Ranked annotator summaries |
| GET | /v1/dashboard/{domain_id}/factors | T | 60 | Factor gaps and inversion |
| GET | /v1/dashboard/{domain_id}/compounding | T | 60 | Sampled cumulative accuracy and change |
| POST | /v1/label-studio/configure | S+T | — | Store project mapping for tenant |
| POST | /v1/label-studio/setup | S | — | Connector handshake, initialize configured domain |
| POST | /v1/label-studio/predict | S+T | — | Score Label Studio tasks and return predictions |
| POST | /v1/label-studio/webhook | S+T | — | Process annotation events, bind reviewer and learn verified revisions |
| GET | /v1/label-studio/health | public | 60 | Connector health |
| POST | /v1/label-health/analyze | public | — | Ephemeral CSV analysis JSON |
| POST | /v1/label-health/report | public | — | HTML report |
| POST | /v1/label-health/report/pdf | public | — | PDF report |
| GET | /v1/billing/checkout-url | T | — | Create Paddle transaction with authenticated tenant custom_data |
| POST | /v1/billing/webhook | Paddle signature if secret configured | — | Link customer/subscription, update tier/cancellation |
| GET | /terms | public | — | Terms HTML |
| GET | /privacy | public | — | Privacy HTML |
| GET | /attribution | public | — | Attribution HTML |

FastAPI also supplies public GET/HEAD /openapi.json, /docs, /docs/oauth2-redirect and /redoc. The final StaticFiles mount at / serves built assets over GET/HEAD when dist exists. Neither framework surface has an explicit rate decorator. There is no /v1/labeling/score route. Legacy registration does not issue the key required by the review UI.

**Proposed contracts.** All additions below require T and tenant-scoped domain resolution wherever a domain appears. No label-only route can safely identify a row. Register before the static mount.

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

## §6 Implementation phases

| Phase | Deliverable | Acceptance |
|---|---|---|
| A · Foundation | Sample report + quota-aware demo queue, optional text ingest/detail, queue sort/pagination/preview/page CSV, account settings | Anonymous visitor opens the sample report. Authenticated reviewer scores the sample, reads source text, verifies a label, exports a page and sees current key usage. |
| B · Annotation | First-pass text classification and audited relabel, structured content + read-only NER, scoped search, explicit bulk review | A reviewer assigns a class to an unscored text, corrects a prior annotation, inspects spans, filters across pages and records known outcomes once. |
| C · Rich annotation | NER range editing, multi-label tags, batch content import, read-only image display with class selection | Text/spans/tags round-trip. A reviewer can classify a displayed image. |
| D · Polish | Keyboard navigation, per-domain guidelines, inter-annotator agreement, theme toggle, mobile queue | Keyboard and mobile review complete the same task; agreement names its unit and denominator. |

## §7 Scope boundary

The launch covers text classification, flat named entities and multi-label text, followed by image classification. Keep bounding boxes/polygons, video/audio, real-time co-editing, model training/AutoML, active-learning sampling, drag-and-drop template design, assignments and deadlines outside A–D. Use the existing Label Studio connector for teams with those workflows. A3 exports a queue page. Account-wide export/deletion and billing portal management need separate contracts and permissions.

## §8 Effort summary

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

## §9 Risk assessment

Three risks and corresponding controls per Phase A prompt:

| Prompt | First risk → control | Second risk → control | Third risk → control |
|---|---|---|---|
| A1 | A 500-label seed exceeds the trial cap → analyze 500 anonymously, explicitly score only 12 under quota. | Retry/concurrent clicks or a user-owned colliding domain → reserved scope, persistent provenance and atomic idempotent seed. | Sample “history” contaminates learning → fixture outcomes feed only the report; live review begins pending. |
| A2 | Text gets parsed as a factor → reserve it in both parsers; test numeric-looking content and prefixed/unprefixed CSV. | Label IDs collide across tenants or domains → scoped parent lookup and 404 isolation tests. | Oversized/sensitive/markup content → byte cap, no payload logs, escaped rendering, update data-handling copy before enablement. |
| A3 | Local sorting hides high-priority items on later pages → database sort before limit, stable tie-breaker. | Polls race filter changes or removals → reset/clamp offsets, ignore stale responses, label page count accurately. | Spreadsheet formulas or false “all data” export → neutralize dangerous cells, quote via Papa.unparse, name download “Export this page”. |
| A4 | DB key disclosure or old-period usage → minimal DTO, hash-scoped lookup, compare UTC period keys. | Wrong database or double-hashed domain selection → labeling list and lazy verified public-name mapping. | Stale subscription state or broken bare links → server-confirmed tier refresh, bounded retries and hash-route links. |

For B, stale human corrections require version checks, repeat submissions require idempotency, and bulk approval requires known outcomes for every selected item. For C, range offsets and overlap need one shared contract; restrict image origins and validate batch sizes. For D, inter-annotator agreement needs a stable common source-task identity and independently observed labels; missing pairs must remain “insufficient evidence”.

## §10 Execution plan

Run every implementation prompt from **jm-service**. Each block includes its own pre-check, acceptance tests and final session entry. The common gate below is part of every block. Use local test data and stub outbound Paddle requests in automated tests.

### Shared verification commands

PowerShell from jm-service, after each prompt:

~~~powershell
python -m pytest --co -q --ignore=test_jm_docker_live.py --ignore=test_jm_docker_live_v2.py --ignore=test_jm_docker_live_v3.py
python -m pytest -q --timeout=30 --ignore=test_jm_docker_live.py --ignore=test_jm_docker_live_v2.py --ignore=test_jm_docker_live_v3.py
python -m mypy jm_service.py db/models.py --config-file pyproject.toml
npm --prefix frontend run build
~~~

Also run mypy on each changed Python module/test with the same config. Build the assets served from dist and open the built UI in a browser for the prompt-specific checks. The three exclusions are live HTTP scripts that execute on import and interpret pytest arguments as their URL. Treat them as a separate live-service smoke gate. Keep the frozen engine intact and the static mount last.

### DLJ-A1 · Sample Data + Demo Mode

~~~text
/model spark
/reasoning high
Target jm-service. Deliver the sample experience in §4.

STEP -1. Read docs/session_state.md, this design §§3–5, Upload.tsx, HealthReport.tsx, csv.ts, api.ts, label_health/ingest.py, labeling_router.py, auth.py, trial_guard.py, db/repository.py and Dockerfile. Collect the baseline with the shared command. Check the label quota before designing the seed transaction.

Implement the versioned 500-row fixture and static packaging in §4. Use the same asset in the browser and the seed endpoint. Keep text/spans in the fixture even when A2 is absent. Public preview works without any domain or key. Offer the separately labeled 12-row scoring action with key, remaining-capacity failures and a link to the pending queue. Use ordinary scoring for quota, state and policy. Never import sample ground truth as user verification. Return counts on replay. Account for parallel requests and conflicts without charging twice.

Add exactly 5 pytest cases covering (1) fixture dimensions/vocabulary and acceptance by the real report parser, (2) missing credential rejection, (3) successful tenant-isolated 12-row seed with counters and pending results, (4) replay with stable results and counters, (5) insufficient remaining capacity rolls back the whole seed. Exercise simultaneous clicks and reserved-domain collision in acceptance. Expected standalone total 282.

Verify: python -m pytest test_label_health.py test_labeling_router.py -q --timeout=30 (include any new sample test module); run §10 shared commands. Open /#/upload with no key, view the sample report, then use a test labeling key, seed, repeat, and verify the queue and usage. Inspect the fixture inside the built dist.

FINAL STEP. Append DLJ-A1, date, changed files, fixture version, report/seed counts, tests, mypy/build and browser results to docs/session_state.md.
~~~

### DLJ-A2 · Text column and content display

~~~text
/model spark
/reasoning high
Target jm-service. Deliver the source-text round trip in §3 and §4.

STEP -1. Read docs/session_state.md, this design, both CSV parsers, Upload.tsx, ReviewCard.tsx, api.ts, labeling_router.py, db/models.py, db/migrate.py, db/repository.py, label_studio.py and legal_pages.py. Trace a batch through quota reservation and rollback. Collect baseline and inspect the exact pending DTO.

Add nullable LabelLog.text and repeatable migration. Thread optional text through browser parser, both request models and repository transaction. Exclude text from both factor inference paths. Set limits and blank/null semantics from §3. Add the scoped single-item detail route, render NEW TextViewer, and use detail even outside the first 200 pending rows. Keep next-item navigation independent of detail lookup. Disable verification for already reviewed items; refetch on conflict. Provide text_preview in the existing pending DTO as an optional first 80 code points, without sending full text. If A1 is present, attach and backfill only server-owned sample text when seeding again. If it merges later, its seed must use this same optional text contract. Review privacy/terms describing stored text.

Add exactly 8 pytest cases: old-schema repeated migration; legacy ingest without text; single detail round trip with whitespace/Unicode; batch round trip; invalid oversized text with batch rollback; anonymous health ignores numeric-looking text as a factor; tenant/domain detail isolation; deep detail and bounded preview beyond row 200. Test browser parser with prefixed and unprefixed CSV in acceptance. Expected standalone 285, sequential after A1 290.

Verify: python -m pytest test_db.py test_labeling_router.py test_label_health.py test_legal_pages.py -q --timeout=30; run §10 shared commands. In browser upload a valid 200+ row report CSV with quoted multiline text and literal HTML, score it, open the label by ID, verify, and open a legacy row. Inspect that markup appears as text.

FINAL STEP. Append DLJ-A2, date, schema/API deltas, rollback/read behavior, tests, mypy/build and browser results to docs/session_state.md.
~~~

### DLJ-A3 · Queue sorting, pagination and page export

~~~text
/model spark
/reasoning high
Target jm-service. Deliver a usable queue beyond 200 pending labels.

STEP -1. Read docs/session_state.md, this design, ScoredQueue.tsx, AnnotatorProfiles.tsx, HealthReport.tsx, api.ts, labeling_router.py and test_labeling_router.py. Record default sort/filter/list shape, response headers and collection baseline.

Extend pending with offset >= 0, existing 1–200 limit, whitelisted sort keys label_id/category/annotator_id/confidence/recommended_action and asc/desc. Use explicit null ordering and unique ID tie-breaker; preserve confidence/scored_at/id defaults and bare-array response. Count with identical tenant/category/pending filters and expose X-Total-Count (including CORS exposure when cross-origin). Do not infer a total from rows.length. Refresh without jumping to page one, reset on changed filters/sort/domain and clamp if last item disappears. Header click/Enter changes server order. Offer 50/100/200 and previous/next, an optional preview cell, and page CSV with escaped spreadsheet formula prefixes. Render a placeholder if A2 has not landed. Populate filter choices independently of a filtered page, e.g. from existing autonomy categories. Search and bulk decisions are B features.

Add exactly 6 pytest cases: legacy defaults; second page plus total; sorting across page boundaries with ties; invalid sort/order/offset; category-scoped total; tenant isolation and empty/out-of-range page. Expected standalone 283, sequential 296.

Verify: python -m pytest test_labeling_router.py -q --timeout=30; run §10 shared commands. With 201+ labels, sort both directions, change category/domain during refresh, visit last page, export and compare row order/count. Include commas, quotes, line breaks and a formula-looking ID. Once A2 lands, confirm preview length and detail navigation for a later-page row.

FINAL STEP. Append DLJ-A3, date, API defaults, export scope, test count, mypy/build and browser results to docs/session_state.md.
~~~

### DLJ-A4 · Settings and subscription

~~~text
/model spark
/reasoning high
Target jm-service. Deliver Settings as specified in §4.

STEP -1. Read docs/session_state.md, this design, App.tsx, api.ts, domain.tsx, auth.py, billing.py, trial_guard.py, email_service.py, db/models.py, db/repository.py, db/migrate.py and label_studio.py. Inspect how domain IDs are scoped, how keys authenticate and all upgrade links. Collect baseline.

Implement the minimal authenticated summary and public domain list in §5. Query the active key from the request, honor period keys, never return hashes or credentials. Implement public_domain_id mapping and backward-compatible migration from §4. Add sidebar link and hash-routed settings, display key status and usage, handle missing key, unpaid trial, unlimited and cancelled states. Allow public-name entry and domain switching. Use existing Paddle checkout endpoint. Show confirmation pending on return and refresh from the backend. Update settings links and handle a missing checkout URL. Keep transaction creation and webhook signature policy in billing.py.

Add exactly 4 pytest cases: unauthenticated account/domains; minimal tenant-owned summary and correct UTC counters/caps; public-domain list with legacy name resolution, migration repeat and cross-tenant isolation; checkout-to-webhook-to-refreshed-tier integration using mocked Paddle. Expected standalone 281, sequential 300.

Verify: python -m pytest test_billing.py test_deployment.py test_jm_service.py -q --timeout=30; run §10 shared commands. In browser open /#/settings from a pasted upgrade link, change domain, replace/clear local key and verify a checkout error and pending/confirmed return using sandbox or a stub. Record which system was exercised.

FINAL STEP. Append DLJ-A4, date, account fields and exclusions, public-ID migration, billing checks, test count, mypy/build and browser results to docs/session_state.md.
~~~

### Phase B outlines and later work

| Outline | Depends on | Scope and acceptance | New pytest target |
|---|---|---|---:|
| B1 · Text task and revision | A2 | NEW task intake and CategorySelector for first classification. A scoped task ID can be resolved by the proposed item relabel route to create its first scored label. Preserve revisions on later edits. Transactionally score once and verify separately. | 8 |
| B2 · NER read view | A2 | Structured content migration, bounded content POST, detail extension, offset validation and read-only highlights with legend. | 8 |
| B3 · Bulk review | A3 | Select current page/explicit IDs, confirm action and known outcomes, handle stale rows without partial learning. | 7 |
| B4 · Search | A2, A3 | Parameterized scoped search over ID, annotator and text; reset page, filter before sorting/counting and verify query cost. | 5 |

Phase C items only: C1 span editor; C2 tag selection and batch content; C3 image display and classification.
Phase D items only: D1 shortcuts, theme and mobile queue; D2 guidelines and inter-annotator agreement.

### Dependency graph and integration order

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
