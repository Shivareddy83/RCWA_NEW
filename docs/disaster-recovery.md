# Disaster Recovery and Backup / Restore

Stage 13 documents a single-region/local deployment recovery model. It does not claim multi-region enterprise DR.

## Assumptions

- **RPO:** determined by the configured PostgreSQL backup frequency; no external backup service is implemented by this repository.
- **RTO:** determined by database restore time plus container startup/migration time; no measured production RTO is claimed.
- The PostgreSQL volume is persistent in Docker Compose.
- Audit events and financial records remain in PostgreSQL.

## Backup

Use PostgreSQL-native tooling from a trusted operator environment:

```sh
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > rcaa-backup.dump
```

For production, store the dump outside the Docker host and protect it with the organization's backup encryption/access controls. The repository does not implement external backup retention or encryption.

## Restore verification

Restore into a **new, isolated database first**. Do not overwrite the only financial database to test a backup.

```sh
createdb rcaa_restore_test
pg_restore --clean --if-exists --dbname=rcaa_restore_test rcaa-backup.dump
```

Then run application read-only verification and the financial regression suite against the restored copy before considering the backup usable.

The exact restore workflow is documented but **not executed in the current environment**.

## Rollback distinctions

- **Application rollback:** deploy a previously validated application image.
- **Schema rollback:** use an explicitly supported Alembic downgrade only after assessing compatibility and data impact.
- **Financial-data restoration:** restore from a verified PostgreSQL backup into an isolated environment first. Never delete financial records as a normal rollback mechanism.

A failed migration should be investigated and repaired using migration tooling or restored from backup; destructive manual table deletion is not the normal recovery path.
