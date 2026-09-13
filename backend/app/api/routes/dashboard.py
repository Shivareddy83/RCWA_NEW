from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.services.dashboard import dashboard_summary
from app.security import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.get("/dashboard/summary")
def summary(session: Session = Depends(get_db), user=Depends(get_current_user)):
    return dashboard_summary(session, user.merchant_id)
