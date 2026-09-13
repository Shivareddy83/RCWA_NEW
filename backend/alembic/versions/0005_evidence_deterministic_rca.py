from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
revision='0005'; down_revision='0004'; branch_labels=None; depends_on=None

def upgrade():
    conn=op.get_bind(); insp=inspect(conn)
    cols={c['name'] for c in insp.get_columns('rca_evidence')}
    for name,typ in [('source_entity_type',sa.String()),('captured_at',sa.DateTime(timezone=True)),('relevance',sa.Text()),('snapshot_json',sa.JSON()),('fingerprint',sa.String())]:
        if name not in cols: op.add_column('rca_evidence',sa.Column(name,typ,nullable=True))
    idx={i['name'] for i in insp.get_indexes('rca_evidence')}
    for name,columns,unique in [('ix_evidence_case_type',['reconciliation_case_id','evidence_type'],False),('ix_evidence_source_entity',['source_entity_type','source_record_id'],False),('uq_evidence_fingerprint',['fingerprint'],True)]:
        if name not in idx: op.create_index(name,'rca_evidence',columns,unique=unique)
    cols={c['name'] for c in inspect(conn).get_columns('rca_results')}
    for name,typ in [('exception_id',sa.String()),('root_cause_category',sa.String()),('confidence_label',sa.String()),('evidence_ids_json',sa.JSON()),('engine_version',sa.String()),('fingerprint',sa.String()),('generated_at',sa.DateTime(timezone=True))]:
        if name not in cols: op.add_column('rca_results',sa.Column(name,typ,nullable=True))
    idx={i['name'] for i in inspect(conn).get_indexes('rca_results')}
    for name,columns,unique in [('ix_rca_root_cause',['root_cause'],False),('ix_rca_engine_version',['engine_version'],False),('ix_rca_case_fingerprint',['reconciliation_case_id','fingerprint'],True)]:
        if name not in idx: op.create_index(name,'rca_results',columns,unique=unique)
    op.execute("UPDATE rca_evidence SET captured_at=COALESCE(captured_at,CURRENT_TIMESTAMP), relevance=COALESCE(relevance,description), snapshot_json=COALESCE(snapshot_json,metadata_json), fingerprint=COALESCE(fingerprint,id)")
    op.execute("UPDATE rca_results SET root_cause_category=COALESCE(root_cause_category,'UNKNOWN'), confidence_label=COALESCE(confidence_label,CASE WHEN confidence>=0.9 THEN 'HIGH' WHEN confidence>=0.7 THEN 'MEDIUM' WHEN confidence>0 THEN 'LOW' ELSE 'UNKNOWN' END), evidence_ids_json=COALESCE(evidence_ids_json,'[]'), engine_version=COALESCE(engine_version,'rca-v1'), fingerprint=COALESCE(fingerprint,id), generated_at=COALESCE(generated_at,created_at)")
    if 'rca_result_history' not in inspect(conn).get_table_names():
        op.create_table('rca_result_history',sa.Column('id',sa.String(),primary_key=True),sa.Column('reconciliation_case_id',sa.String(),sa.ForeignKey('reconciliation_cases.id'),nullable=False),sa.Column('exception_id',sa.String()),sa.Column('root_cause',sa.String(),nullable=False),sa.Column('root_cause_category',sa.String(),nullable=False),sa.Column('confidence_label',sa.String(),nullable=False),sa.Column('explanation',sa.Text(),nullable=False),sa.Column('recommended_action',sa.Text(),nullable=False),sa.Column('evidence_ids_json',sa.JSON(),nullable=False),sa.Column('engine_version',sa.String(),nullable=False),sa.Column('fingerprint',sa.String(),nullable=False),sa.Column('generated_at',sa.DateTime(timezone=True)),sa.Column('archived_at',sa.DateTime(timezone=True)))
        op.create_index('ix_rca_history_case','rca_result_history',['reconciliation_case_id','archived_at'])

def downgrade():
    conn=op.get_bind(); dialect=conn.dialect.name
    if 'rca_result_history' in inspect(conn).get_table_names(): op.drop_table('rca_result_history')
    if dialect == 'sqlite':
        # SQLite cannot safely drop FK columns in-place; rebuild each table with the Stage 04 shape.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("CREATE TABLE rca_results_stage04 AS SELECT id,reconciliation_case_id,root_cause,explanation,confidence,recommended_action,created_at FROM rca_results")
        conn.exec_driver_sql("DROP TABLE rca_results")
        conn.exec_driver_sql("ALTER TABLE rca_results_stage04 RENAME TO rca_results")
        conn.exec_driver_sql("CREATE UNIQUE INDEX uq_rca_results_case ON rca_results(reconciliation_case_id)")
        conn.exec_driver_sql("CREATE TABLE rca_evidence_stage04 AS SELECT id,reconciliation_case_id,evidence_type,source_record_id,description,metadata_json FROM rca_evidence")
        conn.exec_driver_sql("DROP TABLE rca_evidence")
        conn.exec_driver_sql("ALTER TABLE rca_evidence_stage04 RENAME TO rca_evidence")
        conn.exec_driver_sql("CREATE INDEX ix_rca_evidence_case ON rca_evidence(reconciliation_case_id)")
        conn.exec_driver_sql("CREATE INDEX ix_rca_evidence_type ON rca_evidence(evidence_type)")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        return
    # Non-SQLite fallback. Remove Stage 05 indexes first, then use Alembic's table recreation.
    for table, columns in {'rca_results': {'generated_at','fingerprint','engine_version','evidence_ids_json','confidence_label','root_cause_category','exception_id'}, 'rca_evidence': {'fingerprint','snapshot_json','relevance','captured_at','source_entity_type'}}.items():
        for item in list(inspect(conn).get_indexes(table)):
            if set(item.get('column_names') or []) & columns:
                try: op.drop_index(item['name'], table_name=table)
                except Exception: pass
    with op.batch_alter_table('rca_results', recreate='always') as batch:
        for name in ['generated_at','fingerprint','engine_version','evidence_ids_json','confidence_label','root_cause_category','exception_id']: batch.drop_column(name)
    with op.batch_alter_table('rca_evidence', recreate='always') as batch:
        for name in ['fingerprint','snapshot_json','relevance','captured_at','source_entity_type']: batch.drop_column(name)
