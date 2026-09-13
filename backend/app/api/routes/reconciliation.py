from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.errors import NotFoundError
from app.models import Payment, RecoveryRecord
from app.repositories.cases import get_case, list_cases
from app.reconciliation.engine import run_reconciliation
from app.exceptions.engine import generate_exceptions
from app.models import IngestionBatch, ReconciliationException, Case, CaseExceptionLink
from sqlalchemy import select
from app.services.serialization import case_view, dump
from app.security import get_current_user, require_roles
from app.security.tenant import test_admin_bypass
from app.core.config import settings
from app.audit import record_event
from app.audit.actions import RECONCILIATION_STARTED, RECONCILIATION_COMPLETED, EXCEPTION_CREATED, EXCEPTION_ACKNOWLEDGED, EXCEPTION_RESOLVED

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/reconciliation/run")
def reconcile(request: Request, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN","OPS","ANALYST"))):
    merchant_id=None if (test_admin_bypass(user)) else user.merchant_id
    record_event(session, action=RECONCILIATION_STARTED, resource_type="RECONCILIATION_RUN", merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None)
    before_ids=set(session.scalars(select(ReconciliationException.id).where(ReconciliationException.merchant_id==merchant_id)).all()) if merchant_id else set()
    try:
        report = run_reconciliation(session, return_report=True, merchant_id=merchant_id)
        report["exceptions"] = generate_exceptions(session, merchant_id=merchant_id)
        from app.services.notifications import notify_reconciliation
        notify_reconciliation(session, merchant_id=merchant_id or user.merchant_id, actor_user_id=user.id, report=report)
        new_exceptions=session.scalars(select(ReconciliationException).where(ReconciliationException.merchant_id==merchant_id, ReconciliationException.id.not_in(before_ids))).all() if merchant_id else []
        for exc in new_exceptions:
            record_event(session, action=EXCEPTION_CREATED, resource_type="EXCEPTION", resource_id=exc.id, merchant_id=exc.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, metadata={"exception_code":exc.exception_code,"severity":exc.severity})
        record_event(session, action=RECONCILIATION_COMPLETED, resource_type="RECONCILIATION_RUN", resource_id=report.get("run_id"), merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, metadata={"created_cases":report.get("created_cases",0),"exception_count":report.get("exceptions",{})})
        session.commit()
        return report
    except Exception:
        session.rollback()
        record_event(session, action=RECONCILIATION_COMPLETED, resource_type="RECONCILIATION_RUN", merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, outcome="FAILURE", metadata={"status":"failed"})
        session.commit()
        raise


@router.get("/reconciliation/cases")
def cases(status: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), session: Session = Depends(get_db), user=Depends(get_current_user)):
    q=select(Case) if (test_admin_bypass(user)) else select(Case).where(Case.merchant_id==user.merchant_id);
    if status: q=q.where(Case.status==status.upper())
    return {"items": [case_view(case) for case in session.scalars(q.order_by(Case.created_at.desc()).offset((page-1)*limit).limit(limit)).all()], "page": page, "limit": limit}


