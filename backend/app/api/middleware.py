import logging
import re
from time import monotonic
from uuid import uuid4
from fastapi import Request
from app.observability.metrics import inc, observe, set_gauge
from app.core.config import settings
from fastapi.responses import JSONResponse

logger = logging.getLogger("rcaa.request")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

def _safe_request_id(value: str | None) -> str:
    value = (value or "").strip()
    return value if _REQUEST_ID_RE.fullmatch(value) else str(uuid4())

def _route(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path and len(path) <= 200: return path
    return "unmatched"

def client_ip(request: Request) -> str | None:
    """Return the originating client IP only when proxy headers are explicitly trusted."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or None
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else None


async def request_context(request: Request, call_next):
    request_id = _safe_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    request.state.correlation_id = request_id
    request.state.client_ip = client_ip(request)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_request_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body exceeds the configured size limit"}, headers={"X-Request-ID": request_id})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"}, headers={"X-Request-ID": request_id})
    started = monotonic()
    set_gauge("http_requests_in_flight", 1)
    try:
        response = await call_next(request)
    except Exception:
        duration = monotonic() - started
        observe("http_request_duration_seconds", duration, labels={"method": request.method, "route": _route(request), "status": "500"})
        inc("http_requests_total", labels={"method": request.method, "route": _route(request), "status": "500"})
        logger.exception("http_request_failed", extra={"request_id":request_id,"correlation_id":request_id,"method":request.method,"route":_route(request),"status_code":500,"duration_ms":round(duration*1000,2),"outcome":"FAILURE","error_code":"INTERNAL_SERVER_ERROR"})
        raise
    finally:
        set_gauge("http_requests_in_flight", 0)
    duration = monotonic() - started
    route = _route(request)
    status = str(response.status_code)
    observe("http_request_duration_seconds", duration, labels={"method":request.method,"route":route,"status":status})
    inc("http_requests_total", labels={"method":request.method,"route":route,"status":status})
    response.headers["X-Request-ID"] = request_id
    user = getattr(request.state, "user", None)
    merchant_id = getattr(request.state, "merchant_id", None)
    actor_user_id = getattr(request.state, "actor_user_id", None)
    actor_role = getattr(request.state, "actor_role", None)
    logger.info("http_request", extra={"request_id":request_id,"correlation_id":request_id,"merchant_id":merchant_id,"actor_user_id":actor_user_id,"actor_role":actor_role,"method":request.method,"route":route,"status_code":response.status_code,"duration_ms":round(duration*1000,2),"outcome":"SUCCESS" if response.status_code < 400 else "FAILURE"})
    return response
