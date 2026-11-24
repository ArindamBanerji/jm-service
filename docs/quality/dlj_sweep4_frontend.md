# Frontend sweep, round 4

24 November 2026 · jm-service · `bdc4927`

**Frontend P1 convergence is not confirmed.** One of the five round 3 fixes closes its original finding completely. Four original P1s remain partial. A new account-isolation failure brings the number of distinct open frontend P1s to **five**. The frontend is **not ready** to serve as the accepted baseline for Post-Track 2.

| Measure | Result |
|---|---|
| New findings | 1 P1, 2 P2, 0 P3 |
| Round 3 scorecard | 1 CLOSED, 4 PARTIAL, 0 OPEN, 0 REGRESSED |
| Earlier P2s incidentally improved | 3 of 21 partially improved, zero fully closed |
| Verification | Frontend and Playwright TypeScript checks passed. Production build passed. Chromium passed 110 of 112 tests, including all five round 3 tests. |
| Evidence scope | Production bundle served on localhost:8080. Additional browser checks used synthetic credentials and intercepted responses. The bulk contract was checked against the actual Python request model. Database write behavior was traced in source. |

Paths below are relative to jm-service. Screen and component filenames refer to frontend/src/screens and frontend/src/components. A PARTIAL verdict credits the tested path and identifies a remaining path to the original impact. Counts distinguish new defects from additional demonstrations of earlier findings.

## 1. Round 3 fix verification

The stopped-import fix removes the old file and form state. Each of the other four fixes works for a narrower case than the original round 3 finding. In particular, the presence of a boolean in a browser request does not establish that the backend received an explicit outcome.

| Fix | Verdict | Evidence and remaining failure |
|---|---|---|
| FE-R3-1 · explicit bulk outcome (R3-07) | **PARTIAL** | ScoredQueue:146–158 sends IDs and action. api.ts:210 adds `verified_outcome: action === 'approve'`. BulkVerifyRequest in labeling_router.py:140 declares `outcome`. Parsing approve with `verified_outcome: false` produced `outcome=None`; parsing it with `outcome: false` retained False. The writer at line 485 consequently uses the intended legacy fallback. Normal approve/reject values coincide with that fallback, concealing the contract mismatch. A reviewer still cannot supply independent truth for an approved rejection or split a mixed-truth batch by outcome in this UI. This is also the joint acceptance criterion in docs/design/dlj_arch_redesign_v2.md:18,334. |
| FE-R3-2 · late signup (R3-01) | **PARTIAL** | Signup:23–35,42–57 guards unmount, route and current key value. Navigating away or leaving a different key selected defers the receipt. Chromium held registration on Signup, committed key B then explicitly reselected starting key A through the sidebar, entered a domain and released the response. The late handler installed the registration key and erased the chosen domain. Equality misses intervening account changes. |
| FE-R3-3 · CSV and form cleanup (R3-02) | **CLOSED** | Upload:27–46,92–130 aborts the controller, invalidates analysis, clears file/report/progress/sample and all three task fields, and remounts the native file input. The request uses the captured key, signal and domain. fix_round2 and fix_round3 cover the interrupted batch, disappearance of the old filename/scoring button and empty native selection. The normal upload flow passed. The pre-existing uncertainty about an interrupted server commit is R3-05. |
| FE-R3-4 · category save and editors (R3-03) | **PARTIAL** | CategorySelector:28–38 raises the parent saving flag through its awaited callback. ReviewCard:169–171 passes it to both editors. However, verify only sets `busy`. Chromium added a tag to the draft during a held verify and saw its Remove button. Releasing verify navigated to Queue and discarded the edit. In the opposite direction, approve and its shortcut check `busy`, independent of the category saving flag. The canonical revision path also loses typed tag text (dimension 3). |
| FE-R3-5 · Settings usage (R3-08) | **PARTIAL** | api.ts:249–255 supplies defaults for an absent usage object. A starter account rendered successfully. A partial response with `usage.labels_today=null` overrides the default. Chromium then reported a null `toLocaleString` error and zero main headings. Settings:133 evaluates the formatter while constructing the boundary's children, outside UsageBoundary's render protection. |

## 2. Regressions from the fixes

The new registration receipt outlives a later credential change, even though the on-screen receipt clears. The usage fallback also turns unknown quota information into an affirmative subscription claim. Both were observed in the built UI.

