from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind(); tables = inspect(conn).get_table_names()
    if 'billing_subscriptions' not in tables:
        op.create_table('billing_subscriptions',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), nullable=False),
            sa.Column('plan_code', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='TRIAL'),
            sa.Column('currency', sa.String(), nullable=False, server_default='INR'),
            sa.Column('monthly_price', sa.Numeric(12,2), nullable=False, server_default='0'),
            sa.Column('monthly_transaction_limit', sa.Integer()),
            sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=False),
            sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=False),
            sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('provider', sa.String(), nullable=False, server_default='MANUAL'),
            sa.Column('provider_subscription_id', sa.String()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_billing_subscription_merchant','billing_subscriptions',['merchant_id'],unique=True)
        op.create_index('ix_billing_subscription_merchant_status','billing_subscriptions',['merchant_id','status'])
        op.create_index('ix_billing_subscription_plan','billing_subscriptions',['plan_code'])
    if 'billing_invoices' not in tables:
        op.create_table('billing_invoices',
            sa.Column('id', sa.String(), primary_key=True), sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), nullable=False),
            sa.Column('subscription_id', sa.String(), sa.ForeignKey('billing_subscriptions.id')), sa.Column('invoice_number', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='PENDING'), sa.Column('currency', sa.String(), nullable=False, server_default='INR'),
            sa.Column('subtotal', sa.Numeric(12,2), nullable=False, server_default='0'), sa.Column('tax', sa.Numeric(12,2), nullable=False, server_default='0'),
            sa.Column('total', sa.Numeric(12,2), nullable=False, server_default='0'), sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('due_at', sa.DateTime(timezone=True), nullable=False), sa.Column('paid_at', sa.DateTime(timezone=True)),
            sa.Column('provider', sa.String(), nullable=False, server_default='MANUAL'), sa.Column('provider_invoice_id', sa.String()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_billing_invoice_merchant','billing_invoices',['merchant_id'])
        op.create_index('ix_billing_invoice_status','billing_invoices',['status'])
        op.create_index('ix_billing_invoice_merchant_status','billing_invoices',['merchant_id','status'])
        op.create_index('ix_billing_invoice_number','billing_invoices',['invoice_number'])
        op.create_unique_constraint('uq_billing_invoice_number','billing_invoices',['merchant_id','invoice_number'])
    if 'billing_usage_snapshots' not in tables:
        op.create_table('billing_usage_snapshots',
            sa.Column('id', sa.String(), primary_key=True), sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), nullable=False),
            sa.Column('period_start', sa.DateTime(timezone=True), nullable=False), sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
            sa.Column('payments_processed', sa.Integer(), nullable=False, server_default='0'), sa.Column('settlements_processed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('reconciliation_runs', sa.Integer(), nullable=False, server_default='0'), sa.Column('exceptions_created', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
        op.create_index('ix_billing_usage_merchant','billing_usage_snapshots',['merchant_id'])
        op.create_index('ix_billing_usage_merchant_period','billing_usage_snapshots',['merchant_id','period_start'])
        op.create_unique_constraint('uq_billing_usage_period','billing_usage_snapshots',['merchant_id','period_start','period_end'])

def downgrade():
    conn=op.get_bind(); tables=inspect(conn).get_table_names()
    for t in ('billing_usage_snapshots','billing_invoices','billing_subscriptions'):
        if t in tables: op.drop_table(t)
