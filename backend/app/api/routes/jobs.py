from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.jobs import JOB_TYPES, Job
from app.jobs_service import create_job, get_job, list_jobs, retry_job
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)])

CREATE_ROLES = {"ADMIN", "OPS"}
RETRY_ROLES = {"ADMIN", "OPS"}

class CreateJobRequest(BaseModel):
    job_type: str
    payload: dict = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


def _view(job: Job) -> dict:
    return {"job_id":job.job_id,"merchant_id":job.merchant_id,"job_type":job.job_type,"status":job.status,
            "attempt_count":job.attempt_count,"max_attempts":job.max_attempts,"created_at":job.created_at,
            "started_at":job.started_at,"completed_at":job.completed_at,"next_retry_at":job.next_retry_at,
            "last_error_code":job.last_error_code,"last_error_message_safe":job.last_error_message_safe,
            "request_id":job.request_id,"created_by":job.created_by,"result":job.result_json}

@router.post("", status_code=202, dependencies=[Depends(require_roles("ADMIN", "OPS"))])
def create(payload: CreateJobRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    try:
        job, created = create_job(session, merchant_id=user.merchant_id, job_type=payload.job_type, payload=payload.payload,
                                  idempotency_key=idempotency_key, created_by=user.id, request_id=getattr(request.state,"request_id",None),
                                  max_attempts=payload.max_attempts, actor_role=user.role)
        session.commit()
    except PermissionError as exc:
        session.rollback(); raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        session.rollback(); raise HTTPException(422, str(exc)) from exc
    return {"created":created,"job":_view(job)}

@router.get("")
def list_endpoint(status: str | None = None, job_type: str | None = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), session: Session = Depends(get_db), user=Depends(get_current_user)):
    if status and status.upper() not in {"QUEUED","RUNNING","RETRYING","SUCCEEDED","FAILED","DEAD_LETTERED"}: raise HTTPException(422,"Invalid job status")
    if job_type and job_type.upper() not in JOB_TYPES: raise HTTPException(422,"Invalid job type")
    items,total=list_jobs(session,merchant_id=user.merchant_id,page=page,limit=limit,status=status,job_type=job_type)
    return {"items":[_view(x) for x in items],"page":page,"limit":limit,"total":total,"pages":(total+limit-1)//limit}

@router.get("/{job_id}")
def detail(job_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    job=get_job(session,job_id,user.merchant_id)
    if not job: raise HTTPException(404,"Job not found")
    return _view(job)

@router.post("/{job_id}/retry")
def retry(job_id: str, request: Request, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN","OPS"))):
    job=get_job(session,job_id,user.merchant_id)
    if not job: raise HTTPException(404,"Job not found")
    try: return _view(retry_job(session,job,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,"request_id",None)))
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
