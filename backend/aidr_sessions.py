"""Read-only session navigation and source-specific audit timelines."""
import base64
import hashlib
import json
import math

from sqlalchemy import func, text

from .aidr_content import metadata_view, record_contents
from .aidr_hook_queries import present as present_hook
from .aidr_models import AidrHookEvent, AidrOperation, AidrEvent
from .aidr_operations import present as present_operation


def _scope(client_id, **filters):
    return hashlib.sha256(json.dumps([client_id, filters], sort_keys=True).encode()).hexdigest()


def _paging(db, client_id, cursor, scope):
    if not cursor:
        ceilings = [db.query(func.max(model.id)).filter(model.client_id == client_id).scalar() or 0
                    for model in (AidrOperation, AidrHookEvent, AidrEvent)]
        return {'scope': scope, 'ceilings': ceilings, 'position': None}
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        if value['scope'] != scope or len(value['ceilings']) != 3:
            raise ValueError('cursor_scope')
        if not all(type(n) is int and 0 <= n < 2**63 for n in value['ceilings']):
            raise ValueError('cursor_ceiling')
        at, key = value['position']
        if type(at) not in (int, float) or not math.isfinite(at) or not isinstance(key, str) or len(key) > 600:
            raise ValueError('cursor_position')
        return value
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ValueError('invalid_session_cursor') from exc


def _finish(items, rows, limit, paging):
    more = len(rows) > limit
    cursor = ''
    if more:
        last = rows[limit - 1]
        paging = {**paging, 'position': [last['sort_at'], last['key']]}
        cursor = base64.urlsafe_b64encode(json.dumps(paging).encode()).decode().rstrip('=')
    return {'items': items, 'has_more': more, 'next_cursor': cursor}


def sessions(db, client_id, *, cursor='', limit=20, keyword='', agent='', include_questions=False):
    paging = _paging(db, client_id, cursor, _scope(client_id, kind='sessions', keyword=keyword, agent=agent, include_questions=include_questions))
    params = dict(client_id=client_id, log_max=paging['ceilings'][0], hook_max=paging['ceilings'][1], message_max=paging['ceilings'][2],
                  keyword=keyword.lower(), agent=agent, limit=limit + 1, include_questions=include_questions)
    continuation = ''
    if paging['position']:
        params['at'], params['key'] = paging['position']
        continuation = 'AND (sort_at < :at OR (sort_at = :at AND key < :key))'
    rows = db.execute(text(f"""
        WITH evidence AS (
          SELECT agent, session_id, CASE WHEN session_id = '' THEN id ELSE 0 END AS orphan_id,
            julianday(latest_at) AS at, 1 AS logs, 0 AS hooks, 0 AS messages,
            NULL AS prompt_id, 0 AS question_hit
          FROM aidr_operations WHERE client_id = :client_id AND expired_at IS NULL AND id <= :log_max
          UNION ALL
          SELECT json_extract(payload_json, '$.event.agent'), json_extract(payload_json, '$.event.session_id'),
            0, julianday(json_extract(payload_json, '$.received_at')), 0, 1, 0,
            CASE WHEN json_extract(payload_json, '$.event.kind') = 'turn.submit'
              AND EXISTS (SELECT 1 FROM json_each(payload_json, '$.event.contents') c
                WHERE json_extract(c.value, '$.kind') = 'prompt' AND length(json_extract(c.value, '$.text')) > 0)
              THEN id END,
            CASE WHEN :include_questions AND :keyword != '' AND json_extract(payload_json, '$.event.kind') = 'turn.submit'
              THEN EXISTS (SELECT 1 FROM json_each(payload_json, '$.event.contents') c
                WHERE json_extract(c.value, '$.kind') = 'prompt' AND instr(lower(json_extract(c.value, '$.text')), :keyword) > 0)
              ELSE 0 END
          FROM aidr_hook_events WHERE client_id = :client_id AND expired_at IS NULL AND id <= :hook_max
          UNION ALL
          SELECT agent, json_extract(payload_json, '$.session_id'), 0,
            julianday(json_extract(payload_json, '$.observed_at')), 0, 0, 1,
            CASE WHEN kind = 'user_message' AND EXISTS (SELECT 1 FROM json_each(payload_json, '$.message.contents') c
                WHERE length(json_extract(c.value, '$.text')) > 0) THEN -id END,
            CASE WHEN :include_questions AND :keyword != '' AND kind = 'user_message'
              THEN EXISTS (SELECT 1 FROM json_each(payload_json, '$.message.contents') c
                WHERE instr(lower(json_extract(c.value, '$.text')), :keyword) > 0) ELSE 0 END
          FROM aidr_events WHERE client_id=:client_id AND expired_at IS NULL AND id<=:message_max
            AND kind IN ('user_message','assistant_message')
        ), grouped AS (
          SELECT agent, session_id, orphan_id, SUM(logs) AS log_count, SUM(hooks) AS hook_count, SUM(messages) AS message_count,
            MAX(at) AS sort_at, strftime('%Y-%m-%dT%H:%M:%fZ', MAX(at)) AS latest_at,
            json_array(agent, session_id, orphan_id) AS key,
            coalesce(MIN(CASE WHEN prompt_id > 0 THEN prompt_id END), MAX(CASE WHEN prompt_id < 0 THEN prompt_id END)) AS prompt_id,
            MAX(question_hit) AS question_hit
          FROM evidence WHERE (:agent = '' OR agent = :agent)
          GROUP BY agent, session_id, orphan_id
        ) SELECT * FROM grouped
          WHERE (:keyword = '' OR instr(lower(session_id), :keyword) > 0 OR (:include_questions AND question_hit))
          {continuation} ORDER BY sort_at DESC, key DESC LIMIT :limit
    """), params).mappings().all()
    items = [{k: v for k, v in row.items() if k not in ('sort_at', 'question_hit')} for row in rows[:limit]]
    if include_questions:
        prompts = prompt_content(db, client_id, [r['prompt_id'] for r in items if r['prompt_id']])
        for item in items:
            item['question_preview'] = prompts.get(item['prompt_id'], {}).get('display_text', '')[:160]
    return _finish(items, rows, limit, paging)


