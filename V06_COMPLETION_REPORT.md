# RCAA v0.6 — Reports & Notifications

## Scope

This release adds the next customer-facing capability after v0.5: finance reporting and operational notifications. Existing reconciliation, exception, case, evidence, RCA, AI, tenant, authentication, and onboarding architecture is preserved.

## Delivered

- Tenant-scoped reconciliation summary API at `GET /api/v1/reports/summary`.
- Tenant-scoped exception CSV export at `GET /api/v1/reports/exceptions.csv`.
- Tenant-scoped case CSV export at `GET /api/v1/reports/cases.csv`.
- Report generation is audit logged.
- Persistent in-app notifications.
- Per-merchant notification preferences for exceptions, cases, and reports.
- Read/unread notification state.
- Reconciliation notification when a run creates new exceptions.
- Customer-facing Reports page.
- Customer-facing Notifications page.
- Migration `0012_reports_notifications`.
- v0.6 regression tests.

## Financial safety

Reports read authoritative backend financial records. No financial calculations are performed in the browser. AI is not involved in report totals or notification creation decisions.

## Verification

- v0.6 backend tests: **4 passed**.
- Full backend test suite from `backend/`: **8 passed**.
- Frontend test suite: **21 passed**.
- Backend Python compilation: **passed**.
- Alembic migration chain: **0012 is head**; clean SQLite upgrade through 0012 completed successfully.
- Frontend typecheck could not be completed in this clean checkout because the dependency directory is intentionally absent; the existing frontend test suite runs successfully without installed project dependencies.

## Out of scope

Billing, external email/Slack delivery, new payment-provider integrations, public marketing website, production cloud deployment, and further product stages are intentionally not included in v0.6.
