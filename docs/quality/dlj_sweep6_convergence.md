# DLJ convergence sweep 6 — full backend and frontend audit

24 November 2026 · `jm-service` working tree based on `ebf6cbc`, including the uncommitted round 5 implementation and tests.

| Gate | Result |
|---|---|
| Six round 5 fixes | **5 CLOSED, 1 PARTIAL.** The remaining partial is N02, database exception sanitization. Closure here refers to the six named failure paths. The broader review-draft issue still has a failing sibling path. |
| New backend findings | **P1=3, P2=1, P3=0** |
| New frontend findings | **P1=2, P2=2, P3=0** |
| Definitive open P1s | **19**. Frontend patchable **3**, backend patchable **4**, backend structural launch blockers **9**, backend risks accepted for v1.1 **3**. |
| Tests | **436 pytest passed, 0 failed, 1 skipped** of 437 collected. **121 Playwright passed, 0 failed, 0 skipped** across 13 spec files. Round 5 regressions passed **4/4 on each database**. |
| Prompt 00 | **NOT READY** under the specified gate. Seven patchable P1s remain. |

The most consequential new finding is the timing of a successful write response. On the installed, pinned FastAPI version, a request using the service’s database dependency sent the HTTP status and body **before** calling commit. Two other checks distinguish real progress from remaining work. Annotator, category and overview metrics now agree throughout a correction. Chromium preserved a typed tag during category relabel, but discarded another typed tag during Save Tags.

## 1. Independent verification of the six fixes

| Fix | Verdict | Deciding evidence |
|---|---|---|
| 1. R3-01/R4-01, rapid keyed cross-tab invalidation | **CLOSED** | Every delivered API-key storage notification invalidates the generation, even when the live value has already returned to A. The separate whole-storage clear regression is F6-01. |
| 2. R3-03, canonical **category relabel** | **CLOSED** | The callback captures the draft before fetching the canonical label. Both navigation stages check the domain and label. An unrelated review route discards it. Save Tags and verify have different paths, audited in §3. |
| 3. R45, annotator projection | **CLOSED** | Two verified observations remained in the denominator until adjudication. The three projections agreed in an independent database check. |
| 4. N02, outer exception sanitization | **PARTIAL** | The two tested wrapper paths drop bound parameters. Free-form driver diagnostics and database sessions outside that dependency can still expose values. |
| 5. N03, connector action dispatch | **CLOSED** | The string type guard precedes set membership. Known strings proceed to payload validation, unknown strings are ignored. |
| 6. Persist receipt across navigation and erase on a new-key notification | **CLOSED** | A normal successful registration now writes a real session receipt. App erases it on a keyed storage event even with Signup unmounted. F6-01 qualifies the broader logout guarantee. |

### 1.1 Cross-tab ownership and receipt

Full storage handler, `frontend/src/App.tsx:54–57`:

```tsx
    const onStorage = (event: StorageEvent) => {
      if (event.key !== 'rgi-api-key') return
      applyKeyChange(localStorage.getItem('rgi-api-key') ?? '')
    }
```

**One condition gates invalidation.** The same-tab handler has a separate value comparison at lines 58–61. The storage handler has none. Its call to `applyKeyChange` sets the active ref, synchronously dispatches `dlj-account-changing`, removes checkout and registration receipts, and resets domain state. On Signup it updates the sidebar key and stays on the route. On an active import it lets Upload abort in place. Other routes go to Upload and reload. The helper removes the registration receipt at line 41, before any route-specific return.

| Step on mounted Signup | Active value, epoch and effect |
|---|---|
| Registration begins under A | `myEpoch = 1`, current epoch 1. |
| Notification for B arrives | The key-name test accepts it. App reads the current storage value (B, or A if both writes already happened). The synchronous account-change listener increments the epoch to **2**, clears visible and stored receipt, and clears busy. App resets domain/checkout state. |
| Notification for A arrives | The same actions run again even if the previous read also returned A. Epoch becomes **3**. Active key now reflects A. |
| Original response resolves | `Signup.tsx:69–70` compares 1 with 3 and exits before adoption, receipt creation or domain changes. |

The storage key is `deferredKey = 'dlj-deferred-registration'`. These are the two writes in `Signup.tsx:74,83`:

```tsx
sessionStorage.setItem(deferredKey, JSON.stringify({ result, startingKey, active: false }))
sessionStorage.setItem(deferredKey, JSON.stringify({ result, startingKey: result.api_key, active: true }))
```

