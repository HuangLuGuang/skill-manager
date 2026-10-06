"""Bounded audit payload expiry; identity, digest and durable ACK rows survive."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select

from .aidr_policy import CLIENT_KEY, current
from .models import SystemConfig
from .aidr_models import AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation
from .aidr_enforcement import AidrRuntimeRecord


def expire_once(db, now=None, limit=500):
    if not 1 <= limit <= 500:
        raise ValueError('aidr_retention_budget_invalid')
    now = now or datetime.utcnow()
    default_days = current(db)['lifecycle']['retention_days']
    counts = {}
    for model in (AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation, AidrRuntimeRecord):
        runtime = model is AidrRuntimeRecord
        # Filter by the effective device policy before LIMIT so long-retention
        # devices cannot consume the cleanup budget or starve other devices.
        days = select(func.json_extract(SystemConfig.value, '$.lifecycle.retention_days')).where(
            SystemConfig.key == CLIENT_KEY + model.client_id,
            func.json_extract(SystemConfig.value, '$.inherit') == 0,
        ).correlate(model).scalar_subquery()
        effective_days = func.coalesce(days, default_days)
        earliest = now - timedelta(days=1)
        boundary = earliest.replace(tzinfo=timezone.utc).isoformat(timespec='microseconds') if runtime else earliest
        rows = db.query(model).filter(model.expired_at.is_(None), model.received_at < boundary,
            func.julianday(model.received_at) < func.julianday(now) - effective_days,
        ).order_by(model.received_at, model.id).limit(limit).all()
        for row in rows:
            if runtime and not row.content_hash:
                row.content_hash = hashlib.sha256(row.payload_json.encode()).hexdigest()
            row.payload_json = '{}'
            row.expired_at = now.replace(tzinfo=timezone.utc).isoformat(timespec='microseconds') if runtime else now
            if model is AidrOperation:
                row.session_id, row.tool = '', ''
                row.result_status = 'history_expired'
        counts[model.__tablename__] = len(rows)
        db.flush()
    db.commit()
    return counts


def view(db, client_id):
    return {'days': current(db, client_id)['lifecycle']['retention_days'],
            'expired_logs': db.query(AidrEvent).filter(AidrEvent.client_id == client_id, AidrEvent.expired_at.is_not(None)).count(),
            'expired_hooks': db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id, AidrHookEvent.expired_at.is_not(None)).count(),
            'expired_runtime': db.query(AidrRuntimeRecord).filter(AidrRuntimeRecord.client_id == client_id, AidrRuntimeRecord.expired_at.is_not(None)).count(),
            'code': 'aidr_audit_history_retention'}


def cleanup_once():
    from .sqlite_db import SessionLocal
    with SessionLocal() as db:
        return expire_once(db)


async def retention_loop():
    import logging
    # No startup purge as part of migration. Each maintenance pass has a fixed
    # row budget, runs off the ASGI event loop and retains immutable ACK hashes.
    while True:
        await asyncio.sleep(60)
        try:
            await run_in_threadpool(cleanup_once)
        except Exception as exc:
            logging.getLogger(__name__).warning('aidr retention failed: %s', type(exc).__name__)
