from sqlalchemy import event
from app.models.entities import AuditEvent

@event.listens_for(AuditEvent, "before_update")
def _audit_update_forbidden(mapper, connection, target):
    raise ValueError("Audit events are append-only")

@event.listens_for(AuditEvent, "before_delete")
def _audit_delete_forbidden(mapper, connection, target):
    raise ValueError("Audit events are append-only")
