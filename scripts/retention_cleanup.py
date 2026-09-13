#!/usr/bin/env python3
"""Privacy/retention maintenance for raw ingestion artifacts.

This script intentionally removes raw upload rows and webhook payloads while
leaving normalized financial truth, identifiers, reconciliation outcomes and
audit history intact. Run from a scheduled production job after validating
retention requirements with the customer/legal owner.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.time import utc_now
from app.db.session import SessionLocal
from app.models import AuthSession, DataUpload, SecurityRateLimit, WebhookEvent


def run(dry_run: bool = False) -> dict[str, int]:
    now = utc_now()
    upload_cutoff = now - timedelta(days=settings.upload_retention_days)
    raw_cutoff = now - timedelta(days=settings.raw_data_retention_days)
    result = {"uploads_redacted": 0, "webhooks_redacted": 0, "rate_limits_deleted": 0, "sessions_deleted": 0}
    with SessionLocal() as session:
        uploads = session.scalars(select(DataUpload).where(DataUpload.created_at < upload_cutoff, DataUpload.status == "IMPORTED")).all()
        for item in uploads:
            if item.rows_json or item.preview_rows_json:
                result["uploads_redacted"] += 1
                if not dry_run:
                    item.rows_json = []
                    item.preview_rows_json = []
                    item.mapping_json = {}
                    item.validation_json = {"retained": False, "reason": "retention_policy"}
        webhooks = session.scalars(select(WebhookEvent).where(WebhookEvent.received_at < raw_cutoff)).all()
        for item in webhooks:
            if item.payload:
                result["webhooks_redacted"] += 1
                if not dry_run:
                    item.payload = {"redacted": True, "event": item.event_type, "event_id": item.event_id}
        stale = session.execute(delete(SecurityRateLimit).where(SecurityRateLimit.updated_at < raw_cutoff))
        result["rate_limits_deleted"] = stale.rowcount or 0
        expired_sessions = session.execute(delete(AuthSession).where(AuthSession.expires_at < now - timedelta(days=7)))
        result["sessions_deleted"] = expired_sessions.rowcount or 0
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(run(dry_run=args.dry_run))