| New finding | Severity | Evidence and impact |
|---|---|---|
| R4-01 · Deferred credential reappears in another account context | **P1** | Signup:6–18,32–35,45–49,65–71 stores the entire registration receipt in tab session storage. Using synthetic accounts, a registration under A completed after selecting B. Switching to C cleared the visible receipt. Leaving and reopening Signup under C restored the earlier plaintext key and offered Copy and Use this key. A later operator of the same tab can obtain another account's credential. This persists across remounts and is distinct from the old late automatic activation. |
| R4-02 · Missing quota displayed as Unlimited | **P2** | api.ts:249–255 and Settings:129–133 turn missing counts into zero and a missing monthly cap into null. Chromium displayed “This month (— UTC): 0 / Unlimited” for a starter account lacking usage. Genuine HTTP errors still reach ErrorBanner. A successful but incomplete response can mislead a customer about available capacity. |

| Regression question | Result |
|---|---|
| Bulk callers and tests | The sole UI caller still compiles. The backend ignores the added key. Two existing browser tests fail on exact body equality (dimension 4). |
| Signup mounted ref | Setup restores true and teardown sets false and removes the listener, including under StrictMode. No accumulating listener was found. The unresolved promise can finish after unmount by design. Key generation and persistent receipt ownership are the defects. |
| Ordinary uploads | Successful CSV scoring still navigates to the queue. The sample analysis and sample scoring tests also passed. File analysis completions now check their run number. |
| Other editor saves | Own tag/span saves retain their lock while pending. Verification and category save can still overlap. Old route callbacks can also update a newer route's flags (R3-04). |
| Account errors and real readings | Non-2xx, invalid JSON parsing and unexpected media still reject. Present, valid fields override defaults, including actual caps and zero values. Missing data and malformed nested fields produce the two distinct effects above. |
| Dark mode, shortcuts and accessibility | The round 3 change did not edit the theme CSS, global shortcut bindings or modal. Existing theme/navigation checks passed. A/O still bypass the category saving flag, like the equivalent buttons. Native disabled tag controls work during category save. The earlier contrast and keyboard-access issues remain. |

## 3. Component state

Queue selection invalidates on every query-changing control. Review has separate flags for loading, writing annotations and verifying, and the server's normal revision response takes a different path from the new browser fixture.

| Component | State transitions and evidence |
|---|---|
| Upload | A render closure supplies the import domain. Each batch gets a captured key and the same abort signal. Key changes clear private inputs and invalidate late analysis. Domain-only changes keep the original batch destination. Progress counts acknowledgments, which can undercount if the server committed before abort. CsvDropzone still accepts drops while busy, and HealthReport still lacks Upload's analysis generation. |
| ReviewCard | Dirty committed tags/spans hide the category selector and block verification. Their own saves set both flags and release them in finally. Category save sets only isSaving; verify sets only busy. Settled success/error paths release their flags, but a stalled request can hold them indefinitely. No common operation owner protects a newer mutation from an older finally or 409 reload. A typed, unadded tag is separate from tagsDirty. labeling_router.py:688 returns the **original** label ID on relabel. Detail follows supersession at line 742. With that response sequence Chromium refetched, redirected to the successor, and the draft tag input became empty. ReviewCard:50,158–160 preserves input only on the direct successor path. This is further evidence for R3-03. |
| ScoredQueue | Lines 42–65,75–108,146–158 include domain, category, raw/applied search, sort column/direction, page size and offset. Pending debounce masks stale rows, visible IDs intersect selection before submit, and refresh prunes vanished IDs. Preview is display-only and status is fixed. A prior bulk completion can still clear a newer selection within the same domain (R3-06a). |
| Settings | Valid usage from later refreshes wins over defaults. Focus/poll reads still resolve in completion order. Account/domain fetch failures clear state and show an error. Distinguish a valid null cap from a missing cap and validate present fields before rendering. |

## 4. Build and Playwright verification

The frontend no-emit check, production build and complete E2E no-emit check passed. The full browser run exposed a regression that both compilation and the five targeted tests missed.

| Check | Observed result |
|---|---|
| Frontend | From frontend, `npx tsc --noEmit` and `npm run build` exited 0. Vite transformed 451 modules. The localhost entry referenced the built index-i8Qz32pm.js and index-oDx11--j.css. |
| Discovery and spec compilation | `node node_modules/@playwright/test/cli.js test --list` produced 114 lines, 112 tests in 11 files. The frontend TypeScript compiler checked e2e/tsconfig.json with no errors. |
| Chromium | `npx playwright test --workers=3 --reporter=dot` ran 112 tests, zero retries. 110 passed and 2 failed in 36.3 s. All five in fix_round3 passed. |
| Docker | Dockerfile:1–6 uses node:22-slim, installs with npm ci and builds. The Python stage copies /app/frontend/dist from frontend-build. This verifies the build recipe. Container execution remains unverified. |

