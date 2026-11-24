# DLJ backend consistency sweep 1

## Summary (top 5 findings)

1. A missing Paddle webhook secret disables signature enforcement even in live mode. Subscription events can change entitlements and start the cancellation cleanup clock.
2. A scored relabel can introduce a category absent from the scorer. The correction commits successfully, then individual or bulk verification can fail during learning.
3. Upgraded PostgreSQL databases can acquire timezone-naive revision and billing columns where the ORM writes aware timestamps. Fresh-install tests exercise a different schema.
4. SQLite's label table rebuild can cascade-delete existing structured content on a mixed-version database. A second migration can succeed after the loss.
5. Billing identifies a tenant at checkout but upgrades one API key. In a tenant with multiple active keys, the paying key can retain its trial cap.

Reviewed the working tree on 2026-11-24. The 46 application route registrations include 27 in the five named audit modules, both detail aliases, and all other explicitly mounted application handlers. Six SQLAlchemy models and three additional legacy SQLite tables were examined. Framework documentation and the static mount are listed separately. The route inventory uses parsed decorators, full function bodies and dependency aliases. The suggested regex misses signup and autonomy routers and can attribute a neighboring handler’s limiter to the wrong route.

Evidence is source-level unless marked otherwise. The search expression was also compiled for both SQL dialects. The review did not exercise a deployed system, inspect production settings, alter a database, or rerun historical test suites. Session history establishes feature intent and earlier test coverage. Findings describe this snapshot. Historical attribution to a particular prompt requires a version comparison.

**Attribution.** The revision/centroid, structured-content continuity, sample counts, frontend detail race, and fresh-versus-upgraded schema findings cross the feature boundaries under review. The legacy store, Paddle integration and anonymous-report worker pool also contribute current risks. Their presence in this audit does not establish when they were introduced.

## Auth Matrix

“Tenant” means active hashed X-Api-Key via `require_tenant` (auth.py:81–98). Legacy keys use a separate SQLite lookup. “–” means no endpoint decorator. The shared SlowAPI limiter uses remote address, with no configured default limit in rate_limit.py:6. Quotas and worker slots are separate controls.

| Endpoint | Auth? | Domain check? | Rate limit | Verdict and location |
|---|---|---|---|---|
| GET `/v1/domains/{domain_id}/guidelines` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:52 |
| PUT `/v1/domains/{domain_id}/guidelines` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:58 |
| POST `/v1/labels/ingest` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:377 |
| POST `/v1/labels/verify` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:391 |
| POST `/v1/labels/{domain_id}/bulk-verify` | Tenant | Scoped domain + tenant on row | 10/minute | Scoped · labeling_router.py:428 |
| POST `/v1/labels/ingest/batch` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:477 |
| POST `/v1/labels/{domain_id}/sample` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:495 |
| POST `/v1/labels/{domain_id}/tasks` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:539 |
| POST `/v1/labels/{domain_id}/items/{label_id}/relabel` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:576 |
| GET `/v1/labels/{domain_id}/pending` | Tenant | Scoped domain + tenant on row | 60/minute | Scoped · labeling_router.py:653 |
| POST `/v1/labels/{domain_id}/items/{label_id}/content` | Tenant | Scoped domain + tenant on row | – | Scoped · labeling_router.py:714 |
| GET `/v1/labels/{domain_id}/items/{label_id}` | Tenant | Scoped domain + tenant on row | 60/minute | Scoped · labeling_router.py:757 |
| GET `/v1/labels/{domain_id}/{label_id}` | Tenant | Scoped domain + tenant on row | 60/minute | Scoped · labeling_router.py:758 |
| GET `/v1/domains/{domain_id}/autonomy` | Tenant | Scoped domain + tenant on row | 60/minute | Scoped · labeling_router.py:783 |
| POST `/v1/auth/register` | Public | No domain | 5/minute | Public signup · auth.py:47 |
| POST `/v1/admin/api-keys` | X-Admin-Key | No domain | 10/minute | Privileged issuance · auth.py:106 |
| GET `/v1/billing/checkout-url` | Tenant | Authenticated tenant in transaction | – | Key selection gap downstream · billing.py:54 |
| POST `/v1/billing/webhook` | Conditional signature | Customer/subscription or checkout tenant | – | P1, conditional fail-open · billing.py:86 |
| GET `/v1/dashboard/{domain_id}/iaa` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:150 |
| GET `/v1/dashboard/{domain_id}/overview` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:211 |
| GET `/v1/dashboard/{domain_id}/corrections` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:234 |
| GET `/v1/dashboard/{domain_id}/annotators` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:258 |
| GET `/v1/dashboard/{domain_id}/factors` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:296 |
| GET `/v1/dashboard/{domain_id}/compounding` | Tenant | DashboardDomain → require_domain + tenant filter | 60/minute | Scoped · dashboard_router.py:320 |
| GET `/v1/account` | Tenant | Active key hash + tenant | – | Scoped · account.py:26 |
| GET `/v1/account/domains` | Tenant | Tenant-owned rows | – | Scoped · account.py:54 |
| POST `/v1/account/domains/resolve` | Tenant | Scoped hash + tenant | – | Scoped · account.py:73 |
| GET `/v1/health` | Public | No domain | – | Intentional · jm_service.py:396 |
| POST `/v1/register` | Public | No domain | 10/minute | Intentional · jm_service.py:420 |
| POST `/v1/domains` | Legacy X-Api-Key | Assign authenticated owner | – | Separate legacy store · jm_service.py:434 |
| GET `/v1/domains` | Legacy X-Api-Key | Owner filter | 60/minute | Separate legacy store · jm_service.py:476 |
| POST `/v1/domains/{domain_id}/score` | Legacy X-Api-Key | load_engine by owner | 30/minute | Separate legacy store · jm_service.py:499 |
| POST `/v1/domains/{domain_id}/learn` | Legacy X-Api-Key | load_engine by owner | – | Separate legacy store · jm_service.py:547 |
| GET `/v1/domains/{domain_id}/diagnostics` | Legacy X-Api-Key | load_engine by owner | 60/minute | Separate legacy store · jm_service.py:601 |
| GET `/v1/domains/{domain_id}/state` | Legacy X-Api-Key | load_engine by owner | 60/minute | Separate legacy store · jm_service.py:621 |
| POST `/v1/label-health/analyze` | Public | Uploaded CSV only | – | Intentional anonymous health funnel · label_health/api.py:71 |
| POST `/v1/label-health/report` | Public | Uploaded CSV only | – | Intentional anonymous health funnel · label_health/api.py:76 |
| POST `/v1/label-health/report/pdf` | Public | Uploaded CSV only | – | Intentional anonymous health funnel · label_health/api.py:81 |
| POST `/v1/label-studio/configure` | X-LS-Token + Tenant | Config keyed by tenant/project | – | Connector · label_studio.py:153 |
| POST `/v1/label-studio/setup` | X-LS-Token | Configured tenant | – | Connector · label_studio.py:168 |
| POST `/v1/label-studio/predict` | X-LS-Token + Tenant | Bound config + tenant | – | Connector · label_studio.py:178 |
| POST `/v1/label-studio/webhook` | X-LS-Token + Tenant | Bound config + tenant | – | Connector · label_studio.py:229 |
| GET `/v1/label-studio/health` | Public | No domain | 60/minute | Connector · label_studio.py:303 |
| GET `/terms` | Public | No data | – | Intentional · legal_pages.py:128 |
| GET `/privacy` | Public | No data | – | Intentional · legal_pages.py:133 |
| GET `/attribution` | Public | No data | – | Intentional · legal_pages.py:138 |

