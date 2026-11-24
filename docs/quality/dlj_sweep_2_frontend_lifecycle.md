# DLJ frontend lifecycle sweep

## Summary (top 5 findings)

Reviewed jm-service at `722ef13` on 24 November 2026. The five highest-impact failure paths are:

1. **Review can verify the wrong label.** A late detail response passes a domain-only check after navigation between two labels. In Chromium the URL was `#/review/two`, the heading showed `one`, and the verification request named `one`.
2. **A credential change can reuse the previous tenant's screen state.** Requests read the current browser key independently. Data loads and selections depend on the public domain name. With the same domain and label names in two accounts, a new valid key can act on data still displayed from the previous account.
3. **Approval silently abandons annotation edits.** Dirty spans and tags disable category selection, but approval still verifies the stored revision. In the browser a dirty tag followed by approval produced only a verify POST.
4. **Queue actions can target a new domain using old rows.** If the new pending fetch fails, the table keeps old rows. Row selection and bulk submission then operate under the new domain.
5. **Settings can overwrite another domain's guidelines.** The editor permits saving the previous draft during the new domain's load and substitutes empty instructions on a load error.

**Evidence.** Four failure paths were exercised in Chromium with synthetic labels and intercepted API responses. The browser submitted a verification for the previous route label, approved with a dirty tag, posted a selected label from the previous domain after the new queue fetch failed, and saved guidelines from the previous domain while the new GET was pending. These checks capture what the frontend sent. The backend write consequences and remaining findings are traced in source. Read all eight screens, all 18 files under components, App, API client, styles, context, CSV parser and mount. The requested types.ts is absent. The wire types live in api.ts. Later shipped features include B4 search, editable tags, image classification, shortcuts, theme, guidelines and IAA. The review follows the workspace copy of blogs/quality/bug_hunt_v5.md. In the ranked register A locates the function, B identifies the body read, C traces values/branches, D quotes the deciding code and gives the outcome, and E assigns severity. Line numbers refer to this checkout.

## ReviewCard Integration Audit

Read ReviewCard.tsx:17–81 and 82–147, including every callback. The 14 state hooks at lines 23–36 are item, loadedDomain, pending, tier, entityTypes, editedSpans, editedTags, outcome, override, error, message, busy, showGuidelines and guidelines. currentDomain is a ref. load reads detail, up to 200 pending rows and autonomy in parallel. Any rejection skips all three assignments. The route-state preview passed by queue links is unused.

| Detail returned | Render path at ReviewCard.tsx:135–145 |
|---|---|
| No item or domain mismatch | Spinner while busy, then “Label not found” even on some network errors |
| content=null, text present | TextViewer plus NEREditor. On verified items NEREditor:25 delegates to NERViewer. Plain text can thus be upgraded to NER. No tag-creation control appears on plain text |
| text_ner | TextViewer plus editable NER or read-only NERViewer according to verified_at. Save Spans requires a category, a dirty buffer, an unverified row and idle state |
| text_multilabel | TextViewer plus TagSelector. Verification makes the chips read-only. Save Tags has the equivalent guard |
| image_classification | ImageViewer when image_url exists, category control even without text, and the normal factors and verification controls. No image URL yields no image panel. Creation currently validates the URL server-side |
| text=null, no content | TextViewer's unavailable message, factors and review controls. No category selector |
| content omitted | Optional chains handle some branches. With non-null text, line 138 dereferences undefined.content_type. Current backend explicitly emits null at labeling_router.py:778, so this is a version-skew risk, not a current matched-server failure |

On a successful save, relabel creates a successor with a new label ID and revision UUID. Detail follows the chain, returns the successor label_id, and load replaces the local draft and remounts the keyed editor. Using that new ID for verification is correct. A stale revision gets 409 and a reload. Approve captures the current render's outcome and action. It never consumes the span/tag draft. A/O/E listeners are renewed each render with cleanup. E displays an escalation message and leaves the item pending. The NER popup and review shortcut listeners can both be active. Findings below distinguish this from a stale closure.

**NER selection and shortcuts.** At NEREditor.tsx:67–76, a null selection, a collapsed selection or zero ranges exits before reading range 0. A range outside the editor or ending inside annotation chrome yields a null offset. Dragging right-to-left works because the code reads the ordered Range endpoints, then converts DOM text lengths to Unicode code points at 53–65. Equal or inverted computed offsets are rejected. Selecting across an existing highlight is rejected using strict overlap, so adjacent spans are allowed. Rejection leaves any earlier popup intact. Escape at 21 dismisses the popup; the editor calls removeAllRanges only after applying an edit at 86. Review A and O require a scored, unverified item and a selected outcome; O also requires an override. They ignore text-entry targets but remain active on marks and popup buttons. The entity popup has a fixed viewport position estimated from constants at 102.

## ScoredQueue State Management Audit

Read ScoredQueue.tsx:17–96 and 97–167. Lines 44–47 schedule the trimmed search after 300 ms, reset offset to zero and clear the timeout on input change or unmount. With input abc followed by ab before expiry, only ab applies. When both requests have started, lines 65–90 increment a generation and reject older success, error and finally callbacks. The latest applied request wins even if the earlier one finishes last. During the debounce window old results legitimately still represent the previous applied query. A new string with identical trimmed value needlessly resets the page.

Line 42 clears bulk selection on domain, category, **applied** search, sort key/order, page size and offset. Line 49 prunes selected IDs removed on refresh. Changing sort calls setOffset(0). A successful bulk result for the current domain shows processed/skipped counts, clears selection and invokes the latest refresh callback at 127–138. Detailed per-label errors returned by B3 are discarded. A failed mutation keeps selection for retry. The header select-all disables during fetch, individual row boxes and bulk buttons use only bulkBusy. The gap between invalidating a request and invalidating the displayed rows matters even with correct request ordering.

Pending GET returns a bare array. labeling_router.py:653–695 uses identical filters for count and rows. jm_service.py:295 exposes X-Total-Count through CORS. api.ts:205–210 accepts decimal digits and safe integers (zero included). A 200 missing/invalid header throws “Pending total count is unavailable”. A non-2xx fails before the header callback. Queue catches either error, ends busy and retains its previous rows/count. There is no silent estimate from the current page length.

## API Contract Verification

