from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
from app.billing import PLANS, STATUSES, add_month

def test_billing_plan_catalog_is_explicit_and_currency_safe():
    assert set(PLANS) == {'TRIAL','STARTER','GROWTH','BUSINESS'}
    assert all(v['monthly_price'].__class__ is Decimal for v in PLANS.values())
    assert PLANS['STARTER']['monthly_price'] == Decimal('9999.00')
    assert PLANS['GROWTH']['monthly_price'] == Decimal('24999.00')
    assert PLANS['BUSINESS']['monthly_price'] == Decimal('49999.00')
    assert PLANS['TRIAL']['monthly_price'] == Decimal('0.00')

def test_plan_transaction_limits_are_monotonic():
    assert PLANS['TRIAL']['transaction_limit'] < PLANS['STARTER']['transaction_limit'] < PLANS['GROWTH']['transaction_limit'] < PLANS['BUSINESS']['transaction_limit']

def test_subscription_statuses_and_month_rollover():
    assert {'TRIAL','PENDING_ACTIVATION','ACTIVE','PAST_DUE','CANCELLED'} == STATUSES
    assert add_month(datetime(2026, 1, 31, tzinfo=timezone.utc)).month == 2
    assert add_month(datetime(2026, 12, 31, tzinfo=timezone.utc)).year == 2027

def test_billing_models_are_exported():
    from app.models import BillingSubscription, BillingInvoice, BillingUsageSnapshot
    assert BillingSubscription.__tablename__ == 'billing_subscriptions'
    assert BillingInvoice.__tablename__ == 'billing_invoices'
    assert BillingUsageSnapshot.__tablename__ == 'billing_usage_snapshots'
