from __future__ import annotations
from app.core.time import utc_now
from app.models import Notification, NotificationPreference
from sqlalchemy import select
from sqlalchemy.orm import Session


def create_notification(session: Session, *, merchant_id: str, user_id: str | None, kind: str, title: str, message: str, resource_type: str | None = None, resource_id: str | None = None, severity: str = 'INFO') -> Notification | None:
    pref = session.scalar(select(NotificationPreference).where(NotificationPreference.merchant_id == merchant_id))
    if pref and not getattr(pref, f'enable_{kind.lower()}', True):
        return None
    n = Notification(merchant_id=merchant_id, user_id=user_id, kind=kind, title=title, message=message, resource_type=resource_type, resource_id=resource_id, severity=severity)
    session.add(n)
    return n


def notify_reconciliation(session: Session, *, merchant_id: str, actor_user_id: str | None, report: dict) -> int:
    exceptions = report.get('exceptions', {})
    total = int(exceptions.get('created', 0)) if isinstance(exceptions, dict) else 0
    if not total:
        return 0
    create_notification(session, merchant_id=merchant_id, user_id=actor_user_id, kind='EXCEPTIONS', title='Reconciliation exceptions detected', message=f'{total} exception(s) were detected in the latest reconciliation run.', resource_type='RECONCILIATION_RUN', resource_id=report.get('run_id'), severity='WARNING')
    return 1
