import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend import models, runtime_governance
from backend.client_issues import batch_issues
from backend.client_diagnostics import DiagnosticLog, unresolved_incidents
from backend.routers.client_diagnostics import query_logs
from backend.sqlite_db import Base


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def client(db, cid='one'):
    row = models.ManagedClient(client_id=cid, name=cid, hostname=cid, os='linux', arch='amd64', client_version='test')
    db.add(row)
    db.flush()
    return row


def group(cid='one', skills=None):
    return {cid: dict(skills=skills or [], alerts=0, classification={
        'runtime_governance_configured': True, 'runtime_governance_version': '1',
        'runtime_governance': {'enabled': True, 'hosts': ['codex'], 'channels': {'logs': False, 'hooks': True, 'system': False}},
    })}


def observation(db, cid='one', state='failed'):
    value = {'protocol': 5, 'policy_code': 'aidr_desktop_policy_applied', 'policy_version': '1',
             'channels': {'hooks': {'state': state, 'enabled': True, 'policy_version': '1',
                'code': 'aidr_hook_running', 'transport_code': 'aidr_hook_runtime_received',
                'reported_at': datetime.now(timezone.utc).isoformat()}}}
    row = runtime_governance.Observation(client_id=cid, report_json=json.dumps(value), reported_at=datetime.utcnow())
    db.add(row)
    return row


def diagnostic(db, record_id, incident, event_name, at, cid='one'):
    content = {'fields': {'incident_id': incident}}
    row = DiagnosticLog(client_id=cid, record_id=record_id, event=event_name,
        occurred_at=at, level='INFO' if event_name == 'sync_recovered' else 'ERROR',
        module='http:heartbeat', version='test', content=json.dumps(content))
    db.add(row)
    return row


def test_four_categories_recover_without_historical_events(db):
    row = client(db)
    report = observation(db)
    skill = models.ClientSkillInstall(client_id='one', agent_type='codex', skill_name='changed',
        skill_path='/skills/changed', signature='a', governance_json=json.dumps({
            'signature': 'a', 'trigger': 'trusted_content_changed', 'action': 'record', 'action_status': 'completed'}))
    db.add(skill)
    failed = models.ClientTask(client_id='one', task_type='apply_model_config', status='failed', payload_json='{"model":"a","request_id":"old"}')
    db.add(failed)
    now = datetime.utcnow()
    incident = 'a' * 32
    diagnostic(db, 'failure', incident, 'sync_failed', now - timedelta(minutes=1))
    db.add(models.ClientEvent(client_id='one', event_type='skill_quarantined', skill_name='old'))
    db.flush()
    data = group(skills=[skill])
    batch_issues(db, {'one': row}, data)
    assert {item['category'] for item in data['one']['current_issues']} == {'collection', 'tasks', 'governance', 'runtime'}
    assert data['one']['issue_task_ids'] == [failed.id]
    assert data['one']['issue_skill_paths'] == ['/skills/changed']

    value = json.loads(report.report_json)
    value['channels']['hooks']['state'] = 'running'
    report.report_json = json.dumps(value)
    skill.governance_json = json.dumps({'signature': 'a', 'trigger': 'trusted_content_changed', 'action': 'quarantine', 'action_status': 'completed'})
    db.add(models.ClientTask(client_id='one', task_type='apply_model_config', status='succeeded', payload_json='{"request_id":"new","model":"a"}'))
    diagnostic(db, 'recovery', incident, 'sync_recovered', now)
    db.flush()
    batch_issues(db, {'one': row}, data)
    assert data['one']['current_issues'] == []
    assert data['one']['issue_task_ids'] == []


def test_runtime_late_recovery_expiry_identity_and_index(db):
    client(db)
    now = datetime.utcnow()
    diagnostic(db, 'recovered-first', 'a'*32, 'sync_recovered', now - timedelta(minutes=1))
    diagnostic(db, 'late-old-error', 'a'*32, 'sync_failed', now - timedelta(minutes=2))
    diagnostic(db, 'active', 'b'*32, 'sync_failed', now - timedelta(seconds=1))
    diagnostic(db, 'old', 'c'*32, 'sync_failed', now - timedelta(days=8))
    diagnostic(db, 'untracked', '', 'sync_failed', now)
    diagnostic(db, 'other-client', 'b'*32, 'sync_recovered', now, cid='other')
    db.flush()
    query = unresolved_incidents(db, ['one'])
    assert [r.incident_id for r in query] == ['b'*32]
    assert [r.record_id for r in query_logs(db, 'one', '', '', '', '', None, None, True)] == ['active']
    sql = str(query.statement.compile(db.bind, compile_kwargs={'literal_binds': True}))
    plan = str(db.execute(text('EXPLAIN QUERY PLAN ' + sql)).all())
    assert 'SEARCH client_diagnostic_logs USING INDEX ix_client_diagnostics_' in plan
    assert 'SCAN client_diagnostic_logs' not in plan


def test_offline_paused_and_superseded_are_not_current_failures(db):
    row = client(db)
    report = observation(db)
    data = group()
    row.last_seen_at = datetime.utcnow() - timedelta(hours=1)
    db.add(models.ClientTask(client_id='one', task_type='aidr_plugin_action', status='failed', error='policy_superseded'))
    db.add(models.ClientTask(client_id='one', task_type='other', status='failed', created_at=datetime.utcnow()-timedelta(days=8)))
    db.flush()
    batch_issues(db, {'one': row}, data)
    assert data['one']['current_issues'] == []
    row.last_seen_at = datetime.utcnow()
    data['one']['classification']['runtime_governance']['enabled'] = False
    value = json.loads(report.report_json)
    value['channels']['hooks']['state'] = 'disabled'
    value['channels']['hooks']['enabled'] = False
    report.report_json = json.dumps(value)
    db.flush()
    batch_issues(db, {'one': row}, data)
    assert data['one']['current_issues'] == []


def test_batch_query_count_does_not_grow_per_client(db):
    clients = {str(i): client(db, str(i)) for i in range(40)}
    data = {}
    for cid in clients:
        data.update(group(cid))
    statements = []
    def count(*args):
        statements.append(args[2])
    event.listen(db.bind, 'before_cursor_execute', count)
    try:
        batch_issues(db, clients, data)
    finally:
        event.remove(db.bind, 'before_cursor_execute', count)
    assert len(statements) == 5
    assert all(not item['current_issues'] for item in data.values())
