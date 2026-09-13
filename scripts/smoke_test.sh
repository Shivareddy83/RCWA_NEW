#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${RCAA_BASE_URL:-http://localhost:8000}"

check() {
  local path="$1"
  curl --fail --silent --show-error --max-time 10 "$BASE_URL$path" >/dev/null
  echo "PASS $path"
}

check /health
check /ready
check /version
