from __future__ import annotations
from datetime import datetime, timedelta, timezone
from app.models import DataConnector
from app.security.mfa import decrypt_secret, encrypt_secret
from app.providers.razorpay_connector import RazorpayConnector
from app.ingestion import ingest_records

SUPPORTED_CONNECTORS = {"razorpay"}

def connector_credentials(connector: DataConnector) -> dict:
    if not connector.credentials_enc:
        raise ValueError("Connector credentials are not configured")
    import json
    return json.loads(decrypt_secret(connector.credentials_enc))

def save_credentials(connector: DataConnector, credentials: dict) -> None:
    import json
    connector.credentials_enc = encrypt_secret(json.dumps(credentials, separators=(",", ":")))

def sync_razorpay(session, connector: DataConnector, *, days: int = 7) -> dict:
    creds = connector_credentials(connector)
    adapter = RazorpayConnector(creds["key_id"], creds["key_secret"])
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, min(days, 31)))
    payments_total = refunds_total = settlements_total = 0
    cursor = start
    while cursor <= now:
        items = adapter.fetch_combined_recon(cursor.year, cursor.month, cursor.day)
        payments, refunds, settlements = adapter.normalize_combined(items)
        if payments:
            ingest_records(session, [dict(x, merchant_id=connector.merchant_id) for x in payments], source="razorpay_api", record_type="payment", provider="razorpay", merchant_id=connector.merchant_id, commit=False)
        if refunds:
            ingest_records(session, [dict(x, merchant_id=connector.merchant_id) for x in refunds], source="razorpay_api", record_type="refund", provider="razorpay", merchant_id=connector.merchant_id, commit=False)
        if settlements:
            ingest_records(session, [dict(x, merchant_id=connector.merchant_id) for x in settlements], source="razorpay_api", record_type="settlement", provider="razorpay", merchant_id=connector.merchant_id, commit=False)
        payments_total += len(payments); refunds_total += len(refunds); settlements_total += len(settlements)
        cursor += timedelta(days=1)
    return {"provider":"razorpay","days":days,"payments_seen":payments_total,"refunds_seen":refunds_total,"settlement_lines_seen":settlements_total}
