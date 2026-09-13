from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.errors import ConflictError, NotFoundError
from app.models import Payment, Refund, Settlement
from app.repositories.payments import get_payment, get_payment_by_provider_id, list_payments
from app.services.serialization import dump
from app.observability.metrics import inc, observe
from time import monotonic


def create_payment(session: Session, data: dict, *, commit: bool = True):
    payment = Payment(**data)
    session.add(payment)
    try:
        if commit: session.commit()
        else: session.flush()
        session.refresh(payment)
    except Exception as exc:
        session.rollback()
        raise ConflictError("Provider payment already exists") from exc
    return payment


def import_payments(session: Session, items: list[dict], *, commit: bool = True) -> int:
    started = monotonic()
    inc("ingestion_batches_total", labels={"source_type":"payment"})
    inc("ingestion_records_received_total", len(items), labels={"source_type":"payment"})
    created = 0
    duplicates = 0
    for data in items:
        if not get_payment_by_provider_id(session, data["provider"], data["provider_payment_id"]):
            session.add(Payment(**data))
            created += 1
        else:
            duplicates += 1
    if commit: session.commit()
    else: session.flush()
    inc("ingestion_records_created_total", created, labels={"source_type":"payment"})
    inc("ingestion_records_duplicate_total", duplicates, labels={"source_type":"payment"})
    observe("ingestion_duration_seconds", monotonic()-started, labels={"source_type":"payment"})
    return created


def create_refund(session: Session, data: dict, *, commit: bool = True):
    payment = session.scalar(select(Payment).where(Payment.provider == data["provider"], Payment.provider_payment_id == data["provider_payment_id"], Payment.merchant_id == data.get("merchant_id")))
    value = Refund(**data, payment_id=payment.id if payment else None)
    session.add(value)
    try:
        if commit: session.commit()
        else: session.flush()
        session.refresh(value)
    except Exception as exc:
        session.rollback()
        raise ConflictError("Provider refund already exists") from exc
    return value


def create_settlement(session: Session, data: dict, *, commit: bool = True):
    payment = session.scalar(select(Payment).where(Payment.provider == data["provider"], Payment.provider_payment_id == data["provider_payment_id"], Payment.merchant_id == data.get("merchant_id")))
    value = Settlement(**data, payment_id=payment.id if payment else None)
    session.add(value)
    try:
        if commit: session.commit()
        else: session.flush()
        session.refresh(value)
    except Exception as exc:
        session.rollback()
        raise ConflictError("Provider settlement already exists") from exc
    return value


def get_or_404(model, session: Session, record_id: str, label: str):
    value = session.get(model, record_id)
    if not value:
        raise NotFoundError(f"{label} not found")
    return value
