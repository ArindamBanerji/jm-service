# Session State — jm-service

## Repo layout

```
jm-service/
  jm_core.py          — JM engine (443 lines): centroids, scoring, learning, conservation gate
  jm_service.py        — FastAPI service (558 lines): multi-tenant API wrapping jm_core
  jm_experiment.py     — Engine validation suite (381 lines): 4 experiments
  jm_api_demo.py       — End-to-end API demo (214 lines)
  test_jm_service.py   — Integration tests (471 lines): 26 pytest tests
  Dockerfile           — Container build
  docker-compose.yml   — Compose config
  requirements.txt     — Python deps (fastapi, uvicorn, pydantic, httpx, pytest)
  docs/session_state.md — This file
```

## Frozen files

Do NOT modify these files without explicit approval. Check hashes before and after any change.

| File | MD5 | Notes |
|---|---|---|
| `jm_core.py` | `1301b8934ac6368651627bbbd309bbf2` | Engine — centroids, conservation gate, state export/import |

## Standing rules

1. **mypy after every code change** — `python -m mypy <changed_file>` and fix before proceeding
2. **26 integration tests must pass** — `python -m pytest test_jm_service.py -v` after any service change
3. **4 engine experiments must pass** — `python jm_experiment.py` after any engine change
4. **No git operations from Codex** — changes stay local, human pushes
5. **Session state protocol** — read this file as STEP -1, append results as FINAL STEP

## Current file hashes

| File | MD5 |
|---|---|
| `jm_core.py` | `1301b8934ac6368651627bbbd309bbf2` |
| `jm_service.py` | `e7b608f4a62990c1e84e8d7dac6eb6ca` |
| `test_jm_service.py` | `207aa63eada41977fab4e9ef4a84de44` |
| `jm_experiment.py` | `d6421076d766b0918fbb29116355189b` |
| `jm_api_demo.py` | `360fd7734506940db8b8858da5c87167` |

## Results log

| Date | Task | Result | Notes |
|---|---|---|---|
| 2026-10-19 | Initial setup + lifespan fix | PASS | 4/4 experiments pass, 26/26 tests pass, 8 API endpoints verified, smoke test passed. Replaced deprecated `on_event("startup")` with `lifespan` async context manager. |
| 2026-10-20 | E-JM-8 head-to-head | PASS | No sustained crossover; final JM−k-NN gap at N=500+ = -27.35 pp (95% CI -33.33 to -20.56 pp); conservation gate fired on 39 scored decisions. |
| 2026-10-20 | E-JM-9 ablation stability | PASS | Smallest N excluding zero = 200; CI width at N=1000 = 6.30 pp; one allowed near-monotonicity violation. |
| 2026-10-20 | E-JM-8 head-to-head v2 | PASS | crossover=546, final_gap=-4.50pp [95% CI -8.60, -0.30], gate_fires=41, evictions=800 |
| 2026-10-20 | E-JM-9 ablation stability v2 | PASS | CI_excludes_zero_at=none, effect_at_1000=+2.10pp [95% CI -1.50, +5.70], CI_monotonic=yes |
| 2026-10-20 | E-JM-8 head-to-head v4 | PASS | crossover=410, final_gap=+0.90pp [95% CI -1.70, +3.50], gate_fires=247, evictions=1800 |
| 2026-10-20 | E-JM-9 ablation stability v4 | FAIL | CI_excludes_zero_at=N2000, effect_at_2000=+2.25pp [95% CI +0.05, +4.30], CI_monotonic=no; one large 0.00→20.00pp width violation |
| 2026-10-20 | E-JM param sweep v5 | PASS | recommended: noise=0.10, cap=50, gap=+19.50pp |
| 2026-10-20 | E-JM-8 head-to-head v5 | PASS | crossover=639, final_gap=+6.15pp [95% CI +3.75, +8.35], gate_fires=6, evictions=1800 |
| 2026-10-20 | E-JM-9 ablation stability v5 | FAIL | CI_excludes_zero_at=N500, effect_at_2000=+9.20pp [95% CI +7.20, +11.30], CI_monotonic=no; one large 0.00→36.00pp width violation |
| 2026-10-20 | E-JM charts v5 polished | PASS | 4 charts updated with outreach styling |

## Docker Setup Verification — 2026-10-19
- Changed `Dockerfile`: copies all Python files, exposes/runs on port 8000, and persists SQLite at `/data/jm_tenants.db`.
- Changed `docker-compose.yml`: `jm-api` builds locally, maps `8000:8000`, sets `JM_DB_PATH`, mounts `jm-data:/data`, and health-checks `/v1/health`.
- Created `.dockerignore` with `__pycache__`, `*.pyc`, `.pytest_cache`, `*.db`, and `.git` exclusions.
- Gates: PASS — Dockerfile structure validated without running Docker; Compose YAML/service contract valid; `.dockerignore` complete; 26/26 tests passed.
- mypy: N/A — no Python files modified.

## Invariant ablation table — 2026-11-01

- 6 ablations run (I1–I6), 5 paired seeds × 2,000 decisions, 1,000 paired
  bootstrap resamples. Frozen `jm_core.py` remained unchanged at MD5
  `1301b8934ac6368651627bbbd309bbf2`.
- Results:

| Invariant | Accuracy full | Accuracy ablated | Delta (95% CI) | Prediction |
|---|---:|---:|---:|---|
| I1 decision form | 70.55% | 61.36% | +9.19 pp [8.29, 10.12] | confirmed |
| I2 sigma-mu separation | 62.14% | 60.72% | +1.42 pp [0.84, 1.97] | confirmed |
| I3 acquisition not depth | 70.55% | 66.80% | +3.75 pp [2.94, 4.62] | confirmed |
| I4 exogenous conservation | 62.10% | 61.75% | +0.35 pp [-0.01, 0.72] | inconclusive |
| I5 certified verified record | 68.64% | 61.97% | +6.67 pp [5.72, 7.55] | confirmed |
| I6 re-convergence | 67.27% | 55.19% | +12.08 pp [11.19, 12.97] | confirmed |

- Predictions matched: 5/6; I4 exposed gate gaming (149–162 adversarial
  updates admitted per seed) but its pooled accuracy CI included zero.
- Tests: 7 new, 33 total (26 existing + 7 new), 0 failures. Four original
  engine experiments passed. Mypy passed on all five changed Python files.

## I4 extended ablation (N=10,000) — 2026-11-01

- Result: -0.02 pp [95% CI -0.20, +0.17] for full minus confidence-gated
  ablation, pooled across 5 seeds (50,000 paired decisions; 1,000 bootstrap
  resamples).
- Adversarial updates admitted: 3,455 total; 3,431 bypassed a failed historical
  gate and 2,441 (70.7%) moved centroids away from their canonical targets.
- Confidence calibration: no ablation-side inflation. At N=10,000, ablated
  mean confidence was 0.765 correct / 0.633 incorrect versus full 0.775 / 0.664.
- CI trend: not toward significance. The N=5,000 checkpoint briefly favored
  the ablation (-0.23 pp [-0.38, -0.08]); by N=10,000 the effect returned to
  zero. Per the stopping rule, N=20,000 was not run.
- Verdict: **STILL INCONCLUSIVE**. I4's structural gate-bypass violation is
  confirmed, but it produced no measurable terminal accuracy or calibration
  damage at this scale.

## I4 parameter sweep — 2026-11-01

- Configs tested: 18 diagnostic cells across adversarial intensity, horizon,
  wrong-update penalty ratio, and pairwise invariant removal. Each cell used 5
  paired seeds and 1,000 clean holdout probes per seed; CIs used 1,000 paired
  bootstrap resamples.
- Finding: **Outcome A — I4 matters above a high-adversarial-intensity
  boundary.** At N=10K, I4 was unresolved through 50% injection, protective by
  +8.08 pp [6.64, 9.48] at 60%, +25.68 pp [24.12, 27.30] at 80%, and +34.42 pp
  [32.84, 36.06] at 95%.
- Key threshold: between 50% and 60% uniformly injected plausible wrong labels
  after a 1,000-decision warmup. At 40%, effects were transient/non-monotonic
  across 5K–50K; penalty ratios 2:1–20:1 were unresolved.
- Pairwise result: matched controls showed no positive I4 interaction with I1
  or I5 and only a modest +1.06 pp increment with I2. Intensity, not general
  compositional fragility, is the primary boundary.
- Tests: 21 new sweep tests, 54 combined tests, 0 failures. Mypy passed on all
  changed Python files. Frozen `jm_core.py` remained unchanged at MD5
  `1301b8934ac6368651627bbbd309bbf2`.

## LBL-P2 COMPLETE — 2026-11-18
- `jm_core.py` unfrozen for this prompt, modified, and re-pinned. Original 26 tests are in `test_jm_service.py`; this checkout has no `tests/` directory or pre-existing `pyproject.toml`, so a minimal mypy config was added and pytest targeted the relevant root files.
- Baseline `WelfordState`: count, mean, m2. Baseline export keys: config, tau, eta_confirm, eta_override, centroids, variance_trackers, conservation, total_decisions, total_correct. Baseline `learn(self, decision_id: str, actual_action: str, confirmed: bool = True) -> LearnResult`; `score(self, factors: dict[str, float], category: str) -> ScoreResult`.
- Added: `score_readonly()`, `score_readonly_batch()`, `signal_confidence_inversion()`, `centroid_disagreement()` and correct/incorrect Welford trackers.
- Extended: `learn()` with keyword-only eta, outcome_correct, track_outcome; `export_state()`/`from_state()` preserve dual Welford state and load legacy states without those keys.
- Tests: 26 existing passed + 19 new = 45 total; 0 failures. All four engine experiments passed with UTF-8 console output. Mypy clean for `jm_core.py` and `test_lbl_p2.py` with `pyproject.toml`.
- New SHA-256: 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
- Repo-wide pytest collection encountered pre-existing live Docker scripts that exit without a running HTTP server; targeted core/integration suite is the 45-test gate above. Existing third-party pytest_freezegun deprecation warnings remain.

## LBL-P3 — Factor Computation Module
Status: COMPLETE
Date: 2026-11-18
Files created: labeling_factors.py, test_labeling_factors.py
Tests: 19 passed, 0 failed
mypy: clean on both files
Notes: Commands ran from parent claude_projects directory. `test_jm_core.py` is absent; existing core patterns came from `test_lbl_p2.py`. The requested high-easier item_difficulty direction differs from v6's high-harder prose, so this module follows the prompt with confidence-band entropy. `compute_factor_array` is a list subclass with named `.get()` lookup to satisfy frozen `score()` at runtime; the test uses an explicit static cast at that boundary. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-PH0 — Label Health Report (Phase 0)
Status: COMPLETE
Date: 2026-11-18
Files created: label_health/__init__.py, label_health/ingest.py, label_health/analyze.py, label_health/render.py, label_health/api.py, test_label_health.py
Tests: 19 passed, 0 failed; 83 passed in the combined Label Health, factor, LBL-P2, and service suite.
mypy: clean on all 5 requested files.
Notes: Mounted three anonymous `/v1/label-health` routes in `jm_service.py` and added deployment dependencies in `requirements.txt`. The HTML report has an inline risk filter. Fewer than 50 verified rows produce a warning per the requested acceptance test. Category conservation phase uses a per-category ConservationState over verified outcomes. WeasyPrint is installed but Windows lacks its native GObject library; PDF generation falls back to a simplified ReportLab PDF on that host. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-SWEEP-1 — Astra Cross-Module Consistency Sweep
Status: COMPLETE
Date: 2026-11-18
Files created: docs/astra_sweep_1_findings.md
Findings: 6 blockers, 5 warnings, 3 notes
Verdict: BLOCKED
Notes: Factor semantics, calibration history, report input/replay/output and service image packaging require review before P1. All 38 requested tests and five individual mypy checks passed. Core SHA-256 matched.

## LBL-P3-FIX — Factor Semantics Alignment
Status: COMPLETE
Date: 2026-11-18
Files modified: labeling_factors.py, test_labeling_factors.py
Sweep findings addressed: B1 (difficulty direction and schema formula), B2 (calibration history), W4 (default provenance)
Tests: 48 passed, 0 failed across factor and label health suites.
mypy: clean on both modified files.
Line-by-line analysis:
  model_confidence(): clips finite input to [0,1], high means confident, is_default=False; missing confidence must be supplied as a neutral input by a future caller.
  annotator_calibration(): matches category, averages the last 50 boolean annotator_correct values (legacy outcome_correct also accepted), defaults only when none match; caller must supply qualified records for one annotator and epoch in oldest-to-newest order, excluding imports and current item.
  item_difficulty(): validates every score including singleton, computes normalized three-band disagreement entropy, high means hard; zero or one score gives 0.5 with is_default=True. This requested band proxy differs from v6's class-probability entropy default and needs a registered contract before P1.
  schema_complexity(): validates class count and depth, applies min(1, 0.8*C/20 + 0.2*(depth-1)/2), ignores relation count, defaults to zero with is_default=True for empty schema.
  compute_factor_vector(): preserves canonical v6 factor order and seven display fields.
  compute_factor_array(): preserves that order as floats; FactorArray.get() still supplies named lookup to jm_core.score().
Notes: Core SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Missing model confidence and factor-contract version remain caller concerns. Other sweep blockers B3-B6 remain open. Existing pytest_freezegun deprecation warnings remain.

## LBL-PH0-FIX — Report Behavior Hardening
Status: COMPLETE
Date: 2026-11-18
Files modified: label_health/ingest.py, label_health/analyze.py, label_health/render.py, label_health/api.py, test_label_health.py, Dockerfile
Sweep findings addressed: B3 (CSV schema), B4 (action replay), B5 (zero-verified and cost), B6 (Dockerfile), W1 (readonly factor dictionaries), W5 (boundary tests)
Tests: 25 label health passed, 0 failed (19 original + 6 new); 29 factor tests passed.
mypy: clean on ingest.py, analyze.py, render.py, api.py and test_label_health.py individually.
Line-by-line analysis:
  ingest.py: v6 columns normalize to internal verified outcomes and actions, factor_ prefixes strip, legacy columns still work. Checks 0/199/200 rows, 1/2 factors, duplicate/empty headers, empty categories and 21 categories. Zero and 49 verified produce warnings; 50 has no threshold warning. One observed action retains its value and gains a second default action. Validation checks finite factors, ranges, action vocabulary and delimiter safety.
  analyze.py: 300-row path scores and learns verified rows with real factor dictionaries, then readonly batch-scores all rows. Zero-verified path returns null accuracy and cost with a clear message. Unknown actions raise ValueError for API translation to 422. Parsed timestamps sort stably; invalid timestamps preserve CSV order with a warning. Low-evidence cost is marked low confidence.
  render.py: null overall/category accuracy and null cost render as Insufficient data; empty-evidence message is escaped. Optional inversion and profile sections remain conditional. PDF generation retains the existing Windows fallback.
  api.py: checks CSV filename, empty/NUL bytes, size and duplicate/empty headers; parse/validation/replay ValueError paths return 422 with details. Size overflow returns 413. Analyze, HTML and PDF routes share validation.
  Dockerfile: copies label_health/ beside root Python files for service imports.
Notes: The explicit zero/49-verified acceptance behavior overrides v6's 50-verified rejection rule. The current JSON and cost payload retain legacy keys and fixed 10K/$25 assumptions, so the full v6 response and optional input contract still need work. The Dockerfile copy was inspected, not image-built. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-P1 — Postgres Persistence Layer
Status: COMPLETE
Date: 2026-11-18
Files created: db/__init__.py, db/models.py, db/connection.py, db/repository.py, db/migrate.py, test_db.py
Files updated: requirements.txt, Dockerfile
Tests: 15 passed, 0 failed. Existing factor and label health suites passed 54 tests.
mypy: clean on models.py, connection.py, repository.py, test_db.py individually.
Line-by-line analysis:
  models.py: domains, engines, label_log and annotators have the requested UUID keys, JSON state/config, domain foreign keys and timestamps. Engine and annotator pairs are unique. A partial unique index enforces the one project engine with null annotator ID. Label log has a unique domain/label pair and the domain/category/verified_at composite index.
  connection.py: environment DATABASE_URL selects PostgreSQL with asyncpg by default or SQLite with aiosqlite. AsyncSessionLocal yields request sessions, commits on normal completion and rolls back on error; tests exercise both paths.
  repository.py: domain and annotator CRUD and filtered label reads use AsyncSession. Annotator count uses a PostgreSQL/SQLite conflict update for concurrent inserts. Engine export_state/from_state round trip, version increments use conditional updates, and stale versions raise StaleDataError. get_label_log orders verified history by verification time, newest first. score_and_persist writes score and engine state in the caller transaction. verify_and_learn locks the label row, reconstructs the pending decision from durable factors because engine exports omit decision_log, learns, verifies and saves with an optimistic version check. Missing labels raise HTTP 404.
Notes: Chose idempotent SQLAlchemy metadata.create_all in db/migrate.py. The command `python jm-service/db/migrate.py` succeeded from claude_projects with an in-memory SQLite DATABASE_URL. PostgreSQL connectivity and concurrent writers were not exercised. The new repository is a foundation and is not yet wired into jm_service.py's existing SQLite routes. The requested four-table schema has no tenant key, so tenant-scoped isolation remains a required integration/migration decision before hosted multi-tenant use. Removed obsolete SQLAlchemy 1.4 stubs from the test environment to use SQLAlchemy 2.0 typing. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-P4 — Ingest + Verify Endpoints
Status: COMPLETE
Date: 2026-11-18
Files created: labeling_router.py, test_labeling_router.py
Files modified: jm_service.py (router import and mount only)
Tests: 18 passed, 0 failed. Existing factor, label health and database suites passed 69 tests.
mypy: clean on labeling_router.py and test_labeling_router.py with an uncached run after obsolete SQLAlchemy stubs were removed.
Line-by-line analysis:
  POST /v1/labels/ingest: Pydantic requires label/category and at least two finite [0,1] factors. A first request creates the domain with its factor order and approve/reject actions. Later requests reject changed factor names, add new categories through the domain and synchronize missing centroids in the selected engine. Repository score and state/log writes share the request session. Duplicate rows and stale engine versions yield 409; response includes decision ID, score and gate status.
  POST /v1/labels/verify: Locks the domain/label row, returns 404 if absent and 409 if previously verified. Loads the row's annotator engine, checks the action vocabulary, then calls repository.verify_and_learn in the request transaction. Category verified accuracy is computed with a SQL average. Response exposes action, supplied ground-truth correctness, engine update and accuracy.
  POST /v1/labels/ingest/batch: Pydantic caps the batch at 100. Each item is processed sequentially under one request session; an item error includes its zero-based index and rolls back the entire batch. The test verifies rollback of an auto-created domain and earlier score rows.
  GET /v1/labels/{domain_id}/pending: Requires a known domain, filters unverified rows by optional category and orders by increasing confidence with stable tie fields. Limit is constrained to 1–200. The route only reads state.
Notes: New routes use the LBL-P1 database dependency while existing generic routes keep their SQLite implementation. The supplied four-table schema has no tenant identity or access policy; these routes therefore require tenant isolation/authentication work before public hosted deployment. The MVP auto-created action vocabulary is approve/reject as requested and differs from v6's policy tier actions. Tests used SQLite and a mounted test app; PostgreSQL concurrency and production auth remain unverified. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-P6 — Policy Engine (Autonomy Tiers)
Status: COMPLETE
Date: 2026-11-18
Files created: policy_engine.py, test_policy_engine.py
Files modified: labeling_router.py (ingest tier fields and autonomy endpoint), jm_service.py (autonomy router mount), test_labeling_router.py (test app mount)
Tests: 20 policy passed, 0 failed; 87 existing factor, report, database and router tests passed. Combined policy/router run passed 38.
mypy: clean on policy_engine.py, test_policy_engine.py and modified labeling_router.py individually with uncached checks.
Line-by-line analysis:
  compute_tier(): failed gate returns RED first. Inclusive count boundaries are 30, 100 and 200; GREEN requires at least 80% and AUTONOMOUS at least 85%. A caller can supply the 90% preference floor. Inputs are checked for valid category, count and finite accuracy when gate passes.
  check_demotion(): failed gate returns RED. AUTONOMOUS falls to GREEN below 83%; GREEN falls to AMBER below 75%. A result below 75% cascades through GREEN to AMBER in one evaluation so an unsafe GREEN badge is not shown.
  action_policy(): RED maps to human_review, AMBER and GREEN to confirm, AUTONOMOUS to auto_accept.
  evaluate_domain(): loops over every configured category including zero-evidence categories, reads verified count, cumulative accuracy and last-50 rolling accuracy, applies category gate inputs and demotion, and returns per-category TierStatus.
  labeling_router.py changes: ingest scores and persists first, replays verified category outcomes into a separate ConservationState, then includes tier, action policy, next-tier status and the policy-only auto_accepted flag. Domain autonomy reads category evidence and returns the lowest tier as overall_tier. The test app and jm_service.py mount the second router for the domain URL.
Notes: Followed this prompt's RED at <30 and AMBER confirm policy, which differ from v6 §6's RED warmup <50 and AMBER human_review. The v6 document has no 83%/75% demotion rule; the explicit prompt supplies those thresholds. The 90% preference floor is available to policy callers but the router defaults to classification's 85% because domain kind is not stored. The auto_accepted flag is advisory and triggers no automatic action. Current persistence lacks verified provenance, schema epochs, project/annotator dual scopes and tenant access controls, so this endpoint does not yet enforce v6's production auto-accept eligibility. Tests used SQLite; PostgreSQL behavior remains unverified. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. Existing pytest_freezegun deprecation warnings remain.

## LBL-SWEEP-2 — Astra Full-Stack Consistency Sweep
Status: COMPLETE
Date: 2026-11-18
Files created: docs/astra_sweep_2_findings.md
Prior sweep B1-B6: All six targeted regressions fixed. Remaining v6 contract differences are recorded in the findings.
New findings: 6 blockers, 7 warnings, 3 notes, 4 design-update-needed
Verdict: BLOCKED
Tests: 107 passed in the requested five-file suite. Combined mypy clean on all 10 requested source files. Frozen engine SHA-256 matched.
Notes: PostgreSQL rejected the verify query; SQLite probes reproduced a missing dashboard category and cold-annotator autonomous eligibility. Tenant isolation, deployment readiness and HTML-to-PDF delivery also block release.

## LBL-SWEEP2-FIX — B2/B3/B4/W7 Targeted Fixes
Status: COMPLETE
Date: 2026-11-18
Files modified: labeling_router.py, db/repository.py, policy_engine.py, test_labeling_router.py, test_policy_engine.py
Sweep findings addressed: B2 (Postgres cast), B3 (category mutation), B4 (cold annotator), W7 (zero accuracy)
Tests: 112 passed, 0 failed (107 existing + 5 new). The 43 router/policy tests and 26 separate legacy service tests also passed.
mypy: clean on all three source files and both test files.

Line-by-line analysis:
- Accuracy computation — repository.verified_accuracy counts verified rows with observed outcomes and averages a numeric CASE over true/false, scoped by domain, category and optional annotator. verify reads the just-flushed result within the learning transaction. No SQL boolean-to-number cast remains. Label Health's pandas conversions operate entirely in memory. The mounted API on a temporary PostgreSQL 17 instance committed all three verifications and returned 2/3 in verify and autonomy.
- Config mutation — _prepare_engine refreshes under a PostgreSQL row lock on category growth, rechecks membership and capacity, then assigns a new categories list and config_json dictionary. SQLAlchemy persists the changed value with the score. save_engine_state separately writes the exported engine snapshot using its version predicate. No model migration was required. The restart test created a fresh app, DB engine and client over the same SQLite file and recovered both categories from scores by different annotators.
- Auto-accept gate — _ingest first checks the domain category's AUTONOMOUS tier and conservation gate. For an identified annotator it additionally requires at least 30 verified outcomes and at least 80% accuracy for that same domain and category. The regression checks cold start, 24/29, 24/30 and 24/31. Domain-only requests use the existing project policy. The flag is advisory.
- None accuracy handling — _category_stats returns None for both cumulative and rolling accuracy on zero observed outcomes. compute_tier returns RED for unknown accuracy; TierStatus and compute_tier_status preserve the optional float. evaluate_domain handles absent history and skips rolling demotion when no rolling measure exists. Ingest and autonomy serialize unknown accuracy as null; an observed zero remains numeric.

