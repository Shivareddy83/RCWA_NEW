#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT_DIR"
ENV_FILE="${ENV_FILE:-.env.production}"; BUILD="${ROLLBACK_BUILD_ID:-}"
[[ -n "$BUILD" ]] || { echo "Set ROLLBACK_BUILD_ID to a known-good release." >&2; exit 1; }
MANIFEST="releases/${BUILD}.env"; [[ -f "$MANIFEST" ]] || { echo "Missing release manifest: $MANIFEST" >&2; exit 1; }
set -a; source "$ENV_FILE"; source "$MANIFEST"; set +a
export BUILD_ID="$BUILD"; export RCAA_BACKEND_IMAGE; export RCAA_FRONTEND_IMAGE

echo "Rolling application images back to $BUILD. This does not downgrade the database schema."
docker image inspect "$RCAA_BACKEND_IMAGE" >/dev/null
docker image inspect "$RCAA_FRONTEND_IMAGE" >/dev/null
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml up -d backend worker frontend caddy
docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml up -d --wait
RCAA_BASE_URL="${RCAA_BASE_URL:-https://${RCAA_DOMAIN}}" ./scripts/release_health_gate.sh
echo "Rollback PASS: $BUILD"
