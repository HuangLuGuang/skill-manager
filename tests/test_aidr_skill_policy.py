"""Skill policy delivery, evidence semantics, alert choices and bounded refresh."""
import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from backend import aidr_policy, aidr_skill_usage, auth, iam, models
from backend.aidr_behavior import AuditPolicy
from backend.aidr_models import AidrSkillUse
from backend.aidr_skill_contract import SkillAuditPolicy, SkillUse, skill_audit_policy
from backend.api_errors import ApiError
from backend.routers import system
from tests.test_aidr_api import service
from tests.test_aidr_skill_usage import evidence, setup_certification


@pytest.mark.parametrize('patch', [
    {'max_concurrency': 0}, {'max_concurrency': 9}, {'max_files': 10001},
    {'max_file_bytes': 9 << 20}, {'max_total_bytes': 0}, {'digest_cache_seconds': 59},
    {'status_refresh_seconds': 4}, {'check_mode': 'blocking'}, {'max_files': '100'},
    {'alert_rules': {'approval': 'ignore'}},
])
def test_invalid_resource_policy(patch):
    with pytest.raises(ValidationError):
        SkillAuditPolicy.model_validate(patch)


def test_old_saved_settings_receive_defaults():
    value = skill_audit_policy({'enabled': False, 'alerts': False})
    assert not value['enabled'] and not value['alerts']
    assert value['max_total_bytes'] == 8 << 20 and value['digest_cache_seconds'] == 300


