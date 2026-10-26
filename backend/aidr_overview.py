"""Incremental metadata-only overview projections; raw evidence remains authoritative."""
from . import aidr_adapters
import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from threading import RLock
from datetime import datetime, timezone, timedelta

from sqlalchemy import Column, Integer, String, Text, Index, select, func, text, union_all
from sqlalchemy.dialects.sqlite import insert
from .services.gateway_db import run_sync
from .services.aidr_ingest import admission
from .sqlite_db import Base
from .aidr_models import AidrEvent, AidrHookEvent
from .aidr_operations import operation_key
from .aidr_commands import command_counts


class OverviewEvidence(Base):
    __tablename__ = 'aidr_overview_evidence'
    source = Column(String(8), primary_key=True)
    record_id = Column(Integer, primary_key=True)
    client_id = Column(String(128), nullable=False)
    agent = Column(String(32), nullable=False)
    product = Column(String(32), nullable=False)
    session_key = Column(String(64), nullable=False)
    session_id = Column(String(256), nullable=False)
    operation_key = Column(String(64), nullable=False)
    at = Column(Integer, nullable=False)
    phase = Column(String(16), nullable=False)
    tool = Column(String(256), nullable=False)
    command = Column(String(64), nullable=False)
    command_counts_json = Column(Text, nullable=False, default='{}', server_default='{}')
    outcome = Column(String(16), nullable=False)
    __table_args__ = (Index('ix_overview_evidence_operation', 'operation_key'),
                     Index('ix_overview_evidence_window', 'client_id', 'source', 'at', 'product', 'session_key'))


class OverviewOperation(Base):
    __tablename__ = 'aidr_overview_operations'
    key = Column(String(64), primary_key=True)
    client_id = Column(String(128), nullable=False)
    source = Column(String(8), nullable=False)
    product = Column(String(32), nullable=False)
    at = Column(Integer, nullable=False)
    tool = Column(String(256), nullable=False)
    command = Column(String(64), nullable=False)
    command_counts_json = Column(Text, nullable=False, default='{}', server_default='{}')
    failed = Column(Integer, nullable=False)
    record_id = Column(Integer, nullable=False)
    __table_args__ = (Index('ix_overview_operation_window', 'client_id', 'source', 'at', 'product'),)


class OverviewBucket(Base):
    __tablename__ = 'aidr_overview_buckets'
    key = Column(String(64), primary_key=True)
    client_id = Column(String(128), nullable=False)
    source = Column(String(8), nullable=False)
    product = Column(String(32), nullable=False)
    hour = Column(Integer, nullable=False)
    tool = Column(String(256), nullable=False)
    command = Column(String(64), nullable=False)
    calls = Column(Integer, nullable=False)
    failures = Column(Integer, nullable=False)
    __table_args__ = (Index('ix_overview_bucket_window', 'client_id', 'source', 'hour', 'product'),)


class OverviewWatermark(Base):
    __tablename__ = 'aidr_overview_watermarks'
    source = Column(String(8), primary_key=True)
    position = Column(Integer, nullable=False, default=0)
    updated_at = Column(Integer, nullable=False, default=0)
    initial_ceiling = Column(Integer, nullable=False, default=0)


class OverviewCommandBucket(Base):
    __tablename__ = 'aidr_overview_command_buckets'
    key = Column(String(64), primary_key=True)
    client_id = Column(String(128), nullable=False)
    source = Column(String(8), nullable=False)
    product = Column(String(32), nullable=False)
    hour = Column(Integer, nullable=False)
    program = Column(String(64), nullable=False)
    occurrences = Column(Integer, nullable=False)
    __table_args__ = (Index('ix_overview_command_window', 'client_id', 'source', 'hour', 'product'),)


def product_id(agent):
    adapter = aidr_adapters.get(agent)
    if agent not in aidr_adapters.ADAPTERS:
        adapter = next((a for a in aidr_adapters.ADAPTERS.values() if a.inventory_type == agent and agent), adapter)
    return adapter.family or adapter.id


