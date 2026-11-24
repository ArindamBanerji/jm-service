# DLJ frontend re-sweep after the Track 2 fixes

**24 November 2026 · jm-service · Git HEAD `b2dd90c`**

| Audit result | Outcome |
|---|---|
| Components analyzed | 27 React components: App, 8 screens, 18 child components. Also reviewed entrypoint, domain context, CSS, API/CSV helpers, build/deployment configuration, backend handlers, both prior documents and all seven Playwright specs. |
| Current findings | **7 P1 · 26 P2 · 8 P3** (41 distinct findings). Each has one home in the dimension tables. |
| Fix verification, IDs in the brief | **8 CLOSED · 1 PARTIAL · 0 OPEN · 0 REGRESSED** across nine requested labels. Three labels describe the same detail-read bug. |
| Fix verification, original report IDs | **5 CLOSED · 1 PARTIAL · 3 OPEN · 0 REGRESSED** across the original seven P1s and two P2s. See the crosswalk in dimension 1. |
| Track 2 feature groups | **1 COMPLETE · 10 PARTIAL · 0 BROKEN** across the eleven groups defined in dimension 4. |
| Executed checks | Frontend type-check and temporary production build passed. Playwright **59/62 passed**, including **4/4 fix_state** and **20/21 track2**. |

### Five highest-risk items

1. **A clean Git deployment can boot without any frontend bundles (S7.1).** The Docker image copies the distribution directory; its JS and CSS assets are absent from Git. Local browser success masks a blank production entrypoint on that deployment path.
2. **One CSV upload can send data to two accounts (S1.2).** A browser probe captured two batches from the same synthetic file with different fixture keys after the user navigated to Signup and changed the credential.
3. **Bulk review records correctness that the reviewer never supplied (S1.3).** The server derives truth from accepting/inverting a recommendation. Single review treats the action and the known label outcome as independent facts.
4. **A changed queue filter can still act on the previous query's IDs (S2.2).** With the new search held pending, Chromium submitted the previous selection to the bulk endpoint.
5. **Saving an annotation can discard the next edit (S2.1).** Chromium showed a newly added tag before the first save settled, then removed it when the successful save refreshed the item.

**Evidence boundary.** Source references below are relative to jm-service. Unqualified screen/component filenames live in frontend/src/screens and frontend/src/components; App.tsx, api.ts, main.tsx and index.css live directly in frontend/src. The running local frontend referenced the same entry JS and CSS hashes as the temporary build. UI write probes used intercepted requests and synthetic values. Server consequences were traced to handlers. Deployment review used Git contents, build outputs and Docker/Railway config; it did not exercise a remote deployment or physical touch device. The pre-existing working-tree change to frontend/dist/index.html was preserved.

## 1. Fix verification

The stale detail response, dirty approval, queue domain switch and guidelines overwrite fixes hold on their named paths. The earlier report and the fix brief assign several IDs to different defects. Both sets of IDs are reconciled below, since counting the repeated detail race as three closures hides outstanding data-integrity issues.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S1.1 | P1 | App.tsx:42; Signup.tsx:20,45 | Signup bypasses the full credential reset, including on an external storage event. | Replacing or clearing the active key on the receipt screen leaves the previous key displayed and copyable, and retains checkout-pending state. A registration resolving after leaving Signup can also activate its key after the user has chosen another account. |
| S1.2 | P1 | Upload.tsx:63–73; api.ts:165; App.tsx:42 | The import continues after Upload unmounts and reads the credential once per 100-row request. | Confirmed with 200 synthetic rows: held batch one, opened Signup, committed fixture B, released batch one. Chromium sent the first batch with fixture A and the second with fixture B, both to the captured public domain. The server would legitimately authorize each request separately. |
| S1.3 | P1 | ScoredQueue.tsx:146,178; labeling_router.py:483–490 | Bulk approval accepts the recommendation and supplies a ground-truth boolean from the button alone. | Accepting a recommended rejection of an incorrect label writes verified_outcome=true. The same reviewer using the single-card workflow can record action=reject and outcome=false. This contaminates learning and accuracy even when every ID selected was intended. |

**Requested fix labels.** Each of the nine IDs has one verdict. Three labels describe the same late-read path.

| Brief ID | Verdict | Trace and evidence |
|---|---|---|
| P1.1 | CLOSED | ReviewCard:47–72 aborts the previous controller before allocating a new one. Its signal travels through detail/pending/autonomy to fetch. Success, catch and finally check abort and route identity. Effect cleanup aborts on either route parameter change or unmount. fix_state:36 delays A until B renders. |
| P1.2 | CLOSED | ReviewCard:73–77 compares both drafts with server values, 116 guards submission, 140–143 guards A/O/E, and 162–168 supplies unsaved status, disabled controls and title. fix_state:111 exercises NER. In-flight editing is a separate failure, S2.1. |
| P1.3 | CLOSED | ReviewCard:19,58–60,113–121,159 uses useParams, redirects a superseded detail to the returned canonical ID, checks item/URL/domain equality and sends the URL ID on verify. |
| P1.4 | CLOSED | ScoredQueue:21–23 suppresses old rows in the render that receives the new domain. Its effect at 43–49 then clears stored rows and selection. 81,89–95 rejects stale success/failure and empties on current failure. 142/178 guard the bulk action. fix_state:61 passes. Same-domain query changes are covered in S2.2. |
| P1.5 | CLOSED | Settings:29–55 aborts the old GET and binds the editor to the successful read's domain. 125–127 shows empty text and disables save until the matching GET succeeds. Failed reads keep the save guard closed. fix_state:86 passes. |
| P1.6 | PARTIAL | App:37–60 handles same-tab commit and cross-tab storage, removes domain/checkout and reloads Upload for ordinary routes. The Signup exception preserves receipt state and can let work in an unmounted screen finish. See S1.1–2. |
| P1.7 | CLOSED | Same stale-detail condition as brief P1.1. The original report's P1.7 is a different, open bulk-verification defect. |
| P2.19 | CLOSED | Same late-read fix and browser test as brief P1.1. Old mutation callbacks are examined separately in dimension 2. |
| P2.20 | CLOSED | api.ts:169–178 checks status, parses a clone, prefers detail then error and reads the original body as text on parse failure. ApiError retains status. Remaining success-body and nested-error issues are in dimension 3. |

