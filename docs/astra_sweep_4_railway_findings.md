# Railway deployment readiness

**2026-11-21 · BLOCKED for the first public deployment.** A Git deployment of the current revision cannot assemble the service. The working tree contains the application, but the Git tree omits required Docker build inputs. The clean Linux image, managed PostgreSQL connection and persistent volume still need a staging run. Public anonymous report generation also needs resource limits.

**Scope.** The audit covers the frozen core, factors, policy, labeling and dashboard routes, connector, authentication, persistence, report pipeline, frontend serving, smoke client and deployment files. The requested eight suites passed **161/161** in 59.03 seconds on Windows with 322 pytest-freezegun deprecation warnings. The working-tree engine SHA-256 matched `1922316f0998df0d071318c8a82192c880890ff9dddfa62bf399f02f04469e09`. Local FastAPI was 0.163.1 and Pydantic 2.14.2. The image pins 0.115.6 and 2.10.4 respectively.

**Pre-check.** LBL-DEPLOY-1 is recorded as **FAILED**. The previous HTTP smoke passed 9/9 twice with SQLite and the Windows ReportLab fallback. Docker and Podman were still unavailable on the Windows PATH and in Ubuntu WSL during this sweep. LBL-SWEEP3-FIX records tenant scoping, review-domain binding, score capping and scoped annotation revisions. Its remaining limits include missing source annotation on the review card, retained prior centroid movement and unverified live Label Studio registration. Keep those product acceptance checks open.

| Area | Verdict | Action before release |
|---|---|---|
| 1. Database URL | WARNING, blocking for URLs with libpq-style TLS options | Bind the PG service variable and validate TLS on the actual endpoint. |
| 2. Port | CLEAR | Use the image entrypoint and Railway-injected port. |
| 3. Filesystem | BLOCKER for durable legacy and connector data until storage is provisioned | Attach and verify a writable volume at `/data`. |
| 4. Migrations | WARNING | Bound connection attempts and serialize migrations across concurrent starts. |
| 5. Health timing | WARNING | Measure first 200 on staging with the real database and mounted volume. |
| 6. Connections | WARNING | Budget connections per process and bound dashboard history reads. |
| 7. Frontend serving | CLEAR in working tree | Exercise both root and hash navigation from the release image. |
| 8. Build | BLOCKER | Assemble the complete Git revision and build it from a clean checkout. |
| 9. Railway configuration | WARNING | Set private DB reference, credentials, volume and shutdown window. |
| 10. Public exposure | BLOCKER for unrestricted anonymous reports | Bound anonymous traffic and rendering capacity. Sanitize batch errors. |

### 1. Database URL and TLS

Loaded `db/connection.py` with each requested synthetic URL. Both `postgresql://` and `postgres://` became `postgresql+asyncpg://`, retaining user info, host, port and database. An explicit asyncpg URL and `sqlite+aiosqlite:///test.db` passed through unchanged. The Python search found one runtime reader of DATABASE_URL. Both `db/migrate.py` and `jm_service.py` import that engine. Configure the API service with a reference to the PostgreSQL service's URL. The localhost default points back into the API container if that reference is missing. [Railway PostgreSQL connection guidance](https://docs.railway.com/databases/postgresql)

SQLAlchemy 2.0.45 passed the query options through to asyncpg 0.32.0. Binding the resulting arguments to the actual driver signature raised `unexpected keyword argument 'sslmode'` for `?sslmode=require`. The same probe accepted `?ssl=require`. A deployment using the former fails during migration. Use the supported SSL option or translate it at engine creation. Where certificate and hostname verification are required, use a trusted CA and verifying SSL context or supported verify-full configuration. Signature acceptance tests argument compatibility only. Establish a real connection over the selected private DNS or public endpoint and verify TLS on the server before release. Railway's template supports SSL. Private DNS alone establishes no encryption policy.

### 2. Port and host

`docker-entrypoint.sh` uses `exec uvicorn ... --host 0.0.0.0 --port "${PORT:-8000}"`. The image HEALTHCHECK reads the same variable. Localhost in that probe correctly addresses the app in its own container. Python references to port 8000 were in smoke, deployment and live-test clients. The service does not import them. `test_smoke.py` supports `SMOKE_BASE_URL` for a staging HTTPS origin. Running `jm_service.py` directly selects 8100, so preserve the Docker entrypoint. Compose's fixed 8000 probe and `postgres` hostname belong to the local compose stack.

