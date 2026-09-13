from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
revision='0012'; down_revision='0011'; branch_labels=None; depends_on=None

def upgrade():
    conn=op.get_bind(); tables=inspect(conn).get_table_names()
    if 'notification_preferences' not in tables:
        op.create_table('notification_preferences',
            sa.Column('id',sa.String(),primary_key=True), sa.Column('merchant_id',sa.String(),sa.ForeignKey('merchants.id'),nullable=False),
            sa.Column('enable_exceptions',sa.Boolean(),nullable=False,server_default=sa.true()), sa.Column('enable_cases',sa.Boolean(),nullable=False,server_default=sa.true()),
            sa.Column('enable_reports',sa.Boolean(),nullable=False,server_default=sa.true()), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
        op.create_index('ix_notification_pref_merchant','notification_preferences',['merchant_id'],unique=True)
    if 'notifications' not in tables:
        op.create_table('notifications',
            sa.Column('id',sa.String(),primary_key=True), sa.Column('merchant_id',sa.String(),sa.ForeignKey('merchants.id'),nullable=False), sa.Column('user_id',sa.String()),
            sa.Column('kind',sa.String(),nullable=False), sa.Column('severity',sa.String(),nullable=False,server_default='INFO'), sa.Column('title',sa.String(),nullable=False), sa.Column('message',sa.Text(),nullable=False),
            sa.Column('resource_type',sa.String()), sa.Column('resource_id',sa.String()), sa.Column('read_at',sa.DateTime(timezone=True)), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
        op.create_index('ix_notification_merchant_created','notifications',['merchant_id','created_at'])
        op.create_index('ix_notification_user_read','notifications',['user_id','read_at'])

def downgrade():
    conn=op.get_bind();
    if 'notifications' in inspect(conn).get_table_names(): op.drop_table('notifications')
    if 'notification_preferences' in inspect(conn).get_table_names(): op.drop_table('notification_preferences')
