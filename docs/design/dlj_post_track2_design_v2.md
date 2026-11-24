# DLJ post-Track 2 implementation design

**Version 2 · 24 November 2026 · Execution specification · Start with prompt 01**

An existing labeling domain becomes a project in place. Its owner can invite another account, a reviewer can correct and export current annotations, and a pipeline can import predictions and receive signed decision events. The owning tenant pays for shared work. Only observed human outcomes train the engine.

Implement sections 1–8 using the ordered prompts in section 9. Appendix A records the disposition of each v1 finding. This specification covers the FastAPI labeling service, React hash application, Railway deployment and Paddle account binding.

**Starting point.** The current checkout includes B3 bulk verification. Prompt 01 can start immediately. Integrate search, rich content editing, guidelines and IAA as their Track 2 changes land. The 30-day estimate covers post-Track 2 implementation and acceptance. Track 2 completion time is separate.

## 1. Identity, access and project lifecycle

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

### Team and billing transitions

1. A newly registered account owns its own projects. The owner's account-level keys retain historical access. A grant to an invited account covers that account's active keys. The invite screen names the recipient email and role, and discloses this scope. A tenant with no attributable owner or ambiguous billing binding can still use its legacy private workflows.
2. Owner/admin submits email and permitted role. Normalize email as in auth.py. Generate 32 random bytes, store SHA-256 digest, expire in 48 hours. Persist pending invite before calling Resend. Deliver the token once via a hash link. Keep it only in memory during that send. On timeout or process interruption the admin can resend. Resend locks and revokes the old invite, issues a fresh token, and sends after commit. Return mail state pending/sent/failed to admins. Limit issue/resend to 10 per actor/project/hour and acceptance attempts to 10 per IP/minute.
3. The browser exchanges the mailbox token using an authenticated account with matching contact email. Retain it in tab session storage only while signup is in progress, erase it and replace the hash after completion. Acceptance rechecks project active status, inviter authority and allowed target role under lock. Atomically consume the token and create or reactivate membership. Prevent self-grants, owner edits and admin escalation. Invalidate pending grants issued by a demoted/revoked inviter. Revocation takes effect on the next authorized request.
4. Bind a single active owner key on the first shared write. For a multi-key tenant, provide a dry-run and apply operator command accepting owner tenant and canonical active key ID. Before applying, lock the tenant binding and affected keys, sum usage for matching UTC periods, retain the oldest applicable trial start and preserve verified subscription terms. Require a unique matching subscription or an operator-confirmed Paddle reconciliation. Refuse an ambiguous mapping and leave that tenant private. Persist the binding atomically. Make reruns return the existing binding without adding usage again. Route key creation, Paddle callbacks, checkout, quota, usage display and cancellation through that binding for shared accounts. A subsequent key rotation must transfer billing state and binding together. Persist trial_started_at on ProjectBillingOwner and consult it for expiry, reminders and account display. Set it to the applicable original UTC trial start at binding; keep ApiKey.created_at as credential creation time.
5. Lock/check project status and active membership for each mutation. Stale UI writes return 409 for a closed project or 404 after access loss. Completion and archival stop edits/imports across project, legacy and connector paths. Stop fan-out on closure and cancel queued deliveries. Owner reopening resumes new work. Account cleanup deletes child delivery, prediction and invite data before parent labels/domains; cover FK-restricting links with an explicit deletion order.


## 2. Persistence and ownership

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

### Export and workflow predicates

Apply owner/project and current-revision predicates first. Use all for every current item, pending for scored work awaiting review (excludes machine-completed), unclassified for unscored work, verified for a human-observed outcome with verified_at, auto_approved for machine-only completion and overridden for human-verified rows with actual_action different from recommended_action. Expose category revision history separately from action overrides. For predictions, human_reviewed counts distinct adjudicated predictions; pending, machine-only and human-reviewed are disjoint. auto_approved_ever is historical and may overlap human-reviewed. Use an explicit source filter and label denominators in the dashboard.

A JSONL record for plain text after human verification follows. The corresponding CSV stores the factors object and both empty arrays in individual cells using standard CSV quoting.

