# R5 findings — 26 November 2026

**PASS. Prompt 12 (release) is unblocked.** The final PostgreSQL gate passed 222 tests and Playwright passed 138. All 27 active scenarios passed. Six P1 and seven P2 findings were resolved. One minor guide navigation issue remains.

## Pre-check results

| Gate | Before fixes | After fixes |
|---|---:|---:|
| PostgreSQL, full requested selection | 221 passed, 16 deselected | 222 passed, 16 deselected |
| Playwright, full suite | 136 passed | 138 passed |
| mypy | Target path corrected, clean | Clean |
| Frontend TypeScript | Clean | Clean |
| F DDL and test-stub scans | Clean | Clean |

The PostgreSQL runs used `python -m pytest tests/ -q --timeout=120 -k "not exp_dlj"` without fail-fast. The 16 experiment tests also passed in a separate run. The project frontend built successfully. The final F-specific PostgreSQL run passed all 30 tests. The existing pytest-freezegun dependency emitted deprecation warnings.

## Files reviewed

The Prompt F session entry identifies 15 implementation and test files. The table includes those files plus the 12 release, scenario and neighboring implementation files read in full. Line counts refer to the final source. The design review used §§2 and 5 and the Prompt F session entry as authorities.

| File | Lines | Review focus |
|---|---:|---|
| `backend/static/dlj_client.py` | 183 | Redirect policy, safe retries, observed human outcome, streaming and atomic file output. |
| `jm_service.py` | 693 | Public guide shell, client download, OpenAPI and router registration. |
| `labeling_router.py` | 1802 | Project-scoped prediction listing, review payload, export and verification. |
| `webhook_router.py` | 314 | Delivery history, health, versions, admin authorization and secret presentation. |
| `frontend/src/pages/GuidePage.tsx` | 35 | Eight guide sections, mobile picker, verification and signing instructions. |
| `frontend/src/pages/PredictionReviewPage.tsx` | 115 | Queue queries, ownership checks, paging and mutation refresh. |
| `frontend/src/pages/IntegrationsSettingsPage.tsx` | 107 | Webhook changes, confirmation, health, attempt history and secret display. |
| `frontend/src/components/PredictionReviewCard.tsx` | 80 | Focus, modifier keys, current-revision span acknowledgement and action states. |
| `frontend/src/components/DeliveryHealthIndicator.tsx` | 11 | Empty, awaiting and active-delivery health. |
| `frontend/src/App.tsx` | 182 | Public and authenticated routes, account changes and route error handling. |
| `frontend/src/api.ts` | 473 | Validated DTOs, project requests and queue/webhook contracts. |
| `frontend/src/index.css` | 103 | Guide navigation, responsive layout, queue and integrations styling. |
| `tests/__init__.py` | 1 | Test package identity. |
| `tests/test_prompt_f.py` | 344 | 30 F PostgreSQL/API cases, including the client and real dispatch transitions. |
| `e2e/test_prompt_f.spec.ts` | 147 | 14 F browser cases, including focus, acknowledgement and webhook changes. |
| `tests/harness/scenarios/test_s01_s06.py` | 572 | Identity, admission, diagnostics and validation scenarios. |
| `tests/harness/scenarios/test_s07_s14.py` | 794 | Billing, cleanup and migration scenarios. |
| `tests/harness/scenarios/test_s20_s27.py` | 386 | Shared writes, conservation, quota and evidence scenarios. |
| `tests/harness/scenarios/test_s28_s32.py` | 289 | Browser identity, draft, navigation and recovery scenarios. |
| `Dockerfile` | 40 | Release-stage packaging of the downloadable client. |
| `billing.py` | 587 | Purchase-intent binding, provider entitlement transitions. |
| `auth.py` | 395 | Mailbox proof, key issuance and project membership. |
| `label_health/api.py` | 155 | Anonymous request admission and permit lifetime. |
| `scheduler.py` | 515 | Retention ordering and outbound delivery worker. |
| `db/repository.py` | 395 | Revision lineage and effective human evidence. |
| `webhook_security.py` | 87 | Secret encryption, signature format and outbound destination checks. |
| `frontend/src/operationContext.ts` | 50 | Credential, project and operation ownership. |

**Total: 27 files, 8855 lines.**

## P1 — blocks launch

