from __future__ import annotations

import logging
import os
import threading
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import select

from app.ai.service import AIServiceError, investigate
from app.api.deps import get_db
from app.audit import record_event
from app.evidence.builder import build_evidence
from app.jobs import Job, JobStatus, retry_delay_seconds
from app.jobs_service import claim_job, is_retryable, recover_stale_jobs
from app.models import Case, ReconciliationException
from app.observability.metrics import inc, observe
from app.reconciliation.engine import run_reconciliation
from app.ingestion import ingest_records
from app.db.session import SessionLocal
from app.core.config import settings, validate_startup_config

logger = logging.getLogger("rcaa.worker")

validate_startup_config()

BASE_BACKOFF = float(os.getenv("JOB_RETRY_BASE_SECONDS", "1"))
MAX_BACKOFF = float(os.getenv("JOB_RETRY_MAX_SECONDS", "30"))
LEASE_SECONDS = int(os.getenv("JOB_LEASE_SECONDS", "60"))


def _audit(job, action, outcome, metadata, *, request_id=None):
    session = SessionLocal()
    try:
        record_event(session, action=action, resource_type="JOB", resource_id=job.job_id, merchant_id=job.merchant_id,
                     actor_user_id=job.created_by, actor_type="SYSTEM", request_id=request_id or job.request_id,
                     outcome=outcome, metadata={"job_type": job.job_type, **metadata})
        session.commit()
    finally:
        session.close()


def _process(session, job: Job) -> dict:
    payload = job.payload_json or {}
    if payload.get("merchant_id") and payload["merchant_id"] != job.merchant_id:
        raise PermissionError("Job merchant scope mismatch")
    jt = job.job_type
    if jt.startswith("INGEST_"):
        mapping = {
            "INGEST_PAYMENTS": "payment", "INGEST_REFUNDS": "refund",
            "INGEST_SETTLEMENTS": "settlement", "INGEST_BANK_TRANSACTIONS": "bank_transaction",
        }
        record_type = mapping[jt]
        records = payload.get("records")
        if not isinstance(records, list): raise ValueError("records must be a list")
        records = [dict(record, merchant_id=job.merchant_id) for record in records]
        result = ingest_records(session, records, source=str(payload.get("source", "background_job")),
                                provider=payload.get("provider"), record_type=record_type, merchant_id=job.merchant_id, commit=False)
        return result
    if jt == "RUN_RECONCILIATION":
        return run_reconciliation(session, return_report=True, merchant_id=job.merchant_id)
    if jt == "SYNC_CONNECTOR":
        from app.models import DataConnector
        from app.services.connectors import sync_razorpay
        connector_id = str(payload.get("connector_id", ""))
        connector = session.scalar(select(DataConnector).where(DataConnector.id == connector_id, DataConnector.merchant_id == job.merchant_id))
        if not connector:
            raise LookupError("Connector not found")
        if connector.provider != "razorpay":
            raise ValueError("Connector provider is not supported for automatic sync")
        result = sync_razorpay(session, connector, days=int(payload.get("days", 7)))
        # Automatic provider synchronization closes the loop by reconciling newly ingested records.
        # NOTE: run_reconciliation is already imported at module scope (top of file); a redundant
        # local import here previously made Python treat it as a function-local name for this
        # entire _process() function, which raised UnboundLocalError the moment the earlier
        # RUN_RECONCILIATION branch above tried to call it. Removed — use the module-level import.
        from app.exceptions.engine import generate_exceptions
        recon = run_reconciliation(session, return_report=True, merchant_id=job.merchant_id)
        recon["exceptions"] = generate_exceptions(session, merchant_id=job.merchant_id)
        result["reconciliation"] = {"run_id": recon.get("run_id"), "created_cases": recon.get("created_cases", 0), "exceptions": recon.get("exceptions", {})}
        from app.core.time import utc_now
        from datetime import timedelta
        connector.last_sync_at = utc_now()
        connector.next_sync_at = utc_now() + timedelta(minutes=connector.sync_interval_minutes) if connector.sync_enabled else None
        connector.last_sync_status = "SUCCEEDED"
        connector.last_sync_summary = result
        session.flush()
        return result
    case_id = payload.get("case_id")
    if not case_id: raise ValueError("case_id is required")
    case = session.scalar(select(Case).where(Case.id == case_id, Case.merchant_id == job.merchant_id))
    if not case: raise LookupError("Case not found")
    if jt == "BUILD_EVIDENCE":
        bundle = build_evidence(session, case)
        return {"case_id": case.id, "evidence_ids": [x.id for x in bundle.items], "complete": bundle.complete, "missing": bundle.missing}
    if jt == "GENERATE_DETERMINISTIC_RCA":
        from app.rca.engine import generate_rca
        rca, created = generate_rca(session, case)
        return {"case_id": case.id, "rca_id": rca.id, "created": created, "root_cause_code": rca.root_cause}
    if jt == "AI_INVESTIGATION":
        if not case.rca: raise LookupError("RCA not found")
        question = str(payload.get("question", "")).strip()
        if not question: raise ValueError("question is required")
        result, request_fingerprint = investigate(session, case, question)
        return {"case_id": case.id, "request_fingerprint": request_fingerprint, "result": result.model_dump()}
    raise ValueError("Unsupported job type")