**Original report crosswalk.** The actual seven P1 titles at dlj_sweep_2_frontend_lifecycle.md:113–167 map to stale detail **CLOSED**, credential change **PARTIAL**, dirty approval **CLOSED**, queue domain switch **CLOSED**, guidelines overwrite **CLOSED**, cross-key import **OPEN**, and inferred bulk outcome **OPEN**. Original P2.19 (undefined agreement shown as Excellent) is **OPEN** at dashboard_router.py:145–146. Original P2.20 (stale account refresh after key clear) is **CLOSED** on the ordinary Settings key-clear path because a document reload discards the old component. Same-account competing polls still have no generation check. Thus the original nine score **5 CLOSED, 1 PARTIAL, 3 OPEN, 0 REGRESSED**. The headline/session score uses the brief's nine labels.

## 2. Component state and request ownership

The review GET pipeline now checks the route at completion. Several write callbacks, file analyses and account refreshes still apply to whichever screen or draft happens to be visible when they finish.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S2.1 | P1 | ReviewCard.tsx:64–65,78–110,162–163 | Spans and tags remain editable while Save is pending; refetch or revision navigation replaces the draft. | Confirmed in Chromium: added a second tag during save, saw its Remove button, released the response and watched the tag disappear under “Tags saved.” A slow 409/refetch can discard a buffer as well. Dirty state inhibits A/O/E only; changing the domain or following a sidebar/global shortcut discards the draft without confirmation. |
| S2.2 | P1 | ScoredQueue.tsx:23,49,73–88,117–121,141–149,174 | Actionability is keyed to domain alone. Previous rows remain selectable during same-domain search, sort or page changes. | Confirmed: with a no-match search pending, checked the previous row and clicked Approve All. The intercepted POST contained that old row. A valid server would record the action; the new query need never return that row. |
| S2.3 | P2 | ReviewCard.tsx:89–93,106–110,122–132,151–153; CategorySelector.tsx:31–36 | Mutations have no common route-generation or mounted owner. An old 409 calls its captured load, which aborts the current controller. | A failure for A can cancel B's detail read, change B's busy/error state, or destroy B's draft. After unmount the route ref freezes, so an old success can still navigate from another screen. Category and verify also have independent busy flags. |
| S2.4 | P2 | Dashboard.tsx:21–38; AnnotatorProfiles.tsx:16–25 | A live flag guards late results but does not remove already-displayed data when moving between nonempty domains. | On B's slow or failed request A's metrics/annotator names remain under B. Clearing the domain mid-request can strand the spinner because the old finally is ignored. |
| S2.5 | P2 | Upload.tsx:32–34,63–73; CsvDropzone.tsx:5–9; HealthReport.tsx:14–24 | Drag/drop bypasses busy and file results have no identity check. Batch progress in catch is captured at operation start. | A late analysis of file A can accompany B's filename, scoring input or PDF. Retrying a partially committed import starts at row zero and can stop on duplicates. |
| S2.6 | P2 | Settings.tsx:51–55,58–78,93–115,122–127 | Account reads, domain resolution and checkout lack a latest-operation guard. The guidelines textarea stays editable during PUT. | An old focus/poll failure can clear a newer account or unrelated error; successive domain choices can resolve in reverse order. A late checkout can redirect after leaving Settings. A successful PUT can mark subsequently edited text as saved. |
| S2.7 | P2 | ScoredQueue.tsx:50,100–103,126–128,147–151 | Keyboard focus is a row index, and bulk error/finally handlers have no domain guard. | After polling reorders/shrinks a page, Enter opens a different ID or /review/. An old bulk error can appear in the next domain. |
| S2.8 | P2 | ReviewCard.tsx:54–70,156–169; Dashboard.tsx:24–25 | Optional data failures collapse into a missing item, absent guidelines or insufficient agreement data. | One failed supporting pending/autonomy GET hides a valid label. A failed guidelines GET appears unconfigured; an IAA outage prompts staff to collect more labels. |
| S2.9 | P3 | CategorySelector.tsx:21–27; NEREditor.tsx:19–24; KeyboardShortcuts.tsx:29–49 | Several local drafts and timers outlive the interaction that created them. | Category requests can resolve out of order and custom text survives a revision. Help opened immediately after g cancels the prefix timeout without clearing waiting; a later q can navigate unexpectedly. |

**Inventory.** Initial state, update triggers, cleanup and domain ownership were traced for App, eight screens and all eighteen child component files. “Live” below means a cleanup flag rejects callbacks; it does not cancel transport.

