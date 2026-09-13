from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    tables = inspect(conn).get_table_names()
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False),
            sa.Column("family_id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by", sa.String(), nullable=True),
            sa.Column("ip_hash", sa.String(), nullable=True),
            sa.Column("user_agent_hash", sa.String(), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_auth_session_token_hash"),
        )
    indexes = {x["name"] for x in inspect(conn).get_indexes("auth_sessions")}
    for name, cols in {
        "ix_auth_session_user_active": ["user_id", "revoked_at", "expires_at"],
        "ix_auth_session_family": ["family_id"],
        "ix_auth_session_user_id": ["user_id"],
        "ix_auth_session_merchant_id": ["merchant_id"],
        "ix_auth_session_token_hash": ["token_hash"],
        "ix_auth_session_expires_at": ["expires_at"],
        "ix_auth_session_revoked_at": ["revoked_at"],
    }.items():
        if name not in indexes:
            op.create_index(name, "auth_sessions", cols, unique=False)

    cols = {x["name"] for x in inspect(conn).get_columns("users")}
    if "mfa_enabled" not in cols:
        op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "mfa_secret_enc" not in cols:
        op.add_column("users", sa.Column("mfa_secret_enc", sa.Text(), nullable=True))
    indexes = {x["name"] for x in inspect(conn).get_indexes("users")}
    if "ix_users_mfa_enabled" not in indexes:
        op.create_index("ix_users_mfa_enabled", "users", ["mfa_enabled"], unique=False)


def downgrade():
    conn = op.get_bind()
    if "users" in inspect(conn).get_table_names():
        indexes = {x["name"] for x in inspect(conn).get_indexes("users")}
        if "ix_users_mfa_enabled" in indexes:
            op.drop_index("ix_users_mfa_enabled", table_name="users")
        cols = {x["name"] for x in inspect(conn).get_columns("users")}
        if "mfa_secret_enc" in cols:
            op.drop_column("users", "mfa_secret_enc")
        if "mfa_enabled" in cols:
            op.drop_column("users", "mfa_enabled")
    if "auth_sessions" in inspect(conn).get_table_names():
        for name in ["ix_auth_session_revoked_at", "ix_auth_session_expires_at", "ix_auth_session_token_hash", "ix_auth_session_merchant_id", "ix_auth_session_user_id", "ix_auth_session_family", "ix_auth_session_user_active"]:
            if name in {x["name"] for x in inspect(conn).get_indexes("auth_sessions")}:
                op.drop_index(name, table_name="auth_sessions")
        op.drop_table("auth_sessions")
