from __future__ import annotations
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.time import utc_now
from app.core.config import settings
from app.models import BankTransaction, Case, CaseExceptionLink, CaseEvent, CaseNote, ReconciliationException, RecoveryRecord
from .models import CaseStatus, CasePriority, ResolutionCode, VALID_TRANSITIONS

def sla_hours(priority: str) -> int:
    return {
        "CRITICAL": settings.sla_critical_hours,
        "HIGH": settings.sla_high_hours,
        "MEDIUM": settings.sla_medium_hours,
        "LOW": settings.sla_low_hours,
    }.get(priority.upper(), settings.sla_medium_hours)

class CaseBusinessError(ValueError):
    pass


def next_case_number(session: Session) -> str:
    # Operational identifier is human-readable; the unique DB constraint is the final guard.
    year = utc_now().year
    count = session.scalar(select(func.count(Case.id)).where(Case.case_number.like(f"RCAA-{year}-%"))) or 0
    return f"RCAA-{year}-{count + 1:06d}"


def add_case_event(session, case, event_type, actor_reference=None, metadata=None):
    session.add(CaseEvent(id=uuid4().hex, case_id=case.id, event_type=event_type,
                          actor_reference=actor_reference, metadata_json=metadata or {}, created_at=utc_now()))


def _resolve_merchant(case, exception=None):
    if exception and exception.merchant_id:
        return exception.merchant_id
    return (case.metadata_json or {}).get("merchant_id")


def create_case(session: Session, *, exception_id: str | None = None, merchant_id: str | None = None,
                title: str | None = None, description: str | None = None,
                priority: str | None = None, assigned_to: str | None = None,
                actor_reference: str | None = None):
    exception = session.get(ReconciliationException, exception_id) if exception_id else None
    if exception_id and not exception:
        raise CaseBusinessError("Exception not found")
    if exception and exception.reconciliation_case_id:
        existing = session.get(Case, exception.reconciliation_case_id)
        if existing:
            return existing, False
    if priority and priority.upper() not in {x.value for x in CasePriority}:
        raise CaseBusinessError("Invalid priority")
    case = Case(
        id=uuid4().hex, case_number=next_case_number(session),
        merchant_id=merchant_id or (exception.merchant_id if exception else None),
        payment_id=None, record_id=exception.primary_record_id if exception else None,
        record_type="exception" if exception else "case",
        case_type=exception.exception_code if exception else "OPERATIONAL",
        severity=exception.severity if exception else (priority or CasePriority.MEDIUM.value),
        status=CaseStatus.OPEN.value,
        priority=(priority or (exception.severity if exception else CasePriority.MEDIUM.value)).upper(),
        assigned_to=(assigned_to.strip() if assigned_to else None),
        title=title or (f"Investigate {exception.exception_code}" if exception else "RCAA operational case"),
        description=description or (f"Operational investigation for exception {exception.exception_code}." if exception else ""),
        expected_amount=exception.expected_amount if exception else 0,
        actual_amount=exception.actual_amount if exception else 0,
        difference=exception.difference if exception else 0,
        confidence=0,
        match_method="NONE", match_confidence="NONE", matched_record_id=exception.related_record_id if exception else None,
        reason_code=exception.exception_code if exception else "UNKNOWN",
        summary=exception.exception_code if exception else "Operational case",
        metadata_json={"merchant_id": merchant_id or (exception.merchant_id if exception else None)} if (merchant_id or (exception.merchant_id if exception else None)) else {},
        fingerprint=(exception.fingerprint if exception else f"manual:{uuid4().hex}"),
        created_at=utc_now(), resolved_at=None,
        sla_due_at=utc_now() + timedelta(hours=sla_hours((priority or (exception.severity if exception else CasePriority.MEDIUM.value)).upper())),
    )
    session.add(case); session.flush()
    ensure_recovery(session, case)
    add_case_event(session, case, "CASE_CREATED", actor_reference)
    if exception:
        session.add(CaseExceptionLink(case_id=case.id, exception_id=exception.id))
        add_case_event(session, case, "EXCEPTION_ATTACHED", actor_reference, {"exception_id": exception.id})
        exception.reconciliation_case_id = case.id
        # Stage 05: build deterministic evidence and RCA from stored records only.
        from app.rca.engine import generate_rca
        generate_rca(session, case, exception)
    if assigned_to:
        add_case_event(session, case, "CASE_ASSIGNED", actor_reference, {"assigned_to": assigned_to.strip()})
    try:
        session.commit(); session.refresh(case)
    except IntegrityError:
        session.rollback()
        if exception:
            existing = session.scalar(select(Case).where(Case.fingerprint == exception.fingerprint))
            if existing:
                return existing, False
        raise CaseBusinessError("Case creation conflicted with an existing case")
    return case, True


