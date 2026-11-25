# DLJ convergence sweep 7 — backend and frontend

25 November 2026 • jm-service working tree, including the uncommitted round 6 changes • **Prompt 00: NOT READY**

| Round 6 repair | Verdict | Deciding observation |
|---|---|---|
| B6-01 · commit before success | **CLOSED** | Application writes commit inside their handler or an awaited transaction context. Bulk has one outer commit. |
| N02 · database diagnostics | **PARTIAL** | Ordinary bound parameters disappear. The formatter still copies tokens from arbitrary driver messages. Some failures bypass the formatter entirely. |
| B6-02 · connector redelivery | **PARTIAL** | Ordered, dated replay works. A genuine undated reversal can be acknowledged and discarded. A revision can also lose the ordering watermark. |
| B6-03 · billing intake | **PARTIAL** | The 64 KiB observed-byte limit and signature input are correct. The time and concurrent-admission requirements in sweep 6 §6 remain open. |
| R3-03 · review drafts | **PARTIAL** | Save Tags preserves the next typed tag on successful canonical navigation. Category draft, conflict and manual-navigation paths can still discard edits. |
| F6-01 · whole-store clear | **CLOSED** | Both key removal and a whole-store clear trigger account invalidation and receipt cleanup. |
| F6-02 · source file in browser history | **CLOSED** | History holds an opaque file reference. A consumed or previous-owner reference cannot reconstruct a File on Back. Queue history has a different disclosure, F7-01. |

| Scorecard | Result |
|---|---|
| Fix verification | **3 CLOSED, 4 PARTIAL** |
| Newly recorded BE findings | **P1=1, P2=3, P3=0** |
| Newly recorded FE findings | **P1=1, P2=4, P3=0** |
| Definitive P1 ledger | **18 open** = FE patchable **2** + BE patchable **4** + BE structural **9** + BE accepted for v1.1 **3** |
| Test suites | Configured pytest **443 passed, 0 failed, 1 skipped**. SQLite pytest **442 passed, 1 failed, 1 skipped**. Playwright **124 passed** of 124 listed. |
| Self-check | **76/76** files in the primary reading inventory, **46/46** application method/path registrations, **22/22** write-capable registrations including external checkout. Three legal routes are deliberately absent from OpenAPI. |

New-finding totals count distinct IDs first recorded here. Inherited P1s and new failure modes of the same P1 are counted once in the definitive ledger. This is a source and local test audit. Production ingress configuration, billing events and customer data were outside the evidence set.

## 1. Independent verification of the seven fixes

### B6-01 · request completion and durability

Full dependency cleanup, `db/connection.py:115–127`:

```python
            yield session
        except SQLAlchemyError as exc:
            try:
                await session.rollback()
            except Exception:
                pass
            raise RuntimeError(f"Database operation failed: {sanitize_database_error(exc)}") from None
        except BaseException:
            try:
                await session.rollback()
            except Exception:
                pass
            raise
```

Normal exit closes the async session through its context manager. There is no successful-path auto-commit. Uncommitted reads end with session close. SQLAlchemy errors cause a rollback attempt and a sanitized RuntimeError. Other exceptions, including cancellation, get a rollback attempt and propagate. `commit_write:78–87` catches commit-time IntegrityError, OperationalError and ordinary ConnectionError alike, attempts rollback and raises HTTP 500 with a diagnostic. An unsuccessful rollback cannot turn the response into a success. The diagnostic’s contents have a separate finding under N02.

**Bulk trace in execution order.** `labeling_router.py:440–451` authenticates through dependencies, resolves the domain and locks the requested tenant rows. Line 459 marks the outer transaction. Line 477 reserves eligible capacity. Lines 486–492 call single verify, passing explicit `payload.outcome` or the legacy action-derived value. Lines 426–429 pass `request.verified_outcome` to `db/repository.py:289–315`. There the engine receives `outcome_correct` at 310–312, verification is persisted through 136–150, and the versioned engine update is flushed. Single verify skips its own commit at 433–435. After the loop, 494 clears the flag, 495 awaits `db/connection.py:81`, and 496 returns counts. FastAPI serializes the response after the handler returns. A commit exception exits before 496. No affected GET was found that depended on implicit commit. The legacy read dependency has its own SQLite lifecycle.

**Endpoint accounting.** The method/path inventory in §7 gives the commit and return for every write, including the external checkout transaction, non-SQL configuration write, no-op webhook branches and read-only POST report routes. The early return in a transaction context runs its exit before the function returns to FastAPI. Comparing the numeric position of the context manager definition to its caller would miss this ordering.

### N02 · diagnostic boundaries

Complete formatter, `db/connection.py:52–75`:

```python
def sanitize_database_error(exc: Exception) -> str:
    """Return only approved diagnostic fields, never statement values or driver detail."""
    try:
        parts = [type(exc).__name__]
        statement = getattr(exc, "statement", None)
        if isinstance(statement, str):
            operation = re.match(r"\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM|SELECT\s+FROM|ALTER\s+TABLE)\s+([A-Za-z_][\w.]*)", statement, re.I)
            if operation:
                parts.append(f"{operation.group(1).upper()} {operation.group(2)}")
        source = getattr(exc, "orig", exc)
        message = str(source)
        state = getattr(source, "sqlstate", None) or getattr(source, "pgcode", None)
        if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state, re.I):
            parts.append(f"SQLSTATE {state}")
        for candidate in re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+", message):
            parsed = urlsplit(candidate.rstrip(".,;"))
            if parsed.hostname:
                parts.append(f"host {parsed.hostname}")
        unreachable = re.search(r"\b([A-Za-z0-9.-]+)\s+unreachable\b", message)
        if unreachable:
            parts.append(f"host {unreachable.group(1)}")
        return "; ".join(parts)
    except Exception:
        return "Database operation failed (diagnostics withheld)"
```

The formatter never examines `.params`. It keeps the recognized operation and first identifier from `.statement`, recognizes a five-character SQLSTATE, and parses hostnames out of the rendered underlying exception. URL user info and passwords are omitted there. Both ordinary passwordless URLs and malformed URLs have a bounded formatting path. A formatter failure uses the constant at 75. `sanitize_url:39–49` is a separate URL helper. The database formatter does **not** establish that its inferred “host” came from connection metadata. A driver reporting a rejected user value can include a URL or text shaped like an unreachable-host diagnostic. The value can then reappear in an operator log or a commit-failure response. Use trusted connection metadata and stable operator codes. Keep transaction detail out of client messages.