| Screen or component | Lifecycle, dependencies, concurrency and reset |
|---|---|
| App | Reads domain/key/theme on mount. Storage/custom key listeners are replaced on pathname and removed on unmount. Sidebar editing commits on blur/Enter. Domain text changes on each keystroke. The domain provider carries no credential generation. S1.1–2 and S6.2 cover exceptions. |
| ReviewCard | Fourteen local state slots plus currentRoute/loadController. Resets item, outcome, overrides, lists and drafts on route change; render guards both IDs. Guidelines have a separate abortable domain effect. Window shortcuts rebind on each render using current drafts. GET guards do not extend to every write continuation. |
| ScoredQueue | Initial rows/selection empty; effects at 43–70 reset state, debounce 300 ms with clearTimeout, prune missing IDs, and guard autonomy with live. Pending uses generation and a 30 s interval cleaned on change; requests themselves are not aborted. Bulk snapshots IDs, refreshes through a ref on success, reports counts and clears selection. Domain masking works; query ownership and index focus are incomplete. |
| Settings | Domain-guideline fetch uses abort; byte limit and readiness are checked. Account refresh starts at mount, focus and during a bounded checkout poll; timers/listeners clean up. Refresh, resolve and checkout can overlap. domainName is initialized once and can diverge from the sidebar. |
| Dashboard | Independent domain-scoped live guards for IAA and a Promise.all of overview/corrections/compounding. No transport abort; no overlap from polling. Earlier content remains on scope change. |
| AnnotatorProfiles | Domain-dependent live guard. Sort and expanded annotator are component-local. Existing rows, expansion and errors can carry into the next domain. |
| Upload | Event-driven task creation, report analysis, fixture fetch, sample scoring and sequential batch ingestion. Shared busy flag disables ordinary buttons. Domain/key, selected file and mounted route are not pinned through completion. A completed sample also sets global domain. |
| HealthReport | Route-state file triggers analysis; StrictMode can issue duplicate development reads. File and HTML are independent slots. PDF download revokes its object URL after one second; it can complete after navigation. |
| Signup | Submit checks busy, validates email through the native form, persists one-time key and dispatches an event. No cancellation or owner check on registration; clipboard rejection enters a DOM fallback whose cleanup only follows a successful return from execCommand. |
| CategorySelector | Resets choice/saved/error on domain, label, revision or category. Autonomy GET has no abort/live guard; custom input persists. Child-owned busy does not serialize parent verify. Parent callback closes over old route/load. |
| NEREditor / NERViewer | Editor local popup/custom type reset on text and revision-key remount; Escape listener cleans up. Parent owns spans. Viewer derives ordered ranges from props without async state. An invalid second selection leaves the previous popup range active. |
| TagSelector / ImageViewer | Parent owns tags; revision key clears local input/suggestions after reload. No async tag work in child. Image state resets on URL, then native load/error sets the display; broken images show an alert. |
| KeyboardShortcuts / ShortcutsModal | Global capture listener and one-second prefix timer clean up on navigation/open changes. Modal focuses a div, registers Escape and removes its listener. Its inline onClose prop can cause refocus on a parent render. |
| CsvDropzone / SignupBanner | Dropzone owns drag state/file ref; drop is active during busy. Banner reads the effective key on render and holds no cache. |
| GuidelinesPanel / IAAPanel | Pure renderers of nullable props. Markdown subset builds escaped React nodes. IAAPanel's concatenated pair key can collide for pairs such as (a,bc) and (ab,c). |
| TextViewer / FactorBar / ConfidenceIndicator / TierBadge / MetricCard / LoadingSpinner / ErrorBanner | Presentational functions with no effects, timers, async operations or cross-domain storage. Callers own data and visibility. Spinner and banner have status/alert semantics. |

## 3. API contracts and errors

All 28 network wrappers map to mounted FastAPI operations. The shared client preserves status and plain-text diagnostics on non-2xx responses, but a successful response is trusted solely on its MIME type and a TypeScript assertion.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S3.1 | P1 | api.ts:180–183; Settings.tsx:119–120; App.tsx:77 | A 200 HTML body for a JSON operation resolves as a string cast to the requested DTO. | A fallback/proxy page returned from /account becomes a truthy account, then rendering dereferences account.usage. A bad dashboard payload or rejected lazy chunk can likewise take down the route tree; Suspense provides no error boundary. |
| S3.2 | P2 | api.ts:151–160,168–178; Upload.tsx:68–73 | Validation detail is flattened to text; indexed batch errors omit the chunk base and CSV header. Fetch has no general timeout. | A server error on the first item of the second chunk is described as CSV row 1. Most screens stringify transport failures; a stalled request can hold busy indefinitely. |
| S3.3 | P2 | api.ts:192,218–221; labeling_router.py:89–92,788 | Ingest permits slash-containing label IDs. Encoding the string does not make it one segment after ASGI path decoding. | A successfully ingested label can be listed but its item/detail, content and relabel endpoints can return 404. Use a URL-safe stable identifier or align validation and support existing IDs. |
| S3.4 | P3 | api.ts:68–82,132–143,219; label_health/analyze.py:78 | Wire types omit a valid null message and reuse the full response content shape for creation. | Callers are told a health message is a string when present although null is returned, and must supply unrelated defaultable fields to create typed content. The build cannot detect server drift. |

**Contract ledger.** Paths have the /v1 prefix. D and L are encoded public domain and label IDs. Each row names the actual call, inputs, server definition and success representation. Unless indicated, request and response field names agree; unused wrappers still resolve to real routes.

