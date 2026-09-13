# RCAA v0.11 — Launch Readiness

## Implemented
- Secure forgot-password and reset-password flow.
- One-time, expiring reset tokens stored as hashes only.
- Existing sessions revoked after password reset.
- SMTP delivery abstraction with generic anti-enumeration response.
- Development-only reset token exposure for local testing.
- Guided first-reconciliation path in onboarding.
- First-reconciliation messaging: connect/upload → reconcile → investigate → resolve → report.
- Exception/case SLA due timestamps and SLA status endpoint.
- Severity-based SLA defaults: critical 4h, high 24h, medium 72h, low 120h.
- Dashboard and onboarding links for guided setup.

## Product effect
The product now closes two common SaaS activation gaps: account recovery and first-time user confusion. SLA turns exception handling into an operational queue rather than a passive mismatch report.