On ordinary signup the active key changes first and triggers synchronous account cleanup, then line 83 writes the new owner-bound receipt. Navigating away invalidates pending requests at lines 47–51 and leaves the completed receipt in session storage. A subsequent new-key storage notification executes App line 41 even while Signup is unmounted. On remount, lines 8–16 independently reject a receipt whose owner differs from the current key. Settings save/clear and sidebar commits still issue the local event. Active receipt persistence deliberately adds another plaintext copy in the same browser tab. The whole-storage clear case in §3 is a concrete lifecycle gap.

### 1.2 Draft restoration

`ReviewCard.tsx:193–200` checks the callback still owns the source route, sets **`preserveDraft.current = true` at line 195**, snapshots input, dirty lists, domain and source ID at lines 196–198, then refetches at line 200 for a same-ID response. The actual POST body returned by `labeling_router.py:693–694` names the predecessor in `label_id` and puts the successor database UUID in `revision_id`. The successor public label ID comes from the canonical GET.

For a draft of `urgent`, the first detail load follows the predecessor. At `ReviewCard.tsx:85–91` it records the returned successor as `expectedLabelId` and redirects without replacing the input. The new route effect at lines 62–74 keeps the draft only for its source or expected successor in the same domain. On the successful successor load, lines 95–105 restore `urgent`, set **`preserveDraft.current = false`**, and discard the snapshot. On a manual transition to another label or domain, lines 66–71 instead reset the flag and clear the input. Leaving the screen unmounts the refs. A failed canonical read leaves the flag set while the same route remains mounted (F6-04). The successful category path has the requested one-navigation behavior.

### 1.3 Verified-evidence queries

The annotator profile has two WHERE clauses. The ranking subquery counts current items per named annotator. The evidence aggregation admits current items and effective verified predecessors. In `dashboard_router.py:264–275` they are:

```python
.where(LabelLog.domain_id == domain.domain_id,
       LabelLog.tenant_id == session.info.get("tenant_id", ""),
       LabelLog.superseded_by.is_(None), annotator.is_not(None))

.where(LabelLog.domain_id == domain.domain_id,
       LabelLog.tenant_id == session.info.get("tenant_id", ""),
       or_(LabelLog.superseded_by.is_(None), verified))
```

The overview accuracy comes from the final cumulative sample in `_curve`. Its complete WHERE clause for an overview request is at `dashboard_router.py:199`:

```python
.where(LabelLog.domain_id == domain_id,
       LabelLog.tenant_id == session.info.get("tenant_id", ""), verified)
```

The optional category condition on line 201 applies only when that helper receives a category. The overview’s separate current-scored-label count at lines 223–227 supplies `total_labels`. It does not filter accuracy. In both accuracy queries `verified` requires a timestamp, a non-null outcome and `active_verified_evidence()` (lines 36–37). The recursive predicate at `db/repository.py:154–179` checks verified descendants inside the same tenant/domain chain. Category statistics use it at `labeling_router.py:291–313`.

| Independent disposable SQLite check | Annotator count / accuracy | Overview count / accuracy | Category A | Category B |
|---|---|---|---|---|
| Two verified A labels, one correct | 2 / 0.5 | 2 / 0.5 | 2 / 0.5 | 0 / null |
| Incorrect A revised to B, unverified | 2 / 0.5 | 2 / 0.5 | 2 / 0.5 | 0 / null |
| Successor verified correct | 2 / 1.0 | 2 / 1.0 | 1 / 1.0 | 1 / 1.0 |

### 1.4 Database diagnostics and webhook dispatch

The diagnostic transformation at `db/connection.py:38–56` is:

```python
def sanitize_url(url: str) -> str:
    """Hide URL userinfo and credential-like query parameters in diagnostics."""
    parsed = urlsplit(url)
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if ":" in userinfo:
            netloc = f"{userinfo.split(':', 1)[0]}:***@{host}"
    query = urlencode([(key, "***" if key.lower() in {"password", "token", "api_key"} else value)
                       for key, value in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit(parsed._replace(netloc=netloc, query=query))


def sanitize_database_error(exc: Exception) -> str:
    """Use the driver diagnostic, never SQLAlchemy's SQL and parameter dump."""
    source = exc.orig if isinstance(exc, DBAPIError) else exc
    message = str(source)
    return re.sub(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"\]\}]+",
                  lambda match: sanitize_url(match.group(0)), message)
```

`get_db` rolls back and raises a new exception with suppressed chaining for SQLAlchemy errors at lines 86–91. Scheduler applies the same formatter at `scheduler.py:118–119`:

```python
    except Exception as exc:
        logger.error("Scheduler error: %s", sanitize_database_error(exc))
```

