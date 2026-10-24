"""Statistics and drilldowns share first-detection boundaries and device scope."""
from datetime import datetime, timedelta


from backend import auth, models
from backend.aidr_risk import RiskFinding, RiskCursor, RiskConfig
from backend.aidr_risk_overview import overview
from tests.test_aidr_risk import service, aidr_service, configure, BASE


def finding(id, at, **values):
    return RiskFinding(id=id, client_id='one', source='hooks', anchor_id=1,
        agent='codex', risk_code='destructive_command', severity='high',
        config_revision=0, rule_version='1', occurred_at='2020-01-01T00:00:00Z',
        time_basis='reported', detected_at=at, **values)


def test_aggregates_boundaries_score_and_disposition(service):
    client, factory = service
    configure(client)
    now = datetime.utcnow()
    with factory() as db:
        for source in ['hooks','logs','system']:
            db.add(RiskCursor(source=source, position=0, checked_at=now))
        db.add(finding('old-open', now - timedelta(days=50)))
        db.add(finding('high', now - timedelta(hours=1)))
        medium = finding('medium', now - timedelta(hours=2)); medium.severity = 'medium'; medium.agent = ''
        db.add(medium)
        for state in ['resolved','accepted','false_positive']:
            db.add(finding(state, now - timedelta(hours=3), disposition=state))
        foreign = finding('foreign', now - timedelta(hours=1)); foreign.client_id = 'two'; db.add(foreign)
        db.commit()
        result = overview(db, 'one', 7, 480, now)
        assert result['total'] == 5
        assert result['open'] == 3
        assert result['score'] == {'state':'ready','value':27,'high':2,'medium':1,'weight':19}
        assert result['new_24h'] == 5
        assert [r['id'] for r in result['recent']] == ['high', 'medium', 'old-open']
        assert sum(x['high'] + x['medium'] for x in result['trend']) == 5
        assert sum(x['count'] for x in result['types']) == 5
        assert sum(x['count'] for x in result['dispositions']) == 5
        assert sum(x['high']+x['medium'] for x in result['agents']) == 5
        row = db.get(RiskFinding, 'high'); row.disposition = 'resolved'; db.commit()
        assert overview(db,'one',now=now)['score']['value'] == 17
        row.disposition = 'open'; db.commit()
        assert overview(db,'one',now=now)['score']['value'] == 27
    for bucket in result['trend']:
        response = client.get(BASE, params={'detected_since':bucket['since'], 'detected_before':bucket['before'], 'sort_by':'detected_at'})
        assert response.status_code == 200, response.text
        assert response.json()['total'] == bucket['high']+bucket['medium']
    assert client.get(BASE,params={'unknown_agent':True}).json()['total'] == 1
    assert client.get(BASE,params={'detected_since':'2026-01-01'}).status_code == 422
    assert client.get(BASE,params={'detected_since':'2026-02-01T00:00:00Z','detected_before':'2026-01-01T00:00:00Z'}).status_code == 422


def test_exact_boundary_offset_and_unavailable(service):
    client, factory = service
    configure(client)
    now = datetime(2026,10,23,12)
    with factory() as db:
        db.add(finding('midnight', datetime(2026,10,22,16)))
        db.add(finding('before-midnight', datetime(2026,10,22,15,59,59)))
        db.add(finding('upper-exclusive', now))
        db.commit()
        result = overview(db,'one',7,480,now)
        assert result['score']['state'] == 'processing'
        assert result['score']['value'] is None
        assert result['trend'][-1]['high'] == 1
        assert result['trend'][-2]['high'] == 1
    params = {'detected_since':result['trend'][-1]['since'], 'detected_before':result['before']}
    assert [r['id'] for r in client.get(BASE, params=params).json()['items']] == ['midnight']
    with factory() as db:
        db.add(RiskConfig(client_id='one',revision=2,payload='{"enabled":false}')); db.commit()
        assert overview(db,'one',now=now)['score']['state'] == 'disabled'
    response = client.get(BASE+'/overview',params={'days':30,'offset_minutes':480})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert len(response.json()['trend']) == 30
    for params in ({'days':31},{'offset_minutes':841}):
        assert client.get(BASE+'/overview',params=params).status_code == 422
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1,username='owner',role='user',is_active=True)
    assert client.get(BASE.replace('/one/','/two/')+'/overview').status_code in (403,404)


