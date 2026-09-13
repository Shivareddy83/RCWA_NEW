# RCAA v0.12 — Connectivity & Automation

## Implemented
- Encrypted per-merchant connector credentials.
- Razorpay live API connector.
- Combined settlement reconciliation ingestion using Razorpay's settlement recon API.
- Provider payments, refunds and settlement lines normalized through the same deterministic ingestion boundary.
- Connector test endpoint.
- Manual sync job endpoint.
- Durable background SYNC_CONNECTOR jobs with retries, leases and worker execution.
- Scheduled connector sync when enabled.
- Connector status, last sync, next sync and sync summary.

## Security
- Provider credentials are encrypted at rest with the existing Fernet key infrastructure.
- Credentials are never returned by connector APIs.
- Job payloads scrub secrets before persistence.
- Tenant scope is enforced on connector access and jobs.

## Boundary
Razorpay is the supported live connector in v0.12. Stripe, Cashfree and PayU are deliberately not represented as falsely-working integrations; their UI positions are reserved for subsequent provider adapters.
