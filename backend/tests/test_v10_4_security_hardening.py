import hashlib
import hmac
import json
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models import Merchant, BillingSubscription
from app.security.rate_limit import enforce_rate_limit, reset_rate_limit
import app.main as main_module
import app.services.webhooks as webhooks_service
from app.services.webhooks import process_razorpay_webhook

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def test_database_rate_limit_blocks_after_limit_and_can_reset(monkeypatch):
    # enforce_rate_limit() short-circuits to a no-op whenever settings.testing
    # is true (by design, so unrelated tests aren't rate-limited). This test's
    # entire purpose is to exercise the real enforcement path. `settings` is a
    # frozen dataclass (can't be mutated in place), so patch the name that
    # app.security.rate_limit imported rather than the shared settings object
    # itself — this leaves every other test's settings untouched.
    import dataclasses
    import app.security.rate_limit as rate_limit_module
    monkeypatch.setattr(rate_limit_module, "settings", dataclasses.replace(settings, testing=False))

    session = Session()
    action = "v104-test"
    key = "ip:test-v104"
    reset_rate_limit(session, action, key)
    enforce_rate_limit(session, action, key, 2, 300)
    enforce_rate_limit(session, action, key, 2, 300)
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(session, action, key, 2, 300)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"]
    reset_rate_limit(session, action, key)
    enforce_rate_limit(session, action, key, 2, 300)
    session.close()


def test_oversized_request_is_rejected_before_endpoint():
    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(main_module.app)
    response = client.get("/health", headers={"Content-Length": str(settings.max_request_body_bytes + 1)})
    assert response.status_code == 413
    assert response.headers["X-Request-ID"]


def test_production_metrics_require_bearer_token(monkeypatch):
    production = replace(settings, app_env="production", metrics_auth_token="metrics-test-secret")
    monkeypatch.setattr(main_module, "settings", production)
    with pytest.raises(HTTPException) as exc:
        main_module.metrics(None)
    assert exc.value.status_code == 401
    response = main_module.metrics("Bearer metrics-test-secret")
    assert response.media_type.startswith("text/plain")


def _signed(payload: dict, secret: str = "v104-webhook-secret"):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, signature


def test_razorpay_subscription_status_does_not_regress_on_out_of_order_webhook(monkeypatch):
    secret = "v104-webhook-secret"
    monkeypatch.setattr(webhooks_service, "settings", replace(settings, razorpay_webhook_secret=secret, razorpay_webhook_allowed_ips=()))
    session = Session()
    merchant = Merchant(id="m-v104", name="V104 Merchant", email="v104@example.com")
    sub = BillingSubscription(
        merchant_id=merchant.id,
        plan_code="GROWTH",
        status="PENDING_ACTIVATION",
        currency="INR",
        monthly_price=Decimal("24999.00"),
        monthly_transaction_limit=500000,
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc),
        provider="RAZORPAY",
        provider_subscription_id="sub_v104",
        provider_plan_id="plan_AbCdEf12345678",
    )
    session.add_all([merchant, sub])
    session.commit()

    for event_id, provider_status in [("evt-v104-active", "active"), ("evt-v104-pending", "pending")]:
        payload = {
            "entity": "event",
            "event": f"subscription.{provider_status}",
            "created_at": 200 if provider_status == "active" else 100,
            "payload": {"subscription": {"entity": {"id": "sub_v104", "status": provider_status}}},
        }
        raw, signature = _signed(payload, secret)
        result, valid = process_razorpay_webhook(session, raw, signature, event_id)
        assert valid is True
        assert result["status"] == "processed"

    session.refresh(sub)
    assert sub.provider_status == "active"
    assert sub.status == "ACTIVE"
    session.close()
