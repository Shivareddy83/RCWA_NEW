# Production Operations

## Deploy

1. Copy `deploy/.env.production.example` to `.env.production`.
2. Set a real domain and strong secrets.
3. Point DNS for the domain to the deployment host.
4. Run `ENV_FILE=.env.production ./scripts/deploy_production.sh`.
5. Caddy obtains and renews TLS certificates automatically for a public DNS name.

## Verify

Use `RCAA_BASE_URL=https://app.example.com ./scripts/smoke_test.sh`.

Also inspect:

```sh
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 backend worker frontend caddy postgres
```

## Backups

Run `ENV_FILE=.env.production ./scripts/backup_postgres.sh`. Keep backups outside the application host when possible and test restores regularly.

## Restore

Stop customer traffic first, verify the backup, then run:

```sh
CONFIRM_RESTORE=YES ENV_FILE=.env.production ./scripts/restore_postgres.sh ./backups/rcaa_YYYYMMDDTHHMMSSZ.dump
```

After restore, run migrations and the smoke test before reopening traffic.

## Release identity

Set `RCAA_VERSION`, `BUILD_ID`, and `GIT_COMMIT_SHA`. `/version` exposes these non-secret identifiers.
