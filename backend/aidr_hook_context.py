"""Read-time directory evidence for products whose reviews report project roots."""
from sqlalchemy import text
from . import aidr_adapters

MAX_ID = 2**63 - 1


def cwd_expression():
    value = "CASE WHEN json_type(action.value,'$.cwd')='text' AND trim(json_extract(action.value,'$.cwd'))!='' THEN json_extract(action.value,'$.cwd') END"
    return f"""CASE WHEN json_extract(aidr_hook_events.payload_json,'$.event.agent')
      IN ({aidr_adapters.sql_ids('hook_cwd_from_logs')}) THEN (
        SELECT CASE WHEN count(DISTINCT link.id)=1
          AND min(json_extract(link.payload_json,'$.conflicting_evidence'))=0
          AND max(json_extract(link.payload_json,'$.evidence_truncated'))=0
          AND count(DISTINCT {value})=1
          THEN min({value}) END
        FROM aidr_operations link LEFT JOIN json_each(link.payload_json,'$.call.behavior.actions') action ON 1=1
        WHERE link.client_id=aidr_hook_events.client_id AND link.expired_at IS NULL
          AND link.id<=:cwd_log_max
          AND link.agent=json_extract(aidr_hook_events.payload_json,'$.event.agent')
          AND link.session_id=json_extract(aidr_hook_events.payload_json,'$.event.session_id')
          AND link.session_id!=''
          AND coalesce(json_extract(aidr_hook_events.payload_json,'$.user_scope'),'')!=''
          AND json_extract(link.payload_json,'$.call.user_scope')=json_extract(aidr_hook_events.payload_json,'$.user_scope')
          AND coalesce(json_extract(aidr_hook_events.payload_json,'$.event.native_agent_id'),'')=''
          AND coalesce(json_extract(aidr_hook_events.payload_json,'$.event.native_call_id'),'')!=''
          AND json_extract(link.payload_json,'$.call.native_call_id')=json_extract(aidr_hook_events.payload_json,'$.event.native_call_id')
          AND json_extract(link.payload_json,'$.call.tool')=json_extract(aidr_hook_events.payload_json,'$.event.tool')
          AND (coalesce(json_extract(aidr_hook_events.payload_json,'$.event.turn_id'),'')=''
            OR json_extract(link.payload_json,'$.call.turn_id')=json_extract(aidr_hook_events.payload_json,'$.event.turn_id'))
      ) ELSE json_extract(aidr_hook_events.payload_json,'$.event.context.cwd') END"""


def project(db, row, record, log_ceiling=MAX_ID):
    event = record['event']
    if not aidr_adapters.get(event['agent']).hook_cwd_from_logs:
        return record
    cwd = db.execute(text(f"SELECT {cwd_expression()} FROM aidr_hook_events WHERE id=:id"),
                     {'id': row.id, 'cwd_log_max': log_ceiling}).scalar()
    context = event.get('context') or {}
    context.pop('cwd', None)
    if cwd:
        context.update(cwd=cwd, cwd_source='agent_log')
    if context:
        event['context'] = context
    for action in (event.get('behavior') or {}).get('actions', []):
        fields = action.get('source_fields', [])
        if 'record.cwd' in fields:
            action['cwd'] = cwd or ''
            action['source_fields'] = [f for f in fields if f != 'record.cwd']
            if cwd:
                action['cwd_source'] = 'agent_log'
    return record
