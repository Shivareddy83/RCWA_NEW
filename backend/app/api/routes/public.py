import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models import Merchant, MerchantOnboarding, User, BillingSubscription, DemoLead
from app.billing import ensure_trial
from app.security import create_session_tokens, hash_password, get_current_user
from app.security.rate_limit import enforce_rate_limit
from app.core.config import settings

router = APIRouter(prefix='/public', tags=['public-product'])

def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name, value=token,
        max_age=settings.refresh_token_expire_days * 86400, httponly=True,
        secure=settings.refresh_cookie_secure or settings.app_env in {'production', 'prod'},
        samesite=settings.refresh_cookie_samesite, domain=settings.refresh_cookie_domain,
        path='/api/v1/auth',
    )

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

class SignupRequest(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

@router.get('/plans')
def plans():
    return {'plans': [
        {'code':'TRIAL','name':'Trial','price':'0','limit':10000,'description':'Explore reconciliation with a small operational dataset.'},
        {'code':'STARTER','name':'Starter','price':'9999','limit':100000,'description':'For growing finance teams that need daily reconciliation.'},
        {'code':'GROWTH','name':'Growth','price':'24999','limit':500000,'description':'For higher-volume operations and recurring exception work.'},
        {'code':'BUSINESS','name':'Business','price':'49999','limit':2000000,'description':'For finance operations that need scale and priority support.'},
    ]}

@router.post('/signup', status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response, session: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    client_ip = getattr(request.state, "client_ip", None) or (request.client.host if request.client else "unknown")
    enforce_rate_limit(session, "signup", f"ip:{client_ip}", settings.rate_limit_signup_ip, settings.rate_limit_signup_window_seconds)
    enforce_rate_limit(session, "signup", f"email:{email}", settings.rate_limit_signup_email, settings.rate_limit_signup_window_seconds)
    company = payload.company_name.strip()
    name = payload.name.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Enter a valid email address')
    if session.scalar(select(User).where(User.email == email)) or session.scalar(select(Merchant).where(Merchant.email == email)):
        raise HTTPException(409, 'An account already exists for this email')
    merchant = Merchant(name=company, email=email)
    session.add(merchant)
    session.flush()
    user = User(email=email, password_hash=hash_password(payload.password), merchant_id=merchant.id, role='ADMIN', is_active=True)
    session.add(user)
    session.flush()
    session.add(MerchantOnboarding(merchant_id=merchant.id, status='IN_PROGRESS'))
    sub = ensure_trial(session, merchant.id)
    if user.role in settings.mfa_required_roles:
        from app.security import mfa_setup_token
        session.commit()
        session.refresh(user)
        return {
            "mfa_setup_required": True,
            "mfa_setup_token": mfa_setup_token(user),
            "user": {"id": user.id, "email": user.email, "merchant_id": user.merchant_id, "role": user.role},
            "workspace": {"id": merchant.id, "name": merchant.name},
            "subscription": {"plan_code": sub.plan_code, "status": sub.status, "trial_period_end": sub.current_period_end},
        }
    access, refresh, _ = create_session_tokens(session, user, client_ip=client_ip, user_agent=request.headers.get("user-agent"))
    session.commit()
    session.refresh(user)
    _set_refresh_cookie(response, refresh)
    return {
        'access_token': access,
        'token_type': 'bearer',
        'user': {'id': user.id, 'email': user.email, 'merchant_id': user.merchant_id, 'role': user.role},
        'workspace': {'id': merchant.id, 'name': merchant.name},
        'subscription': {'plan_code': sub.plan_code, 'status': sub.status, 'trial_period_end': sub.current_period_end},
        'next_step': 'Complete workspace onboarding and upload your first reconciliation dataset.'
    }

class DemoRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    company_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    monthly_transactions: str = Field(default='100k-500k', max_length=40)
    message: str = Field(default='', max_length=1000)

@router.post('/demo-request', status_code=202)
def demo_request(payload: DemoRequest, request: Request, session: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    client_ip = getattr(request.state, "client_ip", None) or (request.client.host if request.client else "unknown")
    enforce_rate_limit(session, "demo", f"ip:{client_ip}", settings.rate_limit_demo_ip, settings.rate_limit_demo_window_seconds)
    enforce_rate_limit(session, "demo", f"email:{email}", settings.rate_limit_demo_email, settings.rate_limit_demo_window_seconds)
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Enter a valid email address')
    lead = DemoLead(name=payload.name.strip(), company_name=payload.company_name.strip(), email=email, monthly_transactions=payload.monthly_transactions.strip(), message=payload.message.strip())
    session.add(lead)
    session.commit()
    return {'accepted': True, 'message': 'Thanks. Your demo request has been recorded for follow-up.', 'lead_id': lead.id}

@router.get('/demo-requests')
def demo_requests(session: Session = Depends(get_db), user=Depends(get_current_user)):
    # Public lead data is intentionally restricted to authenticated RCAA admins.
    if user.role != 'ADMIN':
        raise HTTPException(403, 'Admin access required')
    leads = session.query(DemoLead).order_by(DemoLead.created_at.desc()).limit(100).all()
    return {'items': [{'id': x.id, 'name': x.name, 'company_name': x.company_name, 'email': x.email, 'monthly_transactions': x.monthly_transactions, 'message': x.message, 'status': x.status, 'created_at': x.created_at} for x in leads]}
