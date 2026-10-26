"""Metadata-only turn enrichment over retained, immutable log evidence."""
import json
from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert
from .aidr_models import AidrEvent, AidrEventTurn, AidrOperation
from .api_errors import ApiError
from . import aidr_adapters


def event_turn_sql():
    return "coalesce(nullif(json_extract(payload_json,'$.turn_id'),''),(SELECT t.turn_id FROM aidr_event_turns t WHERE t.event_id=aidr_events.id),'')"


def present(db, row):
    event = json.loads(row.payload_json)
    turn = db.get(AidrEventTurn, row.id)
    if turn:
        if not event.get('turn_id'):
            event['turn_id'] = turn.turn_id
        if turn.message_phase and event.get('message'):
            event['message']['phase'] = turn.message_phase
    return event


def apply(db, client_id, coverage):
    links = coverage.turn_links or []
    if not links:
        return
    rows = {r.logical_id: r for r in db.query(AidrEvent).filter(
        AidrEvent.client_id == client_id, AidrEvent.expired_at.is_(None),
        AidrEvent.logical_id.in_([l.logical_event_id for l in links]))}
    for link in links:
        row = rows.get(link.logical_event_id)
        # Missing or expired content is never restored by a metadata replay.
        if row is None:
            continue
        event = json.loads(row.payload_json)
        expected = (coverage.source_id, link.session_id, link.native_call_id, link.content_digest)
        observed = tuple(event.get(k) for k in ('source_id', 'session_id', 'native_call_id', 'content_digest'))
        prior = db.get(AidrEventTurn, row.id)
        phase = link.message_phase or ''
        if phase and (row.agent != 'doubaowork' or row.kind != 'assistant_message'
                      or event.get('message', {}).get('phase') not in ('unspecified', phase)
                      or (prior and prior.message_phase not in ('', phase))):
            raise ApiError(409, 'aidr.turn_link_conflict', '轮次关联与原始记录不一致', 'Turn association conflicts with retained evidence')
        if (not aidr_adapters.get(row.agent).log_turn_links or expected != observed
                or event.get('turn_id') not in ('', link.turn_id)
                or (prior and prior.turn_id != link.turn_id)):
            raise ApiError(409, 'aidr.turn_link_conflict', '轮次关联与原始记录不一致', 'Turn association conflicts with retained evidence')
        db.execute(insert(AidrEventTurn).values(event_id=row.id, turn_id=link.turn_id, message_phase=phase).on_conflict_do_nothing())
        if prior and phase and not prior.message_phase:
            prior.message_phase = phase
        if row.kind not in ('tool_call', 'tool_result'):
            continue
        operations = db.query(AidrOperation).filter(
            AidrOperation.client_id == client_id, AidrOperation.agent == row.agent,
            AidrOperation.session_id == link.session_id, AidrOperation.expired_at.is_(None),
            text("(json_extract(payload_json,'$.call.logical_event_id')=:eid OR json_extract(payload_json,'$.result.logical_event_id')=:eid)")
        ).params(eid=link.logical_event_id)
        for operation in operations:
            view = json.loads(operation.payload_json)
            changed = False
            for side in ('call', 'result'):
                item = view.get(side)
                if item and item.get('logical_event_id') == link.logical_event_id and item.get('turn_id') != link.turn_id:
                    item['turn_id'] = link.turn_id
                    changed = True
            if changed:
                operation.payload_json = json.dumps(view, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
