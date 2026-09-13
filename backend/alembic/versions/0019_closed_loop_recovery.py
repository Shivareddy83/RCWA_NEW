from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    tables = set(inspect(conn).get_table_names())
    if "case_recovery_records" not in tables:
        op.create_table(
            "case_recovery_records",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("case_id", sa.String(), sa.ForeignKey("reconciliation_cases.id"), nullable=False),
            sa.Column("merchant_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="IDENTIFIED"),
            sa.Column("exposure_amount", sa.Numeric(14,2), nullable=False, server_default="0"),
            sa.Column("recoverable_amount", sa.Numeric(14,2), nullable=False, server_default="0"),
            sa.Column("recovered_amount", sa.Numeric(14,2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(), nullable=False, server_default="INR"),
            sa.Column("action_type", sa.String(), nullable=True),
            sa.Column("external_reference", sa.String(), nullable=True),
            sa.Column("expected_recovery_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_bank_transaction_id", sa.String(), sa.ForeignKey("bank_transactions.id"), nullable=True),
            sa.Column("action_note", sa.Text(), nullable=True),
            sa.Column("verification_note", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("case_id", name="uq_case_recovery_case"),
        )
    # Backfill one recovery record for every pre-existing case so the new lifecycle is
    # additive and old cases immediately participate in the closed-loop workflow.
    rows = conn.execute(sa.text("SELECT id, merchant_id, difference FROM reconciliation_cases")).mappings().all()
    existing_cases = {r["case_id"] for r in conn.execute(sa.text("SELECT case_id FROM case_recovery_records")).mappings().all()}
    import uuid
    for row in rows:
        if row["id"] in existing_cases:
            continue
        diff = abs(row["difference"] or 0)
        conn.execute(sa.text("""
            INSERT INTO case_recovery_records
            (id, case_id, merchant_id, status, exposure_amount, recoverable_amount, recovered_amount, currency, metadata_json, created_at, updated_at)
            VALUES (:id, :case_id, :merchant_id, :status, :exposure, :recoverable, 0, 'INR', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """), {"id": uuid.uuid4().hex, "case_id": row["id"], "merchant_id": row["merchant_id"],
               "status": "IDENTIFIED" if diff > 0 else "NOT_REQUIRED", "exposure": diff, "recoverable": diff})

    indexes = {x["name"] for x in inspect(conn).get_indexes("case_recovery_records")}
    for name, cols in {
        "ix_recovery_merchant_status": ["merchant_id", "status"],
        "ix_recovery_status": ["status"],
        "ix_case_recovery_records_case_id": ["case_id"],
        "ix_case_recovery_records_verified_bank_transaction_id": ["verified_bank_transaction_id"],
    }.items():
        if name not in indexes:
            op.create_index(name, "case_recovery_records", cols, unique=False)

def downgrade():
    conn = op.get_bind()
    if "case_recovery_records" in inspect(conn).get_table_names():
        for idx in list(inspect(conn).get_indexes("case_recovery_records")):
            op.drop_index(idx["name"], table_name="case_recovery_records")
        op.drop_table("case_recovery_records")
