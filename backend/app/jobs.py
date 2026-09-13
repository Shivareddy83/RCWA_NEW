from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.db.base import Base


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


JOB_TYPES = {
    "INGEST_PAYMENTS",
    "INGEST_REFUNDS",
    "INGEST_SETTLEMENTS",
    "INGEST_BANK_TRANSACTIONS",
    "RUN_RECONCILIATION",
    "BUILD_EVIDENCE",
    "GENERATE_DETERMINISTIC_RCA",
    "AI_INVESTIGATION",
    "SYNC_CONNECTOR",
}


class Job(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_background_job_merchant_idempotency"),
        Index("ix_background_job_queue", "status", "next_retry_at", "created_at"),
        Index("ix_background_job_merchant_created", "merchant_id", "created_at"),
        Index("ix_background_job_type_status", "job_type", "status"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, default=lambda: str(uuid4()))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default=JobStatus.QUEUED.value, index=True)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String)
    last_error_message_safe: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String, index=True)
    created_by: Mapped[str | None] = mapped_column(String, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


def deterministic_idempotency_key(job_type: str, payload: dict) -> str:
    body = {"job_type": job_type, "payload": payload}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def retry_delay_seconds(attempt: int, base: float, maximum: float) -> float:
    return min(maximum, base * (2 ** max(0, attempt - 1)))


def now_plus(seconds: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
