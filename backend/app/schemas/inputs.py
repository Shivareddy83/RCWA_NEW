from decimal import Decimal
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class PaymentIn(BaseModel):
    provider: str = "demo"
    provider_payment_id: str
    provider_order_id: Optional[str] = None
    amount: Decimal = Field(gt=0)
    currency: str = "INR"
    status: str = "captured"
    method: Optional[str] = "card"
    captured: bool = True
    raw_data: dict = {}

class RefundIn(BaseModel):
    provider: str = "demo"
    provider_refund_id: str
    provider_payment_id: str
    amount: Decimal = Field(gt=0)
    status: str = "processed"
    raw_data: dict = {}

class SettlementIn(BaseModel):
    provider: str = "demo"
    provider_settlement_id: str
    provider_payment_id: str
    gross_amount: Decimal
    fee: Decimal = 0
    tax: Decimal = 0
    net_amount: Decimal
    status: str = "processed"
    settled_at: datetime
    utr: Optional[str] = None
    raw_data: dict = {}
