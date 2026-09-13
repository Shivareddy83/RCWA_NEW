from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Case, RCA, RCAHistory, ReconciliationException
from app.evidence.builder import EvidenceBuilder
from .rules import classify
from app.audit import record_event
from app.audit.actions import RCA_GENERATED

ENGINE_VERSION = "rca-v1"

def _explanation(code, case, evidence_items):
    base = classify(code, True)[3]
    if code == "AMOUNT_MISMATCH":
        return (f"{base} Gross/expected inputs: expected={case.expected_amount}; actual={case.actual_amount}; difference={case.difference}. "
                f"The calculation is based only on stored deterministic reconciliation values.")
    return base

def generate_rca(session: Session, case: Case, exception: ReconciliationException | None = None):
    if exception is None:
        exception = session.scalar(select(ReconciliationException).where(ReconciliationException.reconciliation_case_id == case.id))
    bundle = EvidenceBuilder(session).build(case, exception)
    code, category, confidence, explanation, action = classify(exception.exception_code if exception else "UNKNOWN_REFERENCE", bundle.complete)
    if bundle.complete: explanation = _explanation(exception.exception_code, case, bundle.items)
    evidence_ids=[item.id for item in bundle.items]
    payload={"case_id":case.id,"exception_id":exception.id if exception else None,"root_cause_code":code,"category":category,"confidence":confidence,"explanation":explanation,"action":action,"evidence_ids":evidence_ids,"engine_version":ENGINE_VERSION}
    fp=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    existing=session.scalar(select(RCA).where(RCA.reconciliation_case_id==case.id))
    if existing and getattr(existing, "fingerprint", None)==fp: return existing, False
    if existing:
        session.add(RCAHistory(
            reconciliation_case_id=existing.reconciliation_case_id, exception_id=existing.exception_id,
            root_cause=existing.root_cause, root_cause_category=existing.root_cause_category,
            confidence_label=existing.confidence_label, explanation=existing.explanation,
            recommended_action=existing.recommended_action, evidence_ids_json=existing.evidence_ids_json or [],
            engine_version=existing.engine_version, fingerprint=existing.fingerprint, generated_at=existing.generated_at,
            archived_at=datetime.now(timezone.utc)))
        existing.root_cause=code; existing.root_cause_category=category; existing.confidence_label=confidence; existing.explanation=explanation; existing.recommended_action=action; existing.evidence_ids_json=evidence_ids; existing.engine_version=ENGINE_VERSION; existing.fingerprint=fp; existing.generated_at=datetime.now(timezone.utc)
        session.flush();
        record_event(session, action=RCA_GENERATED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_type="SYSTEM", metadata={"rca_id":existing.id,"engine_version":ENGINE_VERSION,"status":"UPDATED"})
        return existing, False
    item=RCA(reconciliation_case_id=case.id, exception_id=exception.id if exception else None, root_cause=code, root_cause_category=category, confidence=Decimal("0.95") if confidence=="HIGH" else Decimal("0.75") if confidence=="MEDIUM" else Decimal("0.50") if confidence=="LOW" else Decimal("0.00"), confidence_label=confidence, explanation=explanation, recommended_action=action, evidence_ids_json=evidence_ids, engine_version=ENGINE_VERSION, fingerprint=fp, generated_at=datetime.now(timezone.utc))
    session.add(item); session.flush()
    record_event(session, action=RCA_GENERATED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_type="SYSTEM", metadata={"rca_id":item.id,"engine_version":ENGINE_VERSION,"status":"CREATED"})
    return item, True
