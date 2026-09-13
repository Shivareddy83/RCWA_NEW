from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
import httpx

class RazorpayConnector:
    provider_name = "razorpay"
    base_url = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str):
        if not key_id or not key_secret:
            raise ValueError("Razorpay connector credentials are required")
        self.auth = (key_id, key_secret)

    def _get(self, path: str, params: dict):
        with httpx.Client(base_url=self.base_url, auth=self.auth, timeout=30.0) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def fetch_combined_recon(self, year: int, month: int, day: int | None = None, skip: int = 0, count: int = 1000) -> list[dict]:
        params = {"year": year, "month": month, "skip": skip, "count": min(max(count, 1), 1000)}
        if day is not None:
            params["day"] = day
        items: list[dict] = []
        while True:
            payload = self._get("/settlements/recon/combined", params)
            page = payload.get("items", [])
            items.extend(page)
            if len(page) < params["count"]:
                break
            params["skip"] += params["count"]
        return items

    def fetch_settlements(self, start: datetime, end: datetime) -> list[dict]:
        params = {"from": int(start.timestamp()), "to": int(end.timestamp()), "count": 100, "skip": 0}
        items: list[dict] = []
        while True:
            payload = self._get("/settlements/", params)
            page = payload.get("items", [])
            items.extend(page)
            if len(page) < params["count"]:
                break
            params["skip"] += params["count"]
        return items

    @staticmethod
    def normalize_combined(items: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        payments: list[dict] = []
        refunds: list[dict] = []
        settlements: list[dict] = []
        for row in items:
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_id:
                continue
            typ = str(row.get("type") or "").lower()
            created = row.get("created_at")
            settled = row.get("settled_at") or created
            created_dt = datetime.fromtimestamp(created, tz=timezone.utc) if isinstance(created, (int, float)) else None
            settled_dt = datetime.fromtimestamp(settled, tz=timezone.utc) if isinstance(settled, (int, float)) else created_dt
            currency = str(row.get("currency") or "INR").upper()
            amount = Decimal(str(row.get("amount") or 0)) / 100
            fee = Decimal(str(row.get("fee") or 0)) / 100
            tax = Decimal(str(row.get("tax") or 0)) / 100
            if typ == "payment":
                payments.append({"provider":"razorpay","external_id":entity_id,"provider_payment_id":entity_id,"provider_order_id":row.get("order_id"),"amount":amount,"currency":currency,"status":"captured" if row.get("settled") else "created","event_timestamp":created_dt or settled_dt,"metadata":row})
                settlements.append({"provider":"razorpay","external_id":f"{row.get('settlement_id') or 'unknown'}:{entity_id}","provider_settlement_id":f"{row.get('settlement_id') or 'unknown'}:{entity_id}","provider_payment_id":entity_id,"gross_amount":amount,"fee":fee,"tax":tax,"net_amount":amount-fee-tax,"currency":currency,"status":"processed" if row.get("settled") else "pending","event_timestamp":settled_dt or created_dt,"utr":row.get("settlement_utr"),"metadata":{**row,"settlement_group_id":row.get("settlement_id")}})
            elif typ == "refund":
                payment_id = str(row.get("payment_id") or "")
                refunds.append({"provider":"razorpay","external_id":entity_id,"provider_refund_id":entity_id,"provider_payment_id":payment_id,"amount":amount,"currency":currency,"status":"processed" if row.get("settled") else "created","event_timestamp":created_dt or settled_dt,"metadata":row})
        return payments, refunds, settlements
