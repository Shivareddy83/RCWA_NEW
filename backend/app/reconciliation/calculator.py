from __future__ import annotations

from decimal import Decimal

from app.models import Payment, Refund, Settlement


def calculate_expected_settlement(
    payment: Payment,
    refunds: list[Refund],
    settlements: list[Settlement],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    gross = Decimal(payment.amount)
    refund_amount = sum(
        (Decimal(item.amount) for item in refunds if item.status in {"processed", "created"}),
        Decimal("0"),
    )
    fees = sum((Decimal(item.fee) for item in settlements), Decimal("0"))
    tax = sum((Decimal(item.tax) for item in settlements), Decimal("0"))
    adjustments = sum(
        (Decimal(str(item.raw_data.get("adjustment", "0"))) for item in settlements),
        Decimal("0"),
    )
    expected = gross - refund_amount - fees - tax + adjustments
    actual = sum((Decimal(item.net_amount) for item in settlements), Decimal("0"))
    difference = actual - expected
    return gross, refund_amount, fees, tax, expected, actual, difference
