from datetime import timedelta, timezone

from backend import models
from backend.aidr_overview import OverviewOperation, OverviewWatermark, OverviewCommandBucket
from backend.aidr_models import AidrHookEvent
from backend.aidr_risk import RiskFinding
from tests.test_dashboard_overview import context, NOW


def seed(factory):
    stamp = int(NOW.replace(tzinfo=timezone.utc).timestamp())
    with factory.begin() as db:
        for client_id, owner in [('visible', 'alice'), ('hidden', 'bob')]:
            db.add(models.ManagedClient(client_id=client_id, name=client_id, hostname=client_id,
                os='macos', arch='arm64', client_version='test', registered_by=owner, last_seen_at=NOW))
        for key, client, source, at, command in [('one', 'visible', 'hooks', stamp, 'command'),
                ('two', 'visible', 'hooks', stamp - 86400, ''),
                ('log', 'visible', 'logs', stamp, ''), ('hidden', 'hidden', 'hooks', stamp, ''),
                ('future', 'visible', 'hooks', stamp + 100, '')]:
            db.add(OverviewOperation(key=key, client_id=client, source=source, product='codex',
                at=at, tool='Bash' if command else 'Read', command=command, failed=int(bool(command)), record_id=1))
        for key, client, at, disposition in [('new', 'visible', NOW, 'open'),
                ('old', 'visible', NOW - timedelta(days=60), 'open'),
                ('handled', 'visible', NOW - timedelta(days=1), 'resolved'),
                ('hidden', 'hidden', NOW, 'open'), ('future', 'visible', NOW + timedelta(days=1), 'open')]:
            db.add(RiskFinding(id=key, client_id=client, source='hooks', anchor_id=1, agent='codex',
                risk_code='destructive_command', severity='high', config_revision=1, rule_version='test',
                occurred_at=at.isoformat(), time_basis='observed', disposition=disposition, detected_at=at))