def get_case(session, case_id):
    return session.get(Case, case_id)



def ensure_recovery(session: Session, case: Case) -> RecoveryRecord:
    recovery = session.scalar(select(RecoveryRecord).where(RecoveryRecord.case_id == case.id))
    if recovery:
        return recovery
    exposure = abs(case.difference or Decimal("0"))
    recovery = RecoveryRecord(
        id=uuid4().hex, case_id=case.id, merchant_id=case.merchant_id,
        status="IDENTIFIED" if exposure > 0 else "NOT_REQUIRED",
        exposure_amount=exposure, recoverable_amount=exposure, recovered_amount=Decimal("0"),
        currency=(case.metadata_json or {}).get("currency", "INR"), created_at=utc_now(), updated_at=utc_now(),
    )
    session.add(recovery); session.flush()
    return recovery


def initiate_recovery(session: Session, case: Case, *, recoverable_amount: Decimal | None = None,
                      action_type: str, external_reference: str | None = None,
                      expected_recovery_at=None, action_note: str | None = None, actor_reference=None):
    recovery = ensure_recovery(session, case)
    amount = Decimal(str(recoverable_amount)) if recoverable_amount is not None else Decimal(str(recovery.exposure_amount))
    if amount < 0 or amount > Decimal(str(recovery.exposure_amount)):
        raise CaseBusinessError("recoverable_amount must be between 0 and the financial exposure")
    if not action_type or not action_type.strip():
        raise CaseBusinessError("action_type is required")
    now = utc_now()
    recovery.recoverable_amount = amount
    recovery.action_type = action_type.strip().upper()
    recovery.external_reference = external_reference.strip() if external_reference else None
    recovery.expected_recovery_at = expected_recovery_at
    recovery.action_note = action_note.strip() if action_note else None
    recovery.initiated_at = now
    recovery.status = "RECOVERY_INITIATED"
    recovery.updated_at = now
    case.updated_at = now
    add_case_event(session, case, "RECOVERY_INITIATED", actor_reference, {
        "recovery_id": recovery.id, "recoverable_amount": str(amount), "action_type": recovery.action_type,
        "external_reference": recovery.external_reference,
    })
    session.commit(); session.refresh(recovery)
    return recovery


def verify_recovery(session: Session, case: Case, *, bank_transaction_id: str, verification_note: str | None = None, actor_reference=None):
    recovery = ensure_recovery(session, case)
    bank = session.scalar(select(BankTransaction).where(BankTransaction.id == bank_transaction_id, BankTransaction.merchant_id == case.merchant_id))
    if not bank:
        raise CaseBusinessError("Bank transaction not found")
    recovered = Decimal(str(bank.amount))
    required = Decimal(str(recovery.recoverable_amount))
    if required <= 0:
        raise CaseBusinessError("No recoverable amount is recorded for this case")
    if recovered != required:
        recovery.recovered_amount = recovered if recovered < required else Decimal("0")
        recovery.status = "PARTIALLY_RECOVERED" if recovered < required else "RECOVERY_INITIATED"
        recovery.verification_note = verification_note.strip() if verification_note else None
        recovery.updated_at = utc_now()
        session.commit(); session.refresh(recovery)
        if recovered < required:
            raise CaseBusinessError(f"Bank transaction proves only {recovered} recovered; {required} is required for verification")
        raise CaseBusinessError(f"Bank transaction amount {recovered} does not exactly match the recoverable amount {required}")
    if recovery.external_reference and recovery.external_reference.lower() not in ((bank.reference or "") + " " + (bank.raw_reference or "")).lower():
        raise CaseBusinessError("Bank transaction reference does not match the recovery reference")
    now = utc_now()
    recovery.recovered_amount = recovered
    recovery.recovered_at = bank.event_timestamp or now
    recovery.verified_at = now
    recovery.verified_bank_transaction_id = bank.id
    recovery.verification_note = verification_note.strip() if verification_note else None
    recovery.status = "VERIFIED"
    recovery.updated_at = now
    case.updated_at = now
    add_case_event(session, case, "RECOVERY_VERIFIED", actor_reference, {
        "recovery_id": recovery.id, "bank_transaction_id": bank.id, "verified_amount": str(recovered),
    })
    session.commit(); session.refresh(recovery)
    return recovery


