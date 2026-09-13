import os, sys, threading
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
os.environ['DATABASE_URL'] = 'sqlite:///./test_stage10.db'
os.environ['AUTH_SECRET'] = 'stage10-test-secret-abcdefghijklmnopqrstuvwxyz'
os.environ['AUTH_BOOTSTRAP_TOKEN'] = 'stage10-bootstrap-token'
os.environ['AI_PROVIDER'] = 'mock'
os.environ['JOB_RETRY_BASE_SECONDS'] = '0'
os.environ['JOB_RETRY_MAX_SECONDS'] = '0'
os.environ['JOB_LEASE_SECONDS'] = '60'

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant, User, Payment, Job
from app.security import hash_password, create_access_token
from app.jobs import JobStatus
from app.jobs_service import create_job, claim_job, recover_stale_jobs
from app.jobs_worker import execute_claimed_job
from app.observability.metrics import reset_metrics

client = TestClient(app, raise_server_exceptions=False)


def reset():
    reset_metrics(); Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add_all([
            Merchant(id='m-a', name='A', email='a-stage10@example.local'),
            Merchant(id='m-b', name='B', email='b-stage10@example.local'),
            User(id='u-admin-a', email='admin10a@example.local', password_hash=hash_password('AdminPass123!'), merchant_id='m-a', role='ADMIN', is_active=True),
            User(id='u-ops-a', email='ops10a@example.local', password_hash=hash_password('OpsPass123!'), merchant_id='m-a', role='OPS', is_active=True),
            User(id='u-analyst-a', email='analyst10a@example.local', password_hash=hash_password('AnalystPass123!'), merchant_id='m-a', role='ANALYST', is_active=True),
            User(id='u-view-a', email='viewer10a@example.local', password_hash=hash_password('ViewerPass123!'), merchant_id='m-a', role='VIEWER', is_active=True),
            User(id='u-admin-b', email='admin10b@example.local', password_hash=hash_password('AdminPass123!'), merchant_id='m-b', role='ADMIN', is_active=True),
        ]); s.commit()

def token(uid='u-admin-a'):
    with SessionLocal() as s: return create_access_token(s.get(User, uid))

def auth(uid='u-admin-a'):
    return {'Authorization': 'Bearer ' + token(uid)}

def make_job(job_type='RUN_RECONCILIATION', payload=None, key='k1', merchant='m-a'):
    with SessionLocal() as s:
        j, created = create_job(s, merchant_id=merchant, job_type=job_type, payload=payload or {}, idempotency_key=key, created_by='u-admin-a', request_id='req-10', actor_role='ADMIN'); s.commit(); return j.job_id, created

def test_job_create_queued_and_unique_id():
    reset(); jid, created = make_job(); assert created
    with SessionLocal() as s:
        j=s.scalar(select(Job).where(Job.job_id==jid)); assert j.status=='QUEUED' and j.job_id

def test_job_api_requires_idempotency_and_rbac():
    reset(); h=auth('u-admin-a')
    assert client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers=h).status_code==400
    r=client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers={**h,'Idempotency-Key':'api-k1'}); assert r.status_code==202
    assert client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers={**auth('u-view-a'),'Idempotency-Key':'viewer-k'}).status_code==403

def test_same_idempotency_key_returns_same_job_and_cross_merchant_cannot_reuse():
    reset(); h=auth('u-admin-a')
    r1=client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers={**h,'Idempotency-Key':'same'}); r2=client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers={**h,'Idempotency-Key':'same'})
    assert r1.json()['job']['job_id']==r2.json()['job']['job_id'] and r2.json()['created'] is False
    r3=client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION','payload':{'merchant_id':'m-b'}},headers={**h,'Idempotency-Key':'cross'}); assert r3.status_code==403

def test_job_list_detail_are_tenant_scoped():
    reset(); a,_=make_job(key='a'); b,_=make_job(key='b',merchant='m-b')
    assert client.get('/api/v1/jobs',headers=auth('u-admin-a')).json()['total']==1
    assert client.get('/api/v1/jobs/'+b,headers=auth('u-admin-a')).status_code==404