`scheduler.py:118–122` invokes the sanitizer and falls back to the exception class. Migration and private billing sessions are wrapped. Legacy SQLite context entry/commit/close at `jm_service.py:102–109` can raise directly. Async session entry/exit at `db/connection.py:113` and URL normalization at 90 precede or surround the protected block. An unhandled database error can reach server diagnostics. Ordinary production FastAPI 500s do not by themselves prove a client received a traceback. The complete caught-handler inventory is in §7.

### B6-02 · annotation ordering

Ordering predicate, `label_studio.py:305–310`:

```python
    if row is not None and source_time is not None and row.source_updated_at is not None:
        stored = row.source_updated_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        if source_time <= stored:
            return {"status": "processed"}
```

1. A CREATED event binds the project-qualified annotation ID. The connector uses an aware `updated_at`, falling back to `created_at` (272–281). With ground truth present the initial verification stores that timestamp at 365–368. With truth absent it returns pending at 333–335 and leaves the timestamp unset.
2. In the pending case HTTP verify can record a true outcome. If the connector already verified it, individual verify returns 409. These are distinct starting states.
3. A later dated UPDATED with a changed decision reaches `verify_and_relearn:369`, copies the structured content and source reference, sets the successor timestamp at 374 and commits at 375.
4. A replay of the older dated CREATED follows `superseded_by` at 301–304, compares its date with the current successor at 309, and exits at 310. No learner or quota mutation occurs on this path. Two genuinely different dated updates received out of order also keep the later timestamp when both sides have watermarks.

There is no source-sequence comparison. With absent dates the history query at 341–348 treats any earlier matching action, truth and reviewer as replay. A genuine return to an earlier judgment disappears while the caller receives success. An unseen older tuple can instead be applied as new. A later undated correction sets its successor watermark to null at 374. A normal API relabel copies provenance except the watermark at `labeling_router.py:683–696`. Equal timestamps also collapse distinct payloads. Preserve source identity and order across both adapters, record a stable delivery identity where available, and reconcile ambiguous deliveries before learning or acknowledging a completed correction.

### B6-03 · authenticated bytes and intake admission

`billing.py:26` sets `MAX_WEBHOOK_BYTES = 64 * 1024`. At 177–183 a declared oversize body returns 413 before any application stream read. Lines 184–191 count actual bytes before appending each chunk. A missing or understated length therefore cannot admit a larger body. The ASGI server may already have received a chunk before handing it to this loop. The body passed to HMAC at 197–199 consists of the unmodified joined bytes. Parsing occurs at 202. Normal signed events still work. Neither a read deadline nor a limit on simultaneous incomplete intakes appears in the handler or the checked deployment files. The historical requirement explicitly included all three limits. Add bounded admission and release on timeout, disconnect and success, or supply verified equivalent ingress controls. The original per-request allocation defect is closed.

### R3-03 · save, refetch and navigation

A user must first change at least one chip to enable Save Tags. With a changed chip and `important` still in the input, 140–142 submits committed chips. The synchronous mutation lock disables editors throughout the POST. Line 144 sets `preserveDraft.current = true` **after POST success, before refetch**. Lines 145–147 snapshot the typed input. The real POST names the predecessor in `label_id` and the successor UUID in `revision_id`. The predecessor GET supplies the successor’s public label ID. Lines 86–91 record it and replace the route. Lines 62–74 keep the matching snapshot, and lines 95–105 restore the typed text and consume it. A manual move to an unrelated domain/item clears it. A terminal fetch error at 110 leaves it live on the original route.

Dirty predicate, `ReviewCard.tsx:114–118`:

```tsx
  const spansDirty = item !== null && JSON.stringify(editedSpans) !==
    JSON.stringify(item.content?.content_type === 'text_ner' ? item.content.spans : [])
  const tagsDirty = item !== null && JSON.stringify(editedTags) !==
    JSON.stringify(item.content?.content_type === 'text_multilabel' ? item.content.tags : [])
  const hasUnsavedEdits = spansDirty || tagsDirty || Boolean(tagInput.trim())
```

| Mutation/refetch | Preservation | Before discard |
|---|---|---|
| Save Tags, 136–155 | Success sets snapshot at 144. Conflict at 151–153 reloads without it. | The user gets a conflict message after a local edit can already be lost. |
| Save Spans, 119–134 | No snapshot. A successful save refreshes what was sent. A conflicting save reloads the server spans. | No pre-discard decision on conflict. |
| Verify and override through submit, 157–178 | No snapshot needed for a clean card. | 161 blocks a dirty span, chip or typed tag. Button and keyboard paths use this predicate. It omits the selected/custom category held inside CategorySelector. Conflict reload at 175. |
| Category submit and afterCategorySaved, CategorySelector:28–40, ReviewCard:197–205 | Success and child 409 callback snapshot the parent drafts at 199 before reading. | The category selection itself is component-local. |

Selecting a different category, then verifying before clicking Relabel, can train on the displayed label’s **old** category. Manual navigation also clears edits without a decision. The successful Save Tags test establishes the requested positive path. Closure requires shared category dirty state, a discard decision for navigation/conflict, and a bounded snapshot lifetime.

### F6-01 · account invalidation

Full `frontend/src/App.tsx:54–57` handler:

```tsx
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'rgi-api-key') applyKeyChange(localStorage.getItem('rgi-api-key') ?? '')
      else if (event.key === null) applyKeyChange('')
    }
```

Two actionable branches. A delivered null-key clear calls `applyKeyChange('')`. A delivered API-key removal reads the now-absent local value and invokes the same helper. Other storage keys do nothing. At 37–52 the helper updates the active ref, dispatches synchronous invalidation, removes checkout/registration receipts, clears the domain, and either updates the sidebar in place on Signup/active import or reloads Upload. Local Settings clear emits the local key-update event. The keyed path still invalidates on each delivered notification, including A→B→A. Listeners are removed at 64. A rendered registration form has additional ordinary fields discussed in §3.

### F6-02 · file lifetime

At `Upload.tsx:141` only `{reportRef: storeReportFile(file)}` is sent in route state. The exact Upload references are in §7. **There is a module-global File reference** in `reportHandoff.ts:2–17` until the next consume, account invalidation or document teardown. The map records the owner key, deletes the entry on consume and checks the current owner before handoff. It has no time-based eviction for abandoned entries. HealthReport consumes once at 23–26, clears component state and invalidates pending results at 27–30. Upload clears file, form, sample and progress and remounts its input at 29–46. An in-flight upload may still hold a network reference until it settles.

