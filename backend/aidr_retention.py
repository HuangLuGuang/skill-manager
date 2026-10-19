"""Bounded audit payload expiry; identity, digest and durable ACK rows survive."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import load_only

from .aidr_policy import CLIENT_KEY, current
from .models import SystemConfig, ClientEvent
from .aidr_models import AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation, AidrSkillUse, AidrSkillCheck
from .aidr_enforcement import AidrRuntimeRecord
from .services.retention import BATCH_SIZE, retention_loop as run_retention_loop
from .services.gateway_db import run_sync
from .services.aidr_ingest import admission

def expire_once(db, now=None, limit=BATCH_SIZE):
    return {table: count for table, count, _ in _expire_batches(db, now=now, limit=limit)}


def _expire_batches(db, now=None, limit=BATCH_SIZE):
    if not 1 <= limit <= BATCH_SIZE:
        raise ValueError('aidr_retention_budget_invalid')
    now = now or datetime.utcnow()
    default_days = current(db)['lifecycle']['retention_days']
    for model in (AidrEvent, AidrHookEvent, AidrCoverageRecord, AidrOperation, AidrRuntimeRecord, AidrSkillUse, AidrSkillCheck):
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
        eligible = (model.expired_at.is_(None), model.received_at <= boundary,
            func.julianday(model.received_at) <= func.julianday(now) - effective_days,
        )
        query = db.query(model).filter(*eligible).order_by(model.received_at, model.id).limit(limit)
        # Only legacy runtime hashes and skill alerts require the stored body or
        # identity fields. Ordinary expiry does not deserialize audit payloads.
        columns = [model.id]
        if runtime:
            columns.extend([model.content_hash, model.payload_json])
        elif model is AidrSkillUse:
            columns.extend([model.client_id, model.call_key])
        rows = query.options(load_only(*columns)).all()
        if model in (AidrEvent, AidrHookEvent):
            from .aidr_overview import remove_evidence
            remove_evidence(db, 'logs' if model is AidrEvent else 'hooks', [row.id for row in rows])
        for row in rows:
            if runtime and not row.content_hash:
                row.content_hash = hashlib.sha256(row.payload_json.encode()).hexdigest()
            if model is AidrSkillUse:
                row.session_id = ''
                row.certification = 'pending'
                key = hashlib.sha256(('skill-use:' + row.client_id + ':' + row.call_key).encode()).hexdigest()
                alert = db.query(ClientEvent).filter_by(aggregate_key=key).first()
                if alert:
                    details = json.loads(alert.details_json)
                    details['active'] = False
                    alert.details_json = json.dumps(details)
        values = {'payload_json': '{}', 'expired_at': now.replace(tzinfo=timezone.utc).isoformat(timespec='microseconds') if runtime else now}
        if model is AidrOperation:
            values.update(session_id='', tool='', result_status='history_expired')
        db.flush()
        expired = 0
        if rows:
            expiry = db.query(model).filter(model.id.in_([row.id for row in rows]))
            if model is AidrOperation:
                # A late result may refresh this mutable view after selection.
                # CASE keeps the eligibility check on the selected primary keys;
                # a range predicate makes SQLite rescan the expiry index per batch.
                expiry = expiry.filter(case((and_(*eligible), True), else_=False))
            expired = expiry.update(values, synchronize_session=False)
        db.commit()
        if rows and model in (AidrEvent, AidrHookEvent):
            from .aidr_overview import invalidate_cache
            invalidate_cache()
        yield model.__tablename__, expired, len(rows) == limit


def view(db, client_id):
    return {'days': current(db, client_id)['lifecycle']['retention_days'],
            'expired_logs': db.query(AidrEvent).filter(AidrEvent.client_id == client_id, AidrEvent.expired_at.is_not(None)).count(),
            'expired_hooks': db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id, AidrHookEvent.expired_at.is_not(None)).count(),
            'expired_runtime': db.query(AidrRuntimeRecord).filter(AidrRuntimeRecord.client_id == client_id, AidrRuntimeRecord.expired_at.is_not(None)).count(),
            'code': 'aidr_audit_history_retention'}


async def cleanup_once():
    from .sqlite_db import SessionLocal
    db = SessionLocal()
    batches = _expire_batches(db, limit=BATCH_SIZE)
    def step():
        for _, count, full in batches:
            if count or full:
                return full
        return None
    more = False
    try:
        while True:
            async with admission():
                full = await run_sync(step)
            if full is None:
                break
            # Refreshed candidates still consumed the selection budget; other
            # expired rows may remain beyond this batch and need a busy retry.
            more |= full
        return more
    finally:
        await run_sync(db.close)


async def retention_loop():
    await run_retention_loop(cleanup_once, 'aidr')
