"""Permission-scoped federation of existing governance records.

Each source filters and counts before pagination. Only the first page-end rows
from each source are merged; there is no fixed recent-record cutoff. Client
projections in the registry are excluded in favor of their authoritative rows.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, case, cast, func, literal, or_, select

from . import client_event_records, iam, iam_models, models

CATEGORIES = ['identity', 'authorization', 'configuration', 'tasks', 'capability', 'other']
RESULTS = ['recorded', 'success', 'failed', 'pending', 'running', 'cancelled',
           'allow', 'deny', 'preview', 'require_approval', 'alert_active', 'alert_inactive', 'unknown']
CLIENT_CATEGORIES = {'discovery':'capability', 'audit':'capability', 'scan':'capability',
                     'remediation':'capability', 'installation':'capability', 'configuration':'configuration'}
IDENTITY_EVENTS = ['client_registered', 'managed_agent_auto_created', 'local_agent_binding_updated', 'takeover_completed']
LEGACY_OPERATIONS = {
    'client_discovery_updated':'discovery_updated', '更新客户端默认分类策略':'default_policy_updated',
    '更新客户端分类策略':'client_policy_updated', '更新客户端策略':'client_policy_updated',
    'aidr.runtime_policy_changed':'runtime_policy_updated', '创建客户端处置任务':'task_created',
    '创建客户端任务':'task_created', '取消客户端任务':'task_cancelled',
    '重试客户端处置任务':'task_retried', '重试客户端任务':'task_retried',
    'aidr.runtime_task_created':'task_created', 'aidr.runtime_task_retried':'task_retried',
    'aidr.skill_observation_requested':'observation_requested',
}
SAFE_FIELDS = ['reason', 'error_code', 'decision_reasons', 'action_id', 'action_type', 'risk_level',
               'local_agent_id', 'managed_agent_id', 'source', 'path', 'task_id', 'policy_version',
               'status_code', 'request_id', 'session_id', 'native_call_id', 'skill_id', 'preview',
               'allowed_models', 'allowed_mcp_gateways', 'note', 'status', 'skill_path']


def decode(raw):
    try:
        value = json.loads(raw or '{}')
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def iso(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()


def result_code(value):
    return {'succeeded':'success', 'completed':'success', 'failure':'failed', 'denied':'deny',
            'submitted':'pending', 'authorized':'allow'}.get(value, value if value in RESULTS else 'unknown')


def source_queries(db, user, codes):
    """Yield query plus normalized SQL fields, retaining source access rules."""
    visible_clients = select(models.ManagedClient.client_id)
    if user.role != 'super_admin':
        visible_clients = visible_clients.where(models.ManagedClient.registered_by == user.username)
    if 'clients:view' in codes:
        e = models.ClientEvent
        category, state, timestamp = client_event_records.expressions()
        yield 'client', db.query(e).filter(e.client_id.in_(visible_clients)), {
            'id':e.id, 'timestamp':timestamp, 'event_type':e.event_type,
            'category':case((e.event_type.in_(IDENTITY_EVENTS), 'identity'),
                            (e.event_type == 'agent_credential_issued', 'authorization'),
                            else_=case(CLIENT_CATEGORIES, value=category, else_='other')),
            'result':case((e.event_type.in_([*IDENTITY_EVENTS, 'agent_credential_issued']), 'recorded'),
                          else_=case({'succeeded':'success', 'submitted':'pending'}, value=state, else_=state)),
            'agent_id':func.coalesce(func.json_extract(e.details_json, '$.managed_agent_id'), ''),
            'local_agent':func.coalesce(e.agent_type, ''), 'client_id':e.client_id,
            'search':[e.skill_name, e.event_type, func.json_extract(e.details_json, '$.path'),
                      func.json_extract(e.details_json, '$.trigger')],
        }
        t = models.ClientTask
        yield 'task', db.query(t).filter(t.client_id.in_(visible_clients)), {
            'id':t.id, 'timestamp':func.coalesce(t.finished_at, t.started_at, t.created_at),
            'event_type':t.task_type, 'category':literal('tasks'),
            'result':case((t.status == 'succeeded', 'success'), else_=t.status),
            'agent_id':func.coalesce(func.json_extract(t.payload_json, '$.managed_agent_id'), ''),
            'local_agent':func.coalesce(func.json_extract(t.payload_json, '$.agent_type'), ''),
            'client_id':t.client_id, 'search':[t.task_type, cast(t.id, String)],
        }
    if 'audit:security' in codes:
        e = models.SecurityAuditEvent
        yield 'security', db.query(e).filter(e.resource_type == 'runtime_task'), {
            'id':e.id, 'timestamp':e.timestamp, 'event_type':e.event_type,
            'category':case((e.event_type == 'runtime_action_authorized', 'authorization'), else_='tasks'),
            'result':case((e.outcome == 'failure', 'failed'), (e.outcome == 'denied', 'deny'), else_=e.outcome),
            'agent_id':case((e.actor.startswith('agent:'), func.substr(e.actor, 7)), else_=''),
            'local_agent':literal(''), 'client_id':literal(''),
            'search':[e.resource_id, e.event_type, e.actor],
        }
    if 'audit:operation' in codes:
        e = iam_models.ManagementAudit
        yield 'management', db.query(e).filter(e.module.in_(['agents', 'clients', 'credentials', 'runtime']),
                                             e.action.notin_(['view', 'get', 'read', 'page_view'])), {
            'id':e.id, 'timestamp':e.created_at, 'event_type':e.action,
            'category':case((e.action == 'execute', 'tasks'),
                            else_=case({'agents':'identity', 'credentials':'authorization'}, value=e.module, else_='configuration')),
            'result':case((e.outcome == 'denied', 'deny'), else_=e.outcome),
            'agent_id':literal(''), 'local_agent':literal(''), 'client_id':literal(''),
            'search':[e.module, e.action, e.target, e.actor],
        }
        e = models.OperationLog
        yield 'operation', db.query(e).filter(e.action.in_(list(LEGACY_OPERATIONS))), {
            'id':e.id, 'timestamp':e.created_at, 'event_type':e.action,
            'category':case((e.action.in_([k for k,v in LEGACY_OPERATIONS.items() if 'task' in v or v == 'observation_requested']), 'tasks'),
                            (e.action == 'client_discovery_updated', 'identity'), else_='configuration'),
            'result':literal('recorded'), 'agent_id':literal(''), 'local_agent':literal(''),
            'client_id':case((e.target.in_(visible_clients), e.target), else_=''),
            'search':[e.action, e.target, e.username],
        }


def page(db, manager, user, *, q='', agent='', client_id='', category='', result='', days=7,
         page=1, page_size=10, order='desc'):
    codes = iam.permission_codes(db, user)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days) if days else None
    end = page * page_size
    entries, total, sources, agent_values, client_values = [], 0, [], set(), set()
    # Names are resolved only from entities the caller may read.
    agents = {}
    if 'agents:view' in codes:
        query = db.query(models.ManagedAgent)
        if user.role != 'super_admin':
            query = query.filter(models.ManagedAgent.created_by == user.username)
        agents = {row.agent_id:row for row in query}
    clients = {}
    if 'clients:view' in codes:
        query = db.query(models.ManagedClient)
        if user.role != 'super_admin':
            query = query.filter(models.ManagedClient.registered_by == user.username)
        clients = {row.client_id:row for row in query}
    matching_agents = [key for key,row in agents.items() if q and q.lower() in row.name.lower()]
    matching_clients = [key for key,row in clients.items() if q and q.lower() in (row.name or row.hostname or '').lower()]

    for source, query, fields in source_queries(db, user, codes):
        sources.append(source)
        for aid, local, cid in query.with_entities(fields['agent_id'], fields['local_agent'], fields['client_id']).distinct():
            if aid: agent_values.add('platform:' + aid)
            if local: agent_values.add('local:' + local)
            if cid in clients: client_values.add(cid)
        if since: query = query.filter(fields['timestamp'] >= since)
        if category: query = query.filter(fields['category'] == category)
        if result: query = query.filter(fields['result'] == result)
        if client_id: query = query.filter(fields['client_id'] == client_id)
        if agent:
            kind, _, value = agent.partition(':')
            query = query.filter(fields['agent_id' if kind == 'platform' else 'local_agent'] == value)
        if q:
            query = query.filter(or_(*(func.coalesce(f, '').contains(q, autoescape=True) for f in fields['search']),
                                     fields['agent_id'].contains(q, autoescape=True), fields['local_agent'].contains(q, autoescape=True),
                                     fields['client_id'].contains(q, autoescape=True), fields['agent_id'].in_(matching_agents),
                                     fields['client_id'].in_(matching_clients)))
        total += query.count()
        sorting = [fields['timestamp'], fields['id']]
        selected = query.add_columns(*(fields[key].label('audit_' + key) for key in
                                      ['timestamp', 'category', 'result', 'agent_id', 'local_agent', 'client_id']))
        selected = selected.order_by(*(v.desc() if order == 'desc' else v.asc() for v in sorting)).limit(end).all()
        linked = {}
        if source == 'client':
            for cid in {record[0].client_id for record in selected}:
                linked.update({(cid, key):value for key,value in client_event_records.usages(db, cid, [r[0] for r in selected if r[0].client_id == cid]).items()})
        for record in selected:
            row = record[0]
            item = {'key':f'{source}:{row.id}', 'source':source, 'source_id':str(row.id),
                    **{key:getattr(record, 'audit_' + key) for key in ['timestamp','category','result','agent_id','local_agent','client_id']}}
            item.update(encode(source, row, linked))
            item['timestamp'] = iso(item['timestamp'])
            item['result'] = result_code(item['result'])
            entries.append(item)
    if 'skills:view' in codes:
        sources.append('registry')
        registry_page = manager.registry.governance_audit_page(since=since, q=q, agent=agent, client_id=client_id,
                                                              category=category, result=result, limit=end, order=order,
                                                              matching_agent_ids=matching_agents)
        total += registry_page['total']
        agent_values.update('platform:' + value for value in registry_page['agents'])
        for raw in registry_page['items']:
            details = raw.get('details') or {}
            entries.append({'key':'registry:' + raw['event_id'], 'source':'registry', 'source_id':raw['event_id'],
                            'event_type':raw['event_type'], 'title':raw['event_type'], 'module':'',
                            'timestamp':iso(raw['timestamp']), 'time_kind':'occurred', 'category':'capability',
                            'result':raw['result'], 'agent_id':details.get('agent_id') or '', 'local_agent':'', 'client_id':'',
                            'actor':raw.get('actor') or '', 'object_id':raw.get('skill_id') or '',
                            'object_name':raw.get('skill_name') or '', 'details':safe_details(details),
                            'skill_id':raw.get('skill_id') if raw.get('skill_id') != 'unknown' else None})
    entries.sort(key=lambda e:(datetime.fromisoformat(e['timestamp']), e['source'],
                              e['source_id'] if e['source'] == 'registry' else int(e['source_id'])),
                 reverse=order == 'desc')
    items = entries[(page-1)*page_size:end]
    for item in items:
        a, c = agents.get(item['agent_id']), clients.get(item['client_id'])
        item.update(agent_name=a.name if a else '', client_name=(c.name or c.hostname) if c else '',
                    agent_origin=a.origin_type if a else '', can_view_agent=bool(a), can_view_client=bool(c))
    return {'items':items, 'total':total, 'page':page, 'page_size':page_size, 'sources':sources,
            'agents':[{'value':v, 'name':agents[v[9:]].name if v.startswith('platform:') and v[9:] in agents else v.split(':',1)[1],
                       'kind':v.split(':',1)[0]} for v in sorted(agent_values)],
            'clients':[{'value':v, 'name':clients[v].name or clients[v].hostname or v} for v in sorted(client_values)],
            'categories':CATEGORIES, 'results':RESULTS}


def safe_details(details):
    scalar = (str, int, float, bool)
    return {key:value for key in SAFE_FIELDS if key in details
            for value in [details[key]] if isinstance(value, scalar)
            or isinstance(value, list) and all(isinstance(part, scalar) for part in value)}


def encode(source, row, linked):
    details = decode(getattr(row, 'details_json', None))
    item = {'event_type':getattr(row, 'event_type', ''), 'module':'', 'title':'', 'actor':'',
            'object_id':'', 'object_name':'', 'time_kind':'occurred', 'details':safe_details(details)}
    if source == 'client':
        usage_id = str(details.get('usage_id', ''))
        p = client_event_records.present(row, details, linked.get((row.client_id, int(usage_id))) if usage_id.isdigit() else None)
        event = {'id':row.id, 'event_type':row.event_type, 'skill_name':row.skill_name, 'agent_type':row.agent_type,
                 'created_at':iso(row.created_at), 'observation_count':row.observation_count,
                 'details':safe_details(details), 'presentation':p}
        item.update(title=row.event_type, object_name=row.skill_name or '', object_id=details.get('managed_agent_id') or '',
                    time_kind=p['time_kind'], client_event=event)
    elif source == 'task':
        payload = decode(row.payload_json)
        item.update(event_type=row.task_type, title='client_task', object_id=str(row.id),
                    object_name=payload.get('skill_name') or '', actor=payload.get('actor') or '', time_kind='task_status',
                    details={**safe_details(payload), 'task_type':row.task_type, 'error_code':row.error or ''})
    elif source == 'security':
        item.update(title=row.event_type, actor=row.actor, object_id=row.resource_id,
                    details={**item['details'], 'decision':row.outcome} if row.event_type == 'runtime_action_authorized' else item['details'])
    elif source == 'management':
        item.update(title='management', module=row.module, event_type=row.action, actor=row.actor, object_id=row.target,
                    details={**item['details'], 'request_id':row.request_id, 'client_ip':row.client_ip})
    elif source == 'operation':
        item.update(title=LEGACY_OPERATIONS[row.action], event_type=LEGACY_OPERATIONS[row.action], actor=row.username,
                    object_id=row.target, time_kind='recorded', details=safe_details(decode(row.details)))
    return item
