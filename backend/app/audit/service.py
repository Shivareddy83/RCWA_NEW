from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.observability.metrics import inc

SENSITIVE_KEYS = {
    "password", "password_hash", "jwt", "token", "access_token", "api_key",
    "apikey", "webhook_secret", "private_key", "ai_api_key", "authorization",
}
OUTCOMES = {"SUCCESS", "FAILURE", "DENIED"}

_ACTION_METRICS = {
    "CASE_CREATED": "cases_created_total", "CASE_RESOLVED": "cases_resolved_total", "CASE_REOPENED": "cases_reopened_total",
    "EXCEPTION_CREATED": "exceptions_created_total", "EXCEPTION_RESOLVED": "exceptions_resolved_total",
}

def _bounded(value, allowed, fallback="other"):
    value = str(value or "").upper()
    return value if value in allowed else fallback


def _safe(value: Any):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items() if str(k).lower() not in SENSITIVE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat()
    return value


def canonical_payload(event: AuditEvent) -> dict:
    return {
        "event_id": event.event_id,
        "merchant_id": event.merchant_id,
        "actor_user_id": event.actor_user_id,
        "actor_role": event.actor_role,
        "actor_type": event.actor_type,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "request_id": event.request_id,
        "timestamp": event.timestamp.astimezone(timezone.utc).isoformat() if event.timestamp.tzinfo else event.timestamp.replace(tzinfo=timezone.utc).isoformat(),
        "outcome": event.outcome,
        "ip_address": event.ip_address,
        "metadata": _safe(event.metadata_json or {}),
        "before_snapshot": _safe(event.before_snapshot),
        "after_snapshot": _safe(event.after_snapshot),
        "previous_event_hash": event.previous_event_hash,
    }


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def calculate_event_hash(previous_event_hash: str | None, payload: dict) -> str:
    canonical = canonical_json(payload).encode("utf-8")
    return hashlib.sha256((previous_event_hash or "").encode("utf-8") + canonical).hexdigest()


def _latest(session: Session) -> AuditEvent | None:
    return session.scalar(select(AuditEvent).order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc()).limit(1))


def record_event(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    merchant_id: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    actor_type: str = "USER",
    request_id: str | None = None,
    outcome: str = "SUCCESS",
    ip_address: str | None = None,
    metadata: dict | None = None,
    before_snapshot: dict | None = None,
    after_snapshot: dict | None = None,
    timestamp: datetime | None = None,
) -> AuditEvent:
    if outcome not in OUTCOMES:
        raise ValueError(f"Invalid audit outcome: {outcome}")
    if not merchant_id and actor_type not in {"SYSTEM_GLOBAL"}:
        # Unknown-identity authentication failures are the only intentionally unscoped events.
        # They cannot safely be assigned to a merchant without turning the audit log into an auth oracle.
        pass
    now = timestamp or datetime.now(timezone.utc)
    event = AuditEvent(
        id=uuid4().hex,
        event_id=str(uuid4()),
        merchant_id=merchant_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        actor_type=actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        timestamp=now,
        outcome=outcome,
        ip_address=ip_address,
        metadata_json=_safe(metadata or {}),
        before_snapshot=_safe(before_snapshot),
        after_snapshot=_safe(after_snapshot),
        previous_event_hash=None,
        event_hash="",
    )
    previous = _latest(session)
    event.previous_event_hash = previous.event_hash if previous else None
    event.event_hash = calculate_event_hash(event.previous_event_hash, canonical_payload(event))
    try:
        session.add(event)
        session.flush()
    except Exception:
        inc("audit_events_failed_total")
        raise
    inc("audit_events_created_total")
    if outcome == "DENIED":
        inc("audit_events_denied_total")
    if action in _ACTION_METRICS:
        inc(_ACTION_METRICS[action])
    if action == "EXCEPTION_ACKNOWLEDGED":
        inc("exceptions_acknowledged_total")
    if action == "CASE_ASSIGNED":
        inc("case_assignments_total")
    if action == "CASE_NOTE_ADDED":
        inc("case_notes_added_total")
    if action == "CASE_STATUS_CHANGED":
        after = after_snapshot or {}
        inc("case_status_transitions_total", labels={"status": _bounded(after.get("to"), {"OPEN","IN_PROGRESS","RESOLVED","REOPENED"}), "priority": "other", "resolution_code": "other"})
    if action in {"CASE_CREATED", "CASE_RESOLVED", "CASE_REOPENED"}:
        after = after_snapshot or {}
        inc("case_events_total", labels={"status": _bounded(after.get("status"), {"OPEN","IN_PROGRESS","RESOLVED","REOPENED"}), "priority": _bounded(after.get("priority"), {"LOW","MEDIUM","HIGH","CRITICAL"}), "resolution_code": _bounded(after.get("resolution_code"), {"RESOLVED","DUPLICATE","FALSE_POSITIVE","NOT_ACTIONABLE","OTHER"})})
    if action == "EXCEPTION_CREATED":
        meta = metadata or {}
        inc("exception_events_total", labels={"exception_code": _bounded(meta.get("exception_code"), {"PAYMENT_NOT_SETTLED","SETTLEMENT_WITHOUT_PAYMENT","REFUND_WITHOUT_PAYMENT","REFUND_NOT_SETTLED","AMOUNT_MISMATCH","STATUS_MISMATCH","DUPLICATE_PAYMENT","DUPLICATE_REFUND","DUPLICATE_SETTLEMENT","AMBIGUOUS_MATCH","DELAYED_SETTLEMENT","UNKNOWN_REFERENCE"}), "severity": _bounded(meta.get("severity"), {"LOW","MEDIUM","HIGH","CRITICAL"})})
    return event


def verify_hash_chain(session: Session) -> tuple[bool, str | None]:
    events = session.scalars(select(AuditEvent).order_by(AuditEvent.timestamp, AuditEvent.id)).all()
    previous_hash = None
    for event in events:
        if event.previous_event_hash != previous_hash:
            return False, event.event_id
        expected = calculate_event_hash(previous_hash, canonical_payload(event))
        if event.event_hash != expected:
            return False, event.event_id
        previous_hash = event.event_hash
    return True, None
