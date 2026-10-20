"""Read-time Codex async completion identity; original Hook fields stay intact."""


def turn_expression(ceiling='9223372036854775807'):
    native = "json_extract(aidr_hook_events.payload_json,'$.event.turn_id')"
    fields = ('agent', 'session_id', 'native_call_id', 'tool', 'native_agent_id')
    same = ' AND '.join(
        f"coalesce(json_extract(peer.payload_json,'$.event.{field}'),'')=coalesce(json_extract(aidr_hook_events.payload_json,'$.event.{field}'),'')"
        for field in fields)
    return f"""coalesce(CASE WHEN
      json_extract(aidr_hook_events.payload_json,'$.event.agent')='codex'
      AND json_extract(aidr_hook_events.payload_json,'$.event.kind') IN ('tool.post','tool.failure')
      AND coalesce({native},'')!=''
      AND coalesce(json_extract(aidr_hook_events.payload_json,'$.user_scope'),'')!=''
      AND coalesce(json_extract(aidr_hook_events.payload_json,'$.event.session_id'),'')!=''
      AND coalesce(json_extract(aidr_hook_events.payload_json,'$.event.native_call_id'),'')!=''
      AND coalesce(json_extract(aidr_hook_events.payload_json,'$.event.tool'),'')!=''
      THEN (SELECT CASE WHEN count(*)=2
        AND sum(json_extract(peer.payload_json,'$.event.kind')='tool.pre')=1
        AND sum(json_extract(peer.payload_json,'$.event.kind') IN ('tool.post','tool.failure'))=1
        AND min(length(coalesce(json_extract(peer.payload_json,'$.event.turn_id'),'')))>0
        THEN min(CASE WHEN json_extract(peer.payload_json,'$.event.kind')='tool.pre'
          THEN json_extract(peer.payload_json,'$.event.turn_id') END) END
        FROM aidr_hook_events peer WHERE peer.client_id=aidr_hook_events.client_id
          AND peer.stream_id=aidr_hook_events.stream_id AND peer.expired_at IS NULL AND peer.id<={ceiling}
          AND json_extract(peer.payload_json,'$.event.native_call_id')=json_extract(aidr_hook_events.payload_json,'$.event.native_call_id')
          AND json_extract(peer.payload_json,'$.user_scope')=json_extract(aidr_hook_events.payload_json,'$.user_scope')
          AND {same}
          AND json_extract(peer.payload_json,'$.event.kind') IN ('tool.pre','tool.post','tool.failure'))
      END, {native}, '')"""
