# RCAA v0.9 Razorpay Billing Hardening

This stage hardens the existing v0.9 Razorpay subscription integration against the documented Razorpay Subscriptions API contract.

## Changes

- Validate Razorpay plan IDs before network calls using the documented `plan_<14 alphanumeric>` shape.
- Reject invalid subscription `total_count` values before network calls.
- Keep subscription creation bounded by `total_count`; do not send both `total_count` and `end_at`.
- Add provider-side subscription fetch support.
- Keep cycle-end cancellation explicit.
- Make Checkout HMAC verification accept an explicit server secret and reject empty inputs.
- Keep verification server-side and tied to the authenticated tenant subscription.
- Preserve raw webhook-body signature verification and webhook idempotency.

## Verification

The hardening regression suite covers the documented create-subscription payload, invalid plan rejection, explicit Checkout signature verification, fetch/cancel endpoints, webhook payment synchronization, and duplicate webhook idempotency.
