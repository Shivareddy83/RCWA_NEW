import hashlib
import hmac
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from app.providers.base import PaymentProvider

class RazorpayProvider(PaymentProvider):
    provider_name = "razorpay"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str):
        self.key_id = key_id
        self.key_secret = key_secret
        self.webhook_secret = webhook_secret

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(
            hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest(),
            signature,
        )

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        if not self.key_id or not self.key_secret:
            raise RuntimeError("Razorpay credentials are not configured")
        import razorpay
        return razorpay.Client(auth=(self.key_id, self.key_secret)).payment.fetch(payment_id)

    def fetch_refund(self, refund_id: str) -> dict[str, Any]:
        if not self.key_id or not self.key_secret:
            raise RuntimeError("Razorpay credentials are not configured")
        import razorpay
        return razorpay.Client(auth=(self.key_id, self.key_secret)).refund.fetch(refund_id)

    def fetch_settlements(self, payment_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Use Razorpay settlement reports for this MVP")

    def normalize_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "razorpay", "provider_payment_id": payload["id"],
                "provider_order_id": payload.get("order_id"),
                "amount": str(Decimal(payload["amount"]) / 100),
                "currency": payload.get("currency", "INR"), "status": payload["status"],
                "method": payload.get("method"), "captured": payload.get("captured", False),
                "raw_data": payload}

    def normalize_refund(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "razorpay", "provider_refund_id": payload["id"],
                "provider_payment_id": payload["payment_id"],
                "amount": str(Decimal(payload["amount"]) / 100),
                "status": payload["status"], "raw_data": payload}

    def normalize_settlement(self, payload: dict[str, Any]) -> dict[str, Any]:
        gross = Decimal(payload["amount"]) / 100
        fee = Decimal(payload.get("fees", 0)) / 100
        tax = Decimal(payload.get("tax", 0)) / 100
        net = gross - fee - tax
        created_at = payload.get("created_at")
        if isinstance(created_at, (int, float)):
            created_at = datetime.fromtimestamp(created_at, tz=timezone.utc)
        return {"provider": "razorpay", "provider_settlement_id": payload["id"],
                "provider_payment_id": payload.get("payment_id", ""),
                "gross_amount": str(gross),
                "fee": str(fee),
                "tax": str(tax),
                "net_amount": str(net),
                "status": payload.get("status", "processed"),
                "settled_at": created_at, "raw_data": payload}