| api.ts function and line | Method, path and input | Server and decoded result |
|---|---|---|
| uploadForAnalysis 194 | POST /label-health/analyze, multipart file | label_health/api.py:71 → JSON HealthReport (nullable message caveat) |
| uploadForReport 195 | POST /label-health/report, multipart file | same module:76 → HTML text for sandboxed iframe |
| downloadReportPdf 196 | POST /label-health/report/pdf, multipart file | :81 → PDF Blob |
| ingestLabel 197 | POST /labels/ingest, domain_id, label_id, category, factors, optional text/annotator_id | labeling_router.py:379 → scored IngestResponse |
| ingestBatch 198 | POST /labels/ingest/batch, domain_id/items | :494 → results/batch_size, 1–100 items per request |
| seedSample 199 | POST /labels/D/sample, no body | :519 → domain_id/created/existing/pending |
| registerAccount 202 | POST /auth/register, email/optional name | auth.py:47 → 201 key/tenant/tier/message |
| verifyLabel 203 | POST /labels/verify, domain_id/label_id/actual_action/verified_outcome | labeling_router.py:393 → VerifyResponse; optional server reason/annotator are unavailable in the wrapper |
| bulkVerify 205 | POST /labels/D/bulk-verify, label_ids/action/optional reason | :439 → processed/skipped/errors, including partial success with HTTP 200 |
| getPending 208 / getPendingPage 209 | GET /labels/D/pending, optional category/limit/offset/sort_by/sort_order/search | :684 → bare row array. Only the page wrapper requires integer X-Total-Count and returns rows/total. jm_service.py:304 exposes the header. Only the first wrapper accepts a signal. |
| getLabelDetail 218 | GET /labels/D/items/L | :788 → current LabelDetail, nullable source/content, revision UUID and canonical label ID |
| createLabelContent 219 | POST /labels/D/items/L/content, content_type/spans/tags/image_url | :745 → 201 label_id/content_type plus appropriate count |
| createTextTask 220 | POST /labels/D/tasks, label_id/text/optional category | :563 → 201 label_id/status/category |
| relabelItem 221 | POST /labels/D/items/L/relabel, category/idempotency_token and optional spans OR tags | :603,680 → requested label_id, successor revision_id, category/previous_category. The subsequent detail GET resolves the successor. Empty arrays clear edits. |
| getOverview 222 | GET /dashboard/D/overview | dashboard_router.py:211 → counts, accuracy, category tiers/inversion and curve |
| getCorrections 223 | GET /dashboard/D/corrections | :234 → rate/count/patterns/top_pattern |
| getAnnotators 224 | GET /dashboard/D/annotators, limit | :258 → domain_id/annotators |
| getFactors 225 | GET /dashboard/D/factors | :296 → names/inversion/factor_stats |
| getCompounding 226 | GET /dashboard/D/compounding, window/category | :320 → points/baseline/current accuracy/improvement |
| getAutonomy 227 | GET /domains/D/autonomy | labeling_router.py:814 → domain_id/categories/overall_tier |
| getAgreement 233 | GET /dashboard/D/iaa | dashboard_router.py:150 → nullable overall and pairwise kappa plus overlap counts |
| getGuidelines 234 / putGuidelines 235 | GET or PUT /domains/D/guidelines; PUT JSON guidelines | labeling_router.py:54,60 → nullable guidelines; PUT allows 10 KiB UTF-8 |
| getAccount 244 / getAccountDomains 245 | GET /account or /account/domains | account.py:26,54 → one account/usage summary or an array of public-name records |
| resolveAccountDomain 246 | POST /account/domains/resolve, domain_id | account.py:73 → public_domain_id |
| getCheckoutUrl 247 | GET /billing/checkout-url, tier | billing.py:59 → checkout_url/tier; server creates the provider checkout |

**Other functions.** ApiError.constructor:148 stores status; explain:151 recursively formats string/list, indexed errors and message/msg; request:163 adds X-Api-Key to protected calls and decodes responses; json:185 creates POST JSON; upload:186 sets FormData; params:187 uses URLSearchParams; id:192 encodes a segment. hasApiKey:200 is the 29th exported function and makes no request. No frontend/src/types.ts exists. Types live in api.ts. No explicit `as any` cast was found in frontend/src. Assertions on parsed fetch bodies, sample fixtures, form values and route state still require runtime invariants.

**Error path.** On 401/404/409/422/429/5xx the client checks ok first. FastAPI string detail, arrays of Pydantic msg, nested quota message and SlowAPI error strings reach ApiError. Plain HTML/text failures use the original response body safely. JSON with only a top-level message is stringified as an object; detail objects with only an unknown code become “Request failed.” An empty body can produce a blank error message. DNS/refused connections reject fetch directly without an HTTP status. Review reloads on 409, Signup distinguishes 409/429, Settings treats a resolve 404 as a new domain; ordinary catches feed ErrorBanner. Guidelines/IAA/queue autonomy have the special fallback paths in dimensions 1–2. Missing credentials omit the header; the server returns 401 on protected operations. Only health-report operations and registration deliberately omit it. No credentials are supplied to third-party image hosts.

**Routes outside the client.** The legacy GET /labels/D/L is an alias. No wrapper is needed for a second route to the same detail. The legacy JM register, domain create/list, score, learn, diagnostics and state APIs, health readiness, admin key issuance, Paddle webhook and the Label Studio configure/setup/predict/webhook/health routes have other consumers. Legal HTML and framework docs/OpenAPI are navigated/requested directly. No orphaned Track 2 wrapper or missing server route for a called frontend function was found.

## 4. Track 2 feature completeness

