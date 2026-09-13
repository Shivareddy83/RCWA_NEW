from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = inspect(conn)
    if 'audit_events' not in insp.get_table_names():
        op.create_table(
            'audit_events',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('event_id', sa.String(), nullable=False, unique=True),
            sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), nullable=True),
            sa.Column('actor_user_id', sa.String(), nullable=True),
            sa.Column('actor_role', sa.String(), nullable=True),
            sa.Column('actor_type', sa.String(), nullable=False),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('resource_type', sa.String(), nullable=False),
            sa.Column('resource_id', sa.String(), nullable=True),
            sa.Column('request_id', sa.String(), nullable=True),
            sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
            sa.Column('outcome', sa.String(), nullable=False),
            sa.Column('ip_address', sa.String(), nullable=True),
            sa.Column('metadata_json', sa.JSON(), nullable=False),
            sa.Column('before_snapshot', sa.JSON(), nullable=True),
            sa.Column('after_snapshot', sa.JSON(), nullable=True),
            sa.Column('previous_event_hash', sa.String(), nullable=True),
            sa.Column('event_hash', sa.String(), nullable=False, unique=True),
        )
    existing_indexes = {i['name'] for i in inspect(conn).get_indexes('audit_events')}
    indexes = [
        ('ix_audit_event_merchant_timestamp', ['merchant_id', 'timestamp'], False),
        ('ix_audit_event_action', ['action'], False),
        ('ix_audit_event_actor', ['actor_user_id'], False),
        ('ix_audit_event_resource', ['resource_type', 'resource_id'], False),
        ('ix_audit_event_request', ['request_id'], False),
        ('ix_audit_events_event_id', ['event_id'], True),
        ('ix_audit_events_event_hash', ['event_hash'], True),
    ]
    for name, cols, unique in indexes:
        if name not in existing_indexes:
            op.create_index(name, 'audit_events', cols, unique=unique)

    dialect = conn.dialect.name
    if dialect == 'sqlite':
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END
        """)
    elif dialect == 'postgresql':
        conn.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION rcaa_audit_events_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit events are append-only';
            END;
            $$ LANGUAGE plpgsql;
        """)
        conn.exec_driver_sql("""
            DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events;
            CREATE TRIGGER audit_events_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION rcaa_audit_events_immutable();
        """)


def downgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == 'sqlite':
        conn.exec_driver_sql('DROP TRIGGER IF EXISTS audit_events_no_update')
        conn.exec_driver_sql('DROP TRIGGER IF EXISTS audit_events_no_delete')
    elif dialect == 'postgresql':
        conn.exec_driver_sql('DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events')
        conn.exec_driver_sql('DROP FUNCTION IF EXISTS rcaa_audit_events_immutable()')
    if 'audit_events' in inspect(conn).get_table_names():
        op.drop_table('audit_events')
