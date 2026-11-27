# DLJ release risks

Applies to a single Railway worker on a fresh PostgreSQL labeling database. The release owner must reopen the applicable risk before changing those assumptions. The historical reconciliation records and estimates are in the [R2 ledger](../session_state.md#dlj-r2-unified--accepted-risk-ledger-for-v11).

| Risk | Exposure and mitigation | Reopen when / owner |
|---|---|---|
| R06 | Legacy JM decisions and snapshots can diverge after a partial legacy write. Keep the legacy SQLite volume isolated and backed up. | Before onboarding a legacy consumer / service owner |
| R07 | Legacy credentials are recoverable from the legacy store. Restrict volume and backup access and keep modern hashed keys separate. | Before redistributing snapshots or granting external legacy access / security owner |
| R24 | SQLite compatibility has different concurrency semantics. Use PostgreSQL for production and the release gate. | Before supporting SQLite multiwriter deployments / database owner |
| R30 | Historical centroid keys can contain ambiguous separators. New legacy domains constrain the names. | Before loading a historical engine snapshot / engine owner |
| Historical billing and migration | Old receipts (N1), repair manifests and later checkouts (N2/N9), ownership (R23/F1), mixed tombstones (N10/R14/F2/F5), and tied events (N11/R19) need reconciliation. Preserve manifests, signed history, backups and quarantine ambiguous ownership. | Before importing or replaying any pre-A data / migration and billing owners |
| Capacity | Historical analytics scale with project size and annotator count. Snapshot export uses a bounded spool, two project slots and a deadline. Large inline media consumes worker memory concurrently with detail and export. | Before raising limits, enabling inline on a new instance class or adding replicas / operations |

Production backup restoration, image startup, delivery through Resend and a real Paddle sandbox checkout require staging evidence. These are cutover checks in the [release checklist](release_checklist.md), outside the accepted v1.1 backlog.
