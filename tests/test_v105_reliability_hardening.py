import os, sys, time
from pathlib import Path
from datetime import timedelta
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_v105_reliability.db')
os.environ.setdefault('AUTH_SECRET', 'stage10-test-secret-abcdefghijklmnopqrstuvwxyz-123456')
os.environ.setdefault('AUTH_BOOTSTRAP_TOKEN', 'stage10-bootstrap-token')
os.environ.setdefault('AI_PROVIDER', 'mock')
os.environ['JOB_RETRY_BASE_SECONDS'] = '0'
os.environ['JOB_RETRY_MAX_SECONDS'] = '0'
os.environ['JOB_LEASE_SECONDS'] = '6'

from sqlalchemy import select
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models import Merchant, User, Job
from app.security import hash_password
from app.jobs import JobStatus
from app.jobs_service import create_job, claim_job, recover_stale_jobs
import app.jobs_worker as worker


def reset():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.add(Merchant(id='m-v105', name='V105', email='v105@example.local'))
        s.add(User(id='u-v105', email='u-v105@example.local', password_hash=hash_password('Password123!'), merchant_id='m-v105', role='ADMIN', is_active=True))
        s.commit()


def make_job():
    with SessionLocal() as s:
        j, _ = create_job(s, merchant_id='m-v105', job_type='RUN_RECONCILIATION', payload={}, idempotency_key='v105', created_by='u-v105', request_id='req-v105', actor_role='ADMIN')
        s.commit(); return j.job_id


def test_active_long_job_refreshes_lease():
    reset(); jid = make_job()
    with SessionLocal() as s:
        j = claim_job(s, worker_id='worker-v105', lease_seconds=6)
        assert j is not None
    original = worker._process
    worker._process = lambda session, job: (time.sleep(5.5) or {'ok': True})
    try:
        # The heartbeat runs at roughly lease/3 and should extend the lease before expiry.
        status = worker.execute_claimed_job(jid, worker_id='worker-v105')
        assert status == JobStatus.SUCCEEDED.value
    finally:
        worker._process = original


def test_stale_recovery_counts_recovered_jobs_metric():
    reset(); jid = make_job()
    with SessionLocal() as s:
        j = claim_job(s, worker_id='dead-v105', lease_seconds=1)
        from app.core.time import utc_now
        j.lease_expires_at = utc_now() - timedelta(seconds=5); s.commit()
        assert recover_stale_jobs(s, stale_before=utc_now()) == 1
    from app.observability.metrics import render_prometheus
    assert 'jobs_stale_recovered_total 1' in render_prometheus()


def test_production_compose_has_resource_and_shutdown_guardrails():
    root = Path(__file__).parents[1]
    compose = (root / 'docker-compose.prod.yml').read_text()
    assert 'mem_limit:' in compose and 'cpus:' in compose and 'pids_limit:' in compose
    assert 'stop_grace_period:' in compose
    assert 'RCAA_BACKEND_IMAGE' in compose and 'RCAA_FRONTEND_IMAGE' in compose


def test_release_and_backup_controls_exist():
    root = Path(__file__).parents[1]
    for name in ['scripts/verify_backup.sh', 'scripts/release_health_gate.sh', 'scripts/rollback_production.sh']:
        p = root / name; assert p.exists() and os.access(p, os.X_OK)
    assert 'sha256sum' in (root / 'scripts/backup_postgres.sh').read_text()
    assert 'pg_restore --list' in (root / 'scripts/verify_backup.sh').read_text()


def test_alert_rules_cover_api_jobs_and_worker_recovery():
    text = (Path(__file__).parents[1] / 'deploy/prometheus-alerts.yml').read_text()
    assert 'RCAAAPIHigh5xx' in text
    assert 'RCAAAPIHighLatency' in text
    assert 'RCAAJobDeadLettered' in text
    assert 'RCAAStaleJobs' in text
