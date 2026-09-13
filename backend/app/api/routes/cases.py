from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.errors import AppError, NotFoundError
from app.models import BankTransaction, Case, CaseEvent, CaseNote, Evidence, ReconciliationException, CaseExceptionLink, RecoveryRecord
from app.cases.service import add_note, assign_case, attach_exception, create_case, get_case, transition, resolution_options, ensure_recovery, initiate_recovery, verify_recovery, mark_unrecoverable, CaseBusinessError
from app.services.serialization import dump
from app.security import get_current_user, require_roles
from app.core.config import settings
from app.security.tenant import ensure_merchant, test_admin_bypass
from app.audit import record_event
from app.audit.actions import CASE_CREATED, CASE_ASSIGNED, CASE_NOTE_ADDED, CASE_STATUS_CHANGED, CASE_RESOLVED, CASE_REOPENED, EXCEPTION_ATTACHED_TO_CASE

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/cases/resolution-options")
def case_resolution_options():
    return {"items": resolution_options()}

class CreateCaseRequest(BaseModel):
    exception_id: Optional[str] = None
    merchant_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
class AssignRequest(BaseModel): assigned_to: Optional[str] = None; actor_reference: Optional[str] = None
class NoteRequest(BaseModel): note: str = Field(min_length=1, max_length=10000); author_reference: Optional[str] = None
class ResolveRequest(BaseModel): resolution_code: Optional[str] = None; resolution_note: Optional[str] = None; actor_reference: Optional[str] = None
class ActorRequest(BaseModel): actor_reference: Optional[str] = None
class AttachExceptionRequest(BaseModel): exception_id: str; actor_reference: Optional[str] = None
class RecoveryInitiateRequest(BaseModel):
    recoverable_amount: Optional[Decimal] = Field(default=None, ge=0)
    action_type: str = Field(min_length=1, max_length=100)
    external_reference: Optional[str] = Field(default=None, max_length=200)
    expected_recovery_at: Optional[datetime] = None
    action_note: Optional[str] = Field(default=None, max_length=5000)
class RecoveryVerifyRequest(BaseModel):
    bank_transaction_id: str
    verification_note: Optional[str] = Field(default=None, max_length=5000)
class RecoveryUnrecoverableRequest(BaseModel):
    note: str = Field(min_length=1, max_length=5000)

def _detail(session, case):
    exceptions = session.scalars(select(ReconciliationException).join(CaseExceptionLink, CaseExceptionLink.exception_id == ReconciliationException.id).where(CaseExceptionLink.case_id == case.id)).all()
    recovery = ensure_recovery(session, case)
    return {**dump(case), "exceptions": dump(exceptions), "evidence": dump(case.evidence), "notes": dump(case.notes), "timeline": dump(case.events), "recovery": dump(recovery), "rca": ({**dump(case.rca), "root_cause_code": case.rca.root_cause, "category": case.rca.root_cause_category, "confidence": case.rca.confidence_label, "evidence_ids": case.rca.evidence_ids_json, "engine_version": case.rca.engine_version} if case.rca else None)}

def _case(session, case_id, user):
    if (test_admin_bypass(user)):
        case = session.get(Case, case_id)
    else:
        case = session.scalar(select(Case).where(Case.id == case_id, Case.merchant_id == user.merchant_id))
    if not case:
        raise NotFoundError("Case not found")
    return case

