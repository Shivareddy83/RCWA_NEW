import logging
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError

logger = logging.getLogger("rcaa.api")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=jsonable_encoder({"detail": "Request validation failed.", "errors": exc.errors()}))

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        logger.exception("Database integrity error", extra={"request_id":getattr(request.state,"request_id","-"),"error_code":"INTEGRITY_ERROR","method":request.method,"route":request.url.path,"status_code":409})
        return JSONResponse(status_code=409, content={"detail": "Resource already exists or violates a database constraint."})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        logger.exception("Request validation/business error", extra={"request_id":getattr(request.state,"request_id","-"),"error_code":"VALIDATION_OR_BUSINESS_ERROR","method":request.method,"route":request.url.path,"status_code":400})
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled application error", extra={"request_id":getattr(request.state,"request_id","-"),"error_code":"INTERNAL_SERVER_ERROR","method":request.method,"route":request.url.path,"status_code":500})
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
