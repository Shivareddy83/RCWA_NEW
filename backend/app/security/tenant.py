from __future__ import annotations
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import BankTransaction, Case, Evidence, Payment, RCA, ReconciliationException, Refund, Settlement, IngestionBatch

# Several routes need a global (all-merchant) view for the seeded "test-admin"
# fixture user so integration tests can assert across every merchant's records
# without juggling tenant setup in every test. That is a legitimate testing
# need, but the original checks only guarded it with `settings.testing`, a
# single boolean that a misconfigured deploy could flip to true. This helper
# adds a second, independent guard (`app_env` must not be production) so the
# cross-tenant bypass is structurally unreachable outside a real test run,
# even if TESTING=1 ever leaked into a non-test environment.
def test_admin_bypass(user) -> bool:
    if not settings.testing:
        return False
    if settings.app_env in {"production", "prod"}:
        return False
    return getattr(user, "id", "") == "test-admin"

def scoped(model, session: Session, record_id: str, user):
    if not hasattr(model, 'merchant_id'):
        if model in (Evidence, RCA):
            case_id_col = Evidence.reconciliation_case_id if model is Evidence else RCA.reconciliation_case_id
            case = session.scalar(select(Case).where(Case.id == case_id_col, Case.merchant_id == user.merchant_id))
            if not case: raise HTTPException(404, "Resource not found")
            value = session.get(model, record_id)
        else:
            value = session.get(model, record_id)
    else:
        value = session.scalar(select(model).where(model.id == record_id, model.merchant_id == user.merchant_id))
    if not value: raise HTTPException(404, "Resource not found")
    return value

def ensure_merchant(value: str | None, user):
    if value and value != user.merchant_id:
        raise HTTPException(404, "Resource not found")
    return user.merchant_id
