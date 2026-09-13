from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import ONBOARDING_COMPLETED, ONBOARDING_PROFILE_UPDATED
from app.models import (
    AuditEvent,
    BankTransaction,
    Merchant,
    MerchantOnboarding,
    Payment,
    ReconciliationException,
    Settlement,
    DataConnector,
)
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/onboarding", tags=["onboarding"], dependencies=[Depends(get_current_user)])

BUSINESS_TYPES = {"D2C_ECOMMERCE", "SAAS", "MARKETPLACE", "EDTECH", "HEALTHCARE", "OTHER"}
TRANSACTION_BANDS = {"UNDER_10K", "10K_100K", "100K_1M", "1M_5M", "OVER_5M"}
PROVIDERS = {"RAZORPAY", "STRIPE", "CASHFREE", "PAYU", "OTHER"}


class OnboardingProfile(BaseModel):
    business_type: Literal["D2C_ECOMMERCE", "SAAS", "MARKETPLACE", "EDTECH", "HEALTHCARE", "OTHER"]
    monthly_transaction_band: Literal["UNDER_10K", "10K_100K", "100K_1M", "1M_5M", "OVER_5M"]
    primary_provider: Literal["RAZORPAY", "STRIPE", "CASHFREE", "PAYU", "OTHER"]


def _counts(session: Session, merchant_id: str) -> dict[str, int]:
    return {
        "payments": int(session.scalar(select(func.count(Payment.id)).where(Payment.merchant_id == merchant_id)) or 0),
        "settlements": int(session.scalar(select(func.count(Settlement.id)).where(Settlement.merchant_id == merchant_id)) or 0),
        "bank_transactions": int(session.scalar(select(func.count(BankTransaction.id)).where(BankTransaction.merchant_id == merchant_id)) or 0),
        "exceptions": int(session.scalar(select(func.count(ReconciliationException.id)).where(ReconciliationException.merchant_id == merchant_id)) or 0),
        "connectors": int(session.scalar(select(func.count(DataConnector.id)).where(DataConnector.merchant_id == merchant_id, DataConnector.status == "CONNECTED")) or 0),
        "reconciliations": int(session.scalar(select(func.count(AuditEvent.id)).where(
            AuditEvent.merchant_id == merchant_id,
            AuditEvent.action == "RECONCILIATION_COMPLETED",
            AuditEvent.outcome == "SUCCESS",
        )) or 0),
    }


def _profile(session: Session, merchant_id: str) -> MerchantOnboarding:
    value = session.scalar(select(MerchantOnboarding).where(MerchantOnboarding.merchant_id == merchant_id))
    if value:
        return value
    value = MerchantOnboarding(merchant_id=merchant_id, status="IN_PROGRESS")
    session.add(value)
    session.flush()
    return value


def _view(session: Session, user) -> dict:
    merchant = session.get(Merchant, user.merchant_id)
    profile = _profile(session, user.merchant_id)
    counts = _counts(session, user.merchant_id)
    profile_complete = all([
        profile.business_type,
        profile.monthly_transaction_band,
        profile.primary_provider,
    ])
    data_ready = counts["payments"] > 0 and counts["settlements"] > 0
    reconciliation_ready = data_ready
    first_run_complete = counts["reconciliations"] > 0
    review_ready = first_run_complete and counts["exceptions"] >= 0
    completed = profile.status == "COMPLETE"
    steps = [
        {"key": "profile", "title": "Business profile", "description": "Tell RCAA what kind of operation you're reconciling.", "complete": profile_complete},
        {"key": "data", "title": "Connect your data", "description": "Use the Razorpay connector or import payments and settlements before the first run.", "complete": data_ready},
        {"key": "reconciliation", "title": "Run reconciliation", "description": "Run the deterministic reconciliation engine on your data.", "complete": first_run_complete},
        {"key": "review", "title": "Review exceptions", "description": "Open the exception queue and investigate any breaks.", "complete": review_ready},
    ]
    return {
        "status": profile.status,
        "completed_at": profile.completed_at,
        "merchant": {"id": merchant.id if merchant else user.merchant_id, "name": merchant.name if merchant else None, "email": merchant.email if merchant else None},
        "profile": {
            "business_type": profile.business_type,
            "monthly_transaction_band": profile.monthly_transaction_band,
            "primary_provider": profile.primary_provider,
        },
        "counts": counts,
        "recommended_path": "RAZORPAY_CONNECTOR" if str(profile.primary_provider or "").upper() == "RAZORPAY" else "FILE_IMPORT",
        "steps": steps,
        "ready_to_complete": profile_complete and data_ready and first_run_complete,
        "complete": completed,
    }


@router.get("/guide")
def onboarding_guide(session: Session = Depends(get_db), user=Depends(get_current_user)):
    state = _view(session, user)
    return {"title":"Your first reconciliation", "principle":"Upload or connect data, reconcile deterministic financial truth, investigate exceptions, resolve them, and report.", "steps": state["steps"], "recommended_path": state["recommended_path"], "next_action": next((x for x in state["steps"] if not x["complete"]), state["steps"][-1] if state["steps"] else None)}

@router.get("")
def get_onboarding(session: Session = Depends(get_db), user=Depends(get_current_user)):
    value = _view(session, user)
    session.commit()
    return value


@router.put("/profile")
def update_profile(
    payload: OnboardingProfile,
    request: Request,
    session: Session = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    profile = _profile(session, user.merchant_id)
    before = {
        "business_type": profile.business_type,
        "monthly_transaction_band": profile.monthly_transaction_band,
        "primary_provider": profile.primary_provider,
        "status": profile.status,
    }
    profile.business_type = payload.business_type
    profile.monthly_transaction_band = payload.monthly_transaction_band
    profile.primary_provider = payload.primary_provider
    if profile.status == "COMPLETE":
        profile.status = "IN_PROGRESS"
        profile.completed_at = None
    record_event(
        session,
        action=ONBOARDING_PROFILE_UPDATED,
        resource_type="MERCHANT_ONBOARDING",
        resource_id=profile.id,
        merchant_id=user.merchant_id,
        actor_user_id=user.id,
        actor_role=user.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        before_snapshot=before,
        after_snapshot={"business_type": profile.business_type, "monthly_transaction_band": profile.monthly_transaction_band, "primary_provider": profile.primary_provider, "status": profile.status},
    )
    session.commit()
    return _view(session, user)


@router.post("/complete")
def complete_onboarding(
    request: Request,
    session: Session = Depends(get_db),
    user=Depends(require_roles("ADMIN")),
):
    profile = _profile(session, user.merchant_id)
    state = _view(session, user)
    if not state["ready_to_complete"]:
        raise HTTPException(409, "Complete the business profile, import payment and settlement data, and run reconciliation before finishing onboarding.")
    now = datetime.now(timezone.utc)
    profile.status = "COMPLETE"
    profile.completed_at = now
    record_event(
        session,
        action=ONBOARDING_COMPLETED,
        resource_type="MERCHANT_ONBOARDING",
        resource_id=profile.id,
        merchant_id=user.merchant_id,
        actor_user_id=user.id,
        actor_role=user.role,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        after_snapshot={"status": "COMPLETE", "completed_at": now.isoformat()},
    )
    session.commit()
    return _view(session, user)
