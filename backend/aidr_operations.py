"""Deterministic per-device operation view over immutable Agent log evidence."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from .aidr_models import AidrOperation, AidrEvent, AidrAuditState


def dump(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)


def stamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp_timezone_required')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def operation_key(client_id, event):
    parts=[client_id,event['agent'],event['source_id'],event['session_id'],event['turn_id'],event['native_call_id']]
    if not event['session_id'] or (event['agent']=='codex' and not event['turn_id']):
        parts.append(event['logical_event_id'])
    return hashlib.sha256(dump(parts).encode()).hexdigest()


def merge_operation(conn, client_id, event):
    if event['kind'] not in {'tool_call', 'tool_result'}:
        return
    table=AidrOperation.__table__
    key=operation_key(client_id,event)
    prior=conn.execute(select(table).where(table.c.client_id==client_id,table.c.operation_key==key)).mappings().first()
    expired = prior and prior['expired_at'] is not None
    view=json.loads(prior['payload_json']) if prior and not expired else {'call':None,'result':None,'seen_ids':[],'conflicting_evidence':False,'evidence_truncated':False}
    if expired:
        view['history_expired'] = True
    if event['logical_event_id'] in view['seen_ids']:
        return
    if len(view['seen_ids'])<16:
        view['seen_ids'].append(event['logical_event_id'])
    else:
        view['evidence_truncated']=True
    side='call' if event['kind']=='tool_call' else 'result'
    current=view[side]
    if current and (current['content_digest']!=event['content_digest'] or current['outcome']!=event['outcome'] or (current['schema_version']==event['schema_version'] and current.get('behavior')!=event.get('behavior'))):
        view['conflicting_evidence']=True
    elif current is None or event['schema_version']>current['schema_version']:
        view[side]=event
    call,result=view['call'],view['result']
    if view['conflicting_evidence'] or view['evidence_truncated']:
        status='conflicting_evidence'
    elif not call:
        status='missing_call'
    elif not result:
        status='missing_result'
    else:
        behavior=result.get('behavior')
        status=behavior['status'] if behavior else {'success':'reported_complete','error':'reported_error'}.get(result['outcome'],'unknown')
    latest=max(stamp(event['observed_at']),prior['latest_at'] if prior else '')
    values=dict(client_id=client_id,operation_key=key,agent=event['agent'],session_id=event['session_id'],tool=call['tool'] if call else '',result_status=status,latest_at=latest,payload_json=dump(view),received_at=datetime.utcnow(),expired_at=None)
    stmt=insert(table).values(**values)
    conn.execute(stmt.on_conflict_do_update(index_elements=['client_id','operation_key'],set_=values))


def backfill_operations(conn):
    """Create a view of old evidence without reparsing or altering any event."""
    table=AidrAuditState.__table__
    after=conn.execute(select(table.c.value).where(table.c.key=='event_watermark')).scalar() or 0
    events=AidrEvent.__table__
    while True:
        rows=conn.execute(select(events.c.id,events.c.client_id,events.c.payload_json).where(events.c.id>after).order_by(events.c.id).limit(500)).all()
        if not rows:
            break
        for eid,cid,payload in rows:
            if payload != '{}':
                merge_operation(conn,cid,json.loads(payload))
            after=eid
        stmt=insert(table).values(key='event_watermark',value=after)
        conn.execute(stmt.on_conflict_do_update(index_elements=['key'],set_={'value':after}))


def repair_codex_session_projections(conn):
    """Join unique historical halves using native identity; retain immutable events.

    The old oversized-record bug cleared the call's session while its result
    recovered it. No timestamp proximity or tool-name matching is used.
    """
    state = AidrAuditState.__table__
    marker = 'codex_session_projection_repair_v1'
    if conn.execute(select(state.c.value).where(state.c.key == marker)).scalar():
        return 0
    table = AidrOperation.__table__
    groups = {}
    for row in conn.execute(select(table).where(table.c.agent == 'codex', table.c.expired_at.is_(None))).mappings():
        view = json.loads(row['payload_json'])
        for side in ('call', 'result'):
            e = view.get(side)
            if not e:
                continue
            identity = tuple(e.get(k) for k in ('source_id', 'source_instance_id', 'turn_id', 'native_call_id'))
            if not all(identity):
                continue
            key = (row['client_id'], e.get('user_scope'), *identity)
            groups.setdefault(key, []).append((row, view, side))
    repaired = 0
    for halves in groups.values():
        if len(halves) != 2 or {h[2] for h in halves} != {'call', 'result'}:
            continue
        call_row, call_view, _ = next(h for h in halves if h[2] == 'call')
        result_row, view, _ = next(h for h in halves if h[2] == 'result')
        call, result = call_view['call'], view['result']
        if (call_row['id'] == result_row['id'] or call_row['session_id'] or call.get('session_id')
                or not result_row['session_id'] or result.get('session_id') != result_row['session_id']
                or call_view.get('result') or view.get('call')
                or any(v.get(k) for v in (call_view, view) for k in ('conflicting_evidence', 'evidence_truncated', 'history_expired'))):
            continue
        view['call'] = call
        view['seen_ids'] = list(dict.fromkeys(call_view['seen_ids'] + view['seen_ids']))
        view['association'] = 'native_call_same_source_instance'
        behavior = result.get('behavior')
        status = behavior['status'] if behavior else {'success': 'reported_complete', 'error': 'reported_error'}.get(result['outcome'], 'unknown')
        conn.execute(table.update().where(table.c.id == result_row['id']).values(
            tool=call['tool'], result_status=status, payload_json=dump(view),
            latest_at=max(call_row['latest_at'], result_row['latest_at']),
            received_at=min(call_row['received_at'], result_row['received_at'])))
        conn.execute(table.delete().where(table.c.id == call_row['id']))
        repaired += 1
    conn.execute(insert(state).values(key=marker, value=1))
    return repaired


def present(row):
    view=json.loads(row.payload_json)
    call,result=view['call'],view['result']
    elapsed=None
    if call and result:
        delta=(datetime.fromisoformat(stamp(result['observed_at']))-datetime.fromisoformat(stamp(call['observed_at']))).total_seconds()*1000
        if delta>=0:elapsed=round(delta,3)
    return {'id':str(row.id),'operation_key':row.operation_key,'agent':row.agent,'session_id':row.session_id,'tool':row.tool,'status':row.result_status,'latest_at':row.latest_at,'log_elapsed_ms':elapsed,'evidence_type':'agent_log','process_relation':'unknown',**view}


def encode_cursor(row):
    return base64.urlsafe_b64encode(dump([row.latest_at,row.id]).encode()).decode().rstrip('=')


def decode_cursor(value):
    data=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
    if not isinstance(data,list) or len(data)!=2 or not isinstance(data[0],str) or type(data[1]) is not int or not 0<data[1]<=2**63-1:
        raise ValueError('invalid_cursor')
    return stamp(data[0]),data[1]
