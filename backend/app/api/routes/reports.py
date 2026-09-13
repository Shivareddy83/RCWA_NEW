from __future__ import annotations
import csv, io
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import REPORT_GENERATED
from app.security import get_current_user
from app.services.reports import build_summary, exception_rows, case_rows

router=APIRouter(prefix='/reports', tags=['reports'], dependencies=[Depends(get_current_user)])

def _date(v):
    return v.isoformat() if v else None

@router.get('/summary')
def summary(start: datetime|None=None, end: datetime|None=None, session:Session=Depends(get_db), user=Depends(get_current_user)):
    return build_summary(session,user.merchant_id,start,end)

def _csv_response(filename, headers, rows):
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(headers)
    for row in rows: writer.writerow(row)
    return StreamingResponse(iter([out.getvalue()]), media_type='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@router.get('/exceptions.csv')
def exceptions_csv(request:Request, start:datetime|None=None, end:datetime|None=None, session:Session=Depends(get_db), user=Depends(get_current_user)):
    items=exception_rows(session,user.merchant_id,start,end)
    record_event(session,action=REPORT_GENERATED,resource_type='REPORT',resource_id='exceptions',merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),metadata={'report':'exceptions','rows':len(items)})
    session.commit()
    return _csv_response('rcaa-exceptions.csv',['exception_id','code','severity','status','source','expected_amount','actual_amount','difference','created_at'],[[x.id,x.exception_code,x.severity,x.status,x.source,x.expected_amount,x.actual_amount,x.difference,_date(x.created_at)] for x in items])

@router.get('/cases.csv')
def cases_csv(request:Request,start:datetime|None=None,end:datetime|None=None,session:Session=Depends(get_db),user=Depends(get_current_user)):
    items=case_rows(session,user.merchant_id,start,end)
    record_event(session,action=REPORT_GENERATED,resource_type='REPORT',resource_id='cases',merchant_id=user.merchant_id,actor_user_id=user.id,actor_role=user.role,request_id=getattr(request.state,'request_id',None),metadata={'report':'cases','rows':len(items)})
    session.commit()
    return _csv_response('rcaa-cases.csv',['case_id','case_number','status','priority','severity','title','expected_amount','actual_amount','difference','resolution_code','created_at','updated_at'],[[x.id,x.case_number,x.status,x.priority,x.severity,x.title,x.expected_amount,x.actual_amount,x.difference,x.resolution_code,_date(x.created_at),_date(x.updated_at)] for x in items])
