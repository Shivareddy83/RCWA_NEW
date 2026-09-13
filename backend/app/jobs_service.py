from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_event
from app.core.time import utc_now
from app.jobs import JOB_TYPES, Job, JobStatus, deterministic_idempotency_key, now_plus
from app.observability.metrics import inc, observe

MAX_IDEMPOTENCY_KEY = 200


def _safe_error(exc: Exception) -> tuple[str, str]:
    name = type(exc).__name__
    message = str(exc).replace("\n", " ")[:500]
    lower = message.lower()
    if "timeout" in lower:
        category = "timeout"
    elif "rate limit" in lower or "429" in lower:
        category = "rate_limit"
    elif any(x in lower for x in ("connection", "network", "unavailable", "temporarily")):
        category = "transient_dependency"
    elif isinstance(exc, (PermissionError,)):
        category = "authorization"
    elif isinstance(exc, (ValueError, KeyError, TypeError)):
        category = "validation"
    elif name in {"LookupError", "FileNotFoundError"}:
        category = "not_found"
    else:
        category = "unknown"
    return category, message


def is_retryable(exc: Exception) -> bool:
    category, _ = _safe_error(exc)
    return category in {"timeout", "transient_dependency", "rate_limit", "OperationalError", "ConnectionError"}


def create_job(session: Session, *, merchant_id: str, job_type: str, payload: dict, idempotency_key: str,
               created_by: str | None, request_id: str | None, max_attempts: int = 3, actor_role: str | None = None) -> tuple[Job, bool]:
    job_type = job_type.upper()
    if job_type not in JOB_TYPES:
        raise ValueError("Unsupported job type")
    payload = dict(payload or {})
    supplied_merchant = payload.pop("merchant_id", None)
    if supplied_merchant is not None and supplied_merchant != merchant_id:
        raise PermissionError("Job merchant scope cannot be changed by the client")
    sensitive = {"password", "password_hash", "token", "access_token", "jwt", "authorization", "api_key", "apikey", "webhook_secret", "private_key", "ai_api_key", "secret", "credential", "credentials"}
    def scrub(value):
        if isinstance(value, dict): return {str(k): scrub(v) for k, v in value.items() if str(k).lower() not in sensitive}
        if isinstance(value, list): return [scrub(v) for v in value]
        return value
    payload = scrub(payload)
    key = idempotency_key.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY:
        raise ValueError("Invalid Idempotency-Key")
    existing = session.scalar(select(Job).where(Job.merchant_id == merchant_id, Job.idempotency_key == key))
    if existing:
        return existing, False
    job = Job(
        merchant_id=merchant_id,
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        max_attempts=max(1, min(int(max_attempts), 10)),
        request_id=request_id,
        created_by=created_by,
        payload_json=payload,
        idempotency_key=key,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Job).where(Job.merchant_id == merchant_id, Job.idempotency_key == key))
        if existing:
            return existing, False
        raise
    record_event(session, action="JOB_CREATED", resource_type="JOB", resource_id=job.job_id,
                 merchant_id=merchant_id, actor_user_id=created_by, actor_role=actor_role,
                 actor_type="USER", request_id=request_id,
                 metadata={"job_type": job.job_type, "max_attempts": job.max_attempts})
    inc("jobs_created_total", labels={"job_type": job.job_type, "status": JobStatus.QUEUED.value, "failure_category": "none"})
    return job, True


def list_jobs(session: Session, *, merchant_id: str, page: int, limit: int, status: str | None = None, job_type: str | None = None):
    from sqlalchemy import func
    q = select(Job).where(Job.merchant_id == merchant_id)
    count_q = select(func.count(Job.id)).where(Job.merchant_id == merchant_id)
    if status:
        q = q.where(Job.status == status.upper()); count_q = count_q.where(Job.status == status.upper())
    if job_type:
        q = q.where(Job.job_type == job_type.upper()); count_q = count_q.where(Job.job_type == job_type.upper())
    total = session.scalar(count_q) or 0
    items = session.scalars(q.order_by(Job.created_at.desc(), Job.id.desc()).offset((page - 1) * limit).limit(limit)).all()
    return items, total


def get_job(session: Session, job_id: str, merchant_id: str) -> Job | None:
    return session.scalar(select(Job).where(Job.job_id == job_id, Job.merchant_id == merchant_id))