### 3. Ephemeral writes and persistent state

`label_health/api.py` reads multipart uploads with a 10 MiB application limit, parses bytes with pandas and creates an ephemeral engine. Framework multipart parsing can spool a large upload to temporary disk **before** the handler checks its size. `label_health/render.py` returns HTML and PDF bytes, using an in-memory buffer for its fallback. No application report file needs to survive a deployment. Core scoring, policy and factor calculation operate in memory. Core export and restore exchange dictionaries. The repository persists engine JSON, labels and annotators in PostgreSQL, and `auth.py` stores tenant key hashes there.

`jm_service.py` writes legacy tenant credentials, decisions and domain state to `JM_DB_PATH`. `label_studio.py` writes mapping JSON via a sibling temporary file and rename. Its default depends on whether `/data` exists, otherwise it writes in the working directory. Set explicit paths under a Railway volume, verify ownership and permissions, then configure a mapping, redeploy and confirm both mapping and legacy state survive. The Docker VOLUME declaration and Compose named volumes alone do not configure the Railway attachment. The JSON lock is process-local. Use one writer or move mappings to PostgreSQL before scaling. [Railway volume reference](https://docs.railway.com/volumes/reference)

### 4. Migration and restart

`docker-entrypoint.sh` runs the shared migration before Uvicorn. Any nonzero migration exit triggers the loop, including refused connections and invalid credentials. Five immediate failures incur four two-second sleeps. Invalid credentials require correcting the service variable. A slow driver connection can consume substantially longer than eight seconds. The entrypoint leaves diagnostic stderr available.

`db/migrate.py` inspects tables and columns, adds missing fields and indexes, calls metadata.create_all in a transaction, then disposes its engine. Two consecutive invocations on the same scratch SQLite DB succeeded here. Sweep 3 and its fix record sequential success on disposable PostgreSQL 17. Concurrent startups can race between inspection and DDL. Existing schema changes outside the enumerated upgrades need versioned migrations. Run schema upgrades once per rollout or take a database migration lock. A Uvicorn startup failure after commit exits the process. A restart under ON_FAILURE reruns migration, subject to Railway retry limits.

### 5. First healthy response

On this Windows host with fresh SQLite and no Label Studio token, migration took **1.42 s** and spawning Uvicorn through first healthy HTTP response took **5.77 s** on a nondefault port. A separate repeat migration took 1.22 s. About **7.2 s** is a local one-migration estimate. It excludes image build, managed DB readiness and Railway network latency.

All routers import and mount before FastAPI enters lifespan. Lifespan initializes legacy SQLite and caches the frozen hash before the service handles traffic. Missing Label Studio credentials are checked on connector requests and do not prevent boot. A missing SQLite **file** in a writable directory is created. A missing parent or an unwritable database fails init_db during startup, before health can return degraded. A later legacy probe failure yields degraded/200. Labeling DB failure or hash mismatch yields unhealthy/503. The DB probe checks connectivity only. Verify migrated tables via authenticated smoke and bound DB connection/probe time within the 120-second startup deadline. [Railway health checks](https://docs.railway.com/deployments/healthchecks)

### 6. Pool and workload

`db/connection.py` uses one async engine per process. The PostgreSQL pool is lazy, with zero open on construction, five retained slots and ten overflow slots by default, up to 15 concurrent connections per process. Each request gets a session that checks out connections on demand, commits or rolls back, then closes. The dashboard auth/domain dependencies and sequential overview queries share that session. Even at 100K labels the normal overview uses one checkout, while concurrent requests and deployment overlap multiply demand. Health also checks out a connection. Set pool size, overflow and timeout against the actual database connection budget and replica count.

`labeling_router._category_stats` materializes verified ORM history. `dashboard_router._curve` uses SQL windows and the overview can return roughly 10K samples for 100K verifications. Worker memory, response size and time holding the checkout are the scaling concerns. Aggregate in SQL, cap points and benchmark a representative domain. Anonymous report routes have no DB dependency. They consume CPU, heap and potentially temporary disk in the web process. The reviewed path has no explicit shared-memory allocation. Raising the assumed 64 MiB shared-memory limit would not address those costs.

### 7. Frontend delivery

`jm_service.py` mounts StaticFiles last and only if `frontend/dist` exists. Earlier API routes win. Without dist, API startup succeeds and the review UI is unavailable. The app uses HashRouter. A URL such as `/#/dashboard` loads index.html at root and routes in the browser. A direct history-style `/dashboard` URL has no SPA rewrite. The built dist and source scan found no localhost:8000 URL. `src/api.ts` uses same-origin `/v1`. The Vite development proxy has no production role.

### 8. Build input and timing

`git ls-tree -r HEAD` contains the older service and ten tracked files in total. The index lacks the frontend manifests and source, `db/`, `label_health/`, routers, entrypoint and `railway.toml`. The local Dockerfile and requirements also have working-tree changes. A Git-connected deploy of HEAD cannot ship the audited application. Include the intended release files in a reviewed commit and build from that exact SHA. For a CLI upload, independently check the uploaded context.

Post-sweep LBL-DEPLOY-2 changed the Dockerfile to copy the built frontend assets directly into Python 3.11 slim. The frontend build passed locally. The release revision now needs a clean Linux image build to verify the packaged assets and native PDF renderer. Its broad root Python COPY also ships test and experiment scripts.

No clean image duration or native PDF result is available. A working-tree frontend build and Windows fallback PDF cannot certify Linux package resolution, fonts, or the supplied 15-minute build target. Time a cold build, validate frontend assets and native WeasyPrint in the image, then run the smoke client. Use the measured time before committing to a build budget.

### 9. Railway service configuration

`railway.toml` selects Dockerfile, `/v1/health`, 120 seconds and ON_FAILURE. Use jm-service as the build root and verify Railway finds this config. Set a strong `ADMIN_API_KEY` for key issuance. Set `LABEL_STUDIO_TOKEN` for connector use, with `LS_CONFIG_PATH` on durable storage. Set project/domain mapping or environment defaults as required for the connected project. The compose smoke admin key is local-only. Use Railway private DNS for PostgreSQL.

Shell exec makes Uvicorn PID 1 so it receives SIGTERM directly. Uvicorn can drain requests, and request-scoped sessions close. The lifespan has no explicit pool disposal or graceful shutdown timeout. Configure enough drain time for in-flight writes and verify a redeploy during representative traffic. Migration emits stdout/stderr, and Uvicorn emits access and error logs to standard streams. Railway captures those streams. Linux termination behavior remains a staging check.

### 10. Public endpoints and error disclosure

`auth.py` uses constant-time comparison for the admin secret and rejects requests if the secret is missing. Labeling/dashboard routes require tenant credentials. Default FastAPI docs, ReDoc and OpenAPI are exposed, with debug mode off. Legacy `POST /v1/register` publicly issues legacy credentials and writes to the volume. Decide whether to expose those legacy routes, restrict registration if unnecessary, and scope CORS to browser origins that actually need it. The shipped wildcard CORS middleware is unnecessary for the same-origin UI. Label Studio server-to-server webhooks authenticate independently of browser CORS.

Anonymous CSV analysis and PDF rendering run synchronously inside async routes with no application rate limit, bounded worker queue or render deadline. One large report can occupy the sole event loop and delay health and authenticated requests. Apply ingress limits before multipart parsing, bound report concurrency and run CPU-heavy work outside the event loop. Verify health responsiveness and memory under representative concurrent uploads before opening unrestricted public access.

Default production 500 responses are generic and health reports DB exception types. However, `labeling_router.ingest_batch` includes `str(IntegrityError)` in the client-facing 422, which can expose SQL and bound values. CSV validation can return parser details. Return stable client-safe messages with the item index and retain sanitized diagnostics server-side. No live public endpoint was probed.

### Ordered pre-deploy checklist

1. Prepare the complete release revision, verify the frozen hash after Linux checkout and confirm every COPY input exists.
2. Build the revision cold, time it, verify the native PDF renderer and serve a hash-routed UI page from the image.
3. Provision PostgreSQL 17, reference its private URL in the API service, verify the chosen TLS policy and budget the pool.
4. Attach writable storage at /data, set the two file paths and production secrets, and confirm database and volume backup/restore.
5. Run migrations twice in staging, exercise a delayed database start and check startup health within 120 seconds.
6. Bound anonymous workloads, sanitize error responses and confirm the intended public routes and browser origins.
7. Run test_smoke.py against the staging HTTPS URL with its admin key. Require 9/9, verify the frontend separately, redeploy, and check retained legacy state, connector mapping, labeling data and in-flight request handling before public traffic.
