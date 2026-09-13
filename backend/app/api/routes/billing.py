from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import BILLING_CHECKOUT_REQUESTED, BILLING_INVOICE_CREATED, BILLING_INVOICE_PAID, BILLING_PLAN_CHANGED, BILLING_SUBSCRIPTION_CANCELLED, BILLING_SUBSCRIPTION_CREATED
from app.billing import PLANS, STATUSES, ensure_trial, get_subscription, snapshot, create_invoice, add_month
from app.models import BillingInvoice, BillingSubscription, Merchant
from app.core.config import settings
from app.providers.razorpay_billing import RazorpayBillingError, RazorpayBillingProvider
from app.security import get_current_user, require_roles

router=APIRouter(prefix='/billing',tags=['billing'],dependencies=[Depends(get_current_user)])
class CheckoutPayload(BaseModel): plan_code: str = Field(pattern=r'^(STARTER|GROWTH|BUSINESS)$')
class ActivatePayload(BaseModel): plan_code: str = Field(pattern=r'^(STARTER|GROWTH|BUSINESS)$')

@router.get('/plans')
def plans():
    return {'currency':'INR','plans':[{'code':k,**{'name':v['name'],'monthly_price':str(v['monthly_price']),'transaction_limit':v['transaction_limit']}} for k,v in PLANS.items()]}

def _sub_view(sub, usage_data=None):
    return {'id':sub.id,'plan_code':sub.plan_code,'plan_name':PLANS.get(sub.plan_code,{}).get('name',sub.plan_code),'status':sub.status,'currency':sub.currency,'monthly_price':str(sub.monthly_price),'monthly_transaction_limit':sub.monthly_transaction_limit,'current_period_start':sub.current_period_start,'current_period_end':sub.current_period_end,'cancel_at_period_end':sub.cancel_at_period_end,'provider':sub.provider,'provider_subscription_id':sub.provider_subscription_id,'cancel_at_period_end':sub.cancel_at_period_end,'usage':usage_data}

@router.get('')
def overview(session:Session=Depends(get_db),user=Depends(get_current_user)):
    sub=ensure_trial(session,user.merchant_id); data=__import__('app.billing',fromlist=['usage']).usage(session,user.merchant_id,sub.current_period_start,sub.current_period_end)
    invoices=session.scalars(select(BillingInvoice).where(BillingInvoice.merchant_id==user.merchant_id).order_by(BillingInvoice.issued_at.desc()).limit(20)).all()
    session.commit()
    return {'subscription':_sub_view(sub,data),'invoices':[{'id':i.id,'invoice_number':i.invoice_number,'status':i.status,'currency':i.currency,'subtotal':str(i.subtotal),'tax':str(i.tax),'total':str(i.total),'issued_at':i.issued_at,'due_at':i.due_at,'paid_at':i.paid_at} for i in invoices]}

