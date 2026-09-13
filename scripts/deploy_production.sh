#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"
ENV_FILE="${ENV_FILE:-.env.production}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE. Copy deploy/.env.production.example and configure it." >&2; exit 1; }
set -a; source "$ENV_FILE"; set +a
python3 scripts/validate_production_env.py
export BUILD_ID="${BUILD_ID:-$(date -u +%Y%m%d%H%M%S)}"
export GIT_COMMIT_SHA="${GIT_COMMIT_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
export RCAA_BACKEND_IMAGE="${RCAA_BACKEND_IMAGE:-rcaa-backend:${BUILD_ID}}"
export RCAA_FRONTEND_IMAGE="${RCAA_FRONTEND_IMAGE:-rcaa-frontend:${BUILD_ID}}"
export RCAA_PREVIOUS_BACKEND_IMAGE="${RCAA_PREVIOUS_BACKEND_IMAGE:-}"
export RCAA_PREVIOUS_FRONTEND_IMAGE="${RCAA_PREVIOUS_FRONTEND_IMAGE:-}"

echo "[1/6] Pre-release database backup"
ENV_FILE="$ENV_FILE" ./scripts/backup_postgres.sh

echo "[2/6] Build immutable release images"
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml build backend frontend
docker tag "$(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml images -q backend | head -1)" "$RCAA_BACKEND_IMAGE"
docker tag "$(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml images -q frontend | head -1)" "$RCAA_FRONTEND_IMAGE"

echo "[3/6] Start/update database and application"
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml up -d postgres
# Migration runs in the backend entrypoint. Keep the migration step isolated before routing traffic.
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml up -d backend worker frontend caddy

echo "[4/6] Wait for health/readiness gates"
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml up -d --wait
RCAA_BASE_URL="${RCAA_BASE_URL:-https://${RCAA_DOMAIN}}" ./scripts/release_health_gate.sh

echo "[5/6] Persist release manifest"
mkdir -p releases
cat > "releases/${BUILD_ID}.env" <<EOF
BUILD_ID=$BUILD_ID
GIT_COMMIT_SHA=$GIT_COMMIT_SHA
RCAA_BACKEND_IMAGE=$RCAA_BACKEND_IMAGE
RCAA_FRONTEND_IMAGE=$RCAA_FRONTEND_IMAGE
EOF
chmod 600 "releases/${BUILD_ID}.env"

echo "[6/6] Release PASS: $BUILD_ID"
echo "For rollback: ROLLBACK_BUILD_ID=<known-good-build> ./scripts/rollback_production.sh"