```json
{"label_id":"L001","revision_label_id":"L001","revision_id":"b5131403-3d03-4328-8b18-11a5f468a57b","source_task_id":null,"annotation_id":null,"annotator_id":"ann_1","category":"billing","text":"Refund requested","recommended_action":"approve","actual_action":"approve","verified_outcome":true,"confidence":0.87,"factors":{"agreement":0.85,"clarity":0.92},"scored_at":"2026-11-20T10:30:00Z","verified_at":"2026-11-20T11:00:00Z","revision_at":null,"content_type":null,"spans":[],"tags":[],"image_url":null,"review_state":"verified"}
```

## 3. HTTP surface and legacy adapters

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

### Request and response contracts

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
| POST P/predictions; GET P/predictions/stats | PredictionImport below. Optional exact source/version filter for stats | 200 {imported,scored,auto_approved,pending_review}. Stats return the counters and rates defined in §6 |
| POST P/webhooks; GET/PATCH/DELETE P/webhooks/{webhook_id} | Create {"url":"https://receiver.example.org/dlj","events":["label.verified"]}. PATCH accepts url, events and active | 201 {id,url,events,active,secret}; detail/patch returns public fields and last_delivery_at, last_status; delete 204 |
| POST P/webhooks/{webhook_id}/rotate-secret; POST .../test; GET .../deliveries | Rotation and test have empty body. Delivery list uses limit and offset | 200 {secret,version} once; 202 {event_id,delivery_id}; 200 {items,total}. Each item has event_id,state,attempts,next_attempt_at,last_status and bounded attempt history |

A Project contains id, public_domain_id (nullable), name, description, status, schema, role, member_count, label_count, settings_version and automation settings. Count current labels and active people including the owner. Add domains.settings_version INTEGER NOT NULL DEFAULT 1. Increment on settings changes using a conditional UPDATE. Return ETag on detail and PATCH; require If-Match for settings updates (428 missing, 412 stale). Restrict display/schema edits to admin or owner and lifecycle changes to owner. Keep project-level defaults in a dedicated settings field if Track 2 already has one. Use a single writable source for guidelines and vocabulary.

**CreateProject**

```json
{"name":"Support triage","public_domain_id":"support-2026","description":"Review refund requests","schema":{"categories":["refund","account"],"factors":["clarity","agreement"],"actions":["approve","reject"]}}
```

**Batch**

```json
{"items":[{"label_id":"L1","category":"refund","annotator_id":"ann-1","text":"Refund requested","factors":{"clarity":0.92,"agreement":0.85}}]}
```

**PredictionImport**

```json
{"source":"triage","version":"2026-11","predictions":[{"label_id":"L2","text":"Please refund this","predicted_category":"refund","model_confidence":0.97,"factors":{"clarity":0.90,"agreement":0.86}}]}
```

Each batch/prediction item can include optional content using the existing LabelContentRequest (content_type, spans, tags, image_url). Validate offsets, substring, uniqueness and content type before commit. The normalized original prediction includes that content. Set the request limit to 4 MiB for either endpoint and reject oversize payloads with 413.

Require Idempotency-Key (1–128 printable characters) on these two new import operations. Hash the validated body serialized as canonical UTF-8 JSON with sorted keys and stable array order. Insert the unique request record within the write transaction. A competing request waits for the first commit or retries after its rollback. Read the committed result on identical replay, return 409 on digest mismatch, and prune completed records after 24 hours. Reauthorize before replay. Use 422 with item_index for invalid items, 409 for a stored label ID conflict, 402 for expired trials and 429 for caps or throttling. Preserve the existing legacy ingest error mapping. Expose X-Volume-Warning and Content-Disposition via CORS alongside X-Total-Count.

## 4. Project export

Export one **current revision** per logical item, scoped by owner tenant and internal domain. Filter superseded_by IS NULL and left join label_content on label_log_id = label_log.id. Use the following dictionary for JSONL v1 and CSV v1. The CSV header uses the same field names. Nullable CSV scalars are empty, and structured values use JSON inside quoted CSV cells.

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

## 5. Frontend and developer interface