Normal first navigation can submit the owned File. Rotation erases unconsumed handoffs. Back can restore the opaque reference, but a consumed or previous-owner entry returns null. Old history records containing a literal File are ignored by the new reader. No re-upload follows from that reference. The StrictMode first-navigation issue in §3 and private queue previews in history have different consequences.

## 2. Backend audit

| New ID | Severity | File and line | Failure scenario | Closure criterion |
|---|---|---|---|---|
| B7-01 | **P1** | `label_studio.py:292–299,325–335,349–353` | Lookup by annotation identity can return an already verified row for a different source task. The handler assigns the incoming task ID before checking category/factors. If those match, the ordinary pending-truth or unchanged-judgment branch commits the new task ID in place. A previously verified judgment now appears to belong to a different task without a revision. This concerns provenance within a tenant. | Treat an established task binding as immutable. Reject a disagreement before assignment. Assert, from a fresh session, that both the original binding and reviewed evidence survive. |
| B7-02 | P2 | `db/migrate.py:63–66,157–158`, `test_migration_fixes.py:162–163` | The SQLite restore invariant fires, but the new generic wrapper erases its safe cause. The migration test stops on its exception-message assertion before it can verify restoration. The failure is reproducible on SQLite. | Give this invariant a fixed non-sensitive error code/message. Verify rollback and subsequent successful upgrade with real saved children. |
| B7-03 | P2 | `test_sweep3_fixes.py:173–179`, `db/models.py:54,70`, `test_round4_fixes.py:100–103` | The image/provenance fixture treats the first row sorted by score time and random UUID as the predecessor. SQLite score timestamps can tie. A valid successor can sort first and make the assertion fail. The focused SQLite run failed here, the full SQLite run passed this case. | Locate the actual predecessor through its non-null successor link or saved original ID. Assert the exact linked pair and copied child. |
| B7-04 | P2 | `label_studio.py:272–281` | A syntactically valid offset datetime near the representable date boundary can overflow during normalization to UTC. Only ValueError maps to 422. | Handle overflow at the same validation boundary and retain acceptance of ordinary offset-aware timestamps. |

**Storage and evidence.** `db/connection.py:14–49,90–127` supports ordinary URLs with or without user info. Non-default sslmode and malformed configuration use a separate startup path. The engine enables SQLite foreign keys. The async request session, billing’s own begin context, scheduler sessions, migration engine and legacy sync SQLite connections have different owners. Repository writes flush in the caller’s transaction. `db/repository.py:45–81` checks engine version on update. First insert still races. HTTP relabel locks the current scoped row and checks the predecessor UUID, links the successor, preserves source text and either copies or replaces structured content. Connector relearning preserves text, image, spans, tags and revision actor/time at 252–285. Source time requires the additional repair in §1. The evidence CTE at 154–176 links by both tenant and domain. A verified predecessor counts until a verified descendant replaces it. Overview, per-category accuracy and the annotator aggregation use that rule (`dashboard_router.py:211–231,258–294`, `repository.py:179–189`). The round 4/5 multi-revision and annotator tests remain pertinent.

**Migrations.** `db/migrate.py:18–28,31–73,79–156` inspects schema before adding columns, uses explicit UTC when widening old PostgreSQL timestamps, and includes source_updated_at in the SQLite rebuild. The child backup/restore and count check run inside a savepoint. Repeatable shape does not establish historical value parity. The provider rename runs only on PostgreSQL (R23). Fresh metadata creation is a separate path. A failing cleanup at 162–163 can also obscure an earlier migration error. No observed SQLite result here establishes lost production rows.

**Label routes.** Authentication establishes the tenant in session context. Guidelines, scoped domain resolution, pending/count/search, detail and revision traversal use the scoped domain and/or tenant predicate. The search terms are SQLAlchemy bound expressions. Detail follows the chain under tenant/domain at 751–768. Initial content at 773–809 rejects a second child, yet permits the first attachment after verification (existing P2). Require revisioned attachment or an explicit immutable-evidence rule. Guidelines cap is 10 KiB UTF-8. Ingest items enforce finite unit-interval values and bounded IDs/text. Factor count and key length, verify action length and optional editable-span mention length lack equivalent maxima. Batch caps items at 100, bulk at 200. Create and edit have different span/tag limits. Predict’s task list also lacks an upper bound (existing validation gap). Single, batch, sample creation and connector first-ingest use the same quota reservation. Batch exceptions unwind the outer transaction. Sample seeding uses a scoped advisory transaction lock on PostgreSQL at 534–535. SQLite has no equivalent per-seed guard. Search and ordinary reads reserve nothing.

**Billing, quota and retention.** Checkout creates the external Paddle transaction before returning the URL. Live signature configuration is mandatory. Event receipts and entitlement updates commit together. Unsupported subscription events return success without an entitlement transition. Customer-first binding can select a sibling purchasing key (R02/R19). A cancellation or canceled update is independent of product lookup. At `trial_guard.py:67–109`, UTC period rollover precedes the cap check, and increments follow it. Effective cancellation gets 50/day. Paid monthly counters roll separately. An expired but active key still authenticates on routes that do not reserve. Bulk verification charges eligible processed labels; individual verification does not reserve. At the cap bulk skips remaining eligible labels. This policy difference predates round 6. Account’s reported caps at `account.py:38–49` can still reflect stored tier.

`scheduler.py:53–107` reads candidates, reacquires all sibling rows in a fresh transaction, rechecks cancellation date, active state and subscription ID, and preserves shared data if a sibling is retained. SQLite begins IMMEDIATE before the reread. PostgreSQL takes a table-level lock then ordered row locks. This serializes cleanup with writes and can stall unrelated tenants; a lock wait has no local deadline in this function. Logging at 98/117 counts expired keys as cleaned tenants (existing P3). Ordinary quota and revision writers still face R24. A failed job is contained at 118–122. Email notifications occur before their sent flags commit at 39–49, so a later failed commit can cause a repeat notice.

**Connector and anonymous reports.** Dispatch guards action type before membership (256–260). Configure, predict and webhook take connector token and tenant key. Setup takes the connector token and binds a configured tenant if available. Configure locks the read/modify/unique-temp-file/replace sequence within one process (165–185). Predict can reuse the original scored row after revision (211–225, existing P2). Unchanged deliveries use no new scoring quota. Ordering is distinct from config-file serialization. Anonymous report intake at `label_health/api.py:84–123` checks busy/declared length, reserves before form parsing, counts actual multipart bytes, and carries one deadline into the CSV read. The worker retains the permit until it finishes, even after a 504. Early read/parse errors release it. A completed form with the wrong field reaches 422 at 115–119 before the explicit close at 123 (existing P2).

