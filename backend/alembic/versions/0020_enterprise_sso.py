from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision="0020"
down_revision="0019"
branch_labels=None
depends_on=None

def upgrade():
    conn=op.get_bind(); tables=set(inspect(conn).get_table_names())
    if "sso_connections" not in tables:
        op.create_table("sso_connections", sa.Column("id",sa.String(),primary_key=True), sa.Column("merchant_id",sa.String(),sa.ForeignKey("merchants.id"),nullable=False), sa.Column("issuer_url",sa.String(),nullable=False), sa.Column("client_id",sa.String(),nullable=False), sa.Column("client_secret_enc",sa.Text(),nullable=False), sa.Column("allowed_domains",sa.Text(),nullable=False,server_default=""), sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.true()), sa.Column("default_role",sa.String(),nullable=False,server_default="VIEWER"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False), sa.UniqueConstraint("merchant_id",name="uq_sso_connection_merchant"))
    if "sso_login_states" not in tables:
        op.create_table("sso_login_states", sa.Column("id",sa.String(),primary_key=True), sa.Column("state_hash",sa.String(),nullable=False), sa.Column("merchant_id",sa.String(),sa.ForeignKey("merchants.id"),nullable=False), sa.Column("code_verifier_enc",sa.Text(),nullable=False), sa.Column("nonce_hash",sa.String(),nullable=False), sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.UniqueConstraint("state_hash"))
    for name,table,col in [("ix_sso_connection_merchant_id","sso_connections","merchant_id"),("ix_sso_login_state_hash","sso_login_states","state_hash"),("ix_sso_state_expires","sso_login_states","expires_at")]:
        if name not in {x["name"] for x in inspect(conn).get_indexes(table)}: op.create_index(name,table,[col],unique=False)

def downgrade():
    conn=op.get_bind()
    for table in ("sso_login_states","sso_connections"):
        if table in inspect(conn).get_table_names(): op.drop_table(table)
