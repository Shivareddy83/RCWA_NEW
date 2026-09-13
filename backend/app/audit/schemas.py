from datetime import datetime
from pydantic import BaseModel

class AuditEventView(BaseModel):
    event_id: str
    merchant_id: str | None
    actor_user_id: str | None
    actor_role: str | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    request_id: str | None
    timestamp: datetime
    outcome: str
    ip_address: str | None
    metadata: dict
    before_snapshot: dict | None
    after_snapshot: dict | None
    previous_event_hash: str | None
    event_hash: str
