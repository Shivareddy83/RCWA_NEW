from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Case

def get_case(session: Session, case_id: str):
    return session.get(Case, case_id)

def get_case_by_fingerprint(session: Session, fingerprint: str):
    return session.scalar(select(Case).where(Case.fingerprint == fingerprint))

def list_cases(session: Session, status=None):
    query = select(Case).order_by(Case.created_at.desc())
    if status:
        query = query.where(Case.status == status)
    return session.scalars(query).all()
