# DLJ convergence sweep 5 — backend and frontend

24 November 2026 · jm-service · HEAD `ebf6cbc` · current working tree

| Gate | Round 5 result |
|---|---|
| Round 4 fixes | **6 CLOSED of 10, 4 PARTIAL, 0 OPEN, 0 REGRESSED**. The ten independently graded deliverables are in §1. |
| Frontend P1s | **2** — stale signup adoption after rapid cross-tab rotation (R3-01) and loss of a review draft (R3-03). |
| Backend P1s | **15** — **2 patchable + 10 structural launch blockers + 3 accepted for v1.1**. R13 and R45 each appear once in the structural count. |
| Test suites | **432 pytest passed, 0 failed, 1 skipped** of 433 collected. **118 Playwright passed, 0 failed, 0 skipped** in 12 spec files. The round 4 module also passed **10/10 on PostgreSQL**. |
| Merged execution plan gate | **NOT READY for Prompt 00 under the stated gate.** Both suites passed. The frontend still has two P1s, two inherited backend defects are patchable, and four round 4 deliverables have residual gaps. |

The normal browser now sends the reviewer’s chosen truth value all the way to the learner and the stored label. Two independent checks explain why green suites did not establish convergence. A real database revision increased the annotator profile’s accuracy from 50% to 100% without any new verification. Chromium also discarded a typed tag when a relabel used the server’s actual response sequence.

## 1. Round 4 fix verification

The denominator counts four prior backend partials, the separate upload timeout, signup epoch, signup receipt, review mutation/draft handling, Settings null handling and the pair of repaired browser assertions. The shared bulk wire fix is counted once. CSV cleanup was already closed before this round and is rechecked in §2. A fix can close its named wire defect while an older, wider launch requirement remains open.

| Deliverable | Verdict | Independent evidence |
|---|---|---|
| R13 · explicit bulk outcome on the browser path | **CLOSED** | Both names and values agree at every hop below. An explicit false survives the server’s fallback check. The optional legacy path is still a structural issue. |
| R45 · preserve negative evidence across revisions | **PARTIAL** | Reordering tags is a no-op. Establishing explicitly empty typed content is a change. The scoped recursive predicate preserves the negative through unverified descendants and retires it after a verified replacement. The annotator projection still excludes the predecessor before aggregation at `dashboard_router.py:269–274`. Its displayed accuracy can improve without verification. |
| R03 · connector successor content and provenance | **CLOSED** | `db/repository.py:128–135,252–286` copies structured content including the image URL, text and source identifiers, sets the backward pointer, tenant actor and revision timestamp, and links the predecessor in the same transaction. The image/provenance test inspects the two stored rows. This establishes the contract for new corrections. |
| R09 · bound bytes before multipart spooling | **CLOSED** | `label_health/api.py:84–110` rejects oversized declared lengths and counts cumulative bytes actually received, before handing each chunk to the parser. The whole request is limited to 10 MiB plus 64 KiB of multipart allowance. The selected CSV has its own 10 MiB limit. |
| S4-01 · intake deadline and permit release | **CLOSED** | `label_health/api.py:48–81,95–123` starts one 30-second budget at admission, wraps form parsing in `asyncio.wait_for`, then wraps the selected file read with the remaining time. Either stall returns 408 and releases the permit. After executor submission, the completion callback owns release, including when the 60-second result wait expires. |
| R3-01 · signup epoch | **PARTIAL** | `Signup.tsx:37–51,64–75` invalidates on observed account changes and unmount. `App.tsx:37–42` checks only the currently stored value before notifying Signup. A sequence of cross-tab writes can leave the old generation valid. See §2. |
| R4-01 · invalidate stored signup receipt | **PARTIAL** | `Signup.tsx:6–18,37–43,74–80` binds restoration to the starting key. This closes the prior different-account disclosure. `App.tsx:37–45` can skip both invalidations on a rapid round trip. The old same-key receipt can remain restorable. This narrower retention defect is below P1 and shares R3-01’s event handling. |
| R3-03 · review mutation lock and draft preservation | **PARTIAL** | All four writes acquire and release the common lock. The remaining loss is a draft typed before the write. `ReviewCard.tsx:58–76,89–93,168–171` clears it during canonical successor navigation. Confirmed in Chromium. |
| R3-08 · null usage | **CLOSED** | `api.ts:249–256` and `Settings.tsx:129–139` handle missing usage and coalesce each of its six fields. Both new malformed-usage browser cases passed. Displaying an unknown paid cap as unlimited remains a separate P2. |
| R4-03 · two exact browser payload assertions | **CLOSED** | `e2e/components.spec.ts:234–244` and `e2e/flows.spec.ts:64–69` both select a known outcome and assert exact IDs, action and `outcome: true`. Both passed. |