The main annotation paths exist and the browser tests exercise NER and tag saves. The feature labels below follow the brief; the session history calls the editor B5 and uses B1/B2 for task revisions and structured content.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S4.1 | P2 | ReviewCard.tsx:146,168; ShortcutsModal.tsx:8 | Escalate is an enabled button and documented shortcut with no backing operation. | Clicking it or pressing E only displays a message. The item stays pending and no escalation is recorded. |
| S4.2 | P2 | ScoredQueue.tsx:170–175; labeling_router.py:695–697 | The queue lists only scored, current, unverified rows. It has a disabled status selector and no per-row status badge. | Verified/rejected status views requested in this sweep cannot be displayed. A new uncategorized task also disappears from the searchable workflow if the user leaves Review before classifying it. |
| S4.3 | P2 | ReviewCard.tsx:79,162–164; CategorySelector.tsx:41–46; labeling_router.py:610–615 | Category controls disagree with both editor prerequisites and the tightened server contract. | Drawing on an uncategorized task hides CategorySelector while Save requires a category. For a scored row, New category offers values the server now rejects with 422. A verified-correct row still offers relabel, which returns 409. |
| S4.4 | P2 | NEREditor.tsx:73–86; labeling_router.py:205,242 | The editor has no span-count limit; initial content and relabel enforce different maximums. | An item with 101 valid initial spans can be rendered and edited, but changing just one type sends the whole array and fails the 100-span relabel limit. |
| S4.5 | P2 | ScoredQueue.tsx:146–151; labeling_router.py:470–490 | Partial bulk results are collapsed into counts and the full selection is cleared. | A reviewer cannot distinguish quota exhaustion from an already verified label or identify which IDs still need attention. Capacity is enforced transactionally per eligible item. |
| S4.6 | P2 | IAAPanel.tsx:14–24; dashboard_router.py:140–147,174–177 | Identical constant ratings return 1.0 even though Cohen’s kappa is undefined when expected agreement is one. | The dashboard labels an uninformative sample Excellent. Overall pooling also assigns pair sides by sorted annotator name; a rename can change pooled marginals. |
| S4.7 | P2 | Settings.tsx:123–127; labeling_router.py:46–65 | Guidelines editing is available to any authenticated tenant key; the implementation has no admin capability. | The earlier admin-only editor requirement is unenforced. Tenant isolation exists; within that tenant a reviewer key can replace the instructions. |
| S4.8 | P3 | TagSelector.tsx:14–22,30–36; labeling_router.py:220–229 | Client tag length/deduplication uses UTF-16 units and locale lowercasing; server validation uses code points and casefold. | Valid emoji tags can be refused locally and apparently distinct chips can collapse after persistence. Silent local rejection gives no validation feedback. |

**Feature scorecard.** The ten lettered checks combine several deliverables in (i). Count dark mode separately from guidelines/IAA to give eleven explicitly defined feature groups. “Partial” means the feature works on at least one supported path but has a material gap. For reference, historical A1 sample, A2 source text, A3 pagination/export and A4 settings are covered under dimensions 2, 3 and 8.

| Group | Verdict | Verification |
|---|---|---|
| B1 enhanced queue | PARTIAL | ConfidenceIndicator:2 rounds confidence × 100; header selects confidence with asc/desc, and backend orders the numeric column. Status is restricted to pending, S4.2. |
| B2 review workflow | PARTIAL | Detail switches among null-content text, NER, multilabel and image. Scored items support known-outcome approve/override and next-item navigation. Revision aliases resolve to a canonical URL. Escalation is absent, S4.1. |
| B3 bulk review | PARTIAL | Individual checkboxes, page select-all, clear, action bar and {label_ids,action,reason?} are wired. No quota preflight is required for integrity; the server checks each eligible item and returns skips. S1.3, S2.2, S4.5 affect results. |
| B4 scoped search | PARTIAL | Input debounces 300 ms, resets offset/selection, URL-encodes search and uses the pending endpoint. Server escapes literal wildcards and shares its filters between count and results; clear restores unfiltered fetch. Previous matches remain actionable until the new fetch settles, S2.2. |
| C1 NER | PARTIAL | Desktop Range selection handles Unicode code points and reverse drag; overlap rejects, adjacency is allowed. Clicking a mark opens a type/delete menu. Options come from autonomy categories; custom entry is available for an empty list. Save sends spans with revision token. Keyboard/touch creation, stale popup, concurrent save and length limits remain. |
| C2 tags | PARTIAL | Suggestion filtering, click/Enter addition, removal, duplicate guard and revision payload work on existing multilabel content. S2.1 loses edits during save. Plain text offers no entry into multilabel editing, although the server permits tags on a row without existing structured content. |
| C3 image viewer | COMPLETE for server-valid image labels | Authored image content requires an HTTPS URL. Native image load/error and explicit broken-image fallback work; image is read-only, classification uses separate controls. ReviewCard:160 has no placeholder for a malformed/legacy image record with a missing URL. |
| D1 keyboard | PARTIAL | ? opens help; g+d/q/s route through the same map as u/h. j/k and Enter work on stable rows. A/O guard dirty edits and E guards dirty edits but cannot escalate. Focus and popup conflicts are in dimension 5. |
| D2 dark mode | PARTIAL | Sidebar toggles html.dark and persists on reload; contrast and system-preference gaps remain in dimension 6. |
| D2 guidelines and IAA | PARTIAL | Confirmed successful GET scopes editor readiness; PUT writes the captured domain. Review renders an escaped Markdown subset. Dashboard renders pair/overall kappa and an empty state. See S2.6, S2.8, S4.6–7. |
| PW-EXPAND | PARTIAL | All 21 typed tests exist and the expansion file type-checks independently. 20 of 21 passed in this run; the signup href assertion fails on a functioning HashRouter link. |

**Totals: 1 COMPLETE, 10 PARTIAL, 0 BROKEN.**

## 5. Accessibility and keyboard navigation

