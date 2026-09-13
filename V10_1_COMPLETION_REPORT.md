# RCAA v0.10.1 — Customer Activation & Sales Operations

## Built on
RCAA v0.10 Product Launch Foundation.

## Product additions
- Workspace activation endpoint with trial status, remaining days and activation score.
- Activation checklist for onboarding, first data upload, first reconciliation exception and paid-plan conversion.
- Customer-facing Activation page and navigation entry.
- Admin demo-lead status workflow: NEW, CONTACTED, QUALIFIED, WON, LOST.
- Persistent lead status updates remain tenant-safe and admin-only.
- No financial truth, reconciliation rules or Razorpay billing behavior was changed.

## Design intent
This stage turns the public signup and demo funnel into an observable activation workflow without introducing background services or speculative automation.

## Verification
- Backend full suite executed after changes.
- Product activation and lead workflow regression tests executed.
- Frontend source hygiene executed.
- Alembic chain remains at 0015; this stage requires no schema migration because it uses existing subscription, onboarding, upload, exception and demo-lead data.
