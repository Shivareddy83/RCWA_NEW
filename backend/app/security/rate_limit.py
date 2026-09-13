from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.models import SecurityRateLimit


def _hash_key(action: str, key: str) -> str:
    secret = settings.auth_secret or "rcaa-rate-limit-development"
    return hmac.new(secret.encode(), f"{action}:{key}".encode(), hashlib.sha256).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def enforce_rate_limit(session: Session, action: str, key: str, limit: int, window_seconds: int) -> None:
    if not settings.rate_limit_enabled or settings.testing or limit <= 0:
        return
    now = utc_now()
    key_hash = _hash_key(action, key)
    row = session.scalar(select(SecurityRateLimit).where(SecurityRateLimit.action == action, SecurityRateLimit.key_hash == key_hash).with_for_update())
    if row is None:
        row = SecurityRateLimit(action=action, key_hash=key_hash, window_started_at=now, count=1, updated_at=now)
        session.add(row)
        try:
            session.flush()
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.scalar(select(SecurityRateLimit).where(SecurityRateLimit.action == action, SecurityRateLimit.key_hash == key_hash))
            if row is None:
                raise
            return enforce_rate_limit(session, action, key, limit, window_seconds)
        return

    if row.blocked_until and _utc(row.blocked_until) > now:
        retry = max(1, int((_utc(row.blocked_until) - now).total_seconds()))
        raise HTTPException(429, "Too many requests. Please try again later.", headers={"Retry-After": str(retry)})

    if now - _utc(row.window_started_at) >= timedelta(seconds=window_seconds):
        row.window_started_at = now
        row.count = 1
        row.blocked_until = None
        row.updated_at = now
        session.flush()
        session.commit()
        return

    row.count += 1
    row.updated_at = now
    if row.count > limit:
        row.blocked_until = _utc(row.window_started_at) + timedelta(seconds=window_seconds)
        session.flush()
        session.commit()
        retry = max(1, int((_utc(row.blocked_until) - now).total_seconds()))
        raise HTTPException(429, "Too many requests. Please try again later.", headers={"Retry-After": str(retry)})
    session.flush()
    session.commit()


def reset_rate_limit(session: Session, action: str, key: str) -> None:
    if not settings.rate_limit_enabled or settings.testing:
        return
    key_hash = _hash_key(action, key)
    session.execute(delete(SecurityRateLimit).where(SecurityRateLimit.action == action, SecurityRateLimit.key_hash == key_hash))
    session.flush()
    session.commit()
