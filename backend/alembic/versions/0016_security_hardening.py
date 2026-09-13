from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    if "security_rate_limits" not in inspect(conn).get_table_names():
        op.create_table(
            "security_rate_limits",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("key_hash", sa.String(), nullable=False),
            sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("action", "key_hash", name="uq_security_rate_limit_key"),
        )
    indexes = {x["name"] for x in inspect(conn).get_indexes("security_rate_limits")}
    if "ix_security_rate_limit_action" not in indexes:
        op.create_index("ix_security_rate_limit_action", "security_rate_limits", ["action"], unique=False)
    if "ix_security_rate_limit_updated" not in indexes:
        op.create_index("ix_security_rate_limit_updated", "security_rate_limits", ["updated_at"], unique=False)

    columns = {x["name"] for x in inspect(conn).get_columns("billing_subscriptions")}
    if "provider_status" not in columns:
        op.add_column("billing_subscriptions", sa.Column("provider_status", sa.String(), nullable=True))
        op.create_index("ix_billing_subscriptions_provider_status", "billing_subscriptions", ["provider_status"], unique=False)
    columns = {x["name"] for x in inspect(conn).get_columns("billing_subscriptions")}
    if "provider_event_created_at" not in columns:
        op.add_column("billing_subscriptions", sa.Column("provider_event_created_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    conn = op.get_bind()
    if "billing_subscriptions" in inspect(conn).get_table_names():
        indexes = {x["name"] for x in inspect(conn).get_indexes("billing_subscriptions")}
        if "ix_billing_subscriptions_provider_status" in indexes:
            op.drop_index("ix_billing_subscriptions_provider_status", table_name="billing_subscriptions")
        columns = {x["name"] for x in inspect(conn).get_columns("billing_subscriptions")}
        if "provider_event_created_at" in columns:
            op.drop_column("billing_subscriptions", "provider_event_created_at")
        if "provider_status" in columns:
            op.drop_column("billing_subscriptions", "provider_status")
    if "security_rate_limits" in inspect(conn).get_table_names():
        indexes = {x["name"] for x in inspect(conn).get_indexes("security_rate_limits")}
        for name in ["ix_security_rate_limit_updated", "ix_security_rate_limit_action"]:
            if name in indexes:
                op.drop_index(name, table_name="security_rate_limits")
        op.drop_table("security_rate_limits")
