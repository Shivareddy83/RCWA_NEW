from __future__ import annotations

from datetime import datetime, timedelta
from bisect import bisect_left, bisect_right
from decimal import Decimal
from typing import Any

from app.models import Payment, Settlement
from app.reconciliation.models import Candidate, MatchConfidence, MatchDecision, MatchMethod
from app.reconciliation.rules import ReconciliationRules


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value.lower() if value else None


def _references(payment: Payment) -> set[str]:
    values = {
        payment.provider_order_id,
        payment.raw_data.get("order_id"),
        payment.raw_data.get("merchant_order_reference"),
        payment.raw_data.get("provider_reference"),
    }
    return {normalized for value in values if (normalized := _normalize(value))}


def _settlement_references(settlement: Settlement) -> set[str]:
    values = {
        settlement.raw_data.get("order_id"),
        settlement.raw_data.get("merchant_order_reference"),
        settlement.raw_data.get("provider_reference"),
        settlement.raw_data.get("settlement_reference"),
    }
    return {normalized for value in values if (normalized := _normalize(value))}


def _payment_bank_references(payment: Payment) -> set[str]:
    values = {
        payment.raw_data.get("utr"),
        payment.raw_data.get("bank_reference"),
        payment.raw_data.get("settlement_reference"),
    }
    return {normalized for value in values if (normalized := _normalize(value))}


def _settlement_bank_references(settlement: Settlement) -> set[str]:
    values = {
        settlement.utr,
        settlement.raw_data.get("utr"),
        settlement.raw_data.get("bank_reference"),
        settlement.raw_data.get("settlement_reference"),
    }
    return {normalized for value in values if (normalized := _normalize(value))}


def _compatible_time(left, right) -> bool:
    if left.tzinfo is not None:
        left = left.astimezone().replace(tzinfo=None)
    if right.tzinfo is not None:
        right = right.astimezone().replace(tzinfo=None)
    return True


def _time_difference(left, right):
    _compatible_time(left, right)
    if left.tzinfo is not None:
        left = left.replace(tzinfo=None)
    if right.tzinfo is not None:
        right = right.replace(tzinfo=None)
    return abs(left - right)


def _candidate(item: Settlement) -> Candidate:
    return Candidate(
        record_id=item.id,
        record_type="settlement",
        amount=Decimal(item.net_amount),
        currency=str(item.raw_data.get("currency", "INR")).upper(),
        timestamp=item.settled_at,
    )


def build_settlement_indexes(settlements: list[Settlement]) -> dict:
    """Build provider/reference indexes once per reconciliation run.

    Exact-reference matching becomes O(1), and amount/time matching only scans
    the small time-window slice for the payment's provider instead of every
    settlement.
    """
    by_provider: dict[str, list[Settlement]] = {}
    by_payment_id: dict[tuple[str, str], list[Settlement]] = {}
    by_order_ref: dict[tuple[str, str], list[Settlement]] = {}
    by_bank_ref: dict[tuple[str, str], list[Settlement]] = {}
    by_time: dict[str, list[tuple[datetime, Settlement]]] = {}

    for item in settlements:
        provider = str(item.provider or "").lower()
        by_provider.setdefault(provider, []).append(item)
        pid = _normalize(item.provider_payment_id)
        if pid:
            by_payment_id.setdefault((provider, pid), []).append(item)
        for ref in _settlement_references(item):
            by_order_ref.setdefault((provider, ref), []).append(item)
        for ref in _settlement_bank_references(item):
            by_bank_ref.setdefault((provider, ref), []).append(item)
        dt = item.settled_at
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        by_time.setdefault(provider, []).append((dt, item))

    for values in by_time.values():
        values.sort(key=lambda x: x[0])
    return {
        "by_provider": by_provider,
        "by_payment_id": by_payment_id,
        "by_order_ref": by_order_ref,
        "by_bank_ref": by_bank_ref,
        "by_time": by_time,
    }