**Field names in the bulk path**

| Hop | Field and meaning |
|---|---|
| Reviewer → queue | `bulkOutcome` is required separately from the approve/reject button. `ScoredQueue.tsx:147–155,186` builds `outcome: bulkOutcome === 'correct'`. There is one truth selection per batch. Mixed truths require separate selections. |
| API client → HTTP JSON | `api.ts:210` requires `body.outcome: boolean` and serializes `json(body)`. The JSON property is **`outcome`**. |
| HTTP JSON → request model | `labeling_router.py:140–145` declares **`BulkVerifyRequest.outcome`**, optional for older clients. |
| Bulk → individual verification | `labeling_router.py:481–488` reads **`payload.outcome`** and passes **`VerifyRequest.verified_outcome`**. It derives from action only for `None`. It independently computes `actual_action` from the recommendation. |
| Verification → repository | `labeling_router.py:424–429` passes **`request.verified_outcome`** to **`verify_and_learn(..., verified_outcome, ...)`**. |
| Repository → learner and label | `db/repository.py:289–316` calls **`engine.learn(outcome_correct=verified_outcome)`**, computes `confirmed` separately from action agreement, and calls **`record_verification(..., verified_outcome, ...)`**. Line 147 sets **`LabelLog.verified_outcome`**. Engine and row writes use the caller’s transaction. |

**Two qualifications to the prior code audit.** The dashboard overview, category statistics and repository accuracy use the effective evidence predicate. The annotators query also imposes a current-row filter. For uploads, the installed Starlette parser closes partial files on parsing exceptions, and the application releases the permit if the required file field is missing. A *successfully parsed* form containing uploads under other field names reaches the 422 at `label_health/api.py:115–119` before the `form.close()` block at lines 120–123. Explicit cleanup on that validation branch is missing. Neither the byte limit nor permit release depends on that close.

## 2. Frontend P1 convergence

**Two distinct frontend P1s remain.** The five user-requested rechecks include CSV cleanup, which was already closed. The five actual P1s on the round 4 frontend ledger included the deferred receipt instead. Both are covered here.

| Round 4 concern | Current result and impact |
|---|---|
| Bulk truth (R3-07) | Closed for the UI. Approve/reject remains the reviewer’s decision on the recommendation. The separately selected truth reaches the learner. Selection changes reset the outcome. No additional UI P1 found. |
| Late signup (R3-01) | **P1 remains.** The same-tab path advances the epoch. The cross-tab listener can miss an intervening account change. A late signup can still replace a deliberately reselected key and erase the selected domain. This is a source-based ordering finding. |
| CSV residue (R3-02) | Closure retained for an observed rotation. `Upload.tsx:27–46,92–130` invalidates late analysis, aborts the import, clears file/report/progress/sample and all task inputs, and remounts the file picker. Every batch is bound to the captured key. The shared cross-tab notification limitation belongs to R3-01. |
| Tags during review (R3-03) | Mid-request editing is blocked. **P1 remains** for silent loss on the normal revision path. The component’s dirty predicate also omits a nonempty tag input until the user adds the chip. |
| Settings (R3-08) | Null-counter crash closed. `labels_today` and `labels_this_month` default to 0, `daily_cap` and `monthly_cap` to null, and `day_key` and `month_key` to a dash. Rendering uses those aliases. A successful response missing usage can still display zero usage and “Unlimited” for a paid account. HTTP failures still surface. Track this as R4-02/P2. |
| Stored receipt (R4-01) | The original disclosure under a different credential is closed. A surviving receipt after a missed round trip requires the *same* starting credential to restore. Count its residual invalidation gap once at the fix level and exclude it from the P1 total. |