FastAPI's /openapi.json, /docs, /docs/oauth2-redirect and /redoc are public documentation. The final conditional static mount at jm_service.py:642 serves the UI and public sample assets. If “health” in A2 means readiness probes only, the three report POSTs are **P1 allowlist deviations** under that narrower policy (one policy decision, separately tracked below). The three anonymous health routes are the explicitly designed free funnel, including report downloads. Their only data input is the caller's file. Paddle is a provider callback requiring equivalent authentication. The connector setup route authenticates the service token and takes the tenant from server-side configuration, unlike a user label read.

**Cross-tenant trace.** Auth writes the verified tenant and key digest to the request session. Pending hashes the public name with that tenant, verifies the domain through repository.get_domain, then ANDs tenant, domain, current, scored and unverified predicates with the entire search OR. Count and rows use the same list. Bulk locks the IDs under both tenant and domain, compares the returned set size with the validated unique request, and rejects the whole set before learning if any are missing. Relabel and detail follow successor IDs under both predicates at every hop. Content is fetched by the already-scoped parent UUID. Dashboard requires the scoped domain and filters metrics by tenant. No cross-tenant label read emerged on these paths. The legacy state export first loads a globally unique legacy domain by domain ID **and** legacy tenant key. The queue CSV is generated from the authenticated pending page in the browser. Neither export reads structured label content.

## labeling_router.py Consistency Analysis

| Handler(s) | Success / validation / failure behavior |
|---|---|
| GET/PUT guidelines | Typed nullable payload, 200, 10 KiB UTF-8 bound, missing domain 404. |
| Ingest | Typed score, 200 even when creating rows. Empty identifiers and factor problems 422. Unique/optimistic conflicts translated to 409. |
| Ingest batch | Typed envelope, 200, 1–100 items. A failing item rolls back the transaction. 402/429 preserved, several other failures wrapped as indexed 422. |
| Verify | Typed result, 200. Missing 404, unscored/superseded/reviewed or optimistic conflict 409, unknown action 422. |
| Bulk verify | Dict, 200 even for zero processed. Empty/duplicate/>200 IDs or invalid action 422. Unknown ID 404 before writes. Only quota-exhaustion and skip conditions are partial successes. Other exceptions roll back prior iterations. |
| Sample | Dict, 200. Fixed domain 404 otherwise, marker conflict 409, unavailable fixture 503. Quota for newly inserted items. |
| Tasks | Dict, 201 for scored and unscored. Empty/oversized source 422. Duplicate ID 409 normally. New domain creation races have different exception coverage. |
| Relabel | Dict, 200 for new revision. Missing 404, stale token 409, incompatible/invalid content 422. Category and token required even for content-only updates. See below. |
| Attach content | Dict, 201. Missing parent 404, existing content 409. Vocabulary, offsets, type and HTTPS URL checks 422. |
| Pending | Bare list of dicts, 200 including empty or out-of-range pages for existing domains. Missing domain 404. Invalid offset/limit/order/sort/overlong search 422. |
| Detail (two paths) | Dict, 200 including reviewed/unscored. Missing 404, broken successor link 409. Returns latest revision. |
| Autonomy | Dict, 200 for owned domain, missing 404. Domain categories and evaluation supply tier summary. |

**Search.** Contains passes the search value as a bound parameter and autoescapes SQL LIKE wildcards. Compilation with the benign term `demo_label` yielded SQLite `?` and PostgreSQL `%(lower_1)s`, each with a separate bound value `demo/_label` and `ESCAPE '/'`. Sort identifiers come from a Literal whitelist. Empty/blank search contributes no predicate. SQLite's built-in lower is limited for non-ASCII text.

**Relabel branches.** Category + spans + tags returns 422 before writing, including when both arrays are empty. A category plus either one array is valid for the compatible content type. No category/token yields request validation 422. Unchanged values **with a current token** still append an audited revision. A stale token yields 409, including on retry after an unseen successful response. Plain text is represented as absent LabelContent. An explicit spans array creates text_ner on the successor and requires stored source text. Tags create text_multilabel, including an empty array. Existing NER rejects tags and existing multilabel rejects spans. Category-only changes copy content. Actor is the tenant identifier, time is UTC, and prior revision UUID and successor public label ID are recorded. A revision is an audit row. Dashboard “corrections” counts verified action overrides, so it is not a list of those audit events.

## Database Model Audit

| Table (db/models.py) | Identity, constraints, nullability and ownership |
|---|---|
| domains:15 | UUID PK, globally unique internal domain ID. Optional public name/guidelines. Tenant string, config and name required. No tenant table FK. |
| engines:29 | Domain FK. Optional annotator, unique domain/annotator and partial unique project engine for NULL annotator. Required state and optimistic version. |
| label_log:47 | Domain FK, unique domain/label ID. Text, annotator, category, confidence, actions, outcome, score/verify times and revision metadata nullable. Required label ID, tenant, factors. Revision links are strings without FKs. |
| label_content:78 | Unique required label_log UUID FK with ON DELETE CASCADE. Type and arrays required, HTTPS URL nullable. Type, array shape and URL policy enforced in handlers. |
| annotators:92 | Domain FK and unique domain/annotator. Activity time nullable. |
| api_keys:104 | Unique digest, tenant is nonunique. Nullable contact/provider IDs, cancellation and notification times. Partial case-insensitive unique contact index. Required period keys/counters. No unique subscription ID. |

Typed Mapped declarations infer NOT NULL for nonoptional fields. Optional columns are explicitly nullable. SQLite enables foreign keys on the production async engine at db/connection.py:42–51, PostgreSQL enforces its declared FKs. The domain FK checks the domain ID only, so child tenant consistency relies on writer code. Revision links rely on application integrity, and _current_label has no cycle bound. Structured content is solely in label_content.spans_json/tags_json/image_url. LabelLog stores text and revision pointers. Pending serializes an 80-code-point preview and factors. Detail joins content by current UUID. Neither the page export nor the legacy engine snapshot exports spans. The extra legacy tenants/domains/decision_log DDL lives in jm_service.py:59–98 in a different database. Its sqlite3 connection at :101 does not enable PRAGMA foreign_keys, so legacy FK enforcement depends on SQLite defaults/build.