**Auth, service and engine.** Signup at `auth.py:47–66` validates email syntax, hashes the new random key, enforces uniqueness and commits before email delivery and returning the plaintext. Mailbox ownership remains unverified. Admin issuance checks the admin credential. `jm_service.py:250–312,317–347` mounts the legacy and DLJ routers in one process, with separate credential databases. FastAPI debug mode is off by default, CORS enumerates origins and exposes X-Total-Count, and static files mount last at 658. Legacy mutation commits are in §7. `jm_core.py` is an in-memory engine per loaded snapshot. The repository reconstructs a durable score context and passes action agreement separately from ground truth at 301–315. Snapshot/version transactions protect modern updates. Legacy load/modify/save has separate commits. The audit found no new tenant-crossing query in the dashboard or label routes. Legal pages, email, policy, limiter, health ingest/analyze/render, models and standalone experiment/demo modules were included in the file cross-check.

## 3. Frontend audit

| New ID | Severity | File and line | Failure scenario | Closure criterion |
|---|---|---|---|---|
| F7-01 | **P1** | `ScoredQueue.tsx:182`, `ReviewCard.tsx:171`, `labeling_router.py:744–747` | Both review navigation paths put the whole pending DTO in browser history. It contains up to 80 code points of private source text and an annotator ID, even when the preview column is hidden. Clearing the key and reloading cannot erase earlier history entries. The current detail view independently checks auth, but the earlier account’s source data remains in history state in the same browser. | Pass route identifiers alone and fetch authenticated detail. Cover manual review, automatic next, logout/rotation and Back. Verify no private label fields in history, including with previews hidden. |
| F7-02 | P2 | `main.tsx:7–8`, `reportHandoff.ts:10–14`, `HealthReport.tsx:23–30` | Development StrictMode replays mount effects. First setup consumes the only File and starts analysis, cleanup invalidates its generation, and the second setup finds an empty handoff. The first response cannot render or clear busy. A heading-only assertion misses a stalled first preview. | Retain an owner-bound handoff for the mounted operation through effect replay. Assert actual preview and busy completion on first navigation in development and production builds. |
| F7-03 | P2 | `Upload.tsx:49–55` | Task creation captures the submitted domain, but its success navigates to a domain-less review URL. A user switching the sidebar domain before the response can land on the wrong domain’s detail or a 404. | Check the operation owner before navigation or explicitly navigate with the submitted domain. Assert both domain and item during a delayed completion. |
| F7-04 | P2 | `HealthReport.tsx:28–40` | PDF completion does not check the generation used for preview. A pending download can still click its link after the user changes report or leaves the screen, and an older completion can clear busy for newer work. | Capture the file and generation, invalidate or abort on replacement/unmount, and check ownership immediately before delivering the file. |
| F7-05 | P2 | `Signup.tsx:37–44`, `App.tsx:39–44` | Signup remains mounted during account rotation. The receipt, key and busy state clear, but the previous user’s typed name/email and form error can remain visible. | Clear the complete signup form on external account change. Keep ordinary receipt adoption working. |

**Screens and request ownership.** App keeps public signup/health routes available. Protected routes can render a shell without a key; the server enforces authorization. Sidebar key and domain update on rotation. Signup increments its epoch at submit, account change and unmount and checks before adopting the result. The receipt is tab-scoped and erased by the global change handler. Local key commits and browser storage subscriptions have cleanup. ReviewCard’s synchronous ref prevents overlapping mutations. Save Tags, Save Spans, verify and child category submit release in finally. TagSelector is controlled by parent callbacks, and NEREditor uses parent span callbacks, checks read-only/disabled controls, and keeps popup state locally. A failed canonical refetch can retain the snapshot (existing P2).

ScoredQueue’s request ID, domain and loaded-query guards suppress late results. Domain, category, raw/debounced search, sort, page size and page changes clear selection and outcome at 43–65. Row toggles, select-all and Escape change IDs without resetting truth at 122–146/182. A previous batch can clear a later same-domain selection at 155–158 (existing P2s). Submitted IDs intersect the visible page and explicit `outcome` reaches the server. Export uses the displayed order and formula escaping. Upload captures credential and domain for a CSV import, checks the live key before each batch, aborts on unmount/rotation, invalidates old analysis on account change, and remounts the picker. A fetch abort cannot revoke a completed server transaction. The displayed committed count covers acknowledged batches only. CsvDropzone disables its chooser while busy, but accepts a drop at 5–9. Report preview now has generation protection, with the exceptions above.

Settings coalesces daily/monthly counters, both caps and period keys and has a usage error boundary. Missing data can look like unlimited capacity or zero use (existing P2). Focus/poll refresh at 70–89 lacks a request generation guard. Domain guidelines have their own abort/domain guard. Settings save/clear dispatch the local change event at 92–102. Dashboard and AnnotatorProfiles ignore responses after changing domain using effect cleanup. They do not abort all network work or immediately remove all old charts. Old values can remain visible while a new request is loading or fails. Dashboard shows a loading indicator during a nonempty-domain fetch.

**Other components.** CategorySelector locks before submit, releases in finally, and disables controls, but the parent cannot see its unsaved selection. Its autonomy fetch at 23–27 lacks an ownership guard. TagSelector propagates input/chip changes to the parent. NEREditor/NERViewer use text elements, code-point slicing and focusable spans. GuidelinesPanel, IAAPanel, ConfidenceIndicator, FactorBar, MetricCard and TierBadge render supplied state. ImageViewer handles load/error and its category badge, TextViewer renders source as text, and ErrorBanner and LoadingSpinner are presentation components. KeyboardShortcuts registers/cleans its listener, ShortcutsModal controls the overlay, and SignupBanner checks key presence. No additional P1 was identified in those presentation components.

**HTTP and deployment.** All protected API wrappers at `api.ts:198–260` use the common request path. X-Api-Key is attached when a credential exists. Signup and the three health operations omit it. All unsuccessful responses, including 401/403, become ApiError with the status. There is no global logout on every 403. JSON contracts largely rely on TypeScript casts, with extra checks for content type, page total and normalized usage. Every called service path maps to §7. The Vite localhost:8000 proxy is development-only. API base is relative `/v1`. Dockerfile builds with Node 22 and copies dist into the Python image. No ts-ignore/ts-expect-error directives were found in frontend/src. The frontend no-emit type check passed. A route-mocked Chromium run establishes UI behavior, not live end-to-end billing or credential isolation.

## 4. Test suite health

