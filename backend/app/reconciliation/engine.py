from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from time import monotonic
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BankTransaction, Payment, Refund, Settlement
from app.rca.service import create_case
from app.reconciliation.calculator import calculate_expected_settlement
from app.reconciliation.matcher import build_settlement_indexes, match_payment_to_settlement
from app.reconciliation.models import MatchConfidence, MatchMethod
from app.reconciliation.rules import rules
from app.observability.metrics import inc, observe


def _currency(record) -> str:
    return str(record.currency if hasattr(record, "currency") else record.raw_data.get("currency", "INR")).upper()


def _stable_record_key(provider: str, provider_id: str | None) -> str:
    return f"{provider}:{provider_id or 'missing'}"


def _case(session, *, payment, record, case_type, reason_code, expected, actual, summary,
          explanation, action, match_method=MatchMethod.NONE.value,
          match_confidence=MatchConfidence.NONE.value, matched_record_id=None, metadata=None):
    return create_case(
        session,
        payment,
        case_type,
        expected,
        actual,
        summary,
        explanation,
        reason_code,
        action,
        record_id=getattr(record, "id", None),
        record_type="payment" if payment else ("settlement" if isinstance(record, Settlement) else "refund"),
        match_method=match_method,
        match_confidence=match_confidence,
        matched_record_id=matched_record_id,
        metadata=metadata or {},
    )


