import os
from pathlib import Path
os.environ["DATABASE_URL"] = "sqlite:///./test_rcaa.db"
os.environ["AUTH_SECRET"] = "stage08-test-secret-abcdefghijklmnopqrstuvwxyz"
os.environ["AUTH_BOOTSTRAP_TOKEN"] = "stage08-bootstrap-token"

from fastapi.testclient import TestClient
from sqlalchemy import select, update, delete
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import AuditEvent, Merchant, User, Payment
from app.security import hash_password, create_access_token
from app.audit import verify_hash_chain, canonical_json, calculate_event_hash, record_event

client = TestClient(app)


def reset():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        m1 = Merchant(id="m-a", name="Merchant A", email="a@example.com")
        m2 = Merchant(id="m-b", name="Merchant B", email="b@example.com")
        s.add_all([m1, m2])
        s.add_all([
            User(id="u-admin", email="admin@a.local", password_hash=hash_password("admin-password-123"), merchant_id="m-a", role="ADMIN", is_active=True),
            User(id="u-ops", email="ops@a.local", password_hash=hash_password("ops-password-123"), merchant_id="m-a", role="OPS", is_active=True),
            User(id="u-view", email="viewer@a.local", password_hash=hash_password("viewer-password-123"), merchant_id="m-a", role="VIEWER", is_active=True),
            User(id="u-b", email="admin@b.local", password_hash=hash_password("admin-password-123"), merchant_id="m-b", role="ADMIN", is_active=True),
        ])
        s.commit()


def token(email, password=None):
    password = password or ("viewer-password-123" if email == "viewer@a.local" else "admin-password-123")
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def headers(t):
    return {"Authorization": f"Bearer {t}"}


def test_login_success_and_failure_audited():
    reset()
    assert client.post("/api/v1/auth/login", json={"email": "admin@a.local", "password": "bad-password-123"}).status_code == 401
    t = token("admin@a.local")
    with SessionLocal() as s:
        events = s.scalars(select(AuditEvent).order_by(AuditEvent.timestamp, AuditEvent.id)).all()
        assert [e.action for e in events][-2:] == ["AUTH_LOGIN_FAILURE", "AUTH_LOGIN_SUCCESS"]
        assert events[-1].outcome == "SUCCESS"
        assert all("password" not in str(e.metadata_json).lower() and "hash" not in str(e.metadata_json).lower() for e in events)
        assert all(e.actor_type in {"USER", "SYSTEM", "SYSTEM_GLOBAL", "AI"} for e in events)


