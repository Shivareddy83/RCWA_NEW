from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.ingestion import ingest_bank_csv, IngestionValidationError
from app.security import get_current_user, require_roles
from app.security.tenant import test_admin_bypass
from app.core.config import settings
from app.audit import record_event
from app.audit.actions import BANK_TRANSACTION_IMPORTED

router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/import/bank-transactions")
async def import_bank_transactions(file: UploadFile = File(...), request: Request = None, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN","OPS"))):
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit")
    try:
        result=ingest_bank_csv(session, content, merchant_id=None if (test_admin_bypass(user)) else user.merchant_id, commit=False)
        record_event(session, action=BANK_TRANSACTION_IMPORTED, resource_type="BANK_IMPORT", merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state,"request_id",None) if request else None, ip_address=request.client.host if request and request.client else None, metadata={"source":"bank_csv","received_count":result.get("received",0),"created_count":result.get("created",0),"duplicate_count":result.get("duplicates",0)})
        session.commit()
        return result
    except IngestionValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