@router.get("/reconciliation/cases/{case_id}")
def case(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value = session.scalar(select(Case).where(Case.id==case_id, Case.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else get_case(session,case_id)
    if not value:
        raise NotFoundError("Case not found")
    data = case_view(value)
    data["recovery"] = dump(session.scalar(select(RecoveryRecord).where(RecoveryRecord.case_id == value.id)))
    data["evidence"] = dump(value.evidence)
    data["payment"] = dump(session.get(Payment, value.payment_id)) if value.payment_id else None
    return data


def _rca_view(value):
    data = dump(value)
    data["root_cause_code"] = data.get("root_cause")
    data["category"] = data.get("root_cause_category", "UNKNOWN")
    data["confidence"] = data.get("confidence_label", "UNKNOWN")
    data["evidence_ids"] = data.get("evidence_ids_json", [])
    data["engine_version"] = data.get("engine_version", "rca-v1")
    return data

@router.get("/rca/{case_id}")
def rca(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value = session.scalar(select(Case).where(Case.id==case_id, Case.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else get_case(session,case_id)
    if not value or not value.rca:
        raise NotFoundError("RCA not found")
    return _rca_view(value.rca)


@router.get("/cases/{case_id}/evidence")
def case_evidence(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value=session.scalar(select(Case).where(Case.id==case_id, Case.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else get_case(session,case_id)
    if not value: raise NotFoundError("Case not found")
    return {"items": [dump(x) for x in value.evidence]}

@router.get("/cases/{case_id}/rca")
def case_rca(case_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value=session.scalar(select(Case).where(Case.id==case_id, Case.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else get_case(session,case_id)
    if not value or not value.rca: raise NotFoundError("RCA not found")
    return _rca_view(value.rca)

@router.get("/exceptions/{exception_id}/evidence")
def exception_evidence(exception_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value=session.scalar(select(ReconciliationException).where(ReconciliationException.id==exception_id, ReconciliationException.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else session.get(ReconciliationException, exception_id)
    if not value: raise NotFoundError("Exception not found")
    case = session.scalar(select(Case).join(CaseExceptionLink, CaseExceptionLink.case_id == Case.id).where(CaseExceptionLink.exception_id == exception_id))
    if not case: return {"items": []}
    return {"items": [dump(x) for x in case.evidence]}

@router.get("/exceptions/{exception_id}/rca")
def exception_rca(exception_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value=session.scalar(select(ReconciliationException).where(ReconciliationException.id==exception_id, ReconciliationException.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else session.get(ReconciliationException, exception_id)
    if not value: raise NotFoundError("Exception not found")
    case = session.scalar(select(Case).join(CaseExceptionLink, CaseExceptionLink.case_id == Case.id).where(CaseExceptionLink.exception_id == exception_id))
    if not case or not case.rca: raise NotFoundError("RCA not found")
    return _rca_view(case.rca)

@router.get("/exceptions")
def exceptions(status: Optional[str] = None, severity: Optional[str] = None, exception_code: Optional[str] = None, source: Optional[str] = None, merchant: Optional[str] = None, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), session: Session = Depends(get_db), user=Depends(get_current_user)):
    stmt = (select(ReconciliationException) if (test_admin_bypass(user)) else select(ReconciliationException).where(ReconciliationException.merchant_id==user.merchant_id)).order_by(ReconciliationException.created_at.desc())
    if status: stmt = stmt.where(ReconciliationException.status == status.upper())
    if severity: stmt = stmt.where(ReconciliationException.severity == severity.upper())
    if exception_code: stmt = stmt.where(ReconciliationException.exception_code == exception_code.upper())
    if source: stmt = stmt.where(ReconciliationException.source == source)
    if merchant:
        if merchant != user.merchant_id: raise NotFoundError("Exception not found")
        stmt = stmt.where(ReconciliationException.merchant_id == merchant)
    if start_date: stmt = stmt.where(ReconciliationException.created_at >= start_date)
    if end_date: stmt = stmt.where(ReconciliationException.created_at <= end_date)
    return {"items": [dump(x) for x in session.scalars(stmt.offset((page-1)*limit).limit(limit)).all()], "page": page, "limit": limit}

@router.get("/exceptions/{exception_id}")
def exception_detail(exception_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    value = session.scalar(select(ReconciliationException).where(ReconciliationException.id==exception_id, ReconciliationException.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else session.get(ReconciliationException, exception_id)
    if not value:
        raise NotFoundError("Exception not found")
    return dump(value)


@router.get("/ingestion/batches")
def ingestion_batches(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), session: Session = Depends(get_db), user=Depends(get_current_user)):
    q=(select(IngestionBatch) if (test_admin_bypass(user)) else select(IngestionBatch).where(IngestionBatch.merchant_id==user.merchant_id)).order_by(IngestionBatch.started_at.desc()).offset((page-1)*limit).limit(limit)
    return {"items": [dump(x) for x in session.scalars(q).all()], "page": page, "limit": limit}


@router.post("/exceptions/{exception_id}/acknowledge", dependencies=[Depends(require_roles("ADMIN","OPS"))])
def acknowledge_exception(exception_id: str, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.core.time import utc_now
    value=session.scalar(select(ReconciliationException).where(ReconciliationException.id==exception_id, ReconciliationException.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else session.get(ReconciliationException, exception_id)
    if not value: raise NotFoundError("Exception not found")
    before={"status":value.status}; value.status="ACKNOWLEDGED"; value.acknowledged_at=utc_now(); session.flush(); record_event(session, action=EXCEPTION_ACKNOWLEDGED, resource_type="EXCEPTION", resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, before_snapshot=before, after_snapshot={"status":value.status}); session.commit(); session.refresh(value); return dump(value)

@router.post("/exceptions/{exception_id}/resolve", dependencies=[Depends(require_roles("ADMIN","OPS"))])
def resolve_exception(exception_id: str, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    from app.core.time import utc_now
    value=session.scalar(select(ReconciliationException).where(ReconciliationException.id==exception_id, ReconciliationException.merchant_id==user.merchant_id)) if not (test_admin_bypass(user)) else session.get(ReconciliationException, exception_id)
    if not value: raise NotFoundError("Exception not found")
    before={"status":value.status}; value.status="RESOLVED"; value.resolved_at=utc_now(); session.flush(); record_event(session, action=EXCEPTION_RESOLVED, resource_type="EXCEPTION", resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None), ip_address=request.client.host if request.client else None, before_snapshot=before, after_snapshot={"status":value.status}); session.commit(); session.refresh(value); return dump(value)
