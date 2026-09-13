# RCAA v0.9 — Real Razorpay Subscription Billing

## Scope

v0.9 converts the v0.8 manual billing foundation into an optional real recurring-billing path using Razorpay Subscriptions, while preserving the manual provider fallback.

## Delivered

- `BILLING_PROVIDER=manual|razorpay` configuration.
- Razorpay monthly plan ID configuration for Starter, Growth, and Business.
- Razorpay subscription creation from the customer billing page.
- Server-side checkout signature verification.
- Razorpay subscription cancellation at cycle end.
- Subscription lifecycle webhook handling.
- Recurring charge → invoice payment synchronization.
- Subscription pending/halted → `PAST_DUE` handling.
- Subscription cancellation/completion/expiry → `CANCELLED` handling.
- Provider/customer/payment identifiers persisted in billing records.
- Signed webhook idempotency through the existing webhook event store.
- Billing notifications for successful charges and payment problems.
- Manual activation/mark-paid actions disabled when Razorpay billing is enabled.
- Razorpay plan bootstrap helper script.
- Customer billing UI integration with Razorpay Checkout.
- v0.9 regression tests.

## Verification

- v0.9 tests: 4/4 passed.
- Existing backend suite from `backend/`: 12/12 passed.
- Frontend tests: 21/21 passed.
- Frontend source hygiene: 37 files passed.
- Python compilation: passed.
- Alembic migrations `0001 → 0014`: clean upgrade reached `0014` head.

## Environment limitation

A real Razorpay network payment was not executed because no merchant test credentials were supplied. The integration is implemented and tested with deterministic HTTP/webhook fixtures; live/test-mode verification requires the RCAA operator's Razorpay test account and configured plan IDs.
