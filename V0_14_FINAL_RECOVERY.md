# RCAA v0.14 — Closed-loop Financial Recovery

## Product change

RCAA now treats a financial exception as unresolved until its financial outcome is established and verified. The feature is additive to the existing reconciliation, evidence, RCA, SLA, case and audit workflow.

## Lifecycle

**Detect → Investigate → Quantify exposure → Initiate recovery → Verify bank outcome → Resolve → Audit**

## Backend

- Added `case_recovery_records` with one recovery record per case.
- Existing cases are backfilled during migration `0019`.
- Recovery amounts use database `Numeric(14,2)` and Python `Decimal`; no frontend financial recalculation is authoritative.
- Recovery initiation records action type, external reference, expected recovery time and notes.
- Verification requires a merchant-scoped bank transaction with an exact amount match and, when supplied, a matching recovery reference.
- A financial case cannot be marked resolved until recovery is `VERIFIED`, except an explicitly selected `FALSE_POSITIVE`.
- All recovery actions and verification events are recorded in the existing case timeline and audit trail.
- No provider/payment/settlement/bank record is mutated by recovery actions.

## Frontend

The existing case investigation workspace now includes a **Closed-loop financial recovery** section showing exposure, recoverable, recovered and status, plus controls for recording a recovery action and verifying the bank outcome. No new financial truth is calculated in the browser.

## API

- `GET /api/v1/cases/{case_id}/recovery`
- `POST /api/v1/cases/{case_id}/recovery/initiate`
- `POST /api/v1/cases/{case_id}/recovery/verify`
- `POST /api/v1/cases/{case_id}/recovery/unrecoverable`

## Verification

Backend regression: 20 passed.

Fresh Alembic migration must reach `0019` head before deployment.

## Scope boundary

RCAA records and verifies recovery; it does not autonomously issue provider refunds, alter bank records, or mutate financial source records.