Keep HashRouter. Add /projects, /projects/new and /projects/:projectId with nested upload, queue, review/:labelId, dashboard, annotators and settings. Mount one authorized project provider there and reuse screens through a scope-aware API adapter. Make links and post-action navigation relative to that scope, encoding IDs once. Keep /signup, /health, /docs, /invite/:token and account /settings global. Preserve every old hash entry including review ID, query and intended destination. Retain the legacy upload flow for anonymous/sample or new-domain work. For authenticated aliases match the saved public name to an accessible project first. If ambiguous, use a chooser with a return target. Never open a same-named label from another project. A missing or revoked explicit UUID gets a scoped error. On key change clear selection/cached data. Cancel in-flight requests or discard stale responses, reset pagination on switch. Keep project settings separate from account checkout.

`frontend/src/api.ts` prefixes /v1, reads X-Api-Key and generally decodes JSON with exceptions for PDF/HTML. Add an authenticated download method with blob/stream handling, preserve error decoding and pending X-Total-Count. Avoid placing keys in download URLs. Keep page-CSV and whole-project export clearly labeled. Use existing NERViewer, CategorySelector, Settings and ReviewCard. Bind later editors only once their Track 2 contracts exist.

**Guide and downloadable client.** Serve /#/docs for humans, /docs for Swagger, /openapi.json for tooling and /dlj_client.py from the static build. Include the client as a source-controlled frontend public asset. Its constructor takes base_url and api_key. Expose create_project, upload, verify, import_predictions and export. POST upload scores within the call. Chunk uploads at 100 items, use one replay key per chunk, and return which chunks committed if a later chunk fails. Stream export bytes to a temporary file and rename after success. Apply request timeouts, surface HTTP status and structured detail, and retry imports only with the same payload and key. Publish a runnable quickstart and test it through actual HTTP with a fresh trial account.

**Screen ownership.** Project List shows status, effective role, current label count and active member count. The authenticated home opens its sole accessible project or the chooser when several exist; zero projects offers Create and the legacy upload flow. Project Settings owns members, guidelines, automation, integrations and export. Global Settings owns API keys, account usage and checkout. Queue keeps separate page-CSV and project-export actions. Show read-only reasons on closed projects. Disable actions the caller cannot perform. Server authorization applies independently.


## 6. Prediction review and quota accounting

1. Validate the project, role (reviewer or higher), active status, replay key, unique label IDs, schema, content and confidence. Insert immutable input and score each item through the same service as labeling_router._ingest. Reserve owner capacity in the same transaction as label creation. Persist DLJ confidence, recommended action, tier and gate result as returned at scoring time. Preserve the model's confidence independently. A failed item rolls back all item scores, engine changes, quota reservations and outbox records.
2. Automation defaults off. A machine approval requires project opt-in, model confidence ≥ floor (default .95, configurable .80–.99), an approve recommendation, an unpaused engine, autonomous tier, passing conservation checks and the existing named-annotator eligibility test. Reuse evaluate_domain and _ingest's eligibility result. Autonomous normally requires at least 200 human outcomes at the default .85 accuracy threshold; rolling demotion can override it. Named annotators require 30 verified at ≥.80 accuracy in scope. Attach a stable reason such as disabled, below_model_floor, policy_requires_review, action_requires_review or approved to each decision.
3. Add Prediction.state with checked values pending, auto_approved, human_reviewed and a monotonically increasing decision_version. A machine decision sets state and machine_approved_at only. It neither sets verified_at nor calls verify_and_learn. Queue predicates exclude machine-completed items from ordinary pending; machine audit and prediction-only filters include them explicitly. Preserve the original snapshot on all revision paths. Clarify to reviewers that accepting an annotation and observing whether the DLJ action was correct are separate inputs.
4. Implement POST P/predictions/{prediction_id}/reopen for reviewers. Require expected decision_version, return 200 with incremented version and pending state after a machine approval; return 409 for other states or stale version. Preserve machine_approved_at for history. POST P/predictions/{prediction_id}/review takes expected_revision_id, decision_version, assessment (correct/incorrect/unknown), actual_action, verified_outcome and optional corrected category/content and reason. Lock the prediction and current revision, apply any edits through shared revision services, verify the final row once and update provenance in the same transaction. A human correction through the annotation UI alone updates the current pointer and returns to pending. Competing review/revision loses with 409. Store the actor's key UUID, human_reviewed_at and explicit assessment of the original output. Return prediction_id, state, revision_id, decision_version. Project and legacy human verify paths that lack a model assessment record unknown; bulk human approval alone cannot certify predicted NER spans for DocBin. Persist a human_spans_reviewed boolean default false, set only on explicit span adjudication.
5. Charge one unit on each newly scored import item using the owner binding or current legacy billing principal. Single human verification, dedicated prediction adjudication, reopening and identical import replays incur zero additional scoring units. **B3 bulk review has its own existing quota behavior:** both legacy and project bulk adapters reserve one unit per processed bulk decision, skip already-verified/ineligible rows, and return partial success at the cap. Keep this separate from atomic import. At 49/50, a two-item import commits zero; two eligible B3 bulk decisions process one and report the skipped one. Do not route prediction adjudication through bulk.