| Migration step (db/migrate.py) | Repeat and dialect analysis |
|---|---|
| 19–42, 43–49 | Inspect existing tables/column names before tenant, public ID, guidelines and label metadata additions. Sequential second run skips additions. Old rows get empty tenant and NULL public name. No automatic attribution to an existing tenant. |
| 50–82 | PostgreSQL DROP NOT NULL is repeatable, but acquires DDL locks each run. SQLite rebuild guarded by reflected nullability. Recreates listed indexes then tenant index IF NOT EXISTS. Mixed-schema child-table hazard below. |
| 83–109 | API key additions guarded by reflected names. PostgreSQL renames legacy provider fields when only old names exist. SQLite adds new names without copying old values. Both-names case leaves old values unmerged. |
| 110–112 | Partial unique lower(email) index is valid on both supported dialects and repeatable once built. Existing duplicate data can prevent the **first** upgrade. |
| 113–116 | create_all creates missing tables, then LabelContent.create(checkfirst=True) is redundant but sequentially safe. Neither reconciles arbitrary missing constraints/columns on existing tables. |

Current ORM fields have a fresh-schema creation path. Legacy provider columns may remain extra on upgraded installations. Time types, defaults and indexes on upgraded tables can differ from fresh metadata. Serial repeatability on a compatible schema does not ensure safe concurrent migration runners, recovery after an interrupted SQLite rebuild, or retained child rows.

## Response Contract Comparison

| Operation | Actual success fields | Consumer implication |
|---|---|---|
| Pending | Array of label_id, category, annotator_id, confidence, recommended_action, factors, text_preview | Narrow current scored rows. No full source, revision token or spans. |
| Detail | domain_id, current label_id/category/annotator/factors/recommendation/confidence, text, actual_action, verified_outcome/at, revision_id, previous_category, status, content | Unscored fields can be null. Original ID resolves to latest; text_preview absent. |
| Verify | label_id, action_taken, was_correct, engine_updated, new_accuracy | Reports submitted ground truth and whether centroid moved. No full row. |
| Bulk verify | processed, skipped, errors[{label_id,error}] | A successful HTTP response can include cap skips and zero processed. |
| Relabel | input label_id, new category, revision_id, previous_category | revision_id is UUID, distinct from generated successor label_id returned by detail. |
| Ingest / batch | label_id, decision_id, recommended_action, confidence, factors_used, category, conservation_status, tier, action_policy, tier_status, auto_accepted. Batch wraps results and batch_size | Movement between DTOs requires explicit field mapping, particularly factors_used vs factors. |

Different projections serve different operations. Only pending sets X-Total-Count and both queries reuse its filters before offset/limit. FastAPI’s injected Response carries the header on successful reads. jm_service.py:285–295 exposes it to allowlisted origins. X-Volume-Warning is separate and absent from CORS exposure. Under concurrent writes, counting and paging in two SELECT statements under PostgreSQL READ COMMITTED can observe different snapshots.

Errors use FastAPI detail strings, structured quota detail objects, indexed batch detail, CSV string lists or Pydantic validation lists. SlowAPI’s registered 429 handler is a separate envelope. Health readiness returns status/checks with 503, and partial bulk results are normal 200 payloads. Unhandled DB/engine errors can yield generic 500 text. Clients must distinguish these representations.

## Frontend-Backend Contract Gaps

No frontend/src/types.ts exists in this checkout. The exported contracts are in frontend/src/api.ts. Compared each client family against its route, including payload field names and media types.

| Client calls (api.ts) | Result of comparison |
|---|---|
| uploadForAnalysis, uploadForReport, downloadReportPdf (188–190) | Multipart file matches. JSON, HTML text, PDF blob branches match. Analysis type leaves nested sections loosely typed. Its message?: string excludes the explicit null returned for verified data (label_health/analyze.py:78). |
| ingestLabel, ingestBatch, seedSample (191–193) | Body and result names agree, factors/text optionality correct for ingest, batch uses items/results, sample returns domain_id/created/existing/pending. |
| registerAccount (196) | Public email/name request and 201 api_key/tenant_id/tier/message agree. Signup stores new-store key. |
| verifyLabel, bulkVerify (197–199) | Required fields and action enum align. Single request interface omits optional backend annotator_id and reason. Bulk error strings match. |
| getPending, getPendingPage (200–211) | Query names and bare array agree. Page client validates X-Total-Count. PendingLabel inherits optional full text from IngestItem, although pending never sends it. |
| getLabelDetail, createLabelContent, createTextTask, relabelItem (212–215) | Detail nullable fields and discriminators match. LabelContent makes defaultable spans/tags/image_url mandatory to TS callers. Editable span text is optional in Python but required by NerSpan. Response count union represented as two optional fields. |
| getOverview, getCorrections, getAnnotators, getFactors, getCompounding (216–220) | Typed envelopes, nullable metrics, percentage units, query options and ISO timestamp strings match. |
| getAutonomy, getAgreement, getGuidelines, putGuidelines (221–230) | Category summaries, pair counts, nullable kappa and nullable guidelines align. |
| getAccount, getAccountDomains, resolveAccountDomain, getCheckoutUrl (232–241) | Summary, counters, domain names/needs_name, checkout_url/tier match. Checkout authenticates key even though billing binding uses tenant only. |

## Quota Path Analysis

| Operation | Units and transaction boundary |
|---|---|
| Single ingest / classified task | 1 via _ingest → reserve_label_capacity → score_and_persist. Unclassified task uses 0. |
| Batch ingest | 1 per item, all in one request session. Any raised failure rolls back earlier reservations, scores and domain changes. |
| Single verify | 0. Checks pending state and learns directly. Trial expiry is not checked here. |
| Bulk verify | 1 per eligible processed item, then the same verify/learn path. Unknown IDs reject the entire request before reservation. Reviewed, unscored and superseded rows skip before reserve. At 50/50 with three pending, processed=0, skipped=3 and each error is daily_cap_exceeded. At 48/50 three pending, 2 commit and 1 skips. Expired trial is 402, not a cap skip. Unexpected failure rolls back the whole request. |
| Relabel/content | Existing scored revision 0, even if category/spans/tags change. Classifying an unscored task invokes _ingest and costs 1. Initial content attachment costs 0. |
| Search/detail/dashboard | 0. A SQL read or HTTP rate limit does not advance usage counters. |
| Demo | Browser report is free. Fixed seed uses 1 per missing item, at most 12. Existing originals can have server-owned text backfilled at 0. All new reservations roll back on failure. |
| Connector / legacy | New connector score via _ingest costs 1. Existing prediction and ordinary verify cost 0. Relearning calls score_and_persist directly. Legacy SQLite score/learn use separate keys and no DLJ volume reservation. |