**Signup epoch and receipt lifetime.** Let the epoch be 0 on a mounted Signup. Submit increments it to 1. Committing B in the sidebar sends the synchronous key event and increments it to 2. Committing A increments it to 3. The response carrying 1 exits before writing a credential. Signup remains mounted on this route. Leaving it unmounts the component, increments its epoch and invalidates the old closure independently of the next mount. The published browser test navigates away before rotating, so unmount alone can make it pass.

With two tabs, each storage notification rereads the live value. If B and then A are written before the receiving tab handles the first notification, both handlers can see A equal to `activeKey.current`. Neither emits `dlj-account-changing`. The submitter still has epoch 1 and matching starting key A. The generation guard therefore allows stale adoption. Treat every relevant credential transition as invalidating an operation, including when the value observed at delivery has returned to its initial value.

The receipt lives in React state and in tab session storage under `dlj-deferred-registration` as `{result, startingKey}`. Restoration checks current local storage. Observed sidebar commits and Settings save/clear (`Settings.tsx:95–101`) use the same App invalidation as an observed cross-tab change. App removes the stored receipt even when Signup is unmounted. Mounted Signup also clears visible and stored state. Navigation alone discards component state and invalidates a pending submit, but deliberately permits restoration of a matching stored receipt on return. Activation removes deferred storage. The equality short-circuit is the gap in an all-account-changes guarantee.

**Mutation ownership.** Only `startMutation` sets `isMutating` true. It takes a synchronous ref lock and aborts the older detail read. `saveSpans`, `saveTags` and `submit` (approve or override, button or shortcut) release it in their respective `finally` blocks at `ReviewCard.tsx:94–149`. `CategorySelector.submit` acquires through the parent’s `onSavingChange(true)` and releases in `finally` after the save and refetch at `CategorySelector.tsx:28–40`. Tag input, chips and suggestions, NER edit handlers and popup controls, CategorySelector’s inputs and submit, and both editor save buttons honor the disabled state. Verify buttons use busy/dirty/outcome checks and their handler checks the synchronous lock even when a category save leaves a button visually enabled. Outcome/override selectors can still change local selection. Escalate only posts a local message. Settled success, conflict and error paths release the lock. A network call that never settles can keep it held.

**Observed draft loss.** The canonical relabel response returns the requested predecessor ID and the successor’s revision UUID (`labeling_router.py:685–694`). Detail follows the predecessor to the successor (`labeling_router.py:747–753`). `afterCategorySaved` preserves typed input only when the POST immediately returns a different label ID. On the real contract it refetches, redirects in `load`, then clears the draft in the route effect. An independent Chromium check used the served bundle and stubbed these two responses to match the server. The typed value became an empty string on the successor. The existing passing test returns the successor ID directly. The lock itself introduced no additional P1 in this review.

## 3. Backend P1 disposition

The round 4 ledger had 17 P1s. R09 and S4-01 exit P1. R03 was already below P1 and its remaining provenance issue is now closed. R45 and the compatibility part of R13 remain open. This yields **15**. The buckets below are mutually exclusive. The plan owns R45 under shared writes even though its remaining projection error is a local repair.

