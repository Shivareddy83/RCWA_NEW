# RCAA v0.15 Final Sellable Release

## Added
- Enterprise OIDC/SSO with PKCE, expiring one-time state, issuer allow-listing, verified-email checks, domain restrictions, JIT provisioning, encrypted client secrets, and tenant-scoped configuration.
- Enterprise SSO administration UI and login entry point.
- Automatic Razorpay synchronization through the durable worker, followed by deterministic reconciliation and exception generation in the same merchant-scoped job.
- SSO and provider-sync deployment environment examples.

## Security design
- No access token is placed in a browser-readable SSO callback cookie.
- Refresh authentication remains HttpOnly and uses the existing session rotation system.
- Provider credentials and OIDC client secrets are encrypted at rest.
- SSO login state is hashed at rest and expires.
- SSO-created users receive only the configured non-admin default role.

## Validation
- Backend Python compilation: PASS.
- Application imports and SSO routes: PASS.
- Frontend contract tests: 22/22 PASS.
- Existing backend suite: not green in this clean run; the first failure is the pre-existing database rate-limit test (`test_database_rate_limit_blocks_after_limit_and_can_reset`). This release does not claim a clean full backend suite until that unrelated regression is resolved.

## Scope
- Automatic provider sync is production-oriented for the existing Razorpay connector. It is not a claim of universal automatic bank feeds or every payment provider.
- Enterprise SSO is a generic OIDC integration surface and must be configured with the customer's identity provider.