def digest(parts):
    return hashlib.sha256(json.dumps(parts, separators=(',', ':')).encode()).hexdigest()


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
        return int((parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).timestamp()) if parsed else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def command_name(behavior):
    actions = behavior.get('actions') or []
    if behavior.get('category') != 'command' and not any(a.get('category') == 'command' for a in actions):
        return ''
    # This field identifies terminal tool calls; occurrence ranks use their own counts.
    return 'command'


def project(source, row):
    raw = json.loads(row.payload_json)
    e = raw.get('event', {}) if source == 'hooks' else raw
    agent = e.get('agent', '')
    kind = e.get('kind', '')
    phase = {'tool.pre': 'call', 'tool.post': 'result', 'tool.failure': 'result',
             'tool_call': 'call', 'tool_result': 'result'}.get(kind, 'activity')
    session = e.get('session_id', '')
    user = raw.get('user_scope')
    call = e.get('native_call_id', '')
    reliable = bool(session and call and user is not None and (not aidr_adapters.get(agent).turn_required or e.get('turn_id')))
    if source == 'hooks':
        reliable = reliable and bool(e.get('tool'))
        identity = [row.client_id, source, row.stream_id, user, agent, session, e.get('turn_id', ''),
                    e.get('native_agent_id', ''), call, e.get('tool', '')]
    else:
        reliable = reliable and bool(e.get('source_id'))
        identity = [source, user, operation_key(row.client_id, e)] if reliable else []
    behavior = e.get('behavior') or {}
    status = behavior.get('status')
    outcome = 'failed' if status == 'reported_error' or kind == 'tool.failure' else (
        'complete' if status in ('reported_success', 'reported_complete') else 'unknown')
    if not behavior and e.get('outcome') == 'error':
        outcome = 'failed'
    return dict(source=source, record_id=row.id, client_id=row.client_id, agent=agent,
                product=product_id(agent),
                session_key=digest([row.client_id, source, user, agent, session]) if session else '',
                session_id=session,
                operation_key=digest(identity) if reliable and phase != 'activity' else '',
                at=timestamp(raw.get('received_at') if source == 'hooks' else e.get('observed_at')),
                phase=phase, tool=e.get('tool', ''), command=command_name(behavior), outcome=outcome,
                command_counts_json=json.dumps(command_counts(behavior), sort_keys=True, separators=(',', ':')))


def reconcile(db, key):
    reconcile_many(db, [key])


def reconcile_many(db, keys):
    keys = sorted({key for key in keys if key})
    table = OverviewOperation.__table__
    evidence = OverviewEvidence.__table__
    # Keep the per-call bound of 34 evidence rows while batching indexed lookups.
    for offset in range(0, len(keys), 50):
        part = keys[offset:offset + 50]
        prior = {row['key']: row for row in db.execute(select(table).where(table.c.key.in_(part))).mappings()}
        queries = [select(select(evidence).where(evidence.c.operation_key == key).limit(34).subquery()) for key in part]
        rows = {key: [] for key in part}
        for row in db.execute(union_all(*queries)).mappings():
            rows[row['operation_key']].append(row)
        changes, removed, saved = [], [], []
        for key in part:
            old = prior.get(key)
            items = rows[key]
            calls = [r for r in items if r['phase'] == 'call']
            current = None
            # Multiple distinct pre-events remain ambiguous.
            if len(items) < 34 and len(calls) == 1 and calls[0]['at']:
                call = calls[0]
                results = [r for r in items if r['phase'] == 'result']
                current = dict(key=key, **{k: call[k] for k in ('client_id', 'source', 'product', 'at', 'tool', 'command', 'command_counts_json', 'record_id')},
                               failed=int(len(results) == 1 and results[0]['outcome'] == 'failed'))
            if old and (not current or any(old[k] != v for k, v in current.items())):
                changes.append((old, -1))
                removed.append(key)
            if current and (not old or any(old[k] != v for k, v in current.items())):
                changes.append((current, 1))
                saved.append(current)
        _change_buckets(db, changes)
        if removed:
            db.execute(table.delete().where(table.c.key.in_(removed)))
        if saved:
            db.execute(insert(table), saved)