def test_skill_schema_upgrade_preserves_receipts_and_evidence(tmp_path):
    from backend.aidr_migrations import upgrade_aidr_schema
    from tests.test_aidr_migrations import legacy_database
    engine, _ = legacy_database(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql('DROP INDEX ix_aidr_skill_due')
        conn.exec_driver_sql('ALTER TABLE aidr_skill_uses DROP COLUMN next_check_at')
        conn.exec_driver_sql('ALTER TABLE aidr_policy_receipts DROP COLUMN skill_audit_json')
        conn.exec_driver_sql("INSERT INTO aidr_policy_receipts(id,client_id,stream_id,version,enabled,start_sequence,created_at) VALUES('receipt','old','stream','1',1,3,'2026-10-01')")
        conn.exec_driver_sql("INSERT INTO aidr_skill_uses(client_id,call_key,agent,session_id,behavior,certification,payload_json,received_at) VALUES('old','call','claude','session','file_access','pending','{\"original\":true}','2026-10-01')")
    upgrade_aidr_schema(engine); upgrade_aidr_schema(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT id,start_sequence,skill_audit_json FROM aidr_policy_receipts').one() == ('receipt',3,None)
        row = conn.exec_driver_sql('SELECT payload_json,next_check_at FROM aidr_skill_uses').one()
        assert row[0] == '{"original":true}' and str(row[1]).startswith('1970-01-01')
        assert conn.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name='ix_aidr_skill_due'").scalar() == 1
    engine.dispose()


def admin_settings(service):
    client, factory = service
    client.app.include_router(system.router, prefix='/api')
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: actor
    with factory() as db:
        iam.initialize(db)
    return client, factory, actor


def test_global_device_inheritance_validation_conflict_and_permissions(service):
    client, factory, actor = admin_settings(service)
    global_url = '/api/system/aidr-redaction'
    device_url = '/api/v1/clients/one/aidr/audit-policy'
    current = client.get(global_url).json()
    settings = skill_audit_policy({'digest_cache_seconds': 120, 'alert_rules': {'approval': 'record'}})
    result = client.put(global_url, json={'enabled': current['enabled'], 'version': current['version'], 'skill_audit': settings})
    assert result.status_code == 200, result.text
    global_policy = result.json()
    device = client.get(device_url).json()
    assert device['inherit'] and device['skill_audit'] == settings
    assert device['skill_audit_runtime']['skill_audit'] is None
    capture = {**device['capture'], 'model_response': False, 'max_fragment_bytes': 1024, 'max_event_bytes': 2048}
    body = {key: device[key] for key in ('version', 'enabled', 'lifecycle')}
    body.update(inherit=False, global_version=global_policy['version'], capture=capture,
                skill_audit={**settings, 'max_concurrency': 2})
    override = client.put(device_url, json=body)
    assert override.status_code == 200, override.text
    assert override.json()['skill_audit']['max_concurrency'] == 2
    assert client.put(device_url, json=body).status_code == 409
    body['version'] = override.json()['version']
    invalid = client.put(device_url, json={**body, 'skill_audit': {**settings, 'max_files': 0}})
    assert invalid.status_code == 422 and invalid.json().get('error_code')
    actor.role = 'user'
    assert client.put(device_url, json=body).status_code == 403
    actor.role = 'admin'
    restored = client.put(device_url, json={**body, 'inherit': True})
    assert restored.status_code == 200, restored.text
    assert restored.json()['skill_audit'] == settings
    assert int(restored.json()['version']) > int(override.json()['version'])


def test_negotiation_receipt_backlog_and_forged_skill_settings(service):
    client, factory = service
    endpoint = '/api/v1/clients/one/aidr/audit-policy'
    request = {'stream_id': 'a' * 32, 'last_sequence': '0'}
    headers = {'authorization': 'Bearer test-one', 'x-aidr-policy-schema': '2'}
    legacy = client.post(endpoint, json=request, headers=headers).json()
    assert 'skill_audit' not in legacy
    headers['x-aidr-skill-audit'] = '1'
    upgraded = client.post(endpoint, json=request, headers=headers).json()
    assert upgraded['skill_audit'] == skill_audit_policy()
    assert upgraded['receipt'] != legacy['receipt']
    assert client.post(endpoint, json=request, headers=headers).json() == upgraded
    with factory() as db:
        assert db.get(models.AidrPolicyReceipt, legacy['receipt']).end_sequence is None
        aidr_policy.validate_receipt(db, 'one', 'a'*32, 1, AuditPolicy.model_validate(upgraded))
        forged = copy.deepcopy(upgraded); forged['skill_audit']['max_files'] = 1
        with pytest.raises(ApiError) as exc:
            aidr_policy.validate_receipt(db, 'one', 'a'*32, 1, AuditPolicy.model_validate(forged))
        assert getattr(exc.value, 'status_code', None) == 409
    acknowledged = {**request, 'last_sequence': '3', 'applied_receipt': upgraded['receipt'], 'applied_after': '2'}
    assert client.post(endpoint, json=acknowledged, headers=headers).status_code == 200
    with factory() as db:
        assert db.get(models.AidrPolicyReceipt, legacy['receipt']).end_sequence == 2
        aidr_policy.validate_receipt(db, 'one', 'a'*32, 2, AuditPolicy.model_validate(legacy))
    assert client.post(endpoint, json=request, headers={**headers, 'x-aidr-policy-schema': '1'}).status_code == 422


@pytest.mark.parametrize('status,rule', [('content_changed','content_changed'), ('unregistered','approval'), ('unapproved','approval'), ('revoked','approval'), ('unauthorized','unauthorized')])
def test_alert_rules_record_alert_and_master_switch(service, monkeypatch, status, rule):
    _, factory = service
    monkeypatch.setattr(aidr_skill_usage, 'certification', lambda *_: {'status':status, 'reason':status})
    with factory() as db:
        evidence(db, skill={'behavior':'invocation','name':'sample','basis':'tool_input.skill'})
        row = db.query(AidrSkillUse).one()
        settings = skill_audit_policy({'alert_rules': {rule:'record'}})
        result = aidr_skill_usage.refresh(db, row, None, settings)
        assert result['certification']['status'] == status and db.query(models.ClientEvent).count() == 0
        settings['alert_rules'][rule] = 'alert'
        aidr_skill_usage.refresh(db, row, None, settings); db.flush()
        assert db.query(models.ClientEvent).count() == 1
        aidr_skill_usage.refresh(db, row, None, settings); db.flush()
        assert db.query(models.ClientEvent).count() == 1
        settings['alerts'] = False
        aidr_skill_usage.refresh(db, row, None, settings); db.flush()
        assert json.loads(db.query(models.ClientEvent).one().details_json)['active'] is False


def test_pending_limit_reason_and_atomic_evidence_replacement(service):
    _, factory = service
    skill = dict(behavior='file_access', path='/skills/sample/SKILL.md', basis='literal_cat',
                 content_status='unavailable', content_reason='file_size_limit')
    SkillUse.model_validate(skill)
    with factory() as db:
        evidence(db, skill=skill)
        row = db.query(AidrSkillUse).one()
        result = aidr_skill_usage.refresh(db, row, None)
        assert result['certification']['reason'] == 'content_file_size_limit'
        assert db.query(models.ClientEvent).count() == 0
        observed = {key:value for key,value in skill.items() if key != 'content_reason'}
        observed.update(content_status='computed', content_digest='f'*64, content_observed_at=datetime.utcnow().isoformat()+'Z')
        evidence(db, source='log', kind='tool_result', skill=observed)
        actual = json.loads(row.payload_json)['skill']
        assert 'content_reason' not in actual
        SkillUse.model_validate(actual)


def test_maintenance_due_index_and_batch_bound(service, monkeypatch):
    _, factory = service
    monkeypatch.setattr('backend.sqlite_db.SessionLocal', factory)
    calls = []
    monkeypatch.setattr(aidr_skill_usage, 'certification', lambda db,row,manager: calls.append(row.id) or {'status':'pending','reason':'source_unknown'})
    with factory() as db:
        future = datetime.utcnow() + timedelta(hours=1)
        payload = json.dumps({'skill':{'name':'sample'},'stage':'attempted','evidence':[]})
        for n in range(2000):
            db.add(AidrSkillUse(client_id='one',call_key=f'{n:064x}',agent='workbuddy',session_id='session',behavior='invocation',payload_json=payload,
                               next_check_at=datetime.utcnow()-timedelta(seconds=5) if n<55 else future))
        db.commit()
        plan = db.execute(text("EXPLAIN QUERY PLAN SELECT id FROM aidr_skill_uses WHERE expired_at IS NULL AND next_check_at <= :now ORDER BY next_check_at, id LIMIT 50"), {'now':datetime.utcnow()}).all()
        assert any('ix_aidr_skill_due' in str(item) for item in plan)
    aidr_skill_usage.maintenance()
    assert len(calls) == 50
    aidr_skill_usage.maintenance()
    assert len(calls) == 55 and len(set(calls)) == 55
    with factory() as db:
        delta = (db.query(AidrSkillUse).order_by(AidrSkillUse.id).first().next_check_at - datetime.utcnow()).total_seconds()
        assert 0 < delta <= 30


def test_crypto_cache_only_within_refresh_pass(monkeypatch):
    checks = []
    monkeypatch.setattr(aidr_skill_usage, 'verify_content_digest', lambda *args: checks.append(args) or True)
    first = aidr_skill_usage.registry_manager()
    for _ in range(20): assert first.verify_digest('digest','signature')
    assert len(checks) == 1
    aidr_skill_usage.registry_manager().verify_digest('digest','signature')
    assert len(checks) == 2


def test_reported_skill_policy_is_separate_from_target(service):
    client, factory, _ = admin_settings(service)
    with factory() as db:
        device = db.get(models.AidrDevice, 'one')
        device.health_json = json.dumps({'audit_policy':{'policy':{'version':'1','skill_audit':skill_audit_policy({'enabled':False})},'code':'aidr_policy_cached','refreshed_at':'2026-10-09T00:00:00Z'}})
        device.last_seen_at = datetime.utcnow(); db.commit()
    view = client.get('/api/v1/clients/one/aidr/audit-policy').json()
    assert view['skill_audit']['enabled']
    assert not view['skill_audit_runtime']['skill_audit']['enabled']
    assert view['skill_audit_runtime']['code'] == 'aidr_policy_cached'


def test_go_client_http_delivery_collection_ack_and_certification(service, tmp_path, monkeypatch):
    import os
    import socket
    import subprocess
    import threading
    import time
    from pathlib import Path
    import uvicorn
    from agent_manager.core.signer import compute_signature

    client, factory, _ = admin_settings(service)
    root = (tmp_path / 'approved-skill').resolve(); root.mkdir()
    (root / 'SKILL.md').write_text('---\nname: sample\n---\nApproved content')
    monkeypatch.setenv('AGENT_MANAGER_DATA_DIR', str(tmp_path / 'keys'))
    signature = compute_signature(root)
    entry = SimpleNamespace(skill_id='v1',name='sample',family_id='family',version_no=1,skill_path=str(root),status='APPROVED',signature=signature)
    monkeypatch.setattr(aidr_skill_usage, 'registry_manager', lambda: SimpleNamespace(list_certification_candidates=lambda **_:[entry]))
    with factory() as db:
        db.add(models.SystemConfig(key=aidr_policy.KEY,value=json.dumps({'enabled':True,'version':'2','skill_audit':skill_audit_policy({'digest_cache_seconds':120})})))
        db.add(models.ClientSkillInstall(client_id='one',agent_type='claude-code',skill_name='sample',skill_path=str(root),version_id='v1'))
        db.add(models.ClientAgent(client_id='one',local_agent_id='claude',agent_type='claude-code',skills_path=str(root.parent),managed_agent_id='agent'))
        db.add(models.ManagedAgent(agent_id='agent',name='Agent',skill_names_json='["v1"]')); db.commit()
    sock = socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(client.app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic()+10
        while not server.started and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        env = {**os.environ,'SKILL_POLICY_TEST_SERVER':f'http://127.0.0.1:{sock.getsockname()[1]}','SKILL_POLICY_TEST_ROOT':str(root)}
        result = subprocess.run(['go','test','./internal/aidr/upload','-run','^TestSkillPolicyHTTPIntegration$','-count=1','-v'],cwd=Path(__file__).parents[1]/'scanner',env=env,capture_output=True,text=True,timeout=90)
        assert result.returncode == 0, result.stdout+result.stderr
        response = client.get('/api/v1/clients/one/aidr/skill-uses',params={'agent':'claude','session_id':'skill-policy-e2e'})
        assert response.status_code == 200, response.text
        items = response.json()['items']
        assert len(items) == 3
        by_call = {item['native_call_id']:item for item in items}
        assert by_call['first']['certification']['status'] == 'verified'
        assert by_call['reused']['certification']['status'] == 'verified'
        assert by_call['reused']['skill']['content_status'] == 'reused'
        assert by_call['reused']['skill']['content_observed_at'] == by_call['first']['skill']['content_observed_at']
        assert by_call['changed']['certification']['status'] == 'content_changed'
        assert all(item['stage']=='attempted' for item in items)
        with factory() as db:
            assert db.query(models.ClientEvent).filter_by(event_type='aidr_skill_alert').count() == 1
        report = client.get('/api/v1/clients/one/aidr/audit-policy').json()['skill_audit_runtime']
        assert report['skill_audit']['digest_cache_seconds'] == 120 and report['version'] == '2'
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
