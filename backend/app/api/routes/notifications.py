from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import NOTIFICATION_READ, NOTIFICATION_PREFERENCES_UPDATED
from app.models import Notification, NotificationPreference
from app.security import get_current_user, require_roles
from app.core.time import utc_now

router=APIRouter(prefix='/notifications', tags=['notifications'], dependencies=[Depends(get_current_user)])

class PreferencePayload(BaseModel):
    enable_exceptions: bool=True
    enable_cases: bool=True
    enable_reports: bool=True

@router.get('')
def list_notifications(unread_only:bool=False, limit:int=50, session:Session=Depends(get_db), user=Depends(get_current_user)):
    limit=max(1,min(limit,100))
    q=select(Notification).where(Notification.merchant_id==user.merchant_id, (Notification.user_id==user.id) | (Notification.user_id.is_(None))).order_by(Notification.created_at.desc()).limit(limit)
    if unread_only: q=q.where(Notification.read_at.is_(None))
    items=session.scalars(q).all()
    unread=session.scalar(select(func.count(Notification.id)).where(Notification.merchant_id==user.merchant_id, (Notification.user_id==user.id) | (Notification.user_id.is_(None)), Notification.read_at.is_(None))) or 0
    return {'items':[{'id':x.id,'kind':x.kind,'severity':x.severity,'title':x.title,'message':x.message,'resource_type':x.resource_type,'resource_id':x.resource_id,'read_at':x.read_at,'created_at':x.created_at} for x in items],'unread_count':unread}

@router.get('/preferences/current')
def preferences(session:Session=Depends(get_db),user=Depends(get_current_user)):
    p=session.scalar(select(NotificationPreference).where(NotificationPreference.merchant_id==user.merchant_id))
    if not p: return {'enable_exceptions':True,'enable_cases':True,'enable_reports':True}
    return {'enable_exceptions':p.enable_exceptions,'enable_cases':p.enable_cases,'enable_reports':p.enable_reports}

@router.put('/preferences',dependencies=[Depends(require_roles('ADMIN'))])
def update_preferences(payload:PreferencePayload,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    p=session.scalar(select(NotificationPreference).where(NotificationPreference.merchant_id==user.merchant_id))
    if not p:
        p=NotificationPreference(merchant_id=user.merchant_id); session.add(p)
    p.enable_exceptions=payload.enable_exceptions;p.enable_cases=payload.enable_cases;p.enable_reports=payload.enable_reports
    record_event(session,action=NOTIFICATION_PREFERENCES_UPDATED,resource_type='NOTIFICATION_PREFERENCES',resource_id=user.merchant_id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),after_snapshot=payload.model_dump())
    session.commit(); return payload.model_dump()

@router.post('/{notification_id}/read')
def read_notification(notification_id:str,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    n=session.scalar(select(Notification).where(Notification.id==notification_id,Notification.merchant_id==user.merchant_id,(Notification.user_id==user.id)|(Notification.user_id.is_(None))))
    if not n: raise HTTPException(404,'Notification not found')
    if n.read_at is None:
        n.read_at=utc_now()
        record_event(session,action=NOTIFICATION_READ,resource_type='NOTIFICATION',resource_id=n.id,merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None))
        session.commit()
    return {'id':n.id,'read_at':n.read_at}

