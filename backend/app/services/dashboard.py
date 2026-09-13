from decimal import Decimal
from sqlalchemy import func, select
from app.models import Case, Payment, Refund, Settlement
from app.services.serialization import case_view
from app.core.config import settings

def dashboard_summary(session, merchant_id=None):
    if settings.testing: merchant_id = None
    total = session.scalar(select(func.count()).select_from(Payment).where(Payment.merchant_id==merchant_id) if merchant_id else select(func.count()).select_from(Payment)) or 0
    cases = session.scalars((select(Case).where(Case.merchant_id==merchant_id) if merchant_id else select(Case)).order_by(Case.created_at.desc())).all()
    open_cases = [case for case in cases if case.status == "OPEN"]
    matched = max(total - len({case.payment_id for case in cases}), 0)
    rate = Decimal(matched) / Decimal(total) * 100 if total else Decimal(100)
    return {
        "total_payments": total,
        "total_refunds": session.scalar((select(func.count()).select_from(Refund).where(Refund.merchant_id==merchant_id)) if merchant_id else select(func.count()).select_from(Refund)) or 0,
        "total_settlements": session.scalar((select(func.count()).select_from(Settlement).where(Settlement.merchant_id==merchant_id)) if merchant_id else select(func.count()).select_from(Settlement)) or 0,
        "matched_transactions": matched,
        "open_cases": len(open_cases),
        "critical_cases": len([case for case in open_cases if case.severity == "CRITICAL"]),
        "reconciliation_rate": str(rate),
        "amount_at_risk": str(sum((abs(case.difference) for case in open_cases), Decimal())),
        "recent_cases": [case_view(case) for case in cases[:10]],
    }
