# Architecture

RCAA uses a small layered backend while preserving the existing API contract.

```text
FastAPI routers
    ↓
services / reconciliation / RCA
    ↓
repositories
    ↓
SQLAlchemy models
    ↓
PostgreSQL (production) / SQLite (tests)
```

Provider integrations sit behind `app.providers.PaymentProvider`. Razorpay is an adapter; the application works with normalized records rather than vendor-specific models.

Financial truth is deterministic. Reconciliation creates cases from stored payment, refund, and settlement records. RCA records the deterministic explanation and evidence. The AI endpoint only narrates persisted RCA/evidence and cannot change financial records.

Configuration is read from environment variables. Request IDs are generated or propagated through HTTP middleware and returned in the response. Server-side logging records request paths and unhandled errors without returning stack traces to clients.

Alembic is the schema migration authority. Application startup does not call `create_all()`. The existing initial migration remains non-destructive; no schema migration was required for this cleanup.
