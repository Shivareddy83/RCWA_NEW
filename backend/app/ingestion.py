"""Normalized, provenance-aware ingestion services."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.core.config import settings
from app.models import BankTransaction, IngestionBatch, Payment, Refund, Settlement
from app.observability.metrics import inc, observe

SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD"}
SUPPORTED_STATUSES = {"created", "authorized", "captured", "failed", "refunded", "processed", "settled", "posted", "pending", "failed", "success", "successful"}

@dataclass(frozen=True)
class NormalizedRecord:
    source: str
    provider: str | None
    record_type: str
    external_id: str
    merchant_id: str | None = None
    order_reference: str | None = None
    payment_reference: str | None = None
    refund_reference: str | None = None
    settlement_reference: str | None = None
    utr: str | None = None
    amount: Decimal | None = None
    currency: str = "INR"
    status: str = "processed"
    event_timestamp: datetime | None = None
    received_timestamp: datetime | None = None
    metadata: dict[str, Any] | None = None
    raw_reference: str | None = None

class IngestionValidationError(ValueError):
    pass

def _text(value: Any, field: str, required: bool = False) -> str | None:
    value = None if value is None else str(value).strip()
    if required and not value:
        raise IngestionValidationError(f"{field} is required")
    return value or None

def _decimal(value: Any, field: str, *, non_negative: bool = True) -> Decimal:
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise IngestionValidationError(f"{field} must be a valid decimal")
    if not result.is_finite():
        raise IngestionValidationError(f"{field} must be finite")
    if non_negative and result < 0:
        raise IngestionValidationError(f"{field} must be non-negative")
    return result.quantize(Decimal("0.01"))

def _currency(value: Any) -> str:
    currency = _text(value, "currency", True).upper()
    if len(currency) != 3 or not currency.isalpha() or currency not in SUPPORTED_CURRENCIES:
        raise IngestionValidationError(f"currency is unsupported: {currency}")
    return currency

def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = _text(value, field, True)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise IngestionValidationError(f"{field} must be a valid ISO-8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def normalize_record(data: dict[str, Any], *, source: str, record_type: str, provider: str | None = None, received_at: datetime | None = None) -> NormalizedRecord:
    received = received_at or utc_now()
    if record_type == "payment":
        external_id = _text(data.get("external_id") or data.get("provider_payment_id"), "external_id", True)
        return NormalizedRecord(source, provider or data.get("provider") or "demo", record_type, external_id,
            data.get("merchant_id"), data.get("order_reference") or data.get("provider_order_id"), external_id,
            amount=_decimal(data.get("amount"), "amount", non_negative=True), currency=_currency(data.get("currency", "INR")),
            status=_text(data.get("status"), "status", True).lower(), event_timestamp=_timestamp(data.get("event_timestamp") or data.get("created_at") or received, "event_timestamp"),
            received_timestamp=received, metadata=data.get("metadata") or data.get("raw_data") or {}, raw_reference=data.get("raw_reference"))
    if record_type == "refund":
        external_id = _text(data.get("external_id") or data.get("provider_refund_id"), "external_id", True)
        payment_ref = _text(data.get("payment_reference") or data.get("provider_payment_id"), "payment_reference", True)
        return NormalizedRecord(source, provider or data.get("provider") or "demo", record_type, external_id,
            data.get("merchant_id"), payment_reference=payment_ref, refund_reference=external_id,
            amount=_decimal(data.get("amount"), "amount", non_negative=True), currency=_currency(data.get("currency", "INR")),
            status=_text(data.get("status"), "status", True).lower(), event_timestamp=_timestamp(data.get("event_timestamp") or data.get("created_at") or received, "event_timestamp"),
            received_timestamp=received, metadata=data.get("metadata") or data.get("raw_data") or {}, raw_reference=data.get("raw_reference"))
    if record_type == "settlement":
        external_id = _text(data.get("external_id") or data.get("provider_settlement_id"), "external_id", True)
        payment_ref = _text(data.get("payment_reference") or data.get("provider_payment_id"), "payment_reference", True)
        amount = _decimal(data.get("net_amount", data.get("amount")), "net_amount", non_negative=True)
        return NormalizedRecord(source, provider or data.get("provider") or "demo", record_type, external_id,
            data.get("merchant_id"), payment_reference=payment_ref, settlement_reference=external_id, utr=_text(data.get("utr"), "utr"),
            amount=amount, currency=_currency(data.get("currency", "INR")), status=_text(data.get("status"), "status", True).lower(),
            event_timestamp=_timestamp(data.get("event_timestamp") or data.get("settled_at") or received, "event_timestamp"),
            received_timestamp=received, metadata=data.get("metadata") or data.get("raw_data") or {}, raw_reference=data.get("raw_reference"))
    if record_type == "bank_transaction":
        external_id = _text(data.get("external_id"), "external_id", True)
        return NormalizedRecord(source, provider or data.get("provider"), record_type, external_id, data.get("merchant_id"),
            order_reference=_text(data.get("reference") or data.get("order_reference"), "reference"),
            settlement_reference=_text(data.get("settlement_reference"), "settlement_reference"), utr=_text(data.get("utr"), "utr"),
            amount=_decimal(data.get("amount"), "amount", non_negative=False), currency=_currency(data.get("currency", "INR")),
            status=_text(data.get("status", "posted"), "status", True).lower(), event_timestamp=_timestamp(data.get("event_timestamp"), "event_timestamp"),
            received_timestamp=received, metadata=data.get("metadata") or {}, raw_reference=data.get("raw_reference"))
    raise IngestionValidationError(f"unsupported record_type: {record_type}")

def _validate_status(status: str) -> None:
    if status not in SUPPORTED_STATUSES:
        raise IngestionValidationError(f"unsupported status: {status}")

def create_batch(session: Session, source: str, provider: str | None, merchant_id: str | None = None) -> IngestionBatch:
    batch = IngestionBatch(source=source, provider=provider, merchant_id=merchant_id, status="STARTED")
    session.add(batch); session.flush(); return batch

def persist_normalized(session: Session, records: list[NormalizedRecord], batch: IngestionBatch, *, commit: bool = True) -> dict[str, int | str]:
    stats = {"received": len(records), "created": 0, "updated": 0, "duplicates": 0, "rejected": 0, "batch_id": batch.id}
    duplicate_refs = []
    batch.record_type = records[0].record_type if records else None
    try:
        for record in records:
            _validate_status(record.status)
            if record.amount is None:
                raise IngestionValidationError("amount is required")
            if record.amount < 0 and record.record_type != "bank_transaction":
                raise IngestionValidationError("amount must be non-negative")
            if record.event_timestamp is None:
                raise IngestionValidationError("event_timestamp is required")
            if record.record_type == "payment":
                existing = session.scalar(select(Payment).where(Payment.provider == record.provider, Payment.provider_payment_id == record.external_id))
                if existing:
                    stats["duplicates"] += 1; duplicate_refs.append(record.external_id); continue
                session.add(Payment(provider=record.provider, provider_payment_id=record.external_id, provider_order_id=record.order_reference,
                    merchant_id=record.merchant_id, amount=record.amount, currency=record.currency, status=record.status,
                    method=(record.metadata or {}).get("method"), captured=record.status == "captured", created_at=record.event_timestamp,
                    captured_at=record.event_timestamp if record.status == "captured" else None, raw_data=record.metadata or {}, source=record.source,
                    external_id=record.external_id, ingestion_batch_id=batch.id, received_at=record.received_timestamp or utc_now(), raw_reference=record.raw_reference)); stats["created"] += 1
            elif record.record_type == "refund":
                existing = session.scalar(select(Refund).where(Refund.provider == record.provider, Refund.provider_refund_id == record.external_id))
                if existing:
                    stats["duplicates"] += 1; duplicate_refs.append(record.external_id); continue
                payment = session.scalar(select(Payment).where(Payment.provider == record.provider, Payment.provider_payment_id == record.payment_reference))
                session.add(Refund(provider=record.provider, provider_refund_id=record.external_id, provider_payment_id=record.payment_reference,
                    payment_id=payment.id if payment else None, amount=record.amount, status=record.status, created_at=record.event_timestamp,
                    processed_at=record.event_timestamp if record.status in {"processed", "successful", "success"} else None, raw_data=record.metadata or {},
                    source=record.source, external_id=record.external_id, ingestion_batch_id=batch.id, received_at=record.received_timestamp or utc_now(), raw_reference=record.raw_reference)); stats["created"] += 1
            elif record.record_type == "settlement":
                existing = session.scalar(select(Settlement).where(Settlement.provider == record.provider, Settlement.provider_settlement_id == record.external_id))
                if existing:
                    stats["duplicates"] += 1; duplicate_refs.append(record.external_id); continue
                payment = session.scalar(select(Payment).where(Payment.provider == record.provider, Payment.provider_payment_id == record.payment_reference))
                meta = record.metadata or {}
                gross = _decimal(meta.get("gross_amount", record.amount), "gross_amount")
                fee = _decimal(meta.get("fee", 0), "fee")
                tax = _decimal(meta.get("tax", 0), "tax")
                session.add(Settlement(provider=record.provider, provider_settlement_id=record.external_id, provider_payment_id=record.payment_reference,
                    payment_id=payment.id if payment else None, gross_amount=gross, fee=fee, tax=tax, net_amount=record.amount, status=record.status,
                    settled_at=record.event_timestamp, utr=record.utr, raw_data=meta, source=record.source, external_id=record.external_id,
                    ingestion_batch_id=batch.id, received_at=record.received_timestamp or utc_now(), raw_reference=record.raw_reference)); stats["created"] += 1
            elif record.record_type == "bank_transaction":
                existing = session.scalar(select(BankTransaction).where(BankTransaction.source == record.source, BankTransaction.external_id == record.external_id))
                if existing:
                    stats["duplicates"] += 1; duplicate_refs.append(record.external_id); continue
                session.add(BankTransaction(source=record.source, provider=record.provider, external_id=record.external_id, merchant_id=record.merchant_id,
                    reference=record.order_reference, amount=record.amount, currency=record.currency, status=record.status, event_timestamp=record.event_timestamp,
                    received_at=record.received_timestamp or utc_now(), ingestion_batch_id=batch.id, raw_reference=record.raw_reference, metadata_json=record.metadata or {})); stats["created"] += 1
        batch.received_count = int(stats["received"]); batch.created_count = int(stats["created"]); batch.updated_count = int(stats["updated"]); batch.duplicate_count = int(stats["duplicates"]); batch.rejected_count = int(stats["rejected"]); batch.duplicate_records_json = duplicate_refs; batch.status="COMPLETED"; batch.completed_at=utc_now()
        if commit: session.commit()
        else: session.flush()
    except Exception as exc:
        session.rollback()
        batch = session.get(IngestionBatch, batch.id)
        if batch:
            batch.status="REJECTED"; batch.received_count=len(records); batch.rejected_count=len(records); batch.error_summary=str(exc)[:1000]; batch.completed_at=utc_now(); session.commit()
        raise
    return stats

def ingest_records(session: Session, data: list[dict[str, Any]], *, source: str, record_type: str, provider: str | None = None, merchant_id: str | None = None, commit: bool = True) -> dict[str, Any]:
    started = __import__("time").monotonic()
    inc("ingestion_batches_total", labels={"source_type": record_type})
    try:
        records = [normalize_record(item, source=source, record_type=record_type, provider=provider) for item in data]
    except IngestionValidationError as exc:
        batch = create_batch(session, source, provider, merchant_id)
        batch.received_count=len(data); batch.rejected_count=len(data); batch.status="REJECTED"; batch.error_summary=str(exc); batch.completed_at=utc_now(); session.commit()
        inc("ingestion_records_received_total", len(data), labels={"source_type": record_type})
        inc("ingestion_records_rejected_total", len(data), labels={"source_type": record_type})
        observe("ingestion_duration_seconds", __import__("time").monotonic()-started, labels={"source_type": record_type})
        raise
    batch = create_batch(session, source, provider, merchant_id)
    result = persist_normalized(session, records, batch, commit=commit)
    inc("ingestion_records_received_total", int(result.get("received",0)), labels={"source_type": record_type})
    inc("ingestion_records_created_total", int(result.get("created",0)), labels={"source_type": record_type})
    inc("ingestion_records_updated_total", int(result.get("updated",0)), labels={"source_type": record_type})
    inc("ingestion_records_duplicate_total", int(result.get("duplicates",0)), labels={"source_type": record_type})
    inc("ingestion_records_rejected_total", int(result.get("rejected",0)), labels={"source_type": record_type})
    observe("ingestion_duration_seconds", __import__("time").monotonic()-started, labels={"source_type": record_type})
    return result

MAX_BANK_ROWS = 10_000

def parse_bank_csv(content: bytes, *, source: str = "bank_csv", provider: str | None = None) -> list[NormalizedRecord]:
    if len(content) > settings.max_upload_bytes:
        raise IngestionValidationError(f"CSV file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestionValidationError("CSV must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    required = {"external_id", "amount", "currency", "event_timestamp"}
    if not reader.fieldnames or not required.issubset({x.strip() for x in reader.fieldnames}):
        missing = sorted(required - set(reader.fieldnames or [])); raise IngestionValidationError(f"missing required column(s): {', '.join(missing)}")
    records=[]
    for row_number, row in enumerate(reader, start=2):
        if len(records) >= MAX_BANK_ROWS:
            raise IngestionValidationError(f"CSV files are limited to {MAX_BANK_ROWS:,} rows")
        try:
            records.append(normalize_record(row, source=source, record_type="bank_transaction", provider=provider))
        except IngestionValidationError as exc:
            raise IngestionValidationError(f"row {row_number}: {exc}") from exc
    return records

def ingest_bank_csv(session: Session, content: bytes, *, source: str="bank_csv", provider: str | None=None, merchant_id: str | None=None, commit: bool = True) -> dict[str, Any]:
    import time
    started = time.monotonic()
    inc("ingestion_batches_total", labels={"source_type": "bank_transaction"})
    try:
        records=parse_bank_csv(content, source=source, provider=provider)
    except IngestionValidationError as exc:
        batch=create_batch(session, source, provider, merchant_id); batch.status="REJECTED"; batch.rejected_count=1; batch.error_summary=str(exc); batch.completed_at=utc_now(); session.commit()
        inc("ingestion_records_rejected_total", labels={"source_type": "bank_transaction"})
        observe("ingestion_duration_seconds", time.monotonic()-started, labels={"source_type": "bank_transaction"})
        raise
    batch=create_batch(session, source, provider, merchant_id)
    result = persist_normalized(session, records, batch, commit=commit)
    inc("ingestion_records_received_total", int(result.get("received",0)), labels={"source_type": "bank_transaction"})
    inc("ingestion_records_created_total", int(result.get("created",0)), labels={"source_type": "bank_transaction"})
    inc("ingestion_records_updated_total", int(result.get("updated",0)), labels={"source_type": "bank_transaction"})
    inc("ingestion_records_duplicate_total", int(result.get("duplicates",0)), labels={"source_type": "bank_transaction"})
    inc("ingestion_records_rejected_total", int(result.get("rejected",0)), labels={"source_type": "bank_transaction"})
    observe("ingestion_duration_seconds", time.monotonic()-started, labels={"source_type": "bank_transaction"})
    return result


def ingest_provider_payload(session: Session, adapter, payloads: list[dict[str, Any]], *, record_type: str, source: str, merchant_id: str | None = None) -> dict[str, Any]:
    """Normalize provider-specific payloads at the adapter boundary, then persist only normalized records."""
    normalizers = {"payment": adapter.normalize_payment, "refund": adapter.normalize_refund, "settlement": adapter.normalize_settlement}
    normalizer = normalizers.get(record_type)
    if normalizer is None:
        raise IngestionValidationError(f"unsupported provider record_type: {record_type}")
    normalized = [normalizer(payload) for payload in payloads]
    return ingest_records(session, normalized, source=source, record_type=record_type, provider=getattr(adapter, "provider_name", None) or normalized[0].get("provider") if normalized else None, merchant_id=merchant_id)
