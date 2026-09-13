from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import BillingInvoice, BillingSubscription, BillingUsageSnapshot, Payment, Settlement, ReconciliationException, AuditEvent

PLANS = {
    "TRIAL": {"name":"Trial", "monthly_price": Decimal("0.00"), "transaction_limit": 10000},
    "STARTER": {"name":"Starter", "monthly_price": Decimal("9999.00"), "transaction_limit": 100000},
    "GROWTH": {"name":"Growth", "monthly_price": Decimal("24999.00"), "transaction_limit": 500000},
    "BUSINESS": {"name":"Business", "monthly_price": Decimal("49999.00"), "transaction_limit": 2000000},
}
STATUSES = {"TRIAL", "PENDING_ACTIVATION", "ACTIVE", "PAST_DUE", "CANCELLED"}

def _utc(v=None): return v or datetime.now(timezone.utc)

def add_month(dt: datetime) -> datetime:
    y, m = dt.year, dt.month
    if m == 12: y, m = y + 1, 1
    else: m += 1
    import calendar
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y,m)[1]))

def get_subscription(session: Session, merchant_id: str) -> BillingSubscription | None:
    return session.scalar(select(BillingSubscription).where(BillingSubscription.merchant_id == merchant_id))

def ensure_trial(session: Session, merchant_id: str) -> BillingSubscription:
    sub = get_subscription(session, merchant_id)
    if sub: return sub
    start = _utc(); end = add_month(start)
    sub = BillingSubscription(merchant_id=merchant_id, plan_code="TRIAL", status="TRIAL", monthly_price=Decimal("0.00"), monthly_transaction_limit=PLANS["TRIAL"]["transaction_limit"], current_period_start=start, current_period_end=end, provider="MANUAL")
    session.add(sub); session.flush(); return sub

def usage(session: Session, merchant_id: str, start: datetime, end: datetime) -> dict:
    payment_count = session.scalar(select(func.count(Payment.id)).where(Payment.merchant_id==merchant_id, Payment.created_at>=start, Payment.created_at<end)) or 0
    settlement_count = session.scalar(select(func.count(Settlement.id)).where(Settlement.merchant_id==merchant_id, Settlement.settled_at>=start, Settlement.settled_at<end)) or 0
    run_count = session.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.merchant_id==merchant_id, AuditEvent.action=='RECONCILIATION_COMPLETED', AuditEvent.outcome=='SUCCESS', AuditEvent.timestamp>=start, AuditEvent.timestamp<end)) or 0
    exception_count = session.scalar(select(func.count(ReconciliationException.id)).where(ReconciliationException.merchant_id==merchant_id, ReconciliationException.created_at>=start, ReconciliationException.created_at<end)) or 0
    total = int(payment_count) + int(settlement_count)
    return {"payments_processed":int(payment_count),"settlements_processed":int(settlement_count),"reconciliation_runs":int(run_count),"exceptions_created":int(exception_count),"billable_transactions":total}

def snapshot(session: Session, merchant_id: str, start: datetime, end: datetime) -> BillingUsageSnapshot:
    value = session.scalar(select(BillingUsageSnapshot).where(BillingUsageSnapshot.merchant_id==merchant_id, BillingUsageSnapshot.period_start==start, BillingUsageSnapshot.period_end==end))
    data = usage(session, merchant_id, start, end)
    if not value:
        value=BillingUsageSnapshot(merchant_id=merchant_id,period_start=start,period_end=end)
        session.add(value)
    value.payments_processed=data['payments_processed']; value.settlements_processed=data['settlements_processed']; value.reconciliation_runs=data['reconciliation_runs']; value.exceptions_created=data['exceptions_created']
    session.flush(); return value

def next_invoice_number(session: Session, merchant_id: str) -> str:
    prefix = datetime.now(timezone.utc).strftime('%Y%m')
    count = session.scalar(select(func.count(BillingInvoice.id)).where(BillingInvoice.merchant_id==merchant_id)) or 0
    return f"RCAA-{prefix}-{int(count)+1:05d}"

def create_invoice(session: Session, sub: BillingSubscription, *, due_days: int = 7) -> BillingInvoice:
    issued = _utc(); due = issued.replace() + __import__('datetime').timedelta(days=due_days)
    subtotal = Decimal(sub.monthly_price); tax = Decimal('0.00'); total = subtotal + tax
    invoice=BillingInvoice(merchant_id=sub.merchant_id, subscription_id=sub.id, invoice_number=next_invoice_number(session,sub.merchant_id), status='PENDING', currency=sub.currency, subtotal=subtotal,tax=tax,total=total,issued_at=issued,due_at=due,provider=sub.provider)
    session.add(invoice); session.flush(); return invoice
