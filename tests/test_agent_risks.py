"""Asset summaries expose visible product scopes, not inferred installation identities."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from backend import auth, iam, iam_models, models
from backend.aidr_risk import RiskFinding, RiskConfig, RiskCursor, SOURCES, asset_summaries
from backend.routers import agents
from tests.test_aidr_api import service


@pytest.mark.parametrize('source', SOURCES)
def test_asset_detection_status_preserves_cursor_and_empty_source_semantics(service, source):
    _, factory = service
    asset = SimpleNamespace(instances=[SimpleNamespace(
        client_id='one', client_name='one', agent_type='claude-code')])
    fields = {
        'hooks': dict(stream_id='stream', event_id='event', source_seq=1, content_hash='hash'),
        'logs': dict(logical_id='event', content_hash='hash', agent='claude', kind='tool'),
        'system': dict(monitor_id='monitor', sequence='1', kind='process', received_at='2026-10-24T00:00:00Z'),
    }
    with factory() as db:
        def status():
            asset_summaries(db, [asset])
            return asset.risk_summary.scopes[0].detection_status

        assert status() == 'pending'
        db.add(SOURCES[source](id=10, client_id='one', payload_json='{}', **fields[source]))
        # Another client's newer record must not affect this client's progress.
        db.add(SOURCES[source](id=20, client_id='two', payload_json='{}', **fields[source]))
        db.flush()
        assert status() == 'pending'
        cursor = RiskCursor(source=source, position=9, checked_at=datetime.utcnow())
        db.add(cursor)
        db.flush()
        assert status() == 'pending'
        cursor.position = 10
        db.flush()
        assert status() == 'ready'
        cursor.checked_at = datetime.utcnow() - timedelta(seconds=31)
        db.flush()
        assert status() == 'pending'
        db.add(RiskConfig(client_id='one', revision=1, payload='{"enabled": false}'))
        db.flush()
        assert status() == 'disabled'
        cursor.checked_at = datetime.utcnow()
        db.flush()
        assert status() == 'disabled'


def test_asset_risks_scope_counts_permissions_and_links(service):
    client, factory = service
    client.app.include_router(agents.router, prefix='/api')
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        iam.initialize(db)
        for name in ('mapped', 'unmapped', 'absent', 'empty', 'qoder', 'hidden'):
            db.add(models.ManagedAgent(agent_id=name, name=name, created_by='owner'))
        for cid, local, kind, managed in (
            ('one', 'cli', 'claude-code', 'mapped'), ('one', 'desktop', 'claude-code', 'mapped'),
            ('one', 'custom', 'custom', 'mapped'), ('two', 'cli', 'claude-code', 'mapped'),
            ('one', 'other', 'custom', 'unmapped'), ('one', 'codex', 'codex', 'empty'),
            ('one', 'qoder', 'qoder', 'qoder'), ('two', 'hidden', 'claude-code', 'hidden'),
        ):
            db.add(models.ClientAgent(client_id=cid, local_agent_id=local, agent_type=kind, managed_agent_id=managed))
        for i, (cid, product, severity) in enumerate((
            ('one', 'claude', 'high'), ('one', 'claude', 'medium'), ('two', 'claude', 'high'),
            ('one', '', 'high'), ('one', 'qoder-cli', 'medium'), ('one', 'qoder-hooks', 'high'),
            ('one', 'qoder-ide', 'high'),
        )):
            db.add(RiskFinding(id=str(i), client_id=cid, source='hooks', anchor_id=i,
                               agent=product, risk_code='tool_policy_denied', severity=severity,
                               config_revision=1, rule_version='1', occurred_at=f'2026-10-22T00:00:0{i}Z', time_basis='received'))
        db.commit()

    sql = []
    def capture(_conn, _cursor, statement, *_):
        if 'aidr_risk_findings' in statement:
            sql.append(statement)
    engine = factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        response = client.get('/api/agents/assets')
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert response.status_code == 200, response.text
    rows = {row['agent_id']: row['risk_summary'] for row in response.json()['items']}
    assert len(sql) == 1
    assert rows['mapped']['high'] == rows['mapped']['medium'] == 1
    assert rows['mapped']['highest_severity'] == 'high'
    assert rows['mapped']['latest_at'] == '2026-10-22T00:00:01Z'
    assert rows['mapped']['unmapped_instances'] == 1
    assert rows['mapped']['status'] == 'product_only'
    assert len(rows['mapped']['scopes']) == 1
    assert rows['unmapped']['status'] == 'unmapped'
    assert rows['absent']['status'] == rows['hidden']['status'] == 'no_instance'
    assert rows['empty']['high'] == rows['empty']['medium'] == 0
    assert rows['empty']['highest_severity'] is None
    assert rows['mapped']['detection_pending'] == 1
    assert rows['mapped']['scopes'][0]['detection_status'] == 'pending'
    assert {scope['agent'] for scope in rows['qoder']['scopes']} == {'qoder-cli', 'qoder-hooks'}
    assert rows['qoder']['high'] == rows['qoder']['medium'] == 1
    for summary in rows.values():
        for scope in summary['scopes']:
            assert scope['client_id'] == 'one'
            result = client.get(f"/api/v1/clients/{scope['client_id']}/aidr/risks", params={'agent': scope['agent']})
            assert result.status_code == 200
            assert result.json()['total'] == scope['high'] + scope['medium']

    assert rows['mapped']['open_count'] == 2
    response = client.put('/api/v1/clients/one/aidr/risks/0/disposition', json={
        'expected_revision': 0, 'status': 'resolved', 'reason': 'Verified remediation'})
    assert response.status_code == 200, response.text
    updated = {row['agent_id']: row['risk_summary'] for row in client.get('/api/agents/assets').json()['items']}
    assert updated['mapped']['open_count'] == updated['mapped']['scopes'][0]['open_count'] == 1
    assert updated['mapped']['high'] == updated['mapped']['medium'] == 1

    response = client.put('/api/v1/clients/one/aidr/risks/configuration', json={'enabled': False})
    assert response.status_code == 200, response.text
    disabled = {row['agent_id']: row['risk_summary'] for row in client.get('/api/agents/assets').json()['items']}
    assert disabled['mapped']['detection_disabled'] == 1
    assert disabled['mapped']['detection_pending'] == 0
    assert disabled['mapped']['scopes'][0]['detection_status'] == 'disabled'
    assert disabled['mapped']['high'] == disabled['mapped']['medium'] == 1

    with factory() as db:
        db.query(iam_models.RolePermission).filter_by(role_name='admin', permission_code='clients:view').delete()
        db.commit()
    assert all(row['risk_summary'] is None for row in client.get('/api/agents/assets').json()['items'])

    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username='owner', role='super_admin', is_active=True)
    rows = {row['agent_id']: row['risk_summary'] for row in client.get('/api/agents/assets').json()['items']}
    assert rows['mapped']['high'] == 2 and len(rows['mapped']['scopes']) == 2


def test_multiple_installations_keep_assets_and_risk_scope_separate(service):
    from backend.routers import clients
    client, factory = service
    client.app.include_router(agents.router, prefix='/api')
    client.app.include_router(clients.router, prefix='/api')
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username='owner', role='super_admin', is_active=True)
    now = datetime.utcnow()
    with factory() as db:
        iam.initialize(db)
        db.add(models.ManagedAgent(agent_id='multi-install', name='Multi install', created_by='owner'))
        for cid, local, kind, count in [('one','cli','claude-code',1), ('one','desktop','claude-code',3), ('two','cli','claude-code',2), ('one','custom','custom',0)]:
            root = f'/qa/{cid}/{local}'
            db.add(models.ClientAgent(client_id=cid, local_agent_id=local, agent_type=kind,
                managed_agent_id='multi-install', install_path=root+'/bin', skills_path=root+'/skills'))
            for index in range(count):
                db.add(models.ClientSkillInstall(client_id=cid, agent_type=kind, skill_name=f'{cid}-{local}-{index}', skill_path=root+f'/skills/s{index}'))
        for index, (cid, product) in enumerate([('one','claude'),('one','claude'),('two','claude'),('one','codex'),('one','')]):
            db.add(RiskFinding(id=f'instance-{index}', client_id=cid, source='hooks',anchor_id=index,
                agent=product,risk_code='destructive_command',severity='high',config_revision=1,
                rule_version='1',occurred_at=now.isoformat()+'Z',time_basis='received',detected_at=now))
        db.commit()
    asset = next(row for row in client.get('/api/agents/assets').json()['items'] if row['agent_id']=='multi-install')
    assert asset['risk_summary']['high'] == 3
    assert len(asset['risk_summary']['scopes']) == 2
    for instance in asset['instances']:
        cid, local = instance['client_id'], instance['local_agent_id']
        assert instance['risk_products'] == ([] if local=='custom' else ['claude'])
        workspace = client.get(f'/api/v1/clients/{cid}/agent-workspace',params={'local_agent_id':local})
        assert workspace.status_code == 200, workspace.text
        skills = workspace.json()['agents'][0]['skills']
        assert len(skills) == {('one','cli'):1,('one','desktop'):3,('two','cli'):2,('one','custom'):0}[(cid,local)]
        assert all(s['name'].startswith(f'{cid}-{local}-') for s in skills)
        base = f'/api/v1/clients/{cid}/aidr/risks'
        overview = client.get(base+'/overview',params={'agent':instance['agent_type']}).json()
        expected = 0 if local=='custom' else 2 if cid=='one' else 1
        assert overview['open'] == overview['total'] == expected
        # Clearing optional filters keeps the installation type and client scope.
        for filters in ({}, {'disposition':'open'}, {'risk_code':'destructive_command'},
                        {'detected_since':overview['since'],'detected_before':overview['before']}):
            result = client.get(base, params={'agent_type':instance['agent_type'], **filters}).json()
            assert result['total'] == expected
            assert {r['id'] for r in result['items']} == (set() if local=='custom' else {'instance-0','instance-1'} if cid=='one' else {'instance-2'})
            assert all(r['agent']=='claude' for r in result['items'])
