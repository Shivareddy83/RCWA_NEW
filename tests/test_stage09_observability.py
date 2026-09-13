import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

os.environ["DATABASE_URL"] = "sqlite:///./test_rcaa.db"
os.environ["AUTH_SECRET"] = "stage09-test-secret-abcdefghijklmnopqrstuvwxyz"
os.environ["AUTH_BOOTSTRAP_TOKEN"] = "stage09-bootstrap-token"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import AuditEvent, Merchant, User, Payment
from app.security import hash_password
from app.observability.metrics import reset_metrics, render_prometheus
from app.observability.logging import StructuredFormatter
import logging

client = TestClient(app, raise_server_exceptions=False)


def reset():
    reset_metrics()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Merchant(id="m-a", name="Merchant A", email="a@example.com"),
            Merchant(id="m-b", name="Merchant B", email="b@example.com"),
            User(id="u-admin", email="admin@a.local", password_hash=hash_password("admin-password-123"), merchant_id="m-a", role="ADMIN", is_active=True),
        ])
        s.commit()


def login():
    r = client.post("/api/v1/auth/login", json={"email":"admin@a.local", "password":"admin-password-123"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_request_id_generation_preservation_and_bounded_http_metrics():
    reset()
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]
    supplied = "stage09-correlation-001"
    r3 = client.get("/health", headers={"X-Request-ID": supplied})
    assert r3.headers["X-Request-ID"] == supplied
    bad = client.get("/health", headers={"X-Request-ID":"x" * 129})
    assert bad.headers["X-Request-ID"] != "x" * 129
    metrics = client.get("/metrics").text
    assert "http_requests_total" in metrics
    assert 'method="GET"' in metrics
    assert 'route="/health"' in metrics
    assert "request_id" not in metrics
    assert "merchant_id" not in metrics


def test_structured_logs_redact_sensitive_values():
    formatter = StructuredFormatter()
    record = logging.LogRecord("test", logging.INFO, __file__, 1,
                               "password=supersecret Authorization=Bearer.jwt api_key=secret-key", (), None)
    payload = json.loads(formatter.format(record))
    assert "supersecret" not in payload["message"]
    assert "secret-key" not in payload["message"]
    assert "Bearer.jwt" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_health_ready_metrics_and_no_secret_exposure():
    reset()
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status":"ready", "database":"ok"}
    body = ready.text + client.get("/metrics").text
    for secret in ["AUTH_SECRET", "password", "postgresql", "sqlite://"]:
        assert secret not in body.lower()


def test_ingestion_metrics_cover_create_and_duplicate():
    reset(); token = login(); h={"Authorization":f"Bearer {token}"}
    payload={"source":"manual_demo","provider":"demo","records":[{"provider_payment_id":"obs-p1","amount":"100","currency":"INR","status":"captured","event_timestamp":"2026-09-02T10:00:00Z"}]}
    assert client.post("/api/v1/import/payments", json=payload, headers=h).status_code == 200
    assert client.post("/api/v1/import/payments", json=payload, headers=h).status_code == 200
    metrics=client.get("/metrics").text
    assert 'ingestion_records_received_total{source_type="payment"}' in metrics
    assert 'ingestion_records_created_total{source_type="payment"}' in metrics
    assert 'ingestion_records_duplicate_total{source_type="payment"}' in metrics
    assert "obs-p1" not in metrics


def test_reconciliation_metrics_cover_match_and_duration():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.post("/api/v1/import/payments", json={"source":"manual_demo","provider":"demo","records":[{"provider_payment_id":"obs-p2","amount":"100","currency":"INR","status":"captured","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    client.post("/api/v1/import/settlements", json={"source":"manual_demo","provider":"demo","records":[{"provider_settlement_id":"obs-s2","provider_payment_id":"obs-p2","amount":"100","gross_amount":"100","fee":"0","tax":"0","currency":"INR","status":"processed","event_timestamp":"2026-09-02T11:00:00Z"}]}, headers=h)
    assert client.post("/api/v1/reconciliation/run", headers=h).status_code == 200
    metrics=client.get("/metrics").text
    assert "reconciliation_runs_total" in metrics
    assert "reconciliation_duration_seconds_count" in metrics
    assert "reconciliation_matches_total" in metrics
    assert "obs-p2" not in metrics


def test_case_exception_and_audit_metrics_increment():
    reset(); token=login(); h={"Authorization":f"Bearer {token}", "X-Request-ID":"obs-case-001"}
    r=client.post("/api/v1/cases", json={"title":"Observed case"}, headers=h)
    assert r.status_code == 200
    cid=r.json()["id"]
    assert client.post(f"/api/v1/cases/{cid}/assign", json={"assigned_to":"ops"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/notes", json={"note":"review"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/start", json={}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/resolve", json={"resolution_code":"FALSE_POSITIVE"}, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/reopen", json={}, headers=h).status_code == 200
    metrics=client.get("/metrics").text
    for name in ["cases_created_total", "cases_resolved_total", "cases_reopened_total", "case_status_transitions_total", "case_notes_added_total", "audit_events_created_total"]:
        assert name in metrics
    assert cid not in metrics


def test_ai_metrics_success_and_reuse():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.post("/api/v1/import/payments", json={"source":"manual_demo","provider":"demo","records":[{"provider_payment_id":"ai-p1","amount":"100","currency":"INR","status":"captured","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    client.post("/api/v1/reconciliation/run", headers=h)
    cases=client.get("/api/v1/reconciliation/cases", headers=h).json()["items"]
    assert cases
    cid=cases[0]["id"]
    q={"question":"Summarize the deterministic evidence."}
    assert client.post(f"/api/v1/cases/{cid}/ai/investigate", json=q, headers=h).status_code == 200
    assert client.post(f"/api/v1/cases/{cid}/ai/investigate", json=q, headers=h).status_code == 200
    metrics=client.get("/metrics").text
    assert "ai_investigations_total" in metrics
    assert "ai_investigations_success_total" in metrics
    assert "ai_investigations_reused_total" in metrics
    assert cid not in metrics


def test_denied_action_and_audit_correlation():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    # Build a viewer directly to exercise Stage 07 RBAC without altering production roles.
    with SessionLocal() as s:
        s.add(User(id="u-view", email="view@a.local", password_hash=hash_password("viewer-password-123"), merchant_id="m-a", role="VIEWER", is_active=True)); s.commit()
    viewer=client.post("/api/v1/auth/login", json={"email":"view@a.local","password":"viewer-password-123"}).json()["access_token"]
    cid=client.post("/api/v1/cases", json={"title":"Protected"}, headers={"Authorization":f"Bearer {token}"}).json()["id"]
    rid="denied-observability-001"
    r=client.post(f"/api/v1/cases/{cid}/resolve", json={"resolution_code":"FALSE_POSITIVE"}, headers={"Authorization":f"Bearer {viewer}","X-Request-ID":rid})
    assert r.status_code==403 and r.headers["X-Request-ID"]==rid
    with SessionLocal() as s:
        event=s.scalar(select(AuditEvent).where(AuditEvent.action=="CASE_RESOLVED", AuditEvent.outcome=="DENIED", AuditEvent.resource_id==cid).order_by(AuditEvent.timestamp.desc()))
        assert event and event.request_id==rid
    assert "audit_events_denied_total" in client.get("/metrics").text


def test_readiness_failure_returns_not_ready(monkeypatch):
    reset()
    import app.main as main
    class BrokenSession:
        def execute(self, *args, **kwargs): raise RuntimeError("db unavailable")
        def close(self): pass
    monkeypatch.setattr(main, "SessionLocal", lambda: BrokenSession())
    r=client.get("/ready")
    assert r.status_code==503
    assert r.json()=={"status":"not_ready","database":"unavailable"}


def test_unexpected_500_is_telemetried_without_stack_trace_to_client():
    reset()
    from fastapi import APIRouter
    router = APIRouter()
    @router.get("/stage09-test-500")
    def forced_500():
        raise RuntimeError("password=supersecret")
    app.include_router(router)
    try:
        r=client.get("/stage09-test-500")
        assert r.status_code==500
        assert "supersecret" not in r.text
        metrics=client.get("/metrics").text
        assert 'http_requests_total{method="GET",route="/stage09-test-500",status="500"}' in metrics
    finally:
        app.routes[:] = [route for route in app.routes if getattr(route, "path", None) != "/stage09-test-500"]


def test_metrics_have_no_high_cardinality_identifiers():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.get("/api/v1/payments", headers={**h,"X-Request-ID":"req-secret-cardinality"})
    text=client.get("/metrics").text
    forbidden_labels=["request_id=", "payment_id=", "case_id=", "merchant_id=", "user_id=", "utr=", "order_id="]
    assert all(label not in text for label in forbidden_labels)


def test_exception_lifecycle_metrics_increment():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.post("/api/v1/import/payments", json={"source":"manual_demo","provider":"demo","records":[{"provider_payment_id":"ex-p1","amount":"100","currency":"INR","status":"captured","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    assert client.post("/api/v1/reconciliation/run", headers=h).status_code==200
    excs=client.get("/api/v1/exceptions",headers=h).json()["items"]
    assert excs
    eid=excs[0]["id"]
    assert client.post(f"/api/v1/exceptions/{eid}/acknowledge",headers=h).status_code==200
    assert client.post(f"/api/v1/exceptions/{eid}/resolve",headers=h).status_code==200
    metrics=client.get("/metrics").text
    assert "exceptions_created_total" in metrics
    assert "exceptions_acknowledged_total" in metrics
    assert "exceptions_resolved_total" in metrics
    assert eid not in metrics


def test_ai_provider_failure_increments_bounded_failure_metric():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.post("/api/v1/import/payments", json={"source":"manual_demo","provider":"demo","records":[{"provider_payment_id":"ai-fail","amount":"100","currency":"INR","status":"captured","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    client.post("/api/v1/reconciliation/run", headers=h)
    cid=client.get("/api/v1/reconciliation/cases",headers=h).json()["items"][0]["id"]
    import app.ai.service as ai_service
    from app.ai.providers.openai_compatible import AIProviderError
    original=ai_service._provider
    class FailingProvider:
        name="mock"; model="test"
        def generate_investigation(self, **kwargs):
            raise AIProviderError("AI_TIMEOUT", "provider timed out")
    ai_service._provider=lambda: FailingProvider()
    try:
        r=client.post(f"/api/v1/cases/{cid}/ai/investigate",json={"question":"test"},headers=h)
        assert r.status_code in {400,503}
    finally:
        ai_service._provider=original
    metrics=client.get("/metrics").text
    assert 'ai_investigations_failed_total{failure_category="timeout",provider="mock"}' in metrics
    assert "ai-fail" not in metrics


def test_observability_does_not_change_financial_truth():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    p=client.post("/api/v1/payments",json={"provider":"demo","provider_payment_id":"immutable-p","amount":"123.45","currency":"INR","status":"captured"},headers=h)
    assert p.status_code==201
    with SessionLocal() as s:
        before=s.scalar(select(Payment).where(Payment.provider_payment_id=="immutable-p"))
        amount=before.amount
    client.get("/metrics"); client.get("/health"); client.get("/ready")
    with SessionLocal() as s:
        after=s.scalar(select(Payment).where(Payment.provider_payment_id=="immutable-p"))
        assert str(after.amount)==str(amount)=="123.45"


def test_all_ingestion_source_metrics_are_bounded():
    reset(); token=login(); h={"Authorization":f"Bearer {token}"}
    client.post("/api/v1/import/refunds", json={"source":"manual_demo","provider":"demo","records":[{"provider_refund_id":"obs-r1","provider_payment_id":"missing-p","amount":"10","currency":"INR","status":"processed","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    client.post("/api/v1/import/settlements", json={"source":"manual_demo","provider":"demo","records":[{"provider_settlement_id":"obs-s1","provider_payment_id":"missing-p","amount":"10","gross_amount":"10","fee":"0","tax":"0","currency":"INR","status":"processed","event_timestamp":"2026-09-02T10:00:00Z"}]}, headers=h)
    csv=b'external_id,amount,currency,event_timestamp,status,reference\nobs-b1,10,INR,2026-09-02T10:00:00Z,posted,missing-p\n'
    assert client.post("/api/v1/import/bank-transactions",files={"file":("bank.csv",csv,"text/csv")},headers=h).status_code==200
    text=client.get("/metrics").text
    for source in ["refund","settlement","bank_transaction"]:
        assert f'source_type="{source}"' in text
    for identifier in ["obs-r1","obs-s1","obs-b1","missing-p"]:
        assert identifier not in text