| New finding | Severity | Evidence and impact |
|---|---|---|
| R4-03 · Two incompatible bulk payload expectations | **P2** | components.spec.ts:240 and flows.spec.ts:68 expect only IDs and action. Both received the intended IDs plus `verified_outcome: true` and failed before their post-action assertions. fix_round3.spec.ts requires that same extra field. Align all three with the actual server contract and retain exact outcome and ID assertions. |

| Round 3 test | What it proves | Missing assertion |
|---|---|---|
| Bulk approve | Checks IDs, action and boolean on the wire. | The mock accepts any field name. Check parsed/persisted independent false, reject, and partial skips. |
| Late signup | Holds registration, navigates away, changes storage and checks the deferred receipt on return. | Same-route key reselection and later receipt invalidation. |
| CSV abort | Holds batch one and checks stop notice, file input, filename, report and scoring control. | Fill the text-task fields before rotation, and distinguish an acknowledged batch from an unknown commit. |
| Category save | Delays relabel and proves the tag input is disabled and survives a direct successor response. | Use the backend's original-ID POST then canonical detail response. Hold verify too, and exercise actual NER edits and keyboard approval. |
| Missing usage | Confirms the account and usage headings survive and the day placeholder appears. | Check whether displayed limits are truthful, malformed partial counters are contained, and a valid refresh restores actual counts. |

## 5. Remaining P2 and P3 findings

Three distinct round 3 P2 rows improved in part. The table uses round 3 ledger IDs for counting because some earlier S ranges combine multiple severities or map several issues to one row. None of the four round 3 P3s closed.

| Requested category | Change since round 3 |
|---|---|
| Accessibility S5.1–S5.6 | No earlier P2 closure or material improvement. Modal focus containment/return, keyboard span creation, stale picker, combobox arrow navigation, profile row activation, visible focus and sort/menu announcements remain (R3-16–20). |
| Dark mode S6.1–S6.3 | Unchanged. Heading/editor contrast and system theme tracking remain P2 (R3-21/22). Fixed chart, divider and popup colors remain P3 (R3-23). |
| State S2.3–S2.9 | **R3-05 improved** through per-file analysis generation on Upload. Drop while busy, uncertain commit and HealthReport analysis races remain. Mutation ownership, wrong-domain dashboard/profile display, settings refresh/save ordering, queue focus and optional fetch failures persist. The category lock is credited under its targeted P1. |
| Track 2 S4.1–S4.8 | No incidental closure. Escalation, status filtering, category/span eligibility, per-item bulk feedback, IAA and guidelines permissions remain. Tag comparison/length remains P3 (R3-15). |
| API S3.2–S3.4 | No incidental improvement. CSV error row offsets, slash IDs, response typing and media matching remain. Settings usage handling is credited under its targeted fix. R3-10 remains P3. |
| Playwright S8.2–S8.5 | **R3-25 improved** through a positive assertion that bulk sends an outcome-shaped field. **R3-26 improved** through held registration, abort cleanup, category-save timing and missing-usage fixtures. Neither verifies persistence. Weak conditional assertions, fixed waits and missing automatic server provisioning remain (R3-27/28). |
| Deployment | R3-24 remains P2. Building locally and inspecting the Dockerfile do not exercise the deployed container. |

## 6. Convergence and next work

**Not ready for Post-Track 2 baseline acceptance.** The five open frontend P1s are R3-01, R3-03, R3-07, R3-08 and new R4-01. No earlier P2 needs promotion on this evidence. R4-02 concerns misleading quota display, and R4-03 concerns a failing test gate.

| Priority | Work and acceptance check |
|---|---|
| 1 | Bind registration completion and receipt visibility to account/operation generation. Repeat A → B → A during registration and rotate once more after deferral. The chosen key/domain must survive and a later account must not see the prior receipt. |
| 2 | Agree on the bulk wire field and capture known truth independently where the ledger requires it. Use the real API to read back outcomes for approved rejections, explicit false, mixed truth and skipped rows. Align the two older assertions and rerun all 112 tests. |
| 3 | Share ownership and locking across verify, category and structured edits, including keyboard actions and stale callbacks. Re-run with both real revision response steps and preserve the draft through canonical navigation. |
| 4 | Validate account/usage at the API boundary, render unknown counts and limits explicitly, and isolate the formatter in a child of the boundary. Check absent, null, zero and populated counters followed by recovery. |
