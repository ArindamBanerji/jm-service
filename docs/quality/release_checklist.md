# DLJ single-instance release checklist

Record the candidate commit, immutable image digest, environment, operator, timestamps and evidence links in the release ticket. Keep secrets in the platform secret store. The architecture release procedure is in [§6](../design/dlj_arch_redesign_v2.md#6-timeline-and-critical-path).

## Before deployment

- [ ] Record the last compatible image and schema, stop competing migrators, schedule the write/worker pause and take a Railway PostgreSQL backup and a legacy/config volume backup. Restore both into isolation. Compare tenant, project, label, content, billing and outstanding-delivery counts.
- [ ] Build the actual Dockerfile in staging. The Node stage must build the SPA from its lockfile. Confirm the final Python image installs its pinned requirements, serves the built assets and downloadable client, and mounts persistent storage at /data. Run with one worker. Check container readiness via /v1/health.
- [ ] Rehearse the entrypoint against an empty PostgreSQL database and twice against the restored staging copy. Verify constraints, existing rows and the fresh-install marker. Stop on incompatible schema, historical ownership ambiguity or a failed migration.
- [ ] On the candidate run the PostgreSQL suite, active scenarios, Playwright, TypeScript, Vite build and mypy. Match the frozen engine digest in session state. Run `python -m tests.release_server --measure` with DLJ_DATABASE_URL pointing to disposable PostgreSQL. Repeat 30 authenticated, committed scoring requests on the staging instance. Require median below 50 ms and nearest-rank p95 below 100 ms.
- [ ] Exercise signup with a mailbox controlled by the operator. Confirm once and use the issued key. Exercise a controlled Paddle sandbox checkout and inspect the provider transaction, tier price, purchaser, payer, callback, replay and resulting quota. The returned checkout link identifies a transaction. The tier price is in that transaction's items. For the provider-backed pytest branch use DLJ_TEST_PADDLE_CHECKOUT=1, a sandbox PADDLE_API_KEY, PADDLE_SANDBOX=true and the sandbox price map, then run `python -m pytest tests/test_release_gate.py -k checkout_url_generation`.
- [ ] Test signed outbound webhooks against a controlled destination, including retry and restart. Compare the canonical body and signature. Keep payment notifications and webhook delivery disabled during an offline restore rehearsal.

## Configuration inventory

For a repeatable local rehearsal, point DLJ_DATABASE_URL at a disposable PostgreSQL database on which the test role can create schemas. Build the frontend before running browser tests. Run the timing probe separately from the regression suites.

```sh
npm --prefix frontend run build
npm --prefix frontend run typecheck:e2e
python -m pytest tests/ -q --timeout=120 -k "not exp_dlj"
python -m tests.release_server --playwright
python -m tests.release_server --measure
```

The browser command boots the current checkout on a private port, runs the repository Playwright configuration, and closes its schema and service on exit. Leave NER_EDITOR_BASE_URL and TAG_IMAGE_BASE_URL unset for this rehearsal.

| Setting | Release check |
|---|---|
| DATABASE_URL | Private Railway PostgreSQL connection. Require the production preflight to succeed. |
| RAILWAY_ENVIRONMENT_NAME, RAILWAY_ENVIRONMENT, ENVIRONMENT | Set the production environment explicitly. Startup validates the database, billing, mail, admin and encryption settings before migration. |
| ADMIN_API_KEY, RESEND_API_KEY | Install private service credentials. Confirm authorized admin issuance and actual delivery from the configured sender. |
| PADDLE_API_KEY, PADDLE_PRICE_MAP, PADDLE_WEBHOOK_SECRET | Use matching environment credentials and secret. Map starter, professional, business and scale to provider price IDs using tier=pri_id pairs. Test each advertised tier. |
| PADDLE_SANDBOX | Keep true during rehearsal. For the live cutover switch to false alongside the matching price map, API key, webhook secret and frontend Paddle configuration. |
| WEBHOOK_ENCRYPTION_KEY | Set a persistent valid Fernet key **before** startup or endpoint creation. Back it up in the secret manager. Replacing it without a re-encryption migration loses access to stored webhook secrets. |
| DLJ_IMAGE_PROJECTS_ENABLED | Enable after text smoke tests. Confirm the capabilities API advertises image/single and that an image project can import, verify and export. |
| DLJ_INLINE_IMAGES_ENABLED | Enable after PNG round-trip and worker memory checks under concurrent intake and export. Keep off if the instance cannot sustain the bounded load. |
| PORT, JM_DB_PATH, LS_CONFIG_PATH | Match Railway routing and persistent volume paths; verify legacy store readability and connector config migration. |
| LABEL_STUDIO_TOKEN, LABEL_STUDIO_TENANT_ID, LABEL_STUDIO_DOMAIN_ID, LS_FACTOR_MAP | Configure if using the connector. Confirm tenant and project binding with a test project. |
| SENTRY_DSN | Optional monitoring sink. Confirm sanitization and alerts for readiness, failed deliveries and elevated latency. |
| API_KEY_SALT | The current modern key verifier hashes high-entropy generated tokens using SHA-256. This name has no application reader. |
| VITE_API_KEY, DLJ_PORT, DLJ_DATABASE_URL | Development/build and test controls. Keep tenant credentials out of frontend builds and isolate the test database. |

## Deployment and smoke tests

1. Deploy the verified image digest. Wait for preflight and migration to finish before admitting traffic. Confirm the application listens on PORT and both stores and the frozen engine appear healthy.
2. Enable payment processing only after matching the backend environment with the frontend. The manual live change removes the sandbox line from frontend/index.html, then pushes, rebuilds and deploys the reviewed frontend. Keep the coordinated rollout behind a maintenance window. Compare the final image digest.
3. Check /, /#/docs, /docs, /openapi.json and /dlj_client.py. Test permitted and denied CORS origins. Complete signup, owner project creation, scoring, review, analytics and CSV download. Check another tenant cannot read the project.
4. Verify HTTPS and inline image ingestion through G4, modality locking after the first write, exact export media, conservation evidence and replay without a second charge. Confirm denied or malformed writes expose no private inputs and debit no quota.
5. Check payment binding and price in the provider dashboard, verify webhook delivery, rotate a test destination secret and check delivery history. Check errors, quota refusals, lease expiry, retention and backlog age. Take the post-deployment backup and attach the evidence.

## Go, hold and rollback

Promote only with green local and staging gates, matching sandbox/live settings, verified backups and an identified release owner. Hold on failed readiness, missing retention evidence, an unresolved launch defect, missed scoring latency, or an unverified vendor transition. The [risk ledger](accepted_risks.md) records the separate historical exceptions.

If a smoke test fails, close write admission, pause cleanup and delivery, retain logs and snapshot the failed state. Roll back to the last schema-compatible image. Compare acknowledged writes, receipts, quota, pending deliveries and key versions. Restore a database backup only with an explicit operator recovery decision and a plan to reconcile writes acknowledged after the backup. Replay signed events against their durable receipt keys, validate both stores and resume traffic only after the same smoke checks pass.
