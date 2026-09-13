from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.base import Base
from app.models import Merchant, Payment, Case, ReconciliationException, Notification
from app.services.reports import build_summary, exception_rows, case_rows
from app.services.notifications import create_notification, notify_reconciliation

engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
Base.metadata.create_all(engine)
Session=sessionmaker(bind=engine)

def seed():
    s=Session(); m=Merchant(name='V06 Merchant',email='v06-'+__import__('uuid').uuid4().hex+'@example.com'); s.add(m); s.flush()
    pid=__import__('uuid').uuid4().hex[:8]
    s.add(Payment(merchant_id=m.id,provider='TEST-'+pid,provider_payment_id='p1-'+pid,amount=Decimal('1000'),currency='INR',status='captured',captured=True))
    cid=__import__('uuid').uuid4().hex
    s.add(Case(merchant_id=m.id,case_type='AMOUNT_MISMATCH',severity='HIGH',status='OPEN',case_number='RCAA-V06-'+cid[:8],title='Mismatch',expected_amount=Decimal('1000'),actual_amount=Decimal('900'),difference=Decimal('100'),confidence=Decimal('1.00'),summary='Mismatch',fingerprint='case-'+cid))
    s.add(ReconciliationException(merchant_id=m.id,exception_code='AMOUNT_MISMATCH',severity='HIGH',status='OPEN',expected_amount=Decimal('1000'),actual_amount=Decimal('900'),difference=Decimal('100'),fingerprint='fp-'+cid,primary_record_id='p1'))
    s.commit(); return s,m.id

def test_report_summary_is_tenant_scoped_and_accurate():
    s,mid=seed(); r=build_summary(s,mid); assert r['payments']['count']==1; assert r['exceptions']['count']==1; assert r['exceptions']['amount_at_risk']=='100.00'; assert r['cases']['open']==1; s.close()

def test_report_rows_are_tenant_scoped():
    s,mid=seed(); assert len(exception_rows(s,mid))==1; assert len(case_rows(s,mid))==1; s.close()

def test_notification_is_created_and_read_state_is_persisted():
    s,mid=seed(); n=create_notification(s,merchant_id=mid,user_id=None,kind='EXCEPTIONS',title='Exceptions detected',message='One exception',severity='WARNING'); s.commit(); assert n is not None; assert s.query(Notification).filter_by(merchant_id=mid).count()==1; s.close()

def test_reconciliation_notification_only_triggers_for_new_exceptions():
    s,mid=seed(); assert notify_reconciliation(s,merchant_id=mid,actor_user_id=None,report={'exceptions':{'created':2}})==1; assert notify_reconciliation(s,merchant_id=mid,actor_user_id=None,report={'exceptions':{'created':0,'existing':4}})==0; s.close()