| ID | Final file and line | Finding and fix | Verification |
|---|---|---|---|
| P1-01 | `jm_service.py:1`, `e2e/test_prompt_f.spec.ts:1` | The supplied mypy and browser-test scan paths did not match the checkout. A missing target invalidated the gate. Ran mypy against the actual Python client, service, labeling router, webhook router and F tests, and scanned the actual browser test file. | All five Python targets typecheck. Both F test files were scanned. |
| P1-02 | `Dockerfile:25` | The release image omitted the downloadable Python client. Added the client to the final image stage at the path the serving route resolves. | The download test checks the packaging instruction, content type and executable source. |
| P1-03 | `backend/static/dlj_client.py:106` | The client inferred ground truth from the action, so choosing approve could train the learner on an unobserved positive. Verification now requires an explicit boolean observation before dispatch. | Client quickstart exercises the real endpoint. The guide shows an approve action with a false observation. |
| P1-04 | `backend/static/dlj_client.py:43` | An authenticated request could follow a redirect with its custom API-key header. The client now rejects redirects before sending another request. | A transport probe checked redirect refusal. |
| P1-05 | `frontend/src/components/PredictionReviewCard.tsx:21`, `frontend/src/pages/PredictionReviewPage.tsx:79` | The UI asserted human span review without displaying the spans or obtaining acknowledgement. The queue now serves the current revision’s spans. The card displays them, ties acknowledgement to the revision and sends the actual flag. | The new NER browser case verifies that review is blocked before acknowledgement and that the submitted payload reflects it. |
| P1-06 | `frontend/src/components/PredictionReviewCard.tsx:34` | A modified keyboard shortcut such as Ctrl+A could accept a prediction and submit evidence. The handler now checks focus, modifiers, consumed events and repeated keystrokes. | The focused-card browser case distinguishes Ctrl+A from a deliberate A. |

## P2 — should fix

| ID | Final file and line | Finding and fix | Verification |
|---|---|---|---|
| P2-01 | `backend/static/dlj_client.py:43`, `:84` | Unkeyed writes could be retried, and a failed upload lost the information needed to reconcile a partial commit. Restrict retries to reads and replay-keyed writes, stream chunks and expose the confirmed count, failed chunk and replay key on failure. | Stable-body replay probe and client quickstart. |
| P2-02 | `backend/static/dlj_client.py:132` | Export consumers could retain an open stream or expose incomplete output. Close streamed responses, support compressed CSV decoding and publish file downloads via an atomic replacement after completion. | Interrupted-download probe preserved the existing destination. The quickstart consumes a real export. |
| P2-03 | `labeling_router.py:1457`, `:1699`, `frontend/src/pages/PredictionReviewPage.tsx:32` | Separately fetched origin lists did not provide a globally sorted, paginated queue. Unknown assessments could appear accepted, and an older fetch could overwrite a newer filter. Use a project-scoped mixed query, current-state projections, deterministic ordering, paging and request-generation checks. | Mixed-origin PostgreSQL test checks distinct pages and unknown assessment. Browser queue, review and navigation tests passed. |
| P2-04 | `labeling_router.py:1112` | The review API could receive competing decision forms or edits attached to an accept operation. Validate the decision form before review and return a validation error on contradiction. | Prediction review contracts and full PostgreSQL suite passed. |
| P2-05 | `webhook_router.py:137`, `:190`, `frontend/src/components/DeliveryHealthIndicator.tsx:1` | A new queued event could hide an earlier failure, endpoints with no evidence could count as healthy, and old attempts could display another attempt’s error or retry information. Use the latest actual attempt for the current endpoint version, separate awaiting status and return attempt-specific details. | Real worker failure followed by successful retry changes health. Browser checks cover the integrations display. |
| P2-06 | `frontend/src/pages/GuidePage.tsx:30`, `frontend/src/pages/IntegrationsSettingsPage.tsx:12`, `webhook_router.py:66` | Integration guidance omitted the actual signature framing and misrepresented pending delivery behavior on rotation. The guide identifies the header, exact signed bytes and deduplication key. Rotation warns about cancellation, and the API gives a rotation date only when the stored versions establish it. | Compared with the signer and dispatcher. Rotation test checks the previous delivery’s state. |
| P2-07 | `tests/test_prompt_f.py:247`, `:308`, `e2e/test_prompt_f.spec.ts:125` | The quickstart and recovery checks could pass without exercising the downloaded client or actual delivery transitions. Browser coverage also left endpoint editing and test-send unchecked. Exercise the client over loopback, run the worker for both delivery attempts, and check edit, test-send and deactivation in the browser. | 30 F PostgreSQL tests and 14 F Playwright tests passed. |

## P3 — minor

1. `frontend/src/pages/GuidePage.tsx:10` records a section in the hash query when selected. A fresh visit to that URL does not explicitly restore the section or synchronise the mobile picker. In-page navigation and the responsive dropdown work. This is a deep-link usability issue.

## Scenario verification

All 27 canonical tests are active. These references point to the tests in `tests/harness/scenarios/` that exercise the oracle. The shorter companion tests in the F module provide additional coverage.