Direct formatter checks returned `postgresql://user:***@host:5432/db` for the supplied embedded-at-sign password and left `postgresql://user@host:5432/db` intact, without raising. **All exception paths are not covered.** Driver constraint diagnostics can quote failing keys or row data as ordinary text, and other SQLAlchemy exception classes can include statements/parameters in their own string. Both survive URL-only substitution. Billing’s private webhook session at `billing.py:199–241` bypasses `get_db`, migration uses its own engine transaction at `db/migrate.py:75–78,156–161`, and the engine at `db/connection.py:62–63` has no parameter-hiding setting. N02 stays P1. The production-safe boundary should log approved fields such as operation, exception class, SQLSTATE and correlation ID, and roll back independently of formatting.

The dispatch order at `label_studio.py:254–258` is:

```text
254     action = payload.get("action")
255     if not isinstance(action, str):
256         raise HTTPException(400, detail=f"action must be a string, got {type(action).__name__}")
257     if action not in {"ANNOTATION_CREATED", "ANNOTATION_UPDATED"}:
258         return {"status": "ignored"}
```

A dictionary, null, 42 or a list all reach line 256 and return 400 on an authenticated call. The test actually posts the dictionary. The other three follow the same type branch by inspection. The literal string `"valid_action"` passes the type check and returns 200/ignored as an unknown event. The two supported annotation strings continue into project, payload and task validation.

## 2. Broad backend audit

### Newly recorded findings

| ID | Severity | File and line | Failure and closure criterion |
|---|---|---|---|
| B6-01 | **P1** | `db/connection.py:81–94`, `labeling_router.py:33,516–517`, `auth.py:58–65`, `requirements.txt:1` | Request teardown commits after success has been sent. A commit-time failure can roll back an acknowledged batch, label verification, or newly issued key. The browser counts acknowledged rows as committed. On FastAPI 0.163.1, the actual batch session dependency has scope `None`, which selects the request exit stack. A local ASGI timing check using the real dependency and an instrumented successful session observed **response start → response body → commit**. Commit before emitting success on every shared write path, preserve rollback, and test the ASGI messages on a failed commit. Deliver signup email only after durable issuance. |
| B6-02 | **P1** | `label_studio.py:279–295,319–337`, `db/repository.py:252–285` | A delayed older annotation update can supersede a newer verified correction and train again. Idempotency compares only the current action/outcome/reviewer. That detects an immediate duplicate, but cannot distinguish an old redelivery from a genuine change back to the prior value. Serialize per source annotation and check durable delivery identity and source revision/order before learning. Define reconciliation for events without reliable ordering. Source finding, independent of R29’s config-file race. |
| B6-03 | **P1** | `billing.py:159–171`, `jm_service.py:288–312` | The public Paddle receiver buffers the entire request before authentication, including when live configuration would return 503. This route has no application byte budget or admission limit. Concurrent large deliveries can exhaust the shared process before signature validation. Apply an observed-byte limit while retaining the exact signed bytes, or verify an enforced equivalent upstream. Deployment ingress limits and production impact were not measured. |
| B6-04 | **P2** | `db/connection.py:40,55–56`, `scheduler.py:118–126` | The diagnostic regex stops before a closing square bracket. A valid bracketed IPv6 URL in an error can therefore hand `urlsplit` an incomplete host. If formatting raises inside the scheduler’s exception handler, the hourly task exits. Make diagnostic formatting total and provide a safe fallback. Independent of a password being present. |

### Coverage and retained findings

