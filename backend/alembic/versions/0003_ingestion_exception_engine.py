"""multi-source ingestion and deterministic exceptions

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
revision="0003"; down_revision="0002"; branch_labels=None; depends_on=None

def _tables(): return set(sa.inspect(op.get_bind()).get_table_names())
def _cols(table): return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
def _add(table,name,typ,nullable=True,default=None):
    if name not in _cols(table): op.add_column(table,sa.Column(name,typ,nullable=nullable,server_default=sa.text(repr(default)) if default is not None else None))
def _idx(table,name,col):
    if name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}: op.create_index(name,table,[col])

def upgrade():
    tables=_tables()
    if "ingestion_batches" not in tables:
        op.create_table("ingestion_batches",sa.Column("id",sa.String(),primary_key=True),sa.Column("source",sa.String(),nullable=False),sa.Column("provider",sa.String()),sa.Column("started_at",sa.DateTime(timezone=True),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)),sa.Column("status",sa.String(),nullable=False,server_default="STARTED"),sa.Column("received_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("created_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("updated_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("duplicate_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("rejected_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("error_summary",sa.Text()))
    _add("ingestion_batches","record_type",sa.String())
    _add("ingestion_batches","duplicate_records_json",sa.JSON(),False,"[]")
    for table in ("payments","refunds","settlements"):
        _add(table,"source",sa.String(),False,"manual_demo"); _add(table,"external_id",sa.String()); _add(table,"ingestion_batch_id",sa.String()); _add(table,"received_at",sa.DateTime(timezone=True)); _add(table,"raw_reference",sa.String())
    if "bank_transactions" not in tables:
        op.create_table("bank_transactions",sa.Column("id",sa.String(),primary_key=True),sa.Column("source",sa.String(),nullable=False,server_default="bank_csv"),sa.Column("provider",sa.String()),sa.Column("external_id",sa.String(),nullable=False),sa.Column("merchant_id",sa.String(),sa.ForeignKey("merchants.id")),sa.Column("reference",sa.String()),sa.Column("amount",sa.Numeric(14,2),nullable=False),sa.Column("currency",sa.String(),nullable=False,server_default="INR"),sa.Column("status",sa.String(),nullable=False,server_default="posted"),sa.Column("event_timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("received_at",sa.DateTime(timezone=True),nullable=False),sa.Column("ingestion_batch_id",sa.String()),sa.Column("raw_reference",sa.String()),sa.Column("metadata_json",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),sa.UniqueConstraint("source","external_id",name="uq_bank_source_external"))
    if "reconciliation_exceptions" not in tables:
        op.create_table("reconciliation_exceptions",sa.Column("id",sa.String(),primary_key=True),sa.Column("reconciliation_case_id",sa.String(),sa.ForeignKey("reconciliation_cases.id"),nullable=True,unique=True),sa.Column("exception_code",sa.String(),nullable=False),sa.Column("severity",sa.String(),nullable=False),sa.Column("status",sa.String(),nullable=False,server_default="OPEN"),sa.Column("source",sa.String()),sa.Column("merchant_id",sa.String()),sa.Column("primary_record_id",sa.String()),sa.Column("related_record_id",sa.String()),sa.Column("expected_amount",sa.Numeric(14,2),nullable=False),sa.Column("actual_amount",sa.Numeric(14,2),nullable=False),sa.Column("difference",sa.Numeric(14,2),nullable=False),sa.Column("evidence_json",sa.JSON(),nullable=False,server_default=sa.text("'{}'")),sa.Column("fingerprint",sa.String(),nullable=False,unique=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("acknowledged_at",sa.DateTime(timezone=True)),sa.Column("resolved_at",sa.DateTime(timezone=True)))
    for table,col in [("ingestion_batches","source"),("ingestion_batches","record_type"),("ingestion_batches","provider"),("ingestion_batches","status"),("payments","source"),("payments","external_id"),("payments","ingestion_batch_id"),("refunds","source"),("refunds","external_id"),("refunds","ingestion_batch_id"),("settlements","source"),("settlements","external_id"),("settlements","ingestion_batch_id"),("bank_transactions","source"),("bank_transactions","external_id"),("bank_transactions","reference"),("bank_transactions","ingestion_batch_id"),("reconciliation_exceptions","exception_code"),("reconciliation_exceptions","severity"),("reconciliation_exceptions","status"),("reconciliation_exceptions","source"),("reconciliation_exceptions","merchant_id"),("reconciliation_exceptions","primary_record_id"),("reconciliation_exceptions","related_record_id"),("reconciliation_exceptions","fingerprint")]: _idx(table,"ix_%s_%s"%(table,col),col)

def downgrade():
    tables=_tables()
    if "reconciliation_exceptions" in tables: op.drop_table("reconciliation_exceptions")
    if "bank_transactions" in tables: op.drop_table("bank_transactions")
    for table in ("settlements","refunds","payments"):
        for col in ("raw_reference","received_at","ingestion_batch_id","external_id","source"):
            if col in _cols(table): op.drop_column(table,col)
    if "ingestion_batches" in tables: op.drop_table("ingestion_batches")