def remove_evidence(db, source, ids):
    if not ids:
        return
    # Serialize with projection before reading its operation keys. Expiry must
    # also cover a projection that was waiting to publish these same records.
    state = OverviewWatermark.__table__
    db.execute(state.update().where(state.c.source == source).values(position=state.c.position))
    table = OverviewEvidence.__table__
    keys = set(db.execute(select(table.c.operation_key).where(table.c.source == source, table.c.record_id.in_(ids))).scalars()) - {''}
    db.execute(table.delete().where(table.c.source == source, table.c.record_id.in_(ids)))
    if not keys:
        return
    remaining = set(db.execute(select(table.c.operation_key).where(table.c.operation_key.in_(keys)).distinct()).scalars())
    _remove_complete_operations(db, keys - remaining)
    reconcile_many(db, remaining)


def _remove_complete_operations(db, keys):
    """Subtract expired operations in batches, keeping partial evidence reconciliation."""
    if not keys:
        return
    table = OverviewOperation.__table__
    rows = db.execute(select(table).where(table.c.key.in_(keys))).mappings().all()
    _change_buckets(db, [(row, -1) for row in rows])
    db.execute(table.delete().where(table.c.key.in_(keys)))


def _change_buckets(db, changes):
    totals, commands = {}, {}
    for row, delta in changes:
        dims = {k: row[k] for k in ('client_id', 'source', 'product', 'tool', 'command')}
        dims['hour'] = row['at'] // 3600 * 3600
        key = digest(dims)
        bucket = totals.setdefault(key, dict(key=key, **dims, calls=0, failures=0))
        bucket['calls'] += delta
        bucket['failures'] += delta * row['failed']
        for program, count in json.loads(row['command_counts_json']).items():
            dims = {k: row[k] for k in ('client_id', 'source', 'product')}
            dims.update(hour=row['at'] // 3600 * 3600, program=program)
            key = digest(dims)
            bucket = commands.setdefault(key, dict(key=key, **dims, occurrences=0))
            bucket['occurrences'] += delta * count
    for model, groups, fields, zero in (
        (OverviewBucket, totals, ('calls', 'failures'), 'calls'),
        (OverviewCommandBucket, commands, ('occurrences',), 'occurrences'),
    ):
        if groups:
            buckets = model.__table__
            stmt = insert(buckets)
            db.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={
                field: buckets.c[field] + stmt.excluded[field] for field in fields}), list(groups.values()))
            db.execute(buckets.delete().where(buckets.c.key.in_(groups), buckets.c[zero] == 0))


def advance(db, limit=250):
    """Bounded, restartable backfill/live update, independent of page requests."""
    state = OverviewWatermark.__table__
    prepared = []
    # Raw log/Hook bodies are immutable except for retention. Parse both sources
    # before acquiring the writer; recheck progress and expiry before publishing.
    for source, model in (('hooks', AidrHookEvent), ('logs', AidrEvent)):
        ceiling = db.query(func.max(model.id)).scalar() or 0
        position = db.execute(select(state.c.position).where(state.c.source == source)).scalar_one_or_none() or 0
        rows = db.query(model).filter(model.id > position).order_by(model.id).limit(limit).all()
        values = [project(source, row) for row in rows if row.expired_at is None and row.payload_json != '{}']
        prepared.append((source, model, ceiling, position, rows[-1].id if rows else position, len(rows) == limit, values))
    more = False
    for source, model, ceiling, position, last, full, values in prepared:
        db.execute(insert(state).values(source=source, position=0, updated_at=0, initial_ceiling=ceiling).on_conflict_do_nothing())
        # Serialize publication with other workers and retention. A changed
        # watermark means this source must be prepared again on the next pass.
        db.execute(state.update().where(state.c.source == source).values(position=state.c.position))
        if db.execute(select(state.c.position).where(state.c.source == source)).scalar_one() != position:
            more = True
            continue
        if values:
            candidates = db.execute(select(model.id, model.expired_at, model.payload_json != '{}').where(
                model.id.in_([value['record_id'] for value in values])))
            live = {record_id for record_id, expired_at, has_body in candidates if expired_at is None and has_body}
            values = [value for value in values if value['record_id'] in live]
        if values:
            db.execute(insert(OverviewEvidence.__table__).on_conflict_do_nothing(), values)
        reconcile_many(db, [value['operation_key'] for value in values])
        db.execute(state.update().where(state.c.source == source).values(
            position=last, updated_at=int(datetime.now(timezone.utc).timestamp())))
        more |= full
    db.commit()
    return more