def prompt_content(db, client_id, ids):
    """Called only for a content-authorized request; never read expired bodies."""
    result = {}
    hook_rows = db.query(AidrHookEvent).filter(AidrHookEvent.client_id == client_id,
            AidrHookEvent.id.in_([i for i in ids if i > 0]), AidrHookEvent.expired_at.is_(None)).all()
    log_rows = db.query(AidrEvent).filter(AidrEvent.client_id == client_id,
            AidrEvent.id.in_([-i for i in ids if i < 0]), AidrEvent.kind == 'user_message', AidrEvent.expired_at.is_(None)).all()
    for row in [*hook_rows, *log_rows]:
        payload = json.loads(row.payload_json)
        contents = [c for c in record_contents(payload) if c.get('kind') == 'prompt']
        body = '\n'.join(c.get('text', '') for c in contents)
        # Codex's captured message can prefix the request with browser/file context.
        # This is a presentation excerpt; the original captured text remains available.
        marker = '\n## My request:\n'
        wrapped = body.lstrip().startswith(('<in-app-browser-context', '# Files mentioned by the user:', '# Response annotations:'))
        display = body.split(marker, 1)[1].strip() if wrapped and marker in body else body
        result[row.id if isinstance(row, AidrHookEvent) else -row.id] = {'text': body, 'display_text': display,
            'truncated': any(c.get('truncated') for c in contents),
            'redacted': any(c.get('redacted') for c in contents)}
    return result


def turn_expression(source):
    if source == 'logs':
        return "coalesce(json_extract(payload_json, '$.call.turn_id'), json_extract(payload_json, '$.result.turn_id'), '')"
    return "coalesce(json_extract(payload_json, '$.event.turn_id'), '')"