| Area | Evidence and disposition |
|---|---|
| Auth and tenant isolation | `auth.py:69–95` hashes the presented DLJ key, checks active status and puts tenant and key digest in the session. `labeling_router.py:47–64,380–517,520–600,604–615,697–755,758–824,827–846` covers guidelines, ingest, verify, bulk, batch, sample, tasks, relabel, pending, content, both detail aliases and autonomy. Public domain IDs are tenant-derived, and label reads/writes further constrain tenant and domain. The pending search is a bound predicate under those filters. No cross-tenant label route found in this review. Signup still issues a key before mailbox proof (R08). Admin issuance checks the configured admin secret. |
| Legacy boundary | `jm_service.py:57–103,317–339,438–456,525–605` uses a separate SQLite store and a different credential lookup. The legacy routes still run in the same process and are mounted publicly. Store/auth isolation is present. Network isolation, production usage and backup access were not established. See accepted risks in §5. |
| Revision integrity and current evidence | HTTP relabel locks the scoped current row, validates the predecessor token, rejects no-op changes, links the successor and either writes the edited kind or copies the existing child (`labeling_router.py:608–652,672–694`). Connector correction copies text, source IDs, image/spans/tags and provenance in the write transaction (`db/repository.py:252–285`). Both adapters retain predecessors. SQLite concurrency remains R24. Existing **P2**: first-time content attachment at `labeling_router.py:758–765,790–795` can enrich an already verified revision without a new evidentiary record. Initial attach and edit also differ on vocabulary and size limits. Review the immutable-content contract before export. |
| Bulk and learner | `labeling_router.py:440–488` scopes and locks requested rows, skips verified/stale items, reserves quota per processed item, and passes the explicit `payload.outcome` as `VerifyRequest.verified_outcome`. `db/repository.py:289–315` persists it and calls `learn(outcome_correct=...)`. `jm_core.py:346–377` uses that value for the outcome trackers, while centroid target and engine conservation track the reviewer’s action and recommendation agreement. Dashboard category accuracy uses stored verified truth. Omitted/null outcome still supplies action-derived truth to learning (R13). |
| Connector | Configure/predict/webhook require connector token plus tenant key. Setup uses the connector token and server-configured tenant or saved config (`label_studio.py:37–45,165–205`). Annotation lookup and successor traversal are tenant/domain scoped. The type guard closes N03. First creation is still racy (R04). Config replacement uses a unique temp file and a process-local lock (R29). Prediction replay still reads the original scored row, a prior **P2** at `label_studio.py:210–225`. B6-02 concerns verified update order, including within one process. |
| Billing, quota, retention | `billing.py:162–169,180–241` fails closed in live mode without a secret, handles cancellation separately from product validation, and commits provider receipts with supported transitions. Customer-first binding and incomplete subscription states remain R02/R19. `trial_guard.py:67–106` rolls UTC counters, enforces the cap before increment and applies 50/day after effective cancellation. Single/batch scoring, sample creation and initial connector scoring reserve capacity; replay of existing work does not. Bulk verification reserves, individual verification and non-scoring edits do not. Unscored tasks do not reserve until classification. Those differences are existing policy, and an expired key can still authenticate on non-reservation routes. Account display still uses stored-tier caps at `account.py:44–49` (**P2**). Retention rechecks all siblings under SQLite `BEGIN IMMEDIATE` or a PostgreSQL table guard and ordered row locks before delete (`scheduler.py:65–107`). SQLite cleanup is serialized within its transaction. Other writes lack the equivalent guard. PostgreSQL lock contention/deadlock risk remains **P2**, and the cleanup log counts retired keys as tenants (**P3**, `scheduler.py:98,117`). |
| Input model inventory | `labeling_router.py:36–44,68–107,123–151,155–179,189–262`: GuidelinesPayload enforces 10 KiB; IngestItem/IngestRequest bound IDs, UTF-8 text and finite factor values but lack a maximum factor count/key length; IngestBatchRequest bounds items to 100. VerifyRequest checks action membership downstream but its string lacks a model maximum. BulkVerifyRequest bounds/distinguishes 1–200 IDs, restricts action and permits nullable coercible bool. TextTaskRequest enforces 32 KiB. RelabelRequest bounds category/token, 100 spans and 20 normalized tags. EditableNerSpan has strict offsets but unbounded optional mention text before comparison. NerSpan/LabelContentRequest bound offsets via source validation, mention length, tag counts, span count and HTTPS URL. Create allows 1,000 spans and 200-character tags vs edit’s 100 and 50. Authenticated requests can consume resources parsing values later rejected (**P2**). Unbounded persisted path/connector IDs remain R05. `label_studio.py:48–55,198–208` also has no maximum predict task count or factor-map size. |
| Anonymous admission | `label_health/api.py:48–81,84–123` rejects busy requests before parsing, counts received bytes before spooling, limits the complete body to 10 MiB plus 64 KiB and the CSV to 10 MiB. One deadline covers form parsing and file read; 408/error releases the permit. Worker timeout returns 504 while the running future retains its permit until completion. Existing **P2**: a successfully parsed form with the wrong file field returns 422 before the explicit close block. The public billing receiver does not share this admission code. |
| Error surfaces | `jm_service.py:274–289` constructs FastAPI with default debug disabled. Controlled route errors use HTTP detail and unexpected errors normally produce a generic 500 body. No application traceback-to-client response was identified. Private server diagnostics have the separate N02 failure; a generic HTTP body does not sanitize the logs. B6-01 also means teardown can fail after the client has already received a 2xx. |
| Concurrency | `db/repository.py:50–70` protects existing engine writes with a version check. It cannot serialize absent rows. Cleanup’s guard, PostgreSQL sample advisory lock (`labeling_router.py:526–527`), and a same-process config lock have distinct scopes. No transport or SQL transaction makes two separate connector updates arrive in source order. |

