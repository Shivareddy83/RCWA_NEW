# RCAA v0.5 — Customer Exception Investigation Workflow

## Scope

This release completes the next customer-facing capability after v0.4: an end-to-end exception-to-investigation workflow. It builds on the existing case, evidence, deterministic RCA, audit, and AI services without replacing the architecture.

## Delivered

- Exception detail can acknowledge an open exception.
- Exception detail can create an investigation case from the exception.
- Existing linked cases can be opened directly from the exception.
- Case workspace now supports the existing lifecycle: start, resolve, reopen.
- Resolution uses the existing `ResolutionCode` enum rather than an invalid free-form value.
- A customer-facing resolution-options endpoint exposes the authoritative enum values.
- Case assignment is available to operational roles.
- Investigation notes are persisted through the existing case-note API.
- Evidence snapshots and relevance are displayed in the investigation workspace.
- Deterministic RCA remains the authoritative financial explanation.
- AI investigation remains read-only and explicitly advisory, with facts, findings, hypotheses, recommendations, evidence references, and uncertainty shown to the operator.
- Existing audit events remain the system of record for workflow actions.

## Files changed for v0.5

- `backend/app/api/routes/cases.py`
- `backend/app/cases/service.py`
- `backend/tests/test_e2e_auth_workflow.py`
- `frontend/app/cases/[id]/page.tsx`
- `frontend/app/exceptions/[id]/page.tsx`
- `frontend/app/globals.css`

No new database migration was needed because the required case, note, event, evidence, RCA, and audit persistence already exists.

## Verification

- Backend end-to-end workflow: **4 passed**
- Frontend tests: **21 passed**
- Frontend source hygiene: **34 files passed**
- Backend Python compilation: **passed**

Frontend `typecheck`/production build was not run because the cleaned repository intentionally does not include `node_modules` and this environment cannot be assumed to have the npm dependency tree installed. The source-level test and hygiene checks pass.

## End-to-end workflow

`Exception → Acknowledge → Open investigation → Start → Assign → Add note → Review evidence/RCA → AI advisory → Resolve with valid resolution code → Reopen when necessary → Audit trail`
