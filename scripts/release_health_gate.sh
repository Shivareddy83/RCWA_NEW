#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${RCAA_BASE_URL:-https://app.example.com}"
ATTEMPTS="${HEALTH_ATTEMPTS:-30}"
DELAY="${HEALTH_DELAY_SECONDS:-2}"
for endpoint in /health /ready /version; do
  ok=0
  for ((i=1;i<=ATTEMPTS;i++)); do
    code="$(curl -ksS -o /tmp/rcaa_health_body -w '%{http_code}' "$BASE_URL$endpoint" || true)"
    if [[ "$code" == "200" ]]; then ok=1; break; fi
    sleep "$DELAY"
  done
  if [[ "$ok" != "1" ]]; then echo "Health gate failed: $endpoint" >&2; cat /tmp/rcaa_health_body 2>/dev/null || true; exit 1; fi
done
echo "Release health gate PASS: $BASE_URL"
