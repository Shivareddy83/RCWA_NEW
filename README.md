# RCAA v0.14 — Final Sellable Release

RCAA is a deterministic payment-to-settlement-to-bank reconciliation and finance-operations investigation platform. AI is advisory only; financial truth remains deterministic and auditable.

See `V0_11_LAUNCH_READINESS.md`, `V0_12_CONNECTIVITY_AUTOMATION.md`, `V0_13_COMPETITIVE_FINOPS.md`, and `FINAL_PRODUCT_POSITIONING.md`.

# RCAA

RCAA is a locally runnable payment-operations platform that ingests provider-normalized payment records, deterministically reconciles them, preserves evidence, creates investigation cases, and provides deterministic root-cause analysis with evidence-grounded AI assistance.

**Core principle:** deterministic code establishes financial truth; AI assists investigation and explanation without modifying financial records.

## Run

Copy `.env.example` to `.env`, then run:

`docker compose up --build`

The backend applies Alembic migrations before starting.

API documentation: `http://localhost:8000/docs`
Dashboard: `http://localhost:3000`

Seed after startup with:

`python scripts/seed_demo_data.py`

When running the seed script outside Docker, set `DATABASE_URL` to the container-accessible database address.

For local verification:

`pip install -r backend/requirements.txt`

`PYTHONPATH=backend alembic -c backend/alembic.ini upgrade head`

`python scripts/seed_demo_data.py`

`uvicorn app.main:app --app-dir backend --reload`

`pytest -q tests`

## Design

PostgreSQL is the production/local Compose store; SQLite is supported only for lightweight tests.

Money uses `Decimal`. Provider IDs are unique and primary matching keys. Reconciliation is repeatable through case fingerprints and never uses fuzzy financial matching.

The Razorpay webhook verifies HMAC-SHA256 and stores each event idempotently. No credentials are committed.

The UI calls the API for summary data, reconciliation runs, case detail, evidence, and deterministic RCA/AI investigation.

The AI layer does not establish financial truth. It operates on persisted RCA and evidence and provides assistive investigation output.

## Security and Operations

The API uses JWT bearer authentication, Scrypt password hashing, server-side RBAC, and merchant tenant isolation.

Initial registration requires a separate `AUTH_BOOTSTRAP_TOKEN`; later user creation is limited to same-merchant admins.

An append-only, merchant-scoped audit trail captures actor, action, resource, request ID, outcome, minimal before/after state, and a SHA-256 hash chain. Sensitive credentials are excluded.

Production-oriented observability provides structured request logging, safe `X-Request-ID` correlation, Prometheus-compatible `/metrics`, lightweight `/health`, database-backed `/ready`, and bounded metric labels.

**v0.10.4 security hardening:** login/signup/demo/MFA endpoints have database-backed abuse throttling; uploads have bounded body/row/column/cell limits; authentication uses short-lived JWTs plus server-side sessions and rotating HttpOnly refresh cookies with reuse detection; TOTP MFA secrets are encrypted; production `/metrics` requires a bearer token and is not published by Caddy; Razorpay webhook processing supports CIDR-aware source-IP allowlisting and ignores stale lifecycle events by provider event timestamp; and production CSP/security headers are enabled. See `docs/security-hardening.md`.

Durable background jobs support idempotent creation, bounded retries, stale-worker recovery, tenant-scoped access, worker metrics, and audit events.

## Testing and Failure Engineering

The test suite includes adversarial regression coverage for:

- Authentication and JWT handling
- RBAC and tenant isolation
- Financial immutability and precision
- Reconciliation ambiguity
- Ingestion and replay safety
- Audit integrity
- Background-job ownership, idempotency, concurrency and recovery
- Retry handling
- AI safety
- Input validation and pagination
- Secret handling
- SQL/ORM safety
- Transactions and migrations
- Observability security

Security hardening includes bounded transaction listing, worker lease-owner validation, ORM-level financial immutability guards, and metric-label allow-listing.

See `docs/security-hardening.md` for the threat model, defects, fixes, limitations, and deferred improvements.

## Operations Console

The Next.js frontend provides a role-aware fintech operations console with:

- Dashboard
- Payments
- Refunds
- Settlements
- Exceptions
- Cases
- Investigation workspace
- Jobs
- Audit
- Ingestion
- Reconciliation

The frontend does not calculate reconciliation or settlement truth and does not call AI/provider APIs directly.

Backend authentication, RBAC, tenant isolation, and financial logic remain authoritative.

Frontend commands:

`npm run lint`

`npm run typecheck`

