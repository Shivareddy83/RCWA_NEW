# RCAA v0.8 — Billing & Subscription Foundation

## Scope

v0.8 adds the customer billing foundation on top of v0.7. The existing reconciliation, investigation, reporting, notification, authentication, tenant isolation, and production-operations architecture was preserved.

## Delivered

- Explicit Trial, Starter, Growth, and Business plan catalog in INR.
- Tenant-scoped billing subscription state.
- Monthly transaction limits and current-period usage calculation.
- Tenant-scoped invoice records with unique invoice numbers.
- Customer billing overview, usage, and invoice APIs.
- Customer plan-request/checkout workflow that creates a pending invoice.
- Admin-controlled subscription activation.
- Admin-controlled invoice payment confirmation.
- Admin-controlled end-of-period cancellation flag.
- Billing audit events for checkout, plan changes, invoice creation/payment, and cancellation.
- Customer-facing Billing page in the existing Next.js operations console.
- Alembic migration `0013_billing`.
- Billing regression tests.

## Commercial boundary

This release intentionally does not pretend to collect money. `MANUAL` is the current billing provider. A plan request creates a pending invoice; an RCAA administrator activates the subscription after payment confirmation. This keeps financial state truthful until a real payment/subscription provider is connected in a later integration stage.

## Verification

- v0.8 billing tests: 4/4 passed.
- Selected regression tests: 11/11 passed.
- Frontend tests: 21/21 passed.
- Frontend source-hygiene check: 37 files passed.
- Python compilation: passed.
- Alembic migrations 0001 → 0013: clean SQLite upgrade reached `0013 (head)`.
- Billing API E2E: trial bootstrap → plan request → pending invoice → admin activation → invoice payment completed successfully.
- Final ZIP integrity: verified.

## Environment limitation

The frontend TypeScript typecheck requires the installed React/Next dependency tree. The clean repository intentionally does not ship `node_modules`, so the typecheck cannot run until dependencies are installed. The existing frontend test and source-hygiene suites pass without that dependency tree.
