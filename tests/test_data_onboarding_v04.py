import os
import sys
from pathlib import Path

os.environ['DATABASE_URL'] = 'sqlite:///./test_rcaa_v04_uploads.db'
os.environ['RAZORPAY_WEBHOOK_SECRET'] = 'test_secret'
os.environ['TESTING'] = '1'
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))

from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.db.session import SessionLocal
from app.models import Merchant

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
client = TestClient(app)


def setup_module():
    with SessionLocal() as session:
        session.add(Merchant(id='v04-merchant', name='V04 Demo', email='v04@example.com'))
        session.commit()


def test_csv_upload_suggests_mapping_and_validates():
    content = b"payment_id,order_id,amount,currency,status,created_at\npay-1,ord-1,100.00,INR,captured,2026-09-08T10:00:00+00:00\n"
    response = client.post('/api/v1/data-onboarding/uploads', params={'data_type': 'payments', 'provider': 'razorpay'}, files={'file': ('payments.csv', content, 'text/csv')})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['status'] == 'READY'
    assert data['mapping']['external_id'] == 'payment_id'
    assert data['validation']['valid'] is True


def test_upload_can_import_and_is_idempotent():
    content = b"payment_id,order_id,amount,currency,status,created_at\npay-2,ord-2,250.00,INR,captured,2026-09-08T10:00:00+00:00\n"
    response = client.post('/api/v1/data-onboarding/uploads', params={'data_type': 'payments', 'provider': 'razorpay'}, files={'file': ('payments.csv', content, 'text/csv')})
    assert response.status_code == 200
    upload_id = response.json()['id']
    imported = client.post(f'/api/v1/data-onboarding/uploads/{upload_id}/import')
    assert imported.status_code == 200, imported.text
    assert imported.json()['status'] == 'IMPORTED'
    assert imported.json()['import_result']['created'] == 1
    repeated = client.post(f'/api/v1/data-onboarding/uploads/{upload_id}/import')
    assert repeated.status_code == 200
    assert repeated.json()['status'] == 'IMPORTED'


def test_bad_file_is_rejected():
    content = b"payment_id,amount\npay-3,not-money\n"
    response = client.post('/api/v1/data-onboarding/uploads', params={'data_type': 'payments'}, files={'file': ('bad.csv', content, 'text/csv')})
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'VALIDATION_FAILED'
    assert data['validation']['error_rows'] == 1


def test_xlsx_upload_is_supported():
    from io import BytesIO
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(['provider_payment_id', 'provider_order_id', 'amount', 'currency', 'status', 'created_at'])
    sheet.append(['xlsx-pay-1', 'xlsx-order-1', 175.50, 'INR', 'captured', '2026-09-08T11:00:00+00:00'])
    stream = BytesIO()
    book.save(stream)
    response = client.post('/api/v1/data-onboarding/uploads', params={'data_type': 'payments', 'provider': 'razorpay'}, files={'file': ('payments.xlsx', stream.getvalue(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['mapping']['external_id'] == 'provider_payment_id'
    assert data['validation']['valid'] is True
