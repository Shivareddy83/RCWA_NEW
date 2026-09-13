from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision='0015'
down_revision='0014'
branch_labels=None
depends_on=None

def upgrade():
    conn=op.get_bind()
    inspector=inspect(conn)
    tables=set(inspector.get_table_names())
    if 'demo_leads' not in tables:
        op.create_table('demo_leads',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('company_name', sa.String(), nullable=False),
            sa.Column('email', sa.String(), nullable=False),
            sa.Column('monthly_transactions', sa.String(), nullable=False, server_default='100k-500k'),
            sa.Column('message', sa.Text(), nullable=False, server_default=''),
            sa.Column('status', sa.String(), nullable=False, server_default='NEW'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        )
    indexes={x['name'] for x in inspect(conn).get_indexes('demo_leads')}
    if 'ix_demo_lead_created' not in indexes: op.create_index('ix_demo_lead_created','demo_leads',['created_at'])
    if 'ix_demo_lead_email' not in indexes: op.create_index('ix_demo_lead_email','demo_leads',['email'])
    if 'ix_demo_leads_status' not in indexes: op.create_index('ix_demo_leads_status','demo_leads',['status'])

def downgrade():
    conn=op.get_bind()
    if 'demo_leads' not in inspect(conn).get_table_names(): return
    indexes={x['name'] for x in inspect(conn).get_indexes('demo_leads')}
    for name in ['ix_demo_leads_status','ix_demo_lead_email','ix_demo_lead_created']:
        if name in indexes: op.drop_index(name,table_name='demo_leads')
    op.drop_table('demo_leads')
