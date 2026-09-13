# RCAA v0.4 Completion Report

## Completed scope

Customer Data Onboarding is implemented on top of the existing RCAA architecture.

### Added

- CSV and XLSX upload support.
- 5 MB / 10,000 row pilot limits.
- Four supported existing financial data types: payments, settlements, refunds, bank transactions.
- Canonical field definitions and automatic column suggestions.
- Customer-reviewable column mapping.
- Row-level validation through the existing authoritative ingestion normalizer.
- Validation summary with valid, warning, and error counts.
- Persistent upload records with tenant isolation.
- Import workflow with existing deterministic ingestion and duplicate handling.
- Idempotent re-import behavior at the upload workflow level.
- Audit events for upload creation, validation, and import completion.
- Customer-facing Data Onboarding UI.
- Reconciliation trigger after import using the existing `/reconciliation/run` endpoint.
- Migration `0011_data_onboarding`.
- Regression coverage for CSV, XLSX, validation failures, import, and idempotent re-import.

## Existing architecture intentionally preserved

- Existing FastAPI application.
- Existing PostgreSQL/SQLAlchemy model layer.
- Existing deterministic reconciliation engine.
- Existing exception and case workflow.
- Existing authentication/RBAC and tenant isolation.
- Existing audit implementation.
- Existing Next.js frontend architecture.
- Existing background-job architecture.

## Verification

- v0.4 backend regression tests: **4 passed**.
- Backend source compilation: **passed**.
- Existing frontend tests: **21 passed**.
- Existing frontend source hygiene check: **34 files passed**.
- Frontend typecheck was not re-run because the cleaned repository intentionally does not contain `node_modules`; the earlier baseline environment also lacked installed frontend dependencies.

## Deliberate scope boundary

Orders are not introduced as a new financial ledger in v0.4 because the existing RCAA domain does not contain an order table and the reconciliation engine currently operates on payment, refund, settlement, and bank records. Payment order references remain supported. A separate order ledger should be added as its own domain feature rather than silently treating order rows as payments.
