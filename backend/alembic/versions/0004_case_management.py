"""case management and operations workflow

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from datetime import datetime

revision='0004'; down_revision='0003'; branch_labels=None; depends_on=None

CASE_COLUMNS = {
    'case_number': sa.Column('case_number', sa.String(), nullable=True),
    'merchant_id': sa.Column('merchant_id', sa.String(), nullable=True),
    'title': sa.Column('title', sa.String(), nullable=True),
    'description': sa.Column('description', sa.Text(), nullable=True),
    'priority': sa.Column('priority', sa.String(), nullable=True),
    'assigned_to': sa.Column('assigned_to', sa.String(), nullable=True),
    'updated_at': sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    'resolution_code': sa.Column('resolution_code', sa.String(), nullable=True),
    'resolution_note': sa.Column('resolution_note', sa.Text(), nullable=True),
}

def upgrade():
    conn=op.get_bind(); inspector=inspect(conn)
    existing={c['name'] for c in inspector.get_columns('reconciliation_cases')}
    for name,column in CASE_COLUMNS.items():
        if name not in existing:
            op.add_column('reconciliation_cases', column)
    conn=op.get_bind()
    rows=conn.execute(text("SELECT id, severity, created_at, case_type FROM reconciliation_cases ORDER BY created_at, id")).fetchall()
    counters={}
    for row in rows:
        if row.created_at:
            created_value = row.created_at
            if isinstance(created_value, str):
                try: created_value = datetime.fromisoformat(created_value.replace('Z','+00:00'))
                except ValueError: created_value = None
            year = created_value.year if created_value else 2026
        else:
            year = 2026
        counters[year]=counters.get(year,0)+1
        # Preserve a pre-existing operational number if present.
        current=conn.execute(text("SELECT case_number FROM reconciliation_cases WHERE id=:id"), {'id':row.id}).scalar()
        num=current or f"RCAA-{year}-{counters[year]:06d}"
        priority=(row.severity or 'MEDIUM').upper()
        if priority not in ('LOW','MEDIUM','HIGH','CRITICAL'): priority='MEDIUM'
        conn.execute(text("UPDATE reconciliation_cases SET case_number=:n, title=COALESCE(title,:t), description=COALESCE(description,:d), priority=COALESCE(priority,:p), updated_at=COALESCE(updated_at,created_at) WHERE id=:id"),
                     {'n':num,'t':f'Investigate {row.case_type}','d':'Operational investigation for a reconciliation discrepancy.','p':priority,'id':row.id})
    existing_indexes={i['name'] for i in inspect(conn).get_indexes('reconciliation_cases')}
    if 'ix_case_number' not in existing_indexes:
        op.create_index('ix_case_number','reconciliation_cases',['case_number'],unique=True)
    if 'ix_case_merchant_id' not in existing_indexes: op.create_index('ix_case_merchant_id','reconciliation_cases',['merchant_id'])
    if 'ix_case_priority' not in existing_indexes: op.create_index('ix_case_priority','reconciliation_cases',['priority'])
    if 'ix_case_assigned_to' not in existing_indexes: op.create_index('ix_case_assigned_to','reconciliation_cases',['assigned_to'])

    tables={t['name'] for t in inspect(conn).get_table_names() if isinstance(t,dict)} if False else set(inspect(conn).get_table_names())
    if 'case_exception_links' not in tables:
        op.create_table('case_exception_links',
            sa.Column('case_id',sa.String(),sa.ForeignKey('reconciliation_cases.id'),primary_key=True),
            sa.Column('exception_id',sa.String(),sa.ForeignKey('reconciliation_exceptions.id'),primary_key=True),
            sa.UniqueConstraint('case_id','exception_id',name='uq_case_exception'))
        op.create_index('ix_case_exception_exception','case_exception_links',['exception_id'])
    if 'case_notes' not in tables:
        op.create_table('case_notes',
            sa.Column('id',sa.String(),primary_key=True), sa.Column('case_id',sa.String(),sa.ForeignKey('reconciliation_cases.id'),nullable=False),
            sa.Column('author_reference',sa.String()), sa.Column('note',sa.Text(),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
        op.create_index('ix_case_notes_case','case_notes',['case_id','created_at'])
    if 'case_events' not in tables:
        op.create_table('case_events',
            sa.Column('id',sa.String(),primary_key=True), sa.Column('case_id',sa.String(),sa.ForeignKey('reconciliation_cases.id'),nullable=False),
            sa.Column('event_type',sa.String(),nullable=False), sa.Column('actor_reference',sa.String()), sa.Column('metadata_json',sa.JSON()),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
        op.create_index('ix_case_events_case','case_events',['case_id','created_at'])
    # Backfill the explicit relationship for exceptions created in Stage 03.
    conn.execute(text("INSERT INTO case_exception_links(case_id, exception_id) SELECT reconciliation_case_id, id FROM reconciliation_exceptions WHERE reconciliation_case_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM case_exception_links l WHERE l.case_id=reconciliation_case_id AND l.exception_id=id)"))

def downgrade():
    conn=op.get_bind(); inspector=inspect(conn); tables=set(inspector.get_table_names())
    if 'case_events' in tables: op.drop_table('case_events')
    if 'case_notes' in tables: op.drop_table('case_notes')
    if 'case_exception_links' in tables: op.drop_table('case_exception_links')
    # Remove indexes introduced by this migration. SQLite may have different generated
    # names when the Stage 03 database was created through SQLAlchemy metadata.
    for idx in list(inspect(conn).get_indexes('reconciliation_cases')):
        cols=set(idx.get('column_names') or [])
        if cols & set(CASE_COLUMNS):
            try: op.drop_index(idx['name'], table_name='reconciliation_cases')
            except Exception: pass
    # Batch recreation safely handles SQLite's limitations around dropping columns
    # that participate in auto-generated indexes/constraints.
    with op.batch_alter_table('reconciliation_cases', recreate='always') as batch:
        current={c['name'] for c in inspect(conn).get_columns('reconciliation_cases')}
        for name in reversed(tuple(CASE_COLUMNS)):
            if name in current: batch.drop_column(name)