def turn_key_expression(source):
    turn = turn_expression(source)
    # A prompt without a native turn ID remains selectable; it cannot own neighboring events.
    missing = "'unassigned'" if source == 'logs' else "CASE WHEN json_extract(payload_json, '$.event.kind') = 'turn.submit' THEN 'prompt:' || id ELSE 'unassigned' END"
    return f"CASE WHEN {turn} != '' THEN 'turn:' || {turn} ELSE {missing} END"


def turns(db, client_id, *, agent, session_id, orphan_id=0, cursor='', limit=100, include_questions=False):
    paging = _paging(db, client_id, cursor, _scope(client_id, kind='turns', agent=agent,
        session_id=session_id, orphan_id=orphan_id, include_questions=include_questions))
    params = dict(client_id=client_id, agent=agent, session_id=session_id, orphan_id=orphan_id,
        log_max=paging['ceilings'][0], hook_max=paging['ceilings'][1], message_max=paging['ceilings'][2], limit=limit+1)
    continuation = ''
    if paging['position']:
        params['at'], params['key'] = paging['position']
        continuation = 'WHERE sort_at > :at OR (sort_at = :at AND key > :key)'
    rows = db.execute(text(f"""
      WITH evidence AS (
        SELECT {turn_key_expression('logs')} AS key, 1 AS logs, 0 AS hooks, 0 AS messages, NULL AS prompt_id,
          julianday(coalesce(json_extract(payload_json, '$.call.observed_at'),
            json_extract(payload_json, '$.result.observed_at'), latest_at)) AS at
        FROM aidr_operations WHERE client_id=:client_id AND agent=:agent AND session_id=:session_id
          AND (:session_id != '' OR id=:orphan_id) AND expired_at IS NULL AND id<=:log_max
        UNION ALL
        SELECT {turn_key_expression('hooks')}, 0, 1, 0,
          CASE WHEN json_extract(payload_json, '$.event.kind')='turn.submit' THEN id END,
          julianday(json_extract(payload_json, '$.received_at'))
        FROM aidr_hook_events WHERE client_id=:client_id AND expired_at IS NULL AND id<=:hook_max
          AND json_extract(payload_json, '$.event.agent')=:agent
          AND json_extract(payload_json, '$.event.session_id')=:session_id AND :session_id != ''
        UNION ALL
        SELECT CASE WHEN coalesce(json_extract(payload_json, '$.turn_id'),'') != '' THEN 'turn:' || json_extract(payload_json, '$.turn_id') ELSE 'unassigned' END,
          0, 0, 1, CASE WHEN kind='user_message' THEN -id END, julianday(json_extract(payload_json, '$.observed_at'))
        FROM aidr_events WHERE client_id=:client_id AND agent=:agent AND expired_at IS NULL AND id<=:message_max
          AND kind IN ('user_message','assistant_message') AND json_extract(payload_json, '$.session_id')=:session_id AND :session_id != ''
      ), grouped AS (
        SELECT key, SUM(logs) AS log_count, SUM(hooks) AS hook_count, SUM(messages) AS message_count, MIN(at) AS sort_at,
          coalesce(MIN(CASE WHEN prompt_id>0 THEN prompt_id END), MAX(CASE WHEN prompt_id<0 THEN prompt_id END)) AS prompt_id, SUM(CASE WHEN prompt_id > 0 THEN 1 ELSE 0 END) AS prompt_count,
          strftime('%Y-%m-%dT%H:%M:%fZ', MIN(at)) AS started_at,
          strftime('%Y-%m-%dT%H:%M:%fZ', MAX(at)) AS latest_at
        FROM evidence GROUP BY key
      ) SELECT * FROM grouped {continuation} ORDER BY sort_at, key LIMIT :limit
    """), params).mappings().all()
    items = [{k: v for k, v in r.items() if k != 'sort_at'} for r in rows[:limit]]
    if include_questions:
        prompts = prompt_content(db, client_id, [r['prompt_id'] for r in items if r['prompt_id']])
        for item in items:
            item['question'] = prompts.get(item['prompt_id'], {})
    return _finish(items, rows, limit, paging)


