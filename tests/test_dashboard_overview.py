from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.aidr_models import AidrEvent, AidrHookEvent
from backend.api_errors import ApiError, api_error_handler
from backend.routers import dashboard
from backend.sqlite_db import Base, get_db

NOW = datetime(2026, 10, 13, 12)


class FrozenDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return NOW


class Manager:
    def dashboard_stats(self):
        return {"total": 125, "risk_counts": {"benign": 100, "malicious": 5},
                "status_counts": {"VETTED": 123}, "todos": [
                    {"skill_id": str(index), "name": f"skill-{index}", "risk_level": "malicious",
                     "submitted_at": "2026-10-13T10:00:00+00:00"} for index in range(20)]}

    def audit(self, **kwargs):
        return [SimpleNamespace(event_id="one", event_type="skill_approved", skill_name="approved",
                                skill_id="one", timestamp=NOW.replace(tzinfo=timezone.utc),
                                details={"secret": "sensitive-evidence"})]


@pytest.fixture
def context(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    user = models.User(id=1, username="alice", role="operator", is_active=True)
    permissions = {"dashboard:view", "skills:view", "mcp:view", "clients:view", "agents:view", "models:view", "privacy_audit:view"}
    monkeypatch.setattr(dashboard, "datetime", FrozenDatetime)
    monkeypatch.setattr(dashboard.iam, "permission_codes", lambda *_: permissions)
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[auth.get_current_active_user] = lambda: user
    app.dependency_overrides[dashboard.get_manager] = lambda: Manager()
    app.include_router(dashboard.router, prefix="/api")
    with TestClient(app) as client:
        yield client, factory, user, permissions
    engine.dispose()


def test_dashboard_permission_and_module_visibility(context):
    client, _, _, permissions = context
    permissions.clear()
    denied = client.get('/api/v1/dashboard/overview')
    assert denied.status_code == 403
    assert denied.json()['error_code'] == 'iam.permission_denied'
    permissions.add('dashboard:view')
    result = client.get('/api/v1/dashboard/overview').json()
    assert result['assets'] == {}
    assert result['skills'] is None and result['trend'] is None
    assert result['todos']['items'] == [] and result['runtime'] == {} and result['activity'] == []


def test_owned_assets_heartbeat_and_aidr_evidence(context):
    client, factory, user, _ = context
    with factory.begin() as db:
        for client_id, owner, seen in [('online', 'alice', NOW - timedelta(minutes=9)),
                                       ('offline', 'alice', NOW - timedelta(minutes=11)),
                                       ('hidden', 'bob', NOW)]:
            db.add(models.ManagedClient(client_id=client_id, name=client_id, hostname=client_id,
                os='macos', arch='arm64', client_version='test', registered_by=owner, last_seen_at=seen))
            db.add(models.ManagedAgent(agent_id=client_id, name=client_id, created_by=owner))
        for i, (client_id, at, expired) in enumerate([
            ('online', NOW, None), ('online', NOW, None), ('hidden', NOW, None),
            ('offline', NOW - timedelta(hours=25), None), ('offline', NOW, NOW),
        ]):
            db.add(AidrEvent(client_id=client_id, logical_id=str(i), content_hash='hash', agent='codex',
                kind='test', payload_json='{"secret":"sensitive-evidence"}', received_at=at, expired_at=expired))
        db.add(AidrHookEvent(client_id='online', stream_id='stream', event_id='hook', source_seq=1,
            content_hash='hash', payload_json='{}', received_at=NOW))
    result = client.get('/api/v1/dashboard/overview').json()
    assert result['assets']['agents'] == 2
    assert result['assets']['clients'] == {'total': 2, 'online': 1}
    assert result['runtime']['aidr'] == {'reporting_clients': 1, 'records': 3, 'hours': 24}
    user.role = 'super_admin'
    result = client.get('/api/v1/dashboard/overview').json()
    assert result['assets']['clients'] == {'total': 3, 'online': 2}
    assert result['runtime']['aidr']['reporting_clients'] == 2


def test_real_pending_counts_exclude_expired_without_mutating(context):
    client, factory, _, _ = context
    with factory.begin() as db:
        for i in range(25):
            db.add(models.McpToolApproval(approval_hash=str(i), request_id=str(i), token_id=1,
                gateway_slug='gateway', tool_name='tool', arguments_hash='hash',
                status='pending', expires_at=NOW + timedelta(hours=1), created_at=NOW, created_by='alice'))
        db.add(models.McpToolApproval(approval_hash='expired', request_id='expired', token_id=1,
            gateway_slug='gateway', tool_name='tool', arguments_hash='hash', status='pending',
            expires_at=NOW - timedelta(seconds=1), created_at=NOW, created_by='alice'))
    response = client.get('/api/v1/dashboard/overview')
    result = response.json()
    assert response.status_code == 200
    assert result['todos']['counts'] == {'skill': 123, 'mcp': 25}
    assert len(result['todos']['items']) == 40
    assert result['skills']['total'] == 125
    assert sum(result['skills']['risk_counts'].values()) == 105
    assert 'sensitive-evidence' not in response.text
    with factory() as db:
        assert db.query(models.McpToolApproval).filter_by(request_id='expired').one().status == 'pending'


def test_daily_boundaries_zero_fill_and_audit_statuses(context):
    client, factory, _, _ = context
    with factory.begin() as db:
        for i, at in enumerate([NOW, NOW - timedelta(days=6), NOW - timedelta(days=7), NOW + timedelta(days=1)]):
            db.add(models.LlmUsageMetric(request_id=f'usage-{i}', tenant_id='t', conversation_id='c',
                model='model', created_at=at))
        for i, (at, status) in enumerate([(NOW, 'blocked'), (NOW, 'error'), (NOW - timedelta(days=1), 'blocked')]):
            db.add(models.LlmRequestAudit(request_id=f'audit-{i}', tenant_id='t', conversation_id='c',
                user_ref='alice', model='model', status=status, created_at=at))
        for i, status in enumerate(['denied', 'error', 'success']):
            db.add(models.McpCallAudit(request_id=f'mcp-{i}', token_id=1, gateway_slug='g',
                status=status, created_at=NOW, error='sensitive-evidence'))
    result = client.get('/api/v1/dashboard/overview?days=7').json()
    assert len(result['trend']['series']) == 7
    assert result['trend']['series'][0] == {'date': '2026-10-07', 'requests': 1}
    assert result['trend']['series'][-1] == {'date': '2026-10-13', 'requests': 1}
    assert sum(row['requests'] for row in result['trend']['series']) == 2
    assert result['runtime']['model_blocked_today'] == 1
    assert result['runtime']['mcp_denied_today'] == 1
    assert all('error' not in row for row in result['activity'])
    assert len(client.get('/api/v1/dashboard/overview?days=30').json()['trend']['series']) == 30
    assert client.get('/api/v1/dashboard/overview?days=31').status_code == 422


def test_scan_activity_respects_ownership_and_feature_flag(context, monkeypatch):
    client, factory, _, permissions = context
    permissions.add('scans:view')
    with factory.begin() as db:
        for owner in (1, 2):
            db.add(models.SecurityScanTask(task_id=f'scan-{owner}', target_id=f'target-{owner}',
                policy_id='policy', idempotency_key=str(owner), request_fingerprint='fingerprint',
                created_by=str(owner), owner_user_id=owner, timeout_at=NOW + timedelta(hours=1),
                status='succeeded', completed_at=NOW, updated_at=NOW))
    monkeypatch.setattr(dashboard.settings, 'AGENT_SECURITY_SCANNING_ENABLED', True)
    result = client.get('/api/v1/dashboard/overview').json()
    scans = [row for row in result['activity'] if row['source'] == 'scan']
    assert [row['target_id'] for row in scans] == ['scan-1']
    assert 'scan' in result['activity_sources']
    monkeypatch.setattr(dashboard.settings, 'AGENT_SECURITY_SCANNING_ENABLED', False)
    result = client.get('/api/v1/dashboard/overview').json()
    assert not any(row['source'] == 'scan' for row in result['activity'])
    assert 'scan' not in result['activity_sources']


def test_reporting_clients_union_and_metadata_only_activity(context, monkeypatch):
    from sqlalchemy import event
    client, factory, _, permissions = context
    permissions.add('scans:view')
    monkeypatch.setattr(dashboard.settings, 'AGENT_SECURITY_SCANNING_ENABLED', True)
    with factory.begin() as db:
        for cid, owner in [('both', 'alice'), ('hooks-only', 'alice'), ('hidden', 'bob')]:
            db.add(models.ManagedClient(client_id=cid, name=cid, hostname=cid, os='linux', arch='x64',
                                        client_version='test', registered_by=owner))
        for index, (cid, at, expired) in enumerate([
            ('both', NOW, None), ('both', NOW, None), ('hooks-only', NOW, None),
            ('hidden', NOW, None), ('both', NOW, NOW), ('both', NOW+timedelta(seconds=1), None),
            ('both', NOW-timedelta(days=2), None),
        ]):
            db.add(AidrHookEvent(client_id=cid, stream_id='a'*32, event_id=str(index), source_seq=index,
                                content_hash='a'*64, payload_json='{}', received_at=at, expired_at=expired))
        db.add(AidrEvent(client_id='both', logical_id='a'*64, content_hash='b'*64, agent='codex',
                         kind='tool_call', payload_json='{}', received_at=NOW))
        db.add(models.SecurityScanTask(task_id='scan', target_id='target', policy_id='policy',
            idempotency_key='scan', request_fingerprint='hash', owner_user_id=1, created_by='alice',
            timeout_at=NOW+timedelta(hours=1), completed_at=NOW, updated_at=NOW,
            target_snapshot_json='{"private":"large-body"}'))
    sql = []
    def observe(_conn, _cursor, statement, *_):
        sql.append(statement)
    engine = factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        response = client.get('/api/v1/dashboard/overview')
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
    assert response.status_code == 200, response.text
    assert response.json()['runtime']['aidr'] == {'records': 4, 'reporting_clients': 2, 'hours': 24}
    assert not any('target_snapshot_json' in s or 'arguments_preview' in s for s in sql)
    assert all(s.lstrip().upper().startswith('SELECT') for s in sql)


def test_mcp_today_uses_beijing_boundaries(context):
    client, factory, _, _ = context
    start = datetime(2026, 10, 12, 16)
    with factory.begin() as db:
        for index, at in enumerate([start - timedelta(microseconds=1), start,
                                   start + timedelta(days=1, microseconds=-1), start + timedelta(days=1)]):
            db.add(models.McpCallAudit(request_id=f"boundary-{index}", token_id=1,
                                      gateway_slug="test", status="denied", created_at=at))
    assert client.get('/api/v1/dashboard/overview').json()['runtime']['mcp_denied_today'] == 2