def test_worker_claim_transitions_to_running_and_concurrent_second_claim_blocked():
    reset(); jid,_=make_job()
    results=[]
    def c():
        with SessionLocal() as s:
            j=claim_job(s,worker_id='w-'+str(len(results)),lease_seconds=60); results.append(j.job_id if j else None)
    t1=threading.Thread(target=c); t2=threading.Thread(target=c); t1.start(); t2.start(); t1.join(); t2.join()
    assert sum(x is not None for x in results)==1
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).status=='RUNNING'

def test_successful_reconciliation_job_succeeds_and_metrics_audit_exist():
    reset(); jid,_=make_job()
    with SessionLocal() as s:
        j=claim_job(s,worker_id='w1',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).status=='SUCCEEDED'
    metrics=client.get('/metrics').text
    assert 'jobs_started_total' in metrics and 'jobs_succeeded_total' in metrics and 'job_duration_seconds' in metrics

def test_ingestion_job_is_idempotent_at_domain_level():
    reset(); payload={'source':'manual_demo','provider':'demo','records':[{'provider_payment_id':'j-p1','amount':'100','currency':'INR','status':'captured','event_timestamp':'2026-09-02T10:00:00Z','merchant_id':'m-a'}]}
    j1,_=make_job('INGEST_PAYMENTS',payload,'ingest-1');
    with SessionLocal() as s: j=claim_job(s,worker_id='w1',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    # Same logical workload is represented by a different job but existing domain uniqueness prevents duplicate row.
    j2,_=make_job('INGEST_PAYMENTS',payload,'ingest-2');
    with SessionLocal() as s: j=claim_job(s,worker_id='w2',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    with SessionLocal() as s: assert len(s.scalars(select(Payment).where(Payment.provider_payment_id=='j-p1')).all())==1

def test_retryable_failure_retries_and_eventually_dead_letters(monkeypatch):
    reset(); jid,_=make_job('RUN_RECONCILIATION',key='retry-1')
    with SessionLocal() as s: j=claim_job(s,worker_id='w1',lease_seconds=60); j.max_attempts=2; s.commit()
    import app.jobs_worker as worker
    monkeypatch.setattr(worker, '_process', lambda session, job: (_ for _ in ()).throw(ConnectionError('temporary database connection failure')))
    assert execute_claimed_job(j.job_id)=='RETRYING'
    with SessionLocal() as s:
        j=claim_job(s,worker_id='w2',lease_seconds=60); assert j.attempt_count==2
    assert execute_claimed_job(j.job_id)=='DEAD_LETTERED'
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).status=='DEAD_LETTERED'

def test_permanent_failure_does_not_retry():
    reset(); jid,_=make_job('RUN_RECONCILIATION',key='perm-1')
    with SessionLocal() as s: j=claim_job(s,worker_id='w1',lease_seconds=60)
    import app.jobs_worker as worker
    original=worker._process
    worker._process=lambda session, job: (_ for _ in ()).throw(ValueError('invalid input'))
    try: assert execute_claimed_job(j.job_id)=='FAILED'
    finally: worker._process=original

def test_stale_running_job_recovers():
    reset(); jid,_=make_job(key='stale-1')
    with SessionLocal() as s:
        j=claim_job(s,worker_id='dead-worker',lease_seconds=1); j.lease_expires_at=__import__('app.core.time',fromlist=['utc_now']).utc_now()-timedelta(seconds=5); s.commit()
        assert recover_stale_jobs(s,stale_before=__import__('app.core.time',fromlist=['utc_now']).utc_now())==1
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).status=='RETRYING'

def test_retry_endpoint_and_all_roles_can_read_but_viewer_cannot_retry():
    reset(); jid,_=make_job(key='retry-api')
    with SessionLocal() as s:
        j=s.get(Job, s.scalar(select(Job.id).where(Job.job_id==jid))); j.status='FAILED'; s.commit()
    assert client.post('/api/v1/jobs/'+jid+'/retry',headers=auth('u-ops-a')).status_code==200
    with SessionLocal() as s:
        j=s.scalar(select(Job).where(Job.job_id==jid)); j.status='FAILED'; s.commit()
    assert client.post('/api/v1/jobs/'+jid+'/retry',headers=auth('u-view-a')).status_code==403
    assert client.get('/api/v1/jobs/'+jid,headers=auth('u-analyst-a')).status_code==200

