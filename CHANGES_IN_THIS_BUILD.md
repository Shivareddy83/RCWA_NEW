# Changes in This Build (v5)

Builds on v4 (fixed the UnboundLocalError in scheduled reconciliation jobs). This pass: verified auto-sync-from-Razorpay actually works end-to-end and added test coverage for it, since it had none.

## What "auto-sync from Razorpay on a schedule" turned out to be
It was already fully built — not something missing. `DataConnector` has `sync_enabled` / `sync_interval_minutes` / `next_sync_at`; `worker_loop()` polls every 30 seconds via `enqueue_due_connector_jobs()`, which finds connectors past their `next_sync_at`, enqueues a `SYNC_CONNECTOR` job, and reschedules. No manual trigger needed once a connector has `sync_enabled=True`.

## What was actually missing: verification
`enqueue_due_connector_jobs()` had **zero test coverage** — no test confirmed it only picks due+enabled connectors, ignores disabled/not-yet-due ones, or reschedules correctly. Given the UnboundLocalError found in the same worker file last pass, "it's wired up" wasn't good enough — it needed to be proven.

**Verified directly** (three merchants, one due+enabled connector, one not-due, one disabled):
- Correctly enqueues exactly the due, enabled connector — 1 job created, right payload.
- Correctly ignores the disabled and not-yet-due connectors.
- Correctly reschedules `next_sync_at`, so an immediate second poll doesn't double-enqueue.

## Two new tests added (`tests/test_stage10_reliability.py`)
- `test_enqueue_due_connector_jobs_only_picks_due_enabled_connectors` — locks in the three behaviors above so this can't silently regress.
- `test_scheduled_sync_connector_job_runs_reconciliation_without_error` — a **specific regression guard** for the v4 UnboundLocalError bug: creates a scheduler-triggered `SYNC_CONNECTOR` job and asserts it never fails with that specific error again.

## Verification
Root + backend suite (e2e file excluded, see v4 notes on its separate working-directory requirement): **223 passed, 1 failed** — up from 221 passed in v4. The 1 failure is the same known business-rule question flagged in v3/v4, untouched.

## Still open
- Same as v4: the case-resolution business-rule question (needs your decision), the `merchant_id NOT NULL` migration, no external pen test, no second gateway, no live bank feed, no paying customer.
- Auto-sync now works and is tested for the happy path and basic scheduling correctness. Not yet tested: behavior when a scheduled sync's Razorpay call actually fails (network error, expired credentials) — the `next_sync_at` is advanced *before* the sync job runs, so a failing connector won't retry until the next full interval rather than sooner. That's a reasonable design choice (avoids hammering a broken connection) but nothing currently alerts you when a connector has been silently failing for days — worth flagging if you're relying on this unattended.
