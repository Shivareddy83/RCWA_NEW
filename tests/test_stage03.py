import os, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal
os.environ['DATABASE_URL']='sqlite:///./stage03_test.db'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.models import Payment, Refund, Settlement, BankTransaction, IngestionBatch, ReconciliationException
from app.ingestion import ingest_records, IngestionValidationError
from app.reconciliation.engine import run_reconciliation
from app.exceptions.engine import generate_exceptions

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client=TestClient(app)

def payment(pid, amount='1000', **kw):
    return {'provider_payment_id':pid,'amount':amount,'currency':'INR','status':'captured',**kw}

def reset():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)

def test_valid_payment_import_and_idempotency():
    reset(); payload={'source':'razorpay_api','provider':'razorpay','records':[payment('P100')|{'external_id':'P100'}]}
    r=client.post('/api/v1/import/payments',json=payload); assert r.status_code==200 and r.json()['created']==1
    r=client.post('/api/v1/import/payments',json=payload); assert r.json()['duplicates']==1 and r.json()['created']==0

def test_refund_import_and_provenance():
    reset(); client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P101')]})
    r=client.post('/api/v1/import/refunds',json={'source':'razorpay_api','provider':'razorpay','records':[{'external_id':'R101','provider_payment_id':'P101','amount':'100','currency':'INR','status':'processed'}]})
    assert r.json()['created']==1
    with engine.connect() as c: assert c.execute(__import__('sqlalchemy').text("select source from refunds where external_id='R101'")).scalar()=='razorpay_api'

def test_settlement_import():
    reset(); client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P102')]})
    r=client.post('/api/v1/import/settlements',json={'source':'bank_csv','provider':'demo','records':[{'external_id':'S102','provider_payment_id':'P102','gross_amount':'1000','fee':'10','tax':'2','net_amount':'988','currency':'INR','status':'processed','settled_at':'2026-09-02T10:00:00Z'}]})
    assert r.json()['created']==1
    assert client.get('/api/v1/ingestion/batches').status_code==200

def test_bank_csv_valid_duplicate_and_provenance():
    reset(); csv=b'external_id,reference,amount,currency,status,event_timestamp\nB1,P200,1000,INR,posted,2026-09-02T10:00:00Z\n'
    r=client.post('/api/v1/import/bank-transactions',files={'file':('bank.csv',csv,'text/csv')}); assert r.status_code==200 and r.json()['created']==1
    r=client.post('/api/v1/import/bank-transactions',files={'file':('bank.csv',csv,'text/csv')}); assert r.json()['duplicates']==1
    assert client.get('/api/v1/ingestion/batches').json()['items'][0]['status']=='COMPLETED'

def test_bank_csv_malformed_is_rejected_without_partial_data():
    reset(); csv=b'external_id,reference,amount,currency,status,event_timestamp\nB1,P200,1000,INR,posted,2026-09-02T10:00:00Z\nB2,P201,nope,INR,posted,2026-09-02T10:00:00Z\n'
    r=client.post('/api/v1/import/bank-transactions',files={'file':('bad.csv',csv,'text/csv')}); assert r.status_code==422 and 'row 3' in r.text
    assert client.get('/api/v1/dashboard/summary').json()['total_payments']==0
    assert client.get('/api/v1/ingestion/batches').json()['items'][0]['status']=='REJECTED'

def test_missing_column_invalid_currency_and_timestamp():
    reset(); assert client.post('/api/v1/import/bank-transactions',files={'file':('x.csv',b'external_id,amount\nB1,10\n','text/csv')}).status_code==422
    assert client.post('/api/v1/import/bank-transactions',files={'file':('x.csv',b'external_id,amount,currency,event_timestamp\nB1,10,ZZZ,2026-09-02T10:00:00Z\n','text/csv')}).status_code==422
    assert client.post('/api/v1/import/bank-transactions',files={'file':('x.csv',b'external_id,amount,currency,event_timestamp\nB1,10,INR,nope\n','text/csv')}).status_code==422

def test_invalid_amount_rejected():
    reset(); r=client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P300',amount='-1')]}); assert r.status_code==422

def test_reconciliation_generates_exception_and_is_idempotent():
    reset(); client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P400','1000')]})
    first=client.post('/api/v1/reconciliation/run').json(); assert first['exceptions']['created']>=1
    second=client.post('/api/v1/reconciliation/run').json(); assert second['exceptions']['created']==0
    items=client.get('/api/v1/exceptions?exception_code=PAYMENT_NOT_SETTLED').json()['items']; assert items
    detail=client.get('/api/v1/exceptions/'+items[0]['id']); assert detail.status_code==200 and detail.json()['evidence_json']['record_id']

def test_amount_mismatch_exception():
    reset(); client.post('/api/v1/payments',json=payment('P401','1000')); client.post('/api/v1/settlements',json={'provider_settlement_id':'S401','provider_payment_id':'P401','gross_amount':'900','fee':'0','tax':'0','net_amount':'900','status':'processed','settled_at':'2026-09-02T10:00:00Z'})
    client.post('/api/v1/reconciliation/run'); assert client.get('/api/v1/exceptions?exception_code=AMOUNT_MISMATCH').json()['items']

