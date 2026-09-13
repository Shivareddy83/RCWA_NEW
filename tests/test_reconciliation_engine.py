import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_reconciliation.db"
sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Payment, Refund, Settlement
from app.reconciliation.calculator import calculate_expected_settlement
from app.reconciliation.engine import run_reconciliation

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


def dt(minutes=0):
    return datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def add_payment(s, pid, amount="1000.00", order=None, currency="INR", status="captured", raw=None, created=None):
    value = Payment(provider="demo", provider_payment_id=pid, provider_order_id=order,
                    amount=Decimal(amount), currency=currency, status=status,
                    captured=status == "captured", created_at=created or dt(), raw_data=raw or {})
    s.add(value); s.flush(); return value


def add_settlement(s, sid, pid, net="1000.00", fee="0", tax="0", currency="INR", minutes=5,
                   status="processed", utr=None, raw=None):
    value = Settlement(provider="demo", provider_settlement_id=sid, provider_payment_id=pid,
                       gross_amount=Decimal(net) + Decimal(fee) + Decimal(tax), fee=Decimal(fee),
                       tax=Decimal(tax), net_amount=Decimal(net), status=status, settled_at=dt(minutes),
                       utr=utr, raw_data={"currency": currency, **(raw or {})})
    s.add(value); s.flush(); return value


def add_refund(s, rid, pid, amount="100.00", status="processed", created=None):
    value = Refund(provider="demo", provider_refund_id=rid, provider_payment_id=pid,
                   amount=Decimal(amount), status=status, created_at=created or dt(), processed_at=created or dt(), raw_data={})
    s.add(value); s.flush(); return value


def fresh():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine); return SessionLocal()


def case_types(s):
    from app.models import Case
    return [c.case_type for c in s.query(Case).all()]


def test_exact_payment_id_match():
    s=fresh(); p=add_payment(s,"p1"); add_settlement(s,"s1","p1"); s.commit()
    assert run_reconciliation(s) == 0
    s.close()


def test_order_reference_match():
    s=fresh(); p=add_payment(s,"p1",order="merchant-1"); add_settlement(s,"s1","stale",raw={"order_id":"MERCHANT-1"}); s.commit()
    assert run_reconciliation(s) == 0
    s.close()


def test_utr_reference_match():
    s=fresh(); add_payment(s,"p1",raw={"utr":"UTR-123"}); add_settlement(s,"s1","stale",utr="utr-123"); s.commit()
    assert run_reconciliation(s) == 0
    s.close()


def test_amount_currency_time_window_match():
    s=fresh(); add_payment(s,"p1",amount="1000",created=dt()); add_settlement(s,"s1","stale",net="1000",minutes=20); s.commit()
    assert run_reconciliation(s) == 0
    s.close()


def test_no_match_is_explicit():
    s=fresh(); add_payment(s,"p1",amount="1000"); add_settlement(s,"s1","other",net="900",minutes=200); s.commit()
    run_reconciliation(s); assert "PAYMENT_WITHOUT_SETTLEMENT" in case_types(s); s.close()


def test_ambiguous_match_is_not_auto_selected():
    s=fresh(); add_payment(s,"p1",amount="1000"); add_settlement(s,"s1","other",net="1000",minutes=5); add_settlement(s,"s2","other2",net="1000",minutes=6); s.commit()
    run_reconciliation(s); assert "AMBIGUOUS_MATCH" in case_types(s); s.close()


def test_duplicate_payment_by_order_reference():
    s=fresh(); add_payment(s,"p1",order="same"); add_payment(s,"p2",order="same"); s.commit()
    run_reconciliation(s); assert "DUPLICATE_PAYMENT" in case_types(s); s.close()


def test_duplicate_refund_source_rows_are_flagged_without_equating_multiple_valid_refunds():
    s=fresh(); add_payment(s,"p1"); add_refund(s,"r1","p1"); add_refund(s,"r2","p1"); s.commit()
    run_reconciliation(s); assert "DUPLICATE_REFUND" not in case_types(s); s.close()


def test_duplicate_settlement_source_rows_are_flagged():
    s=fresh(); add_payment(s,"p1"); add_settlement(s,"s1","p1"); add_settlement(s,"s2","p1"); s.commit()
    run_reconciliation(s); assert "DUPLICATE_SETTLEMENT" in case_types(s); s.close()


def test_missing_settlement():
    s=fresh(); add_payment(s,"p1"); s.commit(); run_reconciliation(s); assert "PAYMENT_WITHOUT_SETTLEMENT" in case_types(s); s.close()


