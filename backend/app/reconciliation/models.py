from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class MatchMethod(str, Enum):
    EXACT_PAYMENT_ID = "EXACT_PAYMENT_ID"
    ORDER_REFERENCE = "ORDER_REFERENCE"
    UTR_REFERENCE = "UTR_REFERENCE"
    AMOUNT_CURRENCY_TIME = "AMOUNT_CURRENCY_TIME"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    NONE = "NONE"


class MatchConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


@dataclass(frozen=True)
class Candidate:
    record_id: str
    record_type: str
    amount: Decimal
    currency: str
    timestamp: Any


@dataclass(frozen=True)
class MatchDecision:
    matched: bool
    method: MatchMethod = MatchMethod.NONE
    confidence: MatchConfidence = MatchConfidence.NONE
    reason: str = ""
    matched_record_id: str | None = None
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReconciliationResult:
    record_id: str
    record_type: str
    status: str
    match_method: str
    match_confidence: str
    matched_record_id: str | None
    expected_amount: Decimal
    actual_amount: Decimal
    difference: Decimal
    currency: str
    reason_code: str
    explanation: str
    metadata: dict[str, Any] = field(default_factory=dict)