def test_empty_ready_and_read_access(service):
    client, factory = service
    configure(client)
    with factory() as db:
        for source in ['hooks','logs','system']:
            db.add(RiskCursor(source=source, position=0, checked_at=datetime.utcnow()))
        db.commit()
    response = client.get(BASE+'/overview')
    assert response.status_code == 200
    value = response.json()
    assert value['score']['value'] == 0
    assert value['total'] == value['open'] == value['new_24h'] == 0
    assert value['recent'] == value['agents'] == value['types'] == []
    assert all(r['high'] == r['medium'] == 0 for r in value['trend'])
    from backend import iam_models
    with factory() as db:
        db.add(iam_models.Role(name='overview_reader',display_name='Overview reader')); db.flush()
        db.add(iam_models.RolePermission(role_name='overview_reader',permission_code='clients:view'))
        db.commit()
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=1,username='owner',role='overview_reader',is_active=True)
    assert client.get(BASE+'/overview').status_code == 200
    assert client.get(BASE.replace('/one/','/two/')+'/overview').status_code == 404


def test_custom_period_keeps_current_backlog_and_exact_day_boundaries(service):
    from datetime import timezone
    client, factory = service
    start = datetime(2026, 1, 1, 16, 15)
    end = start + timedelta(days=1, minutes=20)
    with factory() as db:
        for i, at in enumerate([start-timedelta(seconds=1), start, end-timedelta(seconds=1), end]):
            db.add(finding(f'custom-{i}', at))
        db.commit()
    scope = dict(since=int(start.replace(tzinfo=timezone.utc).timestamp()), until=int(end.replace(tzinfo=timezone.utc).timestamp()), offset_minutes=480)
    result = client.get(BASE+'/overview', params=scope).json()
    for invalid in [dict(since=1), dict(since=2, until=1), dict(since=0, until=720*3600+1)]:
        assert client.get(BASE+'/overview', params=invalid).status_code == 422
    assert result['total'] == 2 and result['open'] == 4
    assert result['trend'][0]['since'] == '2026-01-01T16:15:00Z'
    assert result['trend'][-1]['before'] == '2026-01-02T16:35:00Z'
    assert sum(r['high'] + r['medium'] for r in result['trend']) == 2
    for row in result['trend']:
        listed = client.get(BASE, params={'detected_since':row['since'], 'detected_before':row['before']}).json()
        assert listed['total'] == row['high'] + row['medium']


def test_product_scope_is_shared_by_overview_and_drilldown(service):
    client, factory = service
    configure(client)
    now = datetime.utcnow()
    with factory() as db:
        for source in ['hooks', 'logs', 'system']:
            db.add(RiskCursor(source=source, position=0, checked_at=now))
        db.add(finding('codex-current', now - timedelta(hours=1)))
        db.add(finding('codex-old', now - timedelta(days=50)))
        for identity in ['claude-code', '']:
            row = finding('other-' + identity, now - timedelta(hours=1))
            row.agent = identity
            db.add(row)
        foreign = finding('other-client', now - timedelta(hours=1))
        foreign.client_id = 'two'
        db.add(foreign)
        db.commit()
    response = client.get(BASE + '/overview', params={'agent': 'codex'})
    assert response.status_code == 200
    result = response.json()
    assert result['total'] == 1 and result['open'] == 2
    assert result['score']['weight'] == 16
    assert result['new_24h'] == 1
    assert {r['id'] for r in result['recent']} == {'codex-current', 'codex-old'}
    assert sum(r['count'] for r in result['types']) == 1
    assert sum(r['count'] for r in result['dispositions']) == 1
    assert result['agents'] == [{'key': 'codex', 'high': 1, 'medium': 0}]
    for bucket in result['trend']:
        listed = client.get(BASE, params={'agent_type': 'codex', 'detected_since': bucket['since'], 'detected_before': bucket['before']}).json()
        assert listed['total'] == bucket['high'] + bucket['medium']
    assert client.get(BASE, params={'agent_type': 'codex', 'disposition': 'open'}).json()['total'] == 2
    unmapped = client.get(BASE + '/overview', params={'agent': 'not-mapped'}).json()
    assert unmapped['total'] == 0
    assert unmapped['score']['state'] == 'unmapped' and unmapped['score']['value'] is None
    assert client.get(BASE + '/overview').json()['total'] == 3


def test_inventory_aliases_keep_risk_list_and_overview_consistent(service):
    client, factory = service
    now = datetime.utcnow()
    with factory() as db:
        for identity in ['claude', 'qoder-cli', 'qoder-hooks', 'qoder-ide', 'codex', '']:
            row = finding('mapped-' + identity, now - timedelta(hours=1))
            row.agent = identity
            db.add(row)
        db.commit()
    for inventory_type, expected in [('claude-code', {'claude'}), ('qoder', {'qoder-cli', 'qoder-hooks'}), ('not-mapped', set())]:
        result = client.get(BASE + '/overview', params={'agent': inventory_type}).json()
        listed = client.get(BASE, params={'agent_type': inventory_type}).json()
        assert result['total'] == listed['total'] == len(expected)
        assert {r['agent'] for r in listed['items']} == expected
