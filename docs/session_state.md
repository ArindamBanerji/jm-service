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
