# RCAA v0.7 — Production Deployment & Operations

## Scope

This release adds the production deployment layer only. The existing FastAPI, Next.js, PostgreSQL, worker, reconciliation, case, AI, reports, notifications, onboarding, and data-onboarding architecture is preserved.

## Added

- `docker-compose.prod.yml` production override
- Caddy TLS/reverse-proxy configuration
- production environment template
- fail-fast production environment validation
- repeatable production deployment script
- PostgreSQL backup script
- guarded PostgreSQL restore script
- service smoke-test script
- production operations regression tests
- this release report

## Deployment model

Internet → Caddy → Next.js / FastAPI → PostgreSQL + database-backed worker.

PostgreSQL, FastAPI, worker, and frontend are not directly published to the host in the production override. Caddy owns ports 80/443.

## Safety

The production validator rejects placeholder secrets, weak authentication secrets, localhost CORS origins, and non-PostgreSQL production databases. Database restore requires an explicit `CONFIRM_RESTORE=YES` environment variable.

## Verification

The production operations tests verify the deployment files and validator behavior. Full Docker execution remains dependent on a host with Docker Engine and network access for image builds.