| Run | Passed | Failed | Skipped | Interpretation |
|---|---:|---:|---:|---|
| Full configured pytest, 444 collected | 443 | 0 | 1 | SQLite-only migration case excluded itself. |
| Same full suite with SQLite selected | 442 | 1 | 1 | PostgreSQL-only migration case skipped. Failure at `test_migration_fixes.py:162`, B7-02. |
| Focused round 4, 5 and 6 Python modules with PostgreSQL selected | 21 | 0 | 0 | Includes the round 6 cases. Some fixtures choose their own engine. |
| Focused round 4, 5, 6 and migration tests with SQLite selected | 24 | 2 | 1 | Migration diagnostic and image/provenance fixture failures (B7-02/03). |
| Playwright listing and complete run | 124 | 0 | 0 | 124 collected across 14 files, all executed, zero retries under the repository config. |

The full Python runs excluded the three Docker-live modules and `test_ops_e2e.py`, as requested, and used a 30-second test timeout. SQLite and PostgreSQL selection use DATABASE_URL and DLJ_DATABASE_URL according to fixture. Do not add the focused runs to the full suite totals. Browser fixtures mock many network responses. None of the counts establishes production concurrency or ingress behavior.

**Independent report-navigation check.** Chromium uploaded a synthetic CSV and opened its report using the current Vite development server and a fresh production build. Both received one successful mocked HTML report response. On the development server the filename and spinner remained visible and the preview never appeared during the three-second assertion window. The production build rendered the report inside the iframe and Back returned to Upload. This confirms F7-02 on the normal development workflow as well as the positive production behavior. These two checks are additional to the 124 Playwright suite cases.

### Every round 6 Python case

Reversion judgments below are source-based counterfactuals. The working tree was not reverted.

| Test in test_round6_fixes.py | Assertion | Would reverting the fix fail it? | Exact case and missed sibling |
|---|---|---|---|
| `test_failed_commit_never_acknowledges_verification`, 15 | Injects failing commit, asserts a wire-visible 500 and unchanged verified_at via fresh detail. | Yes for removing the handler commit under the simulated old post-yield dependency. | Exact single-verify commit failure. The fixture replaces get_db; it does not prove production cleanup order, raw ASGI send order for every write, response redaction, bulk rollback or email sequencing. |
| `test_successful_commit_acknowledges_persisted_verification`, 45 | Checks 200 and persisted true. | **No**. A dependency that commits after sending may still complete before TestClient returns. | Useful success control. No injected commit latency or competing read before send. |
| `test_database_diagnostics_never_echo_values`, 51 | Checks SQL operation visible while literals, bound password and userinfo are absent. | Expected yes for the older value-echoing formatter with these inputs. | Direct formatter, not a log/client sink. Its first IPv6 check requires only a truthy message. Copied host-shaped driver values remain uncovered. |
| `test_database_diagnostic_formatter_is_total`, 67 | An exception whose string conversion raises still produces a nonempty diagnostic. | Yes for a formatter that lets the formatting exception escape. | Tests totality, but any nonempty unsafe string also passes. Assert the constant fallback and a subsequent scheduler run. |
| `test_connector_ignores_older_delivery`, 74 | Dated create, changed newer dated update, then old UPDATED and CREATED. Asserts durable latest decision, reviewer and truth, and replaces both learner paths with failure sentinels before replay. | Yes for a current-value-only implementation that relearns the old update. | Faithful dated timeline. No pending-first/HTTP verify, undated genuine reversal, intervening API revision, equal timestamp, changed source task or mixed clocks. |
| `test_billing_rejects_oversize_body_before_signature`, 96 | One oversize TestClient request returns 413. | Yes when the limit is removed. | Tests the ordinary declared-length path. A fully buffered implementation returning 413 can also pass this test alone. |
| `test_billing_stream_without_length_stops_at_limit`, 102 | Feeds an ASGI request directly. Asserts 413 and exactly three reads before stopping. | The old unlimited read cannot satisfy the bounded assertion. **Do not run this unbounded producer against a reverted unlimited reader**. | Genuine observed-byte coverage. A finite sentinel would fail safely on regression. Misses exact-limit valid signatures, understated lengths, bounded time and concurrent admission. |

### Every round 6 browser case

| Test in e2e/fix_round6.spec.ts | Assertion | Would reversion fail it? | Exact case and missed sibling |
|---|---|---|---|
| Save Tags keeps the next typed tag and blocks verification, 7 | Adds a chip, types another tag, saves through predecessor/successor, checks new URL, chip, preserved input and disabled approval. | Yes for loss of the draft or missing typed-tag dirty guard. | Realistic response shape. Backend mocked. Add category draft, span/tag conflicts, failed successor read and explicit manual-discard decisions. |
| Whole-store clear invalidates account and deferred receipt, 37 | Dispatches a null-key notification after clearing storage; checks visible sidebar key and receipt removal. | Yes for keyed-only handling. | Calls the correct handler but synthesizes the event in one tab. Add a native second tab, a protected screen, domain assertion and a mounted import. |
| Report navigation does not retain a File, 46 | Checks the literal history File is absent, changes the stored key, navigates away/back and checks no increment in report calls. | The literal-File assertion should fail on the former implementation. | Key is changed in the same tab without an account-change event; first report content and positive baseline count are not required. The no-extra-request assertion can pass with zero successful previews and does not inspect queue DTO history. |

**Round 4/5 relevance.** The dated replay and commit tests add coverage beyond the earlier rounds. Keep the earlier bulk truth, no-op edit, empty-content revision, evidence lineage, structured-content copy, upload permit, epoch, draft and receipt tests. Round 5 database logging tests exercise specific diagnostic values. Their name alone does not prove every request/driver boundary. The old image-copy case still matters but its predecessor lookup is unreliable on SQLite. The older round 5 browser specifications passed in the 124. No earlier group is superseded wholesale.

## 5. Definitive P1 scorecard

| Patchable ID | Side | Deciding location and open failure | Existing coverage / missing proof |
|---|---|---|---|
| N02 | BE | `db/connection.py:61–72,87,113`, `jm_service.py:102–109`. Arbitrary driver text can supply copied diagnostic fields or bypass the wrapper. | Round 5 wrappers, round 6 formatter. Missing trusted-field-only tests at operator and HTTP sinks. |
| B6-02 | BE | `label_studio.py:305–310,333–348,369–375`, `labeling_router.py:683–696`. Undated or watermark-losing revisions can discard or replace real evidence. | Dated replay and forward corrections covered. Add reconciliation and source-order persistence across both adapters. |
| B6-03 | BE | `billing.py:177–191`. Public intake lacks a deadline and concurrent-reader budget. | Header/stream byte caps and normal signature tests present. No time/concurrency acceptance gate or verified upstream equivalent. |
| B7-01 | BE | `label_studio.py:292–299,325–335,349–353`. Existing annotation can acquire a different source task in place. | Content-copy tests exercise legitimate revisions. No assertion that a conflicting task binding is rejected without mutation. |
| R3-03 | FE | `ReviewCard.tsx:118–153,157–175`, `CategorySelector.tsx:18–19`. Category changes bypass verification’s dirty check; conflict/manual navigation can discard pending work. | Happy canonical saves covered. No complete category/discard/conflict test. |
| F7-01 | FE | `ScoredQueue.tsx:182`, `ReviewCard.tsx:171`. Source previews persist in history across logout or rotation. | File-history regression covers Upload only. Check both review navigation mechanisms. |

