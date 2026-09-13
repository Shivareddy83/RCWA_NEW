from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.audit.repository import get_event, list_events
from app.audit.schemas import AuditEventView
from app.security import get_current_user, require_roles
from app.core.errors import NotFoundError

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(get_current_user)])

@router.get("/events", response_model=dict)
def events(
    action: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str | None = Query(None, pattern="^(SUCCESS|FAILURE|DENIED)$"),
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    request_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
    user=Depends(require_roles("ADMIN", "OPS", "ANALYST")),
):
    items, total = list_events(session, merchant_id=user.merchant_id, action=action, actor_user_id=actor_user_id,
                               resource_type=resource_type, resource_id=resource_id, outcome=outcome,
                               start_date=start_date, end_date=end_date, request_id=request_id,
                               page=page, limit=limit)
    return {"items": [AuditEventView.model_validate({
        "event_id": x.event_id, "merchant_id": x.merchant_id, "actor_user_id": x.actor_user_id,
        "actor_role": x.actor_role, "actor_type": x.actor_type, "action": x.action,
        "resource_type": x.resource_type, "resource_id": x.resource_id, "request_id": x.request_id,
        "timestamp": x.timestamp, "outcome": x.outcome, "ip_address": x.ip_address,
        "metadata": x.metadata_json or {}, "before_snapshot": x.before_snapshot,
        "after_snapshot": x.after_snapshot, "previous_event_hash": x.previous_event_hash,
        "event_hash": x.event_hash,
    }).model_dump(mode="json") for x in items], "page": page, "limit": limit,
            "total": total, "pages": (total + limit - 1) // limit}

@router.get("/events/{event_id}", response_model=AuditEventView)
def event_detail(event_id: str, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN", "OPS", "ANALYST"))):
    event = get_event(session, event_id, user.merchant_id)
    if not event:
        raise NotFoundError("Audit event not found")
    return AuditEventView.model_validate({
        "event_id": event.event_id, "merchant_id": event.merchant_id, "actor_user_id": event.actor_user_id,
        "actor_role": event.actor_role, "actor_type": event.actor_type, "action": event.action,
        "resource_type": event.resource_type, "resource_id": event.resource_id, "request_id": event.request_id,
        "timestamp": event.timestamp, "outcome": event.outcome, "ip_address": event.ip_address,
        "metadata": event.metadata_json or {}, "before_snapshot": event.before_snapshot,
        "after_snapshot": event.after_snapshot, "previous_event_hash": event.previous_event_hash,
        "event_hash": event.event_hash,
    })
