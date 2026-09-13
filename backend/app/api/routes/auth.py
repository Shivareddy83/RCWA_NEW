from __future__ import annotations

import os
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import AUTH_LOGIN_FAILURE, AUTH_LOGIN_SUCCESS, AUTH_REGISTER
from app.core.config import settings
from app.core.time import utc_now
from app.models import AuthSession, Merchant, User, PasswordResetToken
from app.security import (
    ROLES,
    create_session_tokens,
    decode_special_token,
    get_current_session,
    get_current_user,
    hash_password,
    mfa_login_challenge,
    mfa_setup_token,
    revoke_session_by_access,
    revoke_session_by_refresh,
    rotate_refresh_token,
    verify_password,
)
from app.security.mfa import decrypt_secret, encrypt_secret, new_secret, provisioning_uri, verify_code
from app.security.rate_limit import enforce_rate_limit, reset_rate_limit
from app.services.email import send_password_reset

optional_bearer = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=128)
    merchant_id: str
    role: str = "VIEWER"


class LoginRequest(BaseModel):
    email: str
    password: str




class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)

class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)

def _reset_hash(token: str) -> str:
    return hashlib.sha256((settings.auth_secret + token).encode()).hexdigest()

class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaSetupRequest(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class MfaLoginRequest(BaseModel):
    challenge: str
    code: str = Field(min_length=6, max_length=8)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env in {"production", "prod"},
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env in {"production", "prod"},
        samesite=settings.refresh_cookie_samesite,
        domain=settings.refresh_cookie_domain,
        path="/api/v1/auth",
    )


def _user_from_setup_token(token: str | None, session: Session) -> User:
    if not token:
        raise HTTPException(401, "MFA setup authorization required")
    claims = decode_special_token(token, "mfa_setup")
    user = session.get(User, claims["sub"])
    if not user or not user.is_active:
        raise HTTPException(401, "MFA setup authorization is invalid")
    return user


def _audit_login_failure(session: Session, request: Request, user: User | None) -> None:
    record_event(
        session,
        action=AUTH_LOGIN_FAILURE,
        resource_type="USER" if user else "AUTHENTICATION",
        resource_id=user.id if user else None,
        merchant_id=user.merchant_id if user else None,
        actor_user_id=user.id if user else None,
        actor_role=user.role if user else None,
        actor_type="USER" if user else "SYSTEM_GLOBAL",
        request_id=getattr(request.state, "request_id", None),
        ip_address=getattr(request.state, "client_ip", None),
        outcome="FAILURE",
        metadata={"reason": "invalid_credentials"},
    )


@router.post("/register", status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    session: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    bootstrap_token: str | None = Header(None, alias="X-Bootstrap-Token"),
):
    # Keep bootstrap registration isolated from the normal session flow. The
    # endpoint is only used to create the first administrator in an empty DB.
    current = None
    if credentials:
        current = get_current_user(request, credentials, session)
    role = payload.role.upper()
    if role not in ROLES:
        raise HTTPException(422, "Invalid role")
    count = session.scalar(select(func.count(User.id))) or 0
    if count == 0:
        bootstrap_secret = os.getenv("AUTH_BOOTSTRAP_TOKEN", "")
        if not bootstrap_secret or bootstrap_token != bootstrap_secret:
            raise HTTPException(403, "Controlled bootstrap token required for initial registration")
    elif (not current or current.role != "ADMIN" or payload.merchant_id != current.merchant_id):
        raise HTTPException(403, "Only a same-merchant admin may create users")
    merchant = session.get(Merchant, payload.merchant_id)
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    if count == 0 and role != "ADMIN":
        raise HTTPException(400, "Initial user must be ADMIN")
    email = payload.email.lower().strip()
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "User already exists")
    user = User(email=email, password_hash=hash_password(payload.password), merchant_id=merchant.id, role=role, is_active=True)
    session.add(user)
    session.flush()
    record_event(session, action=AUTH_REGISTER, resource_type="USER", resource_id=user.id, merchant_id=user.merchant_id, actor_user_id=getattr(current, "id", None), actor_role=getattr(current, "role", None), actor_type="USER" if current else "SYSTEM", request_id=getattr(request.state, "request_id", None), ip_address=getattr(request.state, "client_ip", None), metadata={"email": user.email, "role": user.role})
    session.commit()
    session.refresh(user)
    return {"id": user.id, "email": user.email, "merchant_id": user.merchant_id, "role": user.role, "is_active": user.is_active, "created_at": user.created_at}


