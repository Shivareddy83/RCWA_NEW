
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Configure the application before importing modules that construct the DB engine.
DB_PATH = Path(__file__).with_name("e2e_test.db")
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{DB_PATH}",
        "AUTH_SECRET": "E" * 64,
        "AUTH_BOOTSTRAP_TOKEN": "E2E-BOOTSTRAP",
        "APP_ENV": "development",
        "CORS_ORIGINS": "http://localhost:3000",
        "AI_PROVIDER": "mock",
        "MFA_ENCRYPTION_KEY": "gprqKB8VuqAWIvBr85ZnWMkt7bhztRDFWe8WTLZiON8=",
    }
)

from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.models import Merchant, BankTransaction


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    command.upgrade(Config("alembic.ini"), "head")
    session = SessionLocal()
    session.add(
        Merchant(
            id="e2e-merchant",
            name="E2E Merchant",
            email="e2e-merchant@example.com",
        )
    )
    session.commit()
    session.close()
    yield
    if DB_PATH.exists():
        DB_PATH.unlink()


@pytest.fixture()
def client():
    return TestClient(app)


def register_and_login(client):
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "StrongPassword123!"},
    )
    if logged_in.status_code != 200:
        registered = client.post(
            "/api/v1/auth/register",
            headers={"X-Bootstrap-Token": "E2E-BOOTSTRAP"},
            json={
                "email": "admin@example.com",
                "password": "StrongPassword123!",
                "merchant_id": "e2e-merchant",
                "role": "ADMIN",
            },
        )
        assert registered.status_code == 201
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "StrongPassword123!"},
        )

    assert logged_in.status_code == 200
    token = logged_in.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_registration_requires_controlled_bootstrap(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "blocked@example.com",
            "password": "StrongPassword123!",
            "merchant_id": "e2e-merchant",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 403


def test_registration_login_me_and_dashboard(client):
    headers = register_and_login(client)

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"
    assert me.json()["merchant_id"] == "e2e-merchant"

    dashboard = client.get("/api/v1/dashboard/summary", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["total_payments"] == 0


def test_bad_credentials_and_invalid_token_are_rejected(client):
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    invalid_token = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert invalid_token.status_code == 401


def test_financial_reconciliation_case_and_rca_flow(client):
    headers = register_and_login(client)

    payment = client.post(
        "/api/v1/payments",
        headers=headers,
        json={
            "provider": "demo",
            "provider_payment_id": "pay_e2e_001",
            "provider_order_id": "ord_e2e_001",
            "amount": "1000.00",
            "currency": "INR",
            "status": "captured",
            "method": "card",
            "captured": True,
            "raw_data": {"source": "e2e"},
        },
    )
    assert payment.status_code == 201

    settlement = client.post(
        "/api/v1/settlements",
        headers=headers,
        json={
            "provider": "demo",
            "provider_settlement_id": "set_e2e_001",
            "provider_payment_id": "pay_e2e_001",
            "gross_amount": "1000.00",
            "fee": "25.00",
            "tax": "5.00",
            "net_amount": "960.00",
            "status": "processed",
            "settled_at": datetime.now(timezone.utc).isoformat(),
            "utr": "utr_e2e_001",
            "raw_data": {"source": "e2e"},
        },
    )
    assert settlement.status_code == 201

    reconciliation = client.post(
        "/api/v1/reconciliation/run", headers=headers
    )
    assert reconciliation.status_code == 200
    assert reconciliation.json()["created_cases"] == 1
    assert reconciliation.json()["mismatch"] == 1

    cases = client.get("/api/v1/reconciliation/cases", headers=headers)
    assert cases.status_code == 200
    assert len(cases.json()["items"]) == 1

    case_id = cases.json()["items"][0]["id"]
    case = client.get(f"/api/v1/reconciliation/cases/{case_id}", headers=headers)
    assert case.status_code == 200

    rca = client.get(f"/api/v1/rca/{case_id}", headers=headers)
    assert rca.status_code == 200
    assert rca.json()["root_cause_code"] == "SETTLEMENT_AMOUNT_MISMATCH"

    start = client.post(f"/api/v1/cases/{case_id}/start", headers=headers)
    assert start.status_code == 200
    assert start.json()["status"] == "IN_PROGRESS"

    note = client.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=headers,
        json={"note": "Verified settlement amount against provider export."},
    )
    assert note.status_code == 200

    assigned = client.post(
        f"/api/v1/cases/{case_id}/assign",
        headers=headers,
        json={"assigned_to": "analyst@example.com"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == "analyst@example.com"

    options = client.get("/api/v1/cases/resolution-options", headers=headers)
    assert options.status_code == 200
    assert any(item["code"] == "PROVIDER_INVESTIGATION_REQUIRED" for item in options.json()["items"])

    blocked = client.post(
        f"/api/v1/cases/{case_id}/resolve", headers=headers,
        json={"resolution_code":"PROVIDER_INVESTIGATION_REQUIRED","resolution_note":"Attempt before financial recovery verification."},
    )
    assert blocked.status_code == 400

    recovery = client.get(f"/api/v1/cases/{case_id}/recovery", headers=headers)
    assert recovery.status_code == 200
    assert recovery.json()["status"] == "IDENTIFIED"
    assert recovery.json()["exposure_amount"] == "10.00"

    initiated = client.post(
        f"/api/v1/cases/{case_id}/recovery/initiate", headers=headers,
        json={"action_type":"PROVIDER_TICKET","external_reference":"RZP-REC-001","action_note":"Provider claim raised for settlement shortfall."},
    )
    assert initiated.status_code == 200
    assert initiated.json()["status"] == "RECOVERY_INITIATED"

    with SessionLocal() as s:
        bank = BankTransaction(
            source="bank_csv", provider="demo", external_id="bank_recovery_001",
            merchant_id="e2e-merchant", reference="RZP-REC-001", amount="10.00", currency="INR",
            status="posted", event_timestamp=datetime.now(timezone.utc), metadata_json={"source":"e2e_recovery"},
        )
        s.add(bank); s.commit(); s.refresh(bank); bank_id = bank.id

    verified = client.post(
        f"/api/v1/cases/{case_id}/recovery/verify", headers=headers,
        json={"bank_transaction_id":bank_id,"verification_note":"Bank credit exactly matches the recoverable settlement shortfall."},
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"
    assert verified.json()["recovered_amount"] == "10.00"

    resolved = client.post(
        f"/api/v1/cases/{case_id}/resolve",
        headers=headers,
        json={
            "resolution_code": "PROVIDER_INVESTIGATION_REQUIRED",
            "resolution_note": "Provider confirmation requested and recovery verified against the bank credit.",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["resolution_code"] == "PROVIDER_INVESTIGATION_REQUIRED"

    reopened = client.post(f"/api/v1/cases/{case_id}/reopen", headers=headers)
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "REOPENED"

    workspace = client.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert workspace.status_code == 200
    assert len(workspace.json()["notes"]) == 1
    assert any(event["event_type"] == "CASE_REOPENED" for event in workspace.json()["timeline"])

    ai = client.post(
        f"/api/v1/cases/{case_id}/ai/investigate",
        headers=headers,
        json={"question": "What should the analyst verify next?"},
    )
    assert ai.status_code == 200
    assert ai.json()["case_id"] == case_id
    assert ai.json()["ai_investigation"]["summary"]


def test_z_v13_launch_readiness_password_reset_and_connector(client):
    headers = register_and_login(client)
    r = client.post('/api/v1/auth/password/forgot', json={'email': 'admin@example.com'})
    assert r.status_code == 200
    token = r.json().get('reset_token')
    assert token
    r = client.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': 'FinalStrongPassword123!'})
    assert r.status_code == 200
    assert r.json()['password_reset'] is True
    assert client.post('/api/v1/auth/password/reset', json={'token': token, 'new_password': 'AnotherStrongPassword123!'}).status_code == 400

    # Login with the new password and configure the encrypted Razorpay connector.
    logged = client.post('/api/v1/auth/login', json={'email': 'admin@example.com', 'password': 'FinalStrongPassword123!'})
    assert logged.status_code == 200
    headers = {'Authorization': f"Bearer {logged.json()['access_token']}"}
    r = client.post('/api/v1/connectors', headers=headers, json={'provider':'razorpay','name':'Razorpay Test','key_id':'rzp_test_12345','key_secret':'secret-value-12345','sync_enabled':True,'sync_interval_minutes':360})
    assert r.status_code == 200
    from app.models import DataConnector
    with SessionLocal() as s:
        connector = s.query(DataConnector).filter_by(merchant_id='e2e-merchant', provider='razorpay').one()
        assert connector.credentials_enc and 'secret-value-12345' not in connector.credentials_enc
    guide = client.get('/api/v1/onboarding/guide', headers=headers)
    assert guide.status_code == 200
    assert guide.json()['recommended_path'] in {'RAZORPAY_CONNECTOR','FILE_IMPORT'}