All paths below include /v1. D and L denote encoded domain and label path segments. Each row identifies the actual client function, verb, payload or query, server handler and parsed result. All 28 exported network functions use request<T>. Field checks compared TS definitions with backend request models and return constructors. Call-site failures appear in the screen matrix. Functions without a UI caller propagate rejection to their caller. The application requires no redundant try/catch in each wrapper.

| api.ts line and function | Method, path, input | Backend and response |
|---|---|---|
|188 uploadForAnalysis|POST /label-health/analyze, multipart file|label_health/api.py:71, JSON report; metadata consumed by Upload. analyze.py:72–79 emits nullable message; TS declares optional string only|
|189 uploadForReport|POST /label-health/report, multipart file|label_health/api.py:76, HTML as text into sandboxed preview|
|190 downloadReportPdf|POST /label-health/report/pdf, multipart file|label_health/api.py:81, PDF as Blob|
|191 ingestLabel|POST /labels/ingest, domain_id plus label_id, category, factors, optional annotator_id/text|labeling_router.py:377, scored IngestResponse|
|192 ingestBatch|POST /labels/ingest/batch, domain_id and items of the same shape|:477, results and batch_size; each call accepts 1–100 items|
|193 seedSample|POST /labels/D/sample, no body|:495, domain_id/created/existing/pending|
|196 registerAccount|POST /auth/register, email, optional name omitted when blank|auth.py:47–49, 201 api_key/tenant_id/tier/message|
|197 verifyLabel|POST /labels/verify, domain_id/label_id/actual_action/verified_outcome|labeling_router.py:391, VerifyResponse. Optional backend annotator_id and reason unavailable in this wrapper|
|199 bulkVerify|POST /labels/D/bulk-verify, label_ids/action/optional reason|:428, processed/skipped/errors. Current UI sends IDs and action only. Partial success is HTTP 200|
|202 getPending|GET /labels/D/pending, category/limit/offset/sort_by/sort_order/search|:653, JSON array, used for review navigation|
|203 getPendingPage|same GET and parameters|:653, same array plus validated X-Total-Count. Client returns rows/total|
|212 getLabelDetail|GET /labels/D/items/L|:757, current LabelDetail with nullable content/text/verification and revision_id. Old GET /labels/D/L alias also exists|
|213 createLabelContent|POST /labels/D/items/L/content, content_type/spans/tags/image_url|:714, 201 label_id/content_type and type-specific count. Wrapper available independently of the UI|
|214 createTextTask|POST /labels/D/tasks, label_id/text/optional category|:539, 201 label_id/status/category|
|215 relabelItem|POST /labels/D/items/L/relabel, category/idempotency_token/optional spans or tags|:576, label_id/category/previous_category/revision_id. json() preserves arrays, including [] to clear. Server rejects simultaneous spans and tags. Span offsets are code points|
|216 getOverview|GET /dashboard/D/overview|dashboard_router.py:211, counts/accuracy/categories/inversion/curve/generated_at|
|217 getCorrections|GET /dashboard/D/corrections|:234, total/rate/patterns/top_pattern|
|218 getAnnotators|GET /dashboard/D/annotators, limit|:258, domain_id and annotators array|
|219 getFactors|GET /dashboard/D/factors|:296, factor_names/inversion/factor_stats|
|220 getCompounding|GET /dashboard/D/compounding, optional window/category|:320, points, baseline/current accuracy and improvement|
|221 getAutonomy|GET /domains/D/autonomy|labeling_router.py:783, domain_id/categories/overall_tier|
|227 getAgreement|GET /dashboard/D/iaa|dashboard_router.py:150, pairs, overall_kappa, total_overlapping_labels|
|228 getGuidelines|GET /domains/D/guidelines|labeling_router.py:52, nullable guidelines|
|229 putGuidelines|PUT /domains/D/guidelines, JSON guidelines|:58, saved guidelines; server enforces 10 KiB UTF-8|
|238 getAccount|GET /account|account.py:26, active key's account, tier, dates, UTC usage/caps|
|239 getAccountDomains|GET /account/domains|:54, array of id/public_domain_id/needs_name|
|240 resolveAccountDomain|POST /account/domains/resolve, domain_id|:73, resolved public_domain_id|
|241 getCheckoutUrl|GET /billing/checkout-url, tier|billing.py:54, checkout_url/tier|

**Local functions.** ApiError.constructor:148 retains status. explain:151 handles strings, nested arrays, item_index/error, message and msg. request:163 builds headers, fetches, checks status, calls the optional response hook and decodes MIME type. json:179 creates a POST JSON body. upload:180 sets multipart file, leaving boundary selection to fetch. params:181 uses URLSearchParams (ampersand, plus, percent, spaces and Unicode survive as data). id:186 uses encodeURIComponent. hasApiKey:194 checks the same localStorage/dev source without a network call. Thus 29 exported functions including the local predicate, 28 network wrappers, 27 distinct HTTP method/path combinations.

