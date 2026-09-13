import os,sys,hmac,hashlib
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///./test_rcaa.db'; os.environ['RAZORPAY_WEBHOOK_SECRET']='test_secret'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app,Base,engine
Base.metadata.drop_all(engine);Base.metadata.create_all(engine);client=TestClient(app)
def p(pid='p1',amount='1000',**x):return {'provider_payment_id':pid,'amount':amount,**x}
def test_payment_and_summary():
 r=client.post('/api/v1/payments',json=p());assert r.status_code==201
 assert client.get('/api/v1/dashboard/summary').json()['total_payments']==1
def test_fee_tax_is_reconciled():
 client.post('/api/v1/payments',json=p('fee')); client.post('/api/v1/settlements',json={'provider_settlement_id':'sfee','provider_payment_id':'fee','gross_amount':'1000','fee':'80','tax':'20','net_amount':'900','status':'processed','settled_at':'2025-01-02T00:00:00Z'})
 assert client.post('/api/v1/reconciliation/run').status_code==200
 assert all(x['case_type']!='SETTLEMENT_MISMATCH' or x['payment_id'] is None for x in client.get('/api/v1/reconciliation/cases').json()['items'])
def test_missing_refund_and_webhook_idempotency():
 client.post('/api/v1/payments',json=p('refund',raw_data={'expected_refund':True})); client.post('/api/v1/reconciliation/run')
 assert any(x['case_type']=='MISSING_REFUND' for x in client.get('/api/v1/reconciliation/cases').json()['items'])
 body=b'{"event":"payment.captured","event_id":"evt1"}';sig=hmac.new(b'test_secret',body,hashlib.sha256).hexdigest()
 assert client.post('/api/v1/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':sig}).status_code==200
 assert client.post('/api/v1/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':sig}).json()['status']=='duplicate'
 assert client.post('/api/v1/webhooks/razorpay',content=body,headers={'X-Razorpay-Signature':'bad'}).status_code==401

def test_health_and_request_id():
 r=client.get('/health',headers={'X-Request-ID':'stage01-test'})
 assert r.status_code==200
 assert r.json()=={'status':'ok','service':'rcaa'}
 assert r.headers['X-Request-ID']=='stage01-test'


def test_not_found_uses_consistent_error_shape():
 r=client.get('/api/v1/payments/does-not-exist')
 assert r.status_code==404
 assert r.json()=={'detail':'Payment not found'}
