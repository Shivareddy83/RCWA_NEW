import os, sys
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///./test_rcaa_v10.db'
os.environ['AUTH_SECRET']='x'*40
os.environ['RAZORPAY_WEBHOOK_SECRET']='test_secret'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app, Base, engine

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
client=TestClient(app)

def test_public_plans_are_customer_ready():
    r=client.get('/api/v1/public/plans')
    assert r.status_code==200
    assert [x['code'] for x in r.json()['plans']]==['TRIAL','STARTER','GROWTH','BUSINESS']

def test_self_service_signup_creates_workspace_trial_and_token():
    r=client.post('/api/v1/public/signup',json={'company_name':'Acme Commerce','name':'Owner Name','email':'owner@acme.example','password':'strong-password-123'})
    assert r.status_code==201, r.text
    body=r.json()
    assert body['access_token']
    assert body['user']['role']=='ADMIN'
    assert body['subscription']['plan_code']=='TRIAL'
    assert body['workspace']['name']=='Acme Commerce'

def test_duplicate_public_signup_is_rejected():
    r=client.post('/api/v1/public/signup',json={'company_name':'Another','name':'Owner','email':'owner@acme.example','password':'strong-password-123'})
    assert r.status_code==409

def test_demo_request_is_persisted_and_admin_can_read_it():
    r=client.post('/api/v1/public/demo-request',json={'name':'Finance Lead','company_name':'Demo Co','email':'lead@demo.example','monthly_transactions':'500k-2M','message':'Settlement mismatch investigation'})
    assert r.status_code==202
    token=client.post('/api/v1/auth/login',json={'email':'owner@acme.example','password':'strong-password-123'}).json()['access_token']
    r=client.get('/api/v1/public/demo-requests',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==200
    assert r.json()['items'][0]['email']=='lead@demo.example'