def execute_claimed_job(job_id: str, worker_id: str | None = None) -> str:
    session = SessionLocal()
    started = monotonic()
    job = session.scalar(select(Job).where(Job.job_id == job_id))
    if not job or job.status != JobStatus.RUNNING.value:
        session.close(); return "SKIPPED"
    if worker_id is not None and job.worker_id != worker_id:
        session.close(); return "SKIPPED"
    if worker_id is not None and job.lease_expires_at is not None:
        lease = job.lease_expires_at
        now = __import__("app.core.time", fromlist=["utc_now"]).utc_now()
        if lease.tzinfo is None: lease = lease.replace(tzinfo=now.tzinfo)
        if lease <= now:
            session.close(); return "SKIPPED"
    inc("jobs_started_total", labels={"job_type": job.job_type, "status": JobStatus.RUNNING.value, "failure_category": "none"})
    heartbeat_stop = threading.Event()
    heartbeat_thread = None
    if worker_id is not None:
        interval = max(5.0, LEASE_SECONDS / 3.0)
        def _heartbeat():
            while not heartbeat_stop.wait(interval):
                hb = SessionLocal()
                try:
                    from sqlalchemy import update
                    from app.core.time import utc_now
                    now = utc_now()
                    hb.execute(update(Job).where(Job.job_id == job_id, Job.status == JobStatus.RUNNING.value, Job.worker_id == worker_id)
                               .values(lease_expires_at=__import__("app.jobs", fromlist=["now_plus"]).now_plus(LEASE_SECONDS), updated_at=now))
                    hb.commit()
                except Exception:
                    hb.rollback()
                    logger.exception("job_heartbeat_failed", extra={"job_id": job_id, "worker_id": worker_id})
                finally:
                    hb.close()
        heartbeat_thread = threading.Thread(target=_heartbeat, name=f"job-heartbeat-{job_id}", daemon=True)
        heartbeat_thread.start()
    try:
        result = _process(session, job)
        job.result_json = result if isinstance(result, dict) else {"result": result}
        job.status = JobStatus.SUCCEEDED.value
        job.completed_at = __import__("app.core.time", fromlist=["utc_now"]).utc_now()
        job.last_error_code = None; job.last_error_message_safe = None
        job.worker_id = None; job.lease_expires_at = None
        record_event(session, action="JOB_SUCCEEDED", resource_type="JOB", resource_id=job.job_id, merchant_id=job.merchant_id,
                     actor_user_id=job.created_by, actor_type="SYSTEM", request_id=job.request_id,
                     metadata={"job_type": job.job_type, "attempt": job.attempt_count})
        session.commit()
        inc("jobs_succeeded_total", labels={"job_type": job.job_type, "status": job.status, "failure_category": "none"})
        observe("job_duration_seconds", monotonic() - started, labels={"job_type": job.job_type, "status": job.status})
        logger.info("job_succeeded", extra={"job_id":job.job_id,"job_type":job.job_type,"request_id":job.request_id,"merchant_id":job.merchant_id,"attempt":job.attempt_count,"status":job.status,"duration_ms":round((monotonic()-started)*1000,2)})
        return job.status
    except Exception as exc:
        session.rollback()
        job = session.scalar(select(Job).where(Job.job_id == job_id))
        category, message = __import__("app.jobs_service", fromlist=["_safe_error"])._safe_error(exc)
        retryable = is_retryable(exc)
        if isinstance(exc, (PermissionError, LookupError, ValueError)):
            retryable = False
        if isinstance(exc, AIServiceError):
            retryable = exc.code in {"AI_TIMEOUT", "AI_PROVIDER_UNAVAILABLE", "AI_RATE_LIMIT", "AI_ERROR"}
        if retryable and job.attempt_count < job.max_attempts:
            job.status = JobStatus.RETRYING.value
            job.next_retry_at = __import__("app.jobs", fromlist=["now_plus"]).now_plus(retry_delay_seconds(job.attempt_count, BASE_BACKOFF, MAX_BACKOFF))
            job.last_error_code = category.upper()[:80]
            job.last_error_message_safe = message
            inc("jobs_retried_total", labels={"job_type": job.job_type, "status": job.status, "failure_category": category})
            action = "JOB_RETRIED"
        else:
            job.status = JobStatus.DEAD_LETTERED.value if job.attempt_count >= job.max_attempts else JobStatus.FAILED.value
            job.completed_at = __import__("app.core.time", fromlist=["utc_now"]).utc_now()
            job.last_error_code = category.upper()[:80]
            job.last_error_message_safe = message
            inc("jobs_dead_lettered_total" if job.status == JobStatus.DEAD_LETTERED.value else "jobs_failed_total",
                labels={"job_type": job.job_type, "status": job.status, "failure_category": category})
            action = "JOB_DEAD_LETTERED" if job.status == JobStatus.DEAD_LETTERED.value else "JOB_FAILED"
        job.worker_id = None; job.lease_expires_at = None
        record_event(session, action=action, resource_type="JOB", resource_id=job.job_id, merchant_id=job.merchant_id,
                     actor_user_id=job.created_by, actor_type="SYSTEM", request_id=job.request_id, outcome="FAILURE",
                     metadata={"job_type":job.job_type,"attempt":job.attempt_count,"failure_category":category,"error_code":job.last_error_code})
        session.commit()
        observe("job_duration_seconds", monotonic()-started, labels={"job_type":job.job_type,"status":job.status})
        logger.error("job_failed", extra={"job_id":job.job_id,"job_type":job.job_type,"request_id":job.request_id,"merchant_id":job.merchant_id,"attempt":job.attempt_count,"status":job.status,"duration_ms":round((monotonic()-started)*1000,2),"failure_category":category})
        return job.status
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=max(1.0, min(5.0, LEASE_SECONDS / 3.0)))
        session.close()