@router.post('/checkout')
def checkout(payload:CheckoutPayload,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    sub=ensure_trial(session,user.merchant_id); plan=PLANS[payload.plan_code]
    if sub.status == 'ACTIVE' and sub.plan_code == payload.plan_code:
        raise HTTPException(409, 'This plan is already active')
    if sub.provider == 'RAZORPAY' and sub.provider_subscription_id and sub.status in {'PENDING_ACTIVATION','ACTIVE','PAST_DUE'}:
        raise HTTPException(409, 'An existing Razorpay subscription is already associated with this workspace')

    now=datetime.now(timezone.utc)
    sub.plan_code=payload.plan_code; sub.monthly_price=Decimal(plan['monthly_price']); sub.monthly_transaction_limit=plan['transaction_limit']; sub.current_period_start=now; sub.current_period_end=add_month(now); sub.cancel_at_period_end=False
    checkout_data=None
    if settings.billing_provider == 'razorpay':
        try:
            provider_plan_id=RazorpayBillingProvider.plan_id(payload.plan_code)
            provider=RazorpayBillingProvider()
            remote=provider.create_subscription(plan_id=provider_plan_id, merchant_id=user.merchant_id)
        except RazorpayBillingError as exc:
            session.rollback()
            raise HTTPException(502, str(exc))
        sub.provider='RAZORPAY'; sub.provider_plan_id=provider_plan_id; sub.provider_subscription_id=remote.get('id'); sub.provider_customer_id=remote.get('customer_id')
        sub.status='PENDING_ACTIVATION'
        checkout_data={
            'provider':'RAZORPAY','key_id':settings.razorpay_key_id,'subscription_id':remote.get('id'),
            'short_url':remote.get('short_url'),'name':'RCAA','description':f"RCAA {plan['name']} monthly subscription",
            'prefill':{'email':user.email},
        }
    else:
        sub.provider='MANUAL'; sub.status='PENDING_ACTIVATION'

    invoice=create_invoice(session,sub)

    record_event(session,action=BILLING_CHECKOUT_REQUESTED,resource_type='BILLING_SUBSCRIPTION',resource_id=sub.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'plan_code':payload.plan_code,'invoice_id':invoice.id,'status':sub.status,'provider':sub.provider})
    record_event(session,action=BILLING_INVOICE_CREATED,resource_type='BILLING_INVOICE',resource_id=invoice.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'invoice_number':invoice.invoice_number,'total':str(invoice.total),'status':invoice.status,'provider':invoice.provider})
    if checkout_data:
        record_event(session,action='BILLING_PROVIDER_CHECKOUT_CREATED',resource_type='BILLING_SUBSCRIPTION',resource_id=sub.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'provider':'RAZORPAY','provider_subscription_id':sub.provider_subscription_id})
    session.commit()
    return {'subscription':_sub_view(sub),'invoice':{'id':invoice.id,'invoice_number':invoice.invoice_number,'status':invoice.status,'total':str(invoice.total),'currency':invoice.currency,'due_at':invoice.due_at},'checkout':checkout_data,'next_step':'Complete the Razorpay checkout to authorize the subscription.' if checkout_data else 'Contact RCAA support to activate the subscription after payment confirmation.'}

class VerifyCheckoutPayload(BaseModel):
    razorpay_payment_id: str = Field(min_length=5,max_length=100)
    razorpay_subscription_id: str = Field(min_length=5,max_length=100)
    razorpay_signature: str = Field(min_length=32,max_length=128)

@router.post('/razorpay/verify')
def verify_razorpay_checkout(payload: VerifyCheckoutPayload,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    if settings.billing_provider != 'razorpay':
        raise HTTPException(409, 'Razorpay billing is not enabled')
    sub=get_subscription(session,user.merchant_id)
    if not sub or sub.provider!='RAZORPAY' or sub.provider_subscription_id != payload.razorpay_subscription_id:
        raise HTTPException(404, 'Razorpay subscription not found')
    if not RazorpayBillingProvider.verify_checkout_signature(payload.razorpay_payment_id,payload.razorpay_subscription_id,payload.razorpay_signature,secret=settings.razorpay_key_secret):
        raise HTTPException(400, 'Invalid Razorpay payment signature')
    sub.last_payment_id=payload.razorpay_payment_id
    record_event(session,action='BILLING_PROVIDER_PAYMENT_VERIFIED',resource_type='BILLING_SUBSCRIPTION',resource_id=sub.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'provider':'RAZORPAY','payment_id':payload.razorpay_payment_id,'subscription_id':sub.provider_subscription_id})
    session.commit()
    return {'verified':True,'subscription_status':sub.status}

@router.post('/subscription/activate',dependencies=[Depends(require_roles('ADMIN'))])
def activate(payload:ActivatePayload,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    sub=ensure_trial(session,user.merchant_id)
    if settings.billing_provider == 'razorpay':
        raise HTTPException(409, 'Manual activation is disabled while Razorpay billing is enabled')
    old=sub.plan_code; plan=PLANS[payload.plan_code]; sub.plan_code=payload.plan_code; sub.status='ACTIVE'; sub.monthly_price=Decimal(plan['monthly_price']); sub.monthly_transaction_limit=plan['transaction_limit']; sub.current_period_start=datetime.now(timezone.utc); sub.current_period_end=add_month(sub.current_period_start); sub.cancel_at_period_end=False
    record_event(session,action=BILLING_PLAN_CHANGED,resource_type='BILLING_SUBSCRIPTION',resource_id=sub.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),before_snapshot={'plan_code':old},after_snapshot={'plan_code':sub.plan_code,'status':sub.status})
    session.commit(); return _sub_view(sub)