**Metrics and UI.** GET stats returns total_imported, pending, machine_only, human_reviewed, auto_approved_ever, auto_approve_rate, assessed_count, model_accuracy, avg_model_confidence and avg_dlj_confidence. Count each prediction once for the selected project/source/version. pending + machine_only + human_reviewed = total_imported. auto_approve_rate uses auto_approved_ever / total_imported. model_accuracy uses correct / (correct + incorrect) among human assessments. Return null for a zero denominator. DLJ action accuracy remains the existing human-outcome measure. Show both denominators. Add prediction ID, state, original model output, revision and decision version to authorized item detail. Queue adds origin=all/human/prediction, optional prediction_state, and prediction_confidence sorting with nulls last and row-ID tiebreaker. ReviewCard offers Accept, Correct and Reopen according to state/role. Keyboard actions must yield focus to the active Track 2 editor.

## 7. Project webhooks

Store events and deliveries in the labeling database. In the transaction that changes the label, enqueue one immutable event and one delivery per active subscribed endpoint. Use the human verification transition for label.verified, the new prediction decision for prediction.auto_approved, and a fresh request UUID for webhook.test. Emit after a successful row transition from every entry point including bulk and connector verification. A replay or rolled-back change yields no extra event. Schema additions include webhook_attempts(delivery_id, attempt_no, started_at, finished_at, outcome, http_status) with a composite primary key. Persist the event's exact UTF-8 body bytes or its canonical JSON string once at creation.

| Event | Transition key | data fields |
|---|---|---|
| label.verified | Current revision UUID + first human verification | label_id, revision_id, actual_action, verified_outcome, confidence |
| prediction.auto_approved | Prediction UUID + decision_version | prediction_id, label_id, revision_id, model_confidence, dlj_confidence, tier |
| webhook.test | Unique test request ID | test=true |

Envelope fields are id, schema_version=1, type, project_id, created_at and data. Deliver POST application/json. Set X-DLJ-Event-ID to id, X-DLJ-Timestamp to integer UTC Unix seconds for this attempt and X-DLJ-Signature to v1=<lowercase hex>. Sign the ASCII timestamp, a literal period and the exact raw body bytes with HMAC-SHA256. Generate a random 32-byte secret, return its base64url encoding once and specify that verifiers decode it before HMAC. The guide's receiver checks a ±300 second window, compares signatures in constant time and durably deduplicates event IDs. Duplicate deliveries are possible if the receiver commits before the sender records success.

Extend jm_service.lifespan to supervise a separate dispatcher alongside the hourly scheduler. Poll every two seconds, claim up to four due rows, allow four concurrent sends and at most one in flight per endpoint. PostgreSQL uses row locks with SKIP LOCKED plus an endpoint lease; local SQLite uses one dispatcher with conditional state updates. Commit claims and attempt numbers before I/O. Use 30-second leases, 10-second total timeout and a fenced completion UPDATE matching the current lease token and destination version. Reclaim an expired attempt as uncertain and consume its retry budget. Four sends maximum, immediate then 10/60/300 seconds with bounded jitter. Retry timeouts, 408, 429 and 5xx. Treat 2xx as delivered and other statuses as terminal. Backoff and leases survive restarts. Stop claiming on shutdown, cancel/await sends within the shutdown deadline and let unacknowledged leases expire. Record dead outcomes after the fourth attempt. Delivery order is unspecified.