| Structural ID | Since sweep 6 | Evidence and plan ownership |
|---|---|---|
| R02 | UNCHANGED | `billing.py:124–145`. Existing same-tenant customer binding wins before the checkout key ID. Prompt 02. |
| R04 | UNCHANGED | `db/repository.py:24–31,50–67`, `label_studio.py:135–144`. Two first writers can both observe no domain or engine. Explicit commits do not turn creation into an upsert. Prompt 05. |
| R05 | UNCHANGED | `label_studio.py:114–133,265–271,326–331`, `labeling_router.py:573–612`. Body limits differ from derived/path/reviewer identifiers at database writes. Prompt 03. |
| R08 | UNCHANGED | `auth.py:47–66`. Registration grants a usable credential before the mailbox owner confirms. Prompt 03. |
| R19 | UNCHANGED | `billing.py:210–224,243–267`. Receipt ordering helps supported transitions; unsupported subscription states and replacement/retired keys remain outside a complete state machine. Prompt 02. |
| R23 | UNCHANGED | `db/migrate.py:119–145`. Historical provider linkage migrates by rename only on PostgreSQL. New SQLite columns may lack old values. Prompt 02. |
| R24 | UNCHANGED | `trial_guard.py:72–105`, `labeling_router.py:619,695–704`. Ordinary SQLite writes still rely on row-level locking semantics absent on that dialect. Retention has its own explicit guard. Prompt 05. |
| R29 | UNCHANGED | `label_studio.py:170–185`. File replacement is atomic; two processes can acknowledge conflicting read/modify/write operations. Prompt 05. |
| R13 | UNCHANGED | `labeling_router.py:488–492`. The UI sends explicit ground truth. Nullable/omitted truth in an older client is still converted from action and trained on. Prompts 04/05, joint S27. |

**Accepted for v1.1.** R06 (`jm_service.py:541–551,599–605`) splits legacy decision and engine commits. R07 (62–95,317–322,438–447) stores reusable legacy keys in SQLite. R30 (`jm_service.py:175–181,327–337`, `jm_core.py:200–206,348–350`) leaves older delimiter-based centroid keys ambiguous. All three are unchanged, confined to the legacy credential/storage path, and still share the service process. No round 6 change connected those credentials or tables to DLJ. Production consumer count and perimeter controls require operational evidence. Reopen the acceptance decision if those assumptions change.

**Reconciliation.** Starting ledger 19, subtract three closed round 6 P1s, add B7-01 and F7-01: **18**. Four of six patchable items were already open. The undated reversion failure is a newly introduced consequence of the round 6 replay heuristic, counted once under B6-02. The two new IDs are findings of this sweep; their discovery does not date their introduction to round 6.

## 6. Prompt 00 gate

| Required condition | Result |
|---|---|
| All seven round 6 fixes CLOSED | **NO — 3/7** |
| FE patchable P1 = 0 | **NO — 2** |
| BE patchable P1 = 0 | **NO — 4** |
| Pytest and Playwright green | **NO across supported databases.** Configured pytest and Chromium passed. SQLite failed. |
| Remaining P1s exclusively structural/accepted | **NO — 6 actionable repairs** |
| No new P1 failure introduced by round 6 fixes | **NO.** The new historical-tuple heuristic can acknowledge and discard an intentional undated correction (B6-02). |

**NOT READY.** Before declaring the gate green, (1) preserve connector source identity and ordering across both revision adapters (B7-01/B6-02), (2) finish the public billing intake budget (B6-03), (3) limit database diagnostics to trusted fields and restore a stable migration-invariant signal (N02/B7-02), (4) preserve or explicitly discard all review drafts before review transitions (R3-03), and (5) remove private DTOs from both review navigation paths (F7-01). Use the exact file/line and acceptance criteria in §§1–5. Stabilize the SQLite predecessor fixture (B7-03) and repeat both database suites and the full browser suite. The other newly recorded P2s do not independently block this gate.

The currently tested happy-path wire contracts are suitable starting fixtures, but do not freeze missing-source-order acknowledgments or receipt/entitlement behavior as contractual success. Prompt 02’s first risk is migrating real customer-to-key ownership without transferring an entitlement to a sibling key. Require populated historical schema fixtures, provider-ID parity across dialects and independent-session concurrency tests before treating the migration as repeatable in production.

## 7. Coverage and independent cross-check

### Endpoint ledger

Each row is a distinct application method/path registration. The two detail paths share an implementation. Runtime OpenAPI exposes 43 operations. Three legal handlers use `include_in_schema=False`, reconciling the total to **46**. Framework-generated schema/docs and the static mount are infrastructure. Of 46 routes, **22** can write persistent application data, configuration or an external checkout. Three health-report POSTs compute a report without persisting a label. “Yes” means the successful write completes before an HTTP success leaves the handler. It makes no claim about the correctness of the stored value.

