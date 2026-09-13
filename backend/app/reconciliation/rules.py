from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings


@dataclass(frozen=True)
class ReconciliationRules:
    settlement_window_days: int
    timestamp_tolerance_minutes: int
    amount_tolerance: Decimal
    timezone: str


rules = ReconciliationRules(
    settlement_window_days=settings.settlement_window_days,
    timestamp_tolerance_minutes=settings.reconciliation_timestamp_tolerance_minutes,
    amount_tolerance=Decimal(settings.reconciliation_amount_tolerance),
    timezone=settings.reconciliation_timezone,
)
