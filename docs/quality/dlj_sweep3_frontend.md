# DLJ frontend sweep, round 3

24 November 2026 · jm-service at `7cb0c27` · 27 React components (App, eight screens, eighteen child components).

**Five distinct P1s remain across the three rounds.** The original split-credential import, stale bulk submission after a query change, HTML-as-DTO crash and missing deployment bundles all have targeted fixes. Remaining failures include two ways to carry state across accounts, a review draft lost during another mutation, implicit ground truth, and a render crash on an incompatible JSON object.

| Measure | Result |
|---|---|
| Current distinct findings | 5 P1, 21 P2, 4 P3 |
| Seven targeted round 2 fixes | 5 CLOSED, 2 PARTIAL, 0 OPEN, 0 REGRESSED |
| Additional round 2 P1 S1.3 | OPEN. Included in current findings, excluded from the seven-fix denominator. |
| Track 2 groups, using round 2 definitions | 3 COMPLETE, 8 PARTIAL, 0 BROKEN. B4 and PW-EXPAND improved. |
| Executed | Frontend typecheck and production build passed. E2E specs typechecked with the frontend compiler. Full Chromium run on localhost:8080 passed 107/107 across 10 specs in 28.8 seconds, three workers, zero retries. |
| Evidence | Build hashes matched the served entrypoint. Additional Chromium checks intercepted writes with synthetic data. Backend persistence and Docker/Railway deployment conclusions below come from source unless explicitly described as executed. |

Paths below are relative to jm-service. Bare component filenames refer to frontend/src/screens or frontend/src/components. App, api and index.css live in frontend/src. Each **R3** row counts once. Scorecards cross-reference these rows.

### Five highest risks and recommended fix order

1. **Bulk ground truth (R3-07).** Collect a known outcome before verifying a homogeneous batch, or split mixed outcomes into appropriate requests. Assert persisted outcomes for both recommended actions, including explicit false. Remove the UI dependency on the deprecated fallback.
2. **Late registration (R3-01).** Bind registration completion to its initiating screen and credential generation. Delay the response, change accounts and navigate away. The chosen key and domain must survive completion.
3. **Prior account's CSV survives rotation (R3-02).** Preserve the stop notice separately and reset file, report, progress and text-task drafts on account changes. Require a fresh file selection under the new key.
4. **Lost review drafts (R3-03).** Share a mutation lock between category, span, tag and verification controls. Guard completion by route and mutation generation, including conflict handlers. Test editing during a delayed category save and during verify.
5. **Invalid JSON object crashes Settings (R3-08).** Validate the account response before storing it, surface a recoverable error and isolate route render failures. Exercise a JSON object missing usage as well as a 200 HTML fallback.

## 1. Round 2 fix verification

Five fixes close the failure paths named in the brief. Registration cleanup and annotation-save locking work on their normal paths but both have reachable timing gaps. Backend R13 provides an explicit bulk outcome and keeps the legacy branch active for clients that omit it.

