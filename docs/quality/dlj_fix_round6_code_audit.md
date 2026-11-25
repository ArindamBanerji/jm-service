# DLJ round 6 executable and code audit

25 November 2026. This audit is for the final round 6 working tree. `python scripts/check_round6.py` enumerates all injected-session write routes and checks the storage, history, draft and diagnostic invariants at runtime. The focused regression files are `test_round6_fixes.py` and `e2e/fix_round6.spec.ts`.

## Red and green evidence

| Fix | Red, before application change | Green, after change | Reversion sensitivity |
|---|---|---|---|
| B6-01 | Verify returned **200** on injected commit failure; test expected 500 | Commit-failure and persisted-success tests pass | Removing the explicit commit makes the first assertion receive 200 again. |
| N02 | SQL text exposed `dlj_secret_key`, formatter raised `format boom` | Diagnostic and total-formatter tests pass | Returning raw exception text fails the secret assertions. |
| B6-02 | Older update restored `approve/7` after correction to `reject/8` | Ordering test passes on both databases | Without source version comparison the old event creates another revision. |
| B6-03 | 65,537-byte unsigned body returned **422**, expected 413 | Size and no-Content-Length stream tests pass | `request.body()` consumes and parses the entire body. |
| R3-03 | After Save Tags, typed `important` became empty | Save Tags browser test passes | Without draft snapshot the canonical route effect clears the input. |
| F6-01 | Whole-store clear left sidebar key `key-A` | Clear-event browser test passes | A keyed-only storage handler ignores the null event. |
| F6-02 | Browser `history.state.usr.file instanceof File` was **true** | History/back browser test passes | Passing the File in navigation state restores it after Back. |

## Shared transaction boundary

`db/connection.py`:

- `sanitize_url` (lines 39–51) is retained from round 5. The new formatter uses only approved fields, so no caller emits the full sanitized URL.
- `sanitize_database_error` (lines 54–76): the `try` and final fallback make the formatter total; the exception class is safe; the statement regex retains only operation and table; the SQLSTATE filter accepts only five alphanumeric characters; URL parsing emits only host, including bracketed IPv6; the unreachable-host branch keeps a safe diagnostic; no statement values, parameters, passwords, driver detail or traceback are emitted. Empty or malformed input returns the class or generic fallback. The function has no mutable shared state.
- `commit_write` (lines 79–89): commit precedes the endpoint return; a failure rolls back, suppresses rollback failure, and raises a sanitized 500. A second concurrent call uses its own session. No success response can be produced by this helper after a failed commit.
- `get_db` (lines 112–127): yields one session and has no post-yield commit. SQLAlchemy failures roll back and suppress raw chaining; other exceptions roll back and re-raise. Both rollback branches suppress cleanup errors so a failed rollback cannot replace the sanitized exception or intended HTTP status. Endpoint validation errors retain their HTTP status. Session context closes on every path.

`labeling_router.py`: `put_guidelines` (61–66), `ingest` (382–395), `verify` (397–439), `bulk_verify` (442–497), `ingest_batch` (500–526), `seed_sample` (529–571), `create_text_task` (574–613), `relabel_item` (616–707), and `create_label_content` (771–813) each reach `commit_write` after their final mutation and before success return. Each added call has the same rollback and sanitized error behavior. Validation branches throw before commit. `verify` defers its own commit only while called inside `bulk_verify`; bulk commits once after processing the entire request. A failed bulk operation leaves the session for dependency rollback. The response DTO is constructed after durable commit for every route except `verify`, where the already computed values are placed in a DTO after commit. `pending` is a read route and has no commit.

`auth.py`: `register` (49–68) flushes to detect duplicate email, commits the key, **then** attempts email delivery and returns it. A failed commit cannot email or return a working key. `create_key` (109–119) commits before returning the secret. `account.py:resolve_domain` (74–85) commits the public-domain mapping before acknowledgement; this write route was found by the exhaustive search beyond the requested file list.

