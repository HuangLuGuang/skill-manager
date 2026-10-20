"""Federated audit visibility, evidence semantics and pagination contracts."""
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from agent_manager.core.models import AuditEvent
from agent_manager.core.registry import Registry
from backend import auth, iam, iam_models, models
from backend.aidr_models import AidrSkillUse
from backend.routers import audit_trail
from backend.sqlite_db import get_db
from tests.test_clients_api import _client


@pytest.fixture
def audit(tmp_path):
    registry = Registry(tmp_path / 'registry')
    client = _client(tmp_path, SimpleNamespace(registry=registry))
    client.app.include_router(audit_trail.router, prefix='/api')
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        username='admin', role='super_admin', is_active=True)
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([models.ManagedClient(client_id=cid, name=cid, hostname=cid, os='linux', arch='amd64',
                                        client_version='test', registered_by=owner)
                    for cid, owner in [('own', 'admin'), ('other', 'someone')]])
        db.commit()
    return client, registry


def get(client, **params):
    response = client.get('/api/v1/audit-trail', params={'days':0, **params})
    assert response.status_code == 200, response.text
    return response.json()


def get_options(client):
    response = client.get('/api/v1/audit-trail/options')
    assert response.status_code == 200, response.text
    return response.json()


def security(**kwargs):
    return models.SecurityAuditEvent(event_id='security-one', timestamp=datetime.utcnow(),
        event_type='runtime_action_authorized', actor='agent:agent-one', resource_type='runtime_task',
        resource_id='runtime-one', action='authorize', outcome='deny', details_json=json.dumps(kwargs),
        prev_hash='', event_hash='hash-one', key_id='key', signature='sig')


def test_sources_are_distinct_and_preserve_decision_and_record_only(audit):
    client, registry = audit
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([
            models.ClientEvent(client_id='own', event_type='skill_governance_recorded', skill_name='sample',
                agent_type='codex', observation_count=12, details_json=json.dumps({'action':'record_only', 'trigger':'unverified'})),
            models.ClientTask(client_id='own', task_type='sync_policy', status='pending'),
            security(action_id='action-one', decision_reasons=['outside_scope'], token='SECRET'),
            iam_models.ManagementAudit(actor='admin', module='agents', action='update', target='agent-one'),
            models.OperationLog(username='admin', action='更新客户端分类策略', target='own'),
        ])
        db.commit()
    registry.log_event(AuditEvent(event_id='registry-one', event_type='skill_load_allowed', skill_id='skill', skill_name='sample'))
    registry.log_event(AuditEvent(event_id='client-event-own-1', event_type='skill_load_blocked', skill_id='skill', skill_name='duplicate'))
    data = get(client)
    assert data['total'] == 6
    assert {row['source'] for row in data['items']} == {'client','task','security','management','operation','registry'}
    event = next(row for row in data['items'] if row['source'] == 'client')
    assert event['result'] == 'recorded'
    assert event['client_event']['presentation']['action'] == 'record_only'
    assert event['client_event']['presentation']['count_kind'] == 'discoveries'
    assert event['agent_id'] == ''  # A local product is not a platform identity.
    decision = get(client, category='authorization', result='deny')['items'][0]
    assert decision['agent_id'] == 'agent-one'
    assert decision['details']['decision'] == 'deny'
    assert 'execution' not in decision and 'SECRET' not in json.dumps(data)
    assert get(client, q='SECRET')['total'] == 0
    assert get(client, agent='local:codex')['total'] == 1
    assert get(client, client_id='own')['total'] == 3


def test_permissions_and_client_ownership_apply_before_counts_and_options(audit):
    client, registry = audit
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([iam_models.RolePermission(role_name='viewer', permission_code=code)
                    for code in ['skills:view', 'clients:view']])
        db.add_all([models.ClientEvent(client_id=cid, event_type='client_registered', agent_type=cid) for cid in ['own','other']])
        db.add_all([security(), iam_models.ManagementAudit(actor='admin', module='agents', action='delete', target='secret-agent')])
        db.commit()
    registry.log_event(AuditEvent(event_id='mirror', event_type='skill_load_blocked', skill_id='s', skill_name='mirror', details={'source':'managed_client', 'agent_id':'secret-agent'}))
    registry.log_event(AuditEvent(event_id='client-event-mirror', event_type='skill_load_blocked', skill_id='s', skill_name='mirror', details={'agent_id':'secret-agent'}))
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(username='admin', role='viewer', is_active=True)
    data = get(client)
    assert data['total'] == 1
    assert data['items'][0]['client_id'] == 'own'
    options = get_options(client)
    assert options['clients'] == [{'value':'own','name':'own'}]
    assert options['agents'] == [{'value':'local:own','name':'own','kind':'local'}]
    assert 'security' not in data['sources'] and 'management' not in data['sources']
    assert get(client, client_id='other')['total'] == 0
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(username='admin', role='empty', is_active=True)
    assert client.get('/api/v1/audit-trail').status_code == 403
    assert client.get('/api/v1/audit-trail/options').status_code == 403