auth.py:53–65 creates a trial key. trial_guard.py:12–23,62–102 applies a 14-day trial from key creation and 50 units per UTC day per active key, without a lifetime or monthly trial cap. Day and month reset lazily on reservation. Both counters increment during trial. Expiry yields 402 on reserving paths. Existing reads, single verify and other free writes still authenticate. On a recognized subscription.created, billing updates one key’s tier and clears cancellation. It resets neither counter. Paid tiers bypass the daily check and use the existing current-month count against 10k/100k/1M or unlimited. A formerly capped trial key can score immediately if the upgraded key has monthly capacity. Account reports zero when stored period keys are stale. billing.TIER_VOLUME_CAPS and trial_guard.TIER_MONTHLY_CAPS duplicate paid values and represent the trial limit in different periods.

## Ranked Findings

Each entry records A location/signature, B full body read, C branch trace, D terminal source excerpt and consequence, and E severity. Line references are relative to jm-service. Findings involving a particular configuration or legacy schema are conditional. P1 includes uncaught production exceptions and silent data loss under the requested rubric.

### P1 (19)

#### P1.1 Subscription writes can run without provider authentication

**A · Locate** `billing.py:87` — `async def paddle_webhook(request: Request) -> dict[str, str]:`  
**B · Read** Full body, lines 87–167.  
**C · Trace** At 89 the default secret is empty. At 91 signature verification is conditional on a truthy secret. The handler opens a write session at 118 and commits at 165. The sandbox flag used by checkout at 65 is never consulted by the webhook.  
**D · Verdict** `if secret and not verify_paddle_signature(body, signature, secret):` (billing.py:91). A deployment missing this setting can accept unauthenticated entitlement and cancellation changes. Sandbox intent is documented at docs/session_state.md:429. Require the provider credential in live mode.  
**E · Classify** P1 (billing.py:91).

#### P1.2 Scored category revisions can break learning

