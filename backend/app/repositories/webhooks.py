from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import WebhookEvent

def get_event(session: Session, provider: str, event_id: str):
    return session.scalar(select(WebhookEvent).where(
        WebhookEvent.provider == provider, WebhookEvent.event_id == event_id
    ))