Notes: Frozen jm_core.py SHA-256 matched 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. The five-suite run emitted 224 existing pytest-freezegun deprecation warnings. The category fix applies on ingest; historical missing categories are restored on their next ingest. Tenant isolation, deployment readiness, report PDF delivery and broader production execution guards remain tracked in sweep 2.

## LBL-P9 — Dashboard API
Status: COMPLETE
Date: 2026-11-18
Files created: dashboard_router.py, test_dashboard.py
Files modified: jm_service.py (router import and mount only), docs/session_state.md
Tests: 16 dashboard tests passed, 0 failed. Six-suite regression passed 128/128, and the separate legacy service suite passed 26/26. All five mounted dashboard routes returned 200 with populated data on a temporary PostgreSQL 17 instance.
mypy: clean on dashboard_router.py and test_dashboard.py. An additional jm_service.py check reported six pre-existing typing errors in CORS setup, RegisterRequest and factor ranges; a shadow-file check with the dashboard import/mount removed reproduced the same six errors.
Line-by-line analysis:
- GET overview — Requires an existing domain (shared 404 check). Counts all scored labels, takes verified count and cumulative accuracy from the last curve point, evaluates configured categories with the shared category history helper and evaluate_domain, and reads inversion from the project engine. A missing project engine uses a fresh in-memory engine and writes no state. Empty domains return zero counts, null accuracy/inversion, empty curve and RED categories. Verified category parity after ingest/verify was checked against the existing autonomy endpoint.
- GET corrections — Groups verified rows by category and both action names. Known, differing actions count as overrides independently of label correctness. Rate is overrides/all verified, null at zero denominator. Each percentage is 100 × pattern count / overrides in that category. Counts sort descending with category and action names breaking ties; no overrides yields empty patterns and null top_pattern.
- GET annotators — Selects the top named annotators by total scored labels (default 50, maximum 100), then aggregates by category within that domain in the same SQL statement. Accuracy uses verified outcomes only. Extremes ignore unverified categories, coincide for a single observed category, and use category order for ties. With no verifications, accuracy and both extremes are null. Last activity is the latest score or verification timestamp.
- GET factors — Loads only the project-engine inversion. Aggregates verified score-time JSON factor values by exact configured key and correctness in SQL, using PostgreSQL json_each_text or SQLite json_each. Missing values do not enter the means. Missing outcome cohorts yield null mean and gap, observed zero gaps stay zero. Numeric gaps rank descending, with config order for ties and unknown gaps last.
- GET compounding — Domain and optional category filters precede cumulative SQL windows. Verification time, score time and row ID break ordering ties. Emits every Nth observation plus any trailing partial window, with zero-based point index and UTC timestamp. Current accuracy includes all observed outcomes. Baseline requires one complete window; improvement is 100 × (current - baseline) percentage points, null until that window exists. This measures observed verified outcomes over time.
Notes: No per-label, per-category or per-annotator query loops. A local file-backed SQLite sample with 100,000 verified rows, one category, two factors and 200 named annotators took 10.48 s for overview, 0.57 s for corrections, 0.42 s for annotators, 0.77 s for factors and 2.01 s for compounding in one run. Overview's shared category helper materializes and replays domain verification history, and the curve separately orders it; the default window returns 10,000 points. These are scoped history scans and one local timing sample. Under the service's default PostgreSQL isolation, separate overview queries can observe intervening commits. Hosted tenant access control remains a release dependency from sweep 2. Frozen jm_core.py SHA-256 matched 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.

## LBL-P15 — Deployment
Status: COMPLETE
Date: 2026-11-18
Files created: docker-entrypoint.sh, test_deployment.py, railway.toml
Files modified: Dockerfile, docker-compose.yml, jm_service.py (health endpoint, version and existing mypy issues), db/migrate.py (synchronous migration entry point), requirements.txt, test_jm_service.py (health fixture and contract)
Tests: 8 deployment passed, 0 failed. Requested seven-suite regression passed 136/136. Combined legacy plus seven-suite regression passed 162/162 after updating the health expectation and lifespan fixture.
mypy: clean on jm_service.py, db/migrate.py and test_deployment.py using jm-service/pyproject.toml.
Line-by-line analysis:
  Dockerfile: python:3.11-slim installs only the Cairo/Pango/GDK libraries used by WeasyPrint, installs pinned requirements, copies root Python modules and label_health/db packages, makes the entrypoint executable, exposes 8000 and checks the selected PORT. Image size and an actual container startup were not measured because Docker is unavailable locally.
  docker-compose.yml: postgres:17-alpine has pg_isready healthcheck and pgdata. jm-api waits for the healthy database, supplies an asyncpg DATABASE_URL, retains legacy SQLite on a separate jm-data volume and uses /v1/health for readiness.
  docker-entrypoint.sh: set -eu runs db.migrate.run_migration before an exec of Uvicorn, binding Railway's PORT with 8000 as the local default. The migration executed twice successfully against a temporary local PostgreSQL 17 instance.
  health endpoint: startup hashes frozen jm_core.py once and caches the comparison. Each request SELECTs 1 from the async labeling DB and the legacy SQLite DB and closes both connections. Healthy returns 200, a legacy DB error returns degraded 200, and a labeling DB or hash error returns unhealthy 503. Responses carry version 0.2.0 and individual checks.
Notes: Railway configuration uses the Dockerfile and /v1/health. Railway still requires a provisioned PostgreSQL service, DATABASE_URL and a persistent /data volume for legacy SQLite. The Docker image was not built locally. The old health test initially failed because it asserted the former status/version and skipped lifespan. Its fixture and assertion now cover the current contract. Existing pytest-freezegun deprecation warnings remain. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.

## LBL-P17 — Label Studio Integration
Status: COMPLETE
Date: 2026-11-18
Files created: label_studio.py, test_label_studio.py
Files modified: jm_service.py (router import and mount only)
Tests: 14 connector tests passed, 0 failed. Requested eight-suite regression passed 150/150; separate legacy service suite passed 26/26.
mypy: clean on label_studio.py, test_label_studio.py and the mounted jm_service.py.
Line-by-line analysis:
  POST /setup: resolves a project-specific stored or environment mapping, creates the JM domain with fixed factor order and approve/reject actions, and returns jm-v1. Repeated setup reuses the domain; a factor-schema mismatch returns 409.
  POST /predict: resolves data.* paths, uses 0.5 for missing mapped factors, rejects invalid inputs through IngestItem, and calls the shared _ingest repository-backed scoring path. A repeated unchanged task reuses its durable label_log score and evaluates current project tier without adding a decision; changed inputs return 409. The response has exactly results:[{result:[], score, model_version}]. Scores are multiplied by 0.49 until project AUTONOMOUS eligibility, so the Label Studio project must use an auto-accept threshold above 0.49. An empty result contains no pre-label class or span.
  POST /webhook: supports created and updated annotations, takes task identity and completed_by, extracts a Choices/Labels action, auto-ingests an unseen task and uses the same repository verify-and-learn transaction for first-time verified outcomes. A submission without configured ground truth remains pending and does not train. Identical verified retries return processed; changed ANNOTATION_UPDATED results replace the prior verification and replay the project engine from durable score rows. Unknown actions return ignored. Revisions are O(domain history) and need load testing at production volumes.
  GET /health: returns status UP and model_version jm-v1.
  POST /configure: validates factor mappings and field paths, persists a project mapping to LS_CONFIG_PATH using a same-directory temporary JSON file and atomic replace. The default path is /data/label_studio.json inside the container. A required X-LS-Token header is checked against LABEL_STUDIO_TOKEN on setup, predict, webhook and configure; missing configuration returns 503.
Notes: Factor mapping comes from per-project JSON or LS_FACTOR_MAP; LABEL_STUDIO_DOMAIN_ID supplies the default domain. The router is mounted at /v1/label-studio, so its URL can be used as the backend base. The supplied response format matches the requested results envelope. Official Label Studio material shows a separate LabelStudioMLBase/ModelResponse wrapper and webhook event contract; a live registration and label-config-specific prediction test remain unverified. The v6 design requires an authenticated signing relay with HMAC and durable event receipts for production webhooks. This implementation uses a shared custom header and row identity for retries, so that security/replay contract remains open. Annotation creation without gold evidence is retained as pending. The config JSON file assumes a persistent /data mount and a single writer; multiple workers require transactional storage. The project-level engine learns while annotator_id is retained for dashboard grouping, and annotator-specific engine learning remains unimplemented. Frozen jm_core.py SHA-256 remained 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.

## LBL-P16 — Verification Review UI
Status: COMPLETE
Date: 2026-11-18
Files created: frontend/ Vite + React + TypeScript project, six screen components, typed api.ts, CSV parser, domain context, shared components.
Files modified: jm_service.py (static mount), Dockerfile (multi-stage frontend build), .dockerignore.
Build: npm --prefix jm-service/frontend run build succeeded; dist/index.html exists. TypeScript compiled with zero errors. Dashboard chunk loads on demand.
Tests: deployment, legacy service, and Label Studio suites 48 passed, 0 failed. Existing pytest-freezegun deprecation warnings only. FastAPI static smoke test returned root 200 and OpenAPI 200; report PDF route remained registered. mypy jm_service.py clean. Frozen jm_core.py SHA-256 verified: 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
Line-by-line analysis:
  Upload: CSV drag/drop calls /label-health/analyze, shows validation errors and report summary, then parses and ingests rows in 100-item batches before navigating to the queue. A batch failure reports how many earlier rows were ingested; CSV verification outcomes stay in the ephemeral report and do not train the live domain.
  ScoredQueue: calls the actual pending API, sorts ascending confidence, filters by category, refreshes every 30 seconds, and shows unverified count. The backend returns at most 200 rows and exposes neither scored_at nor a verified-label audit mode, so the queue does not claim those fields.
  ReviewCard: shows factors with the v6 display anchors, recommendation, confidence, and category tier/gate. Approve and Override submit an explicit ground-truth correctness value to /labels/verify and advance to the next pending label. Keyboard A/O/E works outside form controls. Escalate leaves the label pending and explains that the default approve/reject backend action vocabulary cannot record escalation.
  Dashboard: overview cards, RED/AMBER/GREEN/AUTONOMOUS ladder, Recharts running accuracy, inversion alert, and top three correction patterns consume the corresponding API responses. Autonomous uses blue and GREEN remains confirmation.
  AnnotatorProfiles: shows the backend's annotator summary, supports sortable columns and an expandable row. The API lacks per-category accuracy values; expansion says so instead of inventing a breakdown.
  HealthReport: uploads CSV to /label-health/report, previews returned HTML in a sandboxed iframe, and downloads PDF from /label-health/report/pdf without requiring a domain.
  api.ts: typed requests target the mounted backend paths and use multipart field file for reports. Pending is typed as an array; error details include batch item indices. Neither pending factor defaults nor per-label conservation status are returned by the current API.
  Static serving: HashRouter avoids deep-link reload failures, and StaticFiles mounts at / after API routers when dist exists. Docker builds with Node 22 in a separate stage and copies only dist into the Python runtime image; .dockerignore excludes frontend/node_modules and local dist. Docker CLI was unavailable locally, so the image build itself was not run.
Notes: Launch gaps requiring backend contracts are a durable escalation action, cursor pagination/full queue counts, and per-annotator category breakdowns. The frontend uses the existing unauthenticated labeling endpoints; account and role controls are not present in this scope.

## LBL-SWEEP-3 — Final Release Sweep + Gap Analysis
Status: COMPLETE
Date: 2026-11-18
Files created: docs/astra_sweep_3_findings.md
Release verdict: BLOCKED
V6 gaps: 5 shipped, 18 partial, 11 not built (34 assessed capability groups)
Tests: 150 passed in the requested eight-suite regression, 0 failed; combined mypy clean on 13 files. Frontend production build passed and frozen engine hash matched.
Notes: Four hosted-release blockers remain in ownership, review identity/evidence, autonomous eligibility and connector replay. PostgreSQL 17 HTTP smoke and Chromium CSV-to-review/report download passed; container image and live Label Studio registration remain unverified.

## LBL-SWEEP3-FIX — Tenant Auth + Review Binding + Eligibility + Replay Scope
Status: COMPLETE
Date: 2026-11-18
Files created: auth.py.
Files modified: db/models.py, db/repository.py, db/migrate.py, labeling_router.py, dashboard_router.py, label_studio.py, jm_service.py, frontend/src/api.ts, frontend/src/App.tsx, frontend/src/screens/ScoredQueue.tsx, frontend/src/screens/ReviewCard.tsx, test_labeling_router.py, test_label_studio.py and existing test fixtures. policy_engine.py required no change.
Sweep findings addressed: B1 tenant isolation, B2 review binding, B3 autonomous eligibility, B4 connector replay scope.
Tests: 161 passed, 0 failed in the requested eight-suite regression (11 new tests); 322 existing pytest-freezegun warnings. Focused auth and Label Studio suites: 47 passed. TypeScript/Vite production build succeeded. Combined mypy clean on changed source and tests. Frozen jm_core.py SHA-256 verified: 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
Integration checks: PostgreSQL 17 migration ran twice; two tenant keys used the same public domain independently; cross-tenant pending and verify returned 404 while own ingest, verify and dashboard succeeded. Browser smoke confirmed switching domains reloads the review card and verifies only the newly loaded domain.
Line-by-line analysis:
  auth.py: random 32-byte keys returned once; only SHA-256 hashes stored; inactive, absent or invalid keys return 401; ADMIN_API_KEY and X-Admin-Key protect key issuance. Authenticated requests put tenant ID in the DB session.
  db/models.py and db/migrate.py: all four data tables have indexed tenant_id; api_keys stores hashes; annotation source and supersession columns support revisions. Migration adds columns and indexes to existing tables and creates missing tables idempotently. Existing rows receive the empty legacy tenant ID and need explicit reassignment if retained for hosted use.
  db/repository.py: domain, engine, log, annotator and verification queries check session tenant; new rows inherit it. Internal domain IDs hash tenant plus public domain, preserving isolation under the existing globally unique keys. Revision rows supersede old rows for metrics and train the selected annotator engine; prior centroid movement is retained as the allowed MVP tradeoff.
  labeling_router.py: all five labeling/autonomy endpoints require tenant; ingest and batch resolve scoped IDs; verify locks and checks domain, tenant and label; pending and accuracy queries filter tenant and exclude superseded rows. Wrong tenant returns 404.
  dashboard_router.py: every endpoint resolves a tenant-owned domain and scopes its queries; returned domain ID remains public. Superseded revisions are excluded from current counts, curves and corrections.
  label_studio.py: predict, webhook and configure require tenant key and LS token; setup and health remain without tenant key. Predict caps unqualified score below 0.49 after annotator count/accuracy, item confidence, project tier and conservation checks. Annotation identity includes project and annotation ID; updates follow the prior row and append a scoped successor. Multiple annotations on one task remain distinct.
  frontend/src/api.ts: authenticated calls add X-Api-Key from saved key or dev environment; free Label Health Report calls omit it. ReviewCard clears and reloads on domain switch, binds submission to the domain from which the row was loaded, and refuses a changed-domain submission.
Notes: Public Label Health Report and /v1/health stay anonymous. Setup can create a domain only with configured tenant context; authenticated predict creates it otherwise. API keys stored in browser localStorage follow the requested MVP flow and require stronger credential handling before a security-sensitive launch. The review card still lacks original source annotation content in the pending API; container image and live Label Studio registration were not verified. This entry records completion of the four requested fixes, not a fresh unconditional public-launch verdict.

## LBL-DEPLOY-1 — Railway Deployment Fixes + Smoke Test
Status: FAILED — the Docker Compose build/start gate could not be run because neither Docker nor Podman is installed on Windows or the available Ubuntu WSL distro. Code and non-container checks passed; deployment is not certified.
Date: 2026-11-21
Files created: test_smoke.py.
Files modified: db/connection.py, Dockerfile, docker-entrypoint.sh, docker-compose.yml.
Fixes: DATABASE_URL prefix normalization for postgresql:// and postgres://; Dockerfile HEALTHCHECK already used PORT, retained; added libgobject-2.0-0 and libffi-dev beside existing WeasyPrint libraries; migration retry up to 5 attempts with 2-second waits; development compose ADMIN_API_KEY.
Verification: mypy clean on db/connection.py and test_smoke.py; Python compile clean; 8/8 deployment tests passed; four URL forms resolved as expected; frontend npm production build passed and dist/index.html exists; compose YAML parsed with PostgreSQL +asyncpg URL, admin key, and both services; Railway healthcheckPath is /v1/health; entrypoint passed sh -n; frozen jm_core.py SHA-256 matched 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09. The standalone HTTP smoke passed 9/9 twice against a temporary local SQLite-backed uvicorn instance. Temporary databases and server were removed/stopped.
Line-by-line analysis:
  db/connection.py: postgresql:// and postgres:// replace only the leading scheme with postgresql+asyncpg://; existing postgresql+asyncpg:// and sqlite+aiosqlite:// stay unchanged. The normalized URL is passed to create_async_engine; session commit/rollback behavior is unchanged.
  Dockerfile: frontend/package.json and package-lock.json exist; npm ci/build succeeded outside Docker. Source and package COPY inputs exist. Runtime image copies the built dist, root Python files, label_health, db, and entrypoint; chmod makes the shell script executable. Healthcheck reads PORT with 8000 fallback. Cairo, Pango, GDK Pixbuf, GObject and libffi packages are listed. Actual apt install/image build remains unverified.
  docker-entrypoint.sh: set -eu, migration retries on failures 1-4 with 2-second sleeps and exits 1 after failure 5; success prints completion; exec uvicorn uses PORT or 8000. Shell syntax passed sh -n. Retry timing has not been exercised inside a container.
  docker-compose.yml: Postgres 17 healthcheck gates jm-api startup; DATABASE_URL uses postgresql+asyncpg; development-only ADMIN_API_KEY matches the smoke default; data volumes remain defined. Compose startup itself was unavailable.
  test_smoke.py: polls public health for up to 60 seconds, uploads a valid 300-row CSV to anonymous JSON/HTML/PDF report routes, creates a tenant key through the protected admin route, then ingests/verifies and reads dashboard/autonomy through that key. Prints PASS/FAIL for all nine checks; uses a fresh domain per run; returns exit 1 if health never becomes ready or any check fails. Two local HTTP runs passed 9/9.
Notes: Windows WeasyPrint native import failed during the local smoke, so the PDF endpoint succeeded through its ReportLab fallback. The new Linux image libraries are present in Dockerfile but untested in a built image. To close this gate, run the three commands in test_smoke.py's usage block on a machine with Docker Compose, inspect build/migration/health logs, and verify 9/9. Railway deployment and live Label Studio registration were not attempted.

## LBL-SWEEP-4 — Railway Deployment Readiness
Status: COMPLETE
Date: 2026-11-21
Files created: docs/astra_sweep_4_railway_findings.md
Verdict: BLOCKED
Tests: 161 passed across the eight requested suites. Frozen engine SHA-256 matched.
Notes: LBL-DEPLOY-1 remains FAILED. The release revision lacks required Docker inputs, durable legacy and connector storage needs a verified Railway volume, and anonymous report rendering needs capacity limits. A clean image build and managed PostgreSQL smoke test remain outstanding.

## LBL-DEPLOY-2 — Railway Release Readiness
Status: COMPLETE — code and clean-checkout inputs prepared; live Railway validation pending
Date: 2026-11-21
Files modified: Dockerfile, docker-compose.yml, db/connection.py, label_health/api.py, label_studio.py, test_deployment.py, docs/session_state.md
Files created: frontend/dist release assets tracked; .dockerignore updated
Blockers addressed: built frontend packaged from source-controlled dist; /data paths for legacy and connector state; two-worker anonymous report capacity with 60-second waits; asyncpg sslmode conversion and Railway SSL option
Tests: 161 existing passed, 5 new deployment checks passed; 0 failed. Frontend build passed.
mypy: clean on db/connection.py, label_health/api.py, label_studio.py and test_deployment.py.
Line-by-line analysis:
  Dockerfile: Python image copies all application packages and prebuilt frontend/dist, creates /data, and chmods entrypoint; .dockerignore excludes caches while retaining dist.
  db/connection.py: PostgreSQL schemes normalize to asyncpg, sqlite passes through, sslmode=require maps to connect_args ssl=True, Railway defaults SSL on; pool is 5+10. Unsupported sslmode raises an explicit error.
  label_health/api.py: 10 MiB byte check, two-worker executor and semaphore, 60-second acquisition and processing limits, 504 on timeout and 422 on CSV validation. A timed-out worker retains its slot until it finishes.
  label_studio.py: default config path is /data/ls_config.json; compose and image set the same path.
Notes: Docker/Podman and live Railway PostgreSQL remain unavailable locally. A Railway /data volume and managed database TLS handshake require staging verification. The smoke gate from LBL-DEPLOY-1 remains open. Existing report requests use 10 MiB application limit after multipart parsing; ingress controls may also be needed for hostile uploads.

## LBL-SWEEP-5 — Final Pre-Ship Cleanliness Sweep
Status: COMPLETE
Date: 2026-11-21
Files created: docs/astra_sweep_5_final_findings.md
Tests: 166 passed, 0 failed, 332 warnings in the requested workspace run. Requirements-only run: 151 passed, 15 skipped, 0 failed. LF export of the committed suites: 38 passed and 1 failed. Local HTTP smoke: 9/9.
mypy: clean, 0 errors across 15 files
Verdict: BLOCKED
Notes: Production Starlette advisories, lost Label Studio reviewer identity, and unreproducible release tests block launch. The frozen Git blob and working copy match the expected hash.

## LBL-DEPLOY-3 — Final Ship Fixes
Status: COMPLETE — code and reproducible release revision committed; container/PostgreSQL smoke remains a separate deployment gate
Date: 2026-11-21
Files modified: requirements.txt, label_studio.py, labeling_router.py, test_jm_service.py, test_label_studio.py, test_labeling_router.py, docs/session_state.md
Files added to release candidate: .gitattributes, pyproject.toml, test_labeling_factors.py, test_label_health.py, test_db.py, test_labeling_router.py, test_policy_engine.py, test_dashboard.py, test_label_studio.py, test_smoke.py
Findings addressed: patched FastAPI/Starlette pins; reviewer attribution on first verification and reviewer change; previously missing tests/config; current legacy health contract and lifespan fixture; LF checkout rules for frozen engine and shell entrypoint.
Tests: 195 passed, 0 failed, 1 Starlette TestClient deprecation warning in a requirements-only isolated environment. The same 195 tests passed from a fresh export of the staged Git tree. `pip check` passed.
mypy: clean on label_studio.py and labeling_router.py in the project environment (0 errors). The isolated environment without optional third-party typing packages reports missing-import errors in dependency modules; no source error was reported in the project environment.
Frozen SHA-256: 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09, including the exported candidate.
Missing files for commit: none of the requested release files; all are committed. Unrelated experiments remain untracked.
Line-by-line analysis:
  requirements.txt: FastAPI 0.163.1 and explicit Starlette 1.10.0 replace the vulnerable resolution; pytest-asyncio 0.23.8 is declared; matplotlib is omitted from hosted-service dependencies because only experiments import it. The isolated resolver installed the pins without conflict.
  label_studio.py: verified create binds a previously anonymous prediction to completed_by before learning; update includes reviewer identity in idempotency and appends a scoped revision when reviewer changes; both flows have database assertions. Events without ground truth remain pending.
  labeling_router.py: VerifyRequest accepts optional annotator_id, rejects blank values, binds the row before learning, and loads or creates that reviewer's engine; omitted annotator_id retains the scored scope.
  test_jm_service.py: health expects status/version/checks from the current endpoint and enters the app lifespan with an isolated SQLite labeling database.
