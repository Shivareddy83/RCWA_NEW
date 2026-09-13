from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_and_caddy_are_present():
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    caddy = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "caddy:2.10-alpine" in compose
    assert "RCAA_DOMAIN" in compose
    assert "reverse_proxy backend:8000" in caddy
    assert "reverse_proxy frontend:3000" in caddy


def test_production_env_validator_rejects_defaults():
    env = os.environ.copy()
    env.update({"APP_ENV": "production", "RCAA_DOMAIN": "app.example.com", "POSTGRES_PASSWORD": "CHANGE_ME", "DATABASE_URL": "postgresql://x", "AUTH_SECRET": "x" * 32, "AUTH_BOOTSTRAP_TOKEN": "token", "CORS_ORIGINS": "https://app.example.com", "TRUST_PROXY_HEADERS": "1", "METRICS_AUTH_TOKEN": "metrics-token", "MFA_ENCRYPTION_KEY": "6eIIKadR_-GqxFKCxP3OI9EmXNN_JPOkcw4M3263ouk="})
    result = subprocess.run(["python3", str(ROOT / "scripts" / "validate_production_env.py")], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "POSTGRES_PASSWORD" in result.stderr


def test_production_env_validator_accepts_safe_values():
    env = os.environ.copy()
    env.update({"APP_ENV": "production", "RCAA_DOMAIN": "app.example.com", "POSTGRES_PASSWORD": "strong-db-password", "DATABASE_URL": "postgresql+psycopg://rcaa:strong@postgres:5432/rcaa", "AUTH_SECRET": "x" * 48, "AUTH_BOOTSTRAP_TOKEN": "strong-bootstrap", "CORS_ORIGINS": "https://app.example.com", "TRUST_PROXY_HEADERS": "1", "METRICS_AUTH_TOKEN": "metrics-token", "MFA_ENCRYPTION_KEY": "6eIIKadR_-GqxFKCxP3OI9EmXNN_JPOkcw4M3263ouk="})
    result = subprocess.run(["python3", str(ROOT / "scripts" / "validate_production_env.py")], env=env, text=True, capture_output=True)
    assert result.returncode == 0