| File and route line | Method | Endpoint | Commit or other durable boundary (line) | Return line(s) | Order correct? |
|---|---|---|---|---|---|
| account.py:26 | GET | `/v1/account` | Read only | 38 | n/a |
| account.py:54 | GET | `/v1/account/domains` | Read only | 58 | n/a |
| account.py:73 | POST | `/v1/account/domains/resolve` | 83 | 84 | Yes on write paths |
| auth.py:47 | POST | `/v1/auth/register` | 63 | 66 | Yes on write paths |
| auth.py:107 | POST | `/v1/admin/api-keys` | 117 | 118 | Yes on write paths |
| billing.py:63 | GET | `/v1/billing/checkout-url` | 83–96 await provider transaction and validate response; no local write | 97 | Yes on write paths |
| billing.py:175 | POST | `/v1/billing/webhook` | 229 enters 164–172 begin context; exit commits for 254/273; 211 ignored event | 211, 254, 273 | Yes on write paths |
| dashboard_router.py:150 | GET | `/v1/dashboard/{domain_id}/iaa` | Read only | 176 | n/a |
| dashboard_router.py:211 | GET | `/v1/dashboard/{domain_id}/overview` | Read only | 228 | n/a |
| dashboard_router.py:234 | GET | `/v1/dashboard/{domain_id}/corrections` | Read only | 253 | n/a |
| dashboard_router.py:258 | GET | `/v1/dashboard/{domain_id}/annotators` | Read only | 294 | n/a |
| dashboard_router.py:297 | GET | `/v1/dashboard/{domain_id}/factors` | Read only | 318 | n/a |
| dashboard_router.py:321 | GET | `/v1/dashboard/{domain_id}/compounding` | Read only | 330 | n/a |
| jm_service.py:412 | GET | `/v1/health` | Read only | 433 | n/a |
| jm_service.py:436 | POST | `/v1/register` | 442–446 context exit → 107 | 447 | Yes on write paths |
| jm_service.py:450 | POST | `/v1/domains` | 474–480 context exit → 107 | 481 | Yes on write paths |
| jm_service.py:492 | GET | `/v1/domains` | Read only; legacy context exits via 107 | 502 | n/a |
| jm_service.py:515 | POST | `/v1/domains/{domain_id}/score` | 541–551 decision context exit and save_engine → 342–346 → 107 | 553 | Yes on write paths |
| jm_service.py:563 | POST | `/v1/domains/{domain_id}/learn` | 599–605 decision context exit and save_engine → 342–346 → 107 | 607 | Yes on write paths |
| jm_service.py:617 | GET | `/v1/domains/{domain_id}/diagnostics` | Read only | 634 | n/a |
| jm_service.py:637 | GET | `/v1/domains/{domain_id}/state` | Read only | 651 | n/a |
| label_health/api.py:126 | POST | `/v1/label-health/analyze` | Read only | 128 | n/a |
| label_health/api.py:131 | POST | `/v1/label-health/report` | Read only | 133 | n/a |
| label_health/api.py:136 | POST | `/v1/label-health/report/pdf` | Read only | 138 | n/a |
| label_studio.py:165 | POST | `/v1/label-studio/configure` | 181 atomic file replace | 185 | Yes on write paths |
| label_studio.py:188 | POST | `/v1/label-studio/setup` | 195 if configured; otherwise no write | 196 | Yes on write paths |
| label_studio.py:199 | POST | `/v1/label-studio/predict` | 250 | 251 | Yes on write paths |
| label_studio.py:254 | POST | `/v1/label-studio/webhook` | 334 pending; 352 unchanged; 367 verified; 375 revised. 260/290/310/348 ignored/replay | 260, 290, 310, 335, 348, 353, 368, 376 | Yes on write paths |
| label_studio.py:379 | GET | `/v1/label-studio/health` | Read only | 382 | n/a |
| labeling_router.py:54 | GET | `/v1/domains/{domain_id}/guidelines` | Read only | 57 | n/a |
| labeling_router.py:60 | PUT | `/v1/domains/{domain_id}/guidelines` | 65 | 66 | Yes on write paths |
| labeling_router.py:381 | POST | `/v1/labels/ingest` | 388 | 389 | Yes on write paths |
| labeling_router.py:396 | POST | `/v1/labels/verify` | 434 standalone; bulk delegates final commit to 495 | 435 | Yes on write paths |
| labeling_router.py:440 | POST | `/v1/labels/{domain_id}/bulk-verify` | 495 | 496 | Yes on write paths |
| labeling_router.py:499 | POST | `/v1/labels/ingest/batch` | 524 | 525 | Yes on write paths |
| labeling_router.py:528 | POST | `/v1/labels/{domain_id}/sample` | 568 | 569 | Yes on write paths |
| labeling_router.py:573 | POST | `/v1/labels/{domain_id}/tasks` | 592 scored / 611 unclassified | 593, 612 | Yes on write paths |
| labeling_router.py:615 | POST | `/v1/labels/{domain_id}/items/{label_id}/relabel` | 704 | 705 | Yes on write paths |
| labeling_router.py:709 | GET | `/v1/labels/{domain_id}/pending` | Read only | 744 | n/a |
| labeling_router.py:770 | POST | `/v1/labels/{domain_id}/items/{label_id}/content` | 809 | 810 | Yes on write paths |
| labeling_router.py:814 | GET | `/v1/labels/{domain_id}/items/{label_id}` | Read only | 827 | n/a |
| labeling_router.py:815 | GET | `/v1/labels/{domain_id}/{label_id}` | Read only | 827 | n/a |
| labeling_router.py:840 | GET | `/v1/domains/{domain_id}/autonomy` | Read only | 859 | n/a |
| legal_pages.py:128 | GET | `/terms` | Read only | 130 | n/a |
| legal_pages.py:133 | GET | `/privacy` | Read only | 135 | n/a |
| legal_pages.py:138 | GET | `/attribution` | Read only | 140 | n/a |

The no-op connector path at 348 follows assignments to the ORM object at 326–327. It acknowledges a historical delivery and exits without committing tentative dirtiness. Perform identity validation and replay checks before modifying the row. The branch at 352 **does commit** the changed binding (B7-01). An ignored event has no promised write. Legacy split commits occur before the response but can still leave partial state (R06).

### Exception-handler ledger

The requested 50-line function scan and 40-line exception/log scan were run with `rg -n` and PowerShell’s first-N output. Both truncate the inventory. The function scan includes validators and helpers, and the exception scan includes log statements without a catch. An untruncated syntax-tree inventory of decorators and exception handlers, router mount checks and the runtime OpenAPI count were used for the final tables. No application endpoint or caught DB branch in that cross-check remains unaccounted for.