## 3. Broad frontend audit

| ID | Severity | File and line | Failure and closure criterion |
|---|---|---|---|
| F6-01 | **P1** | `App.tsx:37–64`, `Signup.tsx:37–59,83,116` | The new storage handler ignores the browser’s whole-store clear notification (`key === null`). Other open tabs can retain the sidebar key, domain, visible plaintext signup receipt and cached account data after the active credential has been cleared. The previous handler admitted this event. Invalidate on a relevant local-storage clear as well as a keyed change. Reconcile ownership before displaying sensitive state or submitting a write. Named Settings removeItem still works. |
| F6-02 | **P1** | `Upload.tsx:140`, `HealthReport.tsx:14–21`, `App.tsx:37–52` | “View full report” stores the uploaded File in browser navigation history. Account cleanup clears React and session state but cannot invalidate that file. Back navigation can mount Health Report in another account context, restore the prior CSV from route state and automatically submit it to the anonymous report service. This path needs no stale server response. Pass an ephemeral owner-bound reference and invalidate it on rotation. Source trace; no customer uploads were used. |
| F6-03 | **P2** | `ScoredQueue.tsx:122–126,140–154,186` | Escape clears IDs alone, and individual selection toggles leave the old outcome in place. A subsequent selection can inherit a previous batch’s truth choice. The current outcome remains visible and submitting still takes a deliberate click. Reset or reconfirm truth when the selected cohort changes. The explicit Clear Selection button already resets both. |
| F6-04 | **P2** | `ReviewCard.tsx:86–110,193–200` | After a category POST succeeds, a failed canonical fetch leaves the preservation flag and captured draft alive for that mounted route. Only a successful matching load or unrelated route change clears it. A later load can restore an obsolete snapshot. End preservation on terminal failure or own the handoff with a one-use navigation token. |

**Remaining review P1, R3-03.** The successful category callback is now correct. The canonical Save Tags branch at `ReviewCard.tsx:136–151` still calls `load()` without capturing the input on a same-ID POST. In an independent Chromium check, one chip was added, a second tag was typed, and Save Tags returned the real predecessor-shaped response through a local stub. The chip persisted in the successor fixture and the second input became **an empty string**. Separately, `hasUnsavedEdits` at lines 114–118 excludes a nonempty typed tag, so verify at lines 153–168 can navigate away with that draft. Apply the preservation or explicit save/discard rule to both. This is one inherited P1.

| Area | Result |
|---|---|
| Credential and API ownership | Sidebar and Settings local writes still emit the synchronous key event. Rapid keyed cross-tab transitions now invalidate even when the final value matches. `api.ts:163–187` attaches X-Api-Key when available on every protected call, preserves the caller’s captured key for batch import, and checks every non-2xx response, including 401/403. Register and all three health-report calls deliberately omit the header; static sample fetch is public. Most single writes read the live key at submission. A view rendered under an old key can therefore be out of step with a newly written key until the notification runs. Bind sensitive operations to the identity that loaded the view. |
| Route contracts | Matched `api.ts:198–260` to mounted routes in `jm_service.py:290–299`. Families include health analyze/HTML/PDF, register, ingest/batch/sample, individual/bulk verify, tasks, pending, both item writes and detail, dashboard overview/corrections/annotators/factors/compounding/IAA, autonomy/guidelines, account/domain resolution and checkout. All named calls have handlers. Bulk sends **outcome**, individual verify sends **verified_outcome**. Pending requires a valid X-Total-Count. JSON success is generally a TypeScript cast, not runtime DTO validation. |
| Queue | Domain, category, raw/applied search, sort key/order, page size and offset clear selection and outcome at `ScoredQueue.tsx:43–65`. A loaded-query guard hides stale rows and submit intersects selected IDs with the displayed page. Refresh prunes vanished IDs. An earlier same-domain bulk completion can still clear a newer selection (**P2**, lines 147–159). Preview visibility is display-only. |
| Upload and reporting | Observed key rotation aborts the controller, invalidates analysis, clears the File, sample, report, progress and three task fields, and replaces the file picker (`Upload.tsx:27–46,92–130`). Unmount aborts and releases local state. An in-flight server commit can outlive an aborted fetch. Ordinary validation/network errors retain the file for retry. `CsvDropzone.tsx:5–9` accepts drops while busy, and `HealthReport.tsx:14–24` lacks a response generation guard (**P2**): the preview and chosen PDF can refer to different uploads. F6-02 survives even successful rotation cleanup. |
| Review components | The synchronous lock at `ReviewCard.tsx:44–51` guards span/tag saves, verify/override and CategorySelector’s async save. All release in finally. `CategorySelector.tsx:28–40` takes the parent lock, awaits the parent callback and releases it. `TagSelector.tsx:19–43` changes parent draft state via callbacks and disables input/chips/suggestions. `NEREditor.tsx:39–46,70–95,103–111` checks disabled before editing and uses the parent callback. Their own popup/filter state is local. Manual navigation to an unrelated item cannot inherit the category handoff. A dirty manual navigation can still discard edits (R3-03). |
| Settings and analytics | `Settings.tsx:129–139` handles absent/null usage and all six nullable fields. Missing counters can still read as zero and a missing monthly cap as Unlimited (**P2**). Refresh on focus/poll has no response-generation guard (lines 70–89). `Dashboard.tsx:21–38` and `AnnotatorProfiles.tsx:13–26` ignore late writes after a domain change but can show the last loaded domain’s metrics while the new one loads or fails (**P2**). |
| Remaining components, events, build | Reviewed all eight screens and 18 TSX components, including the presentation components, report display, image, NER viewer, guidelines, agreement and both keyboard components. Window listeners for key/storage/focus/keydown and queue intervals have cleanup; no unmatched permanent application listener was found. No `@ts-ignore` or `@ts-expect-error` in frontend/src. `main.tsx:7–9` mounts HashRouter under StrictMode. `frontend/vite.config.ts:7` hardcodes localhost:8000 for the **development proxy**. Production uses the API base configured in `api.ts:1`. `Dockerfile:1–6,24–29` builds with Node/npm ci and copies dist to the Python stage. Frontend/E2E type checks and a fresh production build passed. Docker/Railway execution was outside this run. |