Allow at most five endpoints per project and ten test sends per endpoint per hour. Enforce public HTTPS destinations, valid TLS, no redirects and an egress policy bound to the actual destination address. Reject embedded credentials and unsupported URL schemes. Encrypt signing material with authenticated encryption and a versioned deployment secret. Disable sends if decryption or destination validation fails. On edit of URL, disable, rotation or closure, increment destination version and cancel pending/leased deliveries for the old version; a send already accepted remotely cannot be recalled. Keep terminal event/delivery/attempt metadata for 30 days and retain pending work until terminal. Purge event payloads once every delivery has expired. Dashboard shows delivery state and age, and admins can inspect attempt metadata. Exclude raw server response bodies, tokens and annotation text from logs.

The launch subscribable events are the two persisted business transitions above. Reject unsupported names with 422. Batch completion needs durable batch membership, export-ready needs async artifact storage and expiry, and conservation changes need persisted per-category transitions. Schedule those event types only with the corresponding producers.

## 8. Database upgrade, rollout and recovery

| Stage | Action | Evidence required to advance |
|---|---|---|
| Inventory | Capture domain UUIDs, owner/internal/public mappings, configs and engine state hashes; label/revision/content counts by tenant; API-key eligibility and current billing periods. Use the SQLAlchemy store. The JM_DB_PATH SQLite decision service has its own domains table | Baseline includes same-name tenants, null public names, empty legacy tenant, two-key accounts, superseded and unscored rows |
| Expand | Serialize db/migrate.py on Railway using a single release runner or transaction-scoped PostgreSQL migration lock. Complete historical migrations first. Inspect child tables before any SQLite rebuild. For a populated legacy layout with children, back up rows to staging tables, rebuild parent and children with original UUIDs, recreate indexes and FK constraints, restore rows, validate and commit as one migration | Run twice on fresh and upgraded SQLite and PostgreSQL. Verify FK integrity, exact old counts/IDs/config/state/history and bulk verification_reason. Exercise interruption/retry. Test restore before deployment |
| Bind | Deploy compatible readers and writers with sharing, prediction automation and delivery disabled. Enable project reads for an internal tenant. Use the tenant reconciliation procedure in §1 before sharing | Old and new paths return the same current revision and owner usage. One shared score charges the owning tenant. Existing public-name recovery and Paddle checkout still work |
| Canary | Enable project writes/team access, then export/batch/guide, then prediction review. Enable automation per project only after an owner/admin opts in. Enable webhook dispatch last with a real staging receiver | No unauthorized cross-account access; current revision survives edit/export; machine evidence stays out of human metrics; process restart recovers durable deliveries. Verify health, DB pool usage, export RSS and retry lag |
| Operate / roll back | Disable failing feature at its writer and UI. Pause automation or the webhook dispatcher independently. Preserve queued deliveries and committed history. Roll back only to a build that understands project status, billing binding and machine disposition once live shared writes have begun. Otherwise stop writes and use the tested restore/reconciliation procedure | Compare post-rollback sample exports and quota totals. Document the last restorable point and replay/reconcile post-backup writes before reopening |

Use deployment configuration for the invitation provider, public app origin, webhook key ring/active key version and service feature switches. Store secrets in Railway environment configuration. Record structured project ID, event ID, retry outcome and oldest due age. Alert if oldest due age exceeds 60 seconds for five minutes or dead deliveries exceed 5% over 15 minutes with at least 20 attempts. Move the same dispatcher to a dedicated worker when sustained delivery lag or API latency exceeds the deployment budget. Keep one enqueuing transaction regardless of worker placement.

**Test harness.** Extend test_labeling_router.open_client and related fixtures with multiple authenticated tenants, distinct browser contexts and transactionally isolated schemas. Enable SQLite foreign keys on every test engine. Use DATABASE_URL for the common PostgreSQL lane; set DLJ_DATABASE_URL consistently for test_bulk_review.py if present. Assert the actual dialect. Include migration fixtures older than create_all, two independent sessions for competing approvals/edits and worker leases, controlled time, captured mail and an injected HTTP transport. Start the built frontend and isolated backend on port 8080 for Playwright. Compare streamed downloads with decoded records. Target 60–85 backend cases and 12–16 browser journeys; prioritize invariant coverage over case counts.

