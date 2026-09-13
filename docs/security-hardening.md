# v0.10.4 Production Security Hardening

## Security objective

RCAA is a finance-operations product. The security model therefore separates **financial truth**, **identity/session security**, **provider integration security**, and **infrastructure controls**.

The deterministic reconciliation engine remains unchanged. AI remains advisory/read-only.

## Identity and authentication

- Passwords use Scrypt with per-password random salts.
- JWT access tokens use an explicit HS256 allow-list and required claims.
- Access tokens are short-lived; production should use a 15-minute lifetime unless an operational reason requires another value.
- Successful credential authentication creates a server-side `auth_sessions` record.
- Access tokens contain the session ID and are rejected after the session is revoked or expired.
- Refresh tokens are cryptographically random, stored only as HMAC hashes, and delivered in an HttpOnly cookie.
- Refresh tokens rotate on every refresh.
- Reuse of a rotated refresh token revokes the complete token family.
- Logout revokes the active session and clears the refresh cookie.
- Session listing/revocation is scoped to the authenticated user.
- No refresh token is exposed to JavaScript.

## MFA

RCAA supports TOTP MFA without storing the authenticator secret in plaintext.

- TOTP secrets are encrypted with Fernet using `MFA_ENCRYPTION_KEY`.
- MFA setup requires password re-authentication for an already authenticated user.
- Login with MFA enabled requires a second factor before an access session is created.
- MFA challenges are short-lived and purpose-bound.
- MFA verification is rate-limited.
- Enabling MFA revokes no existing session; disabling MFA revokes all sessions for that user.
- For production, set `MFA_REQUIRED_ROLES=ADMIN` only after all existing administrators have enrolled, or use the forced-enrollment login flow.

## Brute-force and abuse protection

Database-backed rate limits protect login, signup, demo requests, and MFA verification. Limiter keys are HMAC-hashed, so raw IP/email values are not stored in the rate-limit table.

Uploads are bounded by:

- global request body size
- 5 MiB default upload size
- 10,000 rows per customer upload
- 100 columns per upload
- 10,000 characters per text cell

CSV/XLSX parsing is bounded before financial persistence.

## Tenant and authorization controls

- RBAC is enforced server-side.
- Resource queries are merchant-scoped.
- Cross-tenant resources return safe not-found responses where appropriate.
- Financial source records are protected by application immutability guards.
- Audit events are append-oriented and hash-chain protected.

## Razorpay security

Razorpay checkout/payment signatures are verified server-side.

Razorpay webhooks require HMAC verification over the raw request body. Event IDs provide idempotency. An optional CIDR-aware source-IP allowlist provides network defense in depth.

Subscription lifecycle processing is monotonic using provider event timestamps, reducing the risk of an older out-of-order webhook reverting a newer state.

Keep the allowlist current when Razorpay changes its published infrastructure. Signature verification remains mandatory even when an IP allowlist is configured.

## Metrics and observability

- Production `/metrics` requires a bearer token.
- Production Caddy does not expose `/metrics` publicly.
- Metric labels are allow-listed to prevent high-cardinality leakage.
- Logs do not intentionally contain passwords, API keys, refresh tokens, or MFA secrets.
- Request IDs are propagated for operational correlation.

## Data protection at rest

Application-level encryption is intentionally limited to secrets that must be protected independently of database storage, such as TOTP enrollment secrets.

For customer financial data, production infrastructure must provide:

- PostgreSQL encryption at rest
- encrypted automated backups
- encrypted object storage if used
- TLS for database connections where supported
- least-privilege database roles
- restricted network access to PostgreSQL
- secret-manager based credential delivery
- tested restore procedures

Do not put customer database passwords, Razorpay secrets, AI API keys, or MFA encryption keys in the Git repository.

## Retention

`UPLOAD_RETENTION_DAYS` controls staged customer upload artifacts. `RAW_DATA_RETENTION_DAYS` controls webhook/raw-artifact retention maintenance.

Run `scripts/retention_cleanup.py --dry-run` first. After policy approval, run it from a controlled scheduler. The cleanup removes raw upload rows and webhook payload details while retaining normalized financial records and audit history.

Retention periods must be aligned with the customer's contractual, accounting, legal, and regulatory requirements. The defaults are engineering defaults, not legal advice.

## Production secret rotation

Rotate:

- `AUTH_SECRET`
- `MFA_ENCRYPTION_KEY`
- `METRICS_AUTH_TOKEN`
- `AUTH_BOOTSTRAP_TOKEN`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`
- external AI credentials

A key rotation plan must account for active sessions. Rotating `AUTH_SECRET` invalidates JWTs and refresh-token hashes; this is a deliberate security boundary.

## Network / edge controls

Production topology should be:

`Internet -> Caddy/TLS -> frontend/backend private network -> PostgreSQL`

Do not publish PostgreSQL, backend port 8000, or frontend port 3000 directly to the Internet.

For internet-facing deployments, add a managed WAF/DDoS layer and centralized alerting appropriate to expected traffic.

## Deferred product-security work

The following are intentionally outside this hardening stage:

- email verification
- password reset/recovery
- OIDC/SSO
- enterprise device management
- full session/device UI
- managed WAF/DDoS implementation
- external SIEM integration

These should be added without weakening the deterministic financial controls.
