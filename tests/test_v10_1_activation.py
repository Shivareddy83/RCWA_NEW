import os, sys
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///./test_rcaa_v10_1.db'
os.environ['AUTH_SECRET']='x'*40
os.environ['RAZORPAY_WEBHOOK_SECRET']='test_secret'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app, Base, engine
Base.metadata.drop_all(engine); Base.metadata.create_all(engine); client=TestClient(app)

def test_activation_requires_auth_and_signup_has_activation_state(monkeypatch):
    monkeypatch.delenv('RCAA_LEGACY_TEST_AUTH', raising=False)
    assert client.get('/api/v1/product/activation').status_code == 401
    r=client.post('/api/v1/public/signup',json={'company_name':'Activation Co','name':'Owner Name','email':'activation@demo.example','password':'strong-password-123'})
    assert r.status_code==201
    token=r.json()['access_token']
    a=client.get('/api/v1/product/activation',headers={'Authorization':f'Bearer {token}'})
    assert a.status_code==200
    body=a.json(); assert body['plan_code']=='TRIAL'; assert body['activation_score']==0
    assert {x['key'] for x in body['steps']}=={'onboarding','data','reconciliation','plan'}

def test_admin_can_move_demo_lead_through_sales_status():
    r=client.post('/api/v1/public/demo-request',json={'name':'Lead','company_name':'Sales Co','email':'sales@demo.example'})
    assert r.status_code==202; lead_id=r.json()['lead_id']
    token=client.post('/api/v1/auth/login',json={'email':'activation@demo.example','password':'strong-password-123'}).json()['access_token']
    h={'Authorization':f'Bearer {token}'}
    r=client.patch(f'/api/v1/product/demo-leads/{lead_id}',headers=h,json={'status':'QUALIFIED'})
    assert r.status_code==200 and r.json()['status']=='QUALIFIED'
    r=client.get('/api/v1/public/demo-requests',headers=h)
    assert r.json()['items'][0]['status']=='QUALIFIED'

def test_invalid_demo_lead_status_is_rejected():
    token=client.post('/api/v1/auth/login',json={'email':'activation@demo.example','password':'strong-password-123'}).json()['access_token']
    h={'Authorization':f'Bearer {token}'}
    lead=client.get('/api/v1/public/demo-requests',headers=h).json()['items'][0]['id']
    assert client.patch(f'/api/v1/product/demo-leads/{lead}',headers=h,json={'status':'SPAM'}).status_code==422
