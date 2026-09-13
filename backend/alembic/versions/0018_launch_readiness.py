from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    tables = set(inspect(conn).get_table_names())
    if "password_reset_tokens" not in tables:
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("request_ip_hash", sa.String(), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
        )
    if "data_connectors" not in tables:
        op.create_table(
            "data_connectors",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="DISCONNECTED"),
            sa.Column("credentials_enc", sa.Text(), nullable=True),
            sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_status", sa.String(), nullable=True),
            sa.Column("last_sync_summary", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("merchant_id", "provider", name="uq_connector_merchant_provider"),
        )
    for table, specs in {
        "password_reset_tokens": {
            "ix_password_reset_user_expires": ["user_id", "expires_at"],
            "ix_password_reset_token_hash": ["token_hash"],
            "ix_password_reset_user_id": ["user_id"],
            "ix_password_reset_expires_at": ["expires_at"],
        },
        "data_connectors": {
            "ix_connector_merchant_status": ["merchant_id", "status"],
            "ix_connector_merchant_id": ["merchant_id"],
            "ix_connector_provider": ["provider"],
            "ix_connector_next_sync_at": ["next_sync_at"],
        },
    }.items():
        existing = {x["name"] for x in inspect(conn).get_indexes(table)}
        for name, cols in specs.items():
            if name not in existing:
                op.create_index(name, table, cols, unique=False)
    cols = {x["name"] for x in inspect(conn).get_columns("reconciliation_cases")}
    if "sla_due_at" not in cols:
        op.add_column("reconciliation_cases", sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_case_sla_due_at", "reconciliation_cases", ["sla_due_at"], unique=False)

def downgrade():
    conn = op.get_bind()
    if "reconciliation_cases" in inspect(conn).get_table_names() and "sla_due_at" in {x["name"] for x in inspect(conn).get_columns("reconciliation_cases")}:
        if "ix_case_sla_due_at" in {x["name"] for x in inspect(conn).get_indexes("reconciliation_cases")}: op.drop_index("ix_case_sla_due_at", table_name="reconciliation_cases")
        op.drop_column("reconciliation_cases", "sla_due_at")
    for table in ["data_connectors", "password_reset_tokens"]:
        if table in inspect(conn).get_table_names():
            for idx in list(inspect(conn).get_indexes(table)):
                if idx["name"].startswith(("ix_connector_", "ix_password_reset_")):
                    op.drop_index(idx["name"], table_name=table)
            op.drop_table(table)
