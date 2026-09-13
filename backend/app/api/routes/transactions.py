from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models import Payment, Refund, Settlement
from app.schemas.inputs import PaymentIn, RefundIn, SettlementIn
from app.services.serialization import dump
from app.services.transactions import create_payment, create_refund, create_settlement, get_or_404, import_payments
from app.ingestion import ingest_records, IngestionValidationError
from app.ingestion_schemas import ImportEnvelope
from app.repositories.payments import list_payments
from app.security import get_current_user, require_roles
from app.security.tenant import test_admin_bypass
from app.core.config import settings
from app.audit import record_event
from app.audit.actions import PAYMENT_CREATED, PAYMENT_IMPORTED, REFUND_IMPORTED, SETTLEMENT_IMPORTED

router=APIRouter(dependencies=[Depends(get_current_user)])

def _data(v,user):
    d=v.model_dump()
    if not (test_admin_bypass(user)): d['merchant_id']=user.merchant_id
    return d

def _one(session,model,rid,user):
    if (test_admin_bypass(user)): return session.get(model,rid)
    return session.scalar(select(model).where(model.id==rid,model.merchant_id==user.merchant_id))

@router.post('/payments',status_code=201,dependencies=[Depends(require_roles('ADMIN','OPS'))])
def add_payment(v:PaymentIn,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    value=create_payment(session,_data(v,user), commit=False)
    record_event(session, action=PAYMENT_CREATED, resource_type='PAYMENT', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'provider':value.provider,'provider_payment_id':value.provider_payment_id})
    session.commit(); return dump(value)
@router.post('/payments/import',dependencies=[Depends(require_roles('ADMIN','OPS'))])
def import_payment_records(items:list[PaymentIn],session:Session=Depends(get_db),user=Depends(get_current_user)): return {'created':import_payments(session,[_data(item,user) for item in items], commit=False)}
@router.get('/payments')
def payments(limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0),session:Session=Depends(get_db),user=Depends(get_current_user)):
    q=select(Payment).order_by(Payment.created_at.desc()).offset(offset).limit(limit) if (test_admin_bypass(user)) else select(Payment).where(Payment.merchant_id==user.merchant_id).order_by(Payment.created_at.desc()).offset(offset).limit(limit)
    return {'items':dump(session.scalars(q).all())}
@router.get('/payments/{payment_id}')
def payment(payment_id:str,session:Session=Depends(get_db),user=Depends(get_current_user)):
    v=_one(session,Payment,payment_id,user)
    if not v: from app.core.errors import NotFoundError; raise NotFoundError('Payment not found')
    return dump(v)
@router.post('/refunds',status_code=201,dependencies=[Depends(require_roles('ADMIN','OPS'))])
def add_refund(v:RefundIn,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    value=create_refund(session,_data(v,user), commit=False)
    record_event(session, action=REFUND_IMPORTED, resource_type='REFUND', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'provider':value.provider,'provider_refund_id':value.provider_refund_id})
    session.commit(); return dump(value)
@router.get('/refunds')
def refunds(page:int=Query(1,ge=1), limit:int=Query(50,ge=1,le=200), session:Session=Depends(get_db),user=Depends(get_current_user)):
    q=select(Refund) if (test_admin_bypass(user)) else select(Refund).where(Refund.merchant_id==user.merchant_id)
    q=q.order_by(Refund.created_at.desc()).offset((page-1)*limit).limit(limit)
    return {'items':dump(session.scalars(q).all()),'page':page,'limit':limit}
@router.get('/refunds/{refund_id}')
def refund(refund_id:str,session:Session=Depends(get_db),user=Depends(get_current_user)):
    v=_one(session,Refund,refund_id,user) if (test_admin_bypass(user)) else session.scalar(select(Refund).where(Refund.id==refund_id,Refund.merchant_id==user.merchant_id))
    if not v: from app.core.errors import NotFoundError; raise NotFoundError('Refund not found')
    return dump(v)
@router.post('/settlements',status_code=201,dependencies=[Depends(require_roles('ADMIN','OPS'))])
def add_settlement(v:SettlementIn,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)):
    value=create_settlement(session,_data(v,user), commit=False)
    record_event(session, action=SETTLEMENT_IMPORTED, resource_type='SETTLEMENT', resource_id=value.id, merchant_id=value.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'provider':value.provider,'provider_settlement_id':value.provider_settlement_id})
    session.commit(); return dump(value)
@router.get('/settlements')
def settlements(page:int=Query(1,ge=1), limit:int=Query(50,ge=1,le=200), session:Session=Depends(get_db),user=Depends(get_current_user)):
    q=select(Settlement) if (test_admin_bypass(user)) else select(Settlement).where(Settlement.merchant_id==user.merchant_id)
    q=q.order_by(Settlement.settled_at.desc()).offset((page-1)*limit).limit(limit)
    return {'items':dump(session.scalars(q).all()),'page':page,'limit':limit}
@router.get('/settlements/{settlement_id}')
def settlement(settlement_id:str,session:Session=Depends(get_db),user=Depends(get_current_user)):
    v=_one(session,Settlement,settlement_id,user) if (test_admin_bypass(user)) else session.scalar(select(Settlement).where(Settlement.id==settlement_id,Settlement.merchant_id==user.merchant_id))
    if not v: from app.core.errors import NotFoundError; raise NotFoundError('Settlement not found')
    return dump(v)

def _import(v,record_type,session,user,request):
    records=[]
    for r in v.records:
        r=dict(r)
        if not (test_admin_bypass(user)): r['merchant_id']=user.merchant_id
        records.append(r)
    try:
        result=ingest_records(session,records,source=v.source,provider=v.provider,record_type=record_type,merchant_id=None if (test_admin_bypass(user)) else user.merchant_id, commit=False)
        action={'payment':PAYMENT_IMPORTED,'refund':REFUND_IMPORTED,'settlement':SETTLEMENT_IMPORTED}[record_type]
        record_event(session, action=action, resource_type=f'{record_type.upper()}_IMPORT', merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,'request_id',None), ip_address=request.client.host if request.client else None, metadata={'source':v.source,'provider':v.provider,'received_count':result.get('received',len(records)),'created_count':result.get('created',0),'duplicate_count':result.get('duplicates',0)})
        session.commit()
        return result
    except IngestionValidationError as exc:
        from fastapi import HTTPException; raise HTTPException(422,str(exc)) from exc
@router.post('/import/payments',dependencies=[Depends(require_roles('ADMIN','OPS'))])
def import_payments_v2(v:ImportEnvelope,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)): return _import(v,'payment',session,user,request)
@router.post('/import/refunds',dependencies=[Depends(require_roles('ADMIN','OPS'))])
def import_refunds_v2(v:ImportEnvelope,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)): return _import(v,'refund',session,user,request)
@router.post('/import/settlements',dependencies=[Depends(require_roles('ADMIN','OPS'))])
def import_settlements_v2(v:ImportEnvelope,request:Request,session:Session=Depends(get_db),user=Depends(get_current_user)): return _import(v,'settlement',session,user,request)
