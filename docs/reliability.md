# Reliability and Background Processing

Stage 10 adds a durable database-backed job queue and a separate worker process. Redis and Celery were not established dependencies in the existing project, so the simplest architecture that fits the codebase is a durable SQLAlchemy/Alembic job table plus a polling worker.

## Architecture

`HTTP API -> background_jobs -> worker -> existing domain services -> audit/metrics`

The API creates a durable `QUEUED` job and returns HTTP 202. The worker claims one job using an atomic status transition and a lease. Financial domain services continue to own financial truth.

## Job lifecycle

`QUEUED -> RUNNING -> SUCCEEDED`

or

`RUNNING -> RETRYING -> RUNNING ... -> FAILED/DEAD_LETTERED`

A stale `RUNNING` lease is recovered into a retryable state unless the retry limit has been exhausted.

## Job types

Only the controlled catalog is supported: ingestion for payments/refunds/settlements/bank transactions, reconciliation, evidence building, deterministic RCA, and AI investigation.

## Idempotency

Job creation requires `Idempotency-Key`, unique per merchant. Existing domain uniqueness/fingerprints remain authoritative. A duplicate submission returns the existing job rather than creating a second logical operation.

## Retries

Default maximum attempts is 3. Backoff is exponential and bounded by `JOB_RETRY_MAX_SECONDS`. Transient dependency/timeouts/rate-limit failures are retryable. Validation, authorization, missing resources, unsafe AI output, and invalid citations are not retried.

## Concurrency and recovery

Workers use an atomic claim update and a lease. A second worker cannot claim a job already in `RUNNING`. Expired leases are recovered. A job is never marked successful before the business transaction commits.

## Tenant and RBAC

Jobs are owned by the authenticated merchant at creation. Job reads are merchant scoped. ADMIN/OPS can create and retry; all authenticated roles can list/detail jobs. Worker handlers verify the job merchant before processing case-scoped operations.

## Audit and observability

Job creation, success, retry, failure, and terminal failure are audited as SYSTEM activity. Job metrics use only bounded `job_type`, `status`, and `failure_category` labels. Job IDs, request IDs, merchant IDs, payment IDs, and case IDs are not metric labels.

## Cancellation

Arbitrary cancellation is intentionally deferred because forcefully stopping a running financial operation could create partial effects. Safe cancellation can be considered in a later stage.

## Operational limits

The queue is durable in the database; there is no unbounded in-memory work queue. Worker concurrency is intentionally simple: run multiple worker processes against the same database with atomic claim protection. Configure lease/backoff settings through environment variables.

## Limitations

This stage intentionally does not add Kafka, Celery, Kubernetes, autoscaling, notifications, CI/CD redesign, or deployment redesign.

## Health and readiness

`/health` remains API liveness. `/ready` checks the database required by the HTTP API. The worker is a separately supervised process; worker health is represented by job state, lease recovery, worker logs, and job metrics rather than making a non-critical worker dependency block API readiness.

## Graceful shutdown

The worker accepts SIGTERM/SIGINT, stops accepting new work, lets the current synchronous job finish where the process can continue, and exits. The job lease is cleared only after success/failure handling; an abrupt process termination leaves the lease for stale-job recovery and never marks the job successful merely because shutdown occurred.
