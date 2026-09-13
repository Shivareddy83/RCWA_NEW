from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if "data_uploads" not in inspect(conn).get_table_names():
        op.create_table(
            "data_uploads",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("merchant_id", sa.String(), sa.ForeignKey("merchants.id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("data_type", sa.String(), nullable=False),
            sa.Column("provider", sa.String()),
            sa.Column("content_type", sa.String()),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("headers_json", sa.JSON(), nullable=False),
            sa.Column("preview_rows_json", sa.JSON(), nullable=False),
            sa.Column("rows_json", sa.JSON(), nullable=False),
            sa.Column("mapping_json", sa.JSON(), nullable=False),
            sa.Column("validation_json", sa.JSON(), nullable=False),
            sa.Column("import_result_json", sa.JSON()),
            sa.Column("status", sa.String(), nullable=False, server_default="UPLOADED"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("validated_at", sa.DateTime(timezone=True)),
            sa.Column("imported_at", sa.DateTime(timezone=True)),
        )
        op.create_index("ix_data_upload_merchant", "data_uploads", ["merchant_id"], unique=False)
        op.create_index("ix_data_upload_type", "data_uploads", ["data_type"], unique=False)
        op.create_index("ix_data_upload_provider", "data_uploads", ["provider"], unique=False)
        op.create_index("ix_data_upload_status", "data_uploads", ["status"], unique=False)


def downgrade():
    conn = op.get_bind()
    if "data_uploads" in inspect(conn).get_table_names():
        op.drop_table("data_uploads")
