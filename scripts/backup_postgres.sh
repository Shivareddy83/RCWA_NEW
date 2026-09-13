#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"
ENV_FILE="${ENV_FILE:-.env.production}"; BACKUP_DIR="${BACKUP_DIR:-./backups}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
set -a; source "$ENV_FILE"; set +a
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; FILE="$BACKUP_DIR/rcaa_${STAMP}.dump"
echo "Creating PostgreSQL custom-format backup..."
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$FILE"
chmod 600 "$FILE"
pg_restore --list "$FILE" >/dev/null
sha256sum "$FILE" > "$FILE.sha256"
chmod 600 "$FILE.sha256"
if [[ -n "${BACKUP_RETENTION_COUNT:-}" ]]; then
  mapfile -t dumps < <(ls -1t "$BACKUP_DIR"/rcaa_*.dump 2>/dev/null || true)
  for old in "${dumps[@]:${BACKUP_RETENTION_COUNT}}"; do rm -f -- "$old" "$old.sha256"; done
fi
echo "Backup verified: $FILE"