def test_list_and_options_use_independent_queries(audit, monkeypatch):
    client, registry = audit
    old = datetime.utcnow() - timedelta(days=20)
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add(models.ClientEvent(client_id='own', event_type='client_registered', agent_type='codex', created_at=old))
        db.commit()
        engine = db.get_bind()
    registry.log_event(AuditEvent(event_id='old', event_type='skill_submitted', skill_id='s', skill_name='s',
                                 timestamp=old, details={'agent_id':'historical-agent'}))
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.upper())
    original = registry._read_connection
    @contextmanager
    def traced_connection():
        with original() as conn:
            conn.set_trace_callback(lambda statement: statements.append(statement.upper()))
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)
    monkeypatch.setattr(registry, '_read_connection', traced_connection)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        for order in ['asc', 'desc']:
            for page in [1, 2]:
                data = get(client, page=page, page_size=1, order=order)
                assert data['total'] == 2
                assert not {'agents', 'clients', 'categories', 'results'} & data.keys()
        assert not any('SELECT DISTINCT' in statement for statement in statements)
        assert get(client, days=7)['total'] == 0
        statements.clear()
        options = get_options(client)
        assert {row['value'] for row in options['agents']} == {'local:codex', 'platform:historical-agent'}
        assert options['clients'] == [{'value':'own', 'name':'own'}]
        assert any('SELECT DISTINCT' in statement for statement in statements)
        assert not any('COUNT(' in statement for statement in statements)
        registry.log_event(AuditEvent(event_id='new', event_type='skill_submitted', skill_id='s', skill_name='s',
                                     details={'agent_id':'new-agent'}))
        assert 'platform:new-agent' in {row['value'] for row in get_options(client)['agents']}
    finally:
        event.remove(engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('order', ['asc','desc'])
def test_equal_timestamp_pagination_is_stable_across_sources(audit, order):
    client, registry = audit
    stamp = datetime(2026, 1, 1)
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([models.ClientEvent(client_id='own', event_type='client_registered', created_at=stamp) for _ in range(23)])
        db.add_all([models.ClientTask(client_id='own', task_type='rescan', created_at=stamp) for _ in range(12)])
        db.commit()
    for i in range(7):
        registry.log_event(AuditEvent(event_id=f'event-{i}', event_type='skill_submitted', skill_id='s', skill_name='s', timestamp=stamp.replace(tzinfo=timezone.utc)))
    complete = get(client, page_size=100, order=order)['items']
    paged = [item for page in range(1,10) for item in get(client, page=page, page_size=5, order=order)['items']]
    assert [item['key'] for item in complete] == [item['key'] for item in paged]
    assert len(set(item['key'] for item in paged)) == 42


def test_registry_filters_before_limit_and_excludes_client_mirrors(audit):
    _, registry = audit
    stamp = datetime.now(timezone.utc)
    for index in range(1002):
        registry.log_event(AuditEvent(event_id=f'r-{index}', event_type='skill_submitted', skill_id='s',
            skill_name='needle' if index == 0 else 'ordinary', timestamp=stamp + timedelta(seconds=index)))
    result = registry.governance_audit_page(q='needle', limit=1)
    assert result['total'] == 1 and result['items'][0]['skill_name'] == 'needle'


@pytest.mark.parametrize('order', ['asc', 'desc'])
def test_registry_pagination_preserves_submillisecond_order(audit, order):
    client, registry = audit
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for event_id, timestamp in [('z-earlier', stamp + timedelta(microseconds=100)),
                                ('a-later', stamp + timedelta(microseconds=200)),
                                ('naive', stamp.replace(tzinfo=None, microsecond=300)),
                                ('offset', (stamp + timedelta(microseconds=400)).astimezone(timezone(timedelta(hours=8))))]:
        registry.log_event(AuditEvent(event_id=event_id, event_type='skill_submitted', skill_id='s',
            skill_name='s', timestamp=timestamp))
    complete = get(client, page_size=100, order=order)['items']
    paged = [get(client, page=page, page_size=1, order=order)['items'][0] for page in range(1, 5)]
    assert [item['key'] for item in paged] == [item['key'] for item in complete]
    assert registry.governance_audit_page(since=stamp + timedelta(microseconds=150))['total'] == 3


def test_management_execution_is_classified_as_tasks(audit):
    client, _ = audit
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([iam_models.ManagementAudit(actor='admin', module=module, action='execute', target=target)
                    for module, target in [('clients', '/api/v1/clients/own/tasks'),
                                           ('runtime', '/api/v1/runtime-governance/tasks/runtime-one/kill')]])
        db.commit()
    assert get(client, category='tasks')['total'] == 2
    assert get(client, category='configuration')['total'] == 0


def test_skill_evidence_link_and_time_use_existing_semantics(audit):
    client, _ = audit
    old = datetime.utcnow() - timedelta(days=20)
    with next(client.app.dependency_overrides[get_db]()) as db:
        usage = AidrSkillUse(client_id='own', call_key='call', agent='codex', session_id='session', behavior='invocation',
            payload_json=json.dumps({'evidence':[{'at':old.isoformat()+'Z', 'stage':'host_confirmed', 'source':'hook', 'id':'1'}]}))
        db.add(usage); db.flush()
        db.add(models.ClientEvent(client_id='own', event_type='aidr_skill_alert', details_json=json.dumps({
            'usage_id':str(usage.id), 'active':False, 'stage':'host_confirmed', 'behavior':'invocation'})))
        db.commit()
        usage_id = usage.id
    item = get(client)['items'][0]
    assert item['client_event']['presentation']['usage_id'] == str(usage_id)
    assert item['time_kind'] == 'behavior' and item['result'] == 'alert_inactive'
    assert get(client, days=7)['total'] == 0
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.get(AidrSkillUse, usage_id).client_id = 'other'; db.commit()
    item = get(client, days=7)['items'][0]
    assert item['time_kind'] == 'recorded' and item['client_event']['presentation']['usage_id'] is None


def test_query_validation(audit):
    client, _ = audit
    for params in [{'page_size':101}, {'category':'invented'}, {'agent':'unqualified'}, {'order':'invalid'}]:
        assert client.get('/api/v1/audit-trail', params=params).status_code == 422


def test_agent_name_search_and_links_require_visible_asset(audit):
    client, registry = audit
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add(models.ManagedAgent(agent_id='agent-one', name='Operations assistant', created_by='admin'))
        db.add(security()); db.commit()
    registry.log_event(AuditEvent(event_id='agent-skill', event_type='skill_load_allowed', skill_id='s', skill_name='sample', details={'agent_id':'agent-one'}))
    data = get(client, q='Operations assistant')
    assert data['total'] == 2
    assert all(row['agent_name'] == 'Operations assistant' and row['can_view_agent'] for row in data['items'])
    assert get_options(client)['agents'] == [{'value':'platform:agent-one', 'name':'Operations assistant', 'kind':'platform'}]
    with next(client.app.dependency_overrides[get_db]()) as db:
        db.add_all([iam_models.RolePermission(role_name='audit-reader', permission_code=code)
                    for code in ['skills:view', 'audit:security']]); db.commit()
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(username='admin', role='audit-reader', is_active=True)
    assert get(client, q='Operations assistant')['total'] == 0
    assert all(not row['can_view_agent'] and row['agent_name'] == '' for row in get(client)['items'])
    assert get_options(client)['agents'] == [{'value':'platform:agent-one', 'name':'agent-one', 'kind':'platform'}]
    assert get_options(client)['clients'] == []


def test_default_legacy_menu_name_migrates_without_overwriting_custom_title(audit):
    client, _ = audit
    with next(client.app.dependency_overrides[get_db]()) as db:
        menu = iam_models.Menu(name='skill-audit', title_zh='审计追踪', title_en='Skill Audit', path='/audit', is_system=True)
        db.add(menu); db.commit()
        iam.initialize(db)
        assert (menu.title_key, menu.title_en) == ('iam.navigation.skill-audit', 'Audit Trail')
        menu.title_key = None; menu.title_en = 'Custom audit'; db.commit()
        iam.initialize(db)
        assert menu.title_key is None and menu.title_en == 'Custom audit'
