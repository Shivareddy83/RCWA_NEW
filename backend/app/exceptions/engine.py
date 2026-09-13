from __future__ import annotations
import hashlib, json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Case, CaseExceptionLink, CaseEvent, IngestionBatch, ReconciliationException
from .rules import code_for_case, severity_for

def _fingerprint(case: Case, code: str) -> str:
    payload={"merchant_id": case.metadata_json.get("merchant_id") if case.metadata_json else None,
             "exception_code": code, "primary_record": case.record_id or case.payment_id,
             "related_record": case.matched_record_id, "difference": str(case.difference),
             "reconciliation_context": {"reason_code": case.reason_code, "match_method": case.match_method}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def generate_exceptions(session: Session, merchant_id: str | None = None) -> dict[str,int]:
    created=0; existing=0
    duplicate_code = {"payment":"DUPLICATE_PAYMENT", "refund":"DUPLICATE_REFUND", "settlement":"DUPLICATE_SETTLEMENT"}
    for batch in session.scalars(select(IngestionBatch).where(IngestionBatch.duplicate_count > 0, IngestionBatch.merchant_id == merchant_id)).all():
        code = duplicate_code.get(batch.record_type)
        if not code: continue
        for external_id in (batch.duplicate_records_json or [batch.id]):
            payload={"batch_id":batch.id,"source":batch.source,"provider":batch.provider,"record_type":batch.record_type,"external_id":external_id,"exception_code":code}
            fp=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
            if session.scalar(select(ReconciliationException).where(ReconciliationException.fingerprint==fp)):
                existing += 1; continue
            item = ReconciliationException(id=__import__('uuid').uuid4().hex,reconciliation_case_id=None, exception_code=code, severity=severity_for(code), status="OPEN", source=batch.source, merchant_id=batch.merchant_id, primary_record_id=external_id, related_record_id=None, expected_amount=0, actual_amount=0, difference=0, fingerprint=fp, evidence_json={"ingestion_batch_id":batch.id,"source":batch.source,"provider":batch.provider,"record_type":batch.record_type,"external_id":external_id})
            session.add(item)
            created += 1
    for case in session.scalars(select(Case).where(Case.merchant_id == merchant_id).order_by(Case.created_at) if merchant_id else select(Case).order_by(Case.created_at)).all():
        code=code_for_case(case.case_type)
        fp=_fingerprint(case, code)
        found=session.scalar(select(ReconciliationException).where(ReconciliationException.fingerprint==fp))
        if found:
            existing += 1; continue
        exc = ReconciliationException(reconciliation_case_id=case.id, exception_code=code,
            severity=severity_for(code, case.difference), status=case.status, source=(case.metadata_json or {}).get("source"),
            merchant_id=(case.metadata_json or {}).get("merchant_id"), primary_record_id=case.record_id or case.payment_id,
            related_record_id=case.matched_record_id, expected_amount=case.expected_amount, actual_amount=case.actual_amount,
            difference=case.difference, fingerprint=fp, evidence_json={"case_id":case.id, "record_id":case.record_id, "matched_record_id":case.matched_record_id,
                "expected_amount":str(case.expected_amount), "actual_amount":str(case.actual_amount), "difference":str(case.difference),
                "reason_code":case.reason_code, "match_method":case.match_method})
        session.add(exc)
        session.flush()
        session.add(CaseExceptionLink(case_id=case.id, exception_id=exc.id))
        session.add(CaseEvent(id=__import__("uuid").uuid4().hex, case_id=case.id, event_type="EXCEPTION_ATTACHED", actor_reference="system", metadata_json={"exception_id": exc.id}, created_at=case.created_at))
        created += 1
    session.commit()
    # Build evidence and deterministic RCA for every exception-backed case.
    from app.rca.engine import generate_rca
    for case in session.scalars(select(Case).where(Case.merchant_id == merchant_id)).all() if merchant_id else session.scalars(select(Case)).all():
        exc = session.scalar(select(ReconciliationException).where(ReconciliationException.reconciliation_case_id == case.id))
        if exc:
            generate_rca(session, case, exc)
    session.commit()
    return {"created":created,"existing":existing}
