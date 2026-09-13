# RCAA v0.15 Enterprise Release

This release adds enterprise identity and automatic provider synchronization capabilities on top of v0.14.

## Enterprise SSO
- Generic OpenID Connect (OIDC) configuration per merchant workspace.
- PKCE S256 authorization-code flow with expiring, one-time login state.
- Issuer allow-list support.
- Verified-email and allowed-domain checks.
- Just-in-time user provisioning with a non-admin default role.
- Client secrets encrypted at rest.
- Admin configuration UI and login entry point.
- Access token is never placed in a browser-readable callback cookie; the callback establishes the HttpOnly refresh session and the frontend obtains a short-lived access token through the existing refresh endpoint.

Required environment variables: `SSO_ENABLED`, `SSO_FRONTEND_URL`, `SSO_CALLBACK_URL`, and optionally `SSO_ALLOWED_ISSUERS`.

## Automatic provider synchronization
- Existing Razorpay connector now automatically runs deterministic reconciliation after provider ingestion inside the durable worker.
- Scheduled connector jobs remain merchant-scoped and idempotent.
- Sync status and reconciliation summary are persisted with the connector job result.

## Scope note
This release provides a production-ready OIDC integration surface and an automatic Razorpay provider connector. It does not claim universal bank-feed support; bank/API connectivity remains provider-specific and must be implemented/tested per provider.