def test_status_currency_and_delayed_exceptions():
    reset(); client.post('/api/v1/payments',json=payment('P402','1000',status='failed'));
    # Keep the test deterministic: make the payment four days before the settlement.
    with engine.begin() as conn:
        conn.execute(__import__('sqlalchemy').text("update payments set created_at='2026-09-01T10:00:00' where provider_payment_id='P402'"))
    client.post('/api/v1/settlements',json={'provider_settlement_id':'S402','provider_payment_id':'P402','gross_amount':'1000','net_amount':'1000','fee':'0','tax':'0','currency':'INR','status':'processed','settled_at':'2026-09-10T10:00:00Z'})
    client.post('/api/v1/reconciliation/run'); codes={x['exception_code'] for x in client.get('/api/v1/exceptions').json()['items']}; assert 'STATUS_MISMATCH' in codes and 'DELAYED_SETTLEMENT' in codes

def test_duplicate_settlement_exception():
    reset(); client.post('/api/v1/payments',json=payment('P403','1000')); base={'provider_payment_id':'P403','gross_amount':'1000','net_amount':'1000','fee':'0','tax':'0','status':'processed','settled_at':'2026-09-02T10:00:00Z'}
    client.post('/api/v1/settlements',json={'provider_settlement_id':'S403A',**base}); client.post('/api/v1/settlements',json={'provider_settlement_id':'S403B',**base}); client.post('/api/v1/reconciliation/run')
    assert client.get('/api/v1/exceptions?exception_code=DUPLICATE_SETTLEMENT').json()['items']

def test_duplicate_refund_exception():
    reset(); client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P404','1000')]})
    payload={'source':'razorpay_api','provider':'demo','records':[{'external_id':'R404','provider_payment_id':'P404','amount':'100','status':'processed','currency':'INR'}]}
    assert client.post('/api/v1/import/refunds',json=payload).json()['created']==1
    assert client.post('/api/v1/import/refunds',json=payload).json()['duplicates']==1
    client.post('/api/v1/reconciliation/run')
    assert client.get('/api/v1/exceptions?exception_code=DUPLICATE_REFUND').json()['items']

def test_ambiguous_match_exception():
    reset(); client.post('/api/v1/payments',json=payment('P405','1000',provider_order_id='NO_MATCH')); base={'provider_payment_id':'OTHER','gross_amount':'1000','net_amount':'1000','fee':'0','tax':'0','status':'processed','settled_at':datetime.now(timezone.utc).isoformat()}
    client.post('/api/v1/settlements',json={'provider_settlement_id':'S405A',**base}); client.post('/api/v1/settlements',json={'provider_settlement_id':'S405B',**base}); client.post('/api/v1/reconciliation/run')
    assert client.get('/api/v1/exceptions?exception_code=AMBIGUOUS_MATCH').json()['items']

def test_exception_severity_is_deterministic():
    reset(); client.post('/api/v1/payments',json=payment('P406','1000')); client.post('/api/v1/reconciliation/run'); item=client.get('/api/v1/exceptions?exception_code=PAYMENT_NOT_SETTLED').json()['items'][0]; assert item['severity']=='CRITICAL'

def test_signed_bank_transaction_allowed():
    reset(); csv=b'external_id,reference,amount,currency,event_timestamp\nBNEG,REF,-25.00,INR,2026-09-02T10:00:00Z\n'; r=client.post('/api/v1/import/bank-transactions',files={'file':('bank.csv',csv,'text/csv')}); assert r.status_code==200

def test_import_transaction_rolls_back_all_records_on_validation_failure():
    reset(); r=client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[payment('P407'),payment('P408',amount='bad')]}); assert r.status_code==422
    assert client.get('/api/v1/dashboard/summary').json()['total_payments']==0

def test_provider_normalization_boundary():
    from app.providers.razorpay import RazorpayProvider
    p=RazorpayProvider('k','s','w').normalize_payment({'id':'pay_x','order_id':'ord_x','amount':12345,'currency':'INR','status':'captured'})
    assert p['provider']=='razorpay' and p['amount']=='123.45'


def test_webhook_normalizes_payment_and_preserves_event_idempotency():
    reset()
    import hmac, hashlib, json
    body=json.dumps({"event":"payment.captured","event_id":"evt-p1","payload":{"payment":{"entity":{"id":"pay_web_1","order_id":"ord_web_1","amount":50000,"currency":"INR","status":"captured","captured":1}}}}).encode()
    sig=hmac.new(b'test_secret',body,hashlib.sha256).hexdigest()
    r=client.post('/api/v1/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':sig}); assert r.status_code==200
    assert client.get('/api/v1/payments').json()['items'][0]['source']=='razorpay_webhook'
    assert client.post('/api/v1/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':sig}).json()['status']=='duplicate'

def test_exception_minimal_lifecycle():
    reset(); client.post('/api/v1/payments',json=payment('P500')); client.post('/api/v1/reconciliation/run')
    item=client.get('/api/v1/exceptions').json()['items'][0]
    assert client.post(f"/api/v1/exceptions/{item['id']}/acknowledge").json()['status']=='ACKNOWLEDGED'
    assert client.post(f"/api/v1/exceptions/{item['id']}/resolve").json()['status']=='RESOLVED'
