# v0.10.5 Production Reliability & Resilience Hardening

## Reliability goals

This stage hardens the existing SQL-backed worker architecture without introducing Kubernetes, Kafka, or a new distributed queue.

### Release safety

- Immutable backend/frontend image tags are supported through `RCAA_BACKEND_IMAGE` and `RCAA_FRONTEND_IMAGE`.
- Production deployment runs a pre-release PostgreSQL backup.
- Database migrations execute before the release health gate.
- `/health`, `/ready`, and `/version` are checked before a release is considered successful.
- Every successful release writes `releases/<BUILD_ID>.env` for rollback.
- `rollback_production.sh` restores a known-good application image without attempting a destructive schema downgrade.

**Zero-downtime contract:** the proxy and deployment model are health-gated and support multiple application replicas. A strict zero-downtime SLO still requires running at least two backend/frontend replicas behind the proxy and a production load balancer. A single Docker host with one replica cannot mathematically guarantee zero downtime during replacement.

## Worker resilience

The worker uses durable SQL jobs, atomic claims, leases, retries, and stale-job recovery. Long-running jobs now refresh their lease while processing. This prevents an active worker from being mistaken for a crashed worker merely because a job exceeded its initial lease duration.

SIGTERM/SIGINT stops new work while allowing the current synchronous operation to finish where possible. Container `stop_grace_period` gives the worker time to exit cleanly.

## Database recovery

`backup_postgres.sh` creates a PostgreSQL custom-format dump, verifies the dump catalog, writes a SHA-256 checksum, and supports retention-count cleanup.

`verify_backup.sh` restores the dump into a temporary isolated database and verifies the Alembic version table. This is the required backup acceptance test; never test a backup by overwriting the only production database.

## Health gates

- `/health`: process liveness.
- `/ready`: database readiness.
- `/version`: release identity.
- `release_health_gate.sh`: externally verifies all three before release completion.

The worker intentionally does not block API readiness. Worker health is observed through durable job state, stale-job recovery, metrics, and logs.

## Resource controls

Production Compose applies memory, CPU, and PID limits to PostgreSQL, backend, worker, frontend, and Caddy. These are guardrails, not capacity guarantees. Values must be sized against real production traffic.

## Observability and alerting

`deploy/prometheus-alerts.yml` provides starter alerts for:

- elevated HTTP 5xx rate
- high API p95 latency
- dead-lettered jobs
- stale worker recovery

`deploy/alertmanager.example.yml` is a receiver template. Credentials and organization-specific notification endpoints must be supplied outside Git.

Metrics labels remain bounded; customer IDs, request IDs, job IDs, and payment IDs must not be promoted to metric labels.

## Rollback policy

Application rollback and data rollback are separate operations.

- Application rollback: restore a previously validated image release.
- Schema rollback: only use a reviewed Alembic downgrade when compatibility and data impact are known.
- Financial data recovery: restore a verified backup into an isolated environment first.

Never use application rollback as a substitute for financial-data recovery.