def run_once() -> str | None:
    session = SessionLocal()
    worker_id = str(uuid4())
    try:
        recover_stale_jobs(session, stale_before=__import__("app.jobs", fromlist=["now_plus"]).now_plus(-LEASE_SECONDS))
        job = claim_job(session, worker_id=worker_id, lease_seconds=LEASE_SECONDS)
        if not job: return None
        job_id = job.job_id
    finally:
        session.close()
    return execute_claimed_job(job_id, worker_id=worker_id)


def worker_loop(stop_event: threading.Event | None = None, poll_seconds: float = 1.0):
    stop_event = stop_event or threading.Event()
    last_connector_schedule = 0.0
    while not stop_event.is_set():
        now_mono = monotonic()
        if now_mono - last_connector_schedule >= 30:
            scheduler = SessionLocal()
            try:
                from app.jobs_service import enqueue_due_connector_jobs
                enqueue_due_connector_jobs(scheduler)
            except Exception:
                scheduler.rollback()
                logger.exception("connector_scheduler_failed")
            finally:
                scheduler.close()
            last_connector_schedule = now_mono
        status = run_once()
        if status is None: sleep(poll_seconds)


if __name__ == "__main__":
    import signal
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    logger.info("worker_starting")
    worker_loop(stop_event=stop, poll_seconds=float(os.getenv("JOB_POLL_SECONDS", "1")))
    logger.info("worker_stopped")