| Round 2 ID | Verdict | Trace and evidence |
|---|---|---|
| S7.1 | CLOSED (source/build path) | Dockerfile:1–6,25 builds from the tracked npm lockfile and copies Vite output from Node into Python. Host dist is excluded. See dimension 7 for the image verification limit. |
| S1.1 | PARTIAL | Signup:14–32 and App:37–56 clear old domain, checkout and obsolete receipt on observed credential changes. fix_round2:42 confirms immediate registration. A late registration still changes the active account after the screen loses ownership (R3-01). |
| S1.2 | CLOSED for a single import | Upload:73–108 captures the key and domain, compares storage before each batch, passes the captured key and signal to ingestBatch, and checks again before navigation. App emits the abort event and Upload aborts on unmount. No subsequent batch of that run can use a different key. Retained input on a *new* import is R3-02. |
| S2.1 | PARTIAL | ReviewCard:79–111,163–165 locks tag and span controls through their own relabel request and same-ID refetch. NER guards mouse, keyboard and popup mutation paths. Tag input, suggestions and removals disable. CategorySelector and verification have independent busy state (R3-03). |
| S2.2 | CLOSED for changed-query bulk IDs | ScoredQueue:42–65,75–108,146–151 masks rows by domain, query key and debounce readiness. Request sequence rejects stale results. Selection resets on raw/applied search, category, sort field/direction, page size, offset and domain. Submit intersects visible IDs, blocks busy/stale submissions and handles an empty intersection. fix_round2:91 holds the new query open. |
| S3.1 | CLOSED for HTML returned from a JSON endpoint | api.ts:182–187 rejects text/html with ApiError 502 on JSON endpoints. HTML report and PDF explicitly request their own formats. fix_round2:126 asserts an alert and a surviving Settings heading. Other response shapes are covered in dimension 3. |
| S8.1 | CLOSED | screens:216,225 locate headings under main at mobile width. track2:216 clicks the signup banner link and checks the resulting hash. All three passed in the full run. |
| S1.3 (additional) | OPEN | ScoredQueue:152 and api.ts:210 omit outcome. labeling_router.py:444,489–493 logs the deprecation and still converts approve/reject into true/false. See R3-07. |

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-01 | P1 | Signup.tsx:14,26–33 | The receipt listener clears an existing receipt. The pending registration has no owner check before its storage writes. | Chromium held registration, committed a different sidebar key, left Signup and released the response. The late handler replaced the chosen key and cleared the domain after navigation. Later requests use the unexpected account. |
| R3-02 | P1 | App.tsx:41–54,83 · Upload.tsx:13–32,73–114 | The active-import exception leaves the old Upload component mounted to display the abort message. Its file and analysis survive rotation. | Chromium stopped batch one, switched keys and still saw the original filename. Entering the new domain and clicking Start again sent both batches of that file with the second key, without selecting a file. The original run itself sent only the first key. Previously entered text-task fields also remain visible. |

## 2. Component state management

GET results for label details and guidelines carry a domain or route check, and queue fetches use a sequence counter. Mutation continuations, file analyses and account refreshes do not consistently check which user interaction still owns the result.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-03 | P1 | CategorySelector.tsx:28–38 · ReviewCard.tsx:64–67,120–131,152–165 | Only span/tag saves set isSaving. Category save and verify leave the annotation draft editable. Dirty drafts also have no navigation guard. | In Chromium a tag added while category relabel was held had a visible Remove button. Releasing the response opened the successor revision and the tag disappeared. Verify can similarly navigate away from a newly edited buffer. |
| R3-04 | P2 | ReviewCard.tsx:48–58,86–94,103–111,128–133 · CategorySelector.tsx:21–38 | Old write failures run their captured load before checking current ownership. After unmount the last route ref can remain equal to its captured value. | A late 409 for A can abort B's detail read. An old success can redirect after leaving Review. Category options can also arrive out of order. An auxiliary pending/autonomy failure hides otherwise available detail. |
| R3-05 | P2 | CsvDropzone.tsx:5–9 · Upload.tsx:43–45,74–108 · HealthReport.tsx:14–24 | Drop bypasses the disabled file button. Analysis results and busy state have no per-file generation. Import progress counts acknowledged responses. | A's analysis can appear next to B's filename and B's scoring/download input. An overlapping analysis can re-enable a second import. Aborting fetch after a server commit can report zero committed rows and encourage a duplicate retry. |
| R3-06 | P2 | Settings.tsx:47–78,93–115,125–127 · Dashboard.tsx:21–38 · AnnotatorProfiles.tsx:16–25 | Several editors and reads update state by completion order. Guidelines PUT captures the correct domain but the textarea stays editable. Dashboard and Profiles leave old data visible under a new nonempty domain. | Settings can show “saved” beside text entered after PUT began. A late domain resolution can replace the user's newer selection. Old metrics or names persist during a failed domain switch. Clearing domain during fetch can leave busy set. |
| R3-06a | P2 | ScoredQueue.tsx:53,125–138,152–158 | Focus is an array index across refreshes. Bulk success checks domain only, and errors have no scope check. | Polling can move the highlight to another ID or leave Enter opening /review/ when the index exceeds the page. An old bulk result can clear a newer selection or show an error on the next view. This is distinct from submitting IDs from a changed query. |