def get(client, **params):
    response = client.get('/api/v1/dashboard/agent-analytics', params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_behavior_scope_source_and_exact_drilldown(context):
    client, factory, user, _ = context
    seed(factory)
    result = get(client, kind='behavior', days=7)
    assert result['total'] == 2 and result['failures'] == 1 and result['active_agents'] == 1
    assert len(result['trend']) == 7 and sum(row['value'] for row in result['trend']) == 2
    assert len(get(client, kind='behavior', days=30)['trend']) == 30
    assert {row['id'] for row in result['clients']} == {'visible'}
    for category in result['categories']:
        detail = get(client, kind='behavior', details=True, category=category['key'], since=result['since'], until=result['until'])
        assert detail['total'] == category['value']
        assert all('payload' not in row for row in detail['items'])
    assert get(client, kind='behavior', source='logs')['total'] == 1
    assert get(client, kind='behavior', details=True, client_id='hidden')['total'] == 0
    assert get(client, kind='behavior', details=True, tool='Bash')['total'] == 1
    ascending = get(client, kind='behavior', details=True, sort_by='time', sort_order='asc', page_size=1)
    assert ascending['items'][0]['id'] == 'two'
    assert get(client, kind='behavior', details=True, unknown_agent=True)['total'] == 0
    user.role = 'super_admin'
    assert get(client, kind='behavior')['total'] == 3


def test_current_stock_and_detection_period_are_distinct(context):
    client, factory, _, _ = context
    seed(factory)
    result = get(client, kind='risk')
    assert result['total'] == 2 and result['new'] == 2 and result['high'] == 2
    assert sum(row['value'] for row in result['trend']) == 2
    assert result['types'] == [{'key': 'destructive_command', 'value': 2}]
    stock = get(client, kind='risk', details=True, severity='high', page_size=1, page=99)
    assert stock['total'] == 2 and stock['page'] == 2 and stock['items'][0]['id'] == 'old'
    period = get(client, kind='risk', details=True, scope='period', disposition='resolved', since=result['since'], until=result['until'])
    assert period['total'] == 1 and period['items'][0]['id'] == 'handled'
    assert get(client, kind='risk', details=True, client_id='hidden')['total'] == 0
    assert get(client, kind='risk', details=True, scope='period', source='logs')['total'] == 0


def test_analytics_permissions_and_range_validation(context):
    client, _, _, permissions = context
    permissions.remove('clients:view')
    assert client.get('/api/v1/dashboard/agent-analytics', params={'kind': 'risk'}).status_code == 403
    permissions.add('clients:view')
    for params in [{'since': 1}, {'since': 2, 'until': 1}, {'since': 0, 'until': 31 * 86400},
                   {'source': 'system'}, {'days': 8}, {'page_size': 1000}]:
        assert client.get('/api/v1/dashboard/agent-analytics', params={'kind': 'behavior', **params}).status_code == 422


def test_projection_readiness_and_metadata_only_reads(context):
    from sqlalchemy import event
    client, factory, _, _ = context
    seed(factory)
    stamp = int(NOW.replace(tzinfo=timezone.utc).timestamp())
    with factory.begin() as db:
        db.add(AidrHookEvent(id=1, client_id='visible', stream_id='stream', event_id='event',
                            source_seq=1, content_hash='hash', payload_json='{"private":"evidence"}', received_at=NOW))
    assert get(client, kind='behavior')['state'] == 'preparing'
    with factory.begin() as db:
        db.add(OverviewWatermark(source='hooks', position=1, initial_ceiling=1, updated_at=stamp - 120))
    assert get(client, kind='behavior')['state'] == 'delayed'
    with factory.begin() as db:
        db.get(OverviewWatermark, 'hooks').updated_at = stamp
    statements = []
    engine = factory.kw['bind']
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert get(client, kind='behavior')['state'] == 'ready'
        get(client, kind='risk')
        get(client, kind='risk', details=True)
        get(client, kind='behavior', details=True)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert all('payload_json' not in statement for statement in statements)
    assert not any(statement.lstrip().startswith(('insert ', 'update ', 'delete ')) for statement in statements)


def test_command_ranking_uses_buckets_and_exact_boundary_calls(context):
    import json
    client, factory, _, _ = context
    seed(factory)
    stamp = int(NOW.replace(tzinfo=timezone.utc).timestamp())
    with factory.begin() as db:
        db.get(OverviewOperation, 'one').command_counts_json = '{"git":2,"curl":1}'
        for key, offset, count in [('complete', 3600, 3), ('boundary', 4800, 4), ('outside', 6600, 99)]:
            db.add(OverviewOperation(key=key, client_id='visible', source='hooks', product='codex', at=stamp-offset,
                                     tool='Bash', command='command', command_counts_json=json.dumps({'git': count}), failed=0, record_id=1))
        for key, hour, count in [('hour11', stamp-3600, 3), ('hour10', stamp-7200, 103)]:
            db.add(OverviewCommandBucket(key=key, client_id='visible', source='hooks', product='codex', hour=hour, program='git', occurrences=count))
        db.add(OverviewCommandBucket(key='hidden', client_id='hidden', source='hooks', product='codex', hour=stamp-3600, program='secret', occurrences=500))
    params = dict(kind='behavior', since=stamp-5400, until=stamp+1)
    result = get(client, **params)
    assert result['commands'] == [{'key': 'git', 'value': 9}, {'key': 'curl', 'value': 1}]
    detail = get(client, **params, details=True, program='git')
    assert detail['total'] == 3
    assert sum(row['commands']['git'] for row in detail['items']) == 9


def test_reported_assets_are_separate_and_owned(context):
    import json
    client, factory, _, permissions = context
    seed(factory)
    inventory = {'asset_inventory': {'mcp_servers': [{}, {}], 'plugins': [{'mcp_servers': [{}], 'skills': [{}, {}]}]}}
    with factory.begin() as db:
        for client_id in ['visible', 'hidden']:
            db.add(models.ClientAgent(client_id=client_id, agent_type='codex', local_agent_id='cli', capabilities_json=json.dumps(inventory)))
            db.add(models.ClientSkillInstall(client_id=client_id, agent_type='codex', skill_name='local', skill_path='/skills/local'))
    result = client.get('/api/v1/dashboard/overview').json()
    assert result['reported_assets'] == {'agents': 1, 'skills': 1, 'mcp': 3, 'plugins': 1, 'pluginSkills': 2}
    assert result['assets']['skills'] == 125
    permissions.remove('clients:view')
    assert 'reported_assets' not in client.get('/api/v1/dashboard/overview').json()


def test_product_instances_share_dedup_scope_and_paginate(context):
    from sqlalchemy import event
    client, factory, user, permissions = context
    seed(factory)
    with factory.begin() as db:
        for owner, local, product, offset in [('visible', 'cli', 'old', -1),
                ('visible', 'cli', 'codex', 0), ('visible', 'desktop', 'codex', 0),
                ('hidden', 'cli', 'codex', 0), ('visible', None, 'cursor', 0),
                ('visible', 'cursor', 'cursor', -1), ('visible', 'unknown', '', 0),
                ('visible', 'global-skills', 'global-skills', 0)]:
            db.add(models.ClientAgent(client_id=owner, local_agent_id=local, agent_type=product,
                last_scanned_at=NOW + timedelta(days=offset), capabilities_json='{"private":"never return"}'))
    statements = []
    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)
    engine = factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get('/api/v1/dashboard/agent-instances', params={'products': ['codex'], 'page_size': 1, 'page': 99})
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['total'] == 2 and result['page'] == 2 and len(result['items']) == 1
    assert result['items'][0]['client_id'] == 'visible'
    assert all('capabilities_json' not in statement for statement in statements)
    products = client.get('/api/v1/dashboard/overview').json()['agent_products']
    assert {row['key']: row['value'] for row in products} == {'codex': 2, 'cursor': 1, '': 1}
    assert client.get('/api/v1/dashboard/agent-instances', params={'products': 'global-skills'}).json()['total'] == 0
    for row in products:
        detail = client.get('/api/v1/dashboard/agent-instances', params={'products': [row['key']]}).json()
        assert detail['total'] == row['value']
    assert client.get('/api/v1/dashboard/agent-instances', params=[('products', 'cursor'), ('products', '')]).json()['total'] == 2
    user.role = 'super_admin'
    assert client.get('/api/v1/dashboard/agent-instances', params={'products': 'codex'}).json()['total'] == 3
    permissions.remove('clients:view')
    assert client.get('/api/v1/dashboard/agent-instances', params={'products': 'codex'}).status_code == 403
