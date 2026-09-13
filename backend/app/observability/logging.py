from __future__ import annotations
import json, logging, re, sys

SENSITIVE = {"password", "password_hash", "authorization", "token", "access_token", "jwt", "api_key", "apikey", "webhook_secret", "private_key", "ai_api_key", "prompt", "response", "evidence"}

def _safe(value):
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items() if str(k).lower() not in SENSITIVE}
    if isinstance(value, (list, tuple)): return [_safe(v) for v in value]
    return value

_SECRET_PATTERNS = (
    re.compile(r"(?i)(password|password_hash|api[_-]?key|webhook[_-]?secret|authorization|bearer|jwt|token)\s*[:=]\s*[^\s,}]+"),
)

def _safe_message(value: str) -> str:
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda m: m.group(1) + "=[REDACTED]", result)
    return result

class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": _safe_message(record.getMessage()),
        }
        for field in ("request_id", "correlation_id", "merchant_id", "actor_user_id", "actor_role", "operation", "resource_type", "resource_id", "duration_ms", "outcome", "error_code", "method", "route", "status_code"):
            value = getattr(record, field, None)
            if value is not None: payload[field] = _safe(value)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(_safe(payload), separators=(",", ":"), default=str)

def configure_structured_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(StructuredFormatter())
    root.setLevel(logging.INFO)

__all__ = ["configure_structured_logging", "StructuredFormatter"]
