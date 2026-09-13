import os, sys
from pathlib import Path
from decimal import Decimal
os.environ['DATABASE_URL']='sqlite:///./test_stage07.db'
os.environ['TESTING']='1'
os.environ['AUTH_SECRET']='stage07-test-secret-please-change'
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant, User, Payment, Case
from app.security import hash_password, create_access_token

Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
client=TestClient(app)

def reset():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)

def seed():
    s=SessionLocal(); a=Merchant(id='m-a',name='Merchant A',email='a@example.local'); b=Merchant(id='m-b',name='Merchant B',email='b@example.local'); s.add_all([a,b]);
    s.add_all([
      User(id='u-admin-a',email='admina@example.local',password_hash=hash_password('AdminPass123!'),merchant_id='m-a',role='ADMIN',is_active=True),
      User(id='u-ops-a',email='opsa@example.local',password_hash=hash_password('OpsPass123!'),merchant_id='m-a',role='OPS',is_active=True),
      User(id='u-view-a',email='viewa@example.local',password_hash=hash_password('ViewerPass123!'),merchant_id='m-a',role='VIEWER',is_active=True),
      User(id='u-admin-b',email='adminb@example.local',password_hash=hash_password('AdminPass123!'),merchant_id='m-b',role='ADMIN',is_active=True),
    ]); s.commit(); s.close()

def token(uid):
    s=SessionLocal(); u=s.get(User,uid); t=create_access_token(u); s.close(); return t

def auth(uid): return {'Authorization':'Bearer '+token(uid)}

def test_auth_login_me_and_password_hash():
    reset(); seed();
    r=client.post('/api/v1/auth/login',json={'email':'admina@example.local','password':'AdminPass123!'}); assert r.status_code==200
    assert 'access_token' in r.json()
    me=client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+r.json()['access_token']}); assert me.status_code==200 and me.json()['merchant_id']=='m-a'
    assert 'AdminPass123!' not in me.text and 'password_hash' not in me.text

def test_invalid_expired_and_inactive_token():
    reset(); seed();
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer bad'}).status_code==401
    s=SessionLocal(); u=s.get(User,'u-view-a'); u.is_active=False; s.commit(); s.refresh(u); t=create_access_token(u); s.close(); assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+t}).status_code==401

def test_viewer_forbidden_mutation():
    reset(); seed();
    r=client.post('/api/v1/payments',json={'provider_payment_id':'P1','amount':'10'},headers=auth('u-view-a')); assert r.status_code==403
    r=client.post('/api/v1/cases',json={},headers=auth('u-view-a')); assert r.status_code==403

def test_cross_tenant_payment_and_case_are_hidden():
    reset(); seed();
    s=SessionLocal(); p=Payment(provider='demo',provider_payment_id='PB',merchant_id='m-b',amount=Decimal('10'),currency='INR',status='captured'); s.add(p); s.commit(); pid=p.id; s.close()
    assert client.get('/api/v1/payments/'+pid,headers=auth('u-admin-a')).status_code==404
    assert client.get('/api/v1/cases/not-a-case',headers=auth('u-admin-a')).status_code==404

def test_admin_user_management_and_last_admin_guard():
    reset(); seed();
    r=client.post('/api/v1/users',json={'email':'new@example.local','password':'NewUserPass123!','role':'OPS'},headers=auth('u-admin-a')); assert r.status_code==201
    assert client.get('/api/v1/users',headers=auth('u-admin-a')).json()['items']
    r=client.patch('/api/v1/users/u-admin-a',json={'is_active':False},headers=auth('u-admin-a')); assert r.status_code==400
    r=client.patch('/api/v1/users/u-admin-a',json={'role':'VIEWER'},headers=auth('u-admin-a')); assert r.status_code==400
    assert client.post('/api/v1/users',json={'email':'bad@example.local','password':'BadUserPass123!','role':'OPS'},headers=auth('u-admin-a')).status_code==201

def test_bootstrap_registration_requires_first_admin_then_admin_scopes_users():
    reset(); s=SessionLocal(); s.add(Merchant(id='m-a',name='Merchant A',email='a@example.local')); s.commit(); s.close()
    r=client.post('/api/v1/auth/register',json={'email':'first@example.local','password':'FirstPass123!','merchant_id':'m-a','role':'ADMIN'},headers={'X-Bootstrap-Token':'stage07-bootstrap'}); assert r.status_code==403
    os.environ['AUTH_BOOTSTRAP_TOKEN']='stage07-bootstrap'
    r=client.post('/api/v1/auth/register',json={'email':'first@example.local','password':'FirstPass123!','merchant_id':'m-a','role':'ADMIN'},headers={'X-Bootstrap-Token':'stage07-bootstrap'}); assert r.status_code==201
    assert client.post('/api/v1/auth/register',json={'email':'second@example.local','password':'SecondPass123!','merchant_id':'m-a','role':'VIEWER'}).status_code==403

def test_financial_records_keep_amounts_after_auth_operations():
    reset(); seed();
    r=client.post('/api/v1/payments',json={'provider_payment_id':'P1','amount':'123.45'},headers=auth('u-admin-a')); assert r.status_code==201
    pid=r.json()['id']; before=client.get('/api/v1/payments/'+pid,headers=auth('u-admin-a')).json()['amount']
    client.get('/api/v1/dashboard/summary',headers=auth('u-admin-a'))
    assert client.get('/api/v1/payments/'+pid,headers=auth('u-admin-a')).json()['amount']==before

def test_ops_and_analyst_permissions_are_distinct():
    reset(); seed()
    # OPS can perform case investigation operations.
    r=client.post('/api/v1/cases',json={},headers=auth('u-ops-a')); assert r.status_code==200
    # ANALYST can investigate but cannot perform operational case mutations.
    r=client.post('/api/v1/cases',json={},headers=auth('u-view-a')); assert r.status_code==403
    # Viewer remains read-only.
    assert client.get('/api/v1/payments',headers=auth('u-view-a')).status_code==200

def test_admin_cannot_manage_other_merchant_users():
    reset(); seed()
    assert client.patch('/api/v1/users/u-admin-b',json={'role':'OPS'},headers=auth('u-admin-a')).status_code==404

def test_expired_token_is_rejected_using_real_jwt():
    reset(); seed()
    import jwt
    from datetime import datetime, timedelta, timezone
    claims={'sub':'u-admin-a','merchant_id':'m-a','role':'ADMIN','iat':datetime.now(timezone.utc)-timedelta(hours=2),'exp':datetime.now(timezone.utc)-timedelta(minutes=1)}
    t=jwt.encode(claims,os.environ['AUTH_SECRET'],algorithm='HS256')
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+t}).status_code==401
