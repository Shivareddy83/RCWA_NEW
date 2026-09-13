# RCWA 48 — v0.10.4 Security Hardening Release

## Scope

This release closes the major production-security gaps identified in the previous security review. It preserves the existing RCAA financial/reconciliation architecture and does not introduce new reconciliation behavior.

## Delivered controls

| Area | v0.10.4 result |
|---|---|
| File-upload protection | Hardened: body/upload/row/column/cell limits |
| Login rate limiting | Implemented: DB-backed, hashed keys, 429 responses |
| MFA | Implemented: encrypted TOTP, forced-enrollment capability, MFA login challenge |
| Session management | Hardened: server sessions, short JWTs, HttpOnly rotating refresh cookies, replay detection |
| Data encryption | TOTP secret encrypted at application layer; production DB/backups require infrastructure encryption |
| Data retention | Controlled retention script for raw upload/webhook artifacts |
| Metrics exposure | Bearer protected in production and not routed through Caddy |
| Razorpay IP allowlisting | Implemented with exact IP/CIDR matching; signature verification remains mandatory |
| Webhook ordering | Provider subscription lifecycle updates reject older event timestamps |
| Security headers | HTTPS/HSTS/CSP and browser security headers retained |

## Migration

- Alembic `0016`: rate limiting + Razorpay lifecycle fields
- Alembic `0017`: authentication sessions + user MFA fields

## Release verification

The release must pass:

- Python compilation
- Alembic upgrade/downgrade
- complete backend regression suite
- focused authentication/session/MFA tests
- upload-limit tests
- webhook signature/IP/order tests
- frontend typecheck/build/tests
- release ZIP hygiene check

Docker runtime verification is environment-dependent. Do not claim a live container/browser test unless those runtimes were actually executed.
