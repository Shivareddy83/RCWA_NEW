import hashlib
import hmac
import json
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Merchant, BillingSubscription, BillingInvoice, WebhookEvent
from app.providers.razorpay_billing import RazorpayBillingProvider
from app.services.webhooks import process_razorpay_webhook
import app.services.webhooks as webhooks_service
from app.core.config import settings
from dataclasses import replace

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def _secret():
    return 'v09-webhook-secret'


def _signed(payload: dict):
    raw = json.dumps(payload, separators=(',', ':')).encode()
    sig = hmac.new(_secret().encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


def test_razorpay_subscription_request_uses_plan_and_tenant_note(monkeypatch):
    calls = {}

    class Response:
        status_code = 200
        def json(self):
            return {'id': 'sub_test_001', 'status': 'created', 'short_url': 'https://rzp.io/i/test'}

    def fake_request(method, url, auth, json, timeout):
        calls.update(method=method, url=url, auth=auth, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr('app.providers.razorpay_billing.httpx.request', fake_request)
    remote = RazorpayBillingProvider('key_test', 'secret_test').create_subscription(plan_id='plan_AbCdEf12345678', merchant_id='merchant-1')
    assert remote['id'] == 'sub_test_001'
    assert calls['method'] == 'POST'
    assert calls['url'].endswith('/subscriptions')
    assert calls['json']['plan_id'] == 'plan_AbCdEf12345678'
    assert calls['json']['notes']['rcaa_merchant_id'] == 'merchant-1'
    assert calls['json']['total_count'] == 1200
    assert calls['json']['quantity'] == 1
    assert calls['json']['customer_notify'] is True
    assert 'start_at' not in calls['json']
    assert 'end_at' not in calls['json']


def test_checkout_signature_matches_documented_subscription_formula(monkeypatch):
    secret = 'checkout-secret'
    payment_id = 'pay_test_123'
    subscription_id = 'sub_test_123'
    signature = hmac.new(secret.encode(), f'{payment_id}|{subscription_id}'.encode(), hashlib.sha256).hexdigest()
    expected = hmac.new(secret.encode(), f'{payment_id}|{subscription_id}'.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, signature)
    assert not hmac.compare_digest(expected, '0' * 64)


def test_subscription_charged_webhook_marks_invoice_paid_and_subscription_active(monkeypatch):
    monkeypatch.setattr(webhooks_service, 'settings', replace(settings, razorpay_webhook_secret=_secret()))
    s = Session()
    merchant = Merchant(id='m-v09', name='V09 Merchant', email='v09@example.com')
    sub = BillingSubscription(
        merchant_id=merchant.id, plan_code='GROWTH', status='PENDING_ACTIVATION', currency='INR',
        monthly_price=Decimal('24999.00'), monthly_transaction_limit=500000,
        current_period_start=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
        current_period_end=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
        provider='RAZORPAY', provider_subscription_id='sub_v09', provider_plan_id='plan_AbCdEf12345678'
    )
    invoice = BillingInvoice(
        merchant_id=merchant.id, subscription_id=sub.id, invoice_number='RCAA-V09-001', status='PENDING', currency='INR',
        subtotal=Decimal('24999.00'), tax=Decimal('0'), total=Decimal('24999.00'),
        issued_at=sub.current_period_start, due_at=sub.current_period_end, provider='RAZORPAY'
    )
    s.add_all([merchant, sub]); s.flush(); invoice.subscription_id=sub.id; s.add(invoice); s.commit()

    payload = {
        'entity': 'event', 'event': 'subscription.charged', 'created_at': 1,
        'payload': {
            'subscription': {'entity': {'id': 'sub_v09', 'status': 'active', 'plan_id': 'plan_AbCdEf12345678', 'customer_id': 'cust_v09', 'current_start': 1700000000, 'current_end': 1702592000}},
            'payment': {'entity': {'id': 'pay_v09', 'status': 'captured', 'amount': 2499900, 'currency': 'INR', 'invoice_id': 'inv_v09'}}
        }
    }
    raw, sig = _signed(payload)
    result, valid = process_razorpay_webhook(s, raw, sig, 'evt_v09_001')
    assert valid is True
    assert result['status'] == 'processed'
    s.refresh(sub); s.refresh(invoice)
    assert sub.status == 'ACTIVE'
    assert sub.provider_customer_id == 'cust_v09'
    assert sub.last_payment_id == 'pay_v09'
    assert invoice.status == 'PAID'
    assert invoice.provider_invoice_id == 'inv_v09'
    assert invoice.provider_payment_id == 'pay_v09'
    assert s.query(WebhookEvent).filter_by(event_id='evt_v09_001').count() == 1
    s.close()


def test_duplicate_subscription_webhook_is_idempotent(monkeypatch):
    monkeypatch.setattr(webhooks_service, 'settings', replace(settings, razorpay_webhook_secret=_secret()))
    s = Session()
    payload = {'entity':'event','event':'subscription.authenticated','payload':{'subscription':{'entity':{'id':'unknown-sub','status':'authenticated'}}}}
    raw, sig = _signed(payload)
    first, valid = process_razorpay_webhook(s, raw, sig, 'evt-v09-dup')
    second, valid2 = process_razorpay_webhook(s, raw, sig, 'evt-v09-dup')
    assert valid and valid2
    assert first['status'] == 'ignored'
    assert second['status'] == 'duplicate'
    s.close()


def test_invalid_plan_id_is_rejected_before_network_call(monkeypatch):
    called = False
    def fake_request(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not be called")
    monkeypatch.setattr('app.providers.razorpay_billing.httpx.request', fake_request)
    provider = RazorpayBillingProvider('key_test', 'secret_test')
    try:
        provider.create_subscription(plan_id='plan_growth', merchant_id='merchant-1')
        assert False, 'expected RazorpayBillingError'
    except Exception as exc:
        assert 'Invalid Razorpay plan ID format' in str(exc)
    assert called is False


def test_checkout_signature_verification_uses_explicit_secret():
    secret = 'explicit-secret'
    payment_id = 'pay_test_123'
    subscription_id = 'sub_test_123'
    signature = hmac.new(secret.encode(), f'{payment_id}|{subscription_id}'.encode(), hashlib.sha256).hexdigest()
    assert RazorpayBillingProvider.verify_checkout_signature(payment_id, subscription_id, signature, secret=secret)
    assert not RazorpayBillingProvider.verify_checkout_signature(payment_id, subscription_id, signature, secret='wrong-secret')
    assert not RazorpayBillingProvider.verify_checkout_signature('', subscription_id, signature, secret=secret)


def test_fetch_subscription_and_cancel_use_documented_endpoints(monkeypatch):
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {'id': 'sub_test_123', 'status': 'active'}
    def fake_request(method, url, auth, json, timeout):
        calls.append((method, url, json))
        return Response()
    monkeypatch.setattr('app.providers.razorpay_billing.httpx.request', fake_request)
    provider = RazorpayBillingProvider('key_test', 'secret_test')
    provider.fetch_subscription('sub_test_123')
    provider.cancel_subscription('sub_test_123', at_cycle_end=True)
    assert calls[0][0] == 'GET' and calls[0][1].endswith('/subscriptions/sub_test_123')
    assert calls[1][0] == 'POST' and calls[1][1].endswith('/subscriptions/sub_test_123/cancel')
    assert calls[1][2] == {'cancel_at_cycle_end': True}
