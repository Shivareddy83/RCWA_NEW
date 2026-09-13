from decimal import Decimal
from app.core.config import settings
from .codes import CASE_TO_CODE

CRITICAL_CODES = {"SETTLEMENT_WITHOUT_PAYMENT", "PAYMENT_NOT_SETTLED", "REFUND_WITHOUT_PAYMENT", "BANK_WITHOUT_SETTLEMENT"}
HIGH_CODES = {"BANK_SETTLEMENT_MISMATCH", "BANK_AMBIGUOUS_MATCH", "AMOUNT_MISMATCH", "STATUS_MISMATCH", "DUPLICATE_PAYMENT", "DUPLICATE_REFUND", "DUPLICATE_SETTLEMENT", "AMBIGUOUS_MATCH", "DELAYED_SETTLEMENT"}

def severity_for(code: str, difference: Decimal = Decimal("0")) -> str:
    if code == "AMOUNT_MISMATCH" and abs(difference) <= Decimal(settings.reconciliation_amount_tolerance):
        return "LOW"
    if code in CRITICAL_CODES:
        return "CRITICAL"
    if code in HIGH_CODES:
        return "HIGH"
    return "MEDIUM"

def code_for_case(case_type: str) -> str:
    return CASE_TO_CODE.get(case_type, "UNKNOWN_REFERENCE")