**Component inventory and scope transitions**

| Component(s) | What owns the state and what happens on change |
|---|---|
| App, Signup | Sidebar stores key on blur/Enter. Same-tab custom event and cross-tab storage listeners read current storage and clean up on pathname change. Ordinary key changes reload. Signup and active import use the exceptions above. Theme is separate. |
| Upload, CsvDropzone, HealthReport | CSV import aborts on unmount/account notification. A sidebar domain change alone does not cancel it. Remaining batches stay scoped to the originally captured domain, and completion navigates to the queue for the currently selected domain. Sample seeding and task creation have no comparable ownership check. Dropzone carries local hover state. Report preview uses a sandboxed iframe and revokes PDF object URLs on a timer. |
| ScoredQueue | 300 ms search timer and 30 s polling interval have cleanup. Pending requests finish in the background and must match requestId and domain. The query key includes pagination and sort. Category lookup uses a live flag. A bulk POST already sent cannot be undone by clearing selection. |
| ReviewCard, CategorySelector | Detail/pending/autonomy share an abortable read. Guidelines use another controller. Item render checks both IDs. Keyboard listener rebinds to current state. Draft equality blocks single verification. A stale write catch/finally can still reach current state. Selector resets category on revision, retains custom text and does not cancel autonomy reads. |
| NEREditor, TagSelector, ImageViewer | Editors are keyed by revision. Span popup is local, Escape listener cleans up, invalid selections can leave the previous popup. Tag suggestions use current props and a local input/open flag. ImageViewer resets on URL changes and handles native load/error events. |
| Settings | Readiness requires a successful GET for the active domain. GET is aborted on switch and save uses the captured domain. No cross-domain guidelines PUT from the named load race was found. The account poll/focus listeners and timers clean up, but their in-flight results are unordered. Checkout can still redirect after leaving the screen. |
| Dashboard, AnnotatorProfiles, IAAPanel | Live flags drop old completions without cancelling transport. Previously displayed data and profile expansion can survive switches. IAA failure and absence both feed the same empty-state display. IAAPanel itself owns no request. |
| KeyboardShortcuts, ShortcutsModal | Global listener and prefix timer clean up. Opening help after g can cancel the timer while leaving its waiting ref true. Modal owns initial focus and Escape cleanup. |
| GuidelinesPanel, NERViewer, TextViewer, SignupBanner | Guidelines render a limited Markdown subset as escaped React nodes. Read-only viewers derive output from props. Banner reads current key at render and relies on a parent rerender/remount. |
| ConfidenceIndicator, FactorBar, MetricCard, TierBadge, ErrorBanner, LoadingSpinner | Render values/visibility from props. No domain cache, async writes, timer or unmount work. A bad DTO can still reach formatters, as in dimension 3. |

## 3. API contracts

