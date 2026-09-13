from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

def _add_column_if_missing(conn, table, column):
    columns = {c['name'] for c in inspect(conn).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)
        if column.index:
            op.create_index(f'ix_{table}_{column.name}', table, [column.name])

def upgrade():
    conn = op.get_bind()
    _add_column_if_missing(conn, 'billing_subscriptions', sa.Column('provider_plan_id', sa.String(), index=True))
    _add_column_if_missing(conn, 'billing_subscriptions', sa.Column('provider_customer_id', sa.String(), index=True))
    _add_column_if_missing(conn, 'billing_subscriptions', sa.Column('last_payment_id', sa.String(), index=True))
    _add_column_if_missing(conn, 'billing_invoices', sa.Column('provider_payment_id', sa.String(), index=True))

def downgrade():
    conn = op.get_bind()
    for table, col in [('billing_invoices','provider_payment_id'),('billing_subscriptions','last_payment_id'),('billing_subscriptions','provider_customer_id'),('billing_subscriptions','provider_plan_id')]:
        columns = {c['name'] for c in inspect(conn).get_columns(table)}
        if col in columns:
            idx = f'ix_{table}_{col}'
            indexes = {i['name'] for i in inspect(conn).get_indexes(table)}
            if idx in indexes:
                op.drop_index(idx, table_name=table)
            op.drop_column(table, col)