Native form controls, labeled buttons, numeric scores and textual tiers provide a usable baseline. The annotation and help dialogs, profile expansion and several focus styles leave keyboard-only or screen-reader users without equivalent control.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S5.1 | P2 | ShortcutsModal.tsx:13–27; KeyboardShortcuts.tsx:19–22 | Help sets aria-modal and initially focuses the dialog, but has no focus trap, inert background or focus restoration. | Confirmed in Chromium: two Tabs placed focus outside the open dialog. Escape closes it without restoring the invoking control. Help is documented inside the modal, with no visible trigger or entry hint for discovering ?. |
| S5.2 | P2 | NEREditor.tsx:35–47,67–76,99–106; ReviewCard.tsx:134–146 | Existing marks support Enter/Space, but creating an entity depends on mouseup. The popup neither owns focus nor suppresses review shortcuts. | Keyboard selection and mobile selection handles can leave no create action. Pressing A on an open popup before making a dirty edit can submit the review when an outcome is selected. The popup's blanket mousedown preventDefault can also prevent pointer focus of its custom input. |
| S5.3 | P2 | NEREditor.tsx:21,73–86,101–106 | Cancel/invalid selection does not clear the prior DOM range and stored popup consistently. Popup position assumes fixed dimensions. | A valid range A followed by a range overlapping a mark can leave A actionable while B is visibly selected. Escape only closes the popup; a tall picker can extend below a short viewport. |
| S5.4 | P2 | TagSelector.tsx:30–40; AnnotatorProfiles.tsx:23–25 | The tag combobox lacks arrow-key option traversal/active descendant. Profile rows expand by click alone. | Tab can reach option buttons and Enter adds typed text, but conventional listbox navigation fails. Profile details cannot be expanded by keyboard. Header direction can differ between Enter and click. |
| S5.5 | P2 | index.css:29–30,46,52; Signup.tsx:47–48; Settings.tsx:125–130 | Some inputs suppress outlines without an equivalent focus indicator. Banner errors lack per-input aria-describedby/aria-invalid wiring. | Focus is hard to locate in the tag editor; a screen reader receives the general alert without a reliable link to the field requiring correction. |
| S5.6 | P3 | ScoredQueue.tsx:110–132,174; App.tsx:65 | Queue keyboard focus is visual row state. Sort and menu expansion are not fully announced. | Ctrl/Cmd+A overrides browser select-all outside editing controls; Escape also clears queue selection when an input is focused. Sort buttons lack aria-sort, and the mobile toggle lacks aria-expanded. Screen readers cannot infer the visual row outline. |

Several interactions are unavailable using Tab alone. CategorySelector's select/input/save and NER edit/delete controls use native elements; drag-only creation and click-only expansion are exceptions. A/O/E ignore input, textarea, select, contenteditable, Ctrl/Alt/Meta and dirty edits; global shortcuts ignore repeated keys. Modal Escape and outside click exist. NERViewer highlights have textual entity names and focusable marks. Tag chips have labeled remove buttons. LoadingSpinner announces role=status, ErrorBanner uses role=alert, review status and queue toasts are announced; a guidelines load simply disables its field and a Settings success paragraph has no live role. Color findings below apply equally to keyboard users.

## 6. Dark mode and theming

The toggle and reload behavior passed the browser test. Measured dark-mode foregrounds on several key surfaces fall well below readable contrast, and switching themes does not update the full palette.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S6.1 | P2 | index.css:46,58–80; NEREditor.tsx:96–105 | Explicit light-theme heading colors and the editor's light inline background override inherited dark-theme colors. | Chromium reported h1 rgb(21,34,57) on main rgb(16,23,34), a 1.13:1 ratio. Section titles on dark cards are 1.08:1. Editor body text on its light fill is approximately 1.11:1. CSS targets “Named entities” but the editable region is “Edit named entities”. |
| S6.2 | P2 | App.tsx:27–35; main.tsx:7–9; frontend/index.html:3 | The first OS-derived theme is persisted like an explicit toggle. The class is applied in a post-render effect. | The site stops following OS changes after the initial visit. A slow load can show light base styles before dark is applied. There is no theme transition or toggle animation; the change is immediate. |
| S6.3 | P3 | index.css:18–33,40–48,61–79; Dashboard.tsx:39–42; ReviewCard.tsx:165 | Several surfaces keep fixed colors, dividers and shadows with no semantic theme token. | The chart grid, axes/default tooltip styling, review divider, tag suggestions and popup chip fills do not adapt consistently. At tablet widths the fixed bulk bar can cover the sidebar; opened mobile drawers sit below its z-index. |

The TSX literal-color scan found 18 occurrences in six files (Dashboard 5, HealthReport 1, ReviewCard 1, NEREditor 2, NERViewer 8, TextViewer 1). CSS uses a Tailwind dark variant and explicit .dark selectors with hardcoded values; there is no shared semantic color palette. The light muted text #738196 on white measures 3.96:1. Normal text needs at least 4.5:1 and large text 3:1 for this criterion. Ratios use relative luminance; this was a targeted audit, not a full assistive-technology certification. [W3C contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