| ID | Since round 4 | Evidence, remaining impact and owner |
|---|---|---|
| R02 | UNCHANGED | `billing.py:70–85,120–138` carries the purchasing key but returns an existing customer match first. Two keys for one tenant can receive the wrong entitlement. Prompt 02. |
| R04 | UNCHANGED | `label_studio.py:135–144`, `db/repository.py:23–31,49–66` check for absence before first domain/engine insertion. Conflict handling differs across writers. Prompt 05. |
| R05 | UNCHANGED | `labeling_router.py:565–595`, `label_studio.py:263–276,305–321` allow persisted public domain, source or reviewer IDs outside the bounded request models. PostgreSQL can reject a value SQLite accepted. Prompt 03. |
| R06 | UNCHANGED · accepted | `jm_service.py:541–551,596–605` persists the legacy decision and engine snapshot separately. v1.1 acceptance depends on legacy isolation and the stated absence of known external consumers. |
| R07 | UNCHANGED · accepted | `jm_service.py:64–95,436–447` stores the legacy bearer as identity. Continued isolation and protection of the store and backups are conditions of v1.1 deferral. |
| R08 | UNCHANGED | `auth.py:47–66` issues and returns a working key before mailbox verification. Prompt 03. |
| R19 | UNCHANGED | `billing.py:180–185,214–235` acknowledges unsupported event types and represents subscription and cancellation on one key row. Replacement/reactivation lacks a complete entitlement lifecycle. Prompt 02. |
| R23 | UNCHANGED | `db/migrate.py:118–145` renames historical provider columns only on PostgreSQL. On SQLite, a repeatable migration can still leave the new columns empty alongside the historical values. Prompt 02. |
| R24 | UNCHANGED | `scheduler.py:66–76` serializes SQLite retention. Ordinary quota and revision writes at `trial_guard.py:72–103`, `labeling_router.py:608–611,679–686` still rely on row-lock assumptions. Prompt 05. |
| R29 | UNCHANGED | `label_studio.py:32,165–185` atomically replaces the config file under an interpreter-local lock. Multiple processes can lose a committed project update. Prompt 05. |
| R30 | UNCHANGED · accepted | `jm_service.py:175–181,327–339`, `jm_core.py:200–206,348–350` reject the separator for new legacy domains but retain ambiguous keys in old snapshots. v1.1 under the same legacy isolation assumption. |
| R45 | IMPROVED · **still P1** | `db/repository.py:154–191` and `labeling_router.py:291–300,641–652` repair category evidence and no-op detection. `dashboard_router.py:265–274` still drops a superseded verified negative from the annotator’s accuracy. Prompt 05/S26 must cover this public projection. |
| R13 | IMPROVED · **still P1 for legacy learning** | `labeling_router.py:144,483–487` learns action-derived truth when `outcome` is omitted or null. The current UI sends independent truth. Prompt 05 with 04/S27 must settle legacy semantics before certifying the plan’s requirement that learning requires independent evidence. |

**Patchable carryovers outside those 13 IDs.** N02 remains at `db/connection.py:37–62` and `scheduler.py:119`. The outer engine allows exception parameters, the dependency rethrows, and the scheduler logs full exceptions. A sanitized inner batch warning does not cover these paths. N03 remains at `label_studio.py:253–256`. Top-level action dispatch performs set membership before checking the value’s type, so a malformed event can become an unhandled server error. Both belong to Prompt 03 in the merged plan and count only in the patchable bucket. No independently new backend P1 was established in the round 4 diff.

**Measured R45 impact.** A disposable SQLite database contained one annotator with two verified labels, one correct and one incorrect. Before correction, the profile and overview both returned count 2 and accuracy 0.5. After a category revision of the incorrect label, with its successor still unverified, the profile returned **1 and 1.0** while overview returned **2 and 0.5**. The stored negative survived. The annotator-facing performance figure silently improved. Compute active work-item counts and effective verified evidence separately, and compare projections before and after the successor is verified.

## 4. Test suite health

| Run | Observed |
|---|---|
| Default pytest collection and full run | 433 collected. **432 passed, 0 failed, 1 skipped** in 198.14 s. Used `--timeout=30` and excluded the three Docker live modules and `test_ops_e2e.py`. The default SQLite lane excludes the PostgreSQL-only UTC migration case by its dialect guard. |
| PostgreSQL round 4 module | **10 passed** in 16.45 s with `DLJ_DATABASE_URL` selecting local PostgreSQL. The fixture forwards it to the private-schema test client. Three intake tests are database-independent. This was a focused PostgreSQL run. |
| Playwright discovery and execution | **118 discovered and 118 passed**, 12 files, Chromium, three workers, zero retries, 40.0 s. The served JS asset at localhost:8080 matched the local production bundle byte-for-byte. The two formerly failing exact-body tests passed in that run. |