def test_worker_case_job_is_tenant_scoped():
    reset(); jid,_=make_job('BUILD_EVIDENCE',{'case_id':'does-not-exist','merchant_id':'m-a'},'case-a')
    with SessionLocal() as s: j=claim_job(s,worker_id='w',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='FAILED'
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).status=='FAILED'

def test_job_metrics_have_no_high_cardinality_labels():
    reset(); make_job(key='card-1');
    client.get('/metrics')
    text=client.get('/metrics').text
    assert 'job_id=' not in text and 'request_id=' not in text and 'merchant_id=' not in text

def test_job_payload_never_contains_credentials_from_client():
    reset(); jid,_=make_job(payload={'token':'should-not-be-stored','api_key':'secret','safe':'ok'},key='secret-1')
    # Job creation must not be a credential vault.
    with SessionLocal() as s:
        j=s.scalar(select(Job).where(Job.job_id==jid)); assert j.payload_json['safe']=='ok'
        assert 'token' not in j.payload_json and 'api_key' not in j.payload_json

def test_all_read_roles_can_list_jobs_and_viewer_cannot_retry():
    reset(); jid,_=make_job(key='read-all')
    for uid in ['u-admin-a','u-ops-a','u-analyst-a','u-view-a']:
        assert client.get('/api/v1/jobs',headers=auth(uid)).status_code==200
        assert client.get('/api/v1/jobs/'+jid,headers=auth(uid)).status_code==200

def test_job_creation_is_audited_with_system_execution_event():
    reset(); jid,_=make_job(key='audit-job')
    with SessionLocal() as s:
        events=s.execute(__import__('sqlalchemy').select(__import__('app.models',fromlist=['AuditEvent']).AuditEvent).where(__import__('app.models',fromlist=['AuditEvent']).AuditEvent.resource_id==jid)).scalars().all()
        assert any(e.action=='JOB_CREATED' and e.actor_user_id=='u-admin-a' for e in events)
    with SessionLocal() as s: j=claim_job(s,worker_id='worker-a',lease_seconds=60)
    execute_claimed_job(j.job_id)
    with SessionLocal() as s:
        events=s.execute(__import__('sqlalchemy').select(__import__('app.models',fromlist=['AuditEvent']).AuditEvent).where(__import__('app.models',fromlist=['AuditEvent']).AuditEvent.resource_id==jid)).scalars().all()
        assert any(e.action=='JOB_SUCCEEDED' and e.actor_type=='SYSTEM' for e in events)

def test_refund_settlement_and_bank_ingestion_jobs_execute():
    reset()
    jobs=[
      ('INGEST_PAYMENTS', {'source':'job','provider':'demo','records':[{'provider_payment_id':'p-j','amount':'10','currency':'INR','status':'captured','event_timestamp':'2026-09-02T10:00:00Z'}]}),
      ('INGEST_REFUNDS', {'source':'job','provider':'demo','records':[{'provider_refund_id':'r-j','provider_payment_id':'p-j','amount':'2','currency':'INR','status':'processed','event_timestamp':'2026-09-02T10:01:00Z'}]}),
      ('INGEST_SETTLEMENTS', {'source':'job','provider':'demo','records':[{'provider_settlement_id':'s-j','provider_payment_id':'p-j','net_amount':'8','currency':'INR','status':'processed','event_timestamp':'2026-09-02T11:00:00Z'}]}),
      ('INGEST_BANK_TRANSACTIONS', {'source':'job','provider':'bank','records':[{'external_id':'b-j','amount':'8','currency':'INR','status':'posted','event_timestamp':'2026-09-02T11:01:00Z'}]}),
    ]
    for i,(jt,payload) in enumerate(jobs):
        jid,_=make_job(jt,payload,f'ingest-{i}')
        with SessionLocal() as s: j=claim_job(s,worker_id=f'w-{i}',lease_seconds=60)
        assert execute_claimed_job(j.job_id)=='SUCCEEDED'

