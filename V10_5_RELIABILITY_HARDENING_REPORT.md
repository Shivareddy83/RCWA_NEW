# RCWA 48 — v0.10.5 Production Reliability & Resilience Hardening

## Scope

This release hardens the existing production architecture. It does not replace the SQL-backed job queue, add a new financial feature, or introduce Kubernetes/Kafka.

## Delivered

### 1. Release and deployment safety
- Immutable backend/frontend image references.
- Pre-release PostgreSQL backup.
- Health-gated release completion.
- `/health`, `/ready`, `/version` release checks.
- Release manifest under `releases/`.
- Explicit application rollback script.
- Rollback does not perform an unsafe database downgrade.

### 2. Database backup and recovery
- PostgreSQL custom-format backups.
- Backup catalog verification.
- SHA-256 checksum file.
- Configurable backup retention count.
- Isolated restore verification using a temporary database.
- Alembic-version integrity check after restore.

### 3. Worker failure recovery
- Existing durable SQL job queue retained.
- Atomic job claims retained.
- Lease expiration recovery retained.
- Long-running jobs now refresh their lease while executing.
- This reduces the risk of an active long-running job being treated as crashed.
- SIGTERM/SIGINT stop new work while the current synchronous operation can finish.

### 4. Health/readiness
- API liveness remains `/health`.
- Database readiness remains `/ready`.
- Release identity remains `/version`.
- External health gate script checks all three.
- Worker remains intentionally separate from API readiness; stale-job recovery and metrics provide worker failure detection.

### 5. Resource protection
Production Compose now has memory, CPU, and PID guardrails for PostgreSQL, backend, worker, frontend, and Caddy, plus shutdown grace periods.

### 6. Observability and alerting
Starter Prometheus rules cover:
- HTTP 5xx rate.
- API p95 latency.
- Dead-lettered jobs.
- Stale worker recovery.

Alertmanager configuration is a credential-free template and must be connected to the organization's approved notification system outside Git.

## Zero-downtime qualification

The release is **zero-downtime-ready**, not a false single-host zero-downtime guarantee.

Strict zero downtime requires at least two healthy backend/frontend replicas behind a load balancer/proxy and a deployment mechanism that keeps old capacity serving until replacement capacity passes health checks. A single Docker Compose replica cannot guarantee zero downtime during process replacement.

The scripts therefore use health gates and immutable releases and explicitly separate application rollback from database rollback.

## Validation

- Existing regression suite: 202 passed before the release changes.
- Reliability-focused + identity/security + prior reliability tests: 32 passed after the release changes.
- Full post-change suite: 207 passed in verbose execution.
- Shell syntax: PASS.
- YAML parsing: PASS.
- Docker Compose runtime validation: **not executed** because Docker CLI is unavailable in the build environment.
- Live multi-replica zero-downtime test: **not executed** for the same reason.

No production credentials are included in the release.
