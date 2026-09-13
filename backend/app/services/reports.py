from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Case, Payment, ReconciliationException, Settlement


def _tenant(stmt, model, merchant_id):
    return stmt.where(model.merchant_id == merchant_id)


def build_summary(session: Session, merchant_id: str, start: datetime | None = None, end: datetime | None = None) -> dict:
    payment_q = select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0)).where(Payment.merchant_id == merchant_id)
    settlement_q = select(func.count(Settlement.id), func.coalesce(func.sum(Settlement.net_amount), 0)).where(Settlement.merchant_id == merchant_id)
    exception_q = select(func.count(ReconciliationException.id), func.coalesce(func.sum(func.abs(ReconciliationException.difference)), 0)).where(ReconciliationException.merchant_id == merchant_id)
    case_q = select(func.count(Case.id)).where(Case.merchant_id == merchant_id)
    for q, model in ((payment_q, Payment), (settlement_q, Settlement), (exception_q, ReconciliationException), (case_q, Case)):
        if start: q = q.where(model.created_at >= start)
        if end: q = q.where(model.created_at <= end)
        if model is Payment: payment_q = q
        elif model is Settlement: settlement_q = q
        elif model is ReconciliationException: exception_q = q
        else: case_q = q
    pc, pa = session.execute(payment_q).one()
    sc, sa = session.execute(settlement_q).one()
    ec, ea = session.execute(exception_q).one()
    cc = session.scalar(case_q) or 0
    open_cases = session.scalar(select(func.count(Case.id)).where(Case.merchant_id == merchant_id, Case.status.in_(['OPEN','IN_PROGRESS','REOPENED']))) or 0
    resolved_cases = session.scalar(select(func.count(Case.id)).where(Case.merchant_id == merchant_id, Case.status == 'RESOLVED')) or 0
    by_severity = dict(session.execute(select(ReconciliationException.severity, func.count()).where(ReconciliationException.merchant_id == merchant_id).group_by(ReconciliationException.severity)).all())
    by_code = dict(session.execute(select(ReconciliationException.exception_code, func.count()).where(ReconciliationException.merchant_id == merchant_id).group_by(ReconciliationException.exception_code)).all())
    match_rate = Decimal('100') if not pc else max(Decimal('0'), Decimal('100') * (Decimal(pc) - Decimal(ec)) / Decimal(pc))
    return {
        'period': {'start': start.isoformat() if start else None, 'end': end.isoformat() if end else None},
        'payments': {'count': pc or 0, 'amount': str(Decimal(pa or 0).quantize(Decimal('0.01')))},
        'settlements': {'count': sc or 0, 'net_amount': str(Decimal(sa or 0).quantize(Decimal('0.01')))},
        'exceptions': {'count': ec or 0, 'amount_at_risk': str(Decimal(ea or 0).quantize(Decimal('0.01'))), 'by_severity': by_severity, 'by_code': by_code},
        'cases': {'total': cc, 'open': open_cases, 'resolved': resolved_cases},
        'estimated_match_rate': str(match_rate.quantize(Decimal('0.01'))),
    }


def exception_rows(session: Session, merchant_id: str, start: datetime | None = None, end: datetime | None = None):
    stmt = select(ReconciliationException).where(ReconciliationException.merchant_id == merchant_id).order_by(ReconciliationException.created_at.desc())
    if start: stmt = stmt.where(ReconciliationException.created_at >= start)
    if end: stmt = stmt.where(ReconciliationException.created_at <= end)
    return session.scalars(stmt).all()


def case_rows(session: Session, merchant_id: str, start: datetime | None = None, end: datetime | None = None):
    stmt = select(Case).where(Case.merchant_id == merchant_id).order_by(Case.created_at.desc())
    if start: stmt = stmt.where(Case.created_at >= start)
    if end: stmt = stmt.where(Case.created_at <= end)
    return session.scalars(stmt).all()
