from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision='0007'; down_revision='0006'; branch_labels=None; depends_on=None

def upgrade():
    conn=op.get_bind(); insp=inspect(conn); tables=set(insp.get_table_names())
    if 'users' not in tables:
        op.create_table('users',
            sa.Column('id',sa.String(),primary_key=True),
            sa.Column('email',sa.String(),nullable=False),
            sa.Column('password_hash',sa.String(),nullable=False),
            sa.Column('merchant_id',sa.String(),sa.ForeignKey('merchants.id'),nullable=False),
            sa.Column('role',sa.String(),nullable=False),
            sa.Column('is_active',sa.Boolean(),nullable=False,server_default=sa.true()),
            sa.Column('created_at',sa.DateTime(timezone=True)),
            sa.Column('updated_at',sa.DateTime(timezone=True)),
        )
        op.create_index('ix_users_email','users',['email'],unique=True)
        op.create_index('ix_users_merchant_id','users',['merchant_id'])
        op.create_index('ix_users_role','users',['role'])
        op.create_index('ix_users_is_active','users',['is_active'])
    for table, idx in [('refunds','ix_refund_merchant_id'),('settlements','ix_settlement_merchant_id'),('ingestion_batches','ix_ingestion_batch_merchant_id')]:
        cols={c['name'] for c in insp.get_columns(table)}
        if 'merchant_id' not in cols:
            with op.batch_alter_table(table, recreate='always') as batch:
                batch.add_column(sa.Column('merchant_id',sa.String()))
                batch.create_foreign_key(f'fk_{table}_merchant_id', 'merchants', ['merchant_id'], ['id'])
            if idx not in {i['name'] for i in inspect(conn).get_indexes(table)}:
                op.create_index(idx, table, ['merchant_id'])
    # Backfill tenant ownership for existing linked financial records.
    conn.execute(text('UPDATE refunds SET merchant_id=(SELECT merchant_id FROM payments WHERE payments.id=refunds.payment_id) WHERE merchant_id IS NULL AND payment_id IS NOT NULL'))
    conn.execute(text('UPDATE settlements SET merchant_id=(SELECT merchant_id FROM payments WHERE payments.id=settlements.payment_id) WHERE merchant_id IS NULL AND payment_id IS NOT NULL'))
    conn.execute(text('UPDATE ingestion_batches SET merchant_id=(SELECT merchant_id FROM payments WHERE payments.ingestion_batch_id=ingestion_batches.id LIMIT 1) WHERE merchant_id IS NULL'))
    conn.execute(text('UPDATE ingestion_batches SET merchant_id=(SELECT merchant_id FROM refunds WHERE refunds.ingestion_batch_id=ingestion_batches.id LIMIT 1) WHERE merchant_id IS NULL'))
    conn.execute(text('UPDATE ingestion_batches SET merchant_id=(SELECT merchant_id FROM settlements WHERE settlements.ingestion_batch_id=ingestion_batches.id LIMIT 1) WHERE merchant_id IS NULL'))

def downgrade():
    conn=op.get_bind(); insp=inspect(conn)
    def drop_idx(name, table):
        if name in {i["name"] for i in insp.get_indexes(table)}:
            op.drop_index(name, table_name=table)
    def drop_col(table, name):
        if name in {c["name"] for c in inspect(conn).get_columns(table)}:
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_column(name)
    for table, col in [('ingestion_batches','merchant_id'),('settlements','merchant_id'),('refunds','merchant_id')]:
        if table in insp.get_table_names() and col in {c['name'] for c in insp.get_columns(table)}:
            for idx in list(inspect(conn).get_indexes(table)):
                if col in idx.get('column_names', []):
                    try: op.drop_index(idx['name'], table_name=table)
                    except Exception: pass
            drop_col(table, col)
    if 'users' in insp.get_table_names():
        for name in ('ix_users_is_active','ix_users_role','ix_users_merchant_id','ix_users_email'):
            drop_idx(name,'users')
        op.drop_table('users')
