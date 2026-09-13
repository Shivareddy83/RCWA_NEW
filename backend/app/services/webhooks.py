import hashlib
import ipaddress
import json
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from app.core.config import settings
from app.core.time import utc_now
from app.models import WebhookEvent, BillingSubscription, BillingInvoice
from app.providers.razorpay import RazorpayProvider
from app.repositories.webhooks import get_event
from app.ingestion import ingest_provider_payload, IngestionValidationError
from app.audit import record_event
from app.audit.actions import BILLING_PROVIDER_WEBHOOK_PROCESSED, BILLING_SUBSCRIPTION_STATUS_CHANGED, BILLING_INVOICE_PAID, BILLING_PAYMENT_FAILED
from app.services.notifications import create_notification


def _dt_from_epoch(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _subscription_event(session, event_type: str, payload: dict) -> tuple[dict, bool]:
    sub_entity = ((payload.get("payload") or {}).get("subscription") or {}).get("entity") or {}
    subscription_id = sub_entity.get("id")
    if not subscription_id:
        return {"status": "ignored", "reason": "missing subscription entity"}, True
    sub = session.scalar(select(BillingSubscription).where(BillingSubscription.provider == "RAZORPAY", BillingSubscription.provider_subscription_id == subscription_id))
    if not sub:
        return {"status": "ignored", "reason": "unknown subscription"}, True

    old_status = sub.status
    provider_status = sub_entity.get("status")
    previous_provider_status = getattr(sub, "provider_status", None)
    event_created_at = _dt_from_epoch(payload.get("created_at"))
    previous_event_created_at = getattr(sub, "provider_event_created_at", None)
    if previous_event_created_at and previous_event_created_at.tzinfo is None:
        previous_event_created_at = previous_event_created_at.replace(tzinfo=timezone.utc)
    status_map = {
        "authenticated": "PENDING_ACTIVATION",
        "active": "ACTIVE",
        "pending": "PAST_DUE",
        "halted": "PAST_DUE",
        "cancelled": "CANCELLED",
        "completed": "CANCELLED",
        "expired": "CANCELLED",
        "created": "PENDING_ACTIVATION",
    }
    should_apply_status = provider_status in status_map and (not event_created_at or not previous_event_created_at or event_created_at >= previous_event_created_at)
    if should_apply_status:
        sub.status = status_map[provider_status]
        sub.provider_status = provider_status
        if event_created_at:
            sub.provider_event_created_at = event_created_at
    if sub_entity.get("customer_id"):
        sub.provider_customer_id = sub_entity["customer_id"]
    if sub_entity.get("plan_id"):
        sub.provider_plan_id = sub_entity["plan_id"]
    if sub_entity.get("current_start"):
        sub.current_period_start = _dt_from_epoch(sub_entity["current_start"]) or sub.current_period_start
    if sub_entity.get("current_end"):
        sub.current_period_end = _dt_from_epoch(sub_entity["current_end"]) or sub.current_period_end
    if event_type == "subscription.cancelled":
        sub.cancel_at_period_end = True

    payment_entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    if payment_entity.get("id"):
        sub.last_payment_id = payment_entity["id"]

    if event_type in {"subscription.charged", "subscription.completed"} and payment_entity.get("status") == "captured":
        provider_invoice_id = payment_entity.get("invoice_id")
        invoice = None
        if provider_invoice_id:
            invoice = session.scalar(select(BillingInvoice).where(BillingInvoice.provider_invoice_id == provider_invoice_id))
        if not invoice:
            invoice = session.scalar(select(BillingInvoice).where(BillingInvoice.subscription_id == sub.id, BillingInvoice.status != "PAID").order_by(BillingInvoice.issued_at.desc()))
        if not invoice:
            now = utc_now()
            from app.billing import next_invoice_number
            amount = Decimal(payment_entity.get("amount", 0)) / Decimal(100)
            invoice = BillingInvoice(merchant_id=sub.merchant_id, subscription_id=sub.id, invoice_number=next_invoice_number(session, sub.merchant_id), status="PENDING", currency=payment_entity.get("currency", "INR"), subtotal=amount, tax=Decimal("0.00"), total=amount, issued_at=now, due_at=now, provider="RAZORPAY")
            session.add(invoice)
            session.flush()
        invoice.status = "PAID"
        invoice.paid_at = utc_now()
        invoice.provider = "RAZORPAY"
        invoice.provider_invoice_id = provider_invoice_id or invoice.provider_invoice_id
        invoice.provider_payment_id = payment_entity.get("id") or invoice.provider_payment_id
        sub.status = "ACTIVE"
        record_event(session, action=BILLING_INVOICE_PAID, resource_type="BILLING_INVOICE", resource_id=invoice.id, merchant_id=sub.merchant_id, actor_type="SYSTEM_GLOBAL", after_snapshot={"status":"PAID","provider":"RAZORPAY","provider_payment_id":invoice.provider_payment_id})
        create_notification(session, merchant_id=sub.merchant_id, user_id=None, kind="BILLING", title="RCAA subscription payment received", message=f"Your {sub.plan_code.title()} subscription payment was received successfully.", resource_type="BILLING_INVOICE", resource_id=invoice.id, severity="INFO")
    elif event_type in {"subscription.pending", "subscription.halted"}:
        create_notification(session, merchant_id=sub.merchant_id, user_id=None, kind="BILLING", title="RCAA subscription payment needs attention", message="Your recurring billing payment needs attention. Please update the payment method in Razorpay.", resource_type="BILLING_SUBSCRIPTION", resource_id=sub.id, severity="WARNING")
        record_event(session, action=BILLING_PAYMENT_FAILED, resource_type="BILLING_SUBSCRIPTION", resource_id=sub.id, merchant_id=sub.merchant_id, actor_type="SYSTEM_GLOBAL", outcome="FAILURE", after_snapshot={"provider_status":provider_status})

    if old_status != sub.status:
        record_event(session, action=BILLING_SUBSCRIPTION_STATUS_CHANGED, resource_type="BILLING_SUBSCRIPTION", resource_id=sub.id, merchant_id=sub.merchant_id, actor_type="SYSTEM_GLOBAL", after_snapshot={"from":old_status,"to":sub.status,"provider_status":provider_status})
    session.flush()
    return {"status":"processed","subscription_id":sub.id,"subscription_status":sub.status}, True


def process_razorpay_webhook(session, raw: bytes, signature: str | None, event_id: str | None, client_ip: str | None = None):
    if not signature or not settings.razorpay_webhook_secret:
        return None, False
    allowed_ips = getattr(settings, "razorpay_webhook_allowed_ips", ())
    if allowed_ips:
        try:
            source_ip = ipaddress.ip_address(client_ip or "")
            networks = [ipaddress.ip_network(value, strict=False) for value in allowed_ips]
        except ValueError:
            return None, False
        if not any(source_ip in network for network in networks):
            return None, False

    provider = RazorpayProvider(settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret)
    if not provider.verify_webhook(raw, signature):
        return None, False

    payload = json.loads(raw)
    resolved_event_id = event_id or payload.get("event_id") or hashlib.sha256(raw).hexdigest()
    if get_event(session, "razorpay", resolved_event_id):
        return {"status": "duplicate"}, True

    event_type = payload.get("event", "unknown")
    if event_type.startswith("subscription."):
        result, valid = _subscription_event(session, event_type, payload)
        session.add(WebhookEvent(provider="razorpay", event_id=resolved_event_id, event_type=event_type, signature_valid=True, processed=True, processed_at=utc_now(), payload={"event": event_type, "event_id": resolved_event_id}))
        if valid:
            record_event(session, action=BILLING_PROVIDER_WEBHOOK_PROCESSED, resource_type="BILLING_PROVIDER_WEBHOOK", resource_id=resolved_event_id, merchant_id=None, actor_type="SYSTEM_GLOBAL", metadata={"event_type":event_type,"status":result.get("status")})
        session.commit()
        return result, True

    entity = ((payload.get("payload") or {}).get("payment") or (payload.get("payload") or {}).get("refund") or (payload.get("payload") or {}).get("settlement") or {}).get("entity")
    try:
        if entity and event_type.startswith("payment."):
            ingest_provider_payload(session, provider, [entity], record_type="payment", source="razorpay_webhook")
        elif entity and event_type.startswith("refund."):
            ingest_provider_payload(session, provider, [entity], record_type="refund", source="razorpay_webhook")
        elif entity and event_type.startswith("settlement."):
            ingest_provider_payload(session, provider, [entity], record_type="settlement", source="razorpay_webhook")
    except (IngestionValidationError, KeyError) as exc:
        session.rollback()
        return {"status": "rejected", "error": str(exc)}, True

    session.add(WebhookEvent(provider="razorpay", event_id=resolved_event_id, event_type=event_type, signature_valid=True, processed=True, processed_at=utc_now(), payload={"event": event_type, "event_id": resolved_event_id}))
    session.commit()
    return {"status": "processed"}, True
