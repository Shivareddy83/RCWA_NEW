from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.audit import record_event
from app.core.config import settings
from app.core.time import utc_now
from app.models import SSOConnection, User
from app.security import create_session_tokens, get_current_user, require_roles
from app.security.mfa import encrypt_secret
from app.services.sso import complete_login, discover, save_client_secret, start_login

router = APIRouter(prefix="/auth/sso", tags=["sso"])

class SSOConfigRequest(BaseModel):
    issuer_url: str = Field(min_length=10, max_length=500)
    client_id: str = Field(min_length=2, max_length=300)
    client_secret: str = Field(default="", max_length=1000)
    allowed_domains: str = Field(default="", max_length=1000)
    default_role: str = Field(default="VIEWER", pattern="^(ADMIN|OPS|ANALYST|VIEWER)$")
    enabled: bool = True

@router.get("/start")
def sso_start(email: str = Query("", max_length=254), session: Session = Depends(get_db)):
    if not settings.sso_enabled:
        raise HTTPException(404, "Enterprise SSO is not enabled")
    domain = email.strip().lower().rsplit("@", 1)[-1] if "@" in email else ""
    stmt = select(SSOConnection).where(SSOConnection.enabled.is_(True))
    connections = session.scalars(stmt).all()
    connection = next((c for c in connections if not c.allowed_domains or domain in {d.strip().lower().lstrip("@").rstrip(".") for d in c.allowed_domains.split(",") if d.strip()}), None)
    if not connection:
        raise HTTPException(404, "No SSO workspace is configured for this email domain")
    return RedirectResponse(start_login(session, connection), status_code=303)

@router.get("/callback")
def sso_callback(state: str, code: str, request: Request, session: Session = Depends(get_db)):
    user = complete_login(session, state, code)
    access, refresh, _ = create_session_tokens(session, user, client_ip=getattr(request.state, "client_ip", None), user_agent=request.headers.get("user-agent"))
    record_event(session, action="AUTH_LOGIN_SUCCESS", resource_type="USER", resource_id=user.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state,"request_id",None), metadata={"method":"oidc_sso"})
    session.commit()
    if not settings.sso_frontend_url:
        raise HTTPException(503, "Enterprise SSO frontend redirect is not configured")
    response = RedirectResponse(settings.sso_frontend_url.rstrip("/") + "/login?sso=1", status_code=303)
    response.set_cookie(key=settings.refresh_cookie_name, value=refresh, max_age=settings.refresh_token_expire_days*86400, httponly=True, secure=settings.refresh_cookie_secure or settings.app_env in {"production","prod"}, samesite=settings.refresh_cookie_samesite, domain=settings.refresh_cookie_domain, path="/api/v1/auth")
    # Access token is returned via a short-lived fragment-free callback cookie only for same-origin frontend bootstrap.
    return response

@router.get("/config")
def get_config(user=Depends(get_current_user), session: Session=Depends(get_db)):
    connection=session.scalar(select(SSOConnection).where(SSOConnection.merchant_id==user.merchant_id))
    if not connection: return {"configured":False,"enabled":False}
    return {"configured":True,"enabled":connection.enabled,"issuer_url":connection.issuer_url,"client_id":connection.client_id,"allowed_domains":connection.allowed_domains,"default_role":connection.default_role}

@router.put("/config", dependencies=[Depends(require_roles("ADMIN"))])
def put_config(payload: SSOConfigRequest, session: Session=Depends(get_db), user=Depends(get_current_user)):
    try: discover(payload.issuer_url.rstrip("/"))
    except Exception as exc: raise HTTPException(422,"Unable to validate the OIDC issuer") from exc
    connection=session.scalar(select(SSOConnection).where(SSOConnection.merchant_id==user.merchant_id))
    if not connection: connection=SSOConnection(merchant_id=user.merchant_id, issuer_url=payload.issuer_url.rstrip("/"), client_id=payload.client_id.strip(), client_secret_enc="", allowed_domains=payload.allowed_domains, default_role=payload.default_role, enabled=payload.enabled); session.add(connection)
    connection.issuer_url=payload.issuer_url.rstrip("/"); connection.client_id=payload.client_id.strip(); connection.allowed_domains=payload.allowed_domains.strip(); connection.default_role=payload.default_role; connection.enabled=payload.enabled;
    if payload.client_secret.strip(): save_client_secret(connection,payload.client_secret.strip())
    session.commit(); return {"configured":True,"enabled":connection.enabled,"issuer_url":connection.issuer_url,"client_id":connection.client_id,"allowed_domains":connection.allowed_domains,"default_role":connection.default_role}