def test_case_lifecycle_and_request_correlation_are_audited():
    reset(); t = token("admin@a.local")
    h = headers(t); h["X-Request-ID"] = "audit-case-001"
    c = client.post("/api/v1/cases", json={"title":"Audit case"}, headers=h)
    assert c.status_code == 200
    cid = c.json()["id"]
    assert client.post(f"/api/v1/cases/{cid}/assign", json={"assigned_to":"ops"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/notes", json={"note":"reviewed"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/start", json={}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/resolve", json={"resolution_code":"FALSE_POSITIVE"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/reopen", json={}, headers=h).status_code == 200
    with SessionLocal() as s:
        actions = [e.action for e in s.scalars(select(AuditEvent).where(AuditEvent.merchant_id=="m-a").order_by(AuditEvent.timestamp, AuditEvent.id)).all()]
        for action in ["CASE_CREATED","CASE_ASSIGNED","CASE_NOTE_ADDED","CASE_STATUS_CHANGED","CASE_RESOLVED","CASE_REOPENED"]:
            assert action in actions
        resolved = s.scalar(select(AuditEvent).where(AuditEvent.action=="CASE_RESOLVED").order_by(AuditEvent.timestamp.desc()))
        assert resolved.before_snapshot["status"] == "IN_PROGRESS"
        assert resolved.after_snapshot["status"] == "RESOLVED"
        assert resolved.request_id == "audit-case-001"


def test_user_admin_auditing_excludes_passwords():
    reset(); t=token("admin@a.local"); h=headers(t)
    r=client.post("/api/v1/users", json={"email":"new@a.local","password":"new-password-123","role":"OPS"}, headers=h)
    assert r.status_code == 201
    uid=r.json()["id"]
    assert client.patch(f"/api/v1/users/{uid}", json={"role":"ANALYST"}, headers=h).status_code == 200
    assert client.patch(f"/api/v1/users/{uid}", json={"is_active":False}, headers=h).status_code == 200
    with SessionLocal() as s:
        ev=s.scalars(select(AuditEvent).where(AuditEvent.resource_id==uid).order_by(AuditEvent.timestamp, AuditEvent.id)).all()
        assert {x.action for x in ev} >= {"USER_CREATED","USER_ROLE_CHANGED","USER_DISABLED","USER_UPDATED"}
        text=str([(x.metadata_json,x.before_snapshot,x.after_snapshot) for x in ev]).lower()
        assert "new-password-123" not in text
        assert "password_hash" not in text


def test_viewer_denied_operation_is_audited():
    reset(); vt=token("viewer@a.local"); at=token("admin@a.local")
    cid=client.post("/api/v1/cases",json={"title":"Protected"},headers=headers(at)).json()["id"]
    r=client.post(f"/api/v1/cases/{cid}/resolve",json={"resolution_code":"FALSE_POSITIVE"},headers=headers(vt))
    assert r.status_code == 403
    with SessionLocal() as s:
        e=s.scalar(select(AuditEvent).where(AuditEvent.resource_id==cid, AuditEvent.action=="CASE_RESOLVED", AuditEvent.outcome=="DENIED").order_by(AuditEvent.timestamp.desc()))
        assert e is not None and e.actor_role == "VIEWER"


def test_audit_api_is_read_only_and_tenant_scoped():
    reset(); at=token("admin@a.local"); bt=token("admin@b.local")
    cid=client.post("/api/v1/cases",json={},headers=headers(at)).json()["id"]
    items=client.get("/api/v1/audit/events",headers=headers(at)).json()
    assert items["total"] >= 2
    assert all(x["merchant_id"] == "m-a" for x in items["items"])
    own_event=items["items"][0]["event_id"]
    assert client.get(f"/api/v1/audit/events/{own_event}",headers=headers(at)).status_code == 200
    assert client.get(f"/api/v1/audit/events/{own_event}",headers=headers(bt)).status_code == 404
    assert client.get("/api/v1/audit/events",headers=headers(bt)).json()["total"] >= 1


def test_hash_chain_valid_and_tamper_detected_and_canonical_hash_deterministic():
    reset(); t=token("admin@a.local")
    client.post("/api/v1/cases",json={},headers=headers(t))
    with SessionLocal() as s:
        ok,bad=verify_hash_chain(s); assert ok and bad is None
        first=s.scalar(select(AuditEvent).order_by(AuditEvent.timestamp,AuditEvent.id))
        expected=calculate_event_hash(first.previous_event_hash, canonical_json_payload(first)) if False else calculate_event_hash(first.previous_event_hash, __import__('app.audit.service',fromlist=['canonical_payload']).canonical_payload(first))
        assert expected == first.event_hash
        s.execute(update(AuditEvent).where(AuditEvent.event_id==first.event_id).values(outcome="FAILURE")); s.commit()
        ok,bad=verify_hash_chain(s); assert not ok and bad == first.event_id


def test_audit_orm_update_delete_are_blocked():
    reset(); t=token("admin@a.local"); client.post("/api/v1/cases",json={},headers=headers(t))
    with SessionLocal() as s:
        e=s.scalar(select(AuditEvent).order_by(AuditEvent.timestamp,AuditEvent.id))
        e.outcome="FAILURE"
        try:
            s.commit(); raised=False
        except ValueError:
            s.rollback(); raised=True
        assert raised
        e=s.scalar(select(AuditEvent).order_by(AuditEvent.timestamp,AuditEvent.id))
        try:
            s.delete(e); s.commit(); raised=False
        except ValueError:
            s.rollback(); raised=True
        assert raised


def test_request_id_invalid_value_is_replaced():
    reset(); t=token("admin@a.local")
    r=client.get("/health",headers={"X-Request-ID":"bad value with spaces"})
    assert r.status_code==200 and r.headers["X-Request-ID"] != "bad value with spaces"

def test_imports_reconciliation_exception_and_ai_operations_are_audited():
    reset(); t=token("admin@a.local"); h=headers(t)
    p=client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[{'provider_payment_id':'audit-p1','amount':'1000','currency':'INR','status':'captured','event_timestamp':'2026-09-02T10:00:00Z'}]},headers=h)
    assert p.status_code==200
    rf=client.post('/api/v1/import/refunds',json={'source':'manual_demo','provider':'demo','records':[{'provider_refund_id':'audit-r1','provider_payment_id':'audit-p1','amount':'100','currency':'INR','status':'processed','event_timestamp':'2026-09-02T10:05:00Z'}]},headers=h)
    assert rf.status_code==200
    st=client.post('/api/v1/import/settlements',json={'source':'manual_demo','provider':'demo','records':[{'provider_settlement_id':'audit-s1','provider_payment_id':'audit-p1','amount':'850','gross_amount':'1000','fee':'80','tax':'20','currency':'INR','status':'processed','event_timestamp':'2026-09-02T11:00:00Z'}]},headers=h)
    assert st.status_code==200
    csv=b'external_id,amount,currency,event_timestamp,status,reference\nbank-a,900,INR,2026-09-02T11:01:00Z,posted,audit-p1\n'
    bk=client.post('/api/v1/import/bank-transactions',files={'file':('bank.csv',csv,'text/csv')},headers=h)
    assert bk.status_code==200
    rr=client.post('/api/v1/reconciliation/run',headers=h); assert rr.status_code==200
    cases=client.get('/api/v1/reconciliation/cases',headers=h).json()['items']; assert cases
    cid=cases[0]['id']
    ai=client.post(f'/api/v1/cases/{cid}/ai/investigate',json={'question':'Summarize the deterministic evidence.'},headers=h)
    assert ai.status_code==200, ai.text
    with SessionLocal() as s:
        actions={e.action for e in s.scalars(select(AuditEvent).where(AuditEvent.merchant_id=='m-a')).all()}
        assert {'PAYMENT_IMPORTED','REFUND_IMPORTED','SETTLEMENT_IMPORTED','BANK_TRANSACTION_IMPORTED','RECONCILIATION_STARTED','RECONCILIATION_COMPLETED','AI_INVESTIGATION_REQUESTED','AI_INVESTIGATION_COMPLETED'} <= actions
        ai_events=s.scalars(select(AuditEvent).where(AuditEvent.action.in_(['AI_INVESTIGATION_REQUESTED','AI_INVESTIGATION_COMPLETED']))).all()
        assert all('api_key' not in str(e.metadata_json).lower() and 'secret' not in str(e.metadata_json).lower() for e in ai_events)


