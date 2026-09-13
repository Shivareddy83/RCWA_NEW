from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Payment

def get_payment(session: Session, payment_id: str):
    return session.get(Payment, payment_id)

def get_payment_by_provider_id(session: Session, provider: str, provider_payment_id: str):
    return session.scalar(select(Payment).where(
        Payment.provider == provider, Payment.provider_payment_id == provider_payment_id
    ))

def list_payments(session: Session, limit: int, offset: int):
    return session.scalars(select(Payment).order_by(Payment.created_at.desc()).offset(offset).limit(limit)).all()