## 4. Suite health and regression-test quality

| Run on this working tree | Result |
|---|---|
| Full pytest collection and run with `--timeout=30`; three Docker-live modules and `test_ops_e2e.py` excluded | **437 collected, 436 passed, 0 failed, 1 skipped**, 238.59 s. The emitted skip was `test_migration_fixes.py:135: requires SQLite`. Some suites choose their own dialect; this is not a claim that all 437 were run separately on both. |
| Explicit PostgreSQL, `test_round5_fixes.py` | **4 passed** in 11.05 s. The shared fixture uses a private schema for DB-backed cases. The two sanitizer cases use mocked failures. |
| Explicit SQLite, `test_round5_fixes.py test_migration_fixes.py` | **9 passed, 1 PostgreSQL-only skip** in 7.39 s, including all four round 5 cases. An initial optional run supplied an empty database URL and failed at collection. This result used a valid SQLite URL. |
| Playwright list and full Chromium run | **121 tests in 13 files; 121 passed** in 40.4 s, three workers, zero retries. The local server’s JS matched the local dist asset byte-for-byte. The fresh Vite build produced the same entry filename. |
| TypeScript/build | Application and E2E no-emit checks passed. Vite built 451 modules into a temporary output directory. A first attempt passed the output path to npm with the wrong argument forwarding; invoking Vite directly succeeded. |

**Reversion sensitivity** below is inferred from the old and new paths. No tracked source was reverted. The source-check script counts strings/conditions and prints a fixed red/green table at `scripts/check_round5.py:84–97`; that table supplies no independent execution evidence.

| Round 5 Python test | Actual assertion | Would reverting the fix fail it? Does it cover the original failure? |
|---|---|---|
| `test_annotator_projection`, line 38 | Scores two rows for one annotator, verifies one positive and one negative, revises the negative, checks profile and overview accuracy both stay 0.5, verifies the successor, checks both become 1.0. | **Yes; exact HTTP projection case.** The old profile would show 1.0 just after relabel. The test omits explicit denominator and category assertions. The independent §1.3 check covers both. |
| `test_request_session_exception_hides_database_password`, line 69 | Drives the real dependency through a mocked commit failure, requires the password be absent and a safe host marker remain in the raised message. | **Yes for the old wrapper. Partial for N02.** Its password is present only in SQLAlchemy’s parameter dictionary, and the driver text is innocuous. Merely choosing `exc.orig` passes without exercising URL masking. No outer ASGI log, failing-row detail, or send/commit ordering is asserted. |
| `test_scheduler_log_hides_database_password`, line 96 | Injects the same exception through the scheduler and inspects the actual captured ERROR log for absence of password and presence of host. | **Yes for the old exception logger. Partial for N02.** The same fixture cannot detect sensitive driver text, a formatter exception or scheduler-loop termination. |
| `test_connector_rejects_nonstring_action`, line 107 | An authenticated raw TestClient posts a dictionary action, requires **400** and the expected error message. | **Yes; exact dispatch failure.** Before the guard, set membership raises before validation. Add the other invalid types and a valid configured event as controls. |

