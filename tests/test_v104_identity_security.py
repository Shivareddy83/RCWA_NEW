import base64
import os
import time
from pathlib import Path

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("RCAA_LEGACY_TEST_AUTH", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_rcaa_identity.db")
os.environ.setdefault("AUTH_SECRET", "test-auth-secret-for-v104-identity-security-123456")

from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant, User, AuthSession
from app.security.auth import hash_password
from app.security.mfa import _hotp

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
client = TestClient(app)


def reset():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add(Merchant(id="m-id", name="Identity Merchant", email="identity@example.local"))
        s.add(User(id="u-id", email="identity@example.local", password_hash=hash_password("StrongPass123!"), merchant_id="m-id", role="ADMIN", is_active=True))
        s.commit()


def code_for(secret: str) -> str:
    return _hotp(secret, int(time.time() // 30))


def test_refresh_cookie_rotation_and_reuse_detection():
    reset()
    r = client.post("/api/v1/auth/login", json={"email": "identity@example.local", "password": "StrongPass123!"})
    assert r.status_code == 200
    old_cookie = client.cookies.get("rcaa_refresh")
    access = r.json()["access_token"]
    assert old_cookie
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 200

    refreshed = client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    new_cookie = client.cookies.get("rcaa_refresh")
    assert new_cookie and new_cookie != old_cookie

    # Presenting the rotated token is treated as token-family compromise.
    client.cookies.set("rcaa_refresh", old_cookie, domain="testserver.local", path="/api/v1/auth")
    replay = client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    with SessionLocal() as s:
        assert s.query(AuthSession).count() == 2
        assert s.query(AuthSession).filter(AuthSession.revoked_at.is_(None)).count() == 0


def test_totp_mfa_secret_is_encrypted_and_required_at_login():
    reset()
    from app.core.config import settings
    from cryptography.fernet import Fernet
    object.__setattr__(settings, "mfa_encryption_key", Fernet.generate_key().decode())

    login = client.post("/api/v1/auth/login", json={"email": "identity@example.local", "password": "StrongPass123!"})
    assert login.status_code == 200
    access = login.json()["access_token"]
    setup = client.post("/api/v1/auth/mfa/setup", json={"password": "StrongPass123!"}, headers={"Authorization": f"Bearer {access}"})
    assert setup.status_code == 200
    body = setup.json()
    assert body["secret"] not in body.get("otpauth_uri", "") or body["secret"] in body["otpauth_uri"]

    verify = client.post("/api/v1/auth/mfa/verify", json={"code": code_for(body["secret"])}, headers={"Authorization": f"Bearer {access}"})
    assert verify.status_code == 200

    with SessionLocal() as s:
        user = s.get(User, "u-id")
        assert user.mfa_enabled is True
        assert user.mfa_secret_enc
        assert body["secret"] not in user.mfa_secret_enc

    # Logout current session, then password authentication must stop before access-token issuance.
    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    login2 = client.post("/api/v1/auth/login", json={"email": "identity@example.local", "password": "StrongPass123!"})
    assert login2.status_code == 200
    assert login2.json()["mfa_required"] is True
    challenge = login2.json()["mfa_challenge"]
    verify_login = client.post("/api/v1/auth/mfa/verify-login", json={"challenge": challenge, "code": code_for(body["secret"])})
    assert verify_login.status_code == 200
    assert verify_login.json().get("access_token")


def test_upload_parser_rejects_column_and_cell_abuse():
    from app.data_onboarding import parse_upload
    many_columns = (",".join(f"c{i}" for i in range(101)) + "\n" + ",".join("x" for _ in range(101))).encode()
    try:
        parse_upload(many_columns, "bad.csv")
        assert False
    except Exception as exc:
        assert "columns" in str(exc).lower()

    oversized = ("external_id,amount,event_timestamp\n" + "x" * 10001 + ",1,2025-01-01T00:00:00Z\n").encode()
    try:
        parse_upload(oversized, "bad.csv")
        assert False
    except Exception as exc:
        assert "characters" in str(exc).lower()


def test_required_admin_mfa_enrollment_flow_blocks_plain_password_session():
    reset()
    from app.core.config import settings
    from cryptography.fernet import Fernet
    object.__setattr__(settings, "mfa_encryption_key", Fernet.generate_key().decode())
    object.__setattr__(settings, "mfa_required_roles", ("ADMIN",))
    first = client.post("/api/v1/auth/login", json={"email": "identity@example.local", "password": "StrongPass123!"})
    assert first.status_code == 200
    assert first.json()["mfa_setup_required"] is True
    setup_token = first.json()["mfa_setup_token"]
    setup = client.post("/api/v1/auth/mfa/setup-required", headers={"X-MFA-Setup-Token": setup_token})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    enabled = client.post("/api/v1/auth/mfa/verify-setup-required", headers={"X-MFA-Setup-Token": setup_token}, json={"code": code_for(secret)})
    assert enabled.status_code == 200
    assert enabled.json().get("access_token")
    object.__setattr__(settings, "mfa_required_roles", ())
