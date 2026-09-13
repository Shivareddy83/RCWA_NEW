from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Evidence

def list_case_evidence(session: Session, case_id: str):
    return session.scalars(select(Evidence).where(Evidence.reconciliation_case_id == case_id).order_by(Evidence.captured_at, Evidence.id)).all()
