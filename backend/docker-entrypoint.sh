#!/bin/sh
set -eu

export PYTHONPATH=/app

# Docker service discovery can transiently lag container startup.  Resolve and
# connect to PostgreSQL before Alembic so migrations never race the DB network.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python - <<'PY'
import os
import socket
import time
from urllib.parse import urlparse

url = os.environ["DATABASE_URL"]
host = urlparse(url).hostname
port = urlparse(url).port or 5432
if not host:
    raise SystemExit("DATABASE_URL does not contain a database host")

deadline = time.monotonic() + 60
last_error = None
while time.monotonic() < deadline:
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for family, socktype, proto, _, sockaddr in addresses:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(3)
                sock.connect(sockaddr)
        print(f"Database endpoint {host}:{port} is reachable.")
        break
    except OSError as exc:
        last_error = exc
        time.sleep(2)
else:
    raise SystemExit(f"Database endpoint {host}:{port} is unreachable after 60s: {last_error}")
PY

  alembic upgrade head
fi

exec "$@"