@router.post("/password/forgot")
def password_forgot(payload: PasswordResetRequest, request: Request, session: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    client_ip = getattr(request.state, "client_ip", None) or (request.client.host if request.client else "unknown")
    enforce_rate_limit(session, "password_reset", f"ip:{client_ip}", 10, 3600)
    enforce_rate_limit(session, "password_reset", f"email:{email}", 5, 3600)
    user = session.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    response = {"accepted": True, "message": "If the account exists, password reset instructions have been sent."}
    if not user:
        session.commit()
        return response
    session.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=utc_now()))
    raw = secrets.token_urlsafe(48)
    item = PasswordResetToken(user_id=user.id, token_hash=_reset_hash(raw), expires_at=utc_now() + timedelta(minutes=settings.password_reset_expire_minutes), request_ip_hash=hashlib.sha256((settings.auth_secret + client_ip).encode()).hexdigest())
    session.add(item)
    session.commit()
    if settings.password_reset_public_base_url and settings.smtp_host and settings.smtp_from:
        reset_url = settings.password_reset_public_base_url.rstrip("/") + "/reset-password?token=" + raw
        try:
            send_password_reset(user.email, reset_url)
        except Exception:
            # Never reveal delivery errors to the requester. Operational logs can capture provider failures.
            pass
    elif settings.testing or settings.app_env not in {"production", "prod"}:
        response["reset_token"] = raw
    return response

@router.post("/password/reset")
def password_reset(payload: PasswordResetConfirmRequest, request: Request, response: Response, session: Session = Depends(get_db)):
    token_hash = _reset_hash(payload.token)
    item = session.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash).with_for_update())
    now = utc_now()
    if not item or item.used_at is not None or item.expires_at.replace(tzinfo=now.tzinfo) <= now:
        raise HTTPException(400, "Reset link is invalid or expired")
    user = session.get(User, item.user_id)
    if not user or not user.is_active:
        raise HTTPException(400, "Reset link is invalid or expired")
    user.password_hash = hash_password(payload.new_password)
    item.used_at = now
    session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now))
    access, refresh, _ = create_session_tokens(session, user, client_ip=getattr(request.state, "client_ip", None), user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, refresh)
    session.commit()
    return {"password_reset": True, "access_token": access, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60}

@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, session: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    client_ip = getattr(request.state, "client_ip", None) or (request.client.host if request.client else "unknown")
    enforce_rate_limit(session, "login", f"ip:{client_ip}", settings.rate_limit_login_ip, settings.rate_limit_login_window_seconds)
    enforce_rate_limit(session, "login", f"email:{email}", settings.rate_limit_login_email, settings.rate_limit_login_window_seconds)
    user = session.scalar(select(User).where(User.email == email))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        _audit_login_failure(session, request, user)
        session.commit()
        raise HTTPException(401, "Invalid email or password", headers={"WWW-Authenticate": "Bearer"})

    reset_rate_limit(session, "login", f"email:{email}")
    reset_rate_limit(session, "login", f"ip:{client_ip}")

    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_challenge": mfa_login_challenge(user), "expires_in": 300}

    if user.role in settings.mfa_required_roles:
        return {"mfa_setup_required": True, "mfa_setup_token": mfa_setup_token(user), "expires_in": 600}

    access, refresh, _ = create_session_tokens(session, user, client_ip=client_ip, user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, refresh)
    record_event(session, action=AUTH_LOGIN_SUCCESS, resource_type="USER", resource_id=user.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state, "request_id", None), ip_address=client_ip, metadata={"method": "credential_login", "mfa": False})
    session.commit()
    return {"access_token": access, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60, "mfa_required": False}


@router.post("/mfa/verify-login")
def verify_mfa_login(payload: MfaLoginRequest, request: Request, response: Response, session: Session = Depends(get_db)):
    claims = decode_special_token(payload.challenge, "mfa_login")
    user = session.get(User, claims["sub"])
    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret_enc:
        raise HTTPException(401, "Invalid MFA challenge")
    secret = decrypt_secret(user.mfa_secret_enc)
    enforce_rate_limit(session, "mfa", f"user:{user.id}", settings.rate_limit_mfa_user, settings.rate_limit_mfa_window_seconds)
    if not verify_code(secret, payload.code):
        _audit_login_failure(session, request, user)
        session.commit()
        raise HTTPException(401, "Invalid authentication code")
    access, refresh, _ = create_session_tokens(session, user, client_ip=getattr(request.state, "client_ip", None), user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, refresh)
    record_event(session, action=AUTH_LOGIN_SUCCESS, resource_type="USER", resource_id=user.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state, "request_id", None), ip_address=getattr(request.state, "client_ip", None), metadata={"method": "credential_login", "mfa": True})
    session.commit()
    return {"access_token": access, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60, "mfa_required": False}