`label_studio.py`: `setup` (189–197) commits only if domain setup runs; `predict` (200–252) commits scoring before returning predictions. `webhook` (255–380) checks action type before set membership, parses an optional timezone-aware source timestamp, follows the current revision under the tenant/domain scope, and rejects a timestamp older than or equal to the stored source version. If reliable ordering is absent, it looks for the same action/outcome/reviewer in a predecessor and acknowledges an exact redelivery without learning. The first verification stores source time; a correction stores it on the successor before committing. Branches that mutate annotation metadata, verification or learner state commit before response; ignored and malformed branches make no write. The source time is persisted in `LabelLog.source_updated_at`. A timestamp-free event that genuinely returns to an earlier value requires reconciliation rather than automatic replay, by design.

`db/models.py:LabelLog` adds nullable `source_updated_at` (line 61). `db/migrate.py` adds the column on upgrades, includes it in SQLite rebuild copy, uses timezone-aware PostgreSQL DDL, and converts migration/cleanup exceptions to the safe diagnostic. Existing rows start with null ordering metadata; connector history handles exact redelivery in that state. Migration errors do not print SQL parameters.

## Billing and worker boundaries

`billing.py:_billing_session` (163–173) retains the private context manager's commit-before-return behavior. It preserves intentional HTTP errors and converts database/commit failures into a sanitized log plus generic 500. `paddle_webhook` (176–272) checks declared length before reading, counts actual streamed bytes, rejects at 64 KiB before accumulating excess, joins accepted chunks exactly, and uses those bytes for HMAC and JSON parsing. Missing Content-Length follows the same observed-byte budget. Duplicate receipt and entitlement changes remain one transaction.

`scheduler.py:run_scheduled_tasks` (110–125) emits the allowlisted diagnostic; if formatting unexpectedly raises, it logs a generic class-only fallback and returns so the hourly loop remains live. It does not log raw exception objects or tracebacks.

## Frontend ownership

`App.tsx:onStorage` (54–57) handles every keyed API-key notification and every null-key whole-store clear. Both branches enter `applyKeyChange`, which dispatches account invalidation, clears checkout and deferred receipt, resets domain, and either updates the mounted signup/import view or reloads other views. There is no value-equality gate for external storage events. The same-tab event remains separately value-gated.

`ReviewCard.tsx:saveTags` (136–155) waits for a successful relabel, snapshots typed input and current draft under the current domain/label, then loads or navigates. The route effect (62–74) retains only that source or expected successor; `load` (78–112) records the canonical successor, restores the typed input, takes saved tags from the server, and clears the one-use preservation flag. `hasUnsavedEdits` (118) now includes trimmed typed input, so buttons and keyboard verify cannot discard it. CategorySelector remains available with typed input; spans/tags already committed are never marked dirty after the Save Tags response. `saveSpans` has no second typed-tag field for NER content; verify/navigation requires the dirty guard. Unrelated route changes clear the snapshot.

`Upload.tsx` passes only an opaque one-use reference into route state. `reportHandoff.ts` keeps the File in memory with its originating key, deletes the reference when consumed, rejects a different current key, and clears all references on account change. `HealthReport.tsx:analyze` (18–23) uses a generation to ignore late responses; its route effect consumes the reference once; its account-change effect clears the displayed File/HTML and invalidates in-flight responses. Back navigation cannot retrieve a consumed reference and cannot auto-submit an earlier account's file. A page reload loses the one-use handoff, requiring the user to upload again.

## Endpoint enumeration result

`python scripts/check_round6.py` found **15 injected-session write endpoints, 15 explicit commits, 0 missing**. Billing's webhook uses a separate transaction context that exits before success return. The health-report routes do not write to the labeling database. The script also confirmed no dependency auto-commit, both storage-event branches, no File in history state, both draft preservation paths, tag-input dirty checking, and total diagnostic formatting.