| Scenario | Canonical test | Assertion checked | Result |
|---|---|---|---|
| S1 | `test_s01_s06.py:34` | A mismatched proof cannot claim the mailbox. Confirmation issues the active credential. | Pass |
| S2 | `test_s01_s06.py:108` | Racing confirmations leave one credential. The mail observer sees committed state. | Pass |
| S3 | `test_s01_s06.py:156` | Concurrent intake bounds admitted and waiting work. Refusal, disconnect and recovery release capacity. | Pass |
| S4 | `test_s01_s06.py:377` | Captured application, ASGI and scheduler diagnostics exclude untrusted driver values. | Pass |
| S5 | `test_s01_s06.py:442` | Malformed connector data fails before entitlement lookup. Database and quota readbacks remain unchanged. | Pass |
| S6 | `test_s01_s06.py:500` | Boundary identifiers succeed on create and reuse. Oversized identifiers return validation errors. | Pass |
| S7 | `test_s07_s14.py:28` | With two keys and an existing customer, only the intended payer receives the subscription. | Pass |
| S8 | `test_s07_s14.py:131` | Current subscription status determines capacity. Events for a replaced subscription cannot change it. | Pass |
| S9 | `test_s07_s14.py:186` | Unknown, delayed and duplicate events preserve the current watermark and do not duplicate notifications. | Pass |
| S10 | `test_s07_s14.py:266` | Separate connections exercise both orders. Renewal-first retains data and cleanup-first leaves a tombstone. | Pass |
| S11 | `test_s07_s14.py:463` | Key issuance and rotation serialize with tenant cleanup. An entitled sibling retains its domain. | Pass |
| S12 | `test_s07_s14.py:548` | Cleanup removes one expired tenant once and preserves the other tenant’s data. | Pass |
| S13 | `test_s07_s14.py:634` | Two migrations preserve provider linkage or record quarantine, with independent stored-state checks. | Pass |
| S14 | `test_s07_s14.py:737` | Quota summary and last permitted reservation agree across UTC day and month boundaries. | Pass |
| S20 | `test_s20_s27.py:24` | Both adapters gain the new category, attribute review and update learning and conservation. | Pass |
| S21 | `test_s20_s27.py:61` | Structured revisions preserve lineage, actors and source identity through interleaved connector deliveries. | Pass |
| S22 | `test_s20_s27.py:134` | Concurrent creation converges or returns conflict. Independent readback verifies one domain and engine. | Pass |
| S23 | `test_s20_s27.py:173` | At 49 reservations, concurrent scores produce one success and one refusal. Usage ends at 50. | Pass |
| S24 | `test_s20_s27.py:210` | Competing relabel and verification requests leave one successor and consistent learning evidence. | Pass |
| S25 | `test_s20_s27.py:285` | Two connector processes write distinct project configs. Reload from storage retains both. | Pass |
| S26 | `test_s20_s27.py:313` | The verified negative remains effective across revisions and category reversion until fresh adjudication. | Pass |
| S27 | `test_s20_s27.py:352` | Persisted per-item actions and outcomes agree with learner trackers. The skipped item stays pending. | Pass |
| S28 | `test_s28_s32.py:27` | A held signup response cannot replace the active key after either same-tab or cross-tab rotation. | Pass |
| S29 | `test_s28_s32.py:68` | Rotation between real import chunks leaves the committed prefix with the old owner and clears the new owner’s file. | Pass |
| S30 | `test_s28_s32.py:112` | Delayed detail, search and bulk responses with colliding public IDs cannot cross project ownership or expose review data in history. | Pass |
| S31 | `test_s28_s32.py:222` | The tag draft survives a category save and a declined navigation. Competing edits are locked. | Pass |
| S32 | `test_s28_s32.py:269` | Invalid JSON and a failed lazy chunk produce scoped errors. Navigation and retry recover. | Pass |

## Prior launch-blocker spot-check

| Finding | Implementation | Observed protection |
|---|---|---|
| R02 purchaser binding | `billing.py:218` | Provider activation reconciles checkout intent, payer and tenant. S7 checks the intended key in a two-key tenant. |
| R08 unverified signup | `auth.py:52`, `:82` | Registration starts mailbox proof. Atomic proof consumption and commit precede credential issuance. S1 and S2 passed. |
| R09 admission | `label_health/api.py:93` | Admission precedes expensive parsing. Request and waiter bounds plus permit release are exercised in S3. |
| R14 retention and reactivation | `scheduler.py:358` | Tenant serialization and key revalidation precede destructive cleanup. S10–S12 cover both orderings and sibling data retention. |
| R45 revision evidence | `db/repository.py:232` | The effective evidence query retains a verified predecessor until an adjudicated descendant supersedes it. S26 checks both sides of the transition. |

## Cross-cutting and final verification

- Project prediction routes use project membership and review permissions. Webhook management, health and attempt history pass through the project admin check. Tests cover missing credentials, a foreign project and insufficient role. Guide, Swagger, OpenAPI and client download are intentionally public. API mutations require explicit credentials.
- Webhook list and health responses mask or omit secret material. Creation and rotation provide the one-time secret. Project and credential changes invalidate UI operations. The guide now matches the outbound signer.
- The queue and integration APIs use the existing prediction, label, content, endpoint, delivery and attempt tables. F introduced no migration or DDL. The F tests contain no stubs or demo reset calls.
- The final functional source was reread after edits. The browser suite exercised responsive guide navigation, review focus, span acknowledgement, queue actions and webhook management. The browser F tests use controlled API responses. The PostgreSQL harness independently exercises actual routes and the delivery worker with controlled external responses.
- The release packaging check verified the Dockerfile and the download route. This review did not build or deploy the Railway container or contact a live outbound webhook provider.

**Verdict: PASS.** All P1 and P2 findings are resolved, the required regression suites are green, and Prompt 12 can start.