**Credential and endpoint coverage.** Only /label-health/* and /auth/register are public in this client. Every protected wrapper goes through api.ts:163–168. An absent key omits the header and protected calls return 401; a DEV build can supply VITE_API_KEY. Missing credentials do not bypass the server. Signup sends no prior key. Every distinct mounted Track 2 UI operation above has a wrapper. The alternate detail route needs no second wrapper. The original JM API, admin provisioning, provider callbacks and Label Studio connector have separate callers. Browser image loads use the stored HTTPS URL directly and do not carry X-Api-Key. A remote image host receives a browser request when the image is viewed. DOM text and Markdown use React escaping, CSV page downloads use escapeFormulae, object URLs are revoked, and HealthReport's HTML iframe has an empty sandbox. These observations do not establish a script-injection finding.

## Error Handling Matrix (per screen)

Flags are the requested textual loading/error/catch/try scan, in that order. A busy label can exist even when “loading” is absent. 401 here means an invalid/missing key. Scoring trial expiry uses 402.

| Screen | Flags | Observed 401/500 or rejection path |
|---|---|---|
|AnnotatorProfiles|Y/Y/Y/N|Banner and spinner cleanup, but previous tenant/domain rows can remain under the error|
|Dashboard|Y/Y/Y/N|Main Promise.all rejects as a unit and displays ErrorBanner. IAA silently converts failure to empty data. Old metrics can stay visible|
|HealthReport|Y/Y/Y/Y|Public analyze/download errors set banner and clear busy. Initial report analysis clears preview. A 401 from a gateway is handled like other errors|
|ReviewCard|Y/Y/Y/Y|Core load failures show an error and can also say “Label not found”. 409 mutations reload. Guidelines errors become null; a failed post-save refetch is swallowed by load|
|ScoredQueue|Y/Y/Y/Y|Core fetch and bulk errors show banner. Autonomy failure empties filter options. Rows may outlive failed query|
|Settings|N/Y/Y/Y|Account/domain list errors clear summary/list and show banner. Resolve treats 404 as a new public name. Checkout catches failure. Guidelines GET failure becomes empty editable text|
|Signup|N/Y/Y/Y|Submit changes to “Creating account…”, disables button and catches 409/429 specifically. Other statuses surface message. Public operation|
|Upload|Y/Y/Y/Y|Report, sample seed, create task and ingest errors show banner. Progress for partially committed uploads can be misleading|

All eight screens have failure handling. Loading a whole route, updating one panel and performing a write have different failure paths. The presence of catch does not prove those paths preserve data identity.

## Console Error Risk Assessment

The requested .map/key heuristic flagged zero TSX files. The direct getElementById/querySelector heuristic flagged main.tsx (the React mount). The innerHTML/dangerouslySetInnerHTML scan flagged zero. Manual inspection adds the pair-key collision below, local range queries in NEREditor, copy fallback in Signup, download anchors in Queue/Health and html.classList in App. None of these DOM uses alone establishes an unsafe sink. There is a Suspense loading fallback for lazy Dashboard but no route error boundary to contain a chunk rejection or a malformed success payload.

**Effect inventory.** App:30/34 synchronize theme and credential events. Review:37/44/62/118 handle guidelines, route reset, load and keyboard listener. Queue:41/42/43/44/48/55/87/97 handle scope reset, bulk reset, focus reset, debounce, row pruning, autonomy, interval and keyboard. Dashboard:21/28 use live guards for separate metric requests. Settings:26/47 load guidelines and run account refresh/focus/poll with timer cleanup. AnnotatorProfiles:16 uses a live guard. HealthReport:15 analyzes the file from location.state; StrictMode can issue duplicate mount-time analyses. Signup/Upload have event-driven requests. CategorySelector:21 refreshes options without cancellation. ImageViewer:8 resets load state per URL. NEREditor:19/20 reset popup on text change and clean up the Escape listener. KeyboardShortcuts:10 and ShortcutsModal:13 remove listeners on cleanup. Remaining components have no useEffect. No self-sustaining render loop was found. Review deliberately reattaches its shortcut handler each render, so stale response ownership, rather than an old A/O/E closure, is the main issue there.

## CSS/Layout Issues

The requested TSX color regex matched **18 occurrences**: Dashboard 5, HealthReport 1, ReviewCard 1, NEREditor 2, NERViewer 8, TextViewer 1. All other TSX files had zero. Counts are occurrences including palette entries, not distinct colors. index.css uses hardcoded base colors, media queries and .dark overrides with a Tailwind custom dark variant. It lacks a shared semantic CSS-variable palette for these surfaces. The dark overrides for the read-only “Named entities” panel miss the editor's “Edit named entities” label.

Cards switch to single-column at 900px. Tables scroll within table-wrap and images use max-width:100%. The fixed 250px popup and bulk bar have the specific failures below. NER mouse selection on desktops is code-point aware. Touch selection via native handles has no dedicated completion handler. Mobile behavior is a static compatibility risk here, not a physical-device test result.

## Ranked Findings (P1 → P2 → P3)

Each finding gives the source location and function or selector (A), the body reviewed (B), a line-by-line state trace (C), and an exact deciding expression with the outcome (D). The heading supplies severity (E). There are 7 P1, 27 P2 and 14 P3 findings. Source quotes are exact excerpts from the cited line(s). Paths for TSX filenames resolve to frontend/src/screens, frontend/src/components or App.tsx as named.

#### P1.1 — A late detail response can verify a different label

**A/B.** `frontend/src/screens/ReviewCard.tsx:45` · `const load = useCallback(async () =>`. Body reviewed: load() [45–61].

**C/D.** 45–50: load one, then two under D. 44 resets the card. Two resolves first. 52: D equals D for the late one response. 54–58: item becomes one and loadedDomain stays D. 100–106: review at URL two verifies one. Deciding expression at `ReviewCard.tsx:52`: <code>if (currentDomain.current !== domainId) return</code>.

**Correction.** Key reads and writes to the route label, revision and credential. Ignore stale completion on every branch.

#### P1.2 — Changing the API key leaves the previous tenant’s data actionable

**A/B.** `frontend/src/App.tsx:21` · `export default function App() {`. Body reviewed: App() [21–70].

**C/D.** 50: replacing tenant A’s key with B’s keeps domain D. 41: descendants receive the same domain string. ReviewCard:61 does not refetch. api.ts:165–168 reads B on the next write. With matching public IDs, B’s label can receive a decision made from A’s data. After key removal the old detail can remain readable locally. Deciding expression at `App.tsx:41`: <code>value={{ domainId, setDomainId }}</code>.

**Correction.** Invalidate tenant-derived views and selections on any credential change. Require a fresh successful read before a write.

#### P1.3 — Approval drops unsaved spans and tags

**A/B.** `frontend/src/screens/ReviewCard.tsx:99` · `const submit = async (action: string) =>`. Body reviewed: submit(action: string) [99–117].

**C/D.** 63–66: draft differs from persisted content. 100–103: scored, idle, outcome selected. 106 posts verification, 108–110 leaves the editor. The unchanged server revision becomes verified and the visible edit is lost. Deciding expression at `ReviewCard.tsx:106`: <code>label_id: item.label_id, actual_action: action</code>.

**Correction.** Require save/discard before approval and shortcuts. Preserve the draft until the committed revision is known.

#### P1.4 — Old queue rows can be bulk-verified in the new domain

**A/B.** `frontend/src/screens/ScoredQueue.tsx:128` · `const submitBulk = async (action: 'approve' | 'reject') =>`. Body reviewed: refresh() [65–83], submitBulk(action) [128–139].

**C/D.** 42 clears selection on D1→D2. 67 only clears rows for an empty domain. 81 leaves D1 rows after a D2 failure. 161 permits selecting them. 129–133 pairs D1 IDs with D2. The mock recorded POST /v1/labels/beta/bulk-verify with alpha-label after the beta pending GET returned 500. In the real handler identical pending IDs in D2 can be changed; unmatched IDs return 404. Export can also misname D1 rows as D2 after failure. Deciding expression at `ScoredQueue.tsx:133`: <code>bulkVerify(domainId, { label_ids: ids, action })</code>.

**Correction.** Bind displayed rows to their full query and credential. Clear or disable row actions, shortcuts and export until that scope loads.

#### P1.5 — A guidelines save can overwrite instructions for another domain

**A/B.** `frontend/src/screens/Settings.tsx:12` · `export default function Settings() {`. Body reviewed: Settings() [12–61, 62–108].

**C/D.** 26–32: D1→D2 starts a read without clearing D1’s draft. 102 permits save with a nonempty D2 and configured key. 103 writes text from D1 to D2. Chromium recorded PUT /v1/domains/beta/guidelines carrying alpha rules while the beta GET was pending. On 401/500 line 30 instead installs an empty editable value. Overlapping saves are also unsequenced. Deciding expression at `Settings.tsx:103`: <code>putGuidelines(domainId, guidelines)</code>.

**Correction.** Represent loading, absent, failed and ready separately. Bind the editor and save result to domain/key and serialize saves.

#### P1.6 — One CSV import can write batches under two tenant keys

**A/B.** `frontend/src/screens/Upload.tsx:63` · `const startScoring = async () =>`. Body reviewed: startScoring() [63–74].

**C/D.** 67–70: chunk 1 commits with key A. While it runs, App:50 changes the key to B. The next request uses captured D but rereads the key at api.ts:165. If B can ingest into D, different tenants receive different chunks of one file. Deciding expression at `Upload.tsx:69`: <code>await ingestBatch({ domain_id: domainId, items: rows.slice(start, start</code>.

**Correction.** Pin upload ownership and stop remaining chunks on credential changes. Show the last committed range.

#### P1.7 — Bulk acceptance supplies a ground-truth outcome the reviewer never entered

**A/B.** `labeling_router.py:430` · `async def bulk_verify(request: Request, domain_id: str, payload: BulkVerifyRequest, session: Session, tenant: Tenant) -> dict:`. Body reviewed: bulk_verify(request, domain_id, payload, session, tenant) [430–474].

**C/D.** ScoredQueue:165 offers Approve All for a mixed selection. :133 submits one action with no independent outcome. Backend :468–473 keeps each recommendation and converts the button to a truth value. For a reject recommendation on an incorrect label, accepting the recommendation records correct=true. ReviewCard:144 explicitly distinguishes those facts. The recorded values feed learning and accuracy. Deciding expression at `labeling_router.py:471`: <code>verified_outcome=payload.action == "approve",</code>.

**Correction.** Collect an explicit ground-truth outcome with clear bulk semantics, or record a recommendation decision separately until an outcome is known.

#### P2.1 — Guidelines editing lacks the specified admin permission

**A/B.** `labeling_router.py:59` · `async def put_guidelines(domain_id: str, payload: GuidelinesPayload, tenant: Tenant, session: Session) -> GuidelinesPayload:`. Body reviewed: put_guidelines(domain_id, payload, tenant, session) [58–63].

**C/D.** Settings:101–103 offers save with any configured key. 59–61 resolves a tenant-owned domain; 62 writes with no editor/admin capability check. Same-tenant keys have equal write power. The prior admin-only editor requirement is unenforced; the existing credential model identifies tenants. Deciding expression at `labeling_router.py:62`: <code>domain.guidelines = payload.guidelines</code>.

**Correction.** Introduce an explicit write capability or document a single-owner contract. Enforce the chosen privilege on PUT and reflect it in Settings.

#### P2.2 — Drawing a span can block the category required to save it

**A/B.** `frontend/src/screens/ReviewCard.tsx:17` · `export default function ReviewCard() {`. Body reviewed: ReviewCard() [17–81, 82–147].

**C/D.** 138: a new task has text and no category, so the editor accepts a span. 63 becomes true. 68 rejects saving with no category; 140 hides the selector that could satisfy the prerequisite. Saving requires undoing the work. Deciding expression at `ReviewCard.tsx:140`: <code>!spansDirty &amp;&amp; !tagsDirty &amp;&amp; &lt;CategorySelector</code>.

**Correction.** Require classification before editing or allow atomic category-and-span save.

#### P2.3 — A refetch can overwrite edits made during save

**A/B.** `frontend/src/screens/ReviewCard.tsx:45` · `const load = useCallback(async () =>`. Body reviewed: load() [45–61], saveSpans()/saveTags() [67–98].

**C/D.** 71/87 sends draft A. 138–139 leave editors writable while busy. User makes draft B. 74/90 refetch; 55–56 replace B with stored A. If refetch fails, 60 swallows failure and 75/91 still show success with a stale revision. A 409 reload also replaces the user's buffer. Deciding expression at `ReviewCard.tsx:55`: <code>setEditedSpans(detail.content?.content_type</code>.

**Correction.** Freeze edits during commit or reconcile by draft generation. Distinguish successful write from successful reload.

#### P2.4 — Review shortcuts remain active in the NER popup

**A/B.** `frontend/src/screens/ReviewCard.tsx:119` · `const handler = (event: KeyboardEvent) =>`. Body reviewed: handler(event: KeyboardEvent) [119–127].

**C/D.** NEREditor:76 opens a popup without moving focus. ReviewCard:120–123 excludes text inputs and modifiers but accepts a mark, popup button or body. With outcome selected, A at 124 verifies while editing. O similarly submits when an override exists; E changes the status message. Deciding expression at `ReviewCard.tsx:124`: <code>void submit(item?.recommended_action ?? '')</code>.

**Correction.** Scope review shortcuts to the active review context and suspend them while an annotation dialog is open.

#### P2.5 — Completed requests can navigate away from the user’s new screen

**A/B.** `frontend/src/screens/ReviewCard.tsx:99` · `const submit = async (action: string) =>`. Body reviewed: submit(action: string) [99–117].

**C/D.** 106 awaits verification. The user moves to Settings or changes domain. 108 still uses the original pending list. 109–110 replace the new route on completion. Upload:28–29,58–60,69–72 have the same late-navigation problem; sample completion can additionally replace the active domain. Deciding expression at `ReviewCard.tsx:109`: <code>if (next) navigate(</code>.

**Correction.** Check current route and scope before applying completion side effects.

#### P2.6 — Category corrections inherit an earlier category’s verification

**A/B.** `labeling_router.py:577` · `async def relabel_item(domain_id: str, label_id: str, request: RelabelRequest, session: Session, tenant: Tenant) -> dict[str, str | None]:`. Body reviewed: relabel_item(domain_id, label_id, request, session, tenant) [577–650].

**C/D.** ReviewCard:138–140 makes verified spans and tags read-only but leaves category editing available. CategorySelector:31 relabels A→B. 628–633 copies A’s recommendation, confidence and verified outcome to B. The new category can appear already scored and verified without adjudication under B. Deciding expression at `labeling_router.py:632`: <code>verified_outcome=original.verified_outcome, verified_at=original.verified_at,</code>.

**Correction.** Define whether an edit is a correction of historical metadata or a new decision, then recompute/invalidate category-dependent fields or clearly expose their provenance.

#### P2.7 — An invalid selection can leave an earlier NER range active

**A/B.** `frontend/src/components/NEREditor.tsx:67` · `const selectionEnded = () =>`. Body reviewed: selectionEnded() [67–77], update(type) [78–88].

**C/D.** 76 stores valid range A. A second range B crosses a highlight. 73–74 returns, leaving popup A. 81–82 applies a chosen type to A while B is visibly selected. Escape at 21 closes the popup but leaves native selection intact; only update at 86 clears it. Deciding expression at `NEREditor.tsx:74`: <code>spans.some(span =&gt; start &lt; span.end &amp;&amp; end &gt; span.start)) return</code>.

**Correction.** Invalidate the prior popup on a new selection and clear native ranges when canceling.

#### P2.8 — Pointer input cannot reliably focus the custom entity field

**A/B.** `frontend/src/components/NEREditor.tsx:15` · `export default function NEREditor({ text, spans, entityTypes, onSpansChange, readOnly = false }: Props) {`. Body reviewed: NEREditor(props) [15–66, 67–110].

**C/D.** 94: empty type list. 106 renders a custom input. A pointer press inside it bubbles to 103, canceling native focus on mousedown. Typed characters may go to the page shortcut listener instead. Tab focus can still reach the input. Deciding expression at `NEREditor.tsx:103`: <code>onMouseDown={event =&gt; event.preventDefault()}</code>.

**Correction.** Exclude editable controls from selection-preserving mouse handling and explicitly focus the custom field.

#### P2.9 — Native touch and keyboard selection lack a create trigger

**A/B.** `frontend/src/components/NEREditor.tsx:15` · `export default function NEREditor({ text, spans, entityTypes, onSpansChange, readOnly = false }: Props) {`. Body reviewed: NEREditor(props) [15–66, 67–110].

**C/D.** A touch user adjusts native selection handles, or a keyboard user extends a selection. 99 only subscribes to mouseup, so paths without a synthesized mouseup never run 67–76. A nonempty range then has no create UI. Deciding expression at `NEREditor.tsx:99`: <code>onMouseUp={selectionEnded}</code>.

**Correction.** Handle native selection changes with a touch/keyboard-accessible commit action. Verify on physical mobile browsers.

#### P2.10 — Valid initial NER content can exceed the edit endpoint’s limit

**A/B.** `frontend/src/components/NEREditor.tsx:78` · `const update = (type: string) =>`. Body reviewed: update(type: string) [78–88].

**C/D.** 80–82 allows span 101. labeling_router.py:203 caps relabel at 100 while :240 permits up to 1000 on initial content. Editing a single type on an existing 101-span item sends all 101 and yields 422. The UI offers no explanation before save. Deciding expression at `NEREditor.tsx:81`: <code>onSpansChange([...spans, { start: popup.start, end: popup.end, label: ty</code>.

**Correction.** Align creation and editing limits and validate before accepting unsavable changes.

#### P2.11 — Queue focus drifts or falls outside the refreshed page

**A/B.** `frontend/src/screens/ScoredQueue.tsx:98` · `const onKey = (event: KeyboardEvent) =>`. Body reviewed: onKey(event: KeyboardEvent) [98–117].

**C/D.** 43 resets index on filter/pagination changes. A same-query poll at 89 replaces five rows with two. Index 4 survives, items.length is nonzero at 108; Enter at 115 navigates to /review/ with an empty ID. A reorder can instead open a different label. Deciding expression at `ScoredQueue.tsx:115`: <code>items[focusedRow]?.label_id ?? ''</code>.

**Correction.** Track focus by label ID and choose a valid visible fallback after refresh.

#### P2.12 — Bulk results hide actionable per-label skip reasons

**A/B.** `frontend/src/screens/ScoredQueue.tsx:128` · `const submitBulk = async (action: 'approve' | 'reject') =>`. Body reviewed: submitBulk(action) [128–139].

**C/D.** 133 receives a 200 with processed=0, skipped>0 and per-label quota/stale reasons. 135 reports counts only; 136 clears even the skipped rows. The reviewer cannot distinguish an exhausted cap from an already verified item. Deciding expression at `ScoredQueue.tsx:136`: <code>setSelected(new Set())</code>.

**Correction.** Surface skip reasons and retain still-actionable failures in the current scope.

#### P2.13 — Partial CSV commits have misleading progress and retry behavior

**A/B.** `frontend/src/screens/Upload.tsx:63` · `const startScoring = async () =>`. Body reviewed: startScoring() [63–74].

**C/D.** 63 captures progress=0. First batch commits and 70 schedules progress=100; next batch fails. 73 still reads 0 and omits the partial-commit context from the error, although the separate counter can show 100. Retrying restarts at row zero. api.ts:156 formats batch-local indices as CSV rows without file/header offset. Deciding expression at `Upload.tsx:70`: <code>setProgress(Math.min(start + 100, rows.length))</code>.

**Correction.** Track committed offsets in the operation itself, translate item indices to file rows and provide a safe resume point.

#### P2.14 — Concurrent drops can pair a report with a different file

**A/B.** `frontend/src/components/CsvDropzone.tsx:2` · `export default function CsvDropzone({ onFile, busy = false }: { onFile: (file: File) =>`. Body reviewed: CsvDropzone(props) [2–11].

**C/D.** The Choose button disables when busy; the drop handler at 6 still accepts B while A is pending. Upload:33–34 and HealthReport:14 replace file with B. A finishing last can pair A’s report with B’s name, scoring input or PDF download. Deciding expression at `CsvDropzone.tsx:6`: <code>accept(event.dataTransfer.files[0])</code>.

**Correction.** Gate all ingress when busy and validate response identity against the active file.

#### P2.15 — Non-JSON error bodies lose their HTTP error context

**A/B.** `frontend/src/api.ts:163` · `async function request<T>(path: string, init?: RequestInit, onResponse?: (response: Response) =>`. Body reviewed: request<T>(path, init?, onResponse?) [163–178].

**C/D.** A gateway sends non-JSON with status 502. 169 enters the error path. 171 consumes the body in json(), fails parsing and reads the consumed stream again. The second read rejects with TypeError; 172 never constructs ApiError with the original status. Deciding expression at `api.ts:171`: <code>catch { detail = await response.text() }</code>.

**Correction.** Read the body once and parse conditionally while preserving status.

#### P2.16 — Accepted label IDs containing a slash cannot be opened

**A/B.** `frontend/src/api.ts:212` · `export const getLabelDetail = (domainId: string, labelId: string) =>`. Body reviewed: getLabelDetail(domainId, labelId) [212]; id(value) [186].

**C/D.** labeling_router.py:89 accepts a nonempty ingest ID containing a slash. api.ts:186 encodes it as %2F, but the server’s decoded path now contains two segments. The single-segment route at labeling_router.py:757 cannot retrieve that label by this path. Deciding expression at `api.ts:212`: <code>/items/${id(labelId)}</code>.

**Correction.** Use a URL-safe immutable identifier for path operations or adopt consistent validation and support already-stored IDs.

#### P2.17 — A domain switch can retain old metrics, profiles or a busy spinner

**A/B.** `frontend/src/screens/Dashboard.tsx:13` · `export default function Dashboard() {`. Body reviewed: Dashboard() [13–end], AnnotatorProfiles() [8–end].

**C/D.** A has loaded. 29–33 fetch B without clearing A. On rejection the banner changes but A's metrics remain displayed under B. AnnotatorProfiles:17–19 does the same with identities. Clearing the domain during a load makes old finally skip, and the empty-domain branch leaves busy=true. Deciding expression at `Dashboard.tsx:33`: <code>if (live) setError(String(cause))</code>.

**Correction.** Reset scope-bound rows, errors and busy atomically when scope changes.

#### P2.18 — Panel read failures appear as insufficient data or absent guidelines

**A/B.** `frontend/src/screens/Dashboard.tsx:13` · `export default function Dashboard() {`. Body reviewed: Dashboard() [13–end], IAAPanel({ data }) [11–29].

**C/D.** 24 starts an asynchronous request. Before first success, or after 401/500 at 25, agreement is null. IAAPanel:14 uses the same training-data instruction as for a successful empty response. ReviewCard:40–41 similarly converts failed guidelines reads into unconfigured instructions. Deciding expression at `Dashboard.tsx:25`: <code>if (live) setAgreement(null)</code>.

**Correction.** Render separate loading, failed and confirmed-empty states with scoped retry.

#### P2.19 — Undefined agreement can appear as Excellent

**A/B.** `dashboard_router.py:140` · `def cohen_kappa(left: list[str], right: list[str]) -> float | None:`. Body reviewed: cohen_kappa(left, right) [140–147], agreement(request, domain, session) [152–177].

**C/D.** Two raters both use only X. 141 gives observed=1; 143 gives expected=1. 145–146 returns 1.0 for the undefined 0/0 coefficient. IAAPanel:16–18 labels it Excellent. At 174–176 multiple pairs are pooled by lexicographic rater side, so the overall coefficient may also depend on annotator naming. Deciding expression at `dashboard_router.py:146`: <code>return 1.0 if observed == 1 else None</code>.

**Correction.** Return null for undefined κ. Specify and label the multi-rater aggregate and its weighting.

#### P2.20 — A stale refresh can restore a cleared account

**A/B.** `frontend/src/screens/Settings.tsx:34` · `const refresh = useCallback(async () =>`. Body reviewed: refresh() [34–45], Settings() [12–61, 62–108].

**C/D.** 37 starts for A; 63–67 clears the key, then A’s delayed result at 38 restores the old account and domain list. Sidebar edits at App:50 also bypass Settings' configured/keyVersion updates. 39–42 can clear a pending checkout on tier match across accounts. Deciding expression at `Settings.tsx:38`: <code>setAccount(summary); setDomains(names); setError(null)</code>.

**Correction.** Bind refreshes and checkout state to the credential owner and ignore callbacks after clearing or changing keys.

#### P2.21 — Registration can activate a key after leaving signup

**A/B.** `frontend/src/screens/Signup.tsx:14` · `const submit = async (event: FormEvent) =>`. Body reviewed: submit(event: FormEvent) [14–28].

**C/D.** 19 awaits registration. User navigates away or saves a different credential. A late registration result still replaces the current key in browser storage at 20 and broadcasts it at 21, even though the key receipt screen is gone. Deciding expression at `Signup.tsx:20`: <code>localStorage.setItem('rgi-api-key', result.api_key)</code>.

**Correction.** Scope credential activation to a still-current registration flow and preserve a deliberate intervening key change.

#### P2.22 — Unexpected HTML succeeds as a typed JSON response

**A/B.** `frontend/src/api.ts:163` · `async function request<T>(path: string, init?: RequestInit, onResponse?: (response: Response) =>`. Body reviewed: request<T>(path, init?, onResponse?) [163–178].

**C/D.** A JSON endpoint receives 200 text/html from a fallback page. 169 accepts the status and 176 fulfills the typed request with a string. Settings:95–96 treats an account string as a summary and accesses usage fields during render. App:56 has no render error boundary. Deciding expression at `api.ts:176`: <code>return await response.text() as T</code>.

**Correction.** Declare expected media type per operation, reject unexpected success bodies before setting state and contain route rendering failures.

#### P2.23 — The bulk action bar can cover the sidebar

**A/B.** `frontend/src/index.css:44` · `.bulk-action-bar`. Body reviewed: .bulk-action-bar [40–44]; responsive sidebar [46–48].

**C/D.** At 720 CSS px the sidebar remains 212px wide (47), but 44 starts the fixed bulk control at x=18. At ≤650 the opened drawer has z-index 20 while the action bar remains at 30 (40,48). The bar can obscure navigation and rows. Deciding expression at `index.css:44`: <code>left:18px; right:18px</code>.

**Correction.** Anchor the bar to the content column and coordinate modal/drawer stacking and bottom scroll padding.

#### P2.24 — Dark-mode text can become unreadable

**A/B.** `frontend/src/index.css:77` · `dark theme selectors`. Body reviewed: dark theme selectors [58–80]; NEREditor(props) [15–66, 67–110].

**C/D.** NEREditor:96 uses Edit named entities. 77 matches only the read-only viewer, so :100’s pale surface inherits light text. Popup type buttons combine light inline fills with light foreground at :75. Base .page h1 and .section-title at :46 retain dark text on dark surfaces. Deciding expression at `index.css:77`: <code>[aria-label="Named entities"] .card-pad</code>.

**Correction.** Give headings, editor text and palette chips explicit foreground/background pairs. Verify computed contrast in both themes.

#### P2.25 — Help dialog focus escapes into the background

**A/B.** `frontend/src/components/ShortcutsModal.tsx:11` · `export default function ShortcutsModal({ onClose }: { onClose: () =>`. Body reviewed: ShortcutsModal({ onClose }) [11–34].

**C/D.** 14 moves focus on open. 15–19 only implements Escape. Tabbing past Close can enter the underlying sidebar; it remains interactive despite aria-modal at 24. Closing never restores the invoking focus. Deciding expression at `ShortcutsModal.tsx:14`: <code>dialog.current?.focus()</code>.

**Correction.** Contain focus while open, make the background inert and restore focus on close.

#### P2.26 — Category and verification writes can race

**A/B.** `frontend/src/components/CategorySelector.tsx:26` · `const submit = async () =>`. Body reviewed: submit() [26–38].

**C/D.** 29 sets only the selector’s busy flag. ReviewCard:102 still sees its own busy=false. If the reviewer verifies while the category request is pending, verify can commit first. The category write then sees the same revision UUID (verification does not change it), and labeling_router.py:632 copies verification to the new category. In reverse order, verify receives 409. Deciding expression at `CategorySelector.tsx:31`: <code>await relabelItem(domainId, labelId,</code>.

**Correction.** Coordinate mutation ownership across category, content and verification actions and recheck verification state before relabel.

#### P2.27 — Unclassified tasks disappear from the searchable workflow

**A/B.** `labeling_router.py:655` · `async def pending(request: Request, domain_id: str, response: Response, session: Session, tenant: Tenant, category: str | None = None, limit: int = Query(default=50, ge=1, le=200),`. Body reviewed: pending(request, domain_id, response, session, tenant, …) [655–694].

**C/D.** Upload:28–29 creates a task without category and opens it by known ID. :573 returns pending_classification, so scored_at is null. Leaving before classification hides it from the only Queue listing at :665, even when searching by its exact ID. A direct review URL still works. Deciding expression at `labeling_router.py:665`: <code>LabelLog.verified_at.is_(None), LabelLog.scored_at.is_not(None),</code>.

**Correction.** Provide a list/filter for tasks awaiting classification and link it from the upload and queue screens.

#### P3.1 — The entity popup can extend beyond the viewport

**A/B.** `frontend/src/components/NEREditor.tsx:15` · `export default function NEREditor({ text, spans, entityTypes, onSpansChange, readOnly = false }: Props) {`. Body reviewed: NEREditor(props) [15–66, 67–110].

**C/D.** A popup tall enough to exceed 130px is placed near the bottom using a guessed height at 102. If width<260 or height<130 even the resulting top/left can be negative. No scroll/resize measurement repositions it. Deciding expression at `NEREditor.tsx:102`: <code>window.innerHeight - 130</code>.

**Correction.** Clamp using the measured popup dimensions and constrain overflow to the viewport.

#### P3.2 — An inferred OS theme becomes a permanent user override

**A/B.** `frontend/src/App.tsx:21` · `export default function App() {`. Body reviewed: App() [21–70].

**C/D.** 26–28 reads OS dark when no preference exists. 30–33 immediately persists dark without a toggle. Later OS changes, including across reloads, have no effect because the stored value wins. Deciding expression at `App.tsx:32`: <code>localStorage.setItem('dlj-theme', theme)</code>.

**Correction.** Persist explicit overrides only and subscribe to OS preference while using the default.

#### P3.3 — Two annotator pairs can share a React key

**A/B.** `frontend/src/components/IAAPanel.tsx:11` · `export default function IAAPanel({ data }: { data: AgreementResponse | null }) {`. Body reviewed: IAAPanel({ data }) [11–29].

**C/D.** Distinct valid ordered pairs (a,bc) and (ab,c) both produce key abc at 22. React warns about duplicate sibling keys and can reuse the wrong row when the list changes. Deciding expression at `IAAPanel.tsx:22`: <code>key={pair.annotator_a + pair.annotator_b}</code>.

**Correction.** Use an unambiguous tuple encoding.

#### P3.4 — The navigation prefix can outlive its timeout

**A/B.** `frontend/src/components/KeyboardShortcuts.tsx:5` · `export default function KeyboardShortcuts() {`. Body reviewed: KeyboardShortcuts() [5–51].

**C/D.** 42–44 receives g and arms waiting. Open help with ? before expiry; 24–27 changes open without clearing waiting. Cleanup 48 cancels its reset timer. After closing help, a later q can navigate long after the one-second window. Deciding expression at `KeyboardShortcuts.tsx:48`: <code>window.clearTimeout(timer.current)</code>.

**Correction.** Reset the prefix on effect cleanup, route and dialog transitions.

#### P3.5 — A failed clipboard fallback can leave a hidden key field

**A/B.** `frontend/src/screens/Signup.tsx:29` · `const copy = async () =>`. Body reviewed: copy() [29–42].

**C/D.** Clipboard API rejects. 34–36 creates and selects a temporary textarea containing the key. If the fallback call itself throws at 37, line 38 never removes it and the click promise rejects. The false-return path is handled. Deciding expression at `Signup.tsx:37`: <code>const worked = document.execCommand('copy')</code>.

**Correction.** Use finally for cleanup and present the existing manual-copy message on either failure.

#### P3.6 — A supporting API failure is presented as a missing label

**A/B.** `frontend/src/screens/ReviewCard.tsx:45` · `const load = useCallback(async () =>`. Body reviewed: load() [45–61].

**C/D.** 49–50: detail succeeds but supporting pending/autonomy fails. 53–59 never install the valid item. 60 sets a banner; 135–145 can simultaneously describe it as not found. A guide fetch for another domain also leaves the last guide visible until resolved. Deciding expression at `ReviewCard.tsx:49`: <code>const [detail, rows, autonomy] = await Promise.all([</code>.

**Correction.** Separate essential detail from secondary data and reflect the actual failure reason.

#### P3.7 — Escalation is advertised without an implemented action

**A/B.** `frontend/src/screens/ReviewCard.tsx:119` · `const handler = (event: KeyboardEvent) =>`. Body reviewed: handler(event) [119–127].

**C/D.** Press E or click Escalate on a scored item. 126/144 updates only the message and leaves the item pending. ShortcutsModal:8 advertises Escalate as an action. There is no escalation request. Deciding expression at `ReviewCard.tsx:126`: <code>Escalation needs a configured backend action.</code>.

**Correction.** Describe the placeholder as unavailable or connect a supported escalation action.

#### P3.8 — Omitted content can crash a version-skewed review client

**A/B.** `frontend/src/screens/ReviewCard.tsx:17` · `export default function ReviewCard() {`. Body reviewed: ReviewCard() [17–81, 82–147].

**C/D.** With non-null text and a legacy/malformed response omitting content, the first comparison at 138 is false and the second dereferences undefined. Null from the current server at labeling_router.py:778 works. A present unsupported type with text takes the generic text path; supported images take ImageViewer. Deciding expression at `ReviewCard.tsx:138`: <code>item.content === null || item.content.content_type</code>.

**Correction.** Normalize optional content at the API boundary and handle unknown types without losing the rest of the review.

#### P3.9 — The health report message type omits a valid null value

**A/B.** `frontend/src/api.ts:132` · `export interface HealthReport {`. Body reviewed: HealthReport interface [132–144]; uploadForAnalysis(file) [188].

**C/D.** label_health/analyze.py:78 can emit message=null. api.ts accepts the parsed body without validation but types this member as absent or string. No current Upload rendering path dereferences it, so the mismatch is latent. Deciding expression at `api.ts:143`: <code>message?: string</code>.

**Correction.** Include null in the response type and keep API contract fixtures for ordinary and empty analyses.

#### P3.10 — Unicode tag limits differ between client and server

**A/B.** `frontend/src/components/TagSelector.tsx:17` · `const add = (value: string) =>`. Body reviewed: add(value: string) [17–22].

**C/D.** Browser String.length counts UTF-16 units. A tag of 30 astral characters has length 60 at 19; input maxLength also clips at 50 units. labeling_router.py:222 uses Python code-point length and accepts that tag. Locale lowercase and server casefold also differ for deduplication. Deciding expression at `TagSelector.tsx:19`: <code>tag.length &gt; 50</code>.

**Correction.** Use one documented measure for code-point length and normalize deduplication consistently.

#### P3.11 — Keyboard and pointer sorting behave differently in profiles

**A/B.** `frontend/src/screens/AnnotatorProfiles.tsx:23` · `const header = (key: Key, label: string) =>`. Body reviewed: header(key: Key, label: string) [23].

**C/D.** For a new column, mouse activation at 23 sets both sort and the per-column default direction; Enter updates only sort. Starting with Total descending and moving to Annotator produces opposite order by keyboard. The expandable rows at 25 have click only. Deciding expression at `AnnotatorProfiles.tsx:23`: <code>else setSort(key)</code>.

**Correction.** Share one header activation handler and expose expansion through focusable controls.

#### P3.12 — Late bulk feedback can appear in a different domain

**A/B.** `frontend/src/screens/ScoredQueue.tsx:128` · `const submitBulk = async (action: 'approve' | 'reject') =>`. Body reviewed: submitBulk(action) [128–139].

**C/D.** 133 starts bulk verification in A. On navigation to B, only the success path at 134 checks domain. A late rejection at 138 appears in B. A prior success toast at 135 also survives the filter/domain reset at 41–43. Deciding expression at `ScoredQueue.tsx:138`: <code>catch (cause) { setError(String(cause)) }</code>.

**Correction.** Associate bulk messages and busy state with the originating scope.

#### P3.13 — A real category can collide with the create-new option

**A/B.** `frontend/src/components/CategorySelector.tsx:26` · `const submit = async () =>`. Body reviewed: submit() [26–38].

**C/D.** The identifier validators accept a literal category named __new__. :42–43 renders it with the same value as the new-category option. :27 treats it as a request to use custom instead; choosing that existing option cannot select its real value. At :21–25 changing revision also retains previous custom input. Deciding expression at `CategorySelector.tsx:27`: <code>selected === '__new__' ? custom.trim() : selected.trim()</code>.

**Correction.** Keep the create-new mode separate from user-supplied category values and clear revision-specific draft state.

#### P3.14 — Short mobile drawers can hide the final navigation controls

**A/B.** `frontend/src/index.css:46` · `.sidebar`. Body reviewed: .sidebar [46–48].

**C/D.** 46 fixes the sidebar to viewport height with vertically stacked controls and no overflow-y handling. 48 makes it fixed on small screens. At short heights, keyboard zoom or landscape phone sizes, the footer and last navigation entries can fall below the accessible portion of the drawer. Deciding expression at `index.css:46`: <code>top:0; height:100vh</code>.

**Correction.** Allow the sidebar contents to scroll independently.
