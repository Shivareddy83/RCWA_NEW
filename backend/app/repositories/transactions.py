from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import Payment, Refund, Settlement


def get_payment_by_provider_id(session: Session, provider: str, provider_payment_id: str):
    return session.scalar(select(Payment).where(Payment.provider == provider, Payment.provider_payment_id == provider_payment_id))


def refunds_for_payment(session: Session, provider_payment_id: str):
    return session.scalars(select(Refund).where(Refund.provider_payment_id == provider_payment_id)).all()


def settlements_for_payment(session: Session, provider_payment_id: str):
    return session.scalars(select(Settlement).where(Settlement.provider_payment_id == provider_payment_id)).all()


def refund_count(session: Session):
    return session.scalar(select(func.count()).select_from(Refund)) or 0


def settlement_count(session: Session):
    return session.scalar(select(func.count()).select_from(Settlement)) or 0
