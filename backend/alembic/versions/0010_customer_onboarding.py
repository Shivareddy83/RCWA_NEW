from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if "merchant_onboarding" not in inspect(conn).get_table_names():
        op.create_table(
            "merchant_onboarding",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), nullable=False, unique=True),
            sa.Column("business_type", sa.String(), nullable=True),
            sa.Column("monthly_transaction_band", sa.String(), nullable=True),
            sa.Column("primary_provider", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="IN_PROGRESS"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_merchant_onboarding_merchant", "merchant_onboarding", ["merchant_id"], unique=True)
        op.create_index("ix_merchant_onboarding_status", "merchant_onboarding", ["status"], unique=False)


def downgrade():
    conn = op.get_bind()
    if "merchant_onboarding" in inspect(conn).get_table_names():
        op.drop_table("merchant_onboarding")
