from datetime import datetime, timezone
from app.main import app, Base, engine
from app.models import Payment, ReconciliationException
from fastapi.testclient import TestClient

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client=TestClient(app)

def reset():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)

def payment(pid='P900', amount='1000'):
    return {'provider_payment_id':pid,'amount':amount,'currency':'INR','status':'captured'}

def make_exception():
    client.post('/api/v1/import/payments', json={'source':'manual_demo','provider':'demo','records':[payment('P901')]})
    client.post('/api/v1/reconciliation/run')
    return client.get('/api/v1/exceptions?exception_code=PAYMENT_NOT_SETTLED').json()['items'][0]

def test_create_case_from_exception_and_duplicate_is_idempotent():
    reset(); exc=make_exception()
    first=client.post('/api/v1/cases',json={'exception_id':exc['id']})
    assert first.status_code==200 and first.json()['created'] is False
    assert first.json()['case_number'].startswith('RCAA-')
    second=client.post('/api/v1/cases',json={'exception_id':exc['id']})
    assert second.status_code==200 and second.json()['id']==first.json()['id']

def test_manual_case_number_unique_and_priority_independent():
    reset()
    a=client.post('/api/v1/cases',json={'title':'A','priority':'LOW'}).json()
    b=client.post('/api/v1/cases',json={'title':'B','priority':'CRITICAL'}).json()
    assert a['case_number'] != b['case_number'] and a['priority']=='LOW' and b['priority']=='CRITICAL'

def test_status_state_machine_and_resolution():
    reset(); case=client.post('/api/v1/cases',json={'title':'Investigate'}).json(); cid=case['id']
    assert client.post(f'/api/v1/cases/{cid}/start',json={'actor_reference':'ops-1'}).json()['status']=='IN_PROGRESS'
    assert client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'FALSE_POSITIVE','resolution_note':'Verified'}).json()['status']=='RESOLVED'
    assert client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'OTHER'}).status_code==400
    reopened=client.post(f'/api/v1/cases/{cid}/reopen',json={'actor_reference':'ops-2'})
    assert reopened.status_code==200 and reopened.json()['status']=='REOPENED' and reopened.json()['resolved_at'] is None
    assert reopened.json()['resolution_code']=='FALSE_POSITIVE'

def test_invalid_transitions_and_missing_resolution_rejected():
    reset(); case=client.post('/api/v1/cases',json={}).json(); cid=case['id']
    assert client.post(f'/api/v1/cases/{cid}/reopen',json={}).status_code==400
    assert client.post(f'/api/v1/cases/{cid}/resolve',json={}).status_code==400

def test_assignment_reassignment_and_unassigned():
    reset(); cid=client.post('/api/v1/cases',json={}).json()['id']
    assert client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':'ops-1'}).json()['assigned_to']=='ops-1'
    assert client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':'ops-2'}).json()['assigned_to']=='ops-2'
    assert client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':None}).json()['assigned_to'] is None
    assert client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':'   '}).status_code==400

def test_notes_are_append_only_and_ordered():
    reset(); cid=client.post('/api/v1/cases',json={}).json()['id']
    n1=client.post(f'/api/v1/cases/{cid}/notes',json={'author_reference':'a','note':'first'}).json()
    n2=client.post(f'/api/v1/cases/{cid}/notes',json={'author_reference':'b','note':'second'}).json()
    assert n1['id'] != n2['id']
    detail=client.get(f'/api/v1/cases/{cid}').json()
    assert [n['note'] for n in detail['notes']]==['first','second']

def test_attach_exception_and_duplicate_attachment():
    reset(); exc=make_exception(); cid=client.post('/api/v1/cases',json={}).json()['id']
    assert client.post(f'/api/v1/cases/{cid}/exceptions',json={'exception_id':exc['id']}).status_code==200
    assert client.post(f'/api/v1/cases/{cid}/exceptions',json={'exception_id':exc['id']}).status_code==400
    assert client.post(f'/api/v1/cases/{cid}/exceptions',json={'exception_id':'missing'}).status_code==400
    assert len(client.get(f'/api/v1/cases/{cid}').json()['exceptions'])==1

def test_case_detail_contains_evidence_and_timeline():
    reset(); exc=make_exception(); item=client.post('/api/v1/cases',json={'exception_id':exc['id']}).json()
    cid=item['id']
    client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':'ops'})
    client.post(f'/api/v1/cases/{cid}/notes',json={'note':'check bank file','author_reference':'ops'})
    client.post(f'/api/v1/cases/{cid}/start',json={'actor_reference':'ops'})
    client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'FALSE_POSITIVE','resolution_note':'Exception proven invalid after investigation'})
    detail=client.get(f'/api/v1/cases/{cid}').json()
    event_types=[x['event_type'] for x in detail['timeline']]
    assert 'CASE_CREATED' in event_types and 'CASE_ASSIGNED' in event_types and 'CASE_NOTE_ADDED' in event_types
    assert 'CASE_STATUS_CHANGED' in event_types and 'CASE_RESOLVED' in event_types
    assert detail['exceptions'] and detail['evidence']

