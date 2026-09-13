from __future__ import annotations
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models import DataConnector
from app.security import get_current_user, require_roles
from app.services.connectors import SUPPORTED_CONNECTORS, save_credentials, connector_credentials
from app.jobs_service import create_job
from app.audit import record_event
from app.core.time import utc_now
from app.core.config import settings

router = APIRouter(prefix="/connectors", tags=["connectors"], dependencies=[Depends(get_current_user)])

class ConnectorRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=100)
    key_id: str = Field(min_length=5, max_length=200)
    key_secret: str = Field(min_length=5, max_length=300)
    sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=360, ge=60, le=1440)

class SyncRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=31)

@router.get("")
def list_connectors(session: Session = Depends(get_db), user=Depends(get_current_user)):
    items = session.scalars(select(DataConnector).where(DataConnector.merchant_id == user.merchant_id).order_by(DataConnector.created_at.desc())).all()
    return {"items": [{"id": x.id, "provider": x.provider, "name": x.name, "status": x.status, "sync_enabled": x.sync_enabled, "sync_interval_minutes": x.sync_interval_minutes, "last_sync_at": x.last_sync_at, "next_sync_at": x.next_sync_at, "last_sync_status": x.last_sync_status, "last_sync_summary": x.last_sync_summary} for x in items]}

@router.post("", dependencies=[Depends(require_roles("ADMIN"))])
def create_connector(payload: ConnectorRequest, request: Request, session: Session = Depends(get_db), user=Depends(get_current_user)):
    provider = payload.provider.strip().lower()
    if provider not in SUPPORTED_CONNECTORS:
        raise HTTPException(422, "This provider connector is not available yet. Razorpay is the supported live connector in this release.")
    existing = session.scalar(select(DataConnector).where(DataConnector.merchant_id == user.merchant_id, DataConnector.provider == provider))
    connector = existing or DataConnector(merchant_id=user.merchant_id, provider=provider, name=payload.name.strip())
    connector.name = payload.name.strip(); connector.sync_enabled = payload.sync_enabled; connector.sync_interval_minutes = payload.sync_interval_minutes; connector.status = "CONNECTED"
    save_credentials(connector, {"key_id": payload.key_id.strip(), "key_secret": payload.key_secret.strip()})
    connector.next_sync_at = utc_now() + timedelta(minutes=connector.sync_interval_minutes) if connector.sync_enabled else None
    session.add(connector); session.flush()
    record_event(session, action="CONNECTOR_CONFIGURED", resource_type="CONNECTOR", resource_id=connector.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state, "request_id", None), metadata={"provider": provider, "sync_enabled": connector.sync_enabled})
    session.commit()
    return {"id": connector.id, "provider": connector.provider, "name": connector.name, "status": connector.status, "sync_enabled": connector.sync_enabled, "next_sync_at": connector.next_sync_at}

@router.post("/{connector_id}/test", dependencies=[Depends(require_roles("ADMIN"))])
def test_connector(connector_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    connector = session.scalar(select(DataConnector).where(DataConnector.id == connector_id, DataConnector.merchant_id == user.merchant_id))
    if not connector: raise HTTPException(404, "Connector not found")
    creds = connector_credentials(connector)
    if connector.provider == "razorpay":
        from app.providers.razorpay_connector import RazorpayConnector
        adapter = RazorpayConnector(creds["key_id"], creds["key_secret"])
        try:
            adapter.fetch_settlements(utc_now() - timedelta(days=1), utc_now())
        except Exception as exc:
            connector.status = "ERROR"; connector.last_sync_status = "FAILED"; session.commit()
            raise HTTPException(502, "Provider connection test failed") from exc
    connector.status = "CONNECTED"; session.commit()
    return {"connected": True, "provider": connector.provider}

@router.post("/{connector_id}/sync", dependencies=[Depends(require_roles("ADMIN", "OPS"))])
def sync_connector(connector_id: str, payload: SyncRequest = SyncRequest(), request: Request = None, session: Session = Depends(get_db), user=Depends(get_current_user)):
    connector = session.scalar(select(DataConnector).where(DataConnector.id == connector_id, DataConnector.merchant_id == user.merchant_id))
    if not connector: raise HTTPException(404, "Connector not found")
    job, created = create_job(session, merchant_id=user.merchant_id, job_type="SYNC_CONNECTOR", payload={"connector_id": connector.id, "days": payload.days}, idempotency_key=f"connector-sync:{connector.id}:{utc_now().strftime('%Y%m%d%H%M')}", created_by=user.id, request_id=getattr(request.state, "request_id", None) if request else None, actor_role=user.role)
    session.commit()
    return {"queued": True, "created": created, "job_id": job.job_id, "provider": connector.provider, "days": payload.days}