## Delivery estimate

| Work | v1 days | Revised days | Cost driver |
|---|---:|---:|---|
| Projects and members, including baseline | 4 | 11 | Account scope, old/new route parity, quotas, invites and UI |
| Export | 2 | 3 | Revision-aware snapshot, streaming and DocBin QA |
| API/batch and guide | 2 | 4 | Typed content, downloadable client and executable examples |
| Predictions | 3 | 5 | Provenance, quota atomicity and human-only evidence |
| Webhooks | 1.5 | 6 | Leases, egress controls, retry, deployment and integrations UI |
| Release rehearsal | — | 1 | Dual-DB migration, compatibility and staging recovery |
| **Total** | **12.5** | **30** | Largest uncertainty is reconciling legacy multi-key billing |

## 9. Ordered implementation prompts and release gates

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

### Implementation handoff

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

## Appendix A. Traceability to the v1 Astra review

Verdicts describe the reviewed v1. Sections 1–9 contain the replacement design. V1 §13 lists ten items. Items 11–13 cover additional requests from the review brief.

| # | Finding against v1 | Implemented design decision |
|---|---|---|
| 1 · BLOCKER | db/models.py has UUID primary keys and a nonunique ApiKey.tenant_id. The proposed tenant FK cannot be enforced | Use Domain as project, proper UUID FKs and explicit billing binding (§§1–2) |
| 2 · BLOCKER | Domain.id cannot backfill label_log.domain_id. Old SQLite rebuild can drop child data | Preserve internal keys and rehearse additive migration (§8) |
| 3 · BLOCKER | require_tenant would give an invitee with an owner credential tenant-wide access | Authorize the actor, project role and billing principal independently (§1) |
| 4 · ISSUE | LabelLog has no stored historical tier or created_at. Structured content belongs to a revision | Export the joined current revision and real timestamps (§§2, 4) |
| 5 · BLOCKER | _ingest reports advisory autonomy. Treating approval as verification feeds the decision back into training | Persist machine disposition and human evidence separately (§6) |
| 6 · ISSUE | Scheduler sleeps hourly. Request tasks lose delayed deliveries on restart | Commit events and delivery rows with the mutation; use leased workers (§7) |
| 7 · ISSUE | Flat NavLinks, rgi-domain and the catch-all would lose the selected project | Nested HashRouter scope, explicit aliases and saved-target handling (§5) |
| 8 · ISSUE | create_all and empty-tenant fixtures miss upgrades and cross-account cases | Old-schema fixtures, distinct actors, two database lanes and browser journeys (§§8–9) |
| 9 · BLOCKER | Hash/public name/UUID fallback can resolve the wrong engine | Each namespace has one resolver and both call the same data services (§§1, 3) |
| 10 · ISSUE | 12.5 days omits access, billing reconciliation, export memory and retry recovery | 30 engineering days, sequenced and gated (§9) |
| 11 · ISSUE | Browser CSV already calls JSON batch ingest; old label detail catches dynamic path segments | Version project DTOs under a new prefix and share the scorer (§3) |
| 12 · PASS | FastAPI reference and hash guide coexist | Publish a tested client and quickstart alongside OpenAPI (§5) |
| 13 · ISSUE | Member cleanup, secret rotation, rollout and operational signals were unspecified | Specify lifecycles, retention, canary and rollback (§§1, 7–8) |


### Baseline evidence

On 24 November, test_content.py, test_tasks.py, test_queue.py and test_labeling_router.py passed **56/56 on SQLite and 56/56 on PostgreSQL** on port 5433. These runs establish the existing labeling baseline. The implementation-design update also exercised all eight test_bulk_review.py cases on each database. The requested test_jm_docker_live_v3.py found no listener on its default localhost:8000 (0/14). Against an isolated local Uvicorn instance backed by temporary SQLite stores it passed 12/14. The script expects the old health response (status=ok and a service field), and its compounding loop received a response without decision_id. That loop did not record the response status, so its failure cause remains unconfirmed. The script exercises the original JM API. No Railway deployment or new feature was exercised.

