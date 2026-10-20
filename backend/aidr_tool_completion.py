"""Supplement Hook execution state without rewriting Hook evidence."""
import json
from sqlalchemy import func, literal_column
from .aidr_models import AidrEvent, AidrHookEvent, AidrOperation
from .aidr_correlation import operation_identity_filter


def supplement(db, row, *, event_ceiling=2**63-1, hook_ceiling=2**63-1, log_ceiling=2**63-1):
    record = json.loads(row.payload_json)
    event = record['event']
    if event.get('agent') != 'codex' or event.get('kind') != 'tool.pre':
        return None
    if any(not event.get(k) for k in ('session_id', 'turn_id', 'native_call_id', 'tool')) or not record.get('user_scope') or event.get('native_agent_id'):
        return None
    peers = db.query(AidrHookEvent).filter(
        AidrHookEvent.client_id == row.client_id, AidrHookEvent.id <= hook_ceiling,
        AidrHookEvent.expired_at.is_(None),
        *[literal_column("json_extract(payload_json,'$.event." + k + "')") == event[k]
          for k in ('agent', 'session_id', 'native_call_id')]).limit(3).all()
    # A duplicate pre, another user, or any real outcome makes supplementation unsafe/unnecessary.
    if len(peers) != 1 or peers[0].id != row.id:
        return None
    rows = db.query(AidrEvent).filter(
        AidrEvent.client_id == row.client_id, AidrEvent.agent == 'codex',
        AidrEvent.expired_at.is_(None), AidrEvent.id <= event_ceiling,
        *[literal_column("json_extract(payload_json,'$." + k + "')") == event[k]
          for k in ('session_id', 'turn_id', 'native_call_id')],
        literal_column("json_extract(payload_json,'$.completion.source')='codex.item_completed'"),
    ).limit(3).all()
    if rows:
        if len(rows) != 1:
            return None
        evidence = json.loads(rows[0].payload_json)
        if evidence.get('user_scope') != record['user_scope'] or evidence.get('tool') != event['tool']:
            return None
        return dict(hook_status='end_missing', status=evidence['completion']['status'],
                    **({'exit_code': evidence['completion']['exit_code']} if evidence['completion'].get('exit_code') is not None else {}),
                    source='codex.item_completed', relation='native_identity_matched',
                    record_id=str(rows[0].id), logical_event_id=evidence['logical_event_id'],
                    observed_at=evidence['observed_at'])
    operations = db.query(AidrOperation).filter(*operation_identity_filter(row.client_id, event),
        AidrOperation.expired_at.is_(None), AidrOperation.id <= log_ceiling).limit(2).all()
    if len(operations) != 1:
        return None
    view = json.loads(operations[0].payload_json)
    call, result = view.get('call'), view.get('result')
    if not call or not result or call.get('tool') != event['tool'] or any(view.get(k) for k in ('conflicting_evidence', 'evidence_truncated', 'history_expired')):
        return None
    if any(e.get('user_scope') not in (None, '', record['user_scope']) for e in (call, result)):
        return None
    status = (result.get('behavior') or {}).get('status') or {'error':'reported_error', 'success':'reported_complete'}.get(result.get('outcome'), '')
    return dict(hook_status='end_missing',
        status={'reported_error':'failed', 'reported_success':'completed', 'reported_complete':'completed', 'reported_cancelled':'cancelled'}.get(status, 'result_returned'),
        source='agent_log.tool_result', relation='inferred',
        record_id=str(operations[0].id), logical_event_id=result['logical_event_id'],
        observed_at=result['observed_at'])