def test_ai_failure_is_audited_without_credentials():
    reset(); t=token('admin@a.local'); h=headers(t)
    client.post('/api/v1/import/payments',json={'source':'manual_demo','provider':'demo','records':[{'provider_payment_id':'fail-p1','amount':'1000','currency':'INR','status':'captured','event_timestamp':'2026-09-02T10:00:00Z'}]},headers=h)
    client.post('/api/v1/reconciliation/run',headers=h)
    c=client.get('/api/v1/reconciliation/cases',headers=h).json()['items'][0]['id']
    import app.api.routes.ai as ai_route
    original=ai_route.investigate
    def fail(*args,**kwargs):
        from app.ai.service import AIServiceError
        raise AIServiceError('AI_ERROR','safe failure')
    ai_route.investigate=fail
    try:
        r=client.post(f'/api/v1/cases/{c}/ai/investigate',json={'question':'test'},headers=h)
        assert r.status_code in {400,500,503}
    finally:
        ai_route.investigate=original
    with SessionLocal() as s:
        e=s.scalar(select(AuditEvent).where(AuditEvent.action=='AI_INVESTIGATION_FAILED').order_by(AuditEvent.timestamp.desc()))
        assert e and e.outcome=='FAILURE'
        assert 'api_key' not in str(e.metadata_json).lower()


def test_transaction_rollback_does_not_leave_business_or_success_audit():
    reset()
    from app.services.transactions import create_payment
    try:
        with SessionLocal() as s:
            value=create_payment(s, {'provider':'demo','provider_payment_id':'rollback-p','amount':'10','currency':'INR','status':'captured','merchant_id':'m-a'}, commit=False)
            record_event(s, action='PAYMENT_CREATED', resource_type='PAYMENT', resource_id=value.id, merchant_id='m-a', actor_user_id='u-admin', actor_role='ADMIN', metadata={'provider':'demo'})
            raise RuntimeError('forced rollback')
    except RuntimeError:
        pass
    with SessionLocal() as s:
        assert s.scalar(select(Payment).where(Payment.provider_payment_id=='rollback-p')) is None
        assert s.scalar(select(AuditEvent).where(AuditEvent.resource_type=='PAYMENT', AuditEvent.metadata_json['provider'].as_string()=='demo')) is None


def test_successful_transaction_and_audit_commit_together():
    reset()
    from app.services.transactions import create_payment
    with SessionLocal() as s:
        value=create_payment(s, {'provider':'demo','provider_payment_id':'commit-p','amount':'10','currency':'INR','status':'captured','merchant_id':'m-a'}, commit=False)
        record_event(s, action='PAYMENT_CREATED', resource_type='PAYMENT', resource_id=value.id, merchant_id='m-a', actor_user_id='u-admin', actor_role='ADMIN', metadata={'provider':'demo'})
        s.commit()
    with SessionLocal() as s:
        value=s.scalar(select(Payment).where(Payment.provider_payment_id=='commit-p'))
        event=s.scalar(select(AuditEvent).where(AuditEvent.resource_id==value.id))
        assert value and event and event.outcome=='SUCCESS'