def claim_job(session: Session, *, worker_id: str, lease_seconds: int) -> Job | None:
    now = utc_now()
    candidate = session.scalar(
        select(Job).where(
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RETRYING.value]),
            or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
        ).order_by(Job.created_at, Job.id).limit(1)
    )
    if not candidate:
        return None
    lease_until = now_plus(lease_seconds)
    result = session.execute(
        update(Job).where(
            Job.id == candidate.id,
            Job.status == candidate.status,
            or_(Job.next_retry_at.is_(None), Job.next_retry_at <= now),
        ).execution_options(synchronize_session=False).values(status=JobStatus.RUNNING.value, started_at=now, worker_id=worker_id, lease_expires_at=lease_until,
                  attempt_count=candidate.attempt_count + 1, updated_at=now)
    )
    if result.rowcount != 1:
        session.rollback()
        return None
    session.commit()
    session.expire_all()
    return session.scalar(select(Job).where(Job.id == candidate.id))


def recover_stale_jobs(session: Session, *, stale_before: datetime) -> int:
    jobs = session.scalars(select(Job).where(Job.status == JobStatus.RUNNING.value, Job.lease_expires_at < stale_before)).all()
    recovered = 0
    for job in jobs:
        if job.attempt_count >= job.max_attempts:
            job.status = JobStatus.DEAD_LETTERED.value
            job.completed_at = utc_now()
            job.last_error_code = "WORKER_CRASH_RECOVERY_EXHAUSTED"
            job.last_error_message_safe = "Worker lease expired and retry limit was exhausted."
            inc("jobs_dead_lettered_total", labels={"job_type": job.job_type, "status": job.status, "failure_category": "worker_crash"})
        else:
            job.status = JobStatus.RETRYING.value
            job.next_retry_at = utc_now()
            job.last_error_code = "WORKER_CRASH_RECOVERED"
            job.last_error_message_safe = "Worker lease expired; job returned to retryable state."
            inc("jobs_retried_total", labels={"job_type": job.job_type, "status": job.status, "failure_category": "worker_crash"})
        job.worker_id = None; job.lease_expires_at = None
        recovered += 1
    if recovered:
        inc("jobs_stale_recovered_total", value=recovered)
        session.commit()
    return recovered


def retry_job(session: Session, job: Job, *, actor_user_id: str, actor_role: str, request_id: str | None):
    if job.status not in {JobStatus.FAILED.value, JobStatus.DEAD_LETTERED.value}:
        raise ValueError("Only terminal failed jobs can be retried")
    job.status = JobStatus.QUEUED.value
    job.attempt_count = 0
    job.result_json = None
    job.started_at = None; job.completed_at = None; job.next_retry_at = None
    job.last_error_code = None; job.last_error_message_safe = None
    job.worker_id = None; job.lease_expires_at = None
    record_event(session, action="JOB_RETRIED", resource_type="JOB", resource_id=job.job_id, merchant_id=job.merchant_id,
                 actor_user_id=actor_user_id, actor_role=actor_role, actor_type="USER", request_id=request_id,
                 metadata={"job_type": job.job_type})
    session.commit()
    return job


def enqueue_due_connector_jobs(session: Session, *, limit: int = 20) -> int:
    from app.models import DataConnector
    from app.core.time import utc_now
    now = utc_now()
    connectors = session.scalars(select(DataConnector).where(DataConnector.sync_enabled.is_(True), DataConnector.status == "CONNECTED", DataConnector.next_sync_at.is_not(None), DataConnector.next_sync_at <= now).order_by(DataConnector.next_sync_at).with_for_update(skip_locked=True).limit(limit)).all()
    created = 0
    for connector in connectors:
        key = f"scheduled-sync:{connector.id}:{now.strftime('%Y%m%d%H%M')}"
        job, was_created = create_job(session, merchant_id=connector.merchant_id, job_type="SYNC_CONNECTOR", payload={"connector_id": connector.id, "days": max(1, connector.sync_interval_minutes // 1440 + 2)}, idempotency_key=key, created_by=None, request_id=None, actor_role=None)
        connector.next_sync_at = now + __import__('datetime').timedelta(minutes=connector.sync_interval_minutes)
        created += int(was_created)
    if connectors:
        session.commit()
    return created