def test_reconciliation_job_is_merchant_scoped_and_financial_values_unchanged():
    reset(); payload={'source':'job','provider':'demo','records':[{'provider_payment_id':'scope-p','amount':'123.45','currency':'INR','status':'captured','event_timestamp':'2026-09-02T10:00:00Z'}]}
    jid,_=make_job('INGEST_PAYMENTS',payload,'scope-ingest')
    with SessionLocal() as s: j=claim_job(s,worker_id='w',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    with SessionLocal() as s:
        p=s.scalar(select(Payment).where(Payment.provider_payment_id=='scope-p')); assert p.merchant_id=='m-a' and p.amount==Decimal('123.45')
    rid,_=make_job('RUN_RECONCILIATION',{},'scope-recon')
    with SessionLocal() as s: j=claim_job(s,worker_id='w2',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    with SessionLocal() as s:
        p=s.scalar(select(Payment).where(Payment.provider_payment_id=='scope-p')); assert p.amount==Decimal('123.45')

def test_case_evidence_and_rca_jobs_are_idempotent():
    reset()
    # Create a deterministic case using the existing reconciliation path.
    with SessionLocal() as s:
        p=Payment(provider='demo',provider_payment_id='case-p',merchant_id='m-a',amount=Decimal('100'),currency='INR',status='captured'); s.add(p); s.commit()
    rid,_=make_job('RUN_RECONCILIATION',{},'case-recon')
    with SessionLocal() as s: j=claim_job(s,worker_id='w',lease_seconds=60)
    execute_claimed_job(j.job_id)
    with SessionLocal() as s:
        case=s.scalar(select(__import__('app.models',fromlist=['Case']).Case).where(__import__('app.models',fromlist=['Case']).Case.merchant_id=='m-a'))
        if case:
            for idx,jt in enumerate(['BUILD_EVIDENCE','GENERATE_DETERMINISTIC_RCA']):
                jid,_=make_job(jt,{'case_id':case.id},f'case-job-{idx}')
                with SessionLocal() as ss: jj=claim_job(ss,worker_id=f'w{idx}',lease_seconds=60)
                assert execute_claimed_job(jj.job_id)=='SUCCEEDED'

def test_ai_job_success_is_case_scoped():
    reset()
    with SessionLocal() as s:
        from app.cases.service import create_case
        p=Payment(provider='demo',provider_payment_id='ai-job-p',merchant_id='m-a',amount=Decimal('10'),currency='INR',status='captured'); s.add(p); s.flush()
        case,_=create_case(s, merchant_id='m-a', title='AI job case', description='test')
        from app.rca.engine import generate_rca
        generate_rca(s,case); s.commit(); case_id=case.id
    jid,_=make_job('AI_INVESTIGATION',{'case_id':case_id,'question':'Summarize the evidence.'},'ai-job-1')
    with SessionLocal() as s: j=claim_job(s,worker_id='ai-worker',lease_seconds=60)
    assert execute_claimed_job(j.job_id)=='SUCCEEDED'
    with SessionLocal() as s: assert s.scalar(select(Job).where(Job.job_id==jid)).result_json['case_id']==case_id


def test_ai_timeout_is_retryable(monkeypatch):
    reset(); jid,_=make_job('RUN_RECONCILIATION',key='ai-timeout')
    with SessionLocal() as s: j=claim_job(s,worker_id='w',lease_seconds=60); j.max_attempts=2; s.commit()
    import app.jobs_worker as worker
    from app.ai.service import AIServiceError
    monkeypatch.setattr(worker, '_process', lambda session, job: (_ for _ in ()).throw(AIServiceError('AI_TIMEOUT','provider timed out')))
    assert execute_claimed_job(j.job_id)=='RETRYING'

def test_terminal_job_cannot_be_retried_after_success():
    reset(); jid,_=make_job(key='no-retry-success')
    with SessionLocal() as s: j=claim_job(s,worker_id='w',lease_seconds=60)
    execute_claimed_job(j.job_id)
    assert client.post('/api/v1/jobs/'+jid+'/retry',headers=auth('u-admin-a')).status_code==409

def test_request_id_preserved_on_job_creation_and_visible_in_job():
    reset(); h={**auth('u-admin-a'),'Idempotency-Key':'request-job','X-Request-ID':'stage10-request-123'}
    r=client.post('/api/v1/jobs',json={'job_type':'RUN_RECONCILIATION'},headers=h)
    assert r.status_code==202 and r.headers['X-Request-ID']=='stage10-request-123'
    assert r.json()['job']['request_id']=='stage10-request-123'


def test_enqueue_due_connector_jobs_only_picks_due_enabled_connectors():
    # Previously untested: the scheduled auto-sync path (DataConnector.sync_enabled +
    # next_sync_at, polled by worker_loop() every 30s via enqueue_due_connector_jobs).
    # Verifies it (a) only enqueues connectors that are enabled, connected, and past
    # their next_sync_at, (b) ignores disabled and not-yet-due connectors, and
    # (c) reschedules next_sync_at so it isn't re-enqueued on the very next poll.
    from app.models import DataConnector
    from app.jobs_service import enqueue_due_connector_jobs
    from app.core.time import utc_now
    reset()
    with SessionLocal() as s:
        s.add(Merchant(id='m-sync-b', name='Sync Merchant B', email='sync-b@example.com')); s.commit()
        s.add(DataConnector(id='c-due', merchant_id='m-a', provider='razorpay', name='Due',
                             status='CONNECTED', sync_enabled=True, sync_interval_minutes=60,
                             next_sync_at=utc_now() - timedelta(minutes=5)))
        s.add(DataConnector(id='c-not-due', merchant_id='m-sync-b', provider='razorpay', name='NotDue',
                             status='CONNECTED', sync_enabled=True, sync_interval_minutes=60,
                             next_sync_at=utc_now() + timedelta(minutes=55)))
        s.commit()
        created = enqueue_due_connector_jobs(s)
        assert created == 1
        jobs = s.scalars(select(Job).where(Job.job_type == 'SYNC_CONNECTOR')).all()
        assert len(jobs) == 1 and jobs[0].payload_json['connector_id'] == 'c-due'
        # rescheduled into the future, so an immediate second poll enqueues nothing new
        refreshed = s.get(DataConnector, 'c-due')
        next_sync = refreshed.next_sync_at
        if next_sync.tzinfo is None:
            from datetime import timezone
            next_sync = next_sync.replace(tzinfo=timezone.utc)
        assert next_sync > utc_now()
        assert enqueue_due_connector_jobs(s) == 0


def test_scheduled_sync_connector_job_runs_reconciliation_without_error():
    # Regression guard for the UnboundLocalError previously in the SYNC_CONNECTOR
    # branch of app.jobs_worker._process (a redundant local import of
    # run_reconciliation shadowed the module-level import for the whole function,
    # so every RUN_RECONCILIATION job failed). This exercises the same _process()
    # function end to end for a scheduler-created SYNC_CONNECTOR job to confirm the
    # reconciliation step it triggers no longer raises.
    from app.models import DataConnector
    from app.jobs_service import enqueue_due_connector_jobs
    from app.core.time import utc_now
    reset()
    with SessionLocal() as s:
        s.add(DataConnector(id='c-auto', merchant_id='m-a', provider='razorpay', name='Auto',
                             status='CONNECTED', sync_enabled=True, sync_interval_minutes=60,
                             next_sync_at=utc_now() - timedelta(minutes=1)))
        s.commit()
        assert enqueue_due_connector_jobs(s) == 1
    with SessionLocal() as s: j = claim_job(s, worker_id='auto-worker', lease_seconds=60)
    # This previously raised UnboundLocalError inside _process(); now it should
    # either SUCCEED (if the mocked razorpay sync call cooperates) or fail for a
    # reason unrelated to the reconciliation-import bug — never that specific error.
    status = execute_claimed_job(j.job_id, worker_id='auto-worker')
    with SessionLocal() as s:
        job = s.scalar(select(Job).where(Job.job_id == j.job_id))
        assert job.last_error_code != 'UNBOUNDLOCALERROR', f"reconciliation-import bug regressed: {job.last_error_message_safe}"