def test_reopen_preserves_resolution_history_event():
    reset(); cid=client.post('/api/v1/cases',json={}).json()['id']
    client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'BANK_CORRECTION_REQUIRED','resolution_note':'Bank review'})
    client.post(f'/api/v1/cases/{cid}/reopen',json={})
    detail=client.get(f'/api/v1/cases/{cid}').json()
    resolved_events=[e for e in detail['timeline'] if e['event_type']=='CASE_RESOLVED']
    assert resolved_events[0]['metadata_json']['resolution_code']=='BANK_CORRECTION_REQUIRED'

def test_case_filtering_and_pagination():
    reset()
    for i in range(5): client.post('/api/v1/cases',json={'priority':'HIGH' if i<3 else 'LOW','merchant_id':f'M{i%2}','assigned_to':'ops' if i%2==0 else None})
    r=client.get('/api/v1/cases?priority=HIGH&page=1&limit=2'); assert r.status_code==200 and r.json()['total']==3 and len(r.json()['items'])==2
    assert client.get('/api/v1/cases?merchant=M1').json()['total']==2
    assert client.get('/api/v1/cases?assigned_to=ops').json()['total']==3

def test_exception_filter_and_case_creation_uses_exception_priority():
    reset(); exc=make_exception(); case=client.post('/api/v1/cases',json={'exception_id':exc['id']}).json()
    assert case['severity']==exc['severity'] and case['priority']==exc['severity']

def test_financial_immutability_after_case_operations():
    reset()
    client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P902','1250')]})
    before=client.get('/api/v1/payments').json()['items'][0]
    client.post('/api/v1/reconciliation/run'); exc=client.get('/api/v1/exceptions').json()['items'][0]
    cid=client.post('/api/v1/cases',json={'exception_id':exc['id']}).json()['id']
    client.post(f'/api/v1/cases/{cid}/assign',json={'assigned_to':'ops'})
    client.post(f'/api/v1/cases/{cid}/notes',json={'note':'investigate'})
    client.post(f'/api/v1/cases/{cid}/start',json={})
    client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'FALSE_POSITIVE'})
    after=client.get('/api/v1/payments').json()['items'][0]
    assert before['amount']==after['amount'] and before['status']==after['status']

def test_case_api_404s_and_legacy_case_api_still_works():
    reset(); assert client.get('/api/v1/cases/missing').status_code==404
    assert client.get('/api/v1/reconciliation/cases').status_code==200

def test_case_events_are_append_only_and_note_has_timestamp():
    reset(); cid=client.post('/api/v1/cases',json={}).json()['id']; client.post(f'/api/v1/cases/{cid}/notes',json={'note':'hello'})
    detail=client.get(f'/api/v1/cases/{cid}').json()
    assert all(e['created_at'] for e in detail['timeline']) and detail['notes'][0]['created_at']


def test_case_filters_cover_status_severity_and_exception_code():
    reset(); exc=make_exception(); linked=client.post('/api/v1/cases',json={'exception_id':exc['id']}).json();
    client.post(f"/api/v1/cases/{linked['id']}/start",json={})
    assert client.get('/api/v1/cases?status=IN_PROGRESS').json()['total']==1
    assert client.get(f"/api/v1/cases?severity={exc['severity']}").json()['total']>=1
    assert client.get(f"/api/v1/cases?exception_code={exc['exception_code']}").json()['total']==1

def test_created_date_filters():
    reset(); cid=client.post('/api/v1/cases',json={}).json()['id']; created=client.get(f'/api/v1/cases/{cid}').json()['created_at']
    assert client.get(f'/api/v1/cases?created_from={created}').json()['total']==1
    assert client.get(f'/api/v1/cases?created_to={created}').json()['total']==1

def test_financial_immutability_for_settlement_and_refund():
    reset()
    client.post('/api/v1/payments',json=payment('P903','1000'))
    client.post('/api/v1/refunds',json={'provider_refund_id':'R903','provider_payment_id':'P903','amount':'100','status':'processed','created_at':'2026-09-02T10:00:00Z'})
    client.post('/api/v1/settlements',json={'provider_settlement_id':'S903','provider_payment_id':'P903','gross_amount':'1000','fee':'10','tax':'0','net_amount':'990','status':'processed','settled_at':'2026-09-02T10:00:00Z'})
    before=client.get('/api/v1/settlements').json()['items'][0], client.get('/api/v1/refunds').json()['items'][0]
    client.post('/api/v1/reconciliation/run'); exc=client.get('/api/v1/exceptions').json()['items'][0]; cid=client.post('/api/v1/cases',json={'exception_id':exc['id']}).json()['id']
    client.post(f'/api/v1/cases/{cid}/notes',json={'note':'review'}); client.post(f'/api/v1/cases/{cid}/start',json={}); client.post(f'/api/v1/cases/{cid}/resolve',json={'resolution_code':'FALSE_POSITIVE'})
    after=client.get('/api/v1/settlements').json()['items'][0], client.get('/api/v1/refunds').json()['items'][0]
    assert before[0]['net_amount']==after[0]['net_amount'] and before[1]['amount']==after[1]['amount']

def test_repeated_exception_attachment_is_idempotently_rejected_without_duplicate_link():
    reset(); exc=make_exception(); cid=client.post('/api/v1/cases',json={}).json()['id']
    assert client.post(f'/api/v1/cases/{cid}/exceptions',json={'exception_id':exc['id']}).status_code==200
    assert client.post(f'/api/v1/cases/{cid}/exceptions',json={'exception_id':exc['id']}).status_code==400
    assert len(client.get(f'/api/v1/cases/{cid}').json()['exceptions'])==1
