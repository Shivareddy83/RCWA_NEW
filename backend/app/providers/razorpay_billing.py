from __future__ import annotations
import hashlib
import hmac
import re
from typing import Any
import httpx
from app.core.config import settings

BASE_URL = "https://api.razorpay.com/v1"

class RazorpayBillingError(RuntimeError):
    pass

class RazorpayBillingProvider:
    def __init__(self, key_id: str | None = None, key_secret: str | None = None):
        self.key_id = key_id or settings.razorpay_key_id
        self.key_secret = key_secret or settings.razorpay_key_secret
        if not self.key_id or not self.key_secret:
            raise RazorpayBillingError("Razorpay billing credentials are not configured")

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = httpx.request(method, f"{BASE_URL}{path}", auth=(self.key_id, self.key_secret), json=payload, timeout=20.0)
        except httpx.HTTPError as exc:
            raise RazorpayBillingError("Unable to reach Razorpay") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("description", "Razorpay request failed")
            except Exception:
                detail = "Razorpay request failed"
            raise RazorpayBillingError(str(detail))
        return response.json()

    def create_subscription(self, *, plan_id: str, merchant_id: str, total_count: int = 1200) -> dict[str, Any]:
        if not re.fullmatch(r"plan_[A-Za-z0-9]{14}", plan_id):
            raise RazorpayBillingError("Invalid Razorpay plan ID format")
        if total_count < 1:
            raise RazorpayBillingError("Razorpay total_count must be at least 1")
        return self._request("POST", "/subscriptions", {
            "plan_id": plan_id,
            "total_count": total_count,
            "quantity": 1,
            "customer_notify": True,
            "notes": {"rcaa_merchant_id": merchant_id},
        })

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/subscriptions/{subscription_id}")

    def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool = True) -> dict[str, Any]:
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {"cancel_at_cycle_end": at_cycle_end})

    @staticmethod
    def verify_checkout_signature(payment_id: str, subscription_id: str, signature: str, *, secret: str | None = None) -> bool:
        if not payment_id or not subscription_id or not signature:
            return False
        signing_secret = secret or settings.razorpay_key_secret
        if not signing_secret:
            return False
        expected = hmac.new(signing_secret.encode(), f"{payment_id}|{subscription_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def plan_id(plan_code: str) -> str:
        mapping = {
            "STARTER": settings.razorpay_plan_starter,
            "GROWTH": settings.razorpay_plan_growth,
            "BUSINESS": settings.razorpay_plan_business,
        }
        value = mapping.get(plan_code, "")
        if not value:
            raise RazorpayBillingError(f"Razorpay plan is not configured for {plan_code}")
        return value
