# RCAA v0.9 Razorpay Billing

RCAA v0.9 supports optional recurring Razorpay billing. The existing manual billing path remains available when `BILLING_PROVIDER=manual`.

## Configure

Set:

```text
BILLING_PROVIDER=razorpay
RAZORPAY_KEY_ID=<test-or-live-key-id>
RAZORPAY_KEY_SECRET=<test-or-live-key-secret>
RAZORPAY_WEBHOOK_SECRET=<webhook-secret>
RAZORPAY_PLAN_STARTER=<plan-id>
RAZORPAY_PLAN_GROWTH=<plan-id>
RAZORPAY_PLAN_BUSINESS=<plan-id>
```

Create the three monthly plans with `scripts/create_razorpay_plans.py`, then copy the printed plan IDs into the environment. Test keys and live keys must not be mixed.

## Checkout flow

```text
Customer selects plan
  -> RCAA creates local pending invoice
  -> RCAA creates Razorpay subscription
  -> Browser opens Razorpay Standard Checkout
  -> RCAA verifies checkout signature
  -> Razorpay webhook confirms subscription state/charge
  -> RCAA marks invoice/subscription state
```

The checkout signature is verified server-side. Webhooks are also signature-verified and idempotent using the existing webhook event table.

## Webhook endpoint

```text
POST /api/v1/webhooks/razorpay
```

Configure the Razorpay webhook to send subscription lifecycle events, including:

- `subscription.authenticated`
- `subscription.activated`
- `subscription.charged`
- `subscription.pending`
- `subscription.halted`
- `subscription.resumed`
- `subscription.cancelled`
- `subscription.completed`

## Operational rule

Razorpay is the payment authority. RCAA never activates a Razorpay subscription merely because the browser reports success. Browser verification is recorded, while signed server-side webhooks drive recurring subscription and invoice state.
