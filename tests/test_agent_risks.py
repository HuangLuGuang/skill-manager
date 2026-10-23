"""Asset summaries expose visible product scopes, not inferred installation identities."""
from sqlalchemy import event

from backend import auth, iam, iam_models, models
from backend.aidr_risk import RiskFinding
from backend.routers import agents
from tests.test_aidr_api import service


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

    with factory() as db:
        db.query(iam_models.RolePermission).filter_by(role_name='admin', permission_code='clients:view').delete()
        db.commit()
    assert all(row['risk_summary'] is None for row in client.get('/api/agents/assets').json()['items'])

    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username='owner', role='super_admin', is_active=True)
    rows = {row['agent_id']: row['risk_summary'] for row in client.get('/api/agents/assets').json()['items']}
    assert rows['mapped']['high'] == 2 and len(rows['mapped']['scopes']) == 2