Notes: The committed candidate was tested as an exported Git tree. Managed PostgreSQL, Docker image startup, and native Linux PDF rendering still require the separately documented deployment smoke gate.

## Phase 1+2 Prompt (DLJ-P1P2)
- Date: 2026-11-23
- Files created: legal_pages.py, billing.py, trial_guard.py, email_service.py, test_billing.py, test_legal_pages.py.
- Files modified: jm_service.py (CORS, Sentry, billing and legal routers), db/models.py (ApiKey tier, Lemon Squeezy fields, monthly and daily counters), db/migrate.py (idempotent api_keys column additions), requirements.txt (sentry-sdk), auth.py (request-scoped key hash), labeling_router.py and label_studio.py (transactional label quotas and warning headers), test_labeling_router.py (quota integration checks).
- CORS: restricted to dlj.dakshineshwari.net, rgi.dakshineshwari.net, and the two requested localhost origins.
- Legal pages: /terms, /privacy, /attribution.
- Billing: POST /v1/billing/webhook verifies Lemon Squeezy HMAC signatures and updates an API key already linked to the customer ID. The webhook has no rate limiting decorator.
- Trial: 14-day expiry and 50 labels per UTC day on PostgreSQL-backed labeling ingest.
- Volume: per-key monthly caps for paid tiers with an X-Volume-Warning header at 90%; quota reservation and scoring share one database transaction.
- Email: four Resend templates and an httpx sender with no new Resend dependency.
- Sentry: opt-in via SENTRY_DSN.
- Tests: 271 passed in the collectable suite; the literal repo-wide pytest command stops during collection because the three pre-existing live-Docker scripts exit without a running HTTP server. The final suite excluded those three scripts.
- mypy: clean on all 13 changed Python files.
- Final check: StaticFiles remains the last mount; /v1/billing/webhook has no rate limiter; frozen jm_core.py SHA-256 remains 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
- Deployment follow-up: link a Lemon Squeezy customer ID to an ApiKey during checkout before subscription_created arrives; configure products, webhook secret, and SENTRY_DSN/RESEND_API_KEY as needed. The legacy SQLite /v1/domains/{domain_id}/score route is outside the new PostgreSQL quota guard. The 30-day deletion and trial-email timing stated in the supplied copy do not yet have scheduled jobs.

## Paddle Swap (DLJ-PADDLE)
- Date: 2026-11-23
- Files modified: billing.py (Paddle webhook rewrite), test_billing.py, db/models.py, db/migrate.py, legal_pages.py, docs/session_state.md.
- Change: active billing integration and legal copy switched from the prior provider to Paddle, the merchant of record.
- Paddle-Signature verification: `ts=<ts>;h1=HMAC-SHA256(secret, ts:raw_body)` when PADDLE_WEBHOOK_SECRET is configured; unsigned requests are accepted when it is unset for the requested sandbox flow.
- Event format: `event_type` at the top level; subscription.created, subscription.updated, and subscription.canceled use dotted names.
- Product name: `data.items[0].product.name`.
- Env vars: PADDLE_API_KEY is the API credential for future outbound Paddle calls; this webhook uses optional PADDLE_WEBHOOK_SECRET.
- DB columns: paddle_customer_id and paddle_subscription_id. PostgreSQL migration renames historical columns when present; SQLite adds the new columns.
- No old-provider references remain in Python source or tests; historical session-state entries above retain their original wording.
- Tests: 272 passed in the collectable suite (excluding the three pre-existing live-Docker scripts); the requested targeted runs passed 16 billing tests and 49 legal/deployment/service tests.
- mypy: clean on billing.py, db/models.py, db/migrate.py, legal_pages.py, and test_billing.py.
- Final check: webhook has no rate limiting decorator; existing customer-to-ApiKey linkage is still required before subscription.created can upgrade an account. Configure PADDLE_WEBHOOK_SECRET before accepting production traffic.

## Checkout Flow + Scheduler (DLJ-CHECKOUT)
- Date: 2026-11-23
- Files created: scheduler.py, test_scheduler.py.
- Files modified: billing.py (authenticated checkout transaction and custom_data fallback), db/models.py (contact email and once-only trial notice timestamps), db/migrate.py (new columns), jm_service.py (scheduler lifecycle), test_billing.py, docs/session_state.md.
- Checkout flow: GET /v1/billing/checkout-url requires an API key, creates a Paddle transaction with `custom_data.tenant_id`, and returns Paddle's `checkout.url`. Paddle does not document `custom_data` as a hosted checkout URL query parameter, so the service uses the transactions API.
- Webhook: subscription.created resolves a previously linked customer or falls back to `custom_data.tenant_id`, links `paddle_customer_id`, and saves `data.customer.email` when supplied. An active subscription.updated event clears cancellation. No rate limiting decorator is on the webhook.
- Scheduler: an asyncio task starts with FastAPI lifespan, runs hourly, and is cancelled on shutdown. Trial notices are delivered through Resend once when `contact_email` is present; otherwise the missing address is logged. Cancellation cleanup deletes LabelLog, Engine, Annotator, and Domain rows after 30 days and deactivates the key, while skipping tenants with another active key.
- Env vars: PADDLE_API_KEY, PADDLE_PRICE_MAP (`starter=pri_xxx,...`), PADDLE_SANDBOX (defaults to true), optional PADDLE_WEBHOOK_SECRET for sandbox signature verification, and RESEND_API_KEY for email. Paddle must have a configured default payment link for the transaction response to include a checkout URL.
- Tests: 277 passed in the collectable suite. Literal repo-wide pytest still exits during collection from three pre-existing live-Docker scripts without a running HTTP server; those scripts were excluded for the passing run.
- mypy: clean on billing.py, scheduler.py, db/models.py, db/migrate.py, jm_service.py, test_billing.py, and test_scheduler.py.
- Final check: StaticFiles remains the last mount; checkout-url has require_tenant; webhook has no rate limiting decorator; frozen jm_core.py SHA-256 remains 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.

## DLJ Annotation UI Design v2 (DLJ-DESIGN-V2)
- Date: 2026-11-24
- Files created: docs/design/dlj_annotation_ui_design_v2.md. The v1 input was located in the sibling copilot-sdk repository.
- Files unchanged: all source code (design-only prompt).
- Current test count: 277 collected with the three standalone live-Docker clients excluded. Unfiltered collection exits after a partial 72. Collection and mypy were run; no new test-pass claim.
- Current-state corrections: confirmed six screens/239 LOC and hash routes; distinguished a disabled status filter, informational escalation, first-200 review lookup, limited profile expansion, local key storage, report PDF and engine-state export.
- Added verified component inventory, package ranges, all 32 application operations with auth/rates, and complete column lists for the five ORM models. Distinguished legacy SQLite registration/domains from authenticated DLJ labeling and billing.
- Qualified competitive comparisons using primary sources and separated cumulative verified correctness from measured model improvement.
- Filled design gaps: anonymous vs persistent CSV parsing, text storage/detail/retrieval, tenant scope, additive migrations and rollback, versioned edits, Unicode NER offsets and React peer compatibility, 500-row synthetic report and quota-aware 12-label sample, settings/key usage, public domain-name recovery and Paddle confirmation.
- Updated four phases, scope boundaries, effort and test budgets. Added §10 with executable Phase A specs, Phase B outlines, dependencies, risk mitigations, integration checks and verification commands.
- Execution plan: 4 Phase A prompts (DLJ-A1 through DLJ-A4); sequential pytest targets 282, 290, 296 and 300. Mandatory check matched documented operations to OpenAPI plus hidden legal routes and every model column to SQLAlchemy metadata. Mypy clean on jm_service.py and db/models.py.
- Next: DLJ-A1 (Sample Data + Demo Mode).

## DLJ-A1 — Sample Data + Demo Mode
- Date: 2026-11-24
- Files created: scripts/generate_sample.py, frontend/public/demo/sample_data.json, test_sample.py
- Files modified: Upload.tsx, labeling_router.py, api.ts
- Tests: 282 passed
- mypy: clean
- Build: passed

## DLJ-A2 — Source Text Round Trip
- Date: 2026-11-24
- Schema/API: Added nullable `label_log.text` with repeatable SQLite/PostgreSQL migration; optional 32 KiB UTF-8 text in single and batch ingest; authenticated `GET /v1/labels/{domain_id}/{label_id}` detail; pending rows expose only an optional 80-code-point `text_preview`. Empty text maps to NULL; nonempty whitespace and Unicode are preserved.
- Read/rollback behavior: Old rows display “Source text unavailable.” Detail reads are tenant and domain scoped, including verified labels and IDs outside the first pending page. Batch errors roll back scoring and quota. Sample reseed fills missing text only from the server-owned fixture without charging again. Existing data and the additive column remain on app rollback.
- Tests: 8 new cases; 86 targeted passed, 290 collectable passed with the three live Docker scripts and standalone `test_ops_e2e.py` excluded; 29 legacy service integration tests passed. The unmodified §10 full-suite command yielded 290 passes plus 8 setup errors in `test_ops_e2e.py` because its live-service fixtures are not provided.
- mypy: clean on changed Python modules/tests and shared gate modules.
- Build: passed; `frontend/dist` refreshed and sample fixture present.
- Browser: built UI on isolated local SQLite with a local test key. Prefixed and unprefixed 200-row CSVs both produced reports with 2 factors and scored 200 labels. Quoted multiline Unicode and literal `<b>` markup survived upload, storage, and detail rendering as text. Verified label reopened read-only; legacy row showed the missing-text state.

## DLJ-SIGNUP — Self-Serve Registration
- Date: 2026-11-24
- Files created: test_signup.py, frontend/src/screens/Signup.tsx, frontend/src/components/SignupBanner.tsx.
- Files modified: auth.py (public register endpoint), db/models.py (case-insensitive unique email index), db/migrate.py (repeatable index migration), email_service.py (API key delivery wrapper), jm_service.py (router mount), App.tsx (route and sidebar), api.ts (register call), Upload.tsx, ScoredQueue.tsx, Dashboard.tsx, index.css.
- Endpoint: `POST /v1/auth/register` is public and limited to 5 requests/minute per IP. It validates and normalizes email, rejects duplicates, creates a trial tenant/key, returns the plaintext key in the registration response only, and invokes email delivery. Actual delivery requires `RESEND_API_KEY`; failure is logged while the browser copy remains available.
- Tests: 6 new signup cases; 296 passed in the collectable suite. The requested full-suite command yielded 296 passes plus 8 setup errors in the pre-existing `test_ops_e2e.py` because its live-service fixtures are unavailable. `test_jm_service.py`: 29 passed.
- mypy: clean on auth.py, db/models.py, db/migrate.py, jm_service.py, and email_service.py.
- Build: passed.
- Browser: computer-use browser host was unavailable and existing browser windows were minimized, so direct clipboard, localStorage, and incognito checks could not run. Local HTTP smoke test served the signup page (200), registered `test@example.com` (201, 64-character key, trial), and scored a label using that key (200). The isolated local service had no Resend key, so email delivery was not live-tested.
- Final review: read every function in auth.py and the complete Signup screen; confirmed duplicate rejection, one-time response contract, delivery invocation, and StaticFiles as the final mount.

## DLJ-A3 — Queue Pagination and Page Export
- Date: 2026-11-24
- Files created: test_queue.py (exactly 6 new cases).
- Files modified: labeling_router.py, jm_service.py, frontend/src/api.ts, frontend/src/screens/ScoredQueue.tsx, frontend/src/index.css.
- API defaults: `GET /v1/labels/{domain_id}/pending` remains a bare array with limit=50 (1–200), offset=0, and confidence/scored_at/ID ascending order. Optional allowlisted `sort_by` and asc/desc order apply before pagination; null values sort last and scored_at/unique ID break ties. `X-Total-Count` counts the same tenant/category/pending filter and is exposed by CORS.
- Queue: 50/100/200 rows, server sorting, previous/next, count from header, stable refresh, reset on domain/filter/sort changes, last-page clamp, categories from autonomy, optional 80-code-point source preview, and later-page detail links. Export this page downloads only visible pending rows in displayed order; Papa.unparse quotes CSV and escapes spreadsheet formula prefixes.
- Tests: 40 targeted passed; 302 collectable passed with the three live Docker scripts and `test_ops_e2e.py` excluded. The unmodified §10 full-suite command yielded 302 passes plus 8 pre-existing `test_ops_e2e.py` setup errors (missing live-service fixtures). `test_jm_service.py`: 29 passed. Collection baseline was 304 before A3 and 310 after it; the extra 6 relative to the design's sequential target are DLJ-SIGNUP.
- mypy: clean on labeling_router.py, test_queue.py, jm_service.py, and db/models.py.
- Build: passed; served dist refreshed.
- Browser: Computer Use stopped because URL policy enforcement is unavailable for the current Windows browser, so interactive sorting, refresh, page export, and detail navigation were not observed. API tests exercised 205–213 pending rows, both sort directions, category/tenant scope, last page, tie stability, and later-page 80-code-point preview/detail. A direct Papa Parse check preserved page order, commas/quotes/newlines and escaped a formula-looking ID.

## DLJ-A4 — Settings and Account Summary
- Date: 2026-11-24
- Account API: Authenticated `GET /v1/account` returns the active key's tenant ID/name, tier, active/created/trial/cancel status, UTC day/month period keys, usage counters, and applicable caps. It excludes plaintext keys, hashes, contact email, and billing credentials. `GET /v1/account/domains` returns only tenant-owned public domain IDs; `POST /v1/account/domains/resolve` recovers a legacy public name for the owning tenant.
- Public-ID migration: Added nullable `domains.public_domain_id` with repeatable SQLite/PostgreSQL migration. New ingests and Label Studio carry the public name; repeat ingest backfills an older domain. Legacy hashed domains remain unresolved until the owner supplies the name.
- Billing and UI: Settings handles missing/replaced/cleared local keys, trial and cancelled states, usage, domain selection, Paddle checkout errors, and pending return with backend refresh. Upgrade links point to `/#/settings`. Existing Paddle transaction creation and webhook signature policy remain in `billing.py`; legal pages describe local keys, counters, and stored text.
- Tests: Exactly 4 new `test_account.py` cases. Billing/deployment/service gate: 63 passed. Collectable suite: 306 passed with the three live Docker scripts and `test_ops_e2e.py` excluded. The unmodified shared command yielded 306 passes plus 8 pre-existing `test_ops_e2e.py` setup errors from missing live-service fixtures.
- mypy: clean on 10 changed/related Python source files.
- Build: passed; refreshed `frontend/dist`.
- Browser: Chrome tested the built UI against an isolated local SQLite service and a mocked Paddle checkout. Direct Settings deep link, domain change, local key replace/clear, missing checkout configuration error, checkout return pending state, and refreshed Starter tier after a signed local webhook all worked. No Paddle sandbox or live checkout was exercised.

## DLJ-B1 — Text Tasks and Category Revisions
- Date: 2026-11-24
- Endpoints: `POST /v1/labels/{domain_id}/tasks` creates bounded source-text work items, unscored until classified or scored through ordinary quota-aware ingest when a category is supplied. `POST /v1/labels/{domain_id}/items/{label_id}/relabel` requires the current revision ID as token and appends an audited category revision without scoring or training an already scored item.
- Schema/read behavior: Nullable unscored label fields and revision actor/time/prior/token fields have repeatable SQLite/PostgreSQL migration. Pending and dashboard counts exclude unscored tasks. Detail follows the latest revision and exposes its revision ID. Upload creates text tasks; ReviewCard offers category selection.
- Tests: Exactly 8 new `test_tasks.py` cases. Target: 42 passed on SQLite and 42 on PostgreSQL. Collectable suite: 314 passed on each with standalone live-service scripts excluded. The unmodified shared pytest command yielded 314 passes and 8 pre-existing `test_ops_e2e.py` setup errors from absent live-service fixtures.
- mypy/build: clean; frontend build passed.
- Browser: Native Computer Use stopped because URL policy enforcement was unavailable for the Windows browser. No B1 interactive review result was observed.

## DLJ-B2 — Structured NER Content and Read-Only Viewer
- Date: 2026-11-24
- Schema/API: Added one-to-one `label_content` with UUID parent FK, unique `label_log_id`, ON DELETE CASCADE, content type, spans/tags JSON arrays, and nullable HTTPS image URL (2,048-character limit). Migration creates the table repeatably; SQLite connections enable foreign-key enforcement. Authenticated `POST /v1/labels/{domain_id}/items/{label_id}/content` attaches content to the tenant-scoped current revision. Authenticated detail at `/items/{label_id}` and the legacy detail route return content only when present; pending rows remain bounded. Relabel copies content to the successor revision.
- Validation: NER spans use half-open Unicode code-point offsets into exact stored text; reject missing text, empty/out-of-range/overlapping spans, mismatched substrings, and labels outside domain categories. Multilabel tags use the same category vocabulary. Image references require bounded HTTPS URLs and reject data/base64 URLs. Duplicate content for a revision returns 409.
- Viewer: NEW `NERViewer` renders escaped React text with focusable highlighted entities, inline labels, a color legend, and a textual entity list. `Array.from(text)` handles emoji, combining characters, and repeated substrings; ReviewCard shows it below TextViewer when NER spans exist.
- Tests: Exactly 8 new `test_content.py` cases. Target: 50 passed on SQLite and 50 on PostgreSQL. Collectable suite: 322 passed on each database with the standalone live operations script excluded. The unmodified shared command yielded 322 passes plus 8 pre-existing `test_ops_e2e.py` setup errors because its live-service fixtures are unavailable. Cascade deletion was exercised on both databases.
- mypy: clean on changed Python modules/tests and shared service module. Build: passed; built assets refreshed.
- Browser: Headless Chrome against the built UI and isolated local SQLite service showed two keyboard-focusable highlights at the expected code-point offsets, the entity legend, and literal HTML displayed as text. The local service was stopped after the check.

## DLJ-B3 — Bulk Review
- Date: 2026-11-24
- Files created: `test_bulk_review.py` (exactly 8 cases).
- Files modified: `labeling_router.py` (bulk-verify endpoint), `db/models.py`, `db/repository.py`, `db/migrate.py` (optional verification reason), `trial_guard.py` (structured cap scope), `frontend/src/screens/ScoredQueue.tsx` (page checkboxes, keyboard selection and fixed action bar), `frontend/src/api.ts` (bulkVerify), `frontend/src/index.css`.
- Endpoint: Authenticated `POST /v1/labels/{domain_id}/bulk-verify`, rate limited 10/minute, 1–200 unique IDs. It validates the whole tenant/domain set before changes, skips already verified rows, reserves one quota unit per processed row, and returns processed/skipped counts plus per-label errors. Approve confirms the recommendation; reject overrides it. Each processed row calls the existing `verify` → `verify_and_learn` path, preserving conservation and engine updates. Trial daily and paid monthly caps return partial results with explicit skip reasons; optional reason is stored on the verified log.
- Queue: Selection is page scoped and clears on domain/filter/sort/page changes. Ctrl+A selects the visible page, Escape clears it, and completion shows counts, refreshes the queue, and hides the action bar when empty. The UI states that bulk review consumes a plan quota unit per processed label.
- Tests: 8 passed on SQLite / 8 passed on PostgreSQL. Full collectable suite: 330 passed on SQLite / 330 passed with PostgreSQL configured, excluding the standalone live scripts. Legacy migration and labeling regression gate: 50 passed. Collection with only the three Docker scripts excluded remains 338, including eight standalone `test_ops_e2e.py` functions that require live-service fixtures.
- mypy: clean on six changed/related Python files. Build: passed.
- Browser: Headless Chrome against the built UI and isolated local SQLite service with 51 pending labels confirmed page selection reset, Ctrl+A, Escape, two-label bulk approval, updated 49-row count, toast, and action-bar dismissal. The local service and temporary browser script were stopped/removed.

## DLJ-POST-T2-REVIEW — Post-Track 2 Design Review
- Date: 2026-11-24
- Files created: docs/design/dlj_post_track2_design_v2.md
- Review: 13 checklist items evaluated against live codebase (10 listed in v1 §13 plus 3 from the review brief)
- Findings: 1 PASS / 7 ISSUE / 5 BLOCKER
- Execution plan: 12 Codex prompts, 30 days estimated

## DLJ-POST-T2-DESIGN — Execution specification
- Updated docs/design/dlj_post_track2_design_v2.md in place with the five feature contracts, dual-DB migration, API payloads, worker behavior and release gates.
- Execution plan: 12 ordered Codex prompts, 30 engineering days. Track 2 work still in progress is estimated separately.
- B3 compatibility check: test_bulk_review.py passed 8/8 on SQLite and 8/8 on PostgreSQL.

## DLJ-B4 — Scoped Search
- Date: 2026-11-24
- Files created: `test_search.py` (exactly 6 cases).
- Files modified: `labeling_router.py` (search on pending), `frontend/src/screens/ScoredQueue.tsx` (search input and 300 ms debounce), `frontend/src/api.ts` (search option), `frontend/src/index.css` (search styling).
- Parameter: `GET /v1/labels/{domain_id}/pending?search=<query>` accepts at most 200 characters. A nonblank query matches case-insensitive literal substrings in `label_id`, `annotator_id`, `category`, or stored `text`. Search uses the existing tenant/domain/category/pending filters before count, sorting, and pagination. Empty or whitespace-only search leaves the queue unfiltered. `X-Total-Count` reports the filtered count; the response remains a bare array.
- Queue: Full-width search input below filters, 300 ms debounce, clear control, filtered result count, first-page reset, and preserved sort order. Selection resets when the applied search changes.
- Tests: 6 passed (SQLite) / 6 passed (PostgreSQL). Full collectable suite: 336 passed (SQLite) / 336 passed (PostgreSQL), with the three live Docker scripts and standalone live operations script excluded.
- mypy: clean on `labeling_router.py` and `db/repository.py`.
- Build: passed (`tsc` and Vite).
- Final review: read every function in `labeling_router.py` and `ScoredQueue.tsx`; confirmed filtered count and rows share the same predicates, sort applies before pagination, and empty search matches the unfiltered queue.

## DLJ-PW-EXPAND — Playwright Test Expansion
- Date: 2026-11-24
- Files created/modified: e2e/track2.spec.ts
- Tests added: 21 Playwright tests covering signup, sample data, settings, enhanced queue, review card, and signup banner.
- Previous PW count: 31 observed (7 smoke + 24 screens; the requested 32 baseline was off by one).
- New PW count: 52 in 3 files.
- Build: passed.
- Test list: verified (--list). No browser run or server start, as requested.
- TypeScript: e2e/tsconfig.json does not exist; direct tsc check of track2.spec.ts passed.

