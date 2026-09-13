from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = inspect(conn)
    if "background_jobs" not in insp.get_table_names():
        op.create_table(
            "background_jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("job_id", sa.String(), nullable=False, unique=True),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.Column("next_retry_at", sa.DateTime(timezone=True)),
            sa.Column("last_error_code", sa.String()),
            sa.Column("last_error_message_safe", sa.Text()),
            sa.Column("request_id", sa.String()),
            sa.Column("created_by", sa.String()),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("result_json", sa.JSON()),
            sa.Column("idempotency_key", sa.String(), nullable=False),
            sa.Column("worker_id", sa.String()),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_background_job_merchant_idempotency"),
        )
    existing = {i["name"] for i in inspect(conn).get_indexes("background_jobs")}
    for name, cols in [
        ("ix_background_job_queue", ["status", "next_retry_at", "created_at"]),
        ("ix_background_job_merchant_created", ["merchant_id", "created_at"]),
        ("ix_background_job_type_status", ["job_type", "status"]),
        ("ix_background_job_request_id", ["request_id"]),
        ("ix_background_job_created_by", ["created_by"]),
    ]:
        if name not in existing: op.create_index(name, "background_jobs", cols, unique=False)


def downgrade():
    conn = op.get_bind()
    if "background_jobs" in inspect(conn).get_table_names():
        op.drop_table("background_jobs")