@router.post("/mfa/setup-required")
def mfa_setup_required(
    setup_token: str | None = Header(None, alias="X-MFA-Setup-Token"),
    session: Session = Depends(get_db),
):
    user = _user_from_setup_token(setup_token, session)
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    secret = new_secret()
    user.mfa_secret_enc = encrypt_secret(secret)
    session.commit()
    return {"issuer": settings.mfa_issuer, "account": user.email, "secret": secret, "otpauth_uri": provisioning_uri(secret, user.email), "next_step": "Verify a current authenticator code to enable MFA."}


@router.post("/mfa/verify-setup-required")
def mfa_verify_setup_required(
    payload: MfaCodeRequest,
    response: Response,
    setup_token: str | None = Header(None, alias="X-MFA-Setup-Token"),
    session: Session = Depends(get_db),
):
    user = _user_from_setup_token(setup_token, session)
    enforce_rate_limit(session, "mfa", f"user:{user.id}", settings.rate_limit_mfa_user, settings.rate_limit_mfa_window_seconds)
    if not user.mfa_secret_enc or not verify_code(decrypt_secret(user.mfa_secret_enc), payload.code):
        raise HTTPException(401, "Invalid authentication code")
    user.mfa_enabled = True
    access, refresh, _ = create_session_tokens(session, user, client_ip=None, user_agent=None)
    session.commit()
    _set_refresh_cookie(response, refresh)
    return {"enabled": True, "access_token": access, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60}


@router.get("/mfa/status")
def mfa_status(user: User = Depends(get_current_user)):
    return {"enabled": bool(user.mfa_enabled), "required": user.role in settings.mfa_required_roles}


@router.post("/mfa/setup")
def mfa_setup(payload: MfaSetupRequest, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Password verification failed")
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    secret = new_secret()
    user.mfa_secret_enc = encrypt_secret(secret)
    session.commit()
    return {"issuer": settings.mfa_issuer, "account": user.email, "secret": secret, "otpauth_uri": provisioning_uri(secret, user.email), "next_step": "Verify a current authenticator code to enable MFA."}


@router.post("/mfa/verify")
def mfa_verify(payload: MfaCodeRequest, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    enforce_rate_limit(session, "mfa", f"user:{user.id}", settings.rate_limit_mfa_user, settings.rate_limit_mfa_window_seconds)
    if not user.mfa_secret_enc:
        raise HTTPException(409, "MFA setup has not been started")
    if not verify_code(decrypt_secret(user.mfa_secret_enc), payload.code):
        raise HTTPException(401, "Invalid authentication code")
    user.mfa_enabled = True
    session.commit()
    return {"enabled": True}


@router.post("/mfa/disable")
def mfa_disable(payload: MfaCodeRequest, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    enforce_rate_limit(session, "mfa_disable", f"user:{user.id}", settings.rate_limit_mfa_user, settings.rate_limit_mfa_window_seconds)
    if not user.mfa_enabled or not user.mfa_secret_enc:
        return {"enabled": False}
    if not verify_code(decrypt_secret(user.mfa_secret_enc), payload.code):
        raise HTTPException(401, "Invalid authentication code")
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utc_now()))
    session.commit()
    return {"enabled": False}


@router.post("/refresh")
def refresh(request: Request, response: Response, refresh_token: str | None = Cookie(None, alias=settings.refresh_cookie_name), session: Session = Depends(get_db)):
    access, new_refresh, _ = rotate_refresh_token(session, refresh_token or "", client_ip=getattr(request.state, "client_ip", None), user_agent=request.headers.get("user-agent"))
    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access, "token_type": "bearer", "expires_in": settings.access_token_expire_minutes * 60}


@router.post("/logout")
def logout(request: Request, response: Response, refresh_token: str | None = Cookie(None, alias=settings.refresh_cookie_name), session: Session = Depends(get_db)):
    authorization = request.headers.get("authorization", "")
    access = authorization[7:] if authorization.lower().startswith("bearer ") else None
    revoke_session_by_refresh(session, refresh_token)
    revoke_session_by_access(session, access)
    _clear_refresh_cookie(response)
    return {"status": "logged_out"}


@router.get("/sessions")
def sessions(user: User = Depends(get_current_user), session: Session = Depends(get_db)):
    now = utc_now()
    rows = session.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at > now).order_by(AuthSession.created_at.desc())).all()
    return {"items": [{"id": row.id, "created_at": row.created_at, "expires_at": row.expires_at, "last_used_at": row.last_used_at, "revoked": row.revoked_at is not None} for row in rows]}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, current: AuthSession = Depends(get_current_session), session: Session = Depends(get_db)):
    row = session.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == current.user_id))
    if not row:
        raise HTTPException(404, "Session not found")
    row.revoked_at = utc_now()
    session.commit()
    return {"status": "revoked"}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "merchant_id": user.merchant_id, "role": user.role, "is_active": user.is_active, "mfa_enabled": bool(user.mfa_enabled), "created_at": user.created_at}
