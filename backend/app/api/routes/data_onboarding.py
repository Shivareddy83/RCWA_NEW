from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.audit import record_event
from app.audit.actions import DATA_IMPORT_COMPLETED, DATA_UPLOAD_CREATED, DATA_UPLOAD_VALIDATED
from app.data_onboarding import DATA_TYPES, MAX_PREVIEW_ROWS, MAX_ROWS, MAX_UPLOAD_BYTES, import_rows, parse_upload, suggest_mapping, validate_mapping, validate_rows
from app.models import DataUpload
from app.security import get_current_user, require_roles
from app.services.serialization import dump

router = APIRouter(prefix="/data-onboarding", tags=["data-onboarding"], dependencies=[Depends(get_current_user)])


class MappingPayload(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)


@router.post("/uploads")
async def create_upload(
    request: Request,
    file: UploadFile = File(...),
    data_type: str = "payments",
    provider: str | None = None,
    session: Session = Depends(get_db),
    user=Depends(require_roles("ADMIN", "OPS")),
):
    if data_type not in DATA_TYPES:
        raise HTTPException(422, "Unsupported data type")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
    try:
        rows, headers = parse_upload(content, file.filename or "upload.csv")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    mapping = suggest_mapping(data_type, headers)
    validation = validate_rows(data_type, rows, mapping)
    upload = DataUpload(
        merchant_id=user.merchant_id,
        filename=file.filename or "upload.csv",
        data_type=data_type,
        provider=(provider or "").strip().lower() or None,
        content_type=file.content_type,
        file_size=len(content),
        row_count=len(rows),
        headers_json=headers,
        preview_rows_json=rows[:MAX_PREVIEW_ROWS],
        rows_json=rows,
        mapping_json=mapping,
        validation_json=validation,
        status="READY" if validation["valid"] else "VALIDATION_FAILED",
    )
    session.add(upload)
    session.flush()
    record_event(session, action=DATA_UPLOAD_CREATED, resource_type="DATA_UPLOAD", resource_id=upload.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, metadata={"data_type": data_type, "filename": upload.filename, "rows": len(rows)})
    session.commit()
    return _view(upload)


def _view(upload: DataUpload) -> dict:
    return {
        "id": upload.id,
        "filename": upload.filename,
        "data_type": upload.data_type,
        "provider": upload.provider,
        "content_type": upload.content_type,
        "file_size": upload.file_size,
        "row_count": upload.row_count,
        "status": upload.status,
        "headers": upload.headers_json or [],
        "preview_rows": upload.preview_rows_json or [],
        "mapping": upload.mapping_json or {},
        "validation": upload.validation_json or {},
        "import_result": upload.import_result_json,
        "created_at": upload.created_at,
        "validated_at": upload.validated_at,
        "imported_at": upload.imported_at,
    }


@router.get("/uploads")
def list_uploads(session: Session = Depends(get_db), user=Depends(get_current_user)):
    items = session.scalars(select(DataUpload).where(DataUpload.merchant_id == user.merchant_id).order_by(DataUpload.created_at.desc()).limit(100)).all()
    return {"items": [_view(x) for x in items]}


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, session: Session = Depends(get_db), user=Depends(get_current_user)):
    upload = session.scalar(select(DataUpload).where(DataUpload.id == upload_id, DataUpload.merchant_id == user.merchant_id))
    if not upload:
        raise HTTPException(404, "Upload not found")
    return _view(upload)


@router.post("/uploads/{upload_id}/validate")
def validate_upload(upload_id: str, payload: MappingPayload, request: Request, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN", "OPS"))):
    upload = session.scalar(select(DataUpload).where(DataUpload.id == upload_id, DataUpload.merchant_id == user.merchant_id))
    if not upload:
        raise HTTPException(404, "Upload not found")
    mapping = payload.mapping or upload.mapping_json or {}
    errors = validate_mapping(upload.data_type, upload.headers_json or [], mapping)
    validation = validate_rows(upload.data_type, upload.rows_json or [], mapping) if not errors else {"valid": False, "rows": upload.row_count, "valid_rows": 0, "warning_rows": 0, "error_rows": upload.row_count, "errors": errors[:20], "warnings": []}
    upload.mapping_json = mapping
    upload.validation_json = validation
    upload.status = "READY" if validation["valid"] else "VALIDATION_FAILED"
    from app.core.time import utc_now
    upload.validated_at = utc_now()
    record_event(session, action=DATA_UPLOAD_VALIDATED, resource_type="DATA_UPLOAD", resource_id=upload.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, metadata={"valid": validation["valid"], "errors": validation["error_rows"]})
    session.commit()
    return _view(upload)


@router.post("/uploads/{upload_id}/import")
def import_upload(upload_id: str, request: Request, session: Session = Depends(get_db), user=Depends(require_roles("ADMIN", "OPS"))):
    upload = session.scalar(select(DataUpload).where(DataUpload.id == upload_id, DataUpload.merchant_id == user.merchant_id))
    if not upload:
        raise HTTPException(404, "Upload not found")
    if upload.status == "IMPORTED":
        return _view(upload)
    validation = upload.validation_json or {}
    if not validation.get("valid"):
        raise HTTPException(409, "Fix validation errors before importing this file")
    try:
        result = import_rows(session, merchant_id=user.merchant_id, data_type=upload.data_type, rows=upload.rows_json or [], mapping=upload.mapping_json or {}, source=f"customer_upload:{upload.id}", provider=upload.provider)
    except Exception as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from exc
    from app.core.time import utc_now
    upload.import_result_json = result
    upload.status = "IMPORTED"
    upload.imported_at = utc_now()
    record_event(session, action=DATA_IMPORT_COMPLETED, resource_type="DATA_UPLOAD", resource_id=upload.id, merchant_id=user.merchant_id, actor_user_id=user.id, actor_role=user.role, request_id=getattr(request.state, "request_id", None), ip_address=request.client.host if request.client else None, metadata={"data_type": upload.data_type, "received": result.get("received", 0), "created": result.get("created", 0), "duplicates": result.get("duplicates", 0)})
    session.commit()
    return _view(upload)
