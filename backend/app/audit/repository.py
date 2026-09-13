from __future__ import annotations
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import AuditEvent


def list_events(session: Session, *, merchant_id: str, action: str | None = None,
                actor_user_id: str | None = None, resource_type: str | None = None,
                resource_id: str | None = None, outcome: str | None = None,
                start_date: datetime | None = None, end_date: datetime | None = None,
                request_id: str | None = None, page: int = 1, limit: int = 50):
    stmt = select(AuditEvent).where(AuditEvent.merchant_id == merchant_id).order_by(AuditEvent.timestamp.desc(), AuditEvent.id.desc())
    if action: stmt = stmt.where(AuditEvent.action == action)
    if actor_user_id: stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if resource_type: stmt = stmt.where(AuditEvent.resource_type == resource_type)
    if resource_id: stmt = stmt.where(AuditEvent.resource_id == resource_id)
    if outcome: stmt = stmt.where(AuditEvent.outcome == outcome)
    if start_date: stmt = stmt.where(AuditEvent.timestamp >= start_date)
    if end_date: stmt = stmt.where(AuditEvent.timestamp <= end_date)
    if request_id: stmt = stmt.where(AuditEvent.request_id == request_id)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = session.scalars(stmt.offset((page - 1) * limit).limit(limit)).all()
    return items, total


def get_event(session: Session, event_id: str, merchant_id: str):
    return session.scalar(select(AuditEvent).where(AuditEvent.event_id == event_id, AuditEvent.merchant_id == merchant_id))