`npm test`

`npm run build`

Run these commands from `frontend/`.

## Background Processing

The platform uses a durable database-backed worker rather than Redis/Celery.

Supported jobs include ingestion, reconciliation, evidence generation, deterministic RCA, and AI investigation.

Jobs provide idempotency, bounded retries, worker leases, stale-worker recovery, tenant isolation, metrics, and audit events.

## Deployment

The deployment shape is intentionally small:

**PostgreSQL → FastAPI backend → database-backed worker → Next.js frontend**

The backend and worker use the same image; only the backend runs the migration entrypoint.

Docker services use health-based startup ordering, a persistent PostgreSQL volume, non-root application users, environment-only secrets, and bounded database/job configuration.

Production configuration is validated at startup.

`/health` provides lightweight liveness.

`/ready` checks database readiness.

`/version` exposes only release/build identifiers.

GitHub Actions runs backend regression, frontend tests, typecheck, source hygiene, production build, Compose configuration validation, and Docker builds.

Backup/restore, deployment rollback, migration safety, disaster recovery assumptions, and incident handling are documented in:

- `docs/deployment.md`
- `docs/docker.md`
- `docs/ci-cd.md`
- `docs/disaster-recovery.md`
- `docs/operations-runbook.md`

## Demo and Current Scope

The repository is designed for local/demo and test-mode operation.

Razorpay live fetches are intentionally not invoked without configured test credentials. Ingestion is available through API, webhook, and demo data.

An externally configured AI provider is optional; the default local path remains deterministic/mock and evidence-grounded.

The platform demonstrates the complete investigation flow:

**Payment → Settlement → Reconciliation → Exception → Case → Evidence → Deterministic RCA → AI Assistance → Audit**

The representative demo scenario uses a payment of ₹1,000 with a ₹25 fee and ₹5 tax, producing an expected settlement of ₹970 versus an actual settlement of ₹960. The resulting ₹10 discrepancy is detected deterministically and investigated through the case/evidence/RCA workflow.

Richer settlement allocation, provider polling, live provider integrations, and other production-scale capabilities remain future work.

## Closed-loop Financial Recovery

RCAA v0.14 adds a financial recovery lifecycle to the existing case workflow:

**Exception → Evidence → Deterministic RCA → Owner/SLA → Recovery Action → Recovery Verification → Resolution → Audit**

A financial case with a real exposure cannot be resolved until the recoverable amount is verified against a bank transaction. False-positive cases remain explicitly supported. Recovery actions are operational records only; RCAA never mutates provider, payment, settlement, or bank financial truth.

The case workspace exposes exposure, recoverable amount, recovered amount, recovery status, recovery action/reference, and bank-backed verification.

## Architecture Principle

RCAA separates financial truth from AI assistance.

**Deterministic systems establish:**

- Reconciliation results
- Amount calculations
- Exceptions
- Evidence
- Root-cause classification
- Financial state

**AI assists with:**

- Investigation
- Explanation
- Hypothesis generation
- Recommended next actions
- Evidence-grounded operational reasoning

AI cannot modify financial records, change settlement amounts, mark transactions as settled, issue refunds, resolve financial cases, or bypass authorization.

## License

MIT

## RCAA v0.6 — Reports & Notifications

The current release adds tenant-scoped finance reports, CSV exports, persistent in-app operational notifications, notification preferences, and audit logging for report generation. See `V06_COMPLETION_REPORT.md` for verification details.

## v0.9 — Razorpay Subscription Billing

v0.9 adds an optional real Razorpay recurring-billing path while preserving the v0.8 manual billing fallback. Set `BILLING_PROVIDER=razorpay` and configure the three Razorpay plan IDs plus API/webhook credentials before enabling it in a deployed environment. The customer checkout uses Razorpay Standard Checkout; signed checkout verification is recorded server-side, while subscription lifecycle and recurring charges are reconciled from signed Razorpay webhooks.

The Razorpay webhook endpoint is `POST /api/v1/webhooks/razorpay`. Configure the subscription events needed by the application, including `subscription.authenticated`, `subscription.activated`, `subscription.charged`, `subscription.pending`, `subscription.halted`, `subscription.resumed`, `subscription.cancelled`, and `subscription.completed`.


## v0.10.5 Production Reliability & Resilience

The current release adds health-gated deployment, immutable release image references, verified PostgreSQL backups, isolated backup-restore verification, rollback tooling, worker lease heartbeats, graceful shutdown controls, container resource limits, and Prometheus alert-rule templates. See `docs/reliability-hardening.md`.