Explicit credentials take precedence via nullish coalescing in api.ts:163–168. Public analyze/report/register calls omit the key and authenticated callers otherwise use the stored key or the existing development fallback. Successful bodies are checked against the expected media type before decoding, but the decoded value crosses into the UI through a TypeScript assertion.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-07 | P1 | ScoredQueue.tsx:146–158 · api.ts:210 · labeling_router.py:140–144,444–445,487–493 | The request type and buttons have no separate outcome. R13 accepts one optional boolean for the batch. The current payload works on both backend generations and always selects legacy semantics. | Approving a recommended rejection can record the incorrect label as correct. Skipped rows and quota errors are returned per ID, but the UI clears selection and displays counts only. A mixed-truth batch cannot be represented by one boolean. |
| R3-08 | P1 | api.ts:182–187 · Settings.tsx:61–70,120 · App.tsx:83 | A JSON media type proves neither shape nor required nested fields. The root has Suspense but no render error boundary. | A mocked 200 application/json account response containing {} passed decoding. Chromium reported a day_key dereference error and zero remaining headings. A failed lazy import likewise lacks route-level recovery. |
| R3-09 | P2 | api.ts:150–187 · Upload.tsx:74–79,90–103 | Error parsing preserves status/detail/error and falls back to response text. Indexed CSV errors omit batch offset and header. The importer requires a stored key despite the API helper supporting a development key. | First rejected row in batch two is identified as CSV row 1. A dev-only configured account can score a sample but cannot start a CSV import. The account-change message names the original account clearly but cannot know a pending server commit (R3-05). |
| R3-10 | P3 | api.ts:182–187 | Media matching is a case-sensitive substring test. A missing header, HTML or a 204 with no type on a JSON call gives the readable 502 error. application/json with a charset succeeds. | Application/JSON and vendor +json are rejected. application/jsonp passes the header check. Malformed or empty JSON with a matching header surfaces a parser error. Explicit HTML and PDF endpoints preserve text/blob responses. |
| R3-10a | P2 | csv.ts:24–36 · api.ts:196,224–227 · labeling_router.py:89,788 | CSV ingest accepts a slash inside a label ID. Item detail/edits use an encoded path segment. | A stored ID can appear in Queue yet fail detail routing once ASGI decodes the separator. Ingest validation and item addressing need a common ID contract. |

## 4. Track 2 feature completeness

Scoped search and PW-EXPAND now meet the round 2 feature definitions. C3 remains complete for valid image labels. The eight remaining partial groups have specific gaps even though many normal paths pass browser checks.

| Group | Verdict | Current behavior and remaining gap |
|---|---|---|
| B1 enhanced queue | PARTIAL | Numeric confidence, rounded percentage and sortable header work. Only current scored, unverified items appear. Status selector is disabled and there are no verified/rejected badges. |
| B2 review | PARTIAL | Supported detail types, known-outcome approve/override, revision redirect and next-item navigation work. Escalate only emits a message. Mutation ownership remains incomplete. |
| B3 bulk | PARTIAL | Page/all/none, ID intersection and query resets work. Server enforces quota per eligible row. Explicit ground truth and per-ID skip feedback are missing. |
| B4 scoped search | COMPLETE | Debounce, encoded literal search, domain/category scope, page reset, clear and row ownership work. Returning from Review remounts the queue and clears its query, as before. |
| C1 NER | PARTIAL | Desktop range selection, Unicode offsets, overlap rejection, type/delete and revision save work. Keyboard creation, picker invalidation, server limits and category-save races remain. |
| C2 multilabel | PARTIAL | Existing multilabel rows support suggestions, add/remove and Save Tags. Its own save locks those inputs. There is no transition from plain text to multilabel in Review. |
| C3 image | COMPLETE for valid server data | HTTPS image, loading/error UI and read-only display work. A legacy record with a missing URL still mounts no placeholder. |
| D1 keyboard | PARTIAL | Global routes and help, queue navigation and A/O work in their normal contexts. E cannot persist an escalation. See dimension 5. |
| D2 dark mode | PARTIAL | Toggle and persistence work. Contrast and system theme handling remain defective. |
| D2 guidelines and IAA | PARTIAL | Scoped guidelines GET/PUT, escaped display, and pair/overall IAA rendering work. Role enforcement, save feedback and degenerate kappa remain incomplete. |
| PW-EXPAND | COMPLETE for the 21 specified tests | All 21 collected, typechecked and passed. Critical integration gaps elsewhere in the suite are in dimension 8. |

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-11 | P2 | ReviewCard.tsx:147,169 · ScoredQueue.tsx:176 · labeling_router.py:705 | Escalation only displays text. Pending is the only list status. | Reviewer cannot send an escalation, revisit a reviewed row by status, or rediscover an unclassified task in this queue after leaving it. |
| R3-12 | P2 | ReviewCard.tsx:79,163–165 · CategorySelector.tsx:40–46 · labeling_router.py:206,243,617–623 | Dirty spans hide category selection even when category is required to save. Edit controls and server eligibility/limits differ. | An unclassified task can get stuck with unsavable edits. A verified-correct relabel is refused. Valid initial content with 101–1,000 spans exceeds the 100-span relabel ceiling. |
| R3-13 | P2 | dashboard_router.py:139–147,174–177 · IAAPanel.tsx:14–24 | Expected agreement of one returns 1.0 for identical constant ratings. Overall kappa pools left/right marginals by sorted annotator names. | An undefined score displays as Excellent. Renaming annotators can affect pooled marginals. A failed fetch also looks like insufficient observations. |
| R3-14 | P2 | Settings.tsx:123–127 · labeling_router.py:47–65 | Guidelines writes authorize a tenant key, without an admin role check. | Any holder of that tenant capability can replace instructions despite the requested admin-only editing model. |
| R3-15 | P3 | TagSelector.tsx:14–22,30–36 · labeling_router.py:220–231 | UI length/dedup uses UTF-16 units and locale lowercasing. Backend counts code points and uses casefold. | Valid emoji tags can be refused or chips can collapse after saving. Silent local rejection gives the reviewer no reason. |