## DLJ-B5 — Inline NER Span Editor
- Date: 2026-11-24
- Files created: `frontend/src/components/NEREditor.tsx`, `test_span_edit.py`, `e2e/ner_editor.spec.ts`.
- Files modified: `labeling_router.py`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/components/NERViewer.tsx`, `frontend/src/api.ts`, `frontend/src/index.css`.
- API: `POST /v1/labels/{domain_id}/items/{label_id}/relabel` accepts optional `spans` alongside the existing category and current revision token. It validates at most 100 nonoverlapping, bounded Unicode code-point spans against stored text, derives omitted span text, and rejects mismatches. A span-only change creates an audited successor revision; stale tokens return 409. Relabel resolves the current revision from the original label ID for repeat edits.
- Storage: The existing one-to-one `label_content` table owns NER spans and content type. Edited spans are written as `text_ner` on the successor revision; `label_log` remains the source-text and revision table. No redundant `label_log.spans` column was added.
- UI: ReviewCard provides drag selection, inline entity-type choice, highlight click to change or delete, Escape to close, unsaved indicator, and Save Spans. The read-only NER viewer remains for verified labels. Both viewers use the same stable entity colors. Empty domain categories show a custom type input in the editor.
- Tests: 9 new Python cases; 345 passed on SQLite and 345 passed on PostgreSQL in the full collectable suite (live Docker scripts and standalone live operations script excluded). Two new Playwright tests passed against the Vite UI with mocked API responses, covering Unicode selection/save, type change, and deletion.
- mypy: clean on `labeling_router.py`, `db/models.py`, and `db/repository.py`. Build: passed (`tsc` and Vite).

## DLJ-C2+C3 — TagSelector + Image Viewer
- Date: 2026-11-24
- Files created: `test_tags_image.py`, `frontend/src/components/TagSelector.tsx`, `frontend/src/components/ImageViewer.tsx`, `e2e/tags_image.spec.ts`.
- Files modified: `labeling_router.py` (optional tags in relabel), `frontend/src/screens/ReviewCard.tsx` (tag editor and image viewer), `frontend/src/api.ts` (tag request type), `frontend/src/index.css` (component styling).
- Features: Multi-label chips with autocomplete, custom tags, case-insensitive duplicate guard, keyboard removal and dismissal, unsaved state, and Save Tags. Image classification shows a bounded, contained image, category badge, loading state, and broken-image message. The existing CategorySelector remains available for image category relabeling.
- Storage/API: The existing `label_content.tags_json`, `content_type`, and `image_url` fields back these views; no duplicate `label_log` columns were added. Tag edits use the existing category and revision token, create an audited successor revision, trim and deduplicate tags case-insensitively, and enforce 20 tags and 50 characters each. Plain text content upgrades to `text_multilabel` on tag save.
- Tests: 6 passed (SQLite) / 6 passed (PostgreSQL). Full collectable suite: 351 passed (SQLite), excluding the live Docker and operations scripts. Two Playwright browser checks passed for tag autocomplete/edit/save and image error handling.
- mypy: clean on `labeling_router.py`.
- Build: passed (`tsc` and Vite).

## DLJ-D1+D2 — Polish (Shortcuts, Dark Mode, Guidelines, IAA)
- Date: 2026-11-24
- Files created: test_polish.py, e2e/polish.spec.ts, frontend/src/components/KeyboardShortcuts.tsx, frontend/src/components/ShortcutsModal.tsx, frontend/src/components/GuidelinesPanel.tsx, frontend/src/components/IAAPanel.tsx
- Files modified: frontend/src/App.tsx (shortcuts mount and theme toggle), frontend/src/screens/ReviewCard.tsx (guidelines toggle and text-entry shortcut guard), frontend/src/screens/ScoredQueue.tsx (j/k/Enter focus), frontend/src/screens/Dashboard.tsx (IAA card), frontend/src/screens/Settings.tsx (guidelines editor), frontend/src/api.ts, frontend/src/index.css (dark mode), labeling_router.py (guidelines endpoints), dashboard_router.py (IAA endpoint), db/models.py (guidelines column), db/migrate.py
- Features: Global keyboard shortcuts and ? help modal, dark mode toggle with system preference, annotation guidelines editable in Settings and viewable on Review, IAA using current verified annotations paired by source_task_id with Cohen's kappa.
- Tests: 8 passed (SQLite) / 8 passed (PostgreSQL); full collectable suite 359 passed; 2 Playwright polish checks passed.
- mypy: clean on labeling_router.py, dashboard_router.py, db/models.py, db/migrate.py.
- Build: passed.
- Access limitation: current auth has no admin role; any authenticated key belonging to the domain's tenant can edit guidelines.

## DLJ-FIX-BE1 — Billing/Webhook Hardening

- Date: 2026-11-24
- Findings fixed: P1.1, P1.5, P1.6, P1.10, P1.15
- Files modified: `billing.py`, `db/models.py`, `db/migrate.py`, `test_billing.py`, `test_account.py`
- Files created: `test_billing_fixes.py`
- Webhook: A missing secret returns 503 unless `PADDLE_SANDBOX=true`. Checkout includes the purchasing key UUID. Activation resolves the linked customer first, then the explicit key. Legacy tenant-only transactions use the oldest eligible key with UUID as a tie-breaker. Customer IDs have a partial unique index.
- Entitlements: Subscription mutations require an event ID and timezone-aware occurrence time. Each accepted event gets a durable receipt in the entitlement transaction. Replays return 409, and stale events preserve newer state. An email uniqueness conflict preserves both the tier change and the original contact. Unrecognized products return 400.
- Tests: 10 passed (SQLite) / 10 passed (PostgreSQL). Full suite: 388 passed, 1 skipped. The PostgreSQL-only migration test also passed on PostgreSQL. Concurrent duplicate deliveries yielded one 200 and one 409 on each database.
- mypy: clean on `billing.py`, `trial_guard.py`, and `db/models.py`.

## DLJ-FIX-FE — Frontend State Race + Domain-Switch Fixes

- Date: 2026-11-24
- Findings fixed: Sweep 2 P1.1-P1.7 + P2.19 + P2.20
- Files modified: `frontend/src/screens/ReviewCard.tsx`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/Settings.tsx`, `frontend/src/components/CategorySelector.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx` (and generated `frontend/dist/index.html`).
- Files created: `e2e/fix_state.spec.ts`
- Frontend build: passed
- PW test list: verified (62 tests total, including the four new state tests); new spec type check passed. `e2e/tsconfig.json` does not exist, so the requested project check reported that missing file.

## DLJ-FIX-BE2 — Migration Safety
- Date: 2026-11-24
- Findings fixed: P1.3, P1.4
- Files modified: db/migrate.py
- Files created: test_migration_fixes.py
- PostgreSQL timestamp additions use TIMESTAMPTZ. Previously migrated timezone-naive values are interpreted as UTC during repair. SQLite additions use TIMESTAMP.
- The SQLite label_log rebuild stages and restores label_content in a savepoint with foreign keys enforced. A count mismatch rolls back the rebuild. Tests covered NER spans, tags, image URLs, rollback, cascade deletion, repeat upgrades and fresh-schema column types.
- Tests: 5 passed (SQLite) / 5 passed (PostgreSQL). Each run skipped the other dialect’s timestamp test. All six regression cases passed across the two runs. Full suite with the four requested exclusions: 388 passed, 1 skipped.
- mypy: clean on db/migrate.py, db/models.py and db/connection.py.

## DLJ-FIX-BE3 — Relabel Safety + Input Validation

- Date: 2026-11-24
- Findings fixed: P1.2, P1.8, P1.9, P1.16, P1.17, P1.19, P2.6
- Files modified: `labeling_router.py`, `label_studio.py`, `jm_service.py`, `test_tasks.py` (updated schema fixture for the new relabel rule)
- Files created: `test_validation_fixes.py`
- Tests: 14 passed (SQLite) / 14 passed (PostgreSQL); full suite 388 passed, 1 skipped
- mypy: clean

## DLJ-RESWEEP-BE — Backend Re-Sweep (Post-Fix)

- Date: 2026-11-24
- Dimensions: 8 (fix verification, interaction, auth, data integrity, validation, errors, test gaps, new issues)
- Files analyzed: 80, including 46 application route registrations
- Findings: P1=23, P2=24, P3=3
- Fix verification: 12 CLOSED, 7 PARTIAL, 7 OPEN, 0 REGRESSED across the 26 published P1 findings
- Verification: full default pytest suite 388 passed, 1 skipped. Six relevant test modules in forward and reverse order each returned 59 passed, 1 skipped on both database configurations. Playwright listed 62 tests across 7 files. Live operations and provider calls were not exercised.
- Report: [docs/quality/dlj_resweep_backend.md](quality/dlj_resweep_backend.md)

## DLJ-RESWEEP-FE — Frontend Re-Sweep (Post-Fix)
- Date: 2026-11-24
- Dimensions: 8 (fix verification, state mgmt, API contracts, Track 2 features, accessibility, dark mode, build/deploy, E2E coverage)
- Components analyzed: 27 (App, 8 screens, 18 child components)
- Findings: P1=7, P2=26, P3=8
- Fix verification: 8 CLOSED, 1 PARTIAL, 0 OPEN, 0 REGRESSED using the IDs in the re-sweep brief. Using the original report IDs: 5 CLOSED, 1 PARTIAL, 3 OPEN, 0 REGRESSED.
- Track 2 features: 1 COMPLETE, 10 PARTIAL, 0 BROKEN (11 feature groups defined in the report)
- Verification: frontend type-check and production build passed; Playwright 59 passed / 3 failed, including 4/4 state-fix tests passed.
- Report: docs/quality/dlj_resweep_frontend.md

## DLJ-PW-FLOWS — Playwright Flow + Component Tests

- Date: 2026-11-24
- Files created: `e2e/flows.spec.ts`, `e2e/components.spec.ts`
- Flow tests: 10 (multi-step interaction sequences)
- Spot tests: 30 (component-level coverage)
- Total PW tests: 102
- Typecheck: passed (direct TypeScript check of both new specs; `e2e/tsconfig.json` is absent)
- Browser verification: 40 new mocked tests passed.
- Current UI limits covered as implemented: queue search is re-entered after returning from review; category changes save immediately; a missing image URL does not mount ImageViewer. No application code changed.

## DLJ-FIX-R2-BE — Round 2 Backend Fixes

- Date: 2026-11-24
- Findings fixed: R14, R44, R13, R35, R30, R45, R18, R31, R29, R11
- Files modified: `billing.py`, `scheduler.py`, `labeling_router.py`, `label_studio.py`, `trial_guard.py`, `jm_service.py`, `test_validation_fixes.py`, `test_deployment.py`
- Files created: `test_resweep_fixes.py` (19 regression cases)
- Retention cleanup locks and rechecks the cancelling key in the deletion transaction, including subscription identity, and skips tenants with another active key. Cancellation events bypass product validation. Bulk verification accepts explicit outcome and warns on implicit truth derivation. Batch conflict logs omit SQL parameters. Legacy domain creation rejects pipe separators. Verified-incorrect corrections must change category. Cancelled paid keys use the trial daily cap. Connector annotations and numeric factors are validated; config writes use a unique temporary file and atomic replacement.
- Tests: 19 focused passed (SQLite) / 19 focused passed (PostgreSQL); full SQLite suite 407 passed, 1 skipped.
- mypy: clean across the eight requested modules.

## DLJ-FIX-R2-FE — Round 2 Frontend + Deployment Fixes

- Date: 2026-11-24
- Findings fixed: S7.1, S1.1, S1.2, S2.1, S2.2, S3.1, S8.1
- Files modified: `Dockerfile`, `.dockerignore`, `frontend/src/screens/Upload.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/screens/Signup.tsx`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/components/NEREditor.tsx`, `frontend/src/components/TagSelector.tsx`, `e2e/screens.spec.ts`, `e2e/track2.spec.ts`
- Files created: `e2e/fix_round2.spec.ts`, `e2e/tsconfig.json`
- Frontend build: passed; frontend and Playwright typechecks: passed
- PW tests: 107 passed, including all 3 previously failing tests
- Docker image build: unavailable in this environment (Docker CLI absent in Windows and WSL)

## DLJ-SWEEP3-BE — Backend Sweep Round 3

- Date: 2026-11-24
- Dimensions: 8
- Files analyzed: 35
- Findings: P1=20, P2=13, P3=2
- Round 2 fix verification: 5 CLOSED, 5 PARTIAL, 0 OPEN, 0 REGRESSED
- Remaining open P1s (all rounds): 20 in the backend ledger
- Verification: 408 tests collected. The four fix modules returned 48 passed and 1 dialect-specific skip on each of SQLite and PostgreSQL, including all 19 round 2 cases.
- Report: [docs/quality/dlj_sweep3_backend.md](quality/dlj_sweep3_backend.md)

## DLJ-SWEEP3-FE — Frontend Sweep Round 3

- Date: 2026-11-24
- Dimensions: 8
- Components analyzed: 27 (App, 8 screens, 18 child components)
- Findings: P1=5, P2=21, P3=4
- Round 2 fix verification: 5 CLOSED, 2 PARTIAL, 0 OPEN, 0 REGRESSED
- Remaining open P1s (all rounds): 5 distinct frontend findings, including S1.3 outside the seven-fix denominator
- Verification: frontend and E2E typechecks and frontend production build passed. Playwright: 107 passed, 0 failed across 10 specs. Docker image runtime unverified.
- Report: docs/quality/dlj_sweep3_frontend.md

## DLJ-ARCH-REDESIGN — Structural Redesign Specification

- Date: 2026-11-24
- Sections: 7 (diagnosis, legacy disposition, billing FSM, frontend credential model, integration harness, execution plan, P1 closure map)
- Open P1s addressed: 24 of 24 distinct open findings in the specification; implementation and closure gates remain outstanding.
- Phases: 7 (P0–P6)
- Total effort: 47 engineering days; estimated 24–30 working days with three engineers and reviewer/operations support.
- Report: [docs/design/dlj_arch_redesign_v1.md](design/dlj_arch_redesign_v1.md)

## DLJ-FIX-R3-FE — Round 3 Frontend Fixes

- Date: 2026-11-24
- Findings fixed: 5 FE P1s (bulk outcome, signup race, CSV residue, category/tag conflict, usage crash).
- Files modified: `frontend/src/api.ts`, `frontend/src/screens/Signup.tsx`, `frontend/src/screens/Upload.tsx`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/screens/Settings.tsx`, `frontend/src/components/CategorySelector.tsx`, `frontend/src/components/TagSelector.tsx` (and generated `frontend/dist/index.html`).
- Files created: `e2e/fix_round3.spec.ts`.
- Frontend build: passed; frontend TypeScript check passed. The root `npx tsc` resolves TypeScript 4.9.5 and cannot parse the existing E2E config; the frontend TypeScript compiler checked `e2e/tsconfig.json` successfully.
- PW tests: 5 passed in `fix_round3.spec.ts`; 112 tests listed across 11 files.

## DLJ-ARCH-REDESIGN-V2 — Merged Execution Plan

