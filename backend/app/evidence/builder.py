from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (BankTransaction, Case, CaseEvent, Evidence, IngestionBatch,
                        Payment, RCA, ReconciliationException, Refund, Settlement, WebhookEvent)
from .models import EvidenceType
from app.audit import record_event
from app.audit.actions import EVIDENCE_CREATED


def _dump_scalar(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Decimal): return str(value)
    return value


def _snapshot(obj, fields):
    return {field: _dump_scalar(getattr(obj, field, None)) for field in fields}


def _find_by_id_or_external(session: Session, model, value: str | None):
    if not value: return None
    item = session.get(model, value)
    if item: return item
    if model is Payment: return session.scalar(select(model).where(model.provider_payment_id == value))
    if model is Refund: return session.scalar(select(model).where(model.provider_refund_id == value))
    if model is Settlement: return session.scalar(select(model).where(model.provider_settlement_id == value))
    if model is BankTransaction: return session.scalar(select(model).where(model.external_id == value))
    return None

@dataclass(frozen=True)
class EvidenceBundle:
    items: list[Evidence]
    complete: bool
    missing: list[str]

class EvidenceBuilder:
    REQUIRED = {
        "PAYMENT_NOT_SETTLED": {EvidenceType.PAYMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "DELAYED_SETTLEMENT": {EvidenceType.PAYMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "AMOUNT_MISMATCH": {EvidenceType.PAYMENT_RECORD.value, EvidenceType.SETTLEMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "STATUS_MISMATCH": {EvidenceType.PAYMENT_RECORD.value, EvidenceType.SETTLEMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "DUPLICATE_PAYMENT": {EvidenceType.PAYMENT_RECORD.value, EvidenceType.EXCEPTION_RECORD.value},
        "DUPLICATE_REFUND": {EvidenceType.REFUND_RECORD.value, EvidenceType.EXCEPTION_RECORD.value},
        "DUPLICATE_SETTLEMENT": {EvidenceType.SETTLEMENT_RECORD.value, EvidenceType.EXCEPTION_RECORD.value},
        "AMBIGUOUS_MATCH": {EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "SETTLEMENT_WITHOUT_PAYMENT": {EvidenceType.SETTLEMENT_RECORD.value, EvidenceType.EXCEPTION_RECORD.value},
        "REFUND_WITHOUT_PAYMENT": {EvidenceType.REFUND_RECORD.value, EvidenceType.EXCEPTION_RECORD.value},
        "REFUND_NOT_SETTLED": {EvidenceType.REFUND_RECORD.value, EvidenceType.PAYMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "BANK_SETTLEMENT_MISMATCH": {EvidenceType.BANK_TRANSACTION.value, EvidenceType.SETTLEMENT_RECORD.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
        "BANK_WITHOUT_SETTLEMENT": {EvidenceType.BANK_TRANSACTION.value, EvidenceType.EXCEPTION_RECORD.value},
        "BANK_AMBIGUOUS_MATCH": {EvidenceType.BANK_TRANSACTION.value, EvidenceType.RECONCILIATION_RESULT.value, EvidenceType.EXCEPTION_RECORD.value},
    }

    def __init__(self, session: Session): self.session = session

    def _add(self, case, etype, source_type, source_id, relevance, snapshot, metadata=None):
        payload = {"case_id": case.id, "evidence_type": etype, "source_entity_type": source_type,
                   "source_entity_id": source_id, "snapshot": snapshot, "relevance": relevance}
        fp = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = self.session.scalar(select(Evidence).where(Evidence.fingerprint == fp))
        if existing: return existing
        item = Evidence(reconciliation_case_id=case.id, evidence_type=etype, source_entity_type=source_type,
                        source_record_id=source_id, captured_at=case.created_at,
                        relevance=relevance, snapshot_json=snapshot, description=relevance,
                        metadata_json=metadata or {}, fingerprint=fp)
        self.session.add(item); self.session.flush()
        record_event(self.session, action=EVIDENCE_CREATED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_type="SYSTEM", metadata={"evidence_id":item.id,"evidence_type":etype,"source_entity_type":source_type,"source_record_id":source_id})
        return item

    def build(self, case: Case, exception: ReconciliationException | None = None) -> EvidenceBundle:
        if exception is None:
            exception = self.session.scalar(select(ReconciliationException).where(ReconciliationException.reconciliation_case_id == case.id))
        if not exception: return EvidenceBundle([], False, ["EXCEPTION_RECORD"])
        items=[]
        # Resolve actual stored records from deterministic IDs/references.
        primary = self.session.get(Payment, case.payment_id) if case.payment_id else _find_by_id_or_external(self.session, Payment, case.record_id or exception.primary_record_id)
        related = _find_by_id_or_external(self.session, Settlement, case.matched_record_id or exception.related_record_id)
        related_bank = _find_by_id_or_external(self.session, BankTransaction, case.matched_record_id or exception.related_record_id) if case.record_type == "bank_transaction" else None
        if case.record_type == "refund": primary = _find_by_id_or_external(self.session, Refund, case.record_id or exception.primary_record_id)
        if case.record_type == "settlement": primary = _find_by_id_or_external(self.session, Settlement, case.record_id or exception.primary_record_id)
        if case.record_type == "bank_transaction": primary = _find_by_id_or_external(self.session, BankTransaction, case.record_id or exception.primary_record_id)
        if primary:
            if isinstance(primary, Payment): et=EvidenceType.PAYMENT_RECORD.value; fields=["id","provider","provider_payment_id","provider_order_id","merchant_id","amount","currency","status","created_at","captured_at","source","external_id","received_at"]
            elif isinstance(primary, Refund): et=EvidenceType.REFUND_RECORD.value; fields=["id","provider","provider_refund_id","provider_payment_id","payment_id","amount","status","created_at","processed_at","source","external_id","received_at"]
            elif isinstance(primary, Settlement): et=EvidenceType.SETTLEMENT_RECORD.value; fields=["id","provider","provider_settlement_id","provider_payment_id","payment_id","gross_amount","fee","tax","net_amount","status","settled_at","utr","source","external_id","received_at"]
            else: et=EvidenceType.BANK_TRANSACTION.value; fields=["id","source","provider","external_id","merchant_id","reference","amount","currency","status","event_timestamp","received_at"]
            items.append(self._add(case, et, type(primary).__name__, primary.id, "Primary financial record supporting the exception.", _snapshot(primary, fields)))
        if isinstance(related, Settlement):
            fields=["id","provider","provider_settlement_id","provider_payment_id","payment_id","gross_amount","fee","tax","net_amount","status","settled_at","utr","source","external_id","received_at"]
            items.append(self._add(case, EvidenceType.SETTLEMENT_RECORD.value, "Settlement", related.id, "Matched settlement record used by reconciliation.", _snapshot(related, fields)))
        elif isinstance(related, Payment):
            fields=["id","provider","provider_payment_id","provider_order_id","merchant_id","amount","currency","status","created_at","captured_at","source","external_id","received_at"]
            items.append(self._add(case, EvidenceType.PAYMENT_RECORD.value, "Payment", related.id, "Related payment record used by reconciliation.", _snapshot(related, fields)))
        # Candidate references for ambiguity are preserved from reconciliation metadata, without inventing records.
        metadata = case.metadata_json or {}
        if metadata.get("candidate_records"):
            items.append(self._add(case, EvidenceType.RECONCILIATION_RESULT.value, "ReconciliationResult", case.id,
                "Candidate comparison data recorded by deterministic reconciliation.", {"candidate_records": metadata["candidate_records"], "match_method": case.match_method, "match_confidence": case.match_confidence}))
        else:
            items.append(self._add(case, EvidenceType.RECONCILIATION_RESULT.value, "ReconciliationResult", case.id,
                "Stored deterministic reconciliation calculation and match result.", {
                    "expected_amount": str(case.expected_amount), "actual_amount": str(case.actual_amount), "difference": str(case.difference),
                    "match_method": case.match_method, "match_confidence": case.match_confidence, "reason_code": case.reason_code,
                    "matched_record_id": case.matched_record_id, "record_id": case.record_id
                }))
        items.append(self._add(case, EvidenceType.EXCEPTION_RECORD.value, "ReconciliationException", exception.id,
            "Deterministic exception that triggered the investigation.", {
                "id": exception.id, "exception_code": exception.exception_code, "severity": exception.severity,
                "status": exception.status, "primary_record_id": exception.primary_record_id, "related_record_id": exception.related_record_id,
                "expected_amount": str(exception.expected_amount), "actual_amount": str(exception.actual_amount), "difference": str(exception.difference),
                "fingerprint": exception.fingerprint
            }))
        required=self.REQUIRED.get(exception.exception_code, {EvidenceType.EXCEPTION_RECORD.value})
        present={x.evidence_type for x in items}; missing=sorted(required-present)
        return EvidenceBundle(items, not missing, missing)

def build_evidence(session: Session, case: Case, exception: ReconciliationException | None = None):
    return EvidenceBuilder(session).build(case, exception)
