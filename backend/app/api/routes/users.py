from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models import User
from app.security import get_current_user, require_roles, hash_password
from app.audit import record_event
from app.audit.actions import USER_CREATED, USER_UPDATED, USER_DISABLED, USER_ROLE_CHANGED

router=APIRouter(prefix='/users', tags=['users'], dependencies=[Depends(get_current_user)])
class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(min_length=10, max_length=128)
    role: str
class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None

def _view(u): return {"id":u.id,"email":u.email,"merchant_id":u.merchant_id,"role":u.role,"is_active":u.is_active,"created_at":u.created_at,"updated_at":u.updated_at}

def _last_admin_guard(session,user,new_role=None,new_active=None):
    will_admin = (new_role or user.role) == 'ADMIN' and (new_active if new_active is not None else user.is_active)
    if not will_admin:
        count=session.scalar(select(func.count(User.id)).where(User.merchant_id==user.merchant_id,User.role=='ADMIN',User.is_active.is_(True))) or 0
        if user.role=='ADMIN' and user.is_active and count <= 1: raise HTTPException(400,'Merchant must retain an active ADMIN')

@router.post('', dependencies=[Depends(require_roles('ADMIN'))], status_code=201)
def create_user(payload:CreateUserRequest,request:Request,session:Session=Depends(get_db),current=Depends(get_current_user)):
    role=payload.role.upper()
    if role not in {'ADMIN','OPS','ANALYST','VIEWER'}: raise HTTPException(422,'Invalid role')
    if session.scalar(select(User).where(User.email==payload.email.lower().strip())): raise HTTPException(409,'User already exists')
    u=User(email=payload.email.lower().strip(),password_hash=hash_password(payload.password),merchant_id=current.merchant_id,role=role,is_active=True)
    session.add(u); session.flush()
    record_event(session, action=USER_CREATED, resource_type='USER', resource_id=u.id, merchant_id=current.merchant_id, actor_user_id=current.id, actor_role=current.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'email':u.email,'role':u.role,'is_active':u.is_active})
    session.commit();session.refresh(u);return _view(u)

@router.get('')
def list_users(session:Session=Depends(get_db),current=Depends(get_current_user)):
    return {'items':[_view(u) for u in session.scalars(select(User).where(User.merchant_id==current.merchant_id).order_by(User.created_at)).all()]}

@router.patch('/{user_id}', dependencies=[Depends(require_roles('ADMIN'))])
def update_user(user_id:str,payload:UpdateUserRequest,request:Request,session:Session=Depends(get_db),current=Depends(get_current_user)):
    u=session.scalar(select(User).where(User.id==user_id,User.merchant_id==current.merchant_id))
    if not u: raise HTTPException(404,'User not found')
    before={'role':u.role,'is_active':u.is_active,'email':u.email,'merchant_id':u.merchant_id}
    role_changed=False; disabled=False
    if payload.role is not None:
        role=payload.role.upper()
        if role not in {'ADMIN','OPS','ANALYST','VIEWER'}: raise HTTPException(422,'Invalid role')
        if u.id==current.id and role!='ADMIN': raise HTTPException(400,'Admin cannot demote themselves')
        _last_admin_guard(session,u,new_role=role)
        role_changed = role != u.role
        u.role=role
    if payload.is_active is not None:
        if u.id==current.id and not payload.is_active: raise HTTPException(400,'Admin cannot disable themselves')
        _last_admin_guard(session,u,new_active=payload.is_active)
        disabled = u.is_active and not payload.is_active
        u.is_active=payload.is_active
    u.updated_at = __import__('app.core.time', fromlist=['utc_now']).utc_now()
    session.flush()
    after={'role':u.role,'is_active':u.is_active,'email':u.email,'merchant_id':u.merchant_id}
    if role_changed:
        record_event(session, action=USER_ROLE_CHANGED, resource_type='USER', resource_id=u.id, merchant_id=current.merchant_id, actor_user_id=current.id, actor_role=current.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, before_snapshot={'role':before['role']}, after_snapshot={'role':after['role']})
    if disabled:
        record_event(session, action=USER_DISABLED, resource_type='USER', resource_id=u.id, merchant_id=current.merchant_id, actor_user_id=current.id, actor_role=current.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, before_snapshot={'is_active':before['is_active']}, after_snapshot={'is_active':after['is_active']})
    if role_changed or payload.is_active is not None:
        record_event(session, action=USER_UPDATED, resource_type='USER', resource_id=u.id, merchant_id=current.merchant_id, actor_user_id=current.id, actor_role=current.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, before_snapshot=before, after_snapshot=after)
    session.commit();session.refresh(u);return _view(u)
