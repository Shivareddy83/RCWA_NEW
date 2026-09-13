from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models import BillingSubscription, BillingInvoice, DataUpload, MerchantOnboarding, DemoLead, ReconciliationException, Merchant, User, Case
from app.security import get_current_user, require_roles
from app.billing import PLANS, usage

router = APIRouter(prefix='/product', tags=['product-lifecycle'])

@router.get('/activation')
def activation(session: Session = Depends(get_db), user=Depends(get_current_user)):
    sub = session.scalar(select(BillingSubscription).where(BillingSubscription.merchant_id == user.merchant_id))
    onboarding = session.scalar(select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == user.merchant_id))
    uploads = session.scalar(select(DataUpload.id).where(DataUpload.merchant_id == user.merchant_id).limit(1))
    exceptions = session.scalar(select(ReconciliationException.id).where(ReconciliationException.merchant_id == user.merchant_id).limit(1))
    now = datetime.now(timezone.utc)
    period_end = sub.current_period_end if sub else None
    if period_end and period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    trial_expired = bool(sub and sub.status == 'TRIAL' and period_end and period_end <= now)
    days_remaining = max(0, (period_end.date() - now.date()).days) if period_end else None
    steps = [
        {'key':'onboarding','label':'Complete workspace onboarding','complete':bool(onboarding and onboarding.status == 'COMPLETED')},
        {'key':'data','label':'Upload your first reconciliation dataset','complete':uploads is not None},
        {'key':'reconciliation','label':'Create your first reconciliation exception','complete':exceptions is not None},
        {'key':'plan','label':'Choose a paid plan','complete':bool(sub and sub.plan_code != 'TRIAL' and sub.status in {'ACTIVE','PENDING_ACTIVATION'})},
    ]
    completed = sum(1 for x in steps if x['complete'])
    return {'plan_code':sub.plan_code if sub else None,'status':sub.status if sub else None,'trial_expired':trial_expired,'days_remaining':days_remaining,'activation_score':round(completed/len(steps)*100),'steps':steps,'recommended_plan': 'STARTER' if not sub or sub.plan_code == 'TRIAL' else sub.plan_code}

class LeadStatus(BaseModel):
    status: str = Field(pattern='^(NEW|CONTACTED|QUALIFIED|WON|LOST)$')

@router.patch('/demo-leads/{lead_id}', dependencies=[Depends(require_roles('ADMIN'))])
def update_demo_lead(lead_id: str, payload: LeadStatus, session: Session = Depends(get_db), user=Depends(get_current_user)):
    lead = session.get(DemoLead, lead_id)
    if not lead:
        raise HTTPException(404, 'Demo lead not found')
    lead.status = payload.status
    session.commit()
    return {'id': lead.id, 'status': lead.status}


@router.get('/workspace-health')
def workspace_health(session: Session = Depends(get_db), user=Depends(get_current_user)):
    """Customer-facing health snapshot for retention and next-action guidance."""
    merchant_id = user.merchant_id
    sub = session.scalar(select(BillingSubscription).where(BillingSubscription.merchant_id == merchant_id))
    onboarding = session.scalar(select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant_id))
    upload_count = session.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.merchant_id == merchant_id)) or 0
    open_cases = session.scalar(select(func.count()).select_from(Case).where(Case.merchant_id == merchant_id, Case.status == 'OPEN')) or 0
    resolved_cases = session.scalar(select(func.count()).select_from(Case).where(Case.merchant_id == merchant_id, Case.status == 'RESOLVED')) or 0
    overdue = session.scalar(select(func.count()).select_from(BillingInvoice).where(BillingInvoice.merchant_id == merchant_id, BillingInvoice.status == 'PENDING', BillingInvoice.due_at < datetime.now(timezone.utc))) or 0
    checks = {
        'onboarding': bool(onboarding and onboarding.status == 'COMPLETED'),
        'data': upload_count > 0,
        'operations': resolved_cases > 0 or open_cases > 0,
        'billing': bool(sub and sub.plan_code != 'TRIAL' and sub.status == 'ACTIVE'),
    }
    score = round(sum(checks.values()) / len(checks) * 100)
    if overdue:
        health = 'ATTENTION'
        next_action = 'Review the outstanding invoice and billing status.'
    elif score < 50:
        health = 'ONBOARDING'
        next_action = 'Finish onboarding and upload the first reconciliation dataset.'
    elif score < 100:
        health = 'ACTIVE'
        next_action = 'Run reconciliation regularly and move to a paid plan when ready.'
    else:
        health = 'HEALTHY'
        next_action = 'Keep reconciliation running and review exceptions on a regular cadence.'
    return {'health': health, 'health_score': score, 'next_action': next_action, 'open_cases': open_cases, 'resolved_cases': resolved_cases, 'uploads': upload_count, 'overdue_invoices': overdue, 'plan_code': sub.plan_code if sub else None, 'subscription_status': sub.status if sub else None}

@router.get('/customer-portfolio', dependencies=[Depends(require_roles('ADMIN'))])
def customer_portfolio(session: Session = Depends(get_db), user=Depends(get_current_user)):
    """Admin-only portfolio view for customer success and revenue follow-up."""
    merchants = session.scalars(select(Merchant).order_by(Merchant.created_at.desc())).all()
    rows = []
    revenue = 0
    for merchant in merchants:
        sub = session.scalar(select(BillingSubscription).where(BillingSubscription.merchant_id == merchant.id))
        onboarding = session.scalar(select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant.id))
        uploads = session.scalar(select(func.count()).select_from(DataUpload).where(DataUpload.merchant_id == merchant.id)) or 0
        open_cases = session.scalar(select(func.count()).select_from(Case).where(Case.merchant_id == merchant.id, Case.status == 'OPEN')) or 0
        score_parts = [bool(onboarding and onboarding.status == 'COMPLETED'), uploads > 0, open_cases > 0 or uploads > 0, bool(sub and sub.plan_code != 'TRIAL' and sub.status == 'ACTIVE')]
        score = round(sum(score_parts) / len(score_parts) * 100)
        price = float(sub.monthly_price or 0) if sub else 0
        if sub and sub.status == 'ACTIVE': revenue += price
        if sub and sub.status == 'PAST_DUE': health = 'ATTENTION'
        elif score < 50: health = 'ONBOARDING'
        elif score < 100: health = 'ACTIVE'
        else: health = 'HEALTHY'
        rows.append({'merchant_id': merchant.id, 'company_name': merchant.name, 'email': merchant.email, 'plan_code': sub.plan_code if sub else None, 'subscription_status': sub.status if sub else None, 'monthly_price': price, 'health': health, 'health_score': score, 'uploads': uploads, 'open_cases': open_cases, 'created_at': merchant.created_at})
    return {'items': rows, 'summary': {'customers': len(rows), 'active_customers': sum(1 for x in rows if x['subscription_status'] == 'ACTIVE'), 'trial_customers': sum(1 for x in rows if x['plan_code'] == 'TRIAL'), 'attention_customers': sum(1 for x in rows if x['health'] == 'ATTENTION'), 'mrr': revenue}}