def _action_search(path):
    # Only metadata is searchable; captured prompt/output/file bodies use the separate content permission.
    return f"""EXISTS (SELECT 1 FROM json_each(payload_json, '{path}') action
        WHERE instr(lower(coalesce(json_extract(action.value, '$.command'), '')), :keyword) > 0
        OR EXISTS (SELECT 1 FROM json_each(action.value, '$.targets') target
          WHERE instr(lower(coalesce(json_extract(target.value, '$.value'), '')), :keyword) > 0))"""


def timeline(db, client_id, *, source, agent, session_id, orphan_id=0, cursor='', limit=30, keyword='', order='oldest', turn_key=''):
    scope = _scope(client_id, kind='timeline', source=source, agent=agent, session_id=session_id,
                   orphan_id=orphan_id, keyword=keyword, order=order, turn_key=turn_key)
    paging = _paging(db, client_id, cursor, scope)
    params = dict(client_id=client_id, agent=agent, session_id=session_id, orphan_id=orphan_id,
                  ceiling=paging['ceilings'][0 if source == 'logs' else 1], message_max=paging['ceilings'][2], keyword=keyword.lower(), limit=limit + 1, turn_key=turn_key)
    if source == 'logs':
        cte = f"""WITH timeline AS (
          SELECT cast(id AS TEXT) AS key, cast(id AS TEXT) AS item_ids,
            julianday(coalesce(json_extract(payload_json, '$.call.observed_at'),
              json_extract(payload_json, '$.result.observed_at'), latest_at)) AS sort_at
          FROM aidr_operations WHERE client_id = :client_id AND expired_at IS NULL AND id <= :ceiling
            AND agent = :agent AND session_id = :session_id
            AND (:session_id != '' OR id = :orphan_id)
            AND (:turn_key = '' OR {turn_key_expression('logs')} = :turn_key)
            AND (:keyword = '' OR instr(lower(tool), :keyword) > 0
              OR {_action_search('$.call.behavior.actions')})
          UNION ALL
          SELECT 'message:' || id, 'message:' || id, julianday(json_extract(payload_json, '$.observed_at'))
          FROM aidr_events WHERE client_id=:client_id AND expired_at IS NULL AND id<=:message_max
            AND agent=:agent AND json_extract(payload_json, '$.session_id')=:session_id AND :session_id != ''
            AND kind IN ('user_message','assistant_message')
            AND (:turn_key='' OR (CASE WHEN coalesce(json_extract(payload_json, '$.turn_id'),'') != '' THEN 'turn:' || json_extract(payload_json, '$.turn_id') ELSE 'unassigned' END)=:turn_key)
            AND (:keyword='' OR instr(kind,:keyword)>0 OR instr(json_extract(payload_json, '$.message.phase'),:keyword)>0)
        )"""
    else:
        # Match the same source/user/agent/session/turn/call/tool/subagent namespace as related().
        # Window counts are computed before searching or paging, so pairs cannot straddle pages.
        cte = f"""WITH raw AS (
          SELECT id, payload_json, json_extract(payload_json, '$.event.kind') AS kind,
            julianday(json_extract(payload_json, '$.received_at')) AS at,
            CASE WHEN json_extract(payload_json, '$.event.kind') IN ('tool.pre','tool.post','tool.failure')
              AND coalesce(json_extract(payload_json, '$.user_scope'), '') != ''
              AND coalesce(json_extract(payload_json, '$.event.native_call_id'), '') != ''
              AND coalesce(json_extract(payload_json, '$.event.tool'), '') != ''
              AND (:agent != 'codex' OR coalesce(json_extract(payload_json, '$.event.turn_id'), '') != '')
            THEN json_array(stream_id, json_extract(payload_json, '$.user_scope'),
              json_extract(payload_json, '$.event.native_call_id'), json_extract(payload_json, '$.event.tool'),
              coalesce(json_extract(payload_json, '$.event.turn_id'), ''),
              coalesce(json_extract(payload_json, '$.event.native_agent_id'), ''))
            ELSE cast(id AS TEXT) END AS identity,
            (:keyword = '' OR instr(lower(coalesce(json_extract(payload_json, '$.event.tool'), '')), :keyword) > 0
              OR instr(lower(json_extract(payload_json, '$.event.hook_event')), :keyword) > 0
              OR {_action_search('$.event.behavior.actions')}) AS hit
          FROM aidr_hook_events WHERE client_id = :client_id AND expired_at IS NULL AND id <= :ceiling
            AND json_extract(payload_json, '$.event.agent') = :agent
            AND json_extract(payload_json, '$.event.session_id') = :session_id AND :session_id != ''
            AND (:turn_key = '' OR {turn_key_expression('hooks')} = :turn_key)
        ), counted AS (
          SELECT *, SUM(kind = 'tool.pre') OVER (PARTITION BY identity) AS calls,
            SUM(kind IN ('tool.post','tool.failure')) OVER (PARTITION BY identity) AS results FROM raw
        ), grouped AS (
          SELECT *, CASE WHEN calls = 1 AND results = 1 THEN identity ELSE cast(id AS TEXT) END AS group_key
          FROM counted
        ), timeline AS (
          SELECT cast(MIN(id) AS TEXT) AS key, group_concat(id) AS item_ids, MIN(at) AS sort_at
          FROM grouped GROUP BY group_key HAVING MAX(hit)
        )"""
    direction, comparison = ('ASC', '>') if order == 'oldest' else ('DESC', '<')
    continuation = ''
    if paging['position']:
        params['at'], params['key'] = paging['position']
        continuation = f'WHERE sort_at {comparison} :at OR (sort_at = :at AND key {comparison} :key)'
    rows = db.execute(text(f'{cte} SELECT *, strftime(\'%Y-%m-%dT%H:%M:%fZ\', sort_at) AS at FROM timeline '
                           f'{continuation} ORDER BY sort_at {direction}, key {direction} LIMIT :limit'), params).mappings().all()
    ids = [int(ident) for row in rows[:limit] for ident in row['item_ids'].split(',') if not ident.startswith('message:')]
    model = AidrOperation if source == 'logs' else AidrHookEvent
    records = {row.id: row for row in db.query(model).filter(model.client_id == client_id, model.id.in_(ids), model.expired_at.is_(None))}
    message_ids = [int(r['item_ids'].split(':')[1]) for r in rows[:limit] if r['item_ids'].startswith('message:')]
    messages = {r.id: r for r in db.query(AidrEvent).filter(AidrEvent.client_id==client_id, AidrEvent.id.in_(message_ids), AidrEvent.expired_at.is_(None))}
    items = []
    for row in rows[:limit]:
        if row['item_ids'].startswith('message:'):
            record = messages.get(int(row['item_ids'].split(':')[1]))
            if record:
                event = metadata_view(json.loads(record.payload_json))
                items.append({'key':row['key'], 'at':row['at'], 'message':event,
                    'turn_key':'turn:'+event['turn_id'] if event.get('turn_id') else 'unassigned'})
            continue
        selected = [records[int(i)] for i in row['item_ids'].split(',') if int(i) in records]
        if not selected:
            continue
        item = {'key': row['key'], 'at': row['at']}
        if source == 'logs':
            item['operation'] = metadata_view(present_operation(selected[0]))
            event = item['operation']['call'] or item['operation']['result']
            item['turn_key'] = 'turn:' + event['turn_id'] if event.get('turn_id') else 'unassigned'
        else:
            selected.sort(key=lambda r: (json.loads(r.payload_json)['received_at'], r.id))
            item['records'] = [present_hook(record) for record in selected]
            event = item['records'][0]['record']['event']
            item['turn_key'] = ('turn:' + event['turn_id'] if event.get('turn_id') else
                'prompt:' + str(selected[0].id) if event['kind'] == 'turn.submit' else 'unassigned')
        items.append(item)
    return _finish(items, rows, limit, paging)
