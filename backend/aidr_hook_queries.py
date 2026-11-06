"""Bounded metadata-only Hook navigation and exact source identity lookup."""
from . import aidr_adapters
import json
from sqlalchemy import func, or_, literal_column
from .aidr_models import AidrHookEvent
from .aidr_content import metadata_view
from .aidr_hook_context import project as project_context, MAX_ID
from .aidr_tool_completion import supplement

FIELDS = ('agent', 'hook_event', 'session_id', 'tool', 'native_call_id')

def event_field(name):
    return func.json_extract(AidrHookEvent.payload_json, '$.event.' + name)

def present(row, db, log_ceiling=MAX_ID):
    record = project_context(db, row, json.loads(row.payload_json), log_ceiling)
    item = {'id': str(row.id), 'stream_id': row.stream_id, 'record': metadata_view(record)}
    if (record['event'].get('control_decision') or {}).get('decision') == 'ask':
        from .aidr_hook_control import HookAttemptReportRow, HookApprovalRow
        report = db.query(HookAttemptReportRow).filter_by(client_id=row.client_id, stream_id=row.stream_id, event_id=row.event_id).first()
        approval = db.query(HookApprovalRow).filter_by(client_id=row.client_id, stream_id=row.stream_id, event_id=row.event_id).first()
        if report:
            result = json.loads(report.payload)
            item['control_result'] = {'state': result['state'], 'code': result['code'], 'source': 'client_report'}
        elif approval:
            item['control_result'] = {'state': approval.state, 'source': 'platform'}
    return item

def page(db, client_id, *, after=None, before=None, snapshot_id=None, limit=100, filters=None, keyword=None):
    query = db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id, AidrHookEvent.expired_at.is_(None))
    for name, value in (filters or {}).items():
        if value is not None:
            field = AidrHookEvent.event_id if name == 'event_id' else event_field(name)
            query = query.filter(field == value)
    if keyword:
        pattern = '%' + keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(*(event_field(name).like(pattern, escape='\\') for name in FIELDS), AidrHookEvent.event_id.like(pattern, escape='\\')))
    # Explicit after preserves the existing oldest-first API contract.
    if after is not None:
        rows = query.filter(AidrHookEvent.id > after).order_by(AidrHookEvent.id).limit(limit + 1).all()
        items = rows[:limit]
        return {'items': [present(row, db) for row in items], 'has_more': len(rows) > limit,
                'next_after': str(items[-1].id) if items else str(after), 'order': 'oldest'}
    ceiling = snapshot_id
    if ceiling is None:
        ceiling = query.with_entities(func.max(AidrHookEvent.id)).scalar() or 0
    query = query.filter(AidrHookEvent.id <= ceiling)
    if before is not None:
        query = query.filter(AidrHookEvent.id < before)
    rows = query.order_by(AidrHookEvent.id.desc()).limit(limit + 1).all()
    items = rows[:limit]
    return {'items': [present(row, db) for row in items], 'has_more': len(rows) > limit,
            'next_before': str(items[-1].id) if items else str(before or 0),
            'snapshot_id': str(ceiling), 'order': 'newest'}


def related_records(db, client_id, row):
    """Bounded same-source candidates, without content/context enrichment."""
    record = json.loads(row.payload_json)
    event = record['event']
    result = {'relation': 'unknown', 'code': 'identity_missing', 'items': [], 'truncated': False, 'process_relation': 'unknown'}
    if event.get('kind') not in ('tool.pre', 'tool.post', 'tool.failure'):
        result['code'] = 'not_tool_event'
        return result, []
    required = ('agent', 'session_id', 'native_call_id', 'tool')
    if any(not event.get(field) for field in required) or not record.get('user_scope') or (aidr_adapters.get(event['agent']).turn_required and not event.get('turn_id')):
        return result, []
    query = db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id,
        AidrHookEvent.stream_id == row.stream_id, AidrHookEvent.expired_at.is_(None),
        # The required native call ID is nonempty. Match the indexed JSON
        # expression directly before checking the rest of the source identity.
        literal_column("json_extract(payload_json, '$.event.native_call_id')") == event['native_call_id'],
        func.json_extract(AidrHookEvent.payload_json, '$.user_scope') == record['user_scope'])
    for name in ('agent', 'session_id', 'tool', 'native_agent_id') + (() if event['agent'] == 'codex' else ('turn_id',)):
        query = query.filter(func.coalesce(event_field(name), '') == event.get(name, ''))
    query = query.filter(event_field('kind').in_(('tool.pre', 'tool.post', 'tool.failure')))
    rows = query.order_by(AidrHookEvent.id).limit(33).all()
    if len(rows) > 32:
        result.update(code='evidence_budget', truncated=True)
        return result, []
    return result, rows


def related(db, client_id, row):
    result, rows = related_records(db, client_id, row)
    if not rows:
        return result
    event = json.loads(row.payload_json)['event']
    items = [present(item, db) for item in rows]
    if len(json.dumps(items, ensure_ascii=False).encode()) > 131072:
        result.update(code='evidence_budget', truncated=True)
        return result
    result['items'] = items
    kinds = [json.loads(item.payload_json)['event']['kind'] for item in rows]
    calls = kinds.count('tool.pre')
    outcomes = kinds.count('tool.post') + kinds.count('tool.failure')
    if calls > 1 or outcomes > 1:
        result.update(relation='conflicting', code='identity_conflict')
    elif calls == outcomes == 1:
        turns = {json.loads(item.payload_json)['event'].get('turn_id') or '' for item in rows}
        if event['agent'] == 'codex' and '' in turns:
            result.update(code='identity_missing')
        else:
            result.update(relation='matched', code='cross_turn_native_identity_matched' if len(turns) > 1 else 'native_identity_matched')
    else:
        result.update(relation='incomplete', code='counterpart_missing')
        evidence = supplement(db, row)
        if evidence:
            result['execution_evidence'] = evidence
    return result