## 5. Accessibility and keyboard navigation

During a span/tag save, native disabled tag controls leave the tab order and other controls remain reachable. NER marks remain focusable with tabIndex=0 and ignore activation while locked. The NER surface has aria-busy, but the focused mark has no disabled state, and neither editor provides a consistent announced saving/completion transition.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-16 | P2 | ShortcutsModal.tsx:13–28 · KeyboardShortcuts.tsx:19–27 | S5.1 UNCHANGED. Initial focus, Escape and outside click work. Tab is uncontained and the opener is not restored. | Two Tabs moved focus outside the open modal in Chromium. Someone using a keyboard can interact with the background or lose their place after closing help. |
| R3-17 | P2 | NEREditor.tsx:35–52,69–80,100–113 · ReviewCard.tsx:135–149 | S5.2 UNCHANGED. Existing marks support Enter/Space when unlocked. Creation relies on mouseup. Popup does not take keyboard focus or suspend review shortcuts. | A keyboard-only user cannot create a span. A review shortcut can act while a clean popup is open with an outcome selected. During save a focused mark can appear actionable while silently ignoring activation. |
| R3-18 | P2 | NEREditor.tsx:21–24,69–80,104–106 | S5.3 UNCHANGED. Invalid/overlapping ranges early-return before clearing the previous picker. Escape closes the popup but leaves the DOM range. | A picker opened for range A can apply to A while another range appears selected. Fixed height/width assumptions can put options beyond the viewport. |
| R3-19 | P2 | TagSelector.tsx:28–42 · AnnotatorProfiles.tsx:23–26 | S5.4 UNCHANGED. Tab can reach suggestions and Enter adds typed text. Arrow navigation/active descendant is absent. Profiles expand only on row clicks. | A keyboard user cannot traverse the combobox conventionally or expand a profile row. Disabling the input during a save adds no return-focus handling. |
| R3-20 | P2 | index.css:29–30,46,52 · ScoredQueue.tsx:53,115–138,179 · App.tsx:73 | S5.5 UNCHANGED. Some inputs remove focus outlines without equivalent styling. Queue row highlighting is visual, independent of DOM focus. | j/k still work outside editing controls after results load. Search retains its DOM focus, but removing a focused row checkbox can return focus to the document. Applied filter changes reset the index. Escape clears selection without announcing it. Sort direction and menu expansion lack complete ARIA state. |

## 6. Dark mode and theming