def run_reconciliation(session: Session, *, return_report: bool = False, merchant_id: str | None = None) -> int | dict:
    run_id = str(uuid4())
    started = monotonic()
    inc("reconciliation_runs_total")
    payments_stmt = select(Payment).order_by(Payment.created_at, Payment.id)
    refunds_stmt = select(Refund).order_by(Refund.created_at, Refund.id)
    settlements_stmt = select(Settlement).order_by(Settlement.settled_at, Settlement.id)
    if merchant_id:
        payments_stmt = payments_stmt.where(Payment.merchant_id == merchant_id)
        refunds_stmt = refunds_stmt.where((Refund.merchant_id == merchant_id) | Refund.payment_id.in_(select(Payment.id).where(Payment.merchant_id == merchant_id)))
        settlements_stmt = settlements_stmt.where((Settlement.merchant_id == merchant_id) | Settlement.payment_id.in_(select(Payment.id).where(Payment.merchant_id == merchant_id)))
    payments = session.scalars(payments_stmt).all()
    refunds = session.scalars(refunds_stmt).all()
    settlements = session.scalars(settlements_stmt).all()

    refunds_by_payment = defaultdict(list)
    settlements_by_payment = defaultdict(list)
    payments_by_order = defaultdict(list)
    for refund in refunds:
        refunds_by_payment[(refund.provider, _normalize(refund.provider_payment_id))].append(refund)
    for settlement in settlements:
        settlements_by_payment[(settlement.provider, _normalize(settlement.provider_payment_id))].append(settlement)
    for payment in payments:
        if payment.provider_order_id:
            payments_by_order[(payment.provider, _normalize(payment.provider_order_id))].append(payment)

    settlement_indexes = build_settlement_indexes(settlements)
    matched_settlements: set[str] = set()
    matched_refunds: set[str] = set()
    created = 0
    stats = {"matched": 0, "unmatched": 0, "ambiguous": 0, "mismatch": 0, "delayed": 0, "duplicates": 0, "bank_matched": 0, "bank_unmatched": 0, "bank_mismatch": 0, "bank_ambiguous": 0}

    # Exact duplicate settlement source rows are identified by all normalized financial
    # fields plus timestamp. Equal amounts alone are never treated as duplicates.
    duplicate_settlement_groups = defaultdict(list)
    for settlement in settlements:
        key = (
            settlement.provider, settlement.provider_payment_id, settlement.gross_amount,
            settlement.fee, settlement.tax, settlement.net_amount, settlement.status,
            settlement.settled_at, settlement.utr, _currency(settlement),
        )
        duplicate_settlement_groups[key].append(settlement)
    for group in duplicate_settlement_groups.values():
        if len(group) > 1:
            stats["duplicates"] += 1
            created += int(_case(
                session, payment=None, record=group[0], case_type="DUPLICATE_SETTLEMENT",
                reason_code="DUPLICATE_SETTLEMENT", expected=group[0].net_amount,
                actual=sum((item.net_amount for item in group), Decimal("0")),
                summary="Identical settlement source records were ingested more than once.",
                explanation="The settlement rows have identical provider, payment reference, financial values, status, timestamp, UTR, and currency.",
                action="Deduplicate the settlement source and verify the provider settlement export.",
                metadata={"candidate_ids": [item.id for item in group]},
            ))

    for payment in payments:
        payment_refunds = refunds_by_payment[(payment.provider, _normalize(payment.provider_payment_id))]
        payment_settlements = settlements_by_payment[(payment.provider, _normalize(payment.provider_payment_id))]

        duplicate_orders = payments_by_order.get((payment.provider, _normalize(payment.provider_order_id)), []) if payment.provider_order_id else []
        if len(duplicate_orders) > 1:
            created += int(_case(
                session, payment=payment, record=payment, case_type="DUPLICATE_PAYMENT",
                reason_code="DUPLICATE_PAYMENT", expected=payment.amount,
                actual=sum((item.amount for item in duplicate_orders), Decimal("0")),
                summary="Multiple payment records share the same provider order reference.",
                explanation="The provider order reference maps to multiple payment records; this is treated as a duplicate transaction signal, not proof that equal-amount transactions are duplicates.",
                action="Review the provider payment attempts and confirm whether the repeated order reference is legitimate.",
                metadata={"candidate_ids": [item.id for item in duplicate_orders], "rule": "ORDER_REFERENCE"},
            ))
            stats["duplicates"] += 1

        if payment.status not in {"captured", "authorized", "refunded", "partially_refunded"}:
            created += int(_case(
                session, payment=payment, record=payment, case_type="STATUS_MISMATCH",
                reason_code="STATUS_MISMATCH", expected=payment.amount, actual=Decimal("0"),
                summary=f"Payment status is {payment.status}.",
                explanation="Payment status is outside the reconciliable captured/authorized/refunded states supported by this engine.",
                action="Confirm the provider status and local payment state.",
            ))
            stats["mismatch"] += 1

        if len(payment_refunds) > 1:
            # Multiple refunds can be legitimate. Only flag exact duplicate provider references.
            duplicate_refund_groups = defaultdict(list)
            for refund in payment_refunds:
                duplicate_refund_groups[_stable_record_key(refund.provider, refund.provider_refund_id)].append(refund)
            duplicate_groups = [group for group in duplicate_refund_groups.values() if len(group) > 1]
            if duplicate_groups:
                stats["duplicates"] += len(duplicate_groups)
                for group in duplicate_groups:
                    created += int(_case(
                        session, payment=payment, record=group[0], case_type="DUPLICATE_REFUND",
                        reason_code="DUPLICATE_REFUND", expected=group[0].amount,
                        actual=sum((item.amount for item in group), Decimal("0")),
                        summary="The same provider refund reference appears more than once.",
                        explanation="Identical provider refund references indicate duplicate source records.",
                        action="Deduplicate the source import and verify the provider refund ledger.",
                        metadata={"candidate_ids": [item.id for item in group]},
                    ))

        if payment.raw_data.get("expected_refund") and not payment_refunds:
            created += int(_case(
                session, payment=payment, record=payment, case_type="MISSING_REFUND",
                reason_code="REFUND_NOT_SETTLED", expected=payment.amount, actual=Decimal("0"),
                summary="A refund is expected but no refund record was ingested.",
                explanation="The payment source contains an explicit expected_refund flag, but no matching refund record exists.",
                action="Import the provider refund and verify webhook/report delivery.",
            ))
            stats["unmatched"] += 1
            inc("reconciliation_unmatched_total", labels={"match_method": "NONE", "result": "unmatched"})

        # Matching uses pre-built provider/reference/time indexes so reconciliation
        # remains practical as transaction volume grows.
        candidate_settlements = settlement_indexes["by_provider"].get(str(payment.provider or "").lower(), [])
        decision = match_payment_to_settlement(payment, candidate_settlements, rules, settlement_indexes)
        if decision.matched and decision.matched_record_id:
            matched = next(item for item in candidate_settlements if item.id == decision.matched_record_id)
            matched_records = [matched]
            matched_settlements.add(matched.id)
            matched_refunds.update(item.id for item in payment_refunds)
            stats["matched"] += 1
            inc("reconciliation_matches_total", labels={"match_method": decision.method.value, "result": "matched"})
        elif decision.candidates:
            stats["ambiguous"] += 1
            inc("reconciliation_ambiguous_total", labels={"match_method": decision.method.value, "result": "ambiguous"})
            created += int(_case(
                session, payment=payment, record=payment, case_type="AMBIGUOUS_MATCH",
                reason_code="AMBIGUOUS_MATCH", expected=payment.amount, actual=Decimal("0"),
                summary="Multiple settlement candidates satisfy a deterministic matching rule.",
                explanation=decision.reason,
                action="Review the candidate settlement records; do not select one automatically.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
                metadata={"candidate_ids": [item.record_id for item in decision.candidates], "candidates": [{"record_id": item.record_id, "record_type": item.record_type, "amount": str(item.amount), "currency": item.currency, "timestamp": item.timestamp.isoformat() if hasattr(item.timestamp, "isoformat") else str(item.timestamp)} for item in decision.candidates]},
            ))
            continue
        else:
            stats["unmatched"] += 1
            inc("reconciliation_unmatched_total", labels={"match_method": decision.method.value, "result": "unmatched"})
            created += int(_case(
                session, payment=payment, record=payment, case_type="PAYMENT_WITHOUT_SETTLEMENT",
                reason_code="PAYMENT_NOT_SETTLED", expected=payment.amount, actual=Decimal("0"),
                summary="No unique settlement was found for the payment.",
                explanation=decision.reason or "No settlement matched the configured deterministic rules.",
                action="Check settlement exports and provider references.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
            ))
            continue

        gross, refunded, fees, tax, expected, actual, difference = calculate_expected_settlement(payment, payment_refunds, [matched])
        if matched.status.lower() not in {"settled", "processed", "success", "paid"}:
            created += int(_case(
                session, payment=payment, record=matched, case_type="STATUS_MISMATCH",
                reason_code="STATUS_MISMATCH", expected=expected, actual=actual,
                summary=f"Settlement status is {matched.status}.",
                explanation="The matched settlement has a non-final status and cannot be treated as a completed settlement.",
                action="Confirm settlement status with the provider before considering the payment fully settled.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
                matched_record_id=matched.id,
            ))
            stats["mismatch"] += 1
            inc("reconciliation_mismatches_total", labels={"match_method": decision.method.value, "result": "mismatch"})

        currency_mismatch = _currency(matched) != _currency(payment)
        if currency_mismatch:
            created += int(_case(
                session, payment=payment, record=matched, case_type="CURRENCY_MISMATCH",
                reason_code="CURRENCY_MISMATCH", expected=expected, actual=actual,
                summary="Payment and settlement currencies do not match.",
                explanation=f"Payment currency is {_currency(payment)} while settlement currency is {_currency(matched)}.",
                action="Verify the source currency and normalization before treating the records as financially matched.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
                matched_record_id=matched.id,
                metadata={"gross": str(gross), "refunds": str(refunded), "fees": str(fees), "tax": str(tax)},
            ))
            stats["mismatch"] += 1

        settlement_time = matched.settled_at.replace(tzinfo=None) if matched.settled_at.tzinfo else matched.settled_at
        payment_time = payment.created_at.replace(tzinfo=None) if payment.created_at.tzinfo else payment.created_at
        if settlement_time > payment_time + rules_window():
            stats["delayed"] += 1
            created += int(_case(
                session, payment=payment, record=matched, case_type="DELAYED_SETTLEMENT",
                reason_code="DELAYED_SETTLEMENT", expected=expected, actual=actual,
                summary="Settlement exceeded the configured settlement window.",
                explanation=f"Settlement occurred after the configured {settings.settlement_window_days}-day window.",
                action="Check bank/processor settlement status and settlement timing.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
                matched_record_id=matched.id,
                metadata={"settled_at": matched.settled_at.isoformat(), "payment_created_at": payment.created_at.isoformat()},
            ))

        if difference != 0:
            stats["mismatch"] += 1
            reason = "REFUND_SETTLEMENT_ADJUSTMENT" if refunded else "AMOUNT_MISMATCH"
            created += int(_case(
                session, payment=payment, record=matched, case_type="SETTLEMENT_MISMATCH",
                reason_code=reason, expected=expected, actual=actual,
                summary=f"Expected net settlement {expected}; received {actual}.",
                explanation="Gross amount, refunds, fees, tax, adjustments, and actual settlement amount do not reconcile.",
                action="Reconcile provider settlement line items and verify fee/tax/refund records.",
                match_method=decision.method.value, match_confidence=decision.confidence.value,
                matched_record_id=matched.id,
                metadata={"gross": str(gross), "refunds": str(refunded), "fees": str(fees), "tax": str(tax), "difference": str(difference)},
            ))

    payment_ids = {p.id for p in payments}
    for settlement in settlements:
        if settlement.id in matched_settlements:
            continue
        linked_payment = session.get(Payment, settlement.payment_id) if settlement.payment_id else None
        if linked_payment is None and settlement.provider_payment_id:
            linked_payment = session.scalar(select(Payment).where(
                Payment.provider == settlement.provider,
                Payment.provider_payment_id == settlement.provider_payment_id,
            ))
        if linked_payment is None:
            created += int(_case(
                session, payment=None, record=settlement, case_type="SETTLEMENT_WITHOUT_PAYMENT",
                reason_code="SETTLEMENT_WITHOUT_PAYMENT", expected=Decimal("0"), actual=settlement.net_amount,
                summary="Settlement record has no matching payment.",
                explanation="The settlement could not be linked to a known payment using the deterministic matching hierarchy.",
                action="Verify the settlement reference and payment import.",
                metadata={"settlement_id": settlement.id, "provider_payment_id": settlement.provider_payment_id},
            ))

    for refund in refunds:
        if refund.id in matched_refunds:
            continue
        linked_payment = session.get(Payment, refund.payment_id) if refund.payment_id else None
        if linked_payment is None and refund.provider_payment_id:
            linked_payment = session.scalar(select(Payment).where(
                Payment.provider == refund.provider,
                Payment.provider_payment_id == refund.provider_payment_id,
            ))
        if linked_payment is None:
            created += int(_case(
                session, payment=None, record=refund, case_type="REFUND_WITHOUT_PAYMENT",
                reason_code="REFUND_WITHOUT_PAYMENT", expected=Decimal("0"), actual=refund.amount,
                summary="Refund record has no matching payment.",
                explanation="The refund provider payment reference does not resolve to a known payment.",
                action="Verify the refund reference and payment import.",
            ))
        else:
            linked_settlements = settlements_by_payment.get((refund.provider, _normalize(refund.provider_payment_id)), [])
            if not linked_settlements:
                created += int(_case(
                    session, payment=linked_payment, record=refund, case_type="REFUND_WITHOUT_SETTLEMENT",
                    reason_code="REFUND_NOT_SETTLED", expected=refund.amount, actual=Decimal("0"),
                    summary="Refund is linked to a payment but no settlement record exists for that payment.",
                    explanation="The refund cannot be tied to a settled payment because no settlement record is present.",
                    action="Import the payment settlement and verify the refund settlement treatment.",
                ))


    # Bank reconciliation: settlement payouts should land in the bank for the
    # same merchant. Match by UTR/settlement reference first, then by amount,
    # currency and a bounded date window. This closes the third leg of the
    # payment -> settlement -> bank control without moving money.
    bank_stmt = select(BankTransaction).order_by(BankTransaction.event_timestamp, BankTransaction.id)
    if merchant_id:
        bank_stmt = bank_stmt.where(BankTransaction.merchant_id == merchant_id)
    bank_transactions = session.scalars(bank_stmt).all()

    bank_by_ref = defaultdict(list)
    bank_by_utr = defaultdict(list)
    bank_by_currency = defaultdict(list)
    for bank in bank_transactions:
        for ref in {
            _normalize(bank.reference),
            _normalize((bank.metadata_json or {}).get("settlement_reference")),
            _normalize((bank.metadata_json or {}).get("settlement_id")),
        }:
            if ref:
                bank_by_ref[(str(bank.provider or "").lower(), ref)].append(bank)
                bank_by_ref[("*", ref)].append(bank)
        utr = _normalize((bank.metadata_json or {}).get("utr"))
        if utr:
            bank_by_utr[utr].append(bank)
        bank_by_currency[str(bank.currency).upper()].append(bank)

    matched_bank_ids: set[str] = set()
    bank_stats = {"matched": 0, "unmatched": 0, "mismatch": 0, "ambiguous": 0}
    for settlement in settlements:
        if merchant_id and settlement.merchant_id != merchant_id:
            continue
        provider = str(settlement.provider or "").lower()
        refs = {_normalize(settlement.provider_settlement_id), _normalize(settlement.utr)}
        candidates_map = {}
        for ref in refs:
            if not ref:
                continue
            for bank in bank_by_ref.get((provider, ref), []) + bank_by_ref.get(("*", ref), []) + bank_by_utr.get(ref, []):
                candidates_map[bank.id] = bank
        candidates = list(candidates_map.values())
        if not candidates:
            # Only scan the same-currency bank rows inside the configured
            # settlement timing window; never scan the full bank table.
            bt = settlement.settled_at
            if bt.tzinfo is not None:
                bt = bt.astimezone().replace(tzinfo=None)
            for bank in bank_by_currency.get(str(settlement.raw_data.get("currency", "INR")).upper(), []):
                dt = bank.event_timestamp
                if dt.tzinfo is not None:
                    dt = dt.astimezone().replace(tzinfo=None)
                if abs(dt - bt).days <= max(7, settings.settlement_window_days) and abs(Decimal(bank.amount) - Decimal(settlement.net_amount)) <= rules.amount_tolerance:
                    candidates.append(bank)
        if len(candidates) > 1:
            bank_stats["ambiguous"] += 1
            created += int(_case(
                session, payment=session.get(Payment, settlement.payment_id) if settlement.payment_id else None,
                record=settlement, case_type="BANK_AMBIGUOUS_MATCH",
                reason_code="BANK_AMBIGUOUS_MATCH", expected=settlement.net_amount, actual=Decimal("0"),
                summary="Multiple bank transactions could represent the settlement payout.",
                explanation="More than one bank transaction matched the settlement by reference or deterministic amount/date rules.",
                action="Review the candidate bank credits before closing the settlement.",
                matched_record_id=candidates[0].id if candidates else None,
                metadata={"merchant_id": settlement.merchant_id, "candidate_bank_ids": [x.id for x in candidates]},
            ))
            continue
        if len(candidates) == 1:
            bank = candidates[0]
            matched_bank_ids.add(bank.id)
            bank_amount = Decimal(bank.amount)
            currency_match = str(bank.currency).upper() == str(settlement.raw_data.get("currency", "INR")).upper()
            if bank_amount != Decimal(settlement.net_amount) or not currency_match:
                bank_stats["mismatch"] += 1
                created += int(_case(
                    session, payment=session.get(Payment, settlement.payment_id) if settlement.payment_id else None,
                    record=bank, case_type="BANK_SETTLEMENT_MISMATCH",
                    reason_code="BANK_SETTLEMENT_MISMATCH", expected=settlement.net_amount, actual=bank_amount,
                    summary=f"Bank credit {bank_amount} does not equal settlement net {settlement.net_amount}.",
                    explanation="The settlement and bank transaction were deterministically linked, but the credited amount or currency differs.",
                    action="Verify bank charges, adjustments, split credits, and the provider settlement statement.",
                    matched_record_id=settlement.id,
                    metadata={"merchant_id": settlement.merchant_id, "settlement_id": settlement.id, "bank_transaction_id": bank.id, "settlement_currency": str(settlement.raw_data.get("currency", "INR")).upper(), "bank_currency": str(bank.currency).upper()},
                ))
            else:
                bank_stats["matched"] += 1

    for bank in bank_transactions:
        if bank.id in matched_bank_ids:
            continue
        # A bank credit that is not explained by a settlement is actionable.
        if Decimal(bank.amount) <= 0:
            continue
        bank_stats["unmatched"] += 1
        created += int(_case(
            session, payment=None, record=bank, case_type="BANK_WITHOUT_SETTLEMENT",
            reason_code="BANK_WITHOUT_SETTLEMENT", expected=Decimal("0"), actual=Decimal(bank.amount),
            summary=f"Bank credit {bank.amount} has no matching settlement.",
            explanation="The bank transaction was ingested but could not be linked to a provider settlement using reference, UTR, amount, currency and date rules.",
            action="Verify whether this is a settlement from another provider, an adjustment, or an unclassified receipt.",
            metadata={"merchant_id": bank.merchant_id, "bank_transaction_id": bank.id},
        ))
    stats.update({f"bank_{k}": v for k, v in bank_stats.items()})

    session.commit()
    duration_seconds = monotonic() - started
    duration_ms = round(duration_seconds * 1000, 2)
    observe("reconciliation_duration_seconds", duration_seconds)
    import logging
    logging.getLogger("rcaa.reconciliation").info(
        "reconciliation_complete run_id=%s records=%s matched=%s unmatched=%s ambiguous=%s mismatch=%s delayed=%s duplicates=%s duration_ms=%s",
        run_id, len(payments) + len(refunds) + len(settlements) + len(bank_transactions), stats["matched"], stats["unmatched"],
        stats["ambiguous"], stats["mismatch"], stats["delayed"], stats["duplicates"], duration_ms,
    )
    if return_report:
        return {"created_cases": created, "run_id": run_id, "total_records": len(payments) + len(refunds) + len(settlements), **stats, "duration_ms": duration_ms}
    return created


def _normalize(value):
    if value is None:
        return None
    value = str(value).strip()
    return value.lower() if value else None


def rules_window():
    from datetime import timedelta
    return timedelta(days=rules.settlement_window_days)