| Components checked | Light/dark behavior |
|---|---|
| App, Upload, Signup, Settings | Shell/sidebar, cards, secondary buttons and many form fields switch. Headings, subtitles, focus borders and some notices retain base colors. |
| ScoredQueue, Dashboard, AnnotatorProfiles | Table borders/row highlights, focus outline and pills switch. Queue labels and the dashboard chart have independent colors. Text badges/percentages remain meaningful without color. |
| ReviewCard, HealthReport | Factor tracks and text panel switch. Divider remains pale; the report iframe deliberately displays its independent light document. |
| NEREditor, NERViewer, TextViewer | Read-only source and NER panels have explicit dark overrides. Pastel marks retain dark lettering. Editable text surface and colored popup buttons can have light-on-light combinations. |
| TagSelector, CategorySelector, ImageViewer | Chip text is explicitly dark on pastel, including in dark mode. Suggestions retain white surfaces, the transparent input inherits control colors, category inputs use shared classes, and image caption/error colors are fixed. |
| ShortcutsModal, KeyboardShortcuts, GuidelinesPanel, IAAPanel | Modal cards, kbd keys, guidelines cards, kappa pills and table use shared overrides. KeyboardShortcuts itself has no visible surface. Guidelines and IAA section headings inherit the heading defect. |
| MetricCard, FactorBar, ConfidenceIndicator, TierBadge | Cards and progress tracks/fills adapt. Tiers retain fixed color pairs plus uppercase text. Factors and confidence show numbers as well as bar length. |
| CsvDropzone, SignupBanner, ErrorBanner, LoadingSpinner | Dropzone and banner use shared dark rules; error styling remains a pale high-contrast alert and spinner/loading colors come from base rules. |

## 7. Build, bundle and deployment

The current frontend type-checks and builds locally. The repository-to-image path does not produce the assets referenced by its checked-in entrypoint.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S7.1 | P1 | Dockerfile:1,18; railway.toml:1–3; frontend/.gitignore:11; frontend/dist/index.html:16 | Railway selects the Python Dockerfile, which copies dist without building it. Git contains dist/index.html and static demo/icons but no dist/assets bundles. | On a clean Git checkout the browser can receive index.html while both module and stylesheet URLs return 404, leaving the root empty. Locally built/CLI-uploaded assets can mask this. Build the frontend in a Node stage from the lockfile and copy its output into the runtime image. |
| S7.2 | P3 | frontend/package.json:11–27; App.tsx:14; Dashboard.tsx:2 | Three installed packages have available patch updates. Lazy Dashboard is the largest JS chunk. | npm outdated listed @types/react 19.3.0→19.3.1, react-router-dom 7.18.6→7.18.7, recharts 3.11.0→3.11.1. Dashboard navigation incurs about 118 kB extra gzip even when the user has no data. No vulnerability inference follows from patch age. |
| S7.3 | P3 | frontend/vite.config.ts:6–7; playwright.config.ts:9 | Vite proxies only /v1 to localhost:8000. The browser suite defaults to a different origin and has no webServer provisioning. | The proxy works when FastAPI listens on 8000; pointing the suite at a standalone dev server or a stale listener can test a different build or fail backend checks. |

**Executed.** npx tsc --noEmit passed with noUnusedLocals/noUnusedParameters active. Vite 8.3.8 built to a new temporary directory, leaving the user's existing modified dist/index.html intact. Vite transformed 451 modules. CSS is 18.24 kB / 5.26 kB gzip; entry JS 343.09 / 106.65; lazy Dashboard JS 415.12 / 117.60. A recursive graph of relative static imports, re-exports and literal dynamic imports in frontend/src found **zero cycles**. No undeclared frontend module imports or unused direct runtime packages were found. React/DOM/router are used by the shell, Papa Parse by CSV ingest/export, Recharts by the lazy chart; Tailwind, Vite, React plugin, TypeScript and type packages serve the build. Named Recharts imports and code splitting are present. Papa's default import uses its parse/unparse API. Chunk sizes alone cannot prove per-export elimination.

**Delivery trace.** main.tsx:7–9 mounts HashRouter; /#/review/L1 and /#/settings request the root document, so FastAPI needs no per-screen history rewrite. jm_service.py:648–651 mounts static files after API routing. Production entry and lazy chunks have content hashes. The temporary build produced index-CjJyh0OJ.js, index-BgAWjp4T.css and Dashboard-CVXPqNHL.js; the running local page references the first two. Git HEAD's entry references index-DA_p97vB.js, and git ls-tree -r HEAD frontend/dist contains **zero** assets entries. The local source build and clean deployment are different gates. No Railway deployment was performed. Test both entry assets and the lazy Dashboard import from the image built with a clean context.

## 8. Playwright coverage and test quality

Playwright collected 62 tests across seven specs and ran all of them against the existing local DLJ frontend in Chromium. The four fix_state cases passed; the three failures were traced to selectors or literal URL expectations.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| S8.1 | P2 | e2e/screens.spec.ts:216–230; e2e/track2.spec.ts:216–221 | Two mobile checks select the first matching text in a hidden sidebar. The banner test expects a raw href of /#/signup. | The mobile checks time out on hidden nav anchors at 375×812, before the upload overflow assertion. The banner renders href=#/signup, valid at the root. Use a heading within main and click the link/assert the resulting URL. |
| S8.2 | P2 | e2e/track2.spec.ts:17–61,103–114,165–204; e2e/fix_state.spec.ts:61–109 | The suite lacks a persisted, authenticated end-to-end write/readback and multi-tenant test. | Independent fixtures can pass while storage, revision resolution, quota and tenant isolation fail. There is no complete upload→queue→review→verify→readback, bulk POST→readback, or two real domains with matching label IDs. |
| S8.3 | P2 | e2e/screens.spec.ts:74–83,131–143,166–175; e2e/smoke.spec.ts:13–36; e2e/polish.spec.ts:3–8 | Shell text and conditional checks can succeed with missing features. fill('gq?') does not exercise a sequence of keydown events. | A nav link can satisfy a screen check, body length can pass without tier badges, and zero headers can skip the sort operation. No regression catches dropped edits during save, early bulk action after filter change, or key changes during an import. |
| S8.4 | P2 | e2e/polish.spec.ts:17–25; e2e/fix_state.spec.ts:86–129; e2e/tags_image.spec.ts:13–33 | Mock responses omit important negative and recovery paths; theme coverage checks persistence only. | There is no failed request→retry→success flow through real controls, no guidelines PUT/readback, no keyboard dirty-tag override attempt or canonical successor ID round trip, and no visual/accessibility check across themes. |
| S8.5 | P3 | e2e/screens.spec.ts:45–206; e2e/track2.spec.ts:70–94; playwright.config.ts:3–14 | Fixed waits, broad console suppression and missing suite type-check integration weaken failure signals. | 15 waitForTimeout calls across three files depend on machine/network speed. The filter can suppress real React or API errors; console events miss pageerror. Without explicit Node types, standalone compilation of the full suite errors on process in two specs. |