| `test_round4_fixes.py` case | What it establishes | Missing distinction |
|---|---|---|
| `test_bulk_outcome_field_reaches_verified_label` (two cases, line 19) | Posts through the DTO and reads persisted detail. | Approve/true and reject/false both equal legacy fallback. Both pass if `outcome` is ignored. Earlier explicit-false backend coverage and the mocked browser reject/true case are complementary. S27 still needs one real UI/API run checking learner trackers and skipped IDs. |
| `test_reordered_tags_do_not_create_revision` (29) | Equivalent tag sets return 409 and preserve revision identity. | No positive membership-change assertion in this case. |
| `test_empty_ner_content_is_a_real_revision` (44) | Plain text can acquire empty NER content. | Checks resulting type only. Add successor identity and the empty multilabel counterpart. |
| `test_negative_evidence_remains_until_replacement_verified` (53) | Repository evidence for category A retains its negative until the verified B replacement. | No annotator profile or dashboard response assertion. |
| `test_verified_evidence_uses_latest_verified_descendant` (75) | A two-revision chain returning to category A changes evidence only after adjudication. | Also tests only the repository projection. Both evidence tests pass with the measured profile error. |
| `test_connector_revision_copies_image_and_provenance` (100) | Reads stored child content, image URL, predecessor pointer, actor and timestamp. | Verifies new revisions. It does not repair or assess historical missing provenance. |
| `test_stalled_multipart_releases_admission_slot` (120) | A delayed receive really times out with 408 and restores the semaphore. | No second valid request or partially spooled upload is observed. |
| `test_stalled_file_read_releases_admission_slot` (136) | A delayed file reader consumes the remaining budget and releases the pre-acquired permit. | Uses an isolated fake reader. No combined parse-plus-read timing assertion. |
| `test_streamed_multipart_total_limit_releases_slot` (158) | Rejects an oversized request without Content-Length and restores the permit. | The body arrives as one chunk. Several individually small chunks, multiple fields and wrong-field cleanup are missing. |

The signup epoch browser test unmounts before rotation, and its final equality check can already hold before the late response runs. The receipt test completes ordinary signup, which removes deferred storage, then rotates. It never establishes a nonempty deferred entry as its precondition. The held-verify test exercises disabled controls during the request. The category test mocks a direct successor response; the API returns the predecessor. Add a mounted two-tab lifecycle case, a genuinely deferred receipt followed by a rotation, the canonical draft sequence, and API assertions comparing overview and annotator figures. These cases distinguish the four partial fixes from the paths already covered.

## 5. Merged execution plan readiness

**NOT READY.** The green-suite condition is satisfied. The zero-frontend-P1, no-patchable-P1 and no-partial-fix conditions are unmet. The round 4 recommendation to begin harness work used a different gate.

| Precondition | Decision and acceptance evidence |
|---|---|
| Freeze wire contracts | Freeze the explicit bulk JSON field and distinguish it from the individual verify field. Resolve omitted/null learning semantics before freezing S27. Capture the real relabel POST followed by canonical GET in the fixture contract. |
| Representative fixtures | Retain the isolated database fixtures and both production-bundle payload tests. Extend S28 to cover mounted cross-tab generation changes and stored receipts, S31 to cover canonical navigation with a draft, and S26 to cover the annotator read model. |
| Repeatable schema | Current schema-repeat coverage exists at `test_migration_fixes.py:186`. A second successful DDL pass cannot prove preservation of provider bindings. Prompt 02/S13 needs old SQLite and PostgreSQL datasets with known customer/subscription mappings. |
| Prompt 02 readiness | Resolve the ownership conflict between customer and purchasing key, event ordering/unsupported subscription states, and the historical provider backfill before enabling paid project transitions. Preserve retention serialization while aligning transition lock order. The Dockerfile builds and copies frontend assets. This review did not exercise Railway or a live Paddle delivery. |

Reopen the Prompt 00 gate after the account-generation and draft paths are covered, the annotator projection agrees with effective verified evidence, and N02/N03 have passing outer-boundary checks. Re-run the two suites against the corrected build. Keep the structural launch gates for Prompts 02–05 and the three explicitly accepted legacy risks visible separately. [Merged execution plan](../design/dlj_arch_redesign_v2.md)