| Round 5 Playwright test | Actual assertion | Would reverting the fix fail it? Does it cover the original failure? |
|---|---|---|
| Cross-tab B then A, `fix_round5.spec.ts:12–37` | Holds registration, keeps Signup mounted, delivers two keyed StorageEvents with the live value already A, releases the response and checks form, receipt absence and unchanged key. | **Expected yes; faithful handler-level regression.** Old code ignores both notifications. The events are constructed in one page. It does not establish native two-tab timing or whole-storage clear. Waiting for the HTTP response alone is weaker than waiting for a positive application-side completion marker. |
| Canonical draft, lines 39–75 | Types `urgent`, relabels, asserts predecessor refetch, successor URL/heading and preserved input. | **Yes; exact category path.** The POST mock returns the real predecessor-shaped DTO and the GET returns the successor. It does not exercise Save Tags, verify, manual navigation or a failed successor read. |
| Persistent receipt, lines 77–97 | Requires a real nonempty receipt before and after unmount, then polls storage after a keyed event and checks the old receipt is absent on remount. | **Yes for either missing persistence or keyed cleanup.** The precondition prevents the previous vacuous pass. It simulates a notification rather than changing the shared store in another tab. It cannot establish the clear-event behavior. |

The highest-value missing assertions are a commit failure observed at the actual ASGI send boundary, stale connector delivery after an intervening update, bounded billing intake, value-free diagnostics on direct and dependency-managed sessions, and interaction tests covering real cross-tab logout, report history and the remaining tag draft. Pair streamed-input tests with a successful ordinary request afterward. Retain migration parity and two-writer tests for the structural gates.

## 5. Definitive P1 scorecard

**Seven patchable, nine structural launch blockers and three accepted legacy risks.** New counts compare to the round 5 open ledger. N02 and R3-03 are inherited. The five new P1s are B6-01/02/03 and F6-01/02. R45, N03 and the original keyed signup finding leave the P1 ledger. Thus **17 previously open − 3 closed + 5 newly identified = 19**. Broader design work may absorb these repairs, but each patchable item has a separable release criterion.

| Patchable ID | Side | File:line and failure | Existing test coverage |
|---|---|---|---|
| N02 | BE | `db/connection.py:51–65,81–94`, `scheduler.py:119`, `billing.py:199`. Driver diagnostics or unwrapped SQL exceptions reach outer logs. | Two round 5 tests cover wrapper parameters only. No complete diagnostic boundary test. |
| B6-01 | BE | `db/connection.py:81–91`, `labeling_router.py:33`. Client can receive success before a failed commit. | No wire/commit-order regression located. §2 observed the actual ordering. |
| B6-02 | BE | `label_studio.py:279–295,319–337`. An older update becomes current and trains a second time after a newer correction. | `test_label_studio.py:123,230,262` exercises forward updates and reviewer changes. No stale-redelivery-after-update test located. |
| B6-03 | BE | `billing.py:159–169`. Unauthenticated body buffering can exhaust the shared process before signature verification. | `test_billing_fixes.py:62–92` covers signature policy. No body budget/stream admission test located. |
| R3-03 | FE | `ReviewCard.tsx:114–118,136–168`. Typed tag text can disappear during Save Tags or verification. | Category case and in-request locking are covered. Independent Save Tags check observed the loss. |
| F6-01 | FE | `App.tsx:54–60`, `Signup.tsx:116`. Whole-store clear leaves sensitive UI and receipts live in another tab. | Keyed rotation and individual key removal covered. No native other-tab clear test located. |
| F6-02 | FE | `Upload.tsx:140`, `HealthReport.tsx:14–21`. An earlier account’s source file can be restored and resubmitted from browser history. | Ordinary upload/report and interrupted import covered. No owner-rotation/history test located. |