Round 2 made no changes to the stylesheet or to the theme initializer and persistence effect. The runtime toggle still changes the shell and cards, while the inherited and explicitly assigned foreground colors differ on important content.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-21 | P2 | index.css:46,58–62,76–78 · NEREditor.tsx:100–104 | S6.1 UNCHANGED. Chromium measured heading rgb(21,34,57) on main rgb(16,23,34), about 1.13:1. The editable NER region also misses the dark background selector for “Named entities”. | Main headings are nearly invisible, and editor body text can be light on a light fill. Existing dark-mode tests compare surface changes without measuring text contrast. |
| R3-22 | P2 | App.tsx:27–35 · main.tsx:7 | S6.2 UNCHANGED. An empty preference initializes from matchMedia once. The effect persists that choice on first render without subscribing to changes. | Later OS theme changes are ignored, including across reloads. Applying the class after render permits a light flash. |
| R3-23 | P3 | Dashboard.tsx:40–42 · ReviewCard.tsx:166 · index.css:40–48,61–79 | S6.3 UNCHANGED. Chart grid/axes, divider, suggestion surfaces and popup fills retain fixed colors. | Changing the shell theme leaves some text/surfaces mismatched. Tag chips and read-only NER marks retain explicit dark text on pastel fills. |

## 7. Build and deployment

Railway selects the repository Dockerfile. Node 22 installs from the tracked lockfile with npm ci, then runs the frontend build. The runtime copies /app/frontend/dist from that stage and FastAPI mounts it at the root after the API routes (Dockerfile:1–8,25, railway.toml:1–3, jm_service.py:655–658). The Python stage **did** change from 3.11-slim to 3.12-slim. Other than the base and dist copy, its setup and entrypoint match the round 2 baseline.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-24 | P2 | Dockerfile:1–8,25 · test_deployment.py:130 · playwright.config.ts:9 | Build and browser verification exercised the local frontend. The available deployment test inspects Dockerfile text and local files. Docker CLI unavailable on this host. | A Linux install, Python 3.12 dependency or container startup failure could pass both gates. Image build, entry script, health check and lazy chunk delivery from the image remain unverified. |

The frontend no-emit check and npm run build succeeded with 451 modules. Vite emitted index.html (1.18 kB), index-BgAWjp4T.css (18.24 kB), index-6ole8D7b.js (345.28 kB) and Dashboard-DThozzNF.js (415.12 kB). The running localhost:8080 page referenced the same entry JS and CSS. Build context excludes host frontend/dist and node_modules. Tracked frontend/public includes the sample fixture and icons. HashRouter deep links request the root document. Round 2 introduced browser storage/event names, with no new required environment variables. VITE_API_KEY remains a development fallback with the CSV exception in R3-09.

## 8. E2E coverage and quality

Playwright listed **109 lines, 107 tests, 10 spec files** and executed them all. The distribution is smoke 7, screens 24, track2 21, ner_editor 2, tags_image 2, polish 2, fix_state 4, fix_round2 5, flows 10 and components 30. All 107 passed, including the two mobile main-content assertions and the signup-banner navigation check.

