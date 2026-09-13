# RCAA v0.10 — Product Launch Foundation

## Built on
RCAA v0.9.1 Razorpay billing hardening.

## Product additions
- Public product landing page at `/` for unauthenticated visitors.
- Public pricing for Trial, Starter, Growth and Business.
- Self-service workspace signup at `/signup`.
- Signup creates a tenant, first ADMIN user, onboarding record and Trial subscription.
- Signup returns the existing RCAA access token and sends the customer directly into onboarding.
- Demo request page at `/demo`.
- Persistent `DemoLead` storage with status and transaction-volume context.
- Admin-only Demo Leads view inside the authenticated console.
- Product messaging separates deterministic financial truth from AI advisory behavior.
- Existing authenticated operations console remains intact.

## Billing
Razorpay remains the payment provider when `BILLING_PROVIDER=razorpay`. Product pages do not fake payment collection; paid subscription checkout continues through the existing v0.9.1 Razorpay flow.

## Migration
Added Alembic revision `0015_product_leads` for the demo lead table and indexes. The migration is safe against the existing initial schema behavior that creates ORM tables during revision `0001`.

## Verification
- Backend: 192/192 tests passed.
- v0.10 product tests: 4/4 passed.
- Frontend: 21/21 tests passed.
- Frontend source hygiene: 42 files passed after the final admin-leads page addition.
- Alembic: fresh database upgraded through `0015` successfully.
- `npm run build`: unavailable in this clean package because `node_modules` is intentionally excluded, so the `next` binary is not present in the environment.