def overview(db, client_id, source='hooks', agent='', hours=24, now=None, since=None, until=None):
    agent = product_id(agent)
    now = now or datetime.now(timezone.utc)
    end = until if until is not None else int(now.timestamp()) + 1
    start = since if since is not None else (end // 3600 - hours + 1) * 3600
    model = AidrHookEvent if source == 'hooks' else AidrEvent
    maximum = db.query(func.max(model.id)).filter(model.client_id == client_id).scalar() or 0
    state = db.get(OverviewWatermark, source)
    ready = maximum == 0 or bool(state and state.position >= min(maximum, state.initial_ceiling))
    # New events can arrive continuously; a caught-up worker timestamp distinguishes
    # short live lag from an old backlog without interpreting partial totals as final.
    params = dict(client=client_id, source=source, agent=agent, start=start, end=end,
                  complete_start=(start + 3599)//3600*3600, current=end//3600*3600)
    where = 'client_id=:client AND source=:source AND hour>=:start AND hour<:end'
    if agent:
        where += ' AND product=:agent'
    rows = db.execute(text(f'SELECT product,hour,tool,command,calls,failures FROM aidr_overview_buckets WHERE {where} AND hour>=:complete_start AND hour<:current'), params).mappings().all()
    # The open hour uses the same event-time boundary as drilldown, including when
    # a client's clock is ahead. Completed hours remain pre-aggregated.
    current_where = 'client_id=:client AND source=:source AND at>=:start AND at<:end AND (at<:complete_start OR at>=:current)'
    if agent:
        current_where += ' AND product=:agent'
    rows += db.execute(text(f'''SELECT product,at/3600*3600 hour,tool,command,count(*) calls,sum(failed) failures
        FROM aidr_overview_operations WHERE {current_where} GROUP BY hour,product,tool,command'''), params).mappings().all()
    trend = {at: {'at': max(start, at), 'commands': 0, 'other': 0} for at in range(start//3600*3600, end, 3600)}
    totals = dict(commands=0, tools=0, failures=0, command_occurrences=0)
    ranks = {k: {} for k in ('commands', 'tools', 'agents')}
    for row in rows:
        n = row['calls']
        totals['tools'] += n
        totals['failures'] += row['failures']
        totals['commands'] += n if row['command'] else 0
        trend[row['hour']]['commands' if row['command'] else 'other'] += n
        for dimension, value in [('tools', row['tool']), ('agents', row['product'])]:
            if value:
                ranks[dimension][value] = ranks[dimension].get(value, 0) + n
    # Occurrences have a separate aggregation so repeated subcommands never multiply tool calls.
    command_rows = db.execute(text(f'''SELECT program,sum(occurrences) occurrences
        FROM aidr_overview_command_buckets WHERE {where} AND hour>=:complete_start AND hour<:current GROUP BY program'''), params).mappings().all()
    command_rows += db.execute(text(f'''SELECT j.key program,sum(j.value) occurrences
        FROM aidr_overview_operations, json_each(command_counts_json) j
        WHERE {current_where} GROUP BY j.key'''), params).mappings().all()
    for row in command_rows:
        ranks['commands'][row['program']] = ranks['commands'].get(row['program'], 0) + row['occurrences']
        totals['command_occurrences'] += row['occurrences']
    evidence_where = where.replace('hour', 'at')
    extras = db.execute(text(f'''SELECT count(DISTINCT nullif(session_key,'')) sessions,
        sum(CASE WHEN phase!='activity' AND (operation_key='' OR NOT EXISTS (SELECT 1 FROM aidr_overview_operations o WHERE o.key=aidr_overview_evidence.operation_key)) THEN 1 ELSE 0 END) unlinked
        FROM aidr_overview_evidence WHERE {evidence_where}'''), params).mappings().one()
    totals['sessions'] = extras['sessions']
    status = 'preparing' if not ready else 'delayed' if maximum and state and now.timestamp()-state.updated_at > 60 else 'ready'
    return dict(state=status, updated_at=state.updated_at if state else None,
                source=source, agent=agent, since=start, until=end, totals=totals,
                unlinked=extras['unlinked'] or 0, trend=list(trend.values()),
                rankings={k: [dict(name=name, count=n) for name, n in sorted(v.items(), key=lambda p: (-p[1], p[0]))[:5]] for k, v in ranks.items()})


_cache = OrderedDict()
_cache_lock = RLock()


def cached_overview(db, client_id, source, agent, hours, since=None, until=None):
    # Authentication/visibility runs before this function. Only metadata is cached;
    # retention invalidates it, and the key includes the database and full scope.
    key = (db.get_bind(), client_id, source, agent, hours, since, until)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]
    result = overview(db, client_id, source, agent, hours, since=since, until=until)
    with _cache_lock:
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return result


def invalidate_cache():
    with _cache_lock:
        _cache.clear()


def task_summary(db, client_id, before=None, since=None, until=None, status=''):
    from .models import ClientTask
    from .runtime_governance import Observation
    q = db.query(ClientTask).filter(ClientTask.client_id == client_id)
    if since is not None:
        q = q.filter(ClientTask.created_at >= datetime.fromtimestamp(since, timezone.utc).replace(tzinfo=None),
                     ClientTask.created_at < datetime.fromtimestamp(until, timezone.utc).replace(tzinfo=None))
    counts = dict(q.with_entities(ClientTask.status, func.count()).group_by(ClientTask.status).all())
    if status:
        q = q.filter(ClientTask.status == status)
    history = q.filter(ClientTask.id < before).order_by(ClientTask.id.desc()).limit(31).all() if before else q.order_by(ClientTask.id.desc()).limit(31).all()
    def present(row):
        payload = json.loads(row.payload_json)
        return dict(id=row.id, task_type=row.task_type, status=row.status, error_code=row.error or '',
                    created_at=row.created_at, finished_at=row.finished_at,
                    payload={k: payload[k] for k in ('action', 'agent', 'agent_type', 'skill_name', 'policy_version', 'target') if k in payload})
    result = dict(history=[present(row) for row in history[:30]], next_cursor=history[29].id if len(history)>30 else None, attention=[])
    result['counts'] = counts
    if before or since is not None:
        return result
    active = q.filter(ClientTask.status.in_(('pending', 'running'))).order_by(ClientTask.id.desc()).limit(101).all()
    cutoff = datetime.utcnow() - timedelta(days=7)
    failed = q.filter(ClientTask.status == 'failed', ClientTask.created_at >= cutoff).order_by(ClientTask.id.desc()).limit(101).all()
    report = db.get(Observation, client_id)
    receipt = json.loads(report.report_json) if report else {}
    from .client_governance import policy_view
    target = policy_view(db, client_id)
    current_version = receipt.get('policy_version') if (report and datetime.utcnow() - report.reported_at < timedelta(seconds=30)
        and receipt.get('policy_code') == 'aidr_desktop_policy_applied'
        and receipt.get('policy_version') == target.get('runtime_governance_version')) else None
    successes = q.filter(ClientTask.status == 'succeeded', ClientTask.created_at >= cutoff).order_by(ClientTask.id.desc()).limit(500).all()
    def scope(row):
        p = json.loads(row.payload_json)
        # Only compare the same actual target; request identifiers and actors do not change it.
        return row.task_type, {k: v for k, v in p.items() if k not in ('request_id', 'actor', 'task_id')}
    for row in failed:
        if row.error in ('aidr_desktop_task_superseded', 'policy_superseded'):
            continue
        payload = json.loads(row.payload_json)
        resolved = any(s.id > row.id and scope(s) == scope(row) for s in successes)
        if row.task_type == 'aidr_plugin_action' and payload.get('action') == 'reconcile' and current_version:
            resolved |= any(s.id > row.id and s.task_type == row.task_type and
                            json.loads(s.payload_json).get('action') == 'reconcile' and
                            json.loads(s.payload_json).get('policy_version') == current_version for s in successes)
        if not resolved:
            active.append(row)
    result['attention'] = [present(row) for row in active[:100]]
    result['attention_truncated'] = len(active)>100 or len(failed)>100
    return result


def details(db, client_id, source, since, until, agent='', dimension='', value='', page=1, page_size=30):
    agent = product_id(agent)

    def paginate(query, present_row):
        total = query.order_by(None).count()
        current = min(page, max(1, (total + page_size - 1) // page_size))
        rows = query.offset((current - 1) * page_size).limit(page_size).all()
        return dict(items=[present_row(row) for row in rows], total=total, page=current, page_size=page_size)

    if dimension == 'sessions':
        q = db.query(OverviewEvidence.session_key, OverviewEvidence.agent, OverviewEvidence.session_id,
                     func.max(OverviewEvidence.at).label('at')).filter(OverviewEvidence.client_id == client_id,
            OverviewEvidence.source == source, OverviewEvidence.at >= since, OverviewEvidence.at < until,
            OverviewEvidence.session_key != '')
        if agent: q = q.filter(OverviewEvidence.product == agent)
        q = q.group_by(OverviewEvidence.session_key, OverviewEvidence.agent, OverviewEvidence.session_id)
        return paginate(q.order_by(func.max(OverviewEvidence.at).desc(), OverviewEvidence.session_key.desc()),
                        lambda r: dict(key=r.session_key, agent=r.agent, session_id=r.session_id, at=r.at))
    q = db.query(OverviewOperation).filter(OverviewOperation.client_id == client_id,
        OverviewOperation.source == source, OverviewOperation.at >= since, OverviewOperation.at < until)
    if agent:
        q = q.filter(OverviewOperation.product == agent)
    if dimension == 'commands' and not value:
        q = q.filter(OverviewOperation.command != '')
    elif dimension in ('commands', 'command_occurrences'):
        if value:
            q = q.filter(text('EXISTS (SELECT 1 FROM json_each(aidr_overview_operations.command_counts_json) j WHERE j.key=:program)')).params(program=value)
        else:
            q = q.filter(OverviewOperation.command_counts_json != '{}')
    elif dimension == 'tools' and value:
        q = q.filter(OverviewOperation.tool == value)
    elif dimension == 'agents' and value:
        q = q.filter(OverviewOperation.product == value)
    elif dimension == 'failures':
        q = q.filter(OverviewOperation.failed == 1)
    return paginate(q.order_by(OverviewOperation.at.desc(), OverviewOperation.key.desc()),
                    lambda r: dict(key=r.key, agent=r.product, at=r.at, tool=r.tool, command=r.command,
                                   command_counts=json.loads(r.command_counts_json),
                                   failed=bool(r.failed), record_id=str(r.record_id)))


def detail_entry(db, client_id, source, record_id):
    from .aidr_content import metadata_view
    from .aidr_hook_queries import related, present as present_hook
    from .aidr_models import AidrOperation
    from .aidr_operations import present
    model = AidrHookEvent if source == 'hooks' else AidrEvent
    row = db.query(model).filter_by(id=record_id, client_id=client_id, expired_at=None).first()
    if not row:
        return None
    raw = json.loads(row.payload_json)
    if source == 'hooks':
        result = related(db, client_id, row)
        return dict(key=str(row.id), at=raw.get('received_at'), records=result['items'] or [present_hook(row, db)])
    key = operation_key(client_id, raw)
    op = db.query(AidrOperation).filter_by(client_id=client_id, operation_key=key, expired_at=None).first()
    return dict(key=str(row.id), at=raw.get('observed_at'), operation=metadata_view(present(op))) if op else None


def tick():
    from .sqlite_db import SessionLocal
    with SessionLocal() as db:
        return advance(db)


async def projection_loop():
    while True:
        try:
            async with admission():
                more = await run_sync(tick)
        except Exception:
            logging.getLogger(__name__).exception('aidr_overview_projection_failed')
            more = False
        await asyncio.sleep(0.2 if more else 5)