| ID | Severity | File:Line | Description | Failure Mode |
|---|---|---|---|---|
| R3-25 | P2 | e2e/flows.spec.ts:19–49,57–90 · e2e/components.spec.ts:234 | Flow tests verify navigation, bodies and changes to mocked state. Bulk mocks remove all submitted IDs. The exact expected payload actually excludes an outcome. | A database-backed wrong ground truth, revision conflict, quota skip or tenant mixup can pass. A one-row mock upload also bypasses the real health analyzer's file requirements. Add disposable backend readback with mixed decisions and identical public IDs under different tenants. |
| R3-26 | P2 | e2e/fix_round2.spec.ts:10,42,59,91,126 | All four requested risk areas have a targeted test, but each covers one variant. The test named for spans and tags only manipulates tags. | A stale signup, cross-account file reuse, uncertain first-batch commit, category/verify edit race, stale sort/page or invalid JSON DTO can ship green. The queue test checks removal for a held search and zero writes without attempting a stale action. |
| R3-27 | P2 | e2e/screens.spec.ts:74–83,131–143,166–175 · e2e/polish.spec.ts:3–8 · e2e/components.spec.ts:87 | Conditional assertions, shell/body text, or assertions for the current absence of UI can be satisfied with missing functionality. fill simulates input content rather than keyboard shortcuts. | Missing badges, no sortable columns, or a missing legacy image placeholder can pass. A visually unreadable heading passes the dark surface tests. |
| R3-28 | P3 | e2e/screens.spec.ts:45,60 · e2e/smoke.spec.ts:25 · e2e/track2.spec.ts:93,131 · playwright.config.ts:9 | Fifteen fixed wait sites remain (12 screens, 1 smoke, 2 track2). Several checks filter console errors broadly. No webServer provisions the build under test. | Timing jitter changes results or a stale listener passes them. New flow/component tests use explicit predicates and pageerror collection, while a green smoke run alone cannot establish database readiness. |

**Coverage by screen.** References identify executable groups in e2e. None of the eight screens has zero nominal checks.

| Screen | Tests and observed scope | Missing critical assertion |
|---|---|---|
| Upload | smoke/screens route/dropzone/mobile, track2 sample workflow and banner, flows:57 CSV→queue→review, fix_round2:10 key change while first of two batches is pending | Confirmed partial commit and safe restart across tabs/accounts. |
| Signup | track2:75–95,216 form, hash, CTA, console and real banner click. fix_round2:42 successful receipt and storage cleanup | Late registration and replacing a credential on an existing receipt. |
| Queue | smoke/screens shell/filter, track2:137–170 sorting/preview/bulk, components:224–304 selection/score/paging, fix_state:61 domain switch, fix_round2:91 delayed search, flows:64–85,99,138 bulk/domain/keyboard/retry | Persisted explicit bulk outcome, per-ID skips, held sort/page and refreshed row identity. |
| ReviewCard | screens:202 route, track2:176–205 content/A, fix_state:36,111 stale read/dirty guard, ner_editor and tags_image edits, components:40–125 editor/viewer/category, flows:57,85,114 workflow and spans, fix_round2:59 tag lock | Save locking across category and verify, stale 409, canonical successor with a concurrent draft. |
| Settings | track2:118–131, fix_state:86 delayed guidelines, components:129 PUT, flows:92 guidance visible in Review, fix_round2:126 HTML 200 | Concurrent saves and polling, incompatible JSON shape, real permissions and checkout return. |
| Dashboard | smoke/screens metrics, tiers, mobile heading, components:148–171 IAA cases, flows:107 theme across routes | Wrong-domain metrics during slow/error reads, real degenerate-kappa computation and foreground contrast. |
| AnnotatorProfiles | smoke profile route and screens:161–179 table/sort | Populated row order and expansion by keyboard, domain isolation while a request is pending. |
| HealthReport | smoke route and screens:182–197 upload area/console | Two overlapping files, correct preview and downloadable PDF for the same file. |

**Round 2 regression mapping.** fix_round2:10 observes a real browser cancellation path and the credential on intercepted batch one. It checks the stop-message prefix rather than acknowledged count or server commit. Line 59 holds tag save and asserts disabled input/removal. Line 91 holds a nonmatching search and checks that old rows and actions disappear. Line 126 supplies HTML and checks recovery through the Settings alert. Flows and components add normal bulk, filter, domain switch, retry, keyboard, guideline readback and theme paths. Their fast, successful mocks complement the held-response tests. Neither suite exercises the two race sequences reproduced for this report.

After the five P1 fixes, prioritize unambiguous import progress, scoped Settings/Dashboard reads and keyboard/focus handling. Gate deployment with the actual container and gate bulk verification with persisted action and outcome assertions. These checks cover the two boundaries left outside the local green browser run.
