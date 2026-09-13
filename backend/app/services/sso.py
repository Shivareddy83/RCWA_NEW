from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.models import Merchant, SSOConnection, SSOLoginState, User
from app.security.mfa import decrypt_secret, encrypt_secret


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def save_client_secret(connection: SSOConnection, value: str) -> None:
    connection.client_secret_enc = encrypt_secret(value)

def client_secret(connection: SSOConnection) -> str:
    return decrypt_secret(connection.client_secret_enc)

def discover(issuer: str) -> dict:
    issuer = issuer.rstrip("/")
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        r = client.get(issuer + "/.well-known/openid-configuration")
        r.raise_for_status()
        data = r.json()
    required = ("authorization_endpoint", "token_endpoint", "userinfo_endpoint")
    if any(not data.get(k) for k in required):
        raise ValueError("OIDC provider metadata is incomplete")
    return data

def start_login(session: Session, connection: SSOConnection) -> str:
    if not settings.sso_enabled or not settings.sso_callback_url:
        raise HTTPException(503, "Enterprise SSO is not configured")
    issuer = connection.issuer_url.rstrip("/")
    if settings.sso_allowed_issuers and issuer not in settings.sso_allowed_issuers:
        raise HTTPException(403, "SSO issuer is not allowed")
    metadata = discover(issuer)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    nonce = secrets.token_urlsafe(24)
    row = SSOLoginState(merchant_id=connection.merchant_id, state_hash=_hash(state), code_verifier_enc=encrypt_secret(verifier), nonce_hash=_hash(nonce), expires_at=utc_now()+timedelta(minutes=settings.sso_state_expire_minutes))
    session.add(row); session.commit()
    params = {"response_type":"code","client_id":connection.client_id,"redirect_uri":settings.sso_callback_url,"scope":"openid profile email","state":state,"nonce":nonce,"code_challenge":challenge,"code_challenge_method":"S256"}
    return metadata["authorization_endpoint"] + "?" + urlencode(params)

def complete_login(session: Session, state: str, code: str) -> User:
    if not state or not code:
        raise HTTPException(400, "Invalid SSO callback")
    row = session.scalar(select(SSOLoginState).where(SSOLoginState.state_hash == _hash(state)).with_for_update())
    now = utc_now()
    if not row or row.expires_at.replace(tzinfo=now.tzinfo) <= now:
        raise HTTPException(400, "SSO login state is invalid or expired")
    connection = session.scalar(select(SSOConnection).where(SSOConnection.merchant_id == row.merchant_id, SSOConnection.enabled.is_(True)))
    if not connection:
        raise HTTPException(400, "SSO connection is unavailable")
    issuer = connection.issuer_url.rstrip("/")
    if settings.sso_allowed_issuers and issuer not in settings.sso_allowed_issuers:
        raise HTTPException(403, "SSO issuer is not allowed")
    metadata = discover(issuer)
    verifier = decrypt_secret(row.code_verifier_enc)
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        token = client.post(metadata["token_endpoint"], data={"grant_type":"authorization_code","code":code,"redirect_uri":settings.sso_callback_url,"client_id":connection.client_id,"client_secret":client_secret(connection),"code_verifier":verifier})
        if token.status_code >= 400:
            raise HTTPException(401, "SSO authorization failed")
        token_data = token.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(401, "SSO provider returned no access token")
        info = client.get(metadata["userinfo_endpoint"], headers={"Authorization":f"Bearer {access_token}"})
        if info.status_code >= 400:
            raise HTTPException(401, "Unable to retrieve SSO identity")
        claims = info.json()
    if claims.get("iss") and claims["iss"].rstrip("/") != issuer:
        raise HTTPException(401, "SSO issuer mismatch")
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is False:
        raise HTTPException(401, "SSO account does not provide a verified email")
    domain = email.rsplit("@", 1)[-1]
    allowed = {d.strip().lower().lstrip("@").rstrip(".") for d in connection.allowed_domains.split(",") if d.strip()}
    if allowed and domain not in allowed:
        raise HTTPException(403, "SSO email domain is not allowed for this workspace")
    user = session.scalar(select(User).where(User.email == email))
    if user and user.merchant_id != connection.merchant_id:
        raise HTTPException(403, "SSO account is already associated with another workspace")
    if not user:
        user = User(email=email, password_hash=encrypt_secret(secrets.token_urlsafe(32)), merchant_id=connection.merchant_id, role=connection.default_role.upper(), is_active=True, mfa_enabled=False)
        session.add(user); session.flush()
    row.expires_at = now; session.delete(row)
    return user
