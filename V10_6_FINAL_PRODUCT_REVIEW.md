# RCWA/RCAA v0.10.6 Final Release Review

## Release decision

**Sellable for a controlled B2B pilot / managed SaaS launch: YES.**

**Not yet equivalent to a mature enterprise finance platform: NO.**

This release closes two material product-engineering gaps found in the final review:
1. Bank transactions were ingested and stored but were not actually included in reconciliation.
2. Payment-to-settlement matching could scan the complete settlement set for every payment, creating O(P×S) behavior at scale.

## v0.10.6 changes

- Added deterministic bank-to-settlement reconciliation using settlement ID/UTR/reference first, then bounded amount/currency/date matching.
- Added bank settlement mismatch, bank-without-settlement and ambiguous-bank-match cases.
- Added deterministic RCA/evidence support for the new bank exceptions.
- Optimized settlement matching with pre-built provider/reference/time indexes.
- Fixed a reconciliation metrics bug in the expected-refund path that referenced the match decision before it existed.
- Bumped release version to 0.10.6.

## What the product now solves

For an e-commerce/finance team, the core control is:

**Payment captured -> settlement expected -> bank credit received -> exception -> evidence -> deterministic RCA -> human resolution -> audit/report.**

Supported customer file onboarding currently covers payments, settlements, refunds and bank transactions through CSV/XLSX, with bounded uploads and mapping/validation.

## Strong areas

- Deterministic financial calculations; AI is advisory.
- Tenant-scoped authorization and financial records.
- Scrypt passwords, short-lived access tokens, rotating HttpOnly refresh tokens and replay detection.
- TOTP MFA with encrypted secrets and forced-enrollment capability.
- Login/signup/demo/MFA rate limiting.
- Upload size/row/column/cell limits.
- Razorpay checkout signature verification and webhook HMAC/idempotency/order protection.
- Optional Razorpay IP/CIDR allowlisting.
- Append-oriented audit and evidence/RCA chain.
- Durable SQL jobs, retries, leases, stale recovery and graceful worker shutdown.
- PostgreSQL backup verification and application rollback without unsafe schema downgrade.
- Health/readiness/version release gates.
- Resource limits and starter Prometheus/Alertmanager rules.
- Caddy TLS edge with private backend/frontend/PostgreSQL services.
- Customer onboarding, activation, billing, customer-success and admin sales workflow.
- Razorpay subscription billing foundation.
- Reports, CSV exports and notifications.

## Material gaps before broad self-service SaaS scale

These are **not hidden** and are intentionally separate from this release:

- Email verification.
- Password reset/recovery.
- Production email delivery/templates.
- OIDC/SSO/SCIM for enterprise customers.
- Full session/device management UI.
- Managed WAF/DDoS and centralized SIEM.
- Automated bank/API connectors; current onboarding is file based.
- Direct order-system ingestion/order table. The current payment model can carry provider order references, but there is no dedicated customer order source model.
- Rich accounting/ERP integrations and journal export.
- Chargeback/dispute lifecycle support beyond the current core refund/reconciliation model.
- Production-grade multi-replica load-balancer deployment. The current reliability contract explicitly requires multiple replicas/load balancing for strict zero-downtime.
- Formal legal/privacy/terms/support surfaces should be added before public self-service launch.

## Customer fit

Best first customers:
- Indian D2C/e-commerce businesses.
- Finance/ops teams manually reconciling Razorpay and bank statements.
- Companies with enough monthly payment volume that reconciliation consumes recurring analyst time.
- CA/finance-operations service firms that want a repeatable reconciliation workflow.

The strongest sales message is not “AI reconciliation.” It is:

**“We tell you exactly which payment/settlement/bank transactions do not tie, why they do not tie, what evidence proves it, and what your team should do next — without allowing AI to alter financial truth.”**

## Competitive position

The category is real and competitive. Current products already market payment/settlement reconciliation, bank reconciliation, GST/fee analysis and exception workflows. Razorpay itself also offers reconciliation-related products. The differentiator therefore cannot simply be “automated reconciliation.”

The defensible wedge for RCAA is the combination of:
- deterministic financial truth,
- explainable evidence-backed RCA,
- investigation/case workflow,
- auditability,
- customer self-service onboarding,
- Razorpay-first Indian-market focus,
- and a managed-service option for customers who do not want to operate the workflow themselves.

## Recommended commercial model

Use the existing Starter/Growth/Business subscription structure for software revenue, but initially sell with a **paid onboarding / reconciliation diagnostic**.

A practical launch model:
- Diagnostic: free or low-cost, based on a small historical sample.
- Setup/onboarding: one-time fee.
- Monthly subscription: ₹9,999 / ₹24,999 / ₹49,999 tiers already represented in the product.
- Optional managed reconciliation: recurring service fee or higher plan.
- Enterprise integrations: separately quoted.

Revenue examples:
- 10 Starter customers = ₹99,990 MRR.
- 10 Growth customers = ₹249,990 MRR.
- 10 Business customers = ₹499,990 MRR.
- A mixed base of 5 Starter + 5 Growth + 2 Business = ₹249,990 MRR before onboarding/services.

These are gross subscription examples, not guaranteed revenue.

## End-user satisfaction test

A finance user will be satisfied if the first run answers four questions quickly:
1. What money did we receive?
2. What money should we have received?
3. Which transactions do not match?
4. Why, with evidence, and who needs to act?

The product now supports the core workflow. Satisfaction will still fall if a customer expects automatic live bank/gateway/ERP connections, order-level reconciliation, GST/accounting integration or enterprise identity on day one.

## Final recommendation

**Do not restart the architecture.**

Ship v0.10.6 as the controlled commercial pilot release. Sell the current product around the narrow, measurable problem of payment/settlement/bank reconciliation and exception investigation.

Treat email recovery, order/ERP integrations, automated bank/provider connectors, enterprise SSO, legal/public trust pages, managed WAF/SIEM and strict multi-replica zero-downtime as the next product expansion rather than pretending they already exist.
