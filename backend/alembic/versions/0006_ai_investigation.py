from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
revision='0006'; down_revision='0005'; branch_labels=None; depends_on=None

def upgrade():
    conn=op.get_bind(); insp=inspect(conn)
    if 'ai_investigation_audits' not in insp.get_table_names():
        op.create_table('ai_investigation_audits',
            sa.Column('id',sa.String(),primary_key=True),
            sa.Column('case_id',sa.String(),sa.ForeignKey('reconciliation_cases.id'),nullable=False),
            sa.Column('request_fingerprint',sa.String(),nullable=False),
            sa.Column('evidence_fingerprint',sa.String(),nullable=False),
            sa.Column('prompt_version',sa.String(),nullable=False),
            sa.Column('provider',sa.String(),nullable=False),
            sa.Column('model',sa.String(),nullable=False),
            sa.Column('result_fingerprint',sa.String()),
            sa.Column('result_json',sa.JSON()),
            sa.Column('status',sa.String(),nullable=False),
            sa.Column('latency_ms',sa.Integer()),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=True))
    idx={i['name'] for i in inspect(conn).get_indexes('ai_investigation_audits')}
    if 'uq_ai_request_fingerprint' not in idx: op.create_index('uq_ai_request_fingerprint','ai_investigation_audits',['request_fingerprint'],unique=True)
    if 'ix_ai_audit_case_created' not in idx: op.create_index('ix_ai_audit_case_created','ai_investigation_audits',['case_id','created_at'])

def downgrade():
    op.drop_table('ai_investigation_audits')
