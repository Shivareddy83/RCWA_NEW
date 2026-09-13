from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.api.deps import get_db
from app.security import get_current_user
from app.security.tenant import test_admin_bypass
from app.core.errors import AppError, NotFoundError
from app.core.config import settings
from app.repositories.cases import get_case
from app.models import Case
from app.ai.service import AIServiceError, investigate
from app.audit import record_event
from app.audit.actions import AI_INVESTIGATION_REQUESTED, AI_INVESTIGATION_COMPLETED, AI_INVESTIGATION_FAILED

router = APIRouter(dependencies=[Depends(get_current_user)])

class InvestigationRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)

def _run(case_id: str, question: str, session: Session, user=None, request: Request=None):
    if test_admin_bypass(user):
        case = get_case(session, case_id)
    else:
        case = session.scalar(select(Case).where(Case.id == case_id, Case.merchant_id == user.merchant_id))
    if not case:
        raise NotFoundError("Case not found")
    if not case.rca:
        raise NotFoundError("RCA not found")
    record_event(session, action=AI_INVESTIGATION_REQUESTED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state,"request_id",None) if request else None, ip_address=request.client.host if request and request.client else None, metadata={"question_length":len(question)})
    try:
        result, request_fingerprint = investigate(session, case, question)
    except AIServiceError as exc:
        status = 503 if exc.code in {"AI_MISSING_API_KEY", "AI_PROVIDER_UNAVAILABLE", "AI_TIMEOUT", "AI_RATE_LIMIT", "AI_ERROR", "AI_PROVIDER_CONFIG"} else 400
        record_event(session, action=AI_INVESTIGATION_FAILED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state,"request_id",None) if request else None, ip_address=request.client.host if request and request.client else None, outcome="FAILURE", metadata={"error_code":exc.code})
        session.commit()
        error = AppError(exc.message); error.status_code = status
        raise error
    record_event(session, action=AI_INVESTIGATION_COMPLETED, resource_type="CASE", resource_id=case.id, merchant_id=case.merchant_id, actor_user_id=user.id, actor_role=user.role, actor_type="USER", request_id=getattr(request.state,"request_id",None) if request else None, ip_address=request.client.host if request and request.client else None, metadata={"provider":result.provider,"model":result.model,"request_fingerprint":request_fingerprint})
    session.commit()
    payload = {
        "case_id": case.id,
        "deterministic_rca": {
            "root_cause_code": case.rca.root_cause,
            "category": case.rca.root_cause_category,
            "confidence": case.rca.confidence_label,
            "explanation": case.rca.explanation,
            "recommended_action": case.rca.recommended_action,
            "evidence_ids": case.rca.evidence_ids_json or [],
            "engine_version": case.rca.engine_version,
        },
        "ai_investigation": result.model_dump(),
        "request_fingerprint": request_fingerprint,
    }
    # Preserve the Stage 05 response fields for existing consumers while exposing the new structured result.
    payload["answer"] = result.summary + " " + " ".join(result.deterministic_findings)
    payload["source"] = result.provider
    payload["disclaimer"] = result.safety_disclaimer
    return payload

@router.post("/cases/{case_id}/ai/investigate")
def investigate_case(case_id: str, payload: InvestigationRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    return _run(case_id, payload.question, session, user, request)

@router.post("/ai/cases/{case_id}/ask")
def ask(case_id: str, question: str | None = Query(None, min_length=1, max_length=2000), payload: InvestigationRequest | None = None, request: Request = None, session: Session = Depends(get_db), user=Depends(get_current_user)):
    # Backward compatible query-parameter form plus the new structured body form.
    value = payload.question if payload else question
    if not value:
        raise AppError("question is required")
    return _run(case_id, value, session, user, request)
