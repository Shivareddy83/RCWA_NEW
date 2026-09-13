# RCAA v0.13 Final Release Report

## Scope
v0.11, v0.12 and v0.13 are packaged as one final commercial release. The release builds on v0.10.6 rather than replacing the architecture.

## Version progression
### v0.11 — Launch readiness
- Password recovery.
- Guided onboarding.
- SLA controls.
- Customer activation UX.

### v0.12 — Connectivity automation
- Encrypted connector registry.
- Razorpay API connector.
- Automated provider ingestion through durable worker jobs.
- Scheduled sync.

### v0.13 — Competitive FinOps positioning
- Connector administration UI.
- Operational SLA surface.
- Guided first reconciliation.
- Product documentation describing the deterministic/AI boundary and competitive wedge.
- Explicit provider-adapter boundary so unsupported integrations are not falsely advertised.

## Verification
- Backend tests: 20 passed.
- Fresh Alembic database migration: 0018 head.
- Python AST/compile checks: passed.
- Existing reconciliation, security, auth and billing tests remain green.
- Frontend dependency installation/build was not executed in this tool environment because frontend node_modules is not present and Docker is unavailable here. The production Dockerfile remains the source of truth for clean frontend dependency installation.

## Production claim
This release is appropriate for controlled commercial pilots and SMB/mid-market sales. Do not advertise enterprise SSO, SOC 2, automatic bank feeds, or unsupported payment-gateway integrations until those controls/connectors are implemented and tested.
