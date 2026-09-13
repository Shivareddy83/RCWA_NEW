# Stage 08 — Audit Logging & Compliance Traceability

RCAA Stage 08 adds an append-only operational audit trail without changing deterministic financial truth.

## Event schema

`AuditEvent` records:

- `event_id` — stable event identifier
- `merchant_id` — tenant scope; unknown-identity login failures use `SYSTEM_GLOBAL` because a merchant cannot be safely inferred
- `actor_user_id`, `actor_role`, `actor_type` — human or system actor
- `action` — stable machine-readable action code
- `resource_type`, `resource_id` — affected resource
- `request_id` — request/correlation identifier
- `timestamp`, `outcome`, `ip_address`
- `metadata_json` — minimal operational metadata
- `before_snapshot`, `after_snapshot` — minimal state-change snapshots
- `previous_event_hash`, `event_hash` — tamper-evident hash chain

Sensitive values are filtered before persistence. Passwords, password hashes, JWTs, API keys, webhook secrets, private keys, and AI credentials are not stored in audit metadata or snapshots.

## Action catalog

Authentication: `AUTH_LOGIN_SUCCESS`, `AUTH_LOGIN_FAILURE`, `AUTH_REGISTER`

User administration: `USER_CREATED`, `USER_UPDATED`, `USER_DISABLED`, `USER_ROLE_CHANGED`

Imports: `PAYMENT_CREATED`, `PAYMENT_IMPORTED`, `REFUND_IMPORTED`, `SETTLEMENT_IMPORTED`, `BANK_TRANSACTION_IMPORTED`

Reconciliation: `RECONCILIATION_STARTED`, `RECONCILIATION_COMPLETED`

Exceptions: `EXCEPTION_CREATED`, `EXCEPTION_ACKNOWLEDGED`, `EXCEPTION_RESOLVED`

Cases: `CASE_CREATED`, `CASE_ASSIGNED`, `CASE_NOTE_ADDED`, `CASE_STATUS_CHANGED`, `CASE_RESOLVED`, `CASE_REOPENED`, `EXCEPTION_ATTACHED_TO_CASE`

Evidence/RCA: `EVIDENCE_CREATED`, `RCA_GENERATED`

AI: `AI_INVESTIGATION_REQUESTED`, `AI_INVESTIGATION_COMPLETED`, `AI_INVESTIGATION_FAILED`

Authorization: `AUDIT_ACCESS`, `AUTHORIZATION_DENIED`

Outcomes are `SUCCESS`, `FAILURE`, or `DENIED`.

## Tenant isolation and RBAC

`GET /api/v1/audit/events` and `GET /api/v1/audit/events/{id}` are read-only and merchant-scoped. ADMIN, OPS, and ANALYST can read the audit trail; VIEWER is denied. The server takes merchant ownership from the authenticated identity rather than trusting a client merchant identifier.

## Hash chain

Each event hashes the previous event hash plus deterministic canonical JSON. Canonicalization uses sorted keys, stable separators, UTF-8, and ISO timestamps. The chain detects modification or deletion of an event, but it is not encryption and cannot stop a privileged database administrator from rewriting the complete chain.

## Transactional behavior

Where the existing operation can expose an uncommitted transaction, the audit event is inserted into that same transaction. A rollback therefore removes both the business change and its success audit event. Some legacy ingestion/reconciliation/AI flows commit internally; their Stage 08 audit records are added at the operation boundary after that internal commit and are documented as such rather than pretending they are atomic.

Audit write failure is not allowed to silently manufacture a successful audit record. Security/operational audit writes are explicit database operations and failures surface through the normal request error path.

## Retention

No automatic audit deletion is implemented in Stage 08. Retention is deployment/compliance dependent. Configurable retention is a future concern.

## API

`GET /api/v1/audit/events`

Filters: `action`, `actor_user_id`, `resource_type`, `resource_id`, `outcome`, `start_date`, `end_date`, `request_id`. Pagination is mandatory.

`GET /api/v1/audit/events/{id}`

The detail endpoint enforces merchant scope.

## Security boundaries

Stage 08 does not add MFA, OAuth/SSO, distributed rate limiting, notifications, SIEM integration, external compliance platforms, frontend redesign, deployment redesign, or advanced cryptographic signatures.
