"""Idempotently load eight representative RCAA records."""
import sys
from pathlib import Path
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from app.db.session import SessionLocal, engine
from app.models import Payment, Refund, Settlement, Merchant, User
from app.reconciliation.engine import run_reconciliation
from app.core.time import utc_now
from decimal import Decimal
from app.security import hash_password
s=SessionLocal(); now=utc_now()
merchant=s.query(Merchant).filter_by(id='demo-merchant-a').first()
if not merchant:
 merchant=Merchant(id='demo-merchant-a',name='Demo Merchant A',email='merchant-a@example.local'); s.add(merchant); s.flush()
for uid,email,role,pwd in [('demo-admin','admin@demo.local','ADMIN','DemoAdminPass123!'),('demo-ops','ops@demo.local','OPS','DemoOpsPass123!'),('demo-analyst','analyst@demo.local','ANALYST','DemoAnalystPass123!'),('demo-viewer','viewer@demo.local','VIEWER','DemoViewerPass123!')]:
 if not s.query(User).filter_by(id=uid).first(): s.add(User(id=uid,email=email,password_hash=hash_password(pwd),merchant_id=merchant.id,role=role,is_active=True))
s.flush()
def payment(pid,amount,status='captured',order=None,**raw):
 if not s.query(Payment).filter_by(provider='demo',provider_payment_id=pid).first():s.add(Payment(provider='demo',provider_payment_id=pid,provider_order_id=order or 'order_'+pid,amount=Decimal(amount),currency='INR',status=status,method='card',captured=status=='captured',created_at=now,raw_data=raw))
def settlement(pid,net,fee='0',tax='0',days=1):
 sid='set_'+pid
 if not s.query(Settlement).filter_by(provider='demo',provider_settlement_id=sid).first():s.add(Settlement(provider='demo',provider_settlement_id=sid,provider_payment_id=pid,gross_amount=Decimal(net)+Decimal(fee)+Decimal(tax),fee=Decimal(fee),tax=Decimal(tax),net_amount=Decimal(net),status='processed',settled_at=now+timedelta(days=days),raw_data={}))
def refund(pid,amount):
 rid='ref_'+pid
 if not s.query(Refund).filter_by(provider='demo',provider_refund_id=rid).first():s.add(Refund(provider='demo',provider_refund_id=rid,provider_payment_id=pid,amount=Decimal(amount),status='processed',created_at=now,processed_at=now,raw_data={}))
payment('pay_matched','1000'); settlement('pay_matched','1000')
payment('pay_refund_adjusted','2500'); refund('pay_refund_adjusted','500'); settlement('pay_refund_adjusted','2000')
payment('pay_settlement_mismatch','10000'); settlement('pay_settlement_mismatch','9000')
payment('pay_missing_refund','5000',expected_refund=True); settlement('pay_missing_refund','5000')
payment('pay_duplicate','750',order='order_duplicate'); settlement('pay_duplicate','750')
payment('pay_duplicate_second','750',order='order_duplicate'); settlement('pay_duplicate_second','750')
payment('pay_delayed','2000'); settlement('pay_delayed','2000',days=5)
payment('pay_status','3000',status='failed'); settlement('pay_status','3000')
payment('pay_fee_tax','10000'); settlement('pay_fee_tax','9850','100','50')
payment('pay_unknown','1250'); settlement('pay_unknown','1200')
payment('pay_ambiguous','1100',order='unique_ambiguous'); settlement('pay_ambiguous_candidate_1','1100',days=0); settlement('pay_ambiguous_candidate_2','1100',days=0)
s.commit()
# Keep all synthetic demo financial records in the demo merchant tenant.
s.query(Payment).update({Payment.merchant_id: merchant.id}, synchronize_session=False)
s.query(Refund).update({Refund.merchant_id: merchant.id}, synchronize_session=False)
s.query(Settlement).update({Settlement.merchant_id: merchant.id}, synchronize_session=False)
s.commit()
# Duplicate provider IDs are intentionally represented in raw source evidence: relational unique constraints prevent corrupt duplicate ingestion.
run_reconciliation(s); print('Demo data ready.')