def match_payment_to_settlement(
    payment: Payment,
    settlements: list[Settlement],
    rules: ReconciliationRules,
    indexes: dict | None = None,
) -> MatchDecision:
    if indexes is None:
        indexes = build_settlement_indexes(settlements)

    provider = str(payment.provider or "").lower()
    candidates = indexes["by_provider"].get(provider, [])
    if not candidates:
        return MatchDecision(False, reason="No settlement candidates for the payment provider.")

    payment_id = _normalize(payment.provider_payment_id)
    exact = indexes["by_payment_id"].get((provider, payment_id), []) if payment_id else []
    if len(exact) == 1:
        return MatchDecision(True, MatchMethod.EXACT_PAYMENT_ID, MatchConfidence.HIGH,
                             "Payment and settlement share the same provider payment ID.", exact[0].id)
    if len(exact) > 1:
        return MatchDecision(False, MatchMethod.EXACT_PAYMENT_ID, MatchConfidence.NONE,
                             "Multiple settlements share the same provider payment ID.",
                             candidates=tuple(_candidate(item) for item in exact))

    order_refs = _references(payment)
    order_matches_map = {}
    for ref in order_refs:
        for item in indexes["by_order_ref"].get((provider, ref), []):
            order_matches_map[item.id] = item
    order_matches = list(order_matches_map.values())
    if len(order_matches) == 1:
        return MatchDecision(True, MatchMethod.ORDER_REFERENCE, MatchConfidence.HIGH,
                             "A normalized order/provider reference uniquely identifies the settlement.", order_matches[0].id)
    if len(order_matches) > 1:
        return MatchDecision(False, MatchMethod.ORDER_REFERENCE, MatchConfidence.NONE,
                             "Multiple settlements match the payment order/reference.",
                             candidates=tuple(_candidate(item) for item in order_matches))

    bank_refs = _payment_bank_references(payment)
    bank_matches_map = {}
    for ref in bank_refs:
        for item in indexes["by_bank_ref"].get((provider, ref), []):
            bank_matches_map[item.id] = item
    bank_matches = list(bank_matches_map.values())
    if len(bank_matches) == 1:
        return MatchDecision(True, MatchMethod.UTR_REFERENCE, MatchConfidence.HIGH,
                             "A normalized UTR/bank/settlement reference uniquely identifies the settlement.", bank_matches[0].id)
    if len(bank_matches) > 1:
        return MatchDecision(False, MatchMethod.UTR_REFERENCE, MatchConfidence.NONE,
                             "Multiple settlements match the payment bank reference.",
                             candidates=tuple(_candidate(item) for item in bank_matches))

    window = timedelta(minutes=rules.timestamp_tolerance_minutes)
    payment_dt = payment.created_at
    if payment_dt.tzinfo is not None:
        payment_dt = payment_dt.astimezone().replace(tzinfo=None)
    start_dt = payment_dt - window
    end_dt = payment_dt + window
    timed = indexes["by_time"].get(provider, [])
    time_keys = [entry[0] for entry in timed]
    lo = bisect_left(time_keys, start_dt) if timed else 0
    hi = bisect_right(time_keys, end_dt) if timed else 0
    amount_matches = []
    for _, item in timed[lo:hi]:
        currency = str(item.raw_data.get("currency", payment.currency)).upper()
        if currency != str(payment.currency).upper():
            continue
        amount = Decimal(item.net_amount)
        if abs(amount - Decimal(payment.amount)) <= rules.amount_tolerance:
            amount_matches.append(item)
    if len(amount_matches) == 1:
        method = MatchMethod.TOLERANCE_MATCH if rules.amount_tolerance else MatchMethod.AMOUNT_CURRENCY_TIME
        reason = "Settlement matches currency, amount tolerance, and configured timestamp tolerance."
        return MatchDecision(True, method, MatchConfidence.MEDIUM, reason, amount_matches[0].id)
    if len(amount_matches) > 1:
        return MatchDecision(False, MatchMethod.AMOUNT_CURRENCY_TIME, MatchConfidence.NONE,
                             "Multiple settlements satisfy the amount, currency, and time-window rule.",
                             candidates=tuple(_candidate(item) for item in amount_matches))

    return MatchDecision(False, reason="No deterministic matching rule produced a unique settlement.")