| Structural ID | Since round 5 | File:line, impact and disposition |
|---|---|---|
| R02 | UNCHANGED | `billing.py:120–138`. A same-tenant customer match can override the purchasing key and grant the wrong entitlement. Prompt 02. |
| R04 | UNCHANGED | `db/repository.py:24–31,50–67`, `label_studio.py:135–144`. Concurrent first-domain/engine writers can observe absence, collide, and return an uncontrolled failure. Prompt 05. |
| R05 | UNCHANGED | `labeling_router.py:565–595`, `label_studio.py:263–273,308–318`. Path/derived source and reviewer IDs bypass bounds at persistence. PostgreSQL and SQLite can disagree. Prompt 03. |
| R08 | UNCHANGED | `auth.py:47–66`. A working key reaches the requester and the supplied email before mailbox ownership is proven. Prompt 03. |
| R19 | UNCHANGED | `billing.py:180–185,214–235`. Unsupported states, replacement subscriptions and reactivation after retirement are not consistently represented. Prompt 02. |
| R23 | UNCHANGED | `db/migrate.py:118–145`. PostgreSQL-only renaming can leave historical provider linkage unavailable to new SQLite readers. A second identical schema does not prove values migrated. Prompt 02. |
| R24 | UNCHANGED | `trial_guard.py:72–103`, `labeling_router.py:608–611,679–686`. SQLite lacks the row locking assumed by ordinary quota and revision writes. The retention writer guard covers its own transaction. Prompt 05. |
| R29 | UNCHANGED | `label_studio.py:32,170–185`. Atomic file replacement protects file contents, but concurrent processes can overwrite each other’s acknowledged config update. Prompt 05. |
| R13 | UNCHANGED | `labeling_router.py:140–145,481–488`. Explicit browser truth persists. Legacy missing/null truth still enters learning as an action-derived boolean. Prompt 05 with 04/S27. |
| R45 | **IMPROVED → CLOSED** | `dashboard_router.py:264–275`. Verified lineage is now included in the annotator aggregation. Excluded from the nine. |

| Accepted structural risk | Since round 5 | Isolation and condition |
|---|---|---|
| R06 | UNCHANGED | `jm_service.py:541–551,596–605`. Legacy engine and decision commits are split. Separate JM SQLite data and legacy bearer lookup. Deferred to v1.1. |
| R07 | UNCHANGED | `jm_service.py:57–95,317–322,438–447`. Legacy store and its backups contain reusable bearer keys. DLJ hashes do not protect those records. Deferred to v1.1. |
| R30 | UNCHANGED | `jm_service.py:175–181,327–339`, `jm_core.py:200–206,348–350`. New domains reject the separator; old snapshots still have ambiguous centroid keys. Deferred to v1.1. |

These three remain separately counted as the merged plan specifies. Their storage and authentication scope is legacy-only. They share the DLJ process, and the repository cannot confirm perimeter restrictions or zero production consumers. Revisit acceptance if that operational assumption changes. [Merged plan](../design/dlj_arch_redesign_v2.md)

## 6. Prompt 00 gate

| Condition | Result |
|---|---|
| All patchable P1s closed | **NO — 7 remain** |
| Frontend P1 = 0 | **NO — 3 remain** |
| Test suite green | **YES** for the specified suites and exclusions |
| All round 5 fixes independently closed | **NO — 5/6**, with N02 partial |
| Remaining P1s exclusively structural and covered by the plan or accepted for v1.1 | **NO** |
| Final verdict | **NOT READY** |

**Required before making the gate decision again**

1. **Commit before success** (`db/connection.py:81–94`, shared Session dependency at `labeling_router.py:33`). Make the commit a prerequisite to sending write success. Check a commit-time failure produces no success response, partial data or prematurely delivered key.
2. **Contain diagnostics** (`db/connection.py:38–65,81–94`, `scheduler.py:118–126`, `billing.py:199`). Use a field allowlist at all database boundaries, including billing/migration, and a formatter that cannot stop the scheduler. Assert that server/worker diagnostics omit credentials, parameters and driver-detail values.
3. **Order connector changes** (`label_studio.py:279–295,319–337`). After a newer correction commits, an older delivery must leave the current revision, effective evidence and learner state unchanged.
4. **Bound billing intake** (`billing.py:159–169`). Verify a real enforced ingress limit or enforce cumulative bytes, intake time and concurrency before buffering. Preserve byte-exact verification for supported ordinary deliveries.
5. **Complete review-draft ownership** (`ReviewCard.tsx:114–118,136–168`). Carry typed input through a canonical tag save. Require a decision before verify/navigation discards a pending draft. Assert outcomes on the real predecessor/successor contract.
6. **Invalidate the whole browser account context** (`App.tsx:37–64`, `Signup.tsx:37–59`). Preserve keyed A→B→A behavior and also erase sensitive UI/cache state after a native other-tab storage clear, including when Signup is unmounted.
7. **Remove source files from browser history** (`Upload.tsx:140`, `HealthReport.tsx:14–21`). Use an expiring owner-bound handoff and prove Back after rotation cannot recover the old upload or trigger a report request.

Run the existing suites and add the missing failure assertions above. The nine structural launch blockers and three accepted legacy risks retain their separate plan gates. This audit used the local repository, disposable data, and a local Chromium bundle. It establishes neither a production incident nor a live Railway or Paddle verification.