@router.post('/cases', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def create_case_api(payload: CreateCaseRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    if not (test_admin_bypass(user)):
        ensure_merchant(payload.merchant_id, user)
    if payload.exception_id:
        exc = session.get(ReconciliationException, payload.exception_id) if (test_admin_bypass(user)) else session.scalar(select(ReconciliationException).where(ReconciliationException.id == payload.exception_id, ReconciliationException.merchant_id == user.merchant_id))
        if not exc: raise AppError("Exception not found")
    case, created = create_case(session, exception_id=payload.exception_id, merchant_id=(payload.merchant_id if (test_admin_bypass(user)) and payload.merchant_id else user.merchant_id), title=payload.title, description=payload.description, priority=payload.priority, assigned_to=payload.assigned_to)
    if created:
        record_event(session, action=CASE_CREATED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, after_snapshot={"status":case.status,"priority":case.priority,"assigned_to":case.assigned_to})
        session.commit(); session.refresh(case)
    return {**_detail(session, case), "created": created}

@router.get('/cases')
def list_cases_api(status: Optional[str]=None, priority: Optional[str]=None, severity: Optional[str]=None, merchant: Optional[str]=None, assigned_to: Optional[str]=None, exception_code: Optional[str]=None, created_from: Optional[datetime]=None, created_to: Optional[datetime]=None, page: int=Query(1, ge=1), limit: int=Query(50, ge=1, le=200), session: Session=Depends(get_db), user=Depends(get_current_user)):
    stmt=select(Case).order_by(Case.created_at.desc()) if (test_admin_bypass(user)) else select(Case).where(Case.merchant_id==user.merchant_id).order_by(Case.created_at.desc())
    if merchant:
        if not (test_admin_bypass(user)): ensure_merchant(merchant,user)
        stmt=stmt.where(Case.merchant_id==merchant)
    if status: stmt=stmt.where(Case.status==status.upper())
    if priority: stmt=stmt.where(Case.priority==priority.upper())
    if severity: stmt=stmt.where(Case.severity==severity.upper())
    if assigned_to: stmt=stmt.where(Case.assigned_to==assigned_to)
    if exception_code:
        qexc=select(CaseExceptionLink.case_id).join(ReconciliationException, ReconciliationException.id == CaseExceptionLink.exception_id).where(ReconciliationException.exception_code == exception_code.upper())
        if not (test_admin_bypass(user)): qexc=qexc.where(ReconciliationException.merchant_id == user.merchant_id)
        stmt=stmt.where(Case.id.in_(qexc))
    if created_from: stmt=stmt.where(Case.created_at>=created_from)
    if created_to: stmt=stmt.where(Case.created_at<=created_to)
    total=session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items=session.scalars(stmt.offset((page-1)*limit).limit(limit)).all()
    return {"items":[dump(x) for x in items],"page":page,"limit":limit,"total":total,"pages":(total+limit-1)//limit}


@router.get('/cases/{case_id}/sla')
def case_sla(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    case = _case(session, case_id, user)
    now = datetime.now(timezone.utc)
    due = case.sla_due_at
    if not due:
        return {"status": "NOT_SET", "due_at": None}
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if case.status in {"RESOLVED", "CLOSED"}:
        status = "RESOLVED"
    elif due <= now:
        status = "BREACHED"
    elif (due - now).total_seconds() <= 3600:
        status = "AT_RISK"
    else:
        status = "ON_TRACK"
    return {"status": status, "due_at": due, "hours_remaining": round((due-now).total_seconds()/3600, 2)}

@router.get('/cases/{case_id}/recovery')
def get_recovery(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    case = _case(session, case_id, user)
    recovery = ensure_recovery(session, case)
    session.commit()
    return dump(recovery)

@router.post('/cases/{case_id}/recovery/initiate', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def start_recovery(case_id: str, payload: RecoveryInitiateRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    case = _case(session, case_id, user)
    try:
        recovery = initiate_recovery(session, case, recoverable_amount=payload.recoverable_amount, action_type=payload.action_type, external_reference=payload.external_reference, expected_recovery_at=payload.expected_recovery_at, action_note=payload.action_note, actor_reference=user.email)
    except CaseBusinessError as exc:
        raise AppError(str(exc)) from exc
    record_event(session, action='RECOVERY_INITIATED', resource_type='CASE_RECOVERY', resource_id=recovery.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'case_id':case.id,'recoverable_amount':str(recovery.recoverable_amount),'action_type':recovery.action_type})
    session.commit(); return dump(recovery)

@router.post('/cases/{case_id}/recovery/verify', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def verify_recovery_api(case_id: str, payload: RecoveryVerifyRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    case = _case(session, case_id, user)
    bank = session.scalar(select(BankTransaction).where(BankTransaction.id == payload.bank_transaction_id, BankTransaction.merchant_id == case.merchant_id))
    if not bank: raise NotFoundError('Bank transaction not found')
    try:
        recovery = verify_recovery(session, case, bank_transaction_id=payload.bank_transaction_id, verification_note=payload.verification_note, actor_reference=user.email)
    except CaseBusinessError as exc:
        raise AppError(str(exc)) from exc
    record_event(session, action='RECOVERY_VERIFIED', resource_type='CASE_RECOVERY', resource_id=recovery.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'case_id':case.id,'bank_transaction_id':bank.id,'verified_amount':str(recovery.recovered_amount)})
    session.commit(); return dump(recovery)

@router.post('/cases/{case_id}/recovery/unrecoverable', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def unrecoverable(case_id: str, payload: RecoveryUnrecoverableRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    case = _case(session, case_id, user)
    try:
        recovery = mark_unrecoverable(session, case, note=payload.note, actor_reference=user.email)
    except CaseBusinessError as exc:
        raise AppError(str(exc)) from exc
    record_event(session, action='RECOVERY_MARKED_UNRECOVERABLE', resource_type='CASE_RECOVERY', resource_id=recovery.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'case_id':case.id})
    session.commit(); return dump(recovery)

@router.get('/cases/{case_id}')
def get_case_api(case_id: str, session: Session=Depends(get_db), user=Depends(get_current_user)): return _detail(session,_case(session,case_id,user))

@router.post('/cases/{case_id}/assign', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def assign(case_id: str, payload: AssignRequest, request: Request, session: Session=Depends(get_db), user=Depends(get_current_user)):
    case=_case(session,case_id,user); before={'assigned_to':case.assigned_to}; value=assign_case(session,case,payload.assigned_to,payload.actor_reference)
    record_event(session, action=CASE_ASSIGNED, resource_type='CASE', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, before_snapshot=before, after_snapshot={'assigned_to':value.assigned_to})
    session.commit(); return dump(value)
@router.post('/cases/{case_id}/notes', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def note(case_id: str, payload: NoteRequest, request: Request, session: Session=Depends(get_db), user=Depends(get_current_user)):
    case=_case(session,case_id,user); value=add_note(session,case,payload.note,payload.author_reference)
    record_event(session, action=CASE_NOTE_ADDED, resource_type='CASE', resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'note_id':value.id})
    session.commit(); return dump(value)
@router.post('/cases/{case_id}/start', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def start(case_id: str, request: Request, payload: ActorRequest=ActorRequest(), session: Session=Depends(get_db), user=Depends(get_current_user)):
    case=_case(session,case_id,user); before={'status':case.status}; value=transition(session,case,'IN_PROGRESS',payload.actor_reference)
    record_event(session, action=CASE_STATUS_CHANGED, resource_type='CASE', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None) if request else None, ip_address=request.client.host if request and request.client else None, before_snapshot=before, after_snapshot={'status':value.status})
    session.commit(); return dump(value)
@router.post('/cases/{case_id}/resolve', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def resolve(case_id: str, payload: ResolveRequest, request: Request, session: Session=Depends(get_db), user=Depends(get_current_user)):
    case=_case(session,case_id,user); before={'status':case.status,'resolution_code':case.resolution_code}; value=transition(session,case,'RESOLVED',payload.actor_reference,payload.resolution_code,payload.resolution_note)
    record_event(session, action=CASE_RESOLVED, resource_type='CASE', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, before_snapshot=before, after_snapshot={'status':value.status,'resolution_code':value.resolution_code})
    session.commit(); return dump(value)
@router.post('/cases/{case_id}/reopen', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def reopen(case_id: str, request: Request, payload: ActorRequest=ActorRequest(), session: Session=Depends(get_db), user=Depends(get_current_user)):
    case=_case(session,case_id,user); before={'status':case.status}; value=transition(session,case,'REOPENED',payload.actor_reference)
    record_event(session, action=CASE_REOPENED, resource_type='CASE', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None) if request else None, ip_address=request.client.host if request and request.client else None, before_snapshot=before, after_snapshot={'status':value.status})
    session.commit(); return dump(value)
@router.post('/cases/{case_id}/exceptions', dependencies=[Depends(require_roles('ADMIN','OPS'))])
def add_exception(case_id: str, payload: AttachExceptionRequest, request: Request, session: Session=Depends(get_db), user=Depends(get_current_user)):
    _case(session,case_id,user)
    exc=session.get(ReconciliationException,payload.exception_id) if (test_admin_bypass(user)) else session.scalar(select(ReconciliationException).where(ReconciliationException.id==payload.exception_id, ReconciliationException.merchant_id==user.merchant_id))
    if not exc: raise AppError('Exception not found')
    case=_case(session,case_id,user); value=attach_exception(session,case,payload.exception_id,payload.actor_reference)
    record_event(session, action=EXCEPTION_ATTACHED_TO_CASE, resource_type='CASE', resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'exception_id':payload.exception_id})
    session.commit(); return _detail(session,value)
