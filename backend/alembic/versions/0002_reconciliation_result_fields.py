"""add deterministic reconciliation result fields

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_COLUMNS = [
    ("record_id", sa.Column("record_id", sa.String(), nullable=True)),
    ("record_type", sa.Column("record_type", sa.String(), nullable=False, server_default="payment")),
    ("match_method", sa.Column("match_method", sa.String(), nullable=False, server_default="NONE")),
    ("match_confidence", sa.Column("match_confidence", sa.String(), nullable=False, server_default="NONE")),
    ("matched_record_id", sa.Column("matched_record_id", sa.String(), nullable=True)),
    ("reason_code", sa.Column("reason_code", sa.String(), nullable=False, server_default="UNKNOWN")),
    ("metadata_json", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))),
]


def _columns():
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns("reconciliation_cases")}


def upgrade():
    existing = _columns()
    for name, column in _COLUMNS:
        if name not in existing:
            op.add_column("reconciliation_cases", column)

    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("reconciliation_cases")}
    if "ix_case_record_type_record_id" not in indexes:
        op.create_index("ix_case_record_type_record_id", "reconciliation_cases", ["record_type", "record_id"])
    if "ix_case_reason_code" not in indexes:
        op.create_index("ix_case_reason_code", "reconciliation_cases", ["reason_code"])




def downgrade():
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("reconciliation_cases")}
    if "ix_case_reason_code" in indexes:
        op.drop_index("ix_case_reason_code", table_name="reconciliation_cases")
    if "ix_case_record_type_record_id" in indexes:
        op.drop_index("ix_case_record_type_record_id", table_name="reconciliation_cases")
    existing = _columns()
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("reconciliation_cases", name)