@router.post('/subscription/cancel',dependencies=[Depends(require_roles('ADMIN'))])
def cancel(request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    sub=get_subscription(session,user.merchant_id)
    if not sub: raise HTTPException(404,'Subscription not found')
    if settings.billing_provider == 'razorpay' and sub.provider_subscription_id:
        try:
            remote=RazorpayBillingProvider().cancel_subscription(sub.provider_subscription_id, at_cycle_end=True)
        except RazorpayBillingError as exc:
            raise HTTPException(502, str(exc))
        sub.cancel_at_period_end=True
        if remote.get('status') == 'cancelled' and not remote.get('current_end'):
            sub.status='CANCELLED'
    else:
        sub.cancel_at_period_end=True
    record_event(session,action=BILLING_SUBSCRIPTION_CANCELLED,resource_type='BILLING_SUBSCRIPTION',resource_id=sub.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'cancel_at_period_end':True})
    session.commit(); return _sub_view(sub)

@router.get('/usage')
def current_usage(session:Session=Depends(get_db),user=Depends(get_current_user)):
    sub=ensure_trial(session,user.merchant_id); data=__import__('app.billing',fromlist=['usage']).usage(session,user.merchant_id,sub.current_period_start,sub.current_period_end); limit=sub.monthly_transaction_limit; used=data['billable_transactions']; percent=round((used/limit)*100,2) if limit else 0
    session.commit(); return {'period_start':sub.current_period_start,'period_end':sub.current_period_end,'plan_code':sub.plan_code,'used':used,'limit':limit,'percent_used':percent,'remaining':max(0,limit-used) if limit else None,'breakdown':data}

@router.get('/invoices')
def invoices(session:Session=Depends(get_db),user=Depends(get_current_user)):
    items=session.scalars(select(BillingInvoice).where(BillingInvoice.merchant_id==user.merchant_id).order_by(BillingInvoice.issued_at.desc())).all()
    return {'items':[{'id':i.id,'invoice_number':i.invoice_number,'status':i.status,'currency':i.currency,'subtotal':str(i.subtotal),'tax':str(i.tax),'total':str(i.total),'issued_at':i.issued_at,'due_at':i.due_at,'paid_at':i.paid_at} for i in items]}

@router.post('/invoices/{invoice_id}/mark-paid',dependencies=[Depends(require_roles('ADMIN'))])
def mark_paid(invoice_id:str,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    invoice=session.scalar(select(BillingInvoice).where(BillingInvoice.id==invoice_id,BillingInvoice.merchant_id==user.merchant_id))
    if not invoice: raise HTTPException(404,'Invoice not found')
    if settings.billing_provider == 'razorpay': raise HTTPException(409, 'Manual payment confirmation is disabled while Razorpay billing is enabled')
    if invoice.status=='PAID': return {'id':invoice.id,'status':invoice.status,'paid_at':invoice.paid_at}
    invoice.status='PAID'; invoice.paid_at=datetime.now(timezone.utc)
    sub=session.get(BillingSubscription,invoice.subscription_id) if invoice.subscription_id else None
    if sub and sub.status=='PENDING_ACTIVATION': sub.status='ACTIVE'
    record_event(session,action=BILLING_INVOICE_PAID,resource_type='BILLING_INVOICE',resource_id=invoice.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot={'status':'PAID','paid_at':invoice.paid_at.isoformat()})
    session.commit(); return {'id':invoice.id,'status':invoice.status,'paid_at':invoice.paid_at,'subscription_status':sub.status if sub else None}