**A · Locate** `labeling_router.py:577` — `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,                        session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 577–650.  
**C · Trace** For a scored item, the category is copied from the request into the successor without _prepare_engine. At 642 the predecessor is superseded. Verify then reconstructs the decision from the new category in db/repository.py:260. jm_core.py:349–350 looks up its action centroid directly. A new category, or one missing in the selected annotator snapshot, has no such entry.  
**D · Verdict** `category=request.category, factors_json=original.factors_json,` (labeling_router.py:628). Relabel succeeds, autonomy can omit the category, and subsequent verify raises KeyError. Bulk verification can roll back valid earlier items in the same batch.  
**E · Classify** P1 (labeling_router.py:628).

#### P1.3 PostgreSQL upgrade DDL disagrees with timezone-aware ORM writes

**A · Locate** `db/migrate.py:19` — `def upgrade(sync_connection):`  
**B · Read** Full body, lines 19–112.  
**C · Trace** At 45 revision_at is added as TIMESTAMP. At 98–100 the notification and cancellation dates get the same type. PostgreSQL interprets it without time zone. Fresh metadata uses DateTime(timezone=True). Relabel assigns aware UTC to revision_at and billing.py:161 does the same for cancellation.  
**D · Verdict** `"revision_at": "TIMESTAMP", "idempotency_token": "VARCHAR(200)",` (db/migrate.py:45). Depending on the driver bind path, upgraded installations can reject aware datetimes or convert them through session time zone and lose UTC semantics. These DDLs are not equivalent.  
**E · Classify** P1 (db/migrate.py:45).

#### P1.4 Conditional loss of structured content during SQLite rebuild

**A · Locate** `db/migrate.py:19` — `def upgrade(sync_connection):`  
**B · Read** Full body, lines 19–112.  
**C · Trace** At 53 the nullable-column test triggers for an older parent. At 71 only parent rows are copied. At 73 the old parent is dropped while db/connection.py:51 enables FKs. If label_content already exists and references that parent with CASCADE, the implicit delete affects its children. At 74 only the parent is renamed.  
**D · Verdict** `sync_connection.execute(text("DROP TABLE label_log"))` (db/migrate.py:73). A mixed-version database with existing child data can finish the upgrade with its spans, tags and image references deleted. The ordinary strictly ordered upgrade from before LabelContent has no children at risk.  
**E · Classify** P1 (db/migrate.py:73).

#### P1.5 Checkout upgrades an ambiguous key

**A · Locate** `billing.py:87` — `async def paddle_webhook(request: Request) -> dict[str, str]:`  
**B · Read** Full body, lines 87–167.  
**C · Trace** At checkout line 75 custom data carries tenant only. At 122–133 scalar selects one active row for customer or tenant. auth.py:113 permits multiple keys for one tenant. The chosen row receives the subscription at 142 while account.py:29 and trial_guard.py:67 look up the caller’s specific digest.  
**D · Verdict** `record = await session.scalar(select(ApiKey).where(` (billing.py:129). A valid paid checkout can update a different key while the purchaser remains capped. Customer and subscription IDs lack uniqueness in db/models.py:104.  
**E · Classify** P1 (billing.py:129).

#### P1.6 Webhook ordering can revive or prolong cancelled subscriptions

**A · Locate** `billing.py:87` — `async def paddle_webhook(request: Request) -> dict[str, str]:`  
**B · Read** Full body, lines 87–167.  
**C · Trace** Signature verification at 45–51 checks HMAC but has no freshness check. The handler stores neither event ID nor event time. Created and active-updated events clear cancellation, and every repeated cancellation writes the current delivery time at 161.  
**D · Verdict** `record.cancelled_at = None` (billing.py:144). A delayed older event can override newer state. Even legitimate provider retries can move the retention deadline.  
**E · Classify** P1 (billing.py:144).

#### P1.7 Connector corrections drop structured content and revision provenance

**A · Locate** `db/repository.py:217` — `async def verify_and_relearn(session: AsyncSession, domain_id: str, old_row: LabelLog,                              actual_action: str, verified_outcome: bool,                              annotator_id: str | None) -> LearnResult:`  
**B · Read** Full body, lines 217–243.  
**C · Trace** For an updated verified annotation, label_studio.py:299 invokes relearning. The successor receives annotation ID, source task ID and source text. The predecessor gets superseded. No call copies LabelContent or sets prior_revision_id, revision_actor or revision_at before flush.  
**D · Verdict** `old_row.superseded_by = label_id` (db/repository.py:241). The current detail loses existing spans/tags/image URL, even though the predecessor still owns them. The two revision writers expose different audit histories.  
**E · Classify** P1 (db/repository.py:241).

#### P1.8 Creation races escape normal conflict handling

**A · Locate** `labeling_router.py:540` — `async def create_text_task(domain_id: str, request: TextTaskRequest,                            session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 540–573.  
**C · Trace** Unclassified task checks for a duplicate, then both concurrent first-domain requests can see no domain. repository.create_domain flushes before the final try/except around task flush. Classified task also calls _ingest without catching optimistic StaleDataError.  
**D · Verdict** `await repository.create_domain(session, scoped, scoped, config, public_domain_id` (labeling_router.py:563). An otherwise valid concurrent create can surface a 500 instead of a retryable conflict. get_db rolls back the failed request.  
**E · Classify** P1 (labeling_router.py:563).

#### P1.9 API identifier validation exceeds PostgreSQL storage capacity

**A · Locate** `labeling_router.py:378` — `async def ingest(request: IngestRequest, response: Response, session: Session, tenant: Tenant) -> IngestResponse:`  
**B · Read** Full body, lines 378–388.  
**C · Trace** IngestItem accepts IDs with min_length but no 200-character maximum. Its validator only checks blank/separator. db/models.py:58–62 stores label, annotator and category in VARCHAR(200). The scoped public name is also persisted into VARCHAR(200). PostgreSQL can raise DataError, which the ingest handler’s IntegrityError and StaleDataError clauses do not catch.  
**D · Verdict** `except IntegrityError as exc:` (labeling_router.py:385). Valid-at-the-API input may produce a 500 on PostgreSQL while SQLite accepts it. The same storage mismatch affects batch and other writers.  
**E · Classify** P1 (labeling_router.py:385).

#### P1.10 Billing contact update can abort a legitimate subscription

**A · Locate** `billing.py:87` — `async def paddle_webhook(request: Request) -> dict[str, str]:`  
**B · Read** Full body, lines 87–167.  
**C · Trace** At 138–141 a customer email is assigned to the selected key. A case-insensitive matching address already on another key conflicts with uq_api_keys_contact_email at commit. There is no mapping or reconciliation for that IntegrityError.  
**D · Verdict** `record.contact_email = customer_email` (billing.py:141). The provider receives a server error and the transaction rolls back its tier update. The signup address index now affects billing delivery.  
**E · Classify** P1 (billing.py:141).

#### P1.11 Legacy engine and decision log writes commit independently

**A · Locate** `jm_service.py:557` — `def learn_outcome(domain_id: str, req: LearnRequest, tenant: str = Depends(get_tenant)):`  
**B · Read** Full body, lines 557–598.  
**C · Trace** At 564 load_engine reads a snapshot. validate_learn_input reads the unlearned row separately. At 585 the log is updated without a learned_at-is-null predicate, then save_engine opens another transaction. Two callers can read the same state or a failure can occur between commits. Score has an analogous split at 527–535.  
**D · Verdict** `save_engine(domain_id, engine)` (jm_service.py:589). A decision can be marked learned without its engine update, or concurrent successful operations can overwrite learned state. Current DLJ repository version checks do not protect the legacy store.  
**E · Classify** P1 (jm_service.py:589).

#### P1.12 Legacy registration persists reusable plaintext credentials

**A · Locate** `jm_service.py:422` — `def register_tenant(request: Request, req: RegisterRequest | None = None):`  
**B · Read** Full body, lines 422–431.  
**C · Trace** Registration creates the bearer key and inserts it directly into tenants. The tenant key is also stored with domains and decision rows. get_tenant at 301–305 compares the presented key directly. legal_pages.py:74 describes storage of key hashes only.  
**D · Verdict** `"INSERT INTO tenants (api_key, name, created_at) VALUES (?, ?, ?)",` (jm_service.py:428). A copy of the legacy database exposes usable credentials. New DLJ signup hashes correctly, but both registration APIs ship in the same application.  
**E · Classify** P1 (jm_service.py:428).

#### P1.13 Unverified signup address can bind two parties to one credential

**A · Locate** `auth.py:49` — `async def register(request: Request, payload: RegisterRequest, session: Session) -> dict[str, str]:`  
**B · Read** Full body, lines 49–66.  
**C · Trace** At 50–56 syntax and uniqueness establish eligibility without proof of mailbox control. At 63 the key goes to the supplied mailbox and at 65 the same usable key goes to the HTTP requester. Both can subsequently authenticate as the new tenant.  
**D · Verdict** `return {"api_key": plain, "tenant_id": tenant_id, "tier": "trial",` (auth.py:65). If mailbox owner and requester differ, a user following the welcome email can put labels into an account another party already controls. Existing tenant keys are not returned by duplicate signup.  
**E · Classify** P1 (auth.py:65).

#### P1.14 Anonymous report waiters hold entire uploads before admission

**A · Locate** `label_health/api.py:45` — `async def _analyze(file: UploadFile, output: str) -> Any:`  
**B · Read** Full body, lines 45–68.  
**C · Trace** Each request reads up to 10 MiB before acquiring _slots. Two workers bound active analysis. Additional concurrent requests retain their byte buffers while awaiting the semaphore for up to 60 seconds. The routes lack an application rate or waiting-queue bound.  
**D · Verdict** `data = await file.read(_MAX_BYTES + 1)` (label_health/api.py:48). Application memory consumed by waiting uploads grows with concurrency. Impact depends on upstream admission controls.  
**E · Classify** P1 (label_health/api.py:48).

#### P1.15 Malformed product data can escape payload validation

**A · Locate** `billing.py:87` — `async def paddle_webhook(request: Request) -> dict[str, str]:`  
**B · Read** Full body, lines 87–167.  
**C · Trace** At 111–115 a list and dictionary are checked, but the product name itself has no string validation. At 116 the resulting value is used as a dict key.  
**D · Verdict** `tier = PADDLE_TIER_MAP.get(product_name)` (billing.py:116). An unhashable product name raises TypeError outside the guarded parse block. Unknown scalar product names on creation instead silently fall back to starter at line 143.  
**E · Classify** P1 (billing.py:116).

#### P1.16 Legacy factor range shape can raise a server error

**A · Locate** `jm_service.py:440` — `def create_domain(req: CreateDomainRequest, tenant: str = Depends(get_tenant)):`  
**B · Read** Full body, lines 440–473.  
**C · Trace** CreateDomainRequest accepts lists as range values. create_domain indexes positions zero and one while building DomainConfig. The request validators only inspect factors/categories/actions.  
**D · Verdict** `factor_ranges={k: (v[0], v[1]) for k, v in req.factor_ranges.items()},` (jm_service.py:452). An undersized range reaches unchecked indexing instead of a validation response.  
**E · Classify** P1 (jm_service.py:452).

#### P1.17 Indexed batch errors can reflect SQL parameters and uploaded source text

**A · Locate** `labeling_router.py:478` — `async def ingest_batch(request: IngestBatchRequest, response: Response, session: Session,                        tenant: Tenant) -> IngestBatchResponse:`  
**B · Read** Full body, lines 478–492.  
**C · Trace** A flush error such as an existing label propagates from _ingest. The batch handler stringifies the SQLAlchemy exception and puts that string into HTTP detail. The engine factory has no hide_parameters option. Driver exception formatting can include SQL and bound values, including text and factors.  
**D · Verdict** `detail = exc.detail if isinstance(exc, HTTPException) else str(exc)` (labeling_router.py:488). A client-visible validation response can disclose internal database diagnostics and source data into error telemetry. This path does not establish a cross-tenant read.  
**E · Classify** P1 (labeling_router.py:488).

#### P1.18 Public-report allowlist conflict

**A · Locate** `label_health/api.py:72` — `async def analyze(file: UploadFile = File(...)) -> JSONResponse:` and companion handlers at :77 and :82.  
**B · Read** All three handlers and _analyze.  
**C · Trace** At :71–83 each route accepts an uploaded file without a tenant dependency. At :45–68 validation, size and concurrency checks lead to computation using the caller’s own bytes. Session state records anonymous HTML/PDF/JSON as deliberate.  
**D · Verdict** `return JSONResponse(await _analyze(file, "json"))` (:73). If A2’s health exception is only for readiness, the supplied allowlist excludes all three handlers. Treat these routes as one explicit product exception or require credentials. No stored-tenant disclosure follows from this finding.  
**E · Classify** P1 against the strict allowlist (label_health/api.py:71), conditional on that interpretation.

#### P1.19 Connector input errors can escape request validation

**A · Locate** `label_studio.py:179` — predict, which accepts `payload: dict[str, Any]`.  
**B · Read** predict (:179–226), _task_values (:111–127), IngestItem validators and new-score branch.  
**C · Trace** :183 checks only that tasks is a list. :188 passes each element to _task_values. :112 calls .get before checking the element type. For an object with an out-of-range numeric factor, :123 converts it successfully, then :207–209 constructs IngestItem inside the handler.  
**D · Verdict** `label_id, category, factors = _task_values(task, config)` (:188). Non-object entries raise AttributeError. Internal model validation errors are not FastAPI request validation errors. Neither branch produces the expected controlled 422.  
**E · Classify** P1 (label_studio.py:188).

### P2 (23)

#### P2.1 Cancellation does not end paid scoring

**A · Locate** `trial_guard.py:62` — `async def reserve_label_capacity(session: AsyncSession) -> dict[str, str] | None:`  
**B · Read** Full body, lines 62–102.  
**C · Trace** billing.py:161 sets cancelled_at. require_tenant checks only is_active. reserve checks trial age and tier limits without consulting cancellation. scheduler.py:54 onward only cleans eligible tenants after retention and skips tenants with another active key.  
**D · Verdict** `check_trial_expiry(record)` (trial_guard.py:82). Cancelled paid keys can still score during retention, potentially longer in multi-key tenants. Confirm the intended entitlement end independently of the deletion deadline.  
**E · Classify** P2 (trial_guard.py:82).

#### P2.2 Single and bulk review charge differently

**A · Locate** `labeling_router.py:430` — `async def bulk_verify(request: Request, domain_id: str, payload: BulkVerifyRequest,                       session: Session, tenant: Tenant) -> dict:`  
**B · Read** Full body, lines 430–474.  
**C · Trace** Bulk reserves one unit after skip checks. Its call to verify is the same learn path used for a single decision. Single verify has no reserve or expiry check. At a daily cap bulk returns skips while single can still verify the same eligible row.  
**D · Verdict** `await reserve_label_capacity(session)` (labeling_router.py:458). Review cost and expiry depend on UI operation. B3 explicitly introduced the bulk charge, so this is a policy inconsistency, not a double debit inside the loop.  
**E · Classify** P2 (labeling_router.py:458).

#### P2.3 SQLite legacy billing IDs are stranded

**A · Locate** `db/migrate.py:19` — `def upgrade(sync_connection):`  
**B · Read** Full body, lines 19–112.  
**C · Trace** At 88 the rename branch requires PostgreSQL. At 106–109 SQLite adds fresh nullable Paddle columns. Existing customer/subscription references in the legacy columns are not copied.  
**D · Verdict** `if old in names and new not in names and sync_connection.dialect.name == "postgr` (db/migrate.py:88). Automatic subscription lookup can lose its link on upgraded SQLite. Existing-both-columns databases also need explicit reconciliation.  
**E · Classify** P2 (db/migrate.py:88).

#### P2.4 Duplicate legacy contacts block migration

**A · Locate** `db/migrate.py:19` — `def upgrade(sync_connection):`  
**B · Read** Full body, lines 19–112.  
**C · Trace** At 110–112 the migration builds a unique lower(contact_email) index with a NULL exemption. Previously admitted case variants can map to one non-null key. IF NOT EXISTS only tests whether the index name exists.  
**D · Verdict** `"CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_contact_email "` (db/migrate.py:111). Upgrade fails at index creation until duplicate ownership is resolved. Re-running unchanged data fails again.  
**E · Classify** P2 (db/migrate.py:111).

#### P2.5 Content creation and editing apply incompatible vocabularies and limits

**A · Locate** `labeling_router.py:577` — `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,                        session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 577–650.  
**C · Trace** create_label_content permits up to 1,000 known-label NER spans with matching text. Relabel accepts at most 100 and allows custom labels. Initial tags allow domain vocabulary up to 200 characters. Relabel permits custom tags but only 50 characters and folds duplicates.  
**D · Verdict** `edited_spans.append({"start": span.start, "end": span.end,` (labeling_router.py:600). Some existing content cannot be resaved after an unrelated edit. Custom edited content may fail to round-trip through the content creation API.  
**E · Classify** P2 (labeling_router.py:600).

#### P2.6 Verified records can be revised despite read-only UI

**A · Locate** `labeling_router.py:577` — `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,                        session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 577–650.  
**C · Trace** ReviewCard switches NER/tag editors to read-only on verified_at. Relabel checks the current token but no verified-state restriction. The scored branch copies verified_at/outcome into the changed category or content.  
**D · Verdict** `verified_outcome=original.verified_outcome, verified_at=original.verified_at,` (labeling_router.py:632). The audit records a revision, but the new content inherits an old verification. Category metrics can move without a new verification or matching engine update.  
**E · Classify** P2 (labeling_router.py:632).

#### P2.7 Seed pending count follows original IDs only

**A · Locate** `labeling_router.py:496` — `async def seed_sample(domain_id: str, response: Response, session: Session, tenant: Tenant) -> dict[str, str | int]:`  
**B · Read** Full body, lines 496–536.  
**C · Trace** After relabel, the original sample ID still exists and is superseded. The latest current ID is a generated revision. Seed queries original IDs with verified_at IS NULL. If the successor is reviewed, the original can remain unverified.  
**D · Verdict** `LabelLog.label_id.in_(ids), LabelLog.verified_at.is_(None)))).all()` (labeling_router.py:532). Seed reports a pending sample that is absent from the current queue.  
**E · Classify** P2 (labeling_router.py:532).

#### P2.8 Email delivery precedes database commit

**A · Locate** `auth.py:49` — `async def register(request: Request, payload: RegisterRequest, session: Session) -> dict[str, str]:`  
**B · Read** Full body, lines 49–66.  
**C · Trace** Flush succeeds at 59. Email delivery is attempted at 63. db/connection.py:59 commits only when the dependency finishes. A later commit failure can invalidate an already delivered key.  
**D · Verdict** `if not await send_api_key_email(payload.email, plain):` (auth.py:63). The recipient can receive a credential that the service cannot authenticate.  
**E · Classify** P2 (auth.py:63).

#### P2.9 Signup quickstart sends the user to the other credential store

**A · Locate** `email_service.py:29` — `def api_key_email(api_key: str) -> tuple[str, str]:`  
**B · Read** Full body, lines 29–44.  
**C · Trace** auth.register creates a hashed ApiKey. The welcome email names legacy domain score/learn. jm_service.py:301 checks the separate SQLite tenants table for those routes.  
**D · Verdict** `<li>POST /v1/domains/{{domain_id}}/score with your factors</li>` (email_service.py:39). Following the emailed API instructions with the delivered DLJ key fails authentication.  
**E · Classify** P2 (email_service.py:39).

#### P2.10 Prediction replay reads a superseded label

**A · Locate** `label_studio.py:179` — `async def predict(payload: dict[str, Any], response: Response, session: Session, _: Authorized,                   tenant: Tenant) -> dict[str, list[dict[str, Any]]]:`  
**B · Read** Full body, lines 179–226.  
**C · Trace** The existing-label query looks up the original task ID without superseded_by filtering. The replay branch compares category/factors and returns original confidence. The webhook and detail route explicitly follow the successor chain.  
**D · Verdict** `existing = await session.scalar(select(LabelLog).where(` (label_studio.py:190). Replay can return a stale prediction or reject task content matching the current revision.  
**E · Classify** P2 (label_studio.py:190).

#### P2.11 Undefined agreement is presented as perfect

**A · Locate** `dashboard_router.py:140` — `def cohen_kappa(left: list[str], right: list[str]) -> float | None:`  
**B · Read** Full body, lines 140–147.  
**C · Trace** A pair with identical constant categories has observed=expected=1. The denominator of kappa is zero. The special case returns 1.0.  
**D · Verdict** `return 1.0 if observed == 1 else None` (dashboard_router.py:146). The dashboard can present excellent agreement when the chance-adjusted statistic is undefined. Its existing nullable response type can express this case.  
**E · Classify** P2 (dashboard_router.py:146).

#### P2.12 Search case folding differs across databases

**A · Locate** `labeling_router.py:655` — `async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: Tenant,                   category: str | None = None, limit: int = Query(default=50, ge=1, le=200),                   offset: int = Query(default=0, ge=0),                   sort_by: Literal["label_id", "category", "annotator_id", "confidence", "recommended_action"] | None = None,                   sort_order: Literal["asc", "desc"] = "asc",                   search: str | None = Query(default=None, max_length=200)) -> list[dict]:`  
**B · Read** Full body, lines 655–692.  
**C · Trace** The input is lowercased in Python. func.lower applies the database implementation to stored labels. Standard SQLite only lowercases ASCII, while Python lower transforms many Unicode letters.  
**D · Verdict** `func.lower(LabelLog.text).contains(search_lower, autoescape=True),` (labeling_router.py:675). Case-insensitive substring search is reliable for ASCII. Non-ASCII uppercase source can miss even when the user enters that same term.  
**E · Classify** P2 (labeling_router.py:675).

#### P2.13 Duplicate-email response discloses account existence

**A · Locate** `auth.py:49` — `async def register(request: Request, payload: RegisterRequest, session: Session) -> dict[str, str]:`  
**B · Read** Full body, lines 49–66.  
**C · Trace** Public register checks the normalized contact address and returns 409 for a match, 201 for an available address. The limiter applies per IP.  
**D · Verdict** `raise HTTPException(status_code=409, detail="Email already registered")` (auth.py:52). Membership is observable to unauthenticated clients. This follows the explicit signup UX contract and merits a product/privacy decision.  
**E · Classify** P2 (auth.py:52).

#### P2.14 Sample replay counts disagree with the stated idempotency contract

**A · Locate** `labeling_router.py:496` — `async def seed_sample(domain_id: str, response: Response, session: Session, tenant: Tenant) -> dict[str, str | int]:`  
**B · Read** Full body, lines 496–536.  
**C · Trace** First call creates up to 12 rows and returns len(existing_ids)=0. Repeating it fills existing_ids and initializes created back to zero. The membership and charge are stable while the created/existing response counts change.  
**D · Verdict** `"existing": len(existing_ids), "pending": len(pending_ids)}` (labeling_router.py:536). The operation is idempotent in persistent effects, but replay does not return identical counts as requested in A1.  
**E · Classify** P2 (labeling_router.py:536).

#### P2.15 No-op relabel creates a correction and invalidates the prior token

**A · Locate** `labeling_router.py:577` — `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,                        session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 577–650.  
**C · Trace** If category and submitted arrays equal their stored values, token validation passes. No equality test precedes successor ID generation and prior-row supersession.  
**D · Verdict** `successor_label_id = f"revision:{uuid4().hex}"` (labeling_router.py:608). Identical content produces a new correction, causes legitimate concurrent editors to see 409, and grows the revision chain at zero volume cost.  
**E · Classify** P2 (labeling_router.py:608).

#### P2.16 Checkout creation is an unmetered side effect on GET

**A · Locate** `billing.py:55` — `async def get_checkout_url(tenant: Tenant, tier: str = "starter") -> dict[str, str]:`  
**B · Read** Full body, lines 55–83.  
**C · Trace** An authenticated GET makes a provider POST and returns its URL. No request idempotency key or endpoint limiter is supplied. Retries or prefetch can create multiple pending checkouts.  
**D · Verdict** `response = await client.post(` (billing.py:70). A read-like operation incurs repeated external side effects.  
**E · Classify** P2 (billing.py:70).

#### P2.17 Unscored and revision writes have no independent admission limit

**A · Locate** `labeling_router.py:540` — `async def create_text_task(domain_id: str, request: TextTaskRequest,                            session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 540–573.  
**C · Trace** With category absent, task validation permits 32 KiB and the handler inserts LabelLog with no reservation. No endpoint limit applies. Category-only revisions likewise copy existing content without a cap.  
**D · Verdict** `category=None, factors_json={}, text=request.text,` (labeling_router.py:567). An active credential including an expired trial can grow persistent storage independently of every scoring cap. Free classification drafts may be intentional, but storage/admission limits are missing.  
**E · Classify** P2 (labeling_router.py:567).

#### P2.18 Bulk approval equates acceptance with verified ground truth

**A · Locate** `labeling_router.py:430` — `async def bulk_verify(request: Request, domain_id: str, payload: BulkVerifyRequest,                       session: Session, tenant: Tenant) -> dict:`  
**B · Read** Full body, lines 430–474.  
**C · Trace** Single verify accepts actual_action and verified_outcome separately. Bulk maps approval to the recommendation, then sets outcome true for approval and false for rejection. No independent ground truth is accepted from the bulk caller.  
**D · Verdict** `verified_outcome=payload.action == "approve",` (labeling_router.py:471). Bulk can feed reviewer agreement straight into accuracy/conservation metrics. This follows B3’s specification but disagrees with the single-review ground-truth semantics.  
**E · Classify** P2 (labeling_router.py:471).

#### P2.19 ReviewCard can apply an older detail response to a newer route

**A · Locate** `frontend/src/screens/ReviewCard.tsx:45` — `const load = useCallback(async () => {`  
**B · Read** Entire ReviewCard function, especially load, route-change effect and submit.  
**C · Trace** ReviewCard.tsx:45–61 fetches detail, pending and autonomy together and checks only currentDomain. For two label IDs in the same domain a slower earlier read can win. At :105–108 verification uses item.label_id, independent of the current URL.  
**D · Verdict** `if (currentDomain.current !== domainId) return` (frontend/src/screens/ReviewCard.tsx:52). The card can display or submit the wrong label for the URL. Failure of an auxiliary pending/autonomy request also hides a valid deep detail.  
**E · Classify** P2 (frontend/src/screens/ReviewCard.tsx:52).

#### P2.20 Client drops structured HTTP failures

**A · Locate** `frontend/src/api.ts:163` — `async function request<T>(path: string, init?: RequestInit, onResponse?: (response: Response) => void): Promise<T>`  
**B · Read** request and explain, lines 151–178, plus installed SlowAPI handler.  
**C · Trace** frontend/src/api.ts:169–172 reads response.json().detail. The SlowAPI handler registered at jm_service.py:273 emits a top-level error; explain falls back to a generic message. On non-JSON 5xx, json() consumes the body before text() retries.  
**D · Verdict** `try { detail = (await response.json()).detail } catch { detail = await response.` (frontend/src/api.ts:171). Rate-limit context is lost and text failures can surface a body-read exception instead of ApiError/status.  
**E · Classify** P2 (frontend/src/api.ts:171).

#### P2.21 Legacy domain ownership is not backfilled

**A · Locate** `db/migrate.py:19` — `def upgrade(sync_connection):`.  
**B · Read** upgrade (:19–112), scoped_domain_id and resolve_domain.  
**C · Trace** :25–27 fills newly added tenant IDs with an empty string. A real signup tenant has a UUID. account.py:75–77 requires both a matching tenant and an already matching scoped internal ID. Legacy name resolution only fills public_domain_id on rows already owned.  
**D · Verdict** `Domain.tenant_id == tenant).with_for_update())` (account.py:77). Existing pre-tenancy rows stay inaccessible to issued nonempty tenant IDs until explicitly attributed.  
**E · Classify** P2 (db/migrate.py:25).

#### P2.22 History-dependent work multiplies inside batches

**A · Locate** `labeling_router.py:288` — _category_stats(session, domain_id, categories).  
**B · Read** _category_stats, _ingest and ingest_batch, including session rollback behavior.  
**C · Trace** :290–298 loads complete verified LabelLog ORM objects, including source text, to reconstruct category outcome history. _ingest calls this after each score. Batch loops over up to 100 items in the same transaction.  
**D · Verdict** `select(LabelLog).where(LabelLog.domain_id == domain_id,` (:291). Time and memory per score increase with all verified rows. A large atomic batch repeats that history scan while holding transactional locks.  
**E · Classify** P2 (labeling_router.py:290).

#### P2.23 Tenant-wide guideline writes have no editor role

**A · Locate** `labeling_router.py:59` — put_guidelines(domain_id, payload, tenant, session).  
**B · Read** get/put and guidelines_domain (:45–64), plus require_tenant.  
**C · Trace** :61 resolves the owned domain, :62 replaces guidelines using any active key for that tenant. No role is present in ApiKey or tenant dependency.  
**D · Verdict** `domain.guidelines = payload.guidelines` (:62). A reviewer credential can change instructions for every reviewer in that tenant domain. The session log explicitly records the access limitation.  
**E · Classify** P2 (labeling_router.py:62), an authorization granularity decision, not a cross-tenant read.

### P3 (4)

#### P3.1 Batch and single conflict statuses diverge

**A · Locate** `labeling_router.py:478` — `async def ingest_batch(request: IngestBatchRequest, response: Response, session: Session,                        tenant: Tenant) -> IngestBatchResponse:`  
**B · Read** Full body, lines 478–492.  
**C · Trace** Single ingest maps uniqueness and stale state to 409. An otherwise identical failure inside the batch is wrapped in 422 with item_index unless it is 402/429.  
**D · Verdict** `raise HTTPException(status_code=422, detail={"item_index": index, "error": detai` (labeling_router.py:489). Clients cannot apply the same HTTP retry policy to equivalent failures.  
**E · Classify** P3 (labeling_router.py:489).

#### P3.2 Two success surfaces advertise different pending text fields

**A · Locate** `labeling_router.py:655` — `async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: Tenant,                   category: str | None = None, limit: int = Query(default=50, ge=1, le=200),                   offset: int = Query(default=0, ge=0),                   sort_by: Literal["label_id", "category", "annotator_id", "confidence", "recommended_action"] | None = None,                   sort_order: Literal["asc", "desc"] = "asc",                   search: str | None = Query(default=None, max_length=200)) -> list[dict]:`  
**B · Read** Full body, lines 655–692.  
**C · Trace** Pending serializes preview and factors. frontend/src/api.ts:52 extends IngestItem, inheriting optional full text. LabelDetail omits several pending fields and explicitly supplies full text.  
**D · Verdict** `"recommended_action": row.recommended_action, "factors": row.factors_json,` (labeling_router.py:690). A typed consumer can read pending.text and always receive undefined; current preview rendering uses the correct field.  
**E · Classify** P3 (labeling_router.py:690).

#### P3.3 Optional relabel field is ambiguous to API consumers

**A · Locate** `labeling_router.py:577` — `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest,                        session: Session, tenant: Tenant) -> dict[str, str | None]:`  
**B · Read** Full body, lines 577–650.  
**C · Trace** api.ts:215 and RelabelRequest require category and token even for a tags-only change. The C2 example body contains tags only. Omitting the required fields yields framework 422 before the handler.  
**D · Verdict** `idempotency_token: str = Field(min_length=1, max_length=200)` (labeling_router.py:202). The implemented UI works because it resends category/token. The literal tags-only example cannot work, particularly for unclassified items with no category to resend.  
**E · Classify** P3 (labeling_router.py:202).

#### P3.4 Volume warning is invisible to cross-origin JS

**A · Locate** `labeling_router.py:378` — `async def ingest(request: IngestRequest, response: Response, session: Session, tenant: Tenant) -> IngestResponse:`  
**B · Read** Full body, lines 378–388.  
**C · Trace** Ingest sets X-Volume-Warning from session.info. jm_service.py:295 exposes only X-Total-Count, while the client reads only the count.  
**D · Verdict** `response.headers["X-Volume-Warning"] = warning` (labeling_router.py:383). Allowed cross-origin dashboards cannot inspect the volume warning in JavaScript.  
**E · Classify** P3 (labeling_router.py:383).

DLJ backend consistency sweep complete. 46 explicit application endpoints, six ORM models. 19 P1, 23 P2 and 4 P3 findings. Zero source files modified. This report is the only new file.

