# RCAA v0.14 Final Release Report

## Final feature

**Closed-loop Financial Recovery** is added to the existing RCAA workflow without replacing the reconciliation, evidence, deterministic RCA, SLA, case, audit, authentication, tenant-isolation, connector, or AI-safety architecture.

> An exception is not resolved until RCWA can establish what happened to the money and verify the financial outcome.

## Existing workflow preserved

Payment → Settlement → Bank → Exception → Evidence → Deterministic RCA → Owner/SLA → Case Resolution → Audit

## New workflow extension

Exception → Evidence → Deterministic RCA → Owner/SLA → **Recovery Action → Recovery Verification → Resolution** → Audit

## Implementation

- Migration `0019_closed_loop_recovery` adds one merchant-scoped recovery record per case.
- Existing cases are backfilled during migration.
- Exposure and recovery amounts use `Numeric(14,2)` and Python `Decimal`.
- Recovery action records the action type, external reference, expected recovery time and factual note.
- Recovery verification is performed against a merchant-scoped bank transaction.
- Verification requires an exact recoverable-amount match and, when an external reference was recorded, the bank reference must contain that reference.
- Financial source records remain immutable.
- Recovery actions do not call or mutate payment providers.
- A financial case cannot be resolved until recovery is `VERIFIED`; `FALSE_POSITIVE` remains the explicit exception for cases proven not to represent a real financial exposure.
- Recovery actions and verification are represented in the existing case timeline and audit trail.
- The existing case investigation page now contains the recovery workflow.

## API

- `GET /api/v1/cases/{case_id}/recovery`
- `POST /api/v1/cases/{case_id}/recovery/initiate`
- `POST /api/v1/cases/{case_id}/recovery/verify`
- `POST /api/v1/cases/{case_id}/recovery/unrecoverable`

## Verification performed

- Python compilation: passed.
- Backend regression suite: **20 passed / 0 failed**.
- Fresh Alembic database migration: **0019 head**.
- `case_recovery_records` created successfully on a fresh database.
- End-to-end test proves resolution is blocked before recovery verification and succeeds after exact bank-backed verification.

## Honest scope

RCAA records recovery actions and verifies the financial outcome. It does not autonomously issue refunds, modify provider records, modify bank records, or claim a recovery merely because an analyst marked an exception resolved.
