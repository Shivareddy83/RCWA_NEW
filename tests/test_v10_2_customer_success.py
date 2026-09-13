import os, sys
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///./test_rcaa_v10_2.db'
os.environ['AUTH_SECRET']='x'*40
os.environ['RAZORPAY_WEBHOOK_SECRET']='test_secret'
os.environ['RCAA_LEGACY_TEST_AUTH']='1'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant, User
from app.security import hash_password
Base.metadata.drop_all(engine); Base.metadata.create_all(engine); client=TestClient(app)

def signup(email, company='Health Co'):
    r=client.post('/api/v1/public/signup',json={'company_name':company,'name':'Owner Name','email':email,'password':'strong-password-123'})
    assert r.status_code==201, r.text
    return r.json()['access_token']

def test_workspace_health():
    token=signup('health@example.com')
    r=client.get('/api/v1/product/workspace-health',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==200
    assert {'health','health_score','next_action','uploads','open_cases'} <= set(r.json())

def test_customer_portfolio_admin():
    token=signup('admin@example.com','Admin Co')
    r=client.get('/api/v1/product/customer-portfolio',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==200
    assert {'items','summary'} <= set(r.json())
    assert {'customers','active_customers','trial_customers','mrr'} <= set(r.json()['summary'])

def test_customer_portfolio_forbidden_for_non_admin():
    token=signup('member@example.com','Member Co')
    with SessionLocal() as db:
        u=db.query(User).filter(User.email=='member@example.com').one()
        u.role='ANALYST'; db.commit()
    token=client.post('/api/v1/auth/login',json={'email':'member@example.com','password':'strong-password-123'}).json()['access_token']
    r=client.get('/api/v1/product/customer-portfolio',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==403