**Run evidence.** 59 passed, 3 failed in 31.9 s with three workers. The live /v1/health check returned 503 with structured JSON during inspection. The smoke health test permits that status. This run verifies browser behavior, not healthy database readiness. Temporary output held the failure logs/screenshots. The expansion file compiled independently. All seven specs also type-checked when the compiler was given NodeNext resolution, DOM libraries and the installed Node types explicitly. frontend/tsconfig.json includes only src and vite.config.ts; no e2e/tsconfig.json exists.

| Screen | Executable coverage and what it proves |
|---|---|
| Upload | smoke:18; screens:69–95,216; track2:99–114,211–221. Presence, mocked sample analysis/seed/navigation and signup banner. No real multi-batch ingest or interrupted retry. |
| Queue | smoke:23; screens:99–127; track2:108,137–170; fix_state:61; polish:3. Mocked sort query/control, pagination UI, preview, header/row selection, action visibility and cross-domain reset. The fixture returns fixed rows; neither real ordering nor partial bulk persistence follows. |
| ReviewCard | screens:202; track2:176–205; fix_state:36,111; ner_editor:42,65; tags_image:37,55. Tests render text, choose known outcome, POST via A, guard stale reads, edit Unicode spans, tags and broken images. No persisted next-item/revision verification or interrupted edit. |
| Dashboard | smoke:29; screens:131–155,225; polish:17 opens Upload for theme and supplies no dashboard rendering assertion. Metrics/tier tests can match shell text. No populated IAA or chart data oracle. |
| Settings | track2:118–131; fix_state:86–109. Route/account labels and late guidelines loading guard. No save readback, key rotation, billing return or competing refresh. |
| Signup | track2:75–95,216; the generic navigation loop at screens:56 omits Signup and Settings. Form, CTA, direct hash and console checks. No registration/key receipt/clear round trip. |
| AnnotatorProfiles | smoke:34; screens:161–179. Table/sort structure; no data-driven identity, ordering or expansion oracle. |
| HealthReport | smoke:39; screens:182–197. Upload area and console on load; no file→preview→PDF check. |

All eight screens have multiple named tests or checks. None has zero or just one nominal test; several have zero assertions about persisted domain data. Specs are smoke (7), screens (24), track2 (21), ner_editor (2), tags_image (2), polish (2) and fix_state (4). There are no separate signup.spec.ts, queue.spec.ts, review.spec.ts or settings.spec.ts files.

**Reliability.** Playwright's page/context fixtures isolate cookies, localStorage and request handlers per test. Route interception and explicit response gates in fix_state are stronger than sleeps. The sample seed and verify POST in track2 are mocked; its verify test checks payload/navigation but does not persist a label. No unexpected real mutation was needed for the diagnostic probes. The seven files include 12 fixed waits in screens, one in smoke and two in track2. The NER test constructs a DOM Range and dispatches mouseup rather than driving a full drag. That synthetic event and fixed mobile dimensions leave touch selection, keyboard-only creation, zoom and responsive overlays untested. The failures observed here have deterministic locator/URL causes; no failure was attributed to an animation. Prefer auto-waiting for the specific result row, response, heading or persisted revision.

## Recommended fix priority order

| Order | Work | Acceptance check |
|---|---|---|
| 1 | Build assets in the deployment image (S7.1). | From a clean Git checkout, build the same image Railway uses. GET the root and every referenced asset, then open a Dashboard hash link and verify the lazy chunk renders. |
| 2 | Bind all tenant work to a credential generation; stop unsent batches on scope loss and clear obsolete signup receipts (S1.1–2). | Change keys during a held 200-row import and on a second tab's receipt screen. No subsequent request carries the replacement key for that import, and the old receipt is gone. |
| 3 | Correct the bulk fact model and bind bulk actions to the full loaded query (S1.3, S2.2, S4.5). | Exercise mixed recommendations with an independently supplied outcome, slow sort/search/page changes and a partial quota result. Assert persisted IDs, outcomes and remaining failures. |
| 4 | Serialize review edits and mutations, keep drafts or freeze editing until completion, and validate JSON successes (S2.1, S2.3, S3.1). | Test two edits across one delayed save, route A→B with A returning 409, canonical successor IDs, and an HTML response from a JSON endpoint. Preserve the current draft and route, with a recoverable error. |
| 5 | Fix account/file/dashboard request ownership, category/guidelines permissions and IAA calculation. | Add delayed and failed request cases per scoped view, keyboard-accessible recovery for unclassified tasks, correct null kappa for constant raters, and authorized guidelines save→readback. |
| 6 | Repair the three false failures now; add authenticated browser readback, keyboard and contrast gates alongside the fixes. | Require the full Playwright suite to pass against the freshly built artifact, plus both themes, keyboard-only workflows and a database-backed tenant-isolation flow. |