- Date: 2026-11-24
- Replaces: dlj_arch_redesign_v1.md + dlj_post_track2_design_v2.md
- P1s: 21 BLOCKS LAUNCH, 3 ACCEPTABLE RISK, 3 DEFERRED (v1.1; the same three accepted risks)
- Merged prompts: 12 in 7 waves
- Total effort: 28 days wall-clock with two engineering slots (38 engineer-days)
- Integration scenarios: 27 (from v1's 32)
- Report: [docs/design/dlj_arch_redesign_v2.md](design/dlj_arch_redesign_v2.md)

## DLJ-FIX-R3-BE — Round 3 Backend Fixes

- Date: 2026-11-24
- Findings fixed: R14 (complete), R44 (complete), R13 (complete), R45 (complete), R18 (complete), R01, R03, R09
- Files modified: `billing.py`, `scheduler.py`, `trial_guard.py`, `labeling_router.py`, `label_studio.py`, `db/repository.py`, `label_health/api.py`, `test_content.py`, `test_resweep_fixes.py`
- Files created: `test_sweep3_fixes.py`
- Tests: 15 passed (SQLite) / 15 passed (PostgreSQL); full suite 422 passed, 1 skipped
- mypy: clean

## DLJ-SWEEP4-BE — Backend Sweep Round 4 (Convergence)

- Date: 2026-11-24
- Dimensions: 6
- New findings: P1=1, P2=3, P3=1
- Round 3 fix verification: 4 CLOSED, 4 PARTIAL, 0 OPEN
- Cumulative P1 closed: 21 of 40 distinct (52.5%). Two additional issues downgraded, 17 still P1.
- Structural P1s remaining: 11 (8 scheduled in the merged plan, 3 accepted and deferred to v1.1)
- Convergence: not ready for unrestricted Post-Track 2 feature implementation. Ready to start merged prompt 00 and the corrective waves.
- Verification: five fix modules, 63 passed and one dialect-specific skip on each of SQLite and PostgreSQL. Full default suite: 422 passed, 1 skipped.
- Report: docs/quality/dlj_sweep4_backend.md

## DLJ-SWEEP4-FE — Frontend Sweep Round 4 (Convergence)

- Date: 2026-11-24
- Dimensions: 6
- New findings: P1=1, P2=2, P3=0
- Round 3 fix verification: 1 CLOSED of 5; 4 PARTIAL
- FE P1 convergence: 1 new, 4 carried forward, 5 open
- P2s incidentally improved: 3 partially improved, 0 fully closed
- Convergence: not ready for Post-Track 2
- Verification: production build and frontend/E2E typechecks passed; Chromium 110 passed, 2 failed across 11 specs.
- Report: docs/quality/dlj_sweep4_frontend.md

## DLJ-ARCH-V2-FIXES — Integration Budget + Fix Credit

- Date: 2026-11-24
- Changes: (1) Wave 4 includes a joint 04+05 integration day, bringing the schedule to 29 working days. (2) Pre-existing fix credit covers 19 launch-blocking P1s and 2 previously closed P1 regressions (R44 and R18), 21 IDs in total.
- Effort adjustment: 38 → 37 engineer-days (3 saved through test reuse, 2 added for both engineers on integration day).
- File modified: docs/design/dlj_arch_redesign_v2.md

## DLJ-FIX-R4 — Round 4 Combined Fixes

- Date: 2026-11-24
- FE fixes: bulk outcome field and explicit selection, signup request identity, shared review mutation lock, null usage counters, deferred credential cleanup
- BE fixes: R13, R45, R03, R09 partials completed; stalled upload timeout and admission release
- Files modified: frontend/src/api.ts, App.tsx, screens/Signup.tsx, ReviewCard.tsx, Settings.tsx, ScoredQueue.tsx, components/CategorySelector.tsx; labeling_router.py, dashboard_router.py, db/repository.py, label_health/api.py; existing Playwright expectations and test_sweep3_fixes.py
- Files created: test_round4_fixes.py, e2e/fix_round4.spec.ts, docs/quality/dlj_fix_round4_code_audit.md
- PW: 118 passed, 0 failures (including both previously failing bulk payload assertions)
- pytest: 432 passed, 1 skipped; round 4 tests 10 passed on SQLite and 10 on PostgreSQL
- mypy: clean
- Frontend build and TypeScript checks: passed

## DLJ-SWEEP5 — Convergence Sweep (Round 5, Combined BE+FE)

- Date: 2026-11-24
- Dimensions: 5
- Round 4 fixes: 6 CLOSED of 10, 4 PARTIAL
- FE P1: 2
- BE P1: 2 patchable remaining + 10 structural launch blockers + 3 accepted risks = 15
- Tests: 432 pytest passed, 1 skipped + 118 Playwright passed; focused PostgreSQL run 10 passed
- Execution plan: NOT READY
- Report: docs/quality/dlj_sweep5_convergence.md

## DLJ-FIX-R5 — Round 5 Combined Fixes (Red-Green Verified)

- Date: 2026-11-24
- Methodology: RED-GREEN-RED — each test failed before its fix and passed afterward; assertions depend on the changed code paths
- FE fixes: cross-tab epoch invalidation (R3-01+R4-01), draft preservation on canonical navigation (R3-03), persisted receipt cleanup
- BE fixes: annotator projection (R45), exception sanitization (N02), webhook action type guard (N03)
- Files modified: frontend/src/App.tsx, frontend/src/screens/Signup.tsx, frontend/src/screens/ReviewCard.tsx, dashboard_router.py, db/connection.py, scheduler.py, label_studio.py
- Files created: test_round5_fixes.py, e2e/fix_round5.spec.ts, scripts/check_round5.py
- Red-green evidence: 6/6 fixes verified by red-green; executable post-checks passed
- PW: 121 passed (0 failures)
- pytest: 436 passed, 1 skipped; focused PostgreSQL tests 4 passed
- mypy: clean
- Frontend build and TypeScript checks: passed
- Partials closed: R3-01, R4-01, R3-03, R45
- Patchable P1s closed: N02, N03

## DLJ-SWEEP6 — Convergence Sweep (Round 6, Full Broad Audit)

- Date: 2026-11-24
- Dimensions: 6 (fix verification + broad BE + broad FE + tests + P1 scorecard + gate)
- Round 5 fixes: 5 CLOSED of 6; N02 PARTIAL
- New findings: P1=5, P2=3, P3=0
- Definitive P1: patchable=7 (4 BE, 3 FE), structural=9, accepted=3; total=19
- FE P1: 3
- Tests: 436 pytest passed, 1 skipped + 121 Playwright passed; round 5 module 4 passed on each database
- Execution plan: NOT READY
- Report: docs/quality/dlj_sweep6_convergence.md

## DLJ-FIX-R6 — Round 6 Combined Fixes (Red-Green Verified)

- Date: 2026-11-25
- Methodology: RED-GREEN-RED; all seven regression tests failed on their original paths before the application changes and passed afterward
- BE fixes: commit before response (B6-01), complete diagnostic sanitization (N02), connector delivery ordering (B6-02), billing webhook body limit (B6-03)
- FE fixes: Save Tags draft preservation (R3-03), whole-store clear (F6-01), removal of source File from browser history (F6-02)
- Files modified: db/connection.py, db/models.py, db/migrate.py, labeling_router.py, auth.py, account.py, label_studio.py, billing.py, scheduler.py, frontend/src/App.tsx, frontend/src/screens/ReviewCard.tsx, frontend/src/screens/Upload.tsx, frontend/src/screens/HealthReport.tsx, test_round5_fixes.py
- Files created: test_round6_fixes.py, e2e/fix_round6.spec.ts, frontend/src/reportHandoff.ts, scripts/check_round6.py, docs/quality/dlj_fix_round6_code_audit.md
- Red-green evidence: 7/7 verified; 15 shared-session write endpoints enumerated, 15 explicit commits, 0 missing
- PW: 124 passed (0 failures)
- pytest: 443 passed, 1 skipped; focused PostgreSQL round 6 tests 7 passed
- mypy: clean; frontend build and TypeScript checks passed
- Patchable P1s closed: B6-01, N02, B6-02, B6-03, R3-03, F6-01, F6-02

## DLJ-SWEEP7 — Convergence Sweep (Round 7, Full Broad Audit)

- Date: 2026-11-25
- Dimensions: 7 (fix verification + broad BE + broad FE + tests + P1 scorecard + gate + self-check)
- Round 6 fixes: 3 CLOSED of 7, 4 PARTIAL
- New findings: P1=2, P2=7, P3=0
- Definitive P1: patchable=6, structural=9, accepted=3 (18 total)
- FE P1: 2
- Tests: configured pytest 443 passed, 0 failed, 1 skipped; SQLite pytest 442 passed, 1 failed, 1 skipped; Playwright 124 passed of 124
- Execution plan: NOT READY
- Self-check: 76/76 files, 46/46 application endpoints (22 write-capable)
- Report: docs/quality/dlj_sweep7_convergence.md

## DLJ-DESIGN-V3 + PROMPT-00 — Plan Update and Harness

- Date: 2026-11-25
- Part A: Updated `docs/design/dlj_arch_redesign_v2.md` to v3. The former 12-prompt schedule becomes Prompt 00 followed by seven delivery prompts (A–F and 12) in six waves, with five mandatory independent Astra reviews.
- Estimate: 29 → 27 working days, including 2.5 review days. Effort: 37 → 33 engineer-days.
- PostgreSQL is primary. SQLite is advisory. R24 moves to ACCEPTABLE RISK. The release ledger contains 24 launch obligations, four accepted risks and one closed commit-ordering contract.
- Sweep 5–7 findings assigned: A owns B6-03 and expanded N02, B owns expanded R3-03 and F7-01, C owns B6-02 and B7-01.
- Part B: Built `tests/harness/` with isolated PostgreSQL schemas, real application routes, data factories, browser contracts, scenario shells and a separate advisory SQLite CI job.
- Endpoints covered: 46 of 46. All 22 write contracts observe durable state by HTTP response start using a separate reader or a test provider ledger.
- Scenarios shelled: 27 of 27, all skipped with an owning prompt and acceptance criteria. Known-failure tests: 6 of 6, all strict xfails.
- Harness results: 55 passed (46 HTTP and nine browser contracts), 27 skipped, six xfailed on each of PostgreSQL and SQLite.
- Existing tests: 443 pytest passed, one skipped. All 124 Playwright tests passed against an isolated service with a fresh SPA build.
- mypy: clean across 26 harness source files. Post-check: `tests/harness/README.md`. Next gate: independent R1 review before Prompt A.

## DLJ-R1 — Harness Review (Post-Wave 1)

- Date: 2026-11-25
- Contracts: 46/46. Write durability: 22/22 serial paths verified at response start. Overlapping calls can suppress a required observer.
- Scenarios: 27/27 correctly owned. Known failures: 6/6 reproduced as strict expected failures.
- Existing: 443 pytest passed, one skipped. Playwright: 124 passed with two workers; the two default eight-worker runs passed 100/124 and 105/124.
- Prompt A: NOT READY. Correct root pytest discovery, request-scoped durability observations, identity/billing and DTO contract gaps, and the browser gate configuration.
- Report: docs/quality/dlj_r1_harness_review.md

| 2026-11-25 | Paddle checkout URL fix | PASS | Option A: construct hosted checkout URL from txn_id instead of using checkout.url field. Added error logging. |

## DLJ-PADDLE-JS — Paddle.js Overlay + Checkout URL Revert

- Date: 2026-11-25
- Reverted billing.py to return original checkout.url from Paddle API
- Added Paddle.js to frontend/index.html with sandbox environment
- Updated test assertions to match original checkout.url format
- Tests: 60 passed, 27 skipped, 6 expected failures
- mypy: clean
- Frontend build: passed
- Live verification: pending (need to redeploy and test button click)

## DLJ-R1-FIXER — R1 Harness Blocker Fixes

- Date: 2026-11-25
- Harness blockers addressed: 5/5 (pytest discovery, request-owned durability, identity/billing entry contracts, DTO freeze, repeatable browser worker count).
- Files modified: `tests/harness/conftest.py`, `tests/harness/fixtures/factory.py`, `tests/harness/contracts/test_auth.py`, `test_billing.py`, `test_labels.py`, `test_dashboard.py`, `test_revisions.py`, `playwright.config.ts`.
- File created: `tests/harness/test_observers.py` (overlapping observed writes and missing-observation failure).
- Combined root discovery: 537 collected, exit 0 with the live/ops and untracked live Paddle script excluded. Combined execution before the final observer test: 500 passed, two failed, 28 skipped, six xfailed. The two failures are existing checkout tests expecting the earlier Paddle response shape.
- Harness on PostgreSQL: 60 passed, 27 skipped, six xfailed. SQLite advisory run before the final observer test: 59 passed, 27 skipped, six xfailed. The added observer test passed separately.
- Existing offline suite: 441 passed, two failed, one skipped. The checkout failures reproduce in isolation. The untracked `scripts/test_paddle.py` fails on a live SSL request during unconstrained root collection.
- Playwright: 124 passed with two configured workers against an isolated service.
- mypy: clean for harness conftest and factory.
- Next gate: Prompt A remains pending until the two existing checkout tests are reconciled with the current billing response contract and the offline root suite passes.

## DLJ-PROMPT-A-WIP — Incomplete delivery

- Date: 2026-11-25
- Added both A schema blocks to ORM models and additive migration columns; historical backfill and upgraded-schema constraint validation remain open.
- Tightened Label Studio project, task, category, annotation and annotator ID boundaries; added focused PostgreSQL/SQLite harness regressions in `tests/harness/test_prompt_a_boundaries.py`.
- S1–S14 remain skipped: focused boundary checks do not satisfy the complete scenario oracles.
- Verification: `tests/` 62 passed, 27 skipped, six xfailed; `test_jm_service.py` 29 passed; focused migration tests five passed and one skipped; changed-source mypy clean.
- Prompt A is **NOT COMPLETE**. Billing FSM, signup challenge and frontend, project CRUD/access, admission, historical provider repair, safe diagnostics, and full S1–S14 activation are outstanding. Do not advance to R2.

## DLJ-PADDLE-SITE — Go-Live Site Requirements

- Date: 2026-11-25
- Added /refund, a support email and legal links in the SPA footer, and a public pricing table at /#/pricing.
- Tests: 70 passed, 22 skipped, 4 xfailed on local PostgreSQL port 5433. Both runs collected 96 tests. The initial run on the default port 5432 had 68 fixture errors because PostgreSQL rejected the harness password, so an unchanged pass count could not be established.
- Frontend build: passed. Chromium verified the contact link, the three public HTML policies and all four pricing rows on localhost:8080.
- mypy: clean (jm_service.py and legal_pages.py).
| 2026-11-25 | Contact email on legal pages | PASS | Added support@dakshineshwari.net to /terms, /privacy, /refund and /attribution server HTML |

## DLJ-PROMPT-A-2 — Prompt A Completion

- Date: 2026-11-25
- P1s addressed: R02, R14, R19, N05, B6-03, R08, R09, N02, N03, R05, R23 (11 of 11).
- Scenarios activated: S1–S14 (14 of 14); additional project, invite, archive, and historical-key recovery tests are active.
- Schema: both A migration blocks from A-1 are applied; A-2 added proof-rotation markers and guarded historical provider repair. New tables across Prompt A: 11. New domain/key columns across Prompt A: 9.
- Billing FSM: subscription lifecycle, payer-bound checkout intent, current subscription binding, transition log, tenant-serialized retention, and bounded webhook admission.
- Signup: register → mailbox challenge (202) → single-use confirm (201). The first upgrade deactivates active historical email-linked keys without mailbox proof; a successful challenge rotates their digest in place, preserving tenant and billing history. Previously revoked keys without the migration marker cannot self-reactivate.
- Project routes: create/list, versioned settings, member grants, mailbox-bound invites and acceptance. Owner-only archive/reactivation and admin grants, inviter authority recheck, and read-only archive enforcement on HTTP and connector writes are covered.
- Admission: bounded report/upload and billing readers before body parsing. Diagnostics: database and job errors use approved diagnostic fields.
- Historical repair: confirmed Paddle links are bound to an unambiguous payer; ambiguous/legacy links are quarantined; a guarded manifest supports conditional undo. PostgreSQL is authoritative and SQLite is advisory.
- Files modified: `auth.py`, `billing.py`, `account.py`, `labeling_router.py`, `label_studio.py`, `scheduler.py`, `trial_guard.py`, `db/models.py`, `db/migrate.py`, `db/connection.py`, `jm_service.py`, `label_health/api.py`, `email_service.py`, `frontend/src/api.ts`, `frontend/src/screens/Signup.tsx`, and affected pytest/Playwright contracts.
- Files created: `projects_router.py`, `db/tenant_lock.py`, `tests/harness/test_prompt_a_projects.py`, `tests/harness/test_prompt_a_lifecycle.py`.
- Tests: combined root suite 544 passed, 14 skipped, 4 xfailed; `tests/` PostgreSQL and SQLite advisory each 100 passed, 13 skipped, 4 xfailed; PostgreSQL migration tests 6 passed, 1 skipped.
- mypy: clean (12 service/model files). Frontend build and TypeScript checks: passed. Playwright: 124 passed.
- Release note: first-upgrade deactivation requires affected email-linked key holders to complete mailbox confirmation. Export role checks await the Prompt D export endpoint; the signup receipt remains visible until the user can save the one-time key. `transition_log` records applied changes; rejected and duplicate delivery attempts do not yet get separate persisted rows because `event_id` is the table's primary key, so R2 must resolve that audit contract before launch.
- Next gate: R2 Astra review (billing, projects and access); no production release decision is implied by this test pass.

## DLJ-R2 — Billing, Projects and Access Review (Post-Wave 2)

- Date: 2026-11-25
- P1 closure: 1/11 CLOSED, 10 PARTIAL, 0 OPEN.
- Scenarios: 3/14 PASS, 11 WEAK, 0 MISSING. All 14 ran.
- New review findings: P1=14, P2=8, P3=1.
- Tests: final serial PostgreSQL 100 passed, 13 skipped, 4 xfailed. SQLite advisory 100 passed, 13 skipped, 4 xfailed. PW 124 passed. Offline root discovery 562 collected, exit 0.
- Run variance: default PostgreSQL credentials failed on 5432. Overlapping primary runs on 5433 each had one browser failure. The focused retry and serial full run passed.
- Gate verdict: NOT READY.
- Deferred: export authorization through the future Prompt D endpoint. Billing decision history and safe legacy credential recovery must pass R2.
- Report: docs/quality/dlj_r2_review.md
- Next: correct the R2 findings and repeat the review before starting Prompt B or Prompt C.

## DLJ-R2-FIXER — R2 P1 Fixes + Scenario Strengthening

- Date: 2026-11-25
- P1 findings addressed: F1, F2, F3, F4, F5, F6, F7, F8, F10, F12, F15, F16, F17, F21 (14 of 14); independent R2 reopening remains the gate.
- P2 findings addressed: F13 and F18. F11's malformed connector dispatch now returns 422 before lookup.
- Scenarios strengthened: S2–S12 with claim and lock barriers, signed provider deliveries, fresh readback, diagnostic sinks, provider repair, and collision/ownership checks.
- Billing: purchaser, payer, tier and transaction are bound to checkout intent; signed sandbox webhooks, event-specific transitions, durable decision receipts, lifecycle notices and state versions cover entitlement changes.
- Retention and access: pending purchases, repair holds and disabled paid siblings protect tenant data; project mutations lock tenant then payer then project/member; ambiguous aliases are rejected and revisions retain the actual actor key.
- Historical repair: conflicting bindings quarantine only the affected tenant, guarded undo checks binding and trial start, and unknown signup ownership requires operator reconciliation.
- Files modified: `billing.py`, `auth.py`, `account.py`, `scheduler.py`, `projects_router.py`, `labeling_router.py`, `label_studio.py`, `trial_guard.py`, `db/models.py`, `db/migrate.py`, `db/connection.py`, `tests/harness/conftest.py`, `tests/harness/fixtures/factory.py`, `tests/harness/scenarios/test_s01_s06.py`, `tests/harness/scenarios/test_s07_s14.py`, `tests/harness/contracts/test_billing.py`, `test_billing.py`, `test_account.py`, `test_billing_fixes.py`, `test_resweep_fixes.py`.
- Files created: `db/entitlement.py`, `tests/harness/test_r2_fixes.py`.
- Tests: PostgreSQL `tests/` 123 passed, 13 skipped, 4 xfailed; SQLite advisory harness 122 passed, 14 skipped, 4 xfailed; offline root suite 444 passed, 1 skipped. Root discovery collected 585 with the known live Paddle import script excluded.
- mypy: clean on 13 service/model files. Playwright: 124 passed with two workers. No frontend source changed; frontend build was not repeated.
- Next gate: reopen the independent R2 billing, projects and access review before Prompt B or Prompt C.

## DLJ-R2-REOPEN — Billing, Projects and Access Review (Post-Fixer)

- Date: 2026-11-25
- Original P1 closure: 2/11 CLOSED, 9 PARTIAL, 0 OPEN.
- R2-found P1 closure: 4/14 CLOSED, 10 PARTIAL, 0 OPEN.
- Scenarios: 7/14 PASS, 7 WEAK, 0 MISSING. All 14 active on PostgreSQL.
- New findings: P1=3, P2=2, P3=0.
- Tests: PostgreSQL tests/ and standalone harness each 123 passed, 13 skipped, 4 xfailed. Advisory SQLite 122 passed, 14 skipped, 4 xfailed. Playwright 124 passed. Frontend build passed. Offline root discovery collected 585.
- Gate verdict: NOT READY.
- Report: docs/quality/dlj_r2_review.md
- Next: close the retention, billing, access and boundary findings and repeat R2. Prompt B and Prompt C remain blocked.

## DLJ-R2-FIXER-2 — R2 Reopen Criteria 1-5

- Date: 2026-11-25.
- Criterion 1 (retention): shared `effective_state` protects disabled, null-state paid siblings; tenant deletion terminalizes all siblings, audits every transition, and admin issuance refuses a destroyed tenant. PostgreSQL and SQLite regression checks passed.
- Criterion 2 (billing): retryable delivery attempts are audited separately from terminal receipts; premature signed updates can apply after creation. Resubscription requires a new subscription ID, the historical exemption checks customer and subscription provenance, and checkout metadata and audit IDs are bounded.
- Criterion 3 (access): invitation acceptance refreshes after locking and claims conditionally; payer and issuer key locks are sorted. UUID project selection resolves legacy alias collisions, credential actor identity uses one lookup, and domain-creating paths check payer entitlement.
- Criterion 4 (input and diagnostics): startup URL parsing is redacted, connector-derived IDs and actions are validated before writes, billing and report intake have hard waiter bounds, explicit null project settings return 422, and the PostgreSQL owner constraint matches its inverse.
- Criterion 5 (scenarios): S3, S4, S5, S6, S9, S10 and S12 gained waiter, diagnostic, nested input, boundary, retry, renewal and concurrent retention observations.
- New P1s addressed: N1, N2 and N3. New P2s addressed: N4 and N5. Independent closure review remains required.
- Files modified: `account.py`, `auth.py`, `billing.py`, `db/connection.py`, `db/migrate.py`, `db/entitlement.py`, `label_health/api.py`, `label_studio.py`, `labeling_router.py`, `projects_router.py`, `scheduler.py`, `tests/harness/scenarios/test_s01_s06.py`, `tests/harness/scenarios/test_s07_s14.py`, `tests/harness/test_r2_fixes.py`, `e2e/components.spec.ts`.
- Tests: sequential PostgreSQL `tests/` 130 passed, 13 skipped, 4 xfailed; SQLite advisory harness 127 passed, 16 skipped, 4 xfailed. The focused retention regression passed on both dialects. An overlapping run had fixture setup errors; the sequential PostgreSQL rerun passed.
- mypy: clean on 13 requested backend files. Frontend build: passed. Playwright: 124 passed with two workers.
- Next gate: independent R2 reopen review #2. Prompt B and Prompt C remain blocked until that gate passes.

## DLJ-R2-REOPEN-2 — Post-Fixer Round 2 Review

- Date: 2026-11-25
- Original P1 closure: 5/11
- First-R2 P1 closure: 9/14
- Reopen P1 closure: 1/3
- Scenarios: 10/14 PASS, 4 WEAK (S3, S5, S6, S10), 0 MISSING
- New findings: P1=2, P2=1, P3=0
- Tests: PostgreSQL tests/ and standalone harness each 130 passed, 13 skipped, 4 xfailed. SQLite advisory 127 passed, 16 skipped, 4 xfailed. PW first run 123 passed and 1 failed, isolated full rerun 124 passed. Frontend build passed.
- Independent upgrade check: migrated a populated pre-A PostgreSQL schema twice, verified the disabled paid payer's domain survived sibling cleanup and executed the named ownership-constraint inverse.
- Gate verdict: NOT READY
- Report: docs/quality/dlj_r2_review.md
- Next: resolve the outstanding closure rows and scenario evidence before repeating R2. Prompt B and Prompt C remain blocked.

## DLJ-R2-FIXER-3 — Contract-aligned fixes

- Date: 2026-11-25
- Contract 1 (eligibility): unified checkout/fulfilment/issuance/cleanup eligibility via `resolve_entitlement`; added timestamp tiebreaking, historical provenance checks, disposition-aware receipt retry, and mixed-tombstone normalization.
- Contract 2 (lock order): rechecked collaborator roles after locking, included the acceptor key in sorted invitation locks, and rejected UUID-shaped public aliases.
- Contract 3 (validation first): validated connector shape before payer access, bounded action IDs, validated full provider transaction IDs, and gated project creation on payer eligibility.
- Contract 4 (scenarios): strengthened S3 with peak/recovery assertions, S5 with ground-truth and validation-order checks, S6 with action boundaries, and S10 with both renewal/cleanup commit orders plus reconciliation evidence.
- Findings closed by contract alignment: N6, N7, R02, R14, R19, F1, F2, N1, N2, N03, R05, F6, F16, F17, plus N8 P2.
- Files modified: `account.py`, `auth.py`, `billing.py`, `db/entitlement.py`, `db/migrate.py`, `db/models.py`, `labeling_router.py`, `label_studio.py`, `projects_router.py`, `scheduler.py`, `trial_guard.py`, `frontend/src/screens/ScoredQueue.tsx`, `tests/harness/contracts/test_billing.py`, `tests/harness/scenarios/test_s01_s06.py`, `tests/harness/scenarios/test_s07_s14.py`, `tests/harness/test_r2_fixes.py`.
- Tests: PostgreSQL `tests/` and standalone harness each 134 passed, 13 skipped, 4 xfailed; SQLite advisory harness 131 passed, 16 skipped, 4 xfailed.
- mypy: clean on all 13 requested backend files.
- Playwright: 124 passed in both full runs.
- Frontend build: passed.
- Next gate: R2 reopen review #3.

## DLJ-R2-REOPEN-3 — Contract-verified review

- Date: 2026-11-25
- Contract 1 (eligibility): PARTIAL
- Contract 2 (lock order): PARTIAL
- Contract 3 (validation): PARTIAL
- Contract 4 (scenarios): PARTIAL
- P1 closure: 19/30 incoming findings CLOSED, 11 PARTIAL
- Scenarios: 10/14 PASS, 4 WEAK (S3, S5, S6, S10), 0 MISSING
- New findings: P1=3, P2=1, P3=0
- Tests: PostgreSQL full and standalone each 134 passed, 13 skipped, 4 xfailed. Advisory SQLite 131 passed, 16 skipped, 4 xfailed. PW 124 passed ×2. Initial run variance is recorded in the report.
- Gate verdict: NOT READY
- Report: docs/quality/dlj_r2_review.md
- Next: resolve the documented reopen criteria and repeat independent R2 before Prompt B or Prompt C.

## DLJ-R2-UNIFIED — Accepted-risk ledger for v1.1

The launch installation starts with an empty PostgreSQL schema. A marker recorded in the first migration keeps historical repair jobs off subsequent fresh-install deploys. Before importing a legacy snapshot, reopen the affected rows below. Estimates are engineering estimates for shared work packages and overlap across related IDs.

| Item | Reason and mitigation | Trigger and owner | Future effort |
|---|---|---|---|
| N1 · old rejected receipts | An old receipt can lack trustworthy disposition history. Keep the existing retry/readback checks and preserve source events for reconciliation. New deliveries use applied receipts. | Billing owner, before importing any old receipt table or replaying unclassified deliveries. | 1–2 days |
| N2 · erroneous existing manifests | A pre-existing manifest can associate a modern key with historical ownership. Preserve an audited snapshot and quarantine ambiguous mappings. | Storage owner, before importing manifests or unblocking a quarantined payer. | 2 days with R23 |
| N9 · repair followed by checkout | A later valid checkout can make historical repair quarantine a previously reconciled payer. Keep historical repair off fresh redeploys. | Billing and storage owners, before rerunning repair on a previously repaired tenant with checkout activity. | 2 days with N2 |
| R23 · provider ownership repair | Ambiguous pre-A provenance requires operator evidence before activation. Preserve the existing before/after manifest and conditional undo. | Migration owner, on the first proposed pre-A provider import. | 2–3 days with N2/N9 |
| F1 · historical intent exemption | An old customer/subscription mapping may have insufficient provenance. New grants require a purchaser, payer and provider transaction bound to an intent. | Billing owner, before accepting an intent-free historical creation. | 1 day with R23 |
| N10 · old mixed tombstones with a pending purchase | Historical normalization can override an outstanding intent. Keep those rows out of the launch database and preserve them for reconciliation. | Storage owner, before processing mixed historical keys or restoring such a backup. | 2–3 days with R14/F2/F5 |
| R14 · historical terminalization | Replaying old terminal states requires guarded reconciliation and per-key version checks. Modern retention runs under the tenant guard. | Lifecycle owner, before admitting historical tombstones. | 1–2 days with N10 |
| F2 · legacy cleanup holds | Historical rows can have mixed payer, intent and repair holds. Inventory holds before normalization. | Retention owner, when importing historical siblings with nonterminal obligations. | 1 day with N10 |
| F5 · legacy audit gaps | Historical normalization can change state without a contemporaneous transition or notice. Preserve original versions and reconcile them offline. | Billing owner, before historical transitions feed notices or support tooling. | 1 day with N10 |
| N11 · historical simultaneous events | Existing watermarks may encode a prior arrival-order decision. Preserve signed history for offline reconciliation. Current deliveries have a deterministic cancellation tie rule. | Billing owner, before replaying an old event stream with ties. | 1–2 days with R19 |
| R19 · retrospective lifecycle reconciliation | Previously persisted state may disagree with a replay of equal-time events. Compare payer state, notice history, quota and retention before cutover. | Billing owner, before a historical payer or watermark enters service. | 1 day with N11 |

## DLJ-R2-UNIFIED — Find, fix and verify sweep

- Date: 2026-11-25
- Classification: 6 LAUNCH and 8 DEFERRED among 14 incoming partial/new P1s. 19 previous P1 closures retained.
- LAUNCH P1s fixed: N03, R05, F6, F16, F17 and prospective R19. N12 (P2) also fixed.
- DEFERRED P1 rows: R14, F2, F5, N10, R23, N2, N9 and retrospective N11. Historical-only edges of N1, F1 and R19 are included in the accepted-risk ledger above.
- Scenarios: 14/14 PASS on PostgreSQL. S3, S5, S6 and S10 strengthened.
- Contracts verified: 4/4 for a fresh installation.
- Additional fixes: fresh-install provenance survives redeployment, signed duplicates recheck under the guard, terminal deliveries have a specific reconciliation reason, invitation acceptance uses the verified signup mailbox, and expiry/invalid-task errors retain their public detail. Ordinary screens no longer wait for Paddle.js. Transaction landing pages initialize the checkout SDK.
- Tests: PostgreSQL 140 passed, 13 skipped, 4 xfailed in both the full and standalone runs. SQLite advisory 137 passed, 16 skipped, 4 xfailed. Supplemental offline root suite 444 passed, 1 skipped.
- Playwright: 124 passed ×2, two workers, zero retries. Frontend build and E2E typecheck passed.
- mypy: clean on 21 files.
- Gate verdict: PASS for fresh PostgreSQL.
- Report: docs/quality/dlj_r2_review.md
- Next: Prompt B + Prompt C (Wave 3, parallel).

## DLJ-PROMPT-B — Project UI

- Date: 2026-11-25
- P1s addressed: R3-01, R3-02, R3-03, R3-08, F7-01 (5 of 5).
- Scenarios activated: S28-S32 (5 of 5), including same-tab and cross-tab signup rotation, real chunked import rotation, project isolation, dirty review navigation, and malformed response recovery.
- Design contract: §2 B/C verified across modified frontend paths; operations capture credential, project, generation, operation ID, and abort signal. Review navigation stores identifiers only.
- Files modified: frontend/src/App.tsx, frontend/src/api.ts, frontend/src/domain.tsx, frontend/src/components/CategorySelector.tsx, frontend/src/components/CsvDropzone.tsx, frontend/src/screens/AnnotatorProfiles.tsx, Dashboard.tsx, ReviewCard.tsx, ScoredQueue.tsx, Settings.tsx, Signup.tsx, Upload.tsx, tests/harness/conftest.py, tests/harness/browser/test_browser_contracts.py, tests/harness/scenarios/test_s28_s32.py.
- Files created: frontend/src/operationContext.ts, frontend/src/screens/Projects.tsx, frontend/src/screens/ProjectSettings.tsx.
- Tests: 162 passed, 0 skipped, 0 xfailed in full `tests/` and standalone `tests/harness/` PostgreSQL runs. Joint B/C S27 queue bulk browser integration passed.
- PW: 124 passed on final build (one worker); E2E typecheck passed.
- mypy: clean for auth.py and labeling_router.py.
- Frontend build: passed.
- Next gate: R3 Astra review (B+C combined).

## DLJ-PROMPT-C — Shared Writes

- Date: 2026-11-25
- P1s addressed: R01, R03, R04, R29, R45, R13/R3-07, B6-02, B7-01 (8 of 8).
- Scenarios activated: S20-S27 (8 of 8).
- Schema: C block applied (uq_revision_predecessor, connector_config, project_request, label_log columns).
- Design contracts: §2 B/C and the four R2 contracts verified across modified files.
- Files modified: db/models.py, db/migrate.py, db/repository.py, label_studio.py, labeling_router.py, dashboard_router.py, jm_service.py, tests/harness/scenarios/test_s20_s27.py, tests/harness/scenarios/test_s28_s32.py, tests/harness/contracts/test_connector.py, tests/harness/test_known_failures.py.
- Files created: tests/harness/test_prompt_c_import.py, tests/harness/browser/test_prompt_c_joint.py.
- Tests: PostgreSQL 164 passed, 0 skipped, 0 xfailed; SQLite advisory 161 passed, 3 skipped.
- mypy: clean.
- Frontend build: passed.
- Playwright: 124 passed.
- Next gate: R3 Astra review (B+C combined, then Wave 4).

## DLJ-R3-UNIFIED — B+C combined review

- Date: 2026-11-25
- Contracts: 4/4 VERIFIED under the R2 fresh-install contracts. Connector configuration and stored task binding require scoped reads before payer access.
- B P1 closure: 5/5 CLOSED.
- C P1 closure: 8/8 CLOSED.
- Schema: §4 C block MATCHES on fresh PostgreSQL and a populated A-to-C upgrade run twice.
- B+C interaction: 5/5 paths VERIFIED.
- Scenarios: 27/27 PASS, 0 WEAK.
- New findings found and fixed: C retention dependencies, member import permissions, connector identity/watermark/first spans, configuration version and binding, UUID sample replay, stale signup receipts, route and draft ownership, DTO and truth validation. Strengthened concurrency, migration and real-browser regressions.
- Deferred findings added: none.
- Tests: PostgreSQL 167 passed in full discovery and 167 passed standalone; SQLite 164 passed, 3 PostgreSQL-only skips; Playwright 124 passed ×2 consecutively.
- mypy: clean on 14 changed Python files. E2E TypeScript passed.
- Frontend build: passed.
- Gate verdict: PASS for fresh PostgreSQL.
- Report: docs/quality/dlj_r3_review.md
- Next: Prompt D + Prompt E (Wave 4, parallel).

## DLJ-PROMPT-E — Webhooks
- Date: 2026-11-25
- Schema: E block applied (webhook_endpoint, shared webhook_event preserved/check-first, webhook_delivery, webhook_attempt); retention deletes dependent webhook rows before projects.
- CRUD: register, list, paginated deliveries, update, deactivate, test, rotate; admin+ role gate, five active endpoints, ten tests/hour.
- Delivery: dispatcher in scheduler loop, PostgreSQL SKIP LOCKED plus global claim fence, conditional SQLite fallback, four concurrent sends, one send/endpoint, four attempts (10/60/300-second retries), 30-second fenced leases and recovery.
- Security: public HTTPS revalidated at connection time, redirects disabled, Fernet-encrypted secrets shown once, exact canonical UTF-8 bytes signed with HMAC-SHA256, no source text or response body in delivery logs.
- Contracts: §2 E/F verified; shared Prompt D envelope unchanged; R2/R3 eligibility, lock-order and validation contracts preserved.
- Files modified: db/models.py, db/migrate.py, scheduler.py, jm_service.py, requirements.txt, tests/harness/conftest.py, docs/session_state.md.
- Files created: webhook_router.py, webhook_security.py, tests/harness/test_prompt_e_webhooks.py.
- Tests: PostgreSQL 198 passed, 0 skipped, 0 xfailed; SQLite advisory 185 passed, 3 skipped; Prompt E 15/15 passed on both dialects.
- mypy: clean.
- Frontend build: passed.
- Playwright: 124 passed.
- Next gate: R4 Astra review (D+E combined).

## DLJ-PROMPT-D — Export and Predictions

- Date: 2026-11-25
- Schema: D blocks applied (`project_export_slot`, `prediction`, `webhook_event`) with repeatable fresh/upgrade migration coverage and retention-safe child deletion.
- Export: JSONL/CSV streaming response, optional DocBin, project filters, reviewer role gate, two five-minute lease slots, 5,000-document/16 MiB text caps, 32 MiB browser cap, CSV formula escaping, and PostgreSQL REPEATABLE READ keyset pages.
- Predictions: import (1–100), idempotent replay, scored provenance, five-gate automation without machine learning evidence, optimistic human review, reopen, and state/source/accuracy statistics.
- Event production: canonical `label.verified` and `prediction.auto_approved` envelopes are written transactionally to `webhook_event`; HTTP, prediction-review, and connector human-evidence paths are covered.
- Contracts: §2 D/F verified; R2/R3 eligibility, lock/revalidation, validation-before-access, shared-write, and evidence contracts preserved.
- Files modified: auth.py, db/models.py, db/migrate.py, db/repository.py, labeling_router.py, label_studio.py, scheduler.py, tests/harness/conftest.py, tests/harness/contracts/test_export.py, tests/harness/contracts/test_predictions.py, tests/harness/scenarios/test_s20_s27.py.
- Files created: tests/harness/test_prompt_d_schema.py.
- Tests: PostgreSQL 187 passed, 0 skipped, 0 xfailed; SQLite advisory 181 passed, 3 PostgreSQL-only skipped, plus the final D/S21/S26 subset 8 passed after connector event coverage.
- mypy: clean on all 9 required backend modules.
- Playwright: 124 passed.
- Frontend build: passed.
- Next gate: R4 Astra review (D+E combined).

## EXP-DLJ Experiments (completed)

- Date: 2026-11-25.
- experiments/__init__.py (empty).
- experiments/active_learning_harness.py — shared active learning harness.
- experiments/exp_dlj_01_active_learning.py — centroid distance versus uncertainty sampling.
- experiments/exp_dlj_02_transfer.py — cross-project transfer efficacy.
- experiments/generate_charts.py — four publication charts.
- tests/test_exp_dlj.py — 10 infrastructure tests.
- experiments/results/exp_dlj_01_results.json — EXP-DLJ-01 PASS on deterministic synthetic fallback; centroid distance reached 85% in 200–250 labels across five seeds.
- experiments/results/exp_dlj_02_results.json — EXP-DLJ-02 PASS on deterministic synthetic fallback; cold-start mean 335 labels, transfer mean 0 labels to 80%.
- experiments/results/charts/ — four PNG charts.
- Test count: baseline 188 collected + 10 new = 198 passed in the final full suite.
- mypy: clean on five new Python files.
- No changes to jm_core.py or existing production code.

## EXP-DLJ Parameter Sweep (completed)

- Date: 2026-11-26.
- experiments/exp_dlj_sweep.py — configurable synthetic data generator and both parameter sweeps.
- experiments/generate_sweep_charts.py — seven line and heatmap sweep charts.
- tests/test_exp_dlj_sweep.py — six generator and sweep smoke tests.
- experiments/results/exp_dlj_01_sweep_results.json — 24 unique cells across noise, dimensions, categories, batch size, pool size and the noise × dimensions grid.
- experiments/results/exp_dlj_02_sweep_results.json — 19 unique cells across source size, similarity, dimensions and the source size × similarity grid.
- experiments/results/charts/ — seven new sweep charts plus four prior charts, 11 total.
- Test count: 201 selected baseline + six new = 207 passed, one unrelated SQLite test deselected; 16 experiment tests passed in isolation.
- mypy: clean on six experiment and test modules.
- Operating envelope: DLJ-01 centroid advantage +10.0 pp at default; still +5.5 pp at 20% training-label noise and +5.5 pp at ten factors. At a 500-item pool it loses by 0.8 pp. No noise or dimensionality breakdown was observed in the tested range.
- Operating envelope: DLJ-02 transfer reduction 100% at full rule similarity. At 75% similarity, no transfer seed reached 80% within 500 labels; the negative reduction values in censored cells use a 525-label cap and are estimates.
- All sweep results use deterministic synthetic data; AG News was not cached.
- Baseline collection repair: relocated misplaced webhook `terminal_at` lines in db/models.py and db/migrate.py and the connector prediction guard in label_studio.py.

## R4 Unified Review (D+E Combined)

- Date: 2026-11-26
- Reviewer: Astra+high unified sweep, Prompt D and Prompt E.
- Scope: Fresh PostgreSQL deployment. The eight historical and four legacy accepted risks remain deferred to v1.1.
- PostgreSQL gate: 208 passed, 0 failures in full tests/ discovery. The requested name filter passed 207 and deselected S13. The additional root CI regression run passed 427, skipped 1 SQLite-only case and deselected 33.
- SQLite advisory: 189 passed, 3 PostgreSQL-only skips. PostgreSQL is the only gate. SQLite advisory tests remain for local dev convenience but do not block.
- Playwright: Previous standalone result 124 passed. No frontend code changed. Browser-backed Python scenarios passed in the PostgreSQL gate.
- P1 found: 10. P2 found: 9. P3 found: 0. P1 fixed: 10. P2 fixed: 9.
- SQLite gate issue: Fixed the root regression job that still collected hard-coded SQLite fixtures. Retained the separate advisory job and all tests.
- Integration D↔E: Verified canonical event and delivery persistence, rollback visibility, signed bytes, claim fencing, archive cancellation and child-first retention. A two-session probe observed exactly one claim after commit and none after rollback.
- Export: Local PostgreSQL 17.11 returned 5,000 documents at exactly 16 MiB of source text. Both one-over limits returned 413 and released the slots. Railway Hobby resource measurements remain unverified.
- mypy: Clean on 24 changed Python files. Frontend build passed.
- Verdict: PASS for fresh PostgreSQL.
- Report: docs/quality/dlj_r4_review.md

## Prompt F — Guide, Prediction Review UI, Integrations Settings

**Shipped:** 2026-11-26
**Baseline (pre-F):** PG 192 passed (16 experiment tests deselected), PW 124 passed
**Post-F:** PG 221 passed (16 experiment tests deselected), PW 136 passed
**New tests:** 29 PG + 12 PW

### Deliverables
- `/#/docs` guide page with eight workflow sections, desktop sidebar navigation and a responsive mobile selector.
- `/dlj_client.py` downloadable single-file `DLJClient` with chunked uploads, stable replay keys, three-attempt exponential retry and a configurable 30-second timeout.
- `/docs` Swagger UI and `/openapi.json` remain available; new routes are tagged and documented.
- Prediction review UI with origin/state filters, sortable queue, Accept/Correct/Reopen, optimistic revision checks and focus-scoped `a/c/r/n/p/Escape` shortcuts.
- Project integrations settings with webhook CRUD, HTTPS validation, delivery health, one-time/rotated secrets and the latest 20 attempts.
- Authenticated delivery-history and project webhook-health endpoints.

### Scenarios
- S1, S23 and S27 reruns passed; canonical S28–S31 browser-backed scenarios remained active and passed in the full PostgreSQL gate.
- F-specific quickstart, role gates, sequential-review conflict, secret rotation during delivery and failure/recovery health gates passed.

### Files changed
- `backend/static/dlj_client.py` (new)
- `jm_service.py`
- `labeling_router.py`
- `webhook_router.py`
- `frontend/src/pages/GuidePage.tsx` (new)
- `frontend/src/pages/PredictionReviewPage.tsx` (new)
- `frontend/src/pages/IntegrationsSettingsPage.tsx` (new)
- `frontend/src/components/PredictionReviewCard.tsx` (new)
- `frontend/src/components/DeliveryHealthIndicator.tsx` (new)
- `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/index.css`
- `tests/__init__.py` (new; makes harness imports unambiguous)
- `tests/test_prompt_f.py` (new — 29 tests)
- `e2e/test_prompt_f.spec.ts` (new — 12 tests)

### Verification
- PostgreSQL gate: 221 passed, 16 experiment tests deselected, 0 failures.
- Prompt F backend: 29/29 passed.
- Playwright: 136/136 passed.
- mypy: clean on `jm_service.py`, `labeling_router.py`, `webhook_router.py` and `tests/test_prompt_f.py`.
- Frontend typecheck and production build: passed.
- Python client: syntax valid; all eight public methods present.
- No DDL changes and no new migrations.

## R5 Review — Unified Astra Sweep (Prompt F + Full Regression)

**Date:** 2026-11-26  
**Verdict:** PASS. Prompt 12 is unblocked.  
**Baseline:** PostgreSQL 221 passed, Playwright 136 passed.  
**Post-review:** PostgreSQL 222 passed, 16 experiment tests deselected. Playwright 138 passed. The 16 experiment tests also passed separately.  
**Findings:** P1: 6 resolved (including one verification-path error), P2: 7 fixed, P3: 1 open (guide section deep-link restoration).  
**Scenarios:** 27/27 passed against their design oracles.  
**Files reviewed:** 27 source, test and packaging files, including all 15 files listed for Prompt F.  
**Checks:** mypy and TypeScript clean. Frontend production build passed.  
**Fixes applied:** Corrected the verification targets, packaged the client in the release image, blocked credential-bearing redirects, required observed verification outcomes and span acknowledgement, guarded keyboard shortcuts, corrected retries and export writes, unified queue filtering and paging, validated review decisions, corrected webhook health and attempt history, aligned operator guidance with the signer and rotation behavior, and strengthened client, worker and browser regression tests.  
**Report:** [R5 findings](quality/dlj_r5_review.md)

## Sprint 0 — Smart Sampling + SLA Badge + Quickstart

**Date:** 2026-11-26
**Baseline:** PG 222, PW 138
**Post-Sprint0:** PG 232, PW 142
**New tests:** 10 PG + 4 PW

### Deliverables
- GET /v1/projects/{id}/next-batch — centroid distance ordering, fallback to random
- GET /v1/projects/{id}/sla — accuracy floor, margin, gate status
- Smart Queue toggle on dashboard/queue
- SLA badge on dashboard (green/amber/red shield)
- /#/quickstart — 5-step interactive walkthrough
- Quickstart link in nav

### Files changed
- `labeling_router.py`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/screens/ScoredQueue.tsx`
- `frontend/src/screens/Dashboard.tsx`
- `frontend/src/components/SLABadge.tsx` (new)
- `frontend/src/pages/QuickstartPage.tsx` (new)
- `tests/test_sprint0.py` (new)
- `e2e/test_sprint0.spec.ts` (new)
- `frontend/dist/index.html` (production build output)

Verification: PostgreSQL 232 passed with 16 experiment tests deselected; Playwright 142 passed; frontend TypeScript and production build passed; backend mypy passed. No DDL or migration changes. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

## Sprint 0 Review — Bug Sweep + Test Hardening

**Date:** 2026-11-26  
**Baseline:** PG 232 passed, PW 142 passed  
**Post-review:** PG 251 passed, 16 experiment tests deselected. PW 160 passed.  
**Bugs found:** 15, all fixed.  
**Tests added:** 19 backend + 18 Playwright. The browser journeys run the built app against an isolated PostgreSQL schema. External webhook delivery is simulated.  
**Verification:** Backend mypy, frontend and E2E TypeScript, and the production frontend build passed. The frozen engine hash matched. No schema or migration changes.  
**Files:** `auth.py`, `labeling_router.py`, `frontend/src/api.ts`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/components/SLABadge.tsx`, `frontend/src/pages/GuidePage.tsx`, `frontend/src/pages/QuickstartPage.tsx`, `frontend/dist/index.html`, `tests/test_sprint0.py`, `tests/test_sprint0_extended.py`, `tests/sprint0_browser_server.py`, `tests/e2e/test_sprint0_extended.spec.ts`, `playwright.config.ts`, `e2e/tsconfig.json`, `e2e/test_prompt_f.spec.ts`, `docs/quality/dlj_sprint0_review.md`, `docs/session_state.md`.  
**Report:** [Sprint 0 review](quality/dlj_sprint0_review.md)

## Analytics UI — Distribution + Throughput + Confusion + Agreement

**Date:** 2026-11-26  
**Baseline:** PG 251, PW 160  
**Post:** PG 268, PW 167  
**New tests:** 17 PG + 7 PW

### Deliverables
- GET /v1/projects/{id}/analytics/distribution — category counts + imbalance warning
- GET /v1/projects/{id}/analytics/throughput — daily labels, per-annotator, avg time
- GET /v1/projects/{id}/analytics/confusion — category confusion matrix + top pairs
- GET /v1/projects/{id}/analytics/agreement — inter-annotator agreement heatmap
- Dashboard: distribution bars + throughput line chart
- Insight: confusion matrix + agreement heatmap
- No DDL changes

### Files changed
- `analytics_router.py` (new)
- `jm_service.py`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/screens/Dashboard.tsx`
- `frontend/src/components/DistributionPanel.tsx` (new)
- `frontend/src/components/ThroughputPanel.tsx` (new)
- `frontend/src/pages/AnalyticsPage.tsx` (new)
- `frontend/dist/index.html`
- `tests/test_analytics.py` (new)
- `tests/e2e/test_analytics.spec.ts` (new)

Verification: PostgreSQL 268 passed with 16 experiment tests deselected; Playwright 167 passed on the clean rerun; backend mypy, frontend TypeScript, E2E TypeScript, and the production frontend build passed. No schema or migration files were changed. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

## Multi-Modality Design — Astra Review + Completion

**Date:** 2026-11-26  
**Input:** docs/design/dlj_multimodal_design_v2.md  
**Output:** docs/design/dlj_multimodal_design_v3.md (execution-ready)  
**Findings:** 9 P1, 7 P2, 2 P3  
**Execution plan:** 7 Codex prompts, 116 estimated new tests (83 PostgreSQL + 33 Playwright)

## Design Consolidation

**Date:** 2026-11-26  
**Input:** 4 current design docs (arch_redesign_v2, annotation_ui_v2, post_track2_v2, multimodal_v3)  
**Output:** docs/design/dlj_product_design_v1.md (unified)  
**Sections:** 16 chapters, 133 section/subsection headings; all 39 source sections mapped  
**Contradictions resolved:** 17  
**Gaps identified:** 15 (5 documentation gaps filled, 10 product or evidence questions remain)  
**Superseded:** 8 files indexed in docs/design/SUPERSEDED.md  
**Verification:** 100 mounted operations, 77 DTOs, 26 ORM tables and 238 columns cross-checked; 27 scenario IDs and all archive links verified. Documentation only. Latest recorded Analytics gate: PG 268, PW 167.

## Notes + Guidelines

**Date:** 2026-11-26
**Baseline:** PG 268, PW 167
**Post:** PG 280, PW 172
**New tests:** 12 PG + 5 PW
**DDL:** 3 nullable columns added (`notes`, `review_notes`, `guidelines_updated_at`; existing `guidelines` reused)

### Deliverables
- Per-label notes on verify/review (500 char, optional, in JSONL/CSV export)
- Per-project guidelines (markdown, 10 KiB UTF-8 max, admin-only edit)
- Guidelines banner at top of labeling queue (collapsible, state remembered per project)

### Files changed
- `db/models.py`, `db/migrate.py`, `db/repository.py`
- `labeling_router.py`, `projects_router.py`
- `frontend/src/api.ts`, `frontend/src/index.css`
- `frontend/src/components/GuidelinesPanel.tsx`, `frontend/src/components/GuidelinesBanner.tsx`
- `frontend/src/screens/ReviewCard.tsx`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/ProjectSettings.tsx`
- `e2e/components.spec.ts`, `tests/test_notes_guidelines.py`, `tests/e2e/test_notes_guidelines.spec.ts`
- `frontend/dist/index.html`

**Verification:** PostgreSQL 280 passed with 16 experiment tests deselected; Playwright 172 passed; backend mypy, frontend TypeScript, E2E TypeScript, and production frontend build passed. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

## MM-01 — Project Schema and Modality Policy

**Date:** 2026-11-26
**Baseline:** PG 280, PW 172
**Post:** PG 289, PW 172
**New tests:** 9 PG + 0 PW
**DDL:** 3 columns on `domains` (`content_type`, `label_schema`, `modality_enforced`), 1 check constraint (`ck_domains_modality_pair`), `image_url` widened to `TEXT` on `label_content`

### Deliverables
- Domain model extended with `content_type`, `label_schema`, and `modality_enforced`
- Database constraint enforces the five valid text/image and single/multi/NER pairs
- `modality.py` provides the capability matrix, release-switch validation, and first-label lock check
- Project creation accepts optional modality axes; omitted axes preserve legacy `text`/`single`, unenforced behavior
- Project detail/list responses expose modality policy and lock state
- `GET /v1/projects/capabilities` returns only currently enabled combinations
- Settings updates preserve optimistic concurrency and reject modality changes after the first label
- Runtime switches: `DLJ_IMAGE_PROJECTS_ENABLED`, `DLJ_MULTILABEL_PROJECTS_ENABLED`, `DLJ_NER_PROJECTS_ENABLED`

### Files changed
- `db/models.py`
- `db/migrate.py`
- `db/repository.py`
- `modality.py` (new)
- `projects_router.py`
- `tests/test_modality_schema.py` (new)
- `docs/session_state.md`

**Verification:** PostgreSQL 289 passed with 16 experiment tests deselected; Playwright 172 passed; frontend TypeScript and backend mypy passed. Fresh, repeated, and populated-database migration paths passed on PostgreSQL. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

## MM-03 — Image Project Frontend Workflows

**Date:** 2026-11-26
**Baseline:** PG 306 (MM-02-inclusive actual), PW 172
**Post:** PG 306, PW 181
**New tests:** 0 PG + 9 PW

### Deliverables
- Project creation with capability-gated `content_type` and `label_schema` selectors
- `ImageViewer.tsx` with lazy/async loading, per-project external-host consent, no-referrer requests, responsive sizing, and a hostname-safe broken-image fallback
- Image rendering in labeling and prediction review while category controls, scoring, and keyboard verification remain unchanged
- Image badges and captions in queue rows without exposing media URLs
- CSV/JSON image import with reserved `item_media_url`/`item_text` fields, row-indexed errors, 100-item authenticated chunks, and no anonymous report upload
- Project settings show editable modality before first item and locked modality afterward
- Mobile-responsive image queue and account-change cleanup of image consent/import state

### Files changed
- `frontend/src/api.ts`, `frontend/src/domain.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`
- `frontend/src/screens/Projects.tsx`, `frontend/src/screens/ProjectSettings.tsx`, `frontend/src/screens/Upload.tsx`
- `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/ReviewCard.tsx`
- `frontend/src/components/ImageViewer.tsx`, `frontend/src/components/CsvDropzone.tsx`, `frontend/src/components/PredictionReviewCard.tsx`
- `frontend/src/pages/PredictionReviewPage.tsx`, `frontend/src/pages/QuickstartPage.tsx`, `frontend/src/csv.ts`
- `frontend/dist/index.html`
- `tests/e2e/modality_image.spec.ts` (new), `tests/e2e/test_sprint0_extended.spec.ts` (real-PG render bounds)

**Verification:** PostgreSQL 306 passed with 16 experiment tests deselected; Playwright 181 passed; frontend TypeScript, E2E TypeScript, production frontend build, and backend mypy passed. MM-03 introduced no backend application changes. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

## MM-02 — Atomic Media Ingestion and Bounded Intake

**Date:** 2026-11-26
**Baseline:** PostgreSQL 289 passed, Playwright 172 passed.
**Post:** PostgreSQL 306 passed, 16 experiment tests deselected. Playwright 181 passed, including nine MM-03 tests added in the shared checkout.
**New tests:** 17 PostgreSQL, 0 Playwright.
**Closes:** G4 (admission and transport).

### Deliverables

- Media JSON routes enforce a 20 MiB transport limit before parsing. Two permits per worker bound large or unknown-length requests. A saturated worker returns 429 with Retry-After. Billing and anonymous reports retain their own intake policies.
- Image projects accept validated HTTPS references with signed bytes preserved. Inline JPEG, PNG, GIF and WebP require DLJ_INLINE_IMAGES_ENABLED and pass signature and base64 checks under the 10 MiB decoded per-request budget.
- Project and legacy imports, predictions, connector callbacks, content creation and revision paths enforce the selected project's policy. Atomic writes preserve source media, attribution and quota. Unenforced projects retain mixed-content support.
- Canonical aliases replay existing receipts. Frozen legacy digest fixtures cover text and opaque HTTPS. A changed image under the same key returns 409.
- With identical decision inputs, text and image scores, confidence, recommendations, factors and conservation status matched. The frozen jm_core.py SHA-256 was verified as 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
- Backend mypy, frontend TypeScript and the production frontend build passed.

### Files changed

- Backend: `media_intake.py` (new), `modality.py`, `jm_service.py`, `labeling_router.py`, `label_studio.py`.
- Tests: `tests/test_modality_ingest.py` (new). The existing project-switch scenario in `tests/harness/scenarios/test_s28_s32.py` checks the new project's HTTP response and its rendered rows.
- Shared frontend integration: `frontend/src/api.ts`, `frontend/src/components/ImageViewer.tsx`, `frontend/src/screens/ProjectSettings.tsx`, `frontend/dist/index.html`, and the project-card assertion in `tests/e2e/modality_image.spec.ts`.
- Handoff: `docs/session_state.md`.


## MM-04 — Image Export and IMG Gate

**Date:** 2026-11-26
**Baseline:** PG 306 passed (16 experiment tests deselected), PW 181 passed.
**Post:** PG 316 passed (16 experiment tests deselected), PW 181 passed.
**New tests:** 10 PG + 0 PW. One new pytest case drives Chromium against the real app and PostgreSQL.

### Deliverables

- Image JSONL includes `image_url`, with JSON null for a missing reference. Image CSV places `image_url` immediately after `text`, with an empty cell for a missing reference. Signed HTTPS references and embedded PNGs survived export byte-for-byte.
- The response headers `X-DLJ-Content-Type` and `X-DLJ-Label-Schema` report the project axes, with `mixed` for unenforced legacy projects. Both are exposed through CORS. Downloads retain `Cache-Control: no-store`.
- The repeatable-read export uses cursor pages of keys and byte lengths, reads large media individually, and enforces a 32 MiB encoded media export budget before sending the attachment. Current prediction and revision provenance are preserved. Legacy text JSONL, populated CSV, and the historical empty text CSV header retain their previous formats.
- The project CSV includes the original public IDs and scoring factors. A browser downloaded the CSV, re-imported it through the MM-03 upload screen into a second project, and verified the URLs, captions and factors by API readback. The queue identifies the project download separately from its page preview.
- All ten IMG gate cases passed, including score parity, inline PNG decoding, export cap and slot release, missing media, project isolation, prediction provenance and revisions. The conservation case exercised both the 10-verification warmup and the pause after 50 human decisions.
- Backend mypy, frontend TypeScript and the production build passed. The frozen `jm_core.py` SHA-256 remains `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

### Files changed

- `labeling_router.py`, `jm_service.py`
- `frontend/src/api.ts`, `frontend/src/csv.ts`, `frontend/src/screens/ScoredQueue.tsx`, `frontend/src/screens/Upload.tsx`, `frontend/dist/index.html`
- `tests/test_img_gate.py` (new), `tests/harness/scenarios/test_s28_s32.py` (S30 holds the actual browser response and sends each request once)
- `docs/session_state.md`


## Pre-Launch Sweep — Find All + Fix All

**Date:** 2026-11-26  
**Baseline:** PostgreSQL 316 passed, 16 experiment cases deselected. Playwright 178 passed and 3 failed out of 181. Frontend typecheck, build and backend mypy passed.  
**Post:** PostgreSQL 325 passed, 16 experiment cases deselected. Playwright 184 passed. Frontend and browser-spec TypeScript, the production frontend build and backend mypy passed.

### Findings summary

| Severity | Found | Fixed | Deferred |
|---|---:|---:|---:|
| P1 | 5 | 5 | 0 |
| P2 | 14 | 14 | 0 |
| P3 | 4 | 3 | 1 |

### P1 findings

| ID | Final file and line | Failure and correction |
|---|---|---|
| L01 | `media_intake.py:64` | A stalled body could hold a large-media permit indefinitely. A single monotonic 30-second deadline now covers reading the entire body. Expiry returns 408 and releases the permit. |
| L02 | `frontend/src/csv.ts:8`, `:83` | Browser imports could silently convert null or boolean factors to numbers and discard incompatible image annotations. Validate the original numeric values, reject conflicting aliases and validate the content type, spans and tags before normalization. |
| L03 | `frontend/src/screens/HealthReport.tsx:30`, `frontend/src/api.ts:442` | A PDF requested under a previous account could finish downloading after rotation. Invalidate the operation on account change or unmount, abort the fetch and check ownership before creating a download URL. |
| L04 | `frontend/src/components/ImageViewer.tsx:20` | Legacy review could contact a third-party image host before consent, and an old load/error event could affect a new source. Scope the viewer to project and source, require explicit consent, and clear it on account change. Embedded media stays local. |
| L05 | `jm_service.py:296`, `:322`, `requirements.txt:19` | Malformed input could be reflected in validation responses or captured in optional diagnostics. Keep field locations, types and actionable messages, omit raw inputs and contexts, and mark responses no-store. Disable sensitive Sentry collection of request bodies, headers, cookies, query data, database query data and frame variables. Validated SDK initialization locally without sending an event. |

### P2 findings

| ID | Final file and line | Failure and correction |
|---|---|---|
| L06 | `backend/static/dlj_client.py:26`, `:104` | The downloadable client could form an invalid batch from individually valid images or could only create legacy-style projects. Support explicit project axes and split uploads by item count, encoded JSON bytes and decoded image bytes. Preserve the replay key across retries. |
| L07 | `backend/static/dlj_client.py:171` | Large valid image CSV fields exceeded the Python CSV parser default, EOF handling could terminate parsing with a closed-stream error, and a filter could change format behind the parser. Handle all three and verify an actual large CSV download. CSV parsing raises the process-wide field limit to at least 32 MiB. |
| L08 | `db/repository.py:51` | Image webhooks omitted the media discriminator and authorized detail reference. Write both into the canonical event inside the label transaction. A legacy mixed project uses a scoped existence check. The event excludes the actual signed URL or inline bytes. |
| L09 | `jm_service.py:258`, `:460` | Incomplete Railway production configuration could first fail during a customer operation, and readiness could open or create an empty legacy database. Validate required settings, PostgreSQL and Fernet setup during startup. Probe the existing legacy tenant table read-only off the event loop. |
| L10 | `label_health/api.py:132` | A report upload using the wrong multipart field could leave temporary files open. Close the parsed form before returning 422. |
| L11 | `rate_limit.py:16`, `jm_service.py:347` | Public dynamic routes lacked consistent intake limits and clients could not inspect the applicable window. Apply distinct per-worker public budgets, report the actual SlowAPI window on decorated routes, and expose reset/retry headers through allowlisted CORS. Browser shell traffic has a separate budget from readiness probes and report generation. |
| L12 | `billing.py:95`, `auth.py:339`, `label_studio.py:44` | Paddle key rotation could reject a matching signature in a multi-signature header. Malformed non-ASCII credentials could cause comparison errors. Validate digest syntax, check each supplied signature against the original bytes, and compare admin/connector tokens as bytes. |
| L13 | `analytics_router.py:110`, `:155`, `:228`, `:282` | Analytics loaded full label records, including unused content, to count or aggregate them. Group distribution in PostgreSQL, stream projected columns for throughput and agreement, and restrict revision/prediction fields for confusion. Lifetime throughput still reads historical timestamps to preserve the defined averages. |
| L14 | `db/repository.py:136`, `:252`, `dashboard_router.py:41`, `labeling_router.py:446`, `:548` | Evidence recursion began outside the requested project and batch scoring repeated invariant lookups. Scope the recursive anchor, stream category evidence, reuse the locked domain and cache evidence within one batch and vocabulary. Engine persistence uses a version-checked update. For UUID writes, authorization identifies the owner directly and locks the actor and payer in sorted order. The import reuses its authorized domain and payer only inside the same HTTP request and transaction, and rechecks payer eligibility and quota on each reservation (`auth.py:223`, `db/entitlement.py:88`, `trial_guard.py:50`, `labeling_router.py:612`). The four-label regression counts exactly one payer-lock query and one evidence query and checks that the negative human outcome is retained. |
| L15 | `frontend/src/screens/Projects.tsx:25` | A capability request failure hid the list of accessible projects. Load the list and capabilities independently and retain the identity checks and recoverable error. |
| L16 | `tests/e2e/modality_image.spec.ts:69`, `tests/e2e/test_sprint0_extended.spec.ts:22`, `:102` | Real-database UI tests evaluated state before requests or failure notifications arrived. Synchronize the image queue, project and upload checks with the relevant responses, wait for the simulated lost request to fail, and allow canonical review detail to render. The replay test still compares both request bodies and counts committed rows. |
| L17 | `.github/workflows/harness.yml:37`, `.dockerignore:12`, `tests/harness/requirements.txt:3` | CI could pass without running the complete PostgreSQL and Node Playwright suites, and build context included local artifacts. Run both suites, install the browser and Python SDK test dependency, and exclude test data, browser results, experiments and local env files from the image context. SQLite remains advisory. |
| L18 | `projects_router.py:166`, `frontend/src/api.ts:537` | The chooser fetched all accessible projects and all modality-lock lookups in one response. Return 100 projects by default, cap pages at 200 and expose the next offset. Both browser choosers follow pages with the operation's original credential. Clients listing more than 100 projects must follow `X-Next-Offset`. |
| L19 | `rate_limit.py:40` | Personalized API responses using the custom API-key header lacked a consistent HTTP cache policy. Set private, no-store by default for API responses other than public health and preserve explicit stricter download policies. This applies with the limiter enabled or disabled. |

### P3 findings

| ID | Location | Disposition |
|---|---|---|
| L20 | `frontend/src/pages/GuidePage.tsx:32` | Fixed the image import, privacy, storage and export guidance to match the shipped behavior. |
| L21 | `scheduler.py:492` | Fixed the cleanup log unit. The counter measures expired keys. |
| L22 | `pyproject.toml:6`, `frontend/package.json:8` | Fixed two sources of misleading test-tool output. Register harness markers for standalone test discovery and use the project-pinned TypeScript compiler for browser-spec typechecking in CI. |
| L23 | Local test environment, `pytest_freezegun.py:17` | Deferred the external plugin's `distutils` deprecation warning. It comes from the installed pytest plugin and does not affect assertions or runtime code. |

### Coverage and verification

- The source inventory covered 34 backend Python modules, 47 frontend TypeScript/TSX files, 48 Python test/support files and 20 browser specs/support files at baseline. The runtime OpenAPI inventory contained 97 tagged operations. The PostgreSQL gate includes S1–S14 and S20–S32. Source checks included bare exception handlers, user-derived SQL, production console calls and candidate embedded secrets. Browser fixtures and external error sinks were reviewed separately.
- Reviewed the root-level FastAPI modules and the `db/`, `label_health/`, frontend, current `tests/`, browser suites and deployment configuration against the product and modality designs. The deployed Python implementation lives at repository root. Existing protected routes use tenant/project authorization. Public signup, guide, health, signed billing notifications and anonymous reports have their own entry contracts. The CORS allowlist contains the two product origins and two localhost origins.
- Reviewed query construction, parameter binding, commit/rollback boundaries, version checks, revision evidence, quota, and Paddle/webhook signing. HTTP contracts exercise signed bodies and duplicate delivery. No migration or DDL change in this sweep. The PostgreSQL gate includes fresh schema creation, repeated migration and preservation of seeded data (`tests/test_modality_schema.py:30`, `:67`, `:76`). No production database or live provider was contacted.
- Checked the export snapshot, cursor paging, capped temporary spool, CSV escaping, JSONL records, modality metadata and text/image compatibility. The IMG gate covers real CSV re-import, signed references, embedded media, revision lineage and conservation. Export rows are generated in bounded pages within a repeatable-read transaction and spooled to disk above 1 MiB before download. The media middleware retains its 20 MiB limit and two large-body permits.
- Verified scoped browser errors, account rotation, real upload/review flows, external image consent and fallback, mobile views, guide, quickstart and keyboard actions. Playwright includes both real PostgreSQL journeys and intercepted deterministic UI cases.
- Reviewed runtime and build inputs for embedded credential patterns, public error responses, provider diagnostics and readiness. The commit history and externally managed credentials are outside the source scan. The manual Paddle sandbox switch is present in `frontend/index.html:21`.
- Scoring measurement: 30 consecutive authenticated HTTP writes, after one warmup, on a disposable local PostgreSQL schema with connection pooling. The final quiet run measured 34.6 ms median, 46.5 ms p95 and 56.7 ms maximum. A run alongside regression tests measured 31.3, 42.7 and 46.8 ms respectively. An earlier pooled sample before the scoring changes measured 91.2 ms median and 150.0 ms p95. These are small-project loopback measurements. The engine SHA-256 is `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.
- Release boundaries: verify the Railway image smoke test, environment values, backup/restore and latency under expected production load at cutover. CI workflow edits were checked locally. Docker was unavailable here. The shared local environment uses different uvicorn, Pydantic, pytest, pytest-asyncio and NumPy patch/minor versions from the image pins. A metadata check found no incompatible direct pinned package pair. The exact image remains a deployment smoke check. The previously accepted legacy and historical migration items remain on the v1.1 ledger. Agreement matrices grow with annotator count and historical analytics still scale with the project. No production capacity result is inferred from local tests.

### Tests added

- `tests/test_prelaunch.py` (9 pytest cases): private validation fields, CORS and rate-window headers, project list pagination, intake deadline and permit release, scoped evidence and payer-lock query counts, Paddle signature rotation, missing production configuration, upload byte budgets, and a real SDK image export with an authenticated webhook reference.
- `e2e/fix_round6.spec.ts` (1) and `tests/e2e/modality_image.spec.ts` (2): stale report downloads, invalid image scoring evidence with independent queue readback, and project list pagination during a capability outage.

### Files changed

- **Production and client** — `jm_service.py`, `media_intake.py`, `rate_limit.py`, `analytics_router.py`, `auth.py`, `billing.py`, `dashboard_router.py`, `db/repository.py`, `db/entitlement.py`, `trial_guard.py`, `label_health/api.py`, `label_studio.py`, `labeling_router.py`, `projects_router.py`, `scheduler.py`, `backend/static/dlj_client.py`.
- **Frontend and generated bundle** — `frontend/src/api.ts`, `frontend/src/csv.ts`, `frontend/src/screens/Projects.tsx`, `frontend/src/screens/HealthReport.tsx`, `frontend/src/components/ImageViewer.tsx`, `frontend/src/pages/GuidePage.tsx`, `frontend/dist/index.html`.
- **Regression tests and harness** — `tests/test_prelaunch.py`, `e2e/fix_round6.spec.ts`, `e2e/components.spec.ts`, `e2e/tags_image.spec.ts`, `tests/e2e/modality_image.spec.ts`, `tests/e2e/test_sprint0_extended.spec.ts`, `tests/harness/conftest.py`.
- **Build, CI and documentation** — `.dockerignore`, `.github/workflows/harness.yml`, `requirements.txt`, `tests/harness/requirements.txt`, `pyproject.toml`, `frontend/package.json`, `docs/session_state.md`.

## G4 Verification Report

**Date:** 2026-11-26
**Verdict:** FAIL. A strict text import can commit and charge for a label after silently dropping submitted annotations. Three additional launch-contract checks also failed. Application code was left for the fixing prompt.
**Baseline:** PostgreSQL 325 passed, 16 experiments deselected. Playwright 184 passed.
**Post:** PostgreSQL 330 passed, 8 strict expected failures, 16 experiments deselected (exit 0). Playwright 184 passed (exit 0).
**Frozen engine:** `jm_core.py` SHA-256 `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

### Audit results

Counts in the last column are collected pytest cases, assigned once to their principal audit. “Gaps” counts distinct open findings. The design references are `docs/design/dlj_multimodal_design_v3.md:74` and `docs/design/dlj_product_design_v1.md:1024,1684,1829`. Production routers are at the repository root in this checkout.

| Audit | Items checked | Gaps found | Tests added |
|---|---|---:|---:|
| 1. Bounded intake | 5 checks, including installed dispatch and all 51 non-GET method/path registrations | 1 | 2 |
| 2. URL validation | 4 groups covering scheme, authority/characters/length, format and exact signed bytes | 1 | 2 |
| 3. Data URI validation | 3 groups covering grammar, individual/aggregate size and four signatures | 0 independent; connector timing counted under 4 | 1 |
| 4. Writer enforcement | 7 writer families including both connector adapters and prediction reopen | 3 | 5 |
| 5. Error safety | Validation responses and application diagnostic sinks | 1 | 2 |
| 6. No server fetch | HTTP/DNS call sites and image-reference data flow | 0 | 0; existing tests cover this |
| 7. Replay compatibility | Canonical identity and persisted legacy receipts | 0 | 1 |

### P1 findings

| ID | Evidence | Required result |
|---|---|---|
| G4-01 | `media_intake.py:15`, `labeling_router.py:2016`. The registered prediction review endpoint implements correction. An unsupported encoding reached downstream validation (422). The route misses the admission, size, encoding and read-deadline policy required for correction endpoints in this audit. Its DTO rejects replacement media. | A normal-sized unsupported-encoding correction receives the transport 415 before parsing. Apply the same applicable correction policy to both review and label relabel. |
| G4-02 | `labeling_router.py:139–171`, `modality.py:124–137`. On an enforced text/single project, submitting a nonempty flat tag list or span list returned 200. Each independent case read back one committed label and one quota charge. The flat fields disappeared before the shared validator ran. | Both cases return 422 with zero committed labels and zero quota charge. Keep valid legacy and typed representations compatible. |
| G4-03 | `labeling_router.py:2095–2126`. Prediction reopen creates a successor without the stored-layout check used by review at line 2032. With a deliberately missing persisted image-content row, reopen returned 200 and linked a new invalid successor. This requires an already inconsistent source. Ordinary reopen of a valid image preserves it. | Reject the inconsistent source before changing the prediction or predecessor. Verify the revision link remains unchanged in a fresh session. |
| G4-04 | `auth.py:183`, `label_studio.py:462–472,560–570`. Both mapped adapters rejected an over-budget image with the correct 413, **after five SQL statements** in each test. Config lookup and tenant locking precede validation, contrary to §4’s decoded-size-before-database rule. The test uses a small synthetic limit and counts statements without recording SQL or parameters. | Reject per-item/aggregate inline overflow before the first database statement. Keep the project-dependent mapping and layout checks under their normal authorization and locking rules. |

### P2 findings and coverage gaps

- **G4-05** — `labeling_router.py:957` includes the submitted category in the relabel 422. A synthetic private taxonomy value appeared verbatim in the response. Similar interpolations occur for stored categories at lines 711 and 777 and `label_studio.py:715`; factor names and task IDs occur at `label_studio.py:195,199,497,500`. Report a stable field description or index instead. The test establishes reflection to the requesting caller. It does not establish a cross-tenant leak.
- **G4-06** — `modality.py:61` removes every trailing dot when validating a hostname. It subsequently accepts the original spelling with an empty DNS label before the root. Preserve a single valid terminal root dot and reject multiple terminal dots. No DNS lookup was used for this test.
- Previously missing passing regressions now cover downstream exception/cancellation after a permit was acquired, external URL boundaries, multiple base64 decoder blocks, error paths with a signed-image canary and replay of an actual persisted pre-notes nested-image digest. The 30-second stalled-reader test already exists at `tests/test_prelaunch.py:67`.

### 1. Transport and registered routes

`jm_service.py:346` installs `MediaIntake` around the FastAPI router. Its receive loop completes before FastAPI’s body parser or `require_tenant` calls `request.json()` at `auth.py:179`. `media_intake.py:38–50` rejects unsupported encoding (415), malformed or multiple length declarations (400) and declared oversize (413). Lines 64–93 count each chunk before extending the buffer. The 20 MiB boundary is inclusive. Missing length reserves immediately; a small declaration crossing 1 MiB also requires a permit. A busy worker returns 429 with `Retry-After: 1`. The middleware replays only an accepted body to the router.

The prelaunch L01 change in the working tree (`media_intake.py:64–76`) establishes one monotonic 30-second deadline for the full receive loop. The file is untracked here, so a commit hash could not be attributed. Lines 52–62 register release immediately in an `ExitStack` around both receive and downstream dispatch. Normal completion, validation rejection, oversize, disconnect, scoring/DB exception, read timeout and coroutine cancellation unwind that stack. The deadline governs receipt of bytes. It does not time out database or scoring work. Existing end-to-end tests cover declared/observed oversize, chunked input with no length, saturation, cancellation, deadline and retry (`tests/test_modality_ingest.py:67–145`, `tests/test_prelaunch.py:67`).

The ledger below groups all 51 registered non-GET method/path pairs. Paths share the prefix `/v1`. Braces within an alternatives list denote separate registered routes. All GETs bypass this POST-only middleware.

| Count | Method and actual routes | Media intake |
|---:|---|---|
| 2 | POST `/labels/ingest`, `/labels/ingest/batch` | Covered |
| 2 | POST `/projects/{p}/labels`, `/projects/{p}/labels/batch` | Covered |
| 4 | POST `/labels/{p}/items/{l}/{relabel,content}` and `/projects/{p}/labels/items/{l}/{relabel,content}` | Covered |
| 1 | POST `/projects/{p}/predictions` | Covered; this is batch import. There is no registered `/predictions/batch`. |
| 2 | POST `/label-studio/{predict,webhook}` | Covered; the webhook is the connector callback. |
| 2 | POST `/projects/{p}/predictions/{id}/{review,reopen}` | Both excluded. Review supports correction (G4-01). Reopen accepts revision identity and reuses stored content (G4-03). |
| 8 | POST `/labels/verify`, `/labels/{p}/{bulk-verify,sample,tasks}`, `/projects/{p}/labels/{verify,bulk-verify,sample,tasks}` | Excluded; evidence, text-only task or synthetic sample |
| 3 | POST `/label-health/{analyze,report,report/pdf}` | Excluded; separate bounded multipart reader at `label_health/api.py:127` |
| 2 | PUT `/projects/{p}/guidelines`, `/domains/{p}/guidelines` | Excluded; text settings |
| 2 | POST `/label-studio/{configure,setup}` | Excluded; connector configuration |
| 7 | POST `/admin/api-keys`, `/admin/api-keys/{k}/{rotate,reconcile-signup-owner}`, `/auth/{register,confirm}`, `/account/domains/resolve`, `/billing/webhook` | Excluded; identity/account policies and independent Paddle stream at `billing.py:383` |
| 7 | POST `/projects`; PATCH/DELETE `/projects/{p}`; PUT `/projects/{p}/settings`; POST `/projects/{p}/{members,invites}`, `/projects/{p}/invites/{i}/accept` | Excluded; project administration |
| 5 | POST `/projects/{p}/webhooks`; PATCH/DELETE `/projects/{p}/webhooks/{e}`; POST `/projects/{p}/webhooks/{e}/{rotate,test}` | Excluded; outbound webhook configuration and dispatch |
| 4 | POST `/register`, `/domains`, `/domains/{p}/{score,learn}` | Excluded; separate legacy JM API |

### 2–3. URL and inline validation

| Check | Code and observed behavior |
|---|---|
| External scheme and authority | `modality.py:43–67` requires HTTPS, hostname and valid port, rejects userinfo and invalid authority. HTTP, FTP, file, JavaScript and data references are rejected by the external URL function. `labeling_router.py:123–128` deliberately dispatches valid image data URIs to a separate validator. G4-06 qualifies the hostname result. |
| Characters and length | `modality.py:46–48` checks 1–2,048 characters, whitespace, Unicode controls, backslashes and fragments before parsing. Tests cover both the exact length and one beyond it. |
| Strict format and original bytes | `modality.py:68–74` accepts case-insensitive JPG/JPEG/PNG/WebP/GIF suffixes and exact decoded format hints (`format`, `fm`, or §4’s `response-content-type`). PDF/SVG/HTML without a permitted hint are rejected. Opaque HTTPS is allowed on legacy projects. Validation returns the original string including query order, duplicates and percent-escape spelling. |
| Inline grammar and size | `modality.py:35–40,77–104` requires a supported image prefix and canonical standard base64, rejects SVG, parameters, whitespace and bad padding. Encoded size is checked against 13,981,016 before decode. Decode uses 65,536-character blocks, followed by the independent 10,485,760-byte decoded limit. `labeling_router.py:131–136,287–309` computes the request-wide total on normalized content. `modality.py:138–146` gates new embedded writes on `DLJ_INLINE_IMAGES_ENABLED`; the replay check precedes that policy, so historical receipts remain readable. Connector ordering is G4-04. |
| Magic bytes | `modality.py:39–40,105–112` checks JPEG FF D8, full eight-byte PNG signature, GIF87a or GIF89a, or RIFF plus WEBP at offset 8. MIME mismatch fails. This establishes signature matching, not successful image rendering. |

### 4. Writers and persisted media

| Writer | Shared check and transaction effect |
|---|---|
| Project import, legacy ingest and their batch routes | `labeling_router.py:608,639,662,810,2215` → `prepare_content:475` → `validate_media_for_project:479`. Project batch preflights every normalized item before the score loop. `_ingest:548` performs the scored write and persists structured content at line 565. Enforced text rejects image, enforced image requires it. G4-02 identifies input lost ahead of preflight. |
| Prediction import | `labeling_router.py:1914–1954` uses batch syntax/aggregate validation and shared content preparation before scoring. The original revision carries the image. For embedded data the prediction snapshot stores the original-content reference and digest; detail reconstructs it at line 1205. |
| Connector predict and webhook | `label_studio.py:212,221–247,460–495,536,627–650` maps into the shared content type, validates new writes through shared preparation, and checks stored layout/source equality for bound writes. Existing-source reassignment gets 409. G4-04 concerns when the decoded bound runs. |
| Relabel and prediction correction/reopen | `labeling_router.py:361–367,958–987,1057,2032,2057` rejects supplied replacement media, checks compatible edits and stored layout, and copies the source into the successor. `db/repository.py:224–228` copies discriminator, spans, tags and exact URL. Reopen’s source check is missing (G4-03). |
| Single and bulk verification | `labeling_router.py:689,738,801` checks the existing layout on single verify; bulk delegates to it. Ordinary verification updates evidence in place. The connector relearn successor copies content at `db/repository.py:386`. |
| Typed content creation | `labeling_router.py:1134,1146–1175` calls the shared project validator and the per-discriminator checks before persisting. |
| Synthetic sample and text task | `labeling_router.py:853,899` explicitly call the shared validator with no image. These text-only writers refuse a strict image project. |

### 5–7. Diagnostics, external loading and receipts

- **Diagnostic sinks.** The FastAPI handler (`jm_service.py:321–325`) projects validation errors to location, type and message; the optional Sentry configuration at line 296 disables private data capture. SQLAlchemy hides parameter values and the DB exception formatter selects trusted metadata (`db/connection.py:53,80,93,121`). Batch warnings record index and exception class (`labeling_router.py:828,834`). One synthetic signed URL was submitted across nine invalid/conflicting request cases covering 400, 401, 409, 413, 415 and 422. Its private query marker was absent from all nine responses and captured INFO-and-higher logs. G4-05 is a separate hand-built error, outside the global validation handler. No external telemetry service was exercised.
- **Server fetch.** The model stores the reference in `LabelContent.image_url` (`db/models.py:124`). URL splitting and caption derivation in `modality.py:43,115` are local. Connector task lookup and equality comparison use stored values. `db/repository.py:216,224` persists/copies content. `labeling_router.py:1205,1219,1560,1684,1704,1800,1953,2159` resolves, emits, counts or omits the stored reference. `db/repository.py:62–65` emits a media indicator and an authenticated reference for events. There is no image dereference in these paths. The actual network clients handle Paddle (`billing.py:169`), email (`email_service.py:17`) and distinct configured webhook destinations (`scheduler.py:155–176`, `webhook_security.py:79`). The existing test at `tests/test_modality_ingest.py:147` guards DNS lookup of its fixture image host. The previous consent finding was browser-side: `frontend/src/components/ImageViewer.tsx:27–49` renders remote images after consent and sets no-referrer and lazy loading.
- **Receipts.** `labeling_router.py:592–604,625–639` hashes normalized compact sorted JSON before caption generation. Project, actor, operation and request key scope the lookup. Old-receipt fallback removes the later notes field only for inputs representable by the old serializer. It retains original nested media. The frozen no-content and opaque-HTTPS vectors live in `tests/test_modality_ingest.py:198,306`; strict image identity and mismatch are covered at lines 336 and 351. A new test seeds the historical nested-image digest, obtains the stored result through the flat alias, then gets 409 for changed image bytes under that key. Independent SQL readback finds the original URL and exactly one charge.

### Tests added and gate decision

`tests/test_g4_verification.py` adds 11 functions, 13 collected cases. Five pass. Eight assertions cover the six open findings. They are strict expected failures restricted to the specific contract-mismatch exception. Setup errors remain ordinary failures, and an unexpected pass makes the suite fail until the mark is removed.

| Test | Evidence |
|---|---|
| `test_permit_after_downstream_exit` | Holds the other permit, exercises scoring/DB exceptions, rejection and cancellation after the final receive, then proves another dispatch succeeds. |
| `test_prediction_correction_has_intake_policy` | Checks the registered correction route through the real middleware with a small encoding-policy request. |
| `test_external_reference_contract` | Scheme, suffix cases, inclusive length, controls and exact signed bytes. |
| `test_image_reference_requires_valid_hostname` | Distinguishes a legal rooted DNS name from an empty trailing label. |
| `test_inline_reference_signatures` | All four media signatures across multiple decode blocks and invalid parameter/whitespace/container cases. |
| `test_text_single_rejects_incompatible_annotation` (2) | Checks HTTP status, rows and usage after incompatible tags or spans. |
| `test_reopen_checks_existing_image_layout` | Checks rejection and absence of a successor for an explicitly inconsistent stored image. |
| `test_connector_inline_size_before_database` (2) | Counts statements before a mapped image is rejected through predict or webhook. |
| `test_media_error_responses_and_logs` | Signed-image query canary across transport, auth, typed validation, conflict and private-media replacement errors. |
| `test_relabel_diagnostic_uses_field_metadata` | Distinguishes naming an invalid category field from returning its submitted private value. |
| `test_old_nested_receipt_cannot_authorize_replacement` | Real legacy receipt, equivalent current alias, changed media conflict and persisted usage. |

**Browser run history.** Two intermediate full runs overlapped PostgreSQL testing and finished with 183/184 and 182/184. The SLA badge assertion timed out on the first run. The second timed out on the annotators screen and on the labeling journey’s accuracy display. The SLA test passed on its own, and the complete two-worker Playwright suite passed 184/184 after PostgreSQL testing finished. No browser test was edited or disabled.

**Conclusion:** G4 fails the specified launch contracts. Running `python -m pytest tests/test_g4_verification.py -m xfail --runxfail -q --timeout=120` produced **8 failures, 5 deselected**. The default regression suite result includes those documented expected failures. Reopen the gate when the four P1s pass without expected-failure marks and the two P2s have been resolved or explicitly accepted.

## G4 Fix — Four P1 Blockers + Two P2s

**Date:** 2026-11-26

**Baseline:** PostgreSQL 330 passed, 8 expected failures, 16 experiment cases deselected. Playwright 184 passed.

**Post:** PostgreSQL 344 passed, 0 expected failures, 16 experiment cases deselected. Playwright 184 passed.

### P1 fixes

1. Strict imports retain the presence of nonempty flat tags and spans through parsing. A strict text/single project returns 422 before scoring or charging. Label and prediction imports also check before returning a cached receipt. Legacy digest serialization and valid typed annotation formats are preserved.
2. The ASGI media-intake route matcher now includes prediction review/correction. Unsupported content encoding returns 415 before FastAPI validation; the same size, permit and read-deadline rules as label relabel apply.
3. Prediction review and reopen validate the locked source revision before creating a successor. Missing image content, an invalid URL or malformed inline media returns 409. The successor copies the validated source, and existing inline media remains reviewable after new inline imports are disabled.
4. Connector predict and webhook authenticate the connector token, then validate embedded image syntax, signatures and individual/aggregate decoded size before tenant or mapping SQL. Since field names are configurable, all embedded image values in the JSON envelope count toward the request budget. Project policy and source binding still use the authorized mapping under lock. All four connector budget cases observed zero database statements.

### P2 fixes

5. Relabel, verify and connector errors identify the invalid category without returning its value. Related connector diagnostics omit raw task and factor names.
6. HTTPS hostname validation accepts a single DNS root dot and rejects an empty label caused by additional trailing dots. The stored URL retains its original spelling.

### G4 verdict

**PASS.** All eight former expected failures pass as ordinary tests. The focused module passed all 19 cases, including six additional checks for aggregate budgets, corrupted source references and receipt replays. Backend mypy and frontend TypeScript passed. The frozen `jm_core.py` SHA-256 is `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.

During an overlapping run, PostgreSQL pytest finished with 343 passed and one browser queue-navigation failure. Playwright finished with 182 passed and two timeouts in the sample-queue and throughput-chart tests. The queue-navigation test passed individually. Both full suites then passed when run sequentially with the same settings.

### Files changed

- Application: `labeling_router.py`, `modality.py`, `media_intake.py`, `label_studio.py`, `db/repository.py`.
- Regression tests: `tests/test_g4_verification.py`, `tests/test_modality_ingest.py`, `test_validation_fixes.py`.
- Session record: `docs/session_state.md`.

## Prompt 12 — Release Gate

**Date:** 27 November 2026
**Decision:** NO-GO. The authenticated scoring latency exceeds both local release limits.
**Baseline:** PostgreSQL 344 passed, 16 experiments deselected. Playwright 184 passed.
**Final:** PostgreSQL 17: 360 passed, 16 experiments deselected, including all 27 design scenarios and 16 release tests. Playwright: 196 passed in 6.5 minutes, including eight new spot tests and four new journeys. The browser suite passed after moving login and readiness into the page fixture so each spec gets the same setup. Both specs explicitly set their intended time budget.

### Part A — Findings and fixes

| Severity | Location | Finding and disposition |
|---|---|---|
| P1 | billing.py, paddle_transaction_url | An unrecognized sandbox flag selected the live transaction endpoint. Only explicit true/false values are accepted. A configuration error stops checkout before an intent is written. |
| P1 | jm_service.py, validate_production_config; docker-entrypoint.sh | An ENVIRONMENT-only production deployment skipped preflight. A malformed or incomplete price map could pass startup, and migration ran before configuration validation. Production now validates the four advertised tiers, mode, required settings, database and Fernet key before migration. |
| P1 | docker-entrypoint.sh; rate_limit.py, RateLimitHeaders | The default Uvicorn access line could record private searches in request targets. Deployed access events use a static route template and status. The raw access logger is disabled for the image. |
| P1 | db/tenant_lock.py:9, labeling_router.py:473, db/repository.py:254 | Existing PostgreSQL guard rows now take a single locking read. First creation still handles competing writers. The evidence query reuses a parameterized statement and reads current transaction data. The final native benchmark still exceeds both thresholds; this P1 is open. |
| P2 | jm_service.py, health | Pool exhaustion could outlast the container health deadline without a response. PostgreSQL readiness now returns a bounded 503 and recovers on the next successful probe. |
| P2 | frontend/src/screens/ScoredQueue.tsx | The full-project CSV button was hidden for text projects. Eligible reviewers can now download either modality. The image-specific notice remains scoped to image projects. |
| P2 | projects_router.py, list_projects | Membership role was missing from the summary used by the queue. The listing now returns the active role in the same query. The UI positively checks export eligibility and the API enforces it independently. |
| P2 | frontend/src/App.tsx, domain.tsx and screens/Projects.tsx | The directory performed a second paginated project fetch and could show a blank list during loading. The directory and sidebar share the account-scoped result, refresh on directory entry, and expose loading, empty and retry states. |
| P2 | account.py, domains; frontend/src/api.ts | Account Settings fetched an unbounded ORM result, including unused columns. Pages now default to 100 rows, cap at 200, and return X-Next-Offset. The client follows every page with the original credential and abort signal. |
| P2 | e2e/fix_round3.spec.ts, fix_state.spec.ts, ner_editor.spec.ts and tags_image.spec.ts | Four browser specifications could silently target port 8080 during a candidate run. They inherit the configured target and retain the explicit editor-specific overrides. |
| P2 | tests/e2e/modality_image.spec.ts | The pagination regression depended on another test having already created a project. It now creates both projects and waits for the actual final page before checking the result. |
| P2 | e2e/screens.spec.ts:43 and tests/e2e/release_flows.spec.ts | A fixed delay for the initial redirect and immediate assertions on asynchronous imports, detail reads and settings reloads produced false failures while the page was still loading. The checks now wait for the redirect or the scoped real HTTP response, then assert the rendered state. |
| P2 | tests/sprint0_browser_server.py:26 and tests/e2e/test_sprint0_extended.spec.ts:19 | The browser fixture used a separate health engine and opened a database connection for each operation on a single event loop. Readiness and business operations now share one isolated pool. Its worker setup has its own bounded startup budget, independent of feature assertions. |
| P3 | .dockerignore and Dockerfile | Root experiment and demo modules were included by the image copy. They are excluded from the build context, and an obsolete cache-bust comment was removed. |

Four P1 findings received changes. Three closed; scoring latency remains open. All nine P2 findings and the Docker packaging P3 were fixed. The browser test fixes also removed an import-order dependency in the release login fixture.

### Part B — Tests added

- 16 backend cases in tests/test_release_gate.py cover text and image signup through verification, signed payment notifications, minute and daily limits, streamed export, schema constraints and repeat migration, checkout configuration, SPA assets, export roles, tenant-scoped pagination, readiness, pool recovery, private access logs and production preflight.
- Eight browser spot checks and four multi-step journeys run against real API and PostgreSQL fixtures. The flows cover text CSV through review and export, embedded PNG through rendering and export, prediction acceptance and the project modality lock.
- Signup tests deliver actual messages to a private test Maildir. Successful provider checkout and delivery to a real inbox require sandbox/provider credentials. The opt-in checkout check reads the actual Paddle transaction and compares its price ID. Production checkout links are opaque transaction links.

### Part C — Release verification

- The 27 design scenarios plus two additional signup cases passed during the sweep. S4 also passed after restoring its existing database injection path.
- Mypy passed on the changed Python modules, including the release and Sprint 0 runners. The frontend production build and TypeScript checks passed.
- The Dockerfile, .dockerignore, Railway health path, entrypoint shell syntax, frontend bundle and downloadable client were checked. Docker and Podman were unavailable locally. Staging must build, boot and smoke-test the exact image.
- PostgreSQL migrations were rehearsed on an empty schema and a populated disposable schema. Checks include primary/foreign keys, named checks, uniques, indexes and retained rows. Rollback and restoration of a Railway backup are separate operator checks.
- The IMG gate and G4 cover bounded admission, connector pre-SQL rejection, strict text annotations, correction/reopen, media preservation, modality locking and export. The browser flows exercise real image decoding and text/image CSV downloads.
- The final 30 authenticated writes measured 153.45 ms median and 271.34 ms p95 against limits of 50 and 100 ms. Earlier native runs measured 166.69/335.02 and 268.97/638.78 ms. The earlier WSL measurement of 49.76/68.48 ms was on an intermediate candidate.
- Standalone confirmation on 27 November: two consecutive runs of `python -m tests.release_server --measure` used a disposable local PostgreSQL 17 instance. Each verified 30 timed writes after one warmup. Run 1 measured 153.09 ms median and 266.41 ms p95 (3,878 MiB available, 27% CPU before the run). Run 2 measured 151.51 ms median and 254.06 ms p95 (3,795 MiB available, 43% CPU before the run). Both prechecks found zero browser processes and zero competing test runners. Norton remained enabled. Both runs exceeded both limits.
- Norton quarantined the temporary timing helpers `p12_time_breakdown.py` and `dlj-p12-time-signoff.py` under `IDP.Generic` at 03:42:16 and 04:39:02 Pacific, respectively. The quarantine metadata gives no specific triggering operation. The normal benchmark completed before the second helper was quarantined. No fine-grained timing result was produced; both helpers were left in quarantine.
- Engine SHA-256: 1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09.
- Risks: [accepted_risks.md](quality/accepted_risks.md). Configuration, cutover and rollback: [release_checklist.md](quality/release_checklist.md).
- The 120-second Windows browser-fixture teardown timeout cleared on the successful full PostgreSQL run after process cleanup. The full browser rerun passed with the corrected shared login fixture. Release performance remains unverified on Railway. No production deployment was performed.

### Manual steps remaining

1. Take and restore-test the Railway and legacy-volume backups. Record the previous image and schema.
2. Install the persistent WEBHOOK_ENCRYPTION_KEY and other required secrets before starting the candidate.
3. Build and deploy the candidate to staging, then perform the provider, migration and latency smoke checks.
4. Coordinate the live PADDLE_SANDBOX=false switch, matching provider credentials and price map with the manual frontend sandbox-line removal, reviewed push and image deployment.
5. Enable DLJ_IMAGE_PROJECTS_ENABLED and verify capabilities and external-image review.
6. Enable DLJ_INLINE_IMAGES_ENABLED after the staging intake/export memory check.
7. Complete production health, checkout, delivery, isolation and data readbacks; take the post-deployment backup.

### Files changed

- Service and packaging: .dockerignore, Dockerfile, docker-entrypoint.sh, account.py, billing.py, db/repository.py, db/tenant_lock.py, jm_service.py, labeling_router.py, projects_router.py, rate_limit.py.
- Frontend: frontend/src/App.tsx, frontend/src/api.ts, frontend/src/domain.tsx, frontend/src/screens/Projects.tsx, frontend/src/screens/ScoredQueue.tsx.
- Tests: tests/test_release_gate.py, tests/release_server.py, tests/harness/fixtures/pg_schema.py, tests/e2e/release_fixture.ts, tests/e2e/release_spot.spec.ts, tests/e2e/release_flows.spec.ts, tests/e2e/modality_image.spec.ts, e2e/fix_round3.spec.ts, e2e/fix_state.spec.ts, e2e/ner_editor.spec.ts, e2e/tags_image.spec.ts.
- Browser regression fixes also touched e2e/screens.spec.ts, tests/sprint0_browser_server.py and tests/e2e/test_sprint0_extended.spec.ts.
- Operations: docs/quality/accepted_risks.md, docs/quality/release_checklist.md, docs/session_state.md.

## Prompt 12d — Scoring Latency Fix

**Date:** 27 November 2026
**Baseline latency:** 153 ms median / 271 ms p95 (previous release sign-off measurement).
**Post-fix latency:** 146.47 ms median / 300.61 ms p95, 30 committed writes after one warmup on native Windows PostgreSQL 17.
**Budget:** <50 ms median / <100 ms p95.
**Verdict:** FAIL. Functional verification passed. Scoring latency remains the launch blocker.

### Diagnostic findings

The benchmark is `python -m tests.release_server --measure`. It warms up once, sends 30 sequential authenticated one-item batches over loopback HTTP and checks that all 31 rows are pending. The signup-to-score pytest case additionally creates a schema, authenticates a user, verifies a label, reads its SLA and tears down the schema. The SQL counts below isolate the scoring transaction.

| Measurement | Original candidate | Revised candidate |
|---|---:|---:|
| Application SQL statements per warm write | 13 | 11 |
| Transaction control | one BEGIN and one COMMIT | one BEGIN and one COMMIT |
| Sum of mean PostgreSQL execution times for application statements | 3.16 ms | 2.96 ms |

The original transaction authenticated the active key, discovered the project, locked its tenant guard, read the billing binding, locked and revalidated the actor and payer in UUID order, re-read and locked the project, checked the replay receipt, loaded the engine, updated quota, inserted the label, updated the versioned engine, streamed revision-aware evidence and inserted the receipt. COMMIT preceded the response. The revised path combines project discovery with the guard lock and billing binding lookup with the sorted key locks. Credential reads on either side of locking serve distinct purposes. On first engine creation the repository rechecks the domain and engine. A newly used pooled connection can add three asyncpg type-discovery statements.

The call chain is `MediaIntake` → `require_tenant` (body validation and key digest lookup) → `require_project_tenant` / `resolve_entitlement` → `project_import_batch` (replay digest and modality validation) → `_ingest`. Ingest awaits `_prepare_engine`, quota reservation, `score_and_persist` and `_category_stats`. Engine scoring, state serialization and tier evaluation run in process. The handler adds the replay receipt and awaits `commit_write`. The benchmark uses no named annotator or typed content.

Native PostgreSQL 17 statement statistics and parameter-suppressed transaction logs measured the five most expensive original application statements at 1.030 ms for the label insert, 0.930 ms for the receipt insert, 0.178 ms for quota update, 0.167 ms for engine update and 0.147 ms for the evidence query. With statement logging on, the original HTTP median was 168.85 ms, about 165.7 ms above the sum of SQL means. Across 30 warm requests the median transaction span was 86 ms, with 7.30 ms median cumulative server parse, bind, execute and transaction-control time. Backend IDs confirmed connection pooling. PostgreSQL JIT was unavailable in this build.

HTTP client events correlated to the database log gave medians of 42.5 ms from sending the request body to BEGIN, 83 ms from BEGIN to COMMIT, 25 ms from COMMIT to client response headers and 2.5 ms from headers to body completion. One slow write had a 187 ms gap between the label insert and engine update. Phase medians are independent. A second diagnostic used the existing client workload with a separate native Uvicorn process. It measured 144.48 ms median and 202.75 ms p95. Its 11 SQL means summed to 2.96 ms, about 141.5 ms below the HTTP median. ASGI and PostgreSQL timestamps gave medians of 19.5 ms from ASGI start to receipt of the body, 6 ms from receipt to BEGIN, 64.5 ms from BEGIN to COMMIT and 1.5 ms from COMMIT to the first ASGI send.

With Chrome closed, the High performance plan measured 156.56/316.75 ms. Available memory stayed at or above 5,017 MiB and the Windows CPU performance counter averaged 23.2% of nominal during the benchmark process. The Balanced control measured 153.81/324.09 ms. Balanced was restored and the temporary scheme removed. Norton remained enabled. An explicit TCP listener and the pinned Uvicorn version also missed the budget. The release benchmark source was restored after the listener experiment.

The measured bottleneck is elapsed time outside SQL execution, including intervals between database calls and across HTTP processing. The traces do not identify a single host component or prove that Prompt 12a introduced the historical difference. Local Git refs, stash, worktrees and editor history did not yield the pre-12a scoring build. The 34.6/46.5 ms historical result lacks a comparable phase trace.

### Fixes applied

- `auth.py` discovers the project UUID and locks an existing owner tenant guard in one query. The guard subquery is restricted to the authenticated tenant. Missing guards and member writes follow their original locking paths. The project is re-read under lock after the keys.
- `db/entitlement.py` resolves an established billing binding and locks its actor/payer keys together in UUID order. The shared eligibility check and legacy single-candidate validation remain active. The query leads with the key table so the existing payer-lock regression check continues to observe the lock.

### Verification

- PostgreSQL: 360 passed, 16 experiment tests deselected. All 27 required scenario IDs passed (29 scenario-file cases).
- Playwright: 196 passed in 7.0 minutes. PostgreSQL, Playwright and the final benchmark ran sequentially.
- Both changed Python modules passed mypy. The unchanged evidence/payer-lock test and signup-to-score test passed individually. The complete suite covered authorization, quota, replay, revision evidence and commit-before-response.
- Frozen engine SHA-256: `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`.
- Files changed for 12d: `auth.py`, `db/entitlement.py`, `docs/session_state.md`.
