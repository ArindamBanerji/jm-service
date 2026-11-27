# Sprint 0 review — 26 November 2026

**Result: PASS.** PostgreSQL passed 251 tests and Playwright passed 160. The review fixed 15 findings in sampling, SLA reporting and the walkthrough. The frozen engine SHA-256 matched before and after the review.

## Bugs found and fixed

| # | Final source | Failure and fix |
|---|---|---|
| 1 | `labeling_router.py:1208` | Requesting 500 rows returned a validation error. Positive requests now return at most 200 rows. Zero and negative sizes still fail validation. |
| 2 | `labeling_router.py:1228`, `frontend/src/screens/ScoredQueue.tsx:99` | Smart search and pagination operated on the first 200 previews. A match beyond page 1 or after character 100 could disappear. Filter the full project and source text before ranking, and return the filtered total and absolute ranks. |
| 3 | `labeling_router.py:1170` | Named annotators could remain in warmup indefinitely because sampling loaded only the unnamed engine. Unknown categories or unusable centroids could produce a failure, a nonfinite distance or a fabricated large distance. Count project training, match each row to its engine, and use a nullable distance when no valid comparison exists. A trained empty queue retains its strategy. |
| 4 | `labeling_router.py:1236` | A one-row smart request loaded every full pending document into memory. Stream ranking inputs and truncated previews from PostgreSQL, retaining at most the requested offset plus page size in the ranking heap. Exact ranking still examines the filtered candidates. |
| 5 | `frontend/src/screens/ScoredQueue.tsx:45` | Navigation discarded the reviewer's choice, a late warmup probe could override it, and random fallback turned the toggle off. Remember each project's preference in the tab, discard stale ranking responses and allow a warmup sample to remain selected. |
| 6 | `frontend/src/screens/ReviewCard.tsx:221` | After the first review from the smart queue, the next label came from ordinary pending order. Carry the ordering choice in the route and read the next priority after verification commits. Check request ownership before navigating. |
| 7 | `labeling_router.py:1269` | Project SLA used the unnamed engine's recommendation-agreement rate. An incorrect label could count as correct, and named reviewers' evidence could disappear. Use the current effective human outcomes from all project reviewers, ordered by verification time, for the rolling accuracy. The evidence and conservation states come from one SQL statement. |
| 8 | `labeling_router.py:1294` | A negative margin could coexist with an active automation flag, and flags ignored payer eligibility. Compare the unrounded margin with the floor, respect conservation gates and require an active project and eligible paid payer before reporting automation active. |
| 9 | `auth.py:262` | A non-member reading an existing project's SLA received the wrong status for this endpoint. The SLA now returns 403. A missing project returns 404, and a foreign sampling request retains the existing concealed 404 response. |
| 10 | `frontend/src/api.ts:259`, `frontend/src/components/SLABadge.tsx:5` | Malformed measurement fields could reach numeric rendering. The badge also labelled a critical margin as paused and had no margin tooltip. Validate the response fields and states, distinguish critical from paused and expose the margin on hover. |
| 11 | `frontend/src/pages/QuickstartPage.tsx:35` | A blank name silently created a default project. Mutations and form edits could race an account or domain change. Block blank names, lock submitted fields, capture each operation's identity, check it after awaits and release the controls when the request is invalidated. |
| 12 | `frontend/src/pages/QuickstartPage.tsx:57` | Oversized input could be silently truncated or rejected by the smaller API limit. Retrying a committed upload with a lost response generated fresh identifiers. Validate 1–100 items, preserve input on rejection, and reuse the same item IDs, body and replay key for an unchanged upload. |
| 13 | `frontend/src/pages/QuickstartPage.tsx:76` | Splitting CSV on commas corrupted quoted text. An unfinished file read could also race Upload. Use the existing CSV parser, bound file size, surface read and format errors, and wait for the selected file to finish reading. |
| 14 | `frontend/src/pages/QuickstartPage.tsx:69` | The walkthrough treated agreement with a recommendation as the label's ground truth. It also allowed selection to change during verification or after completion. Show the source text and assigned category, ask about correctness, record the corresponding action and observed outcome, and lock selection during and after the write. |
| 15 | `frontend/src/pages/GuidePage.tsx:17`, `frontend/src/pages/QuickstartPage.tsx:119` | The guide had no walkthrough entry, the completion links lost their intended guide sections, and the newly created project's dashboard was hard to reach. Link the guide and walkthrough in both directions, restore section targets, link directly to the project and focus the active step. |

## Tests added

- **19 backend tests** in `tests/test_sprint0_extended.py`. Eighteen exercise real PostgreSQL routes or stored state. One checks nonfinite numerical inputs directly. Coverage includes cap-plus-one pagination, search beyond the preview, stable ordering, parallel reads, verified-row exclusion, tenant isolation, missing projects, accuracy and margin changes, gate trip and recovery, expired payer behavior, replay and malformed geometry.
- **18 Playwright tests** in `tests/e2e/test_sprint0_extended.spec.ts`. All 15 requested journeys or spot checks run with the built React app and real project-scoped API. Three additional cases cover quoted CSV with a response lost after commit, correcting oversized input without a partial write, and changing domain during project creation.
- The browser fixture uses a disposable PostgreSQL schema per worker, an ephemeral loopback port and the actual dispatch worker. The prediction journey starts from an autonomous project seeded with prior evidence. The webhook journey substitutes destination resolution and the external HTTP send, then checks the actual attempt history and health response.
- Existing SLA fixtures now include persisted verified labels. The Playwright configuration discovers both browser-test directories. Two existing Prompt F browser-test typings were corrected so the expanded browser suite also typechecks.

## Final counts

| Check | Measured baseline | Final |
|---|---:|---:|
| PostgreSQL gate | 232 passed, 16 deselected | 251 passed, 16 deselected |
| Playwright | 142 passed | 160 passed |
| TypeScript | Clean | Frontend and E2E clean |
| mypy | Sprint 0 router clean | Application targets and changed Python tests clean |
| Frontend production build | — | Passed |

The backend lives at the repository root. The mypy check used the real service, routers, database and label-health packages. The walkthrough's demo writes and the browser tests ran against isolated local data. No migration or DDL changes were made. The `jm_core.py` SHA-256 remained `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.
