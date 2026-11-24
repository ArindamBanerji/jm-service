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
