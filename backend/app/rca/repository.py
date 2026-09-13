from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import RCA

def get_by_case(session: Session, case_id: str):
    return session.scalar(select(RCA).where(RCA.reconciliation_case_id == case_id))