def mark_unrecoverable(session: Session, case: Case, *, note: str, actor_reference=None):
    recovery = ensure_recovery(session, case)
    if not note or not note.strip():
        raise CaseBusinessError("A reason is required to mark a recovery unrecoverable")
    recovery.status = "UNRECOVERABLE"
    recovery.verification_note = note.strip()
    recovery.updated_at = utc_now()
    case.updated_at = utc_now()
    add_case_event(session, case, "RECOVERY_MARKED_UNRECOVERABLE", actor_reference, {"recovery_id": recovery.id})
    session.commit(); session.refresh(recovery)
    return recovery

def transition(session, case, target: str, actor_reference=None, resolution_code=None, resolution_note=None):
    try: target_status = CaseStatus(target.upper())
    except ValueError: raise CaseBusinessError("Invalid case status")
    current = CaseStatus(case.status)
    if target_status not in VALID_TRANSITIONS[current]:
        raise CaseBusinessError(f"Invalid case status transition: {current.value} -> {target_status.value}")
    if target_status == CaseStatus.RESOLVED:
        if not resolution_code:
            raise CaseBusinessError("resolution_code is required to resolve a case")
        try: code = ResolutionCode(resolution_code.upper()).value
        except ValueError: raise CaseBusinessError("Invalid resolution_code")
        recovery = ensure_recovery(session, case)
        if code != ResolutionCode.FALSE_POSITIVE.value and Decimal(str(recovery.exposure_amount)) > 0 and recovery.status != "VERIFIED":
            raise CaseBusinessError("Financial case cannot be resolved until recovery is verified; use FALSE_POSITIVE only when the financial exception is proven invalid")
        case.resolution_code = code
        case.resolution_note = resolution_note
        case.resolved_at = utc_now()
        add_case_event(session, case, "CASE_RESOLVED", actor_reference, {"resolution_code": code})
    elif target_status == CaseStatus.REOPENED:
        case.resolved_at = None
        add_case_event(session, case, "CASE_REOPENED", actor_reference)
    else:
        add_case_event(session, case, "CASE_STATUS_CHANGED", actor_reference, {"from": current.value, "to": target_status.value})
    case.status = target_status.value
    case.updated_at = utc_now()
    session.commit(); session.refresh(case)
    return case


def assign_case(session, case, assigned_to: str | None, actor_reference=None):
    value = assigned_to.strip() if assigned_to else None
    if assigned_to is not None and not value:
        raise CaseBusinessError("assigned_to must be a non-empty identifier")
    case.assigned_to = value
    case.updated_at = utc_now()
    add_case_event(session, case, "CASE_ASSIGNED", actor_reference, {"assigned_to": value})
    session.commit(); session.refresh(case); return case


def resolution_options():
    """Return stable customer-facing resolution choices without duplicating enum values."""
    return [{"code": item.value, "label": item.value.replace("_", " ").title()} for item in ResolutionCode]


def add_note(session, case, note: str, author_reference: str | None = None):
    if not note or not note.strip(): raise CaseBusinessError("note must not be empty")
    item = CaseNote(id=uuid4().hex, case_id=case.id, author_reference=author_reference, note=note.strip(), created_at=utc_now())
    session.add(item); add_case_event(session, case, "CASE_NOTE_ADDED", author_reference, {"note_id": item.id})
    case.updated_at = utc_now(); session.commit(); session.refresh(item); return item


def attach_exception(session, case, exception_id: str, actor_reference=None):
    exception = session.get(ReconciliationException, exception_id)
    if not exception: raise CaseBusinessError("Exception not found")
    if session.scalar(select(CaseExceptionLink).where(CaseExceptionLink.case_id == case.id, CaseExceptionLink.exception_id == exception.id)):
        raise CaseBusinessError("Exception is already attached to this case")
    # An exception has one primary reconciliation case for backward compatibility,
    # but the explicit link table allows intentional operational grouping into another case.
    session.add(CaseExceptionLink(case_id=case.id, exception_id=exception.id))
    if not exception.reconciliation_case_id:
        exception.reconciliation_case_id = case.id
    add_case_event(session, case, "EXCEPTION_ATTACHED", actor_reference, {"exception_id": exception.id})
    case.updated_at = utc_now(); session.commit(); session.refresh(case); return case