def test_settlement_without_payment():
    s=fresh(); add_settlement(s,"s1","unknown"); s.commit(); run_reconciliation(s); assert "SETTLEMENT_WITHOUT_PAYMENT" in case_types(s); s.close()


def test_refund_without_payment():
    s=fresh(); add_refund(s,"r1","unknown"); s.commit(); run_reconciliation(s); assert "REFUND_WITHOUT_PAYMENT" in case_types(s); s.close()


def test_amount_mismatch():
    s=fresh(); add_payment(s,"p1",amount="1000"); add_settlement(s,"s1","p1",net="900"); s.commit(); run_reconciliation(s); assert "SETTLEMENT_MISMATCH" in case_types(s); s.close()


def test_fee_calculation():
    s=fresh(); p=add_payment(s,"p1",amount="1000"); settlement=add_settlement(s,"s1","p1",net="900",fee="80",tax="20");
    values=calculate_expected_settlement(p,[],[settlement]); assert values[4] == Decimal("900.00"); s.close()


def test_tax_calculation():
    s=fresh(); p=add_payment(s,"p1",amount="1000"); settlement=add_settlement(s,"s1","p1",net="900",fee="50",tax="50");
    values=calculate_expected_settlement(p,[],[settlement]); assert values[3] == Decimal("50.00"); assert values[4] == Decimal("900.00"); s.close()


def test_partial_refund():
    s=fresh(); add_payment(s,"p1",amount="1000"); add_refund(s,"r1","p1",amount="250"); add_settlement(s,"s1","p1",net="750"); s.commit(); assert run_reconciliation(s) == 0; s.close()


def test_multiple_refunds_are_aggregated():
    s=fresh(); p=add_payment(s,"p1",amount="1000"); r1=add_refund(s,"r1","p1",amount="100"); r2=add_refund(s,"r2","p1",amount="150"); settlement=add_settlement(s,"s1","p1",net="750");
    values=calculate_expected_settlement(p,[r1,r2],[settlement]); assert values[1] == Decimal("250.00"); assert values[4] == Decimal("750.00"); s.close()


def test_delayed_settlement():
    s=fresh(); add_payment(s,"p1"); add_settlement(s,"s1","p1",minutes=60*24*4); s.commit(); run_reconciliation(s); assert "DELAYED_SETTLEMENT" in case_types(s); s.close()


def test_status_mismatch():
    s=fresh(); add_payment(s,"p1",status="failed"); add_settlement(s,"s1","p1"); s.commit(); run_reconciliation(s); assert "STATUS_MISMATCH" in case_types(s); s.close()


def test_zero_amount_edge_is_not_accepted_by_payment_schema_but_calculator_handles_decimal_zero():
    s=fresh(); p=add_payment(s,"p1",amount="0.00"); settlement=add_settlement(s,"s1","p1",net="0.00");
    values=calculate_expected_settlement(p,[],[settlement]); assert values[4] == Decimal("0.00"); s.close()


def test_currency_mismatch():
    s=fresh(); add_payment(s,"p1",currency="INR"); add_settlement(s,"s1","p1",currency="USD"); s.commit(); run_reconciliation(s); assert "CURRENCY_MISMATCH" in case_types(s); s.close()


def test_timestamp_boundary():
    s=fresh(); add_payment(s,"p1"); add_settlement(s,"s1","stale",net="1000",minutes=30); s.commit(); assert run_reconciliation(s) == 0; s.close()


def test_idempotency():
    s=fresh(); add_payment(s,"p1"); s.commit(); first=run_reconciliation(s); second=run_reconciliation(s); assert first == 1; assert second == 0; s.close()


def test_repeated_execution_keeps_same_case_set():
    s=fresh(); add_payment(s,"p1"); s.commit(); run_reconciliation(s); from app.models import Case; first={(c.case_type,c.fingerprint) for c in s.query(Case).all()}; run_reconciliation(s); second={(c.case_type,c.fingerprint) for c in s.query(Case).all()}; assert first == second; s.close()


def test_razorpay_settlement_normalization_calculates_net_with_decimal():
    from app.providers.razorpay import RazorpayProvider
    provider = RazorpayProvider("", "", "")
    normalized = provider.normalize_settlement({"id":"s1","payment_id":"p1","amount":100000,"fees":8000,"tax":2000,"created_at":1750000000})
    assert normalized["gross_amount"] == "1000"
    assert normalized["fee"] == "80"
    assert normalized["tax"] == "20"
    assert normalized["net_amount"] == "900"
    assert normalized["settled_at"].tzinfo is not None
