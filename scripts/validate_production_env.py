#!/usr/bin/env python3
"""Fail fast on unsafe production environment configuration."""
from __future__ import annotations

import os
import re
import sys
import base64

PLACEHOLDERS = {"", "CHANGE_ME", "replace-with-a-strong-local-password", "replace-with-a-random-secret-at-least-32-characters", "replace-with-a-random-bootstrap-token"}

def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if os.getenv("APP_ENV", "").lower() not in {"production", "prod"}:
        fail("APP_ENV must be production")
    required = ["RCAA_DOMAIN", "POSTGRES_PASSWORD", "DATABASE_URL", "AUTH_SECRET", "AUTH_BOOTSTRAP_TOKEN", "CORS_ORIGINS", "TRUST_PROXY_HEADERS", "METRICS_AUTH_TOKEN", "MFA_ENCRYPTION_KEY"]
    for name in required:
        value = os.getenv(name, "").strip()
        if value in PLACEHOLDERS:
            fail(f"{name} is missing or still contains a placeholder")
    if len(os.environ["AUTH_SECRET"]) < 32:
        fail("AUTH_SECRET must be at least 32 characters")
    try:
        if len(base64.urlsafe_b64decode(os.environ["MFA_ENCRYPTION_KEY"].encode())) != 32:
            fail("MFA_ENCRYPTION_KEY must be a valid 32-byte Fernet key")
    except Exception:
        fail("MFA_ENCRYPTION_KEY must be a valid Fernet key")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", os.environ["RCAA_DOMAIN"]):
        fail("RCAA_DOMAIN contains unsupported characters")
    if os.environ["TRUST_PROXY_HEADERS"] not in {"1", "true", "yes", "on"}:
        fail("TRUST_PROXY_HEADERS must be enabled behind the production proxy")
    if os.environ.get("REFRESH_COOKIE_SECURE", "1") not in {"1", "true", "yes", "on"}:
        fail("REFRESH_COOKIE_SECURE must be enabled in production")
    if "localhost" in os.environ["CORS_ORIGINS"] or "127.0.0.1" in os.environ["CORS_ORIGINS"]:
        fail("production CORS_ORIGINS must not contain localhost")
    if not os.environ["DATABASE_URL"].startswith("postgresql"):
        fail("DATABASE_URL must use PostgreSQL")
    print("Production environment validation passed.")

if __name__ == "__main__":
    main()
