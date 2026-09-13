# Case Management & Operations Workflow

Stage 04 adds a thin operational case layer above deterministic reconciliation exceptions.

## Flow

`financial records -> reconciliation -> exception -> case -> investigation -> resolution`

Cases never edit payment, refund, settlement, or other financial source-of-truth fields.

## Lifecycle

- `OPEN -> IN_PROGRESS`
- `OPEN -> RESOLVED` when resolution information is supplied
- `IN_PROGRESS -> RESOLVED`
- `RESOLVED -> REOPENED`
- `REOPENED -> IN_PROGRESS`
- `REOPENED -> RESOLVED`

Resolution requires a stable resolution code. Reopening clears `resolved_at` but keeps the prior resolution fields and timeline history.

## Case / exception relationship

A reconciliation exception has its original reconciliation case for backward compatibility. `case_exception_links` provides an explicit operational grouping relationship so a case can contain multiple related exceptions without copying financial data.

## Evidence and timeline

Case detail exposes references to stored evidence, linked exceptions, notes, and append-only case events. No raw provider secrets or large payloads are copied into the case.

## APIs

- `POST /api/v1/cases`
- `GET /api/v1/cases`
- `GET /api/v1/cases/{id}`
- `POST /api/v1/cases/{id}/assign`
- `POST /api/v1/cases/{id}/notes`
- `POST /api/v1/cases/{id}/start`
- `POST /api/v1/cases/{id}/resolve`
- `POST /api/v1/cases/{id}/reopen`
- `POST /api/v1/cases/{id}/exceptions`

Case listing supports status, priority, severity, merchant, assignment, exception code, created-date filters and bounded page/limit pagination.
