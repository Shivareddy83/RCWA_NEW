#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then echo "Usage: $0 path/to/rcaa_backup.dump" >&2; exit 1; fi
set -a; source "$ENV_FILE"; set +a
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
VERIFY_DB="${POSTGRES_DB}_restore_verify_${STAMP}"
cleanup() { docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$VERIFY_DB" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Checking PostgreSQL dump catalog..."
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres pg_restore --list < "$BACKUP_FILE" >/dev/null

echo "Creating isolated restore database: $VERIFY_DB"
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres createdb -U "$POSTGRES_USER" "$VERIFY_DB"
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$VERIFY_DB" --clean --if-exists --no-owner < "$BACKUP_FILE"

echo "Running restored-database integrity checks..."
COUNT="$(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$VERIFY_DB" -Atqc "SELECT count(*) FROM alembic_version")"
[[ "$COUNT" == "1" ]] || { echo "Restore verification failed: alembic_version missing" >&2; exit 1; }
VERSION="$(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" -d "$VERIFY_DB" -Atqc "SELECT version_num FROM alembic_version")"
echo "Restore verification PASS; alembic version: $VERSION"
