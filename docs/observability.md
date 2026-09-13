# RCAA Observability

## Architecture

Stage 09 adds operational observability without changing financial business logic:

`request -> authorization -> business operation -> audit event -> logs/metrics`

The observability layer is intentionally separate from reconciliation, RCA, and AI decision logic.

## Structured logging

Application request logs are JSON-compatible and may include timestamp, level, logger, message, request ID, correlation ID, merchant/actor context when safely available, operation/resource identifiers, duration, outcome, and safe error codes.

Credentials and sensitive values are redacted. Request/response bodies are not logged by the HTTP middleware.

## Request/correlation IDs

`X-Request-ID` is accepted when it matches the safe length/character policy. Missing or invalid values receive a generated UUID. The same ID is stored on request state, returned in the response header, included in HTTP logs, and passed to audit events where applicable.

## Metrics

The `/metrics` endpoint exposes Prometheus-compatible in-process metrics.

### HTTP

- `http_requests_total`
- `http_request_duration_seconds`
- `http_requests_in_flight`

Labels are limited to method, bounded route, and status.

### Ingestion

- `ingestion_batches_total`
- `ingestion_records_received_total`
- `ingestion_records_created_total`
- `ingestion_records_updated_total`
- `ingestion_records_duplicate_total`
- `ingestion_records_rejected_total`
- `ingestion_duration_seconds`

The source-type label is one of payment, refund, settlement, or bank_transaction.

### Reconciliation

- `reconciliation_runs_total`
- `reconciliation_duration_seconds`
- `reconciliation_matches_total`
- `reconciliation_unmatched_total`
- `reconciliation_ambiguous_total`
- `reconciliation_mismatches_total`

Matching labels describe deterministic methods/results only. They do not contain record IDs.

### Exceptions and cases

Exception and case lifecycle counters are generated from existing operational events. Labels use bounded codes/statuses rather than IDs.

### AI

- `ai_investigations_total`
- `ai_investigation_duration_seconds`
- `ai_investigations_success_total`
- `ai_investigations_failed_total`
- `ai_investigations_reused_total`

AI failure categories are bounded: provider unavailable, timeout, rate limit, invalid response/citation, unsafe output, insufficient context, and configuration error.

### Audit

- `audit_events_created_total`
- `audit_events_failed_total`
- `audit_events_denied_total`

Metrics do not replace the Stage 08 append-only audit store.

## Health and readiness

`GET /health` is a lightweight liveness check and does not query dependencies.

`GET /ready` checks database connectivity. It returns `200` with `{"status":"ready","database":"ok"}` when ready, otherwise `503` with a safe not-ready response.

No credentials, connection strings, or internal secrets are returned.

## Cardinality rules

Never use request IDs, payment IDs, refund IDs, settlement IDs, case IDs, exception IDs, user IDs, merchant IDs, UTRs, order references, or emails as metric labels.

These values belong in logs/audit context where appropriate, not Prometheus label dimensions.

## Security

Observability must not weaken Stage 07 authentication, RBAC, or tenant isolation. Metrics and readiness contain only aggregate/safe operational data. Audit records remain tenant-scoped and append-only.

Passwords, hashes, JWTs, authorization headers, API keys, webhook secrets, private keys, AI credentials, complete AI prompts/responses, and complete evidence bundles are not emitted.

## Troubleshooting workflow

1. Check `/health` for process liveness.
2. Check `/ready` for database readiness.
3. Inspect `http_requests_total` and request duration metrics.
4. Use the `X-Request-ID` response value to correlate HTTP logs with audit events.
5. Check ingestion, reconciliation, exception, case, AI, and audit counters for the affected operation.
6. Inspect safe structured error fields for unexpected 5xx failures.

## Financial immutability

Observability only observes existing operations. It does not calculate or mutate payment, refund, settlement, reconciliation, exception, evidence, RCA, or case financial values.

## Limitations and future possibilities

Metrics are process-local and intentionally lightweight for this stage. External metric storage, distributed telemetry, SIEM integration, alerting, dashboards, and deployment-specific retention policies remain deployment/future concerns.

Stage 09 does not introduce workers, queues, retries, Kafka, Celery, notifications, frontend redesign, deployment redesign, or autonomous AI behavior.
