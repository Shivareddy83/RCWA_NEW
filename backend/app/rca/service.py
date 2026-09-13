from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from app.models import Case, Evidence, Payment, RCA
from app.repositories.cases import get_case_by_fingerprint
from app.cases.service import next_case_number, sla_hours
from app.core.time import utc_now
from datetime import timedelta


def create_case(
    session,
    payment: Payment | None,
    case_type: str,
    expected: Decimal,
    actual: Decimal,
    summary: str,
    evidence: str,
    cause: str,
    action: str,
    confidence=Decimal(".90"),
    *,
    record_id: str | None = None,
    record_type: str = "payment",
    match_method: str = "NONE",
    match_confidence: str = "NONE",
    matched_record_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    source_key = payment.id if payment else (record_id or "none")
    fingerprint_payload = {
        "source": source_key,
        "record_type": record_type,
        "case_type": case_type,
        "expected": str(expected),
        "actual": str(actual),
        "match_method": match_method,
        "matched_record_id": matched_record_id,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if get_case_by_fingerprint(session, fingerprint):
        return False

    metadata = dict(metadata or {})
    if payment is not None:
        metadata.setdefault("source", getattr(payment, "source", None))
        metadata.setdefault("merchant_id", getattr(payment, "merchant_id", None))
    case = Case(
        case_number=next_case_number(session),
        merchant_id=(payment.merchant_id if payment else metadata.get("merchant_id")),
        title=f"Investigate {case_type}",
        description=summary,
        priority="CRITICAL" if abs(expected - actual) >= 1000 else "HIGH",
        assigned_to=None,
        resolution_code=None,
        resolution_note=None,
        payment_id=payment.id if payment else None,
        record_id=record_id,
        record_type=record_type,
        case_type=case_type,
        severity="CRITICAL" if abs(expected - actual) >= 1000 else "HIGH",
        status="OPEN",
        expected_amount=expected,
        actual_amount=actual,
        difference=actual - expected,
        confidence=confidence,
        match_method=match_method,
        match_confidence=match_confidence,
        matched_record_id=matched_record_id,
        reason_code=cause,
        summary=summary,
        metadata_json=metadata,
        fingerprint=fingerprint,
        sla_due_at=utc_now() + timedelta(hours=sla_hours("CRITICAL" if abs(expected - actual) >= 1000 else "HIGH")),
    )
    session.add(case)
    session.flush()
    from app.cases.service import add_case_event
    add_case_event(session, case, "CASE_CREATED")
    from app.audit import record_event
    from app.audit.actions import CASE_CREATED
    record_event(session, action=CASE_CREATED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_type="SYSTEM", metadata={"case_type":case.case_type,"reason_code":case.reason_code})
    return True