| File | DB or possibly DB exception lines | HTTP/log treatment and sanitizer coverage |
|---|---|---|
| db/connection.py | 74, 82/85, 95, 116/119, 122/125 | Formatter fallback constant. Commit maps to HTTP 500. Engine creation and ORM dependency errors use sanitizer. Nested rollback errors suppressed. Other exceptions re-raised at 127. Context entry/exit and normalization outside catch. |
| scheduler.py | 118, 121 | Scheduled DB exceptions flow to sanitizer. Fallback uses class. Job helpers bubble to dispatcher. |
| db/migrate.py | 157, 162 | Both main migration and dispose exceptions mapped through sanitizer. B7-02 covers loss of a safe invariant code. |
| billing.py | 159, 168, 170, 233, 269 | Email conflict has constant warning inside savepoint. HTTP errors pass through. Other private-session failures sanitized in logs with constant client 500. Receipt/customer conflicts have fixed 409 detail. Original exceptions can remain chained in Python; the normal HTTPException handler does not render them. |
| auth.py | 60 | IntegrityError maps to fixed duplicate response. No raw log. Other ORM errors rely on dependency. |
| labeling_router.py | 390, 392, 430, 508, 556, 590, 600, 609, 676, 806 | Explicit conflict/status messages. Batch log uses index, class and correlation ID (512/518). Caught capacity HTTP errors pass through or become skip reasons (478, 509). Unexpected ORM errors propagate to dependency. |
| label_studio.py | No DB-specific catch | Conversion/annotation validation catches only. Session errors rely on dependency or commit_write. |
| jm_service.py | 420, 428 | Both health probes expose class names only. Separate legacy DB wrapper at 102–109 has no diagnostic catch. |
| db/repository.py, trial_guard.py, account.py, dashboard_router.py | None | Functions delegate session handling, return controlled HTTP errors or propagate to caller. |
| label_health/api.py | None | Parser, timeout, executor and admission cleanup. No application DB session. |

Catch lines in the runtime inventory, including non-DB validation and cleanup branches:

- `auth.py` — 60.
- `billing.py` — 93, 119, 139, 159, 168, 170, 182, 205, 233, 269.
- `db/connection.py` — 74, 82, 85, 95, 116, 119, 122, 125.
- `db/migrate.py` — 157, 162.
- `email_service.py` — 25.
- `jm_service.py` — 264, 420, 428.
- `label_health/api.py` — 34, 65, 71, 77, 79, 91, 112, 117.
- `label_health/render.py` — 93.
- `label_studio.py` — 129, 231, 280, 288, 319.
- `labeling_factors.py` — 28.
- `labeling_router.py` — 84, 176, 288, 390, 392, 430, 478, 508, 556, 590, 600, 609, 676, 806.
- `scheduler.py` — 118, 121.

### Source-file self-check

Primary inventory **76/76 read in full**. It includes both historical documents, all 8 screen TSX files, all 18 component TSX files, App, main and domain context. Supporting fixture excerpts used to investigate SQLite are additional reads outside this denominator. No listed source was skipped. Every path below has status **read in full**.

**Backend, database, libraries and standalone Python (30).** `account.py`, `auth.py`, `billing.py`, `dashboard_router.py`, `db/__init__.py`, `db/connection.py`, `db/migrate.py`, `db/models.py`, `db/repository.py`, `e_jm_8_head_to_head.py`, `e_jm_9_ablation_stability.py`, `e_jm_param_sweep.py`, `email_service.py`, `jm_api_demo.py`, `jm_core.py`, `jm_experiment.py`, `jm_service.py`, `label_health/__init__.py`, `label_health/analyze.py`, `label_health/api.py`, `label_health/ingest.py`, `label_health/render.py`, `label_studio.py`, `labeling_factors.py`, `labeling_router.py`, `legal_pages.py`, `policy_engine.py`, `rate_limit.py`, `scheduler.py`, `trial_guard.py`.

**Screens (8).** `frontend/src/screens/AnnotatorProfiles.tsx`, `frontend/src/screens/Dashboard.tsx`, `frontend/src/screens/HealthReport.tsx`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/Settings.tsx`, `frontend/src/screens/Signup.tsx`, `frontend/src/screens/Upload.tsx`.

**Components (18).** `frontend/src/components/CategorySelector.tsx`, `frontend/src/components/ConfidenceIndicator.tsx`, `frontend/src/components/CsvDropzone.tsx`, `frontend/src/components/ErrorBanner.tsx`, `frontend/src/components/FactorBar.tsx`, `frontend/src/components/GuidelinesPanel.tsx`, `frontend/src/components/IAAPanel.tsx`, `frontend/src/components/ImageViewer.tsx`, `frontend/src/components/KeyboardShortcuts.tsx`, `frontend/src/components/LoadingSpinner.tsx`, `frontend/src/components/MetricCard.tsx`, `frontend/src/components/NEREditor.tsx`, `frontend/src/components/NERViewer.tsx`, `frontend/src/components/ShortcutsModal.tsx`, `frontend/src/components/SignupBanner.tsx`, `frontend/src/components/TagSelector.tsx`, `frontend/src/components/TextViewer.tsx`, `frontend/src/components/TierBadge.tsx`.

**Frontend entry, context, API and build (7).** `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/csv.ts`, `frontend/src/domain.tsx`, `frontend/src/main.tsx`, `frontend/src/reportHandoff.ts`, `frontend/vite.config.ts`.

**Tests and browser configuration (8).** `e2e/components.spec.ts`, `e2e/fix_round5.spec.ts`, `e2e/fix_round6.spec.ts`, `e2e/flows.spec.ts`, `playwright.config.ts`, `test_round4_fixes.py`, `test_round5_fixes.py`, `test_round6_fixes.py`.

**Historical and deployment inputs (5).** `docker-entrypoint.sh`, `Dockerfile`, `docs/quality/dlj_sweep6_convergence.md`, `docs/session_state.md`, `requirements.txt`.

### Upload state and navigation search

All matches for history, pushState, replaceState, navigate and state (including React useState) in `frontend/src/screens/Upload.tsx`, with 1-based working-tree lines. No direct browser-history API call appears.

```tsx
1  import { useEffect, useRef, useState } from 'react'
2  import { useNavigate } from 'react-router-dom'
15  const navigate = useNavigate()
16  const [file, setFile] = useState<File | null>(null)
17  const [report, setReport] = useState<HealthReport | null>(null)
18  const [error, setError] = useState<string | null>(null)
19  const [busy, setBusy] = useState(false)
20  const [progress, setProgress] = useState(0)
21  const [sample, setSample] = useState(false)
22  const [taskId, setTaskId] = useState('')
23  const [taskText, setTaskText] = useState('')
24  const [taskCategory, setTaskCategory] = useState('')
25  const [dropzoneVersion, setDropzoneVersion] = useState(0)
54  navigate(`/review/${encodeURIComponent(taskId.trim())}`)
88  navigate('/queue')
122  navigate('/queue')
141  <div className="button-row">{sample ? (hasApiKey() && <button className="button" onClick={scoreSample} disabled={busy}>Score 12 sample labels</button>) : <button className="button" onClick={startScoring} disabled={busy || !domainId}>Start scoring these labels</button>}<button className="button secondary" onClick={() => { if (file) navigate('/health', { state: { reportRef: storeReportFile(file) } }) }}>View full report</button></div>
```

The sole Upload navigation with a state payload is 141. The private queue payloads in F7-01 originate in other components.
