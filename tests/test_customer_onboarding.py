import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite:///./test_rcaa_onboarding.db'
os.environ['RAZORPAY_WEBHOOK_SECRET'] = 'test_secret'
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))

from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant, Payment, Settlement

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
client = TestClient(app)


def seed_merchant():
    with SessionLocal() as session:
        merchant = Merchant(id='onboarding-merchant', name='Onboarding Demo', email='onboarding@example.com')
        session.add(merchant)
        session.commit()


def setup_module():
    seed_merchant()


def test_onboarding_starts_in_progress():
    response = client.get('/api/v1/onboarding')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'IN_PROGRESS'
    assert data['complete'] is False
    assert data['ready_to_complete'] is False
    assert data['steps'][0]['complete'] is False


def test_admin_can_save_profile():
    response = client.put('/api/v1/onboarding/profile', json={
        'business_type': 'D2C_ECOMMERCE',
        'monthly_transaction_band': '10K_100K',
        'primary_provider': 'RAZORPAY',
    })
    assert response.status_code == 200
    assert response.json()['profile']['primary_provider'] == 'RAZORPAY'
    assert response.json()['steps'][0]['complete'] is True


def test_completion_requires_data_and_reconciliation():
    response = client.post('/api/v1/onboarding/complete')
    assert response.status_code == 409


def test_onboarding_completes_after_successful_reconciliation_event():
    with SessionLocal() as session:
        session.add(Payment(
            provider='razorpay', provider_payment_id='onboard-pay', provider_order_id='order-1',
            merchant_id='onboarding-merchant', amount='100.00', currency='INR', status='captured',
            captured=True, source='test', external_id='onboard-pay', raw_data={}
        ))
        session.add(Settlement(
            provider='razorpay', provider_settlement_id='onboard-settle', provider_payment_id='onboard-pay',
            merchant_id='onboarding-merchant', gross_amount='100.00', fee='0.00', tax='0.00', net_amount='100.00',
            status='processed', settled_at=datetime(2025, 1, 2, tzinfo=timezone.utc), source='test', external_id='onboard-settle', raw_data={}
        ))
        session.commit()

    assert client.post('/api/v1/reconciliation/run').status_code == 200
    response = client.post('/api/v1/onboarding/complete')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'COMPLETE'
    assert data['complete'] is True
    assert data['completed_at'] is not None
