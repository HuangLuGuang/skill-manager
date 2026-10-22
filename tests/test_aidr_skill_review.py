"""Skill audit denial, bounded search, observation receipts and evidence scope."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend import aidr_skill_review as review, models
from backend.aidr_models import AidrSkillCheck, AidrSkillUse
from backend.aidr_skill_contract import SkillObservationReceipt
from backend.aidr_skill_usage import refresh
from backend.api_errors import ApiError
from tests.test_aidr_api import service
from tests.test_aidr_skill_usage import evidence, setup_certification


@pytest.mark.parametrize('result_first', [False, True])
def test_denial_is_terminal_even_when_out_of_order(service, result_first):
    _, factory = service
    with factory() as db:
        if result_first:
            evidence(db, 'permission.denied')
        evidence(db, skill={'behavior':'invocation', 'name':'sample', 'basis':'tool_input.skill'})
        if not result_first:
            evidence(db, 'permission.denied')
        row = db.query(AidrSkillUse).one()
        assert json.loads(row.payload_json)['stage'] == 'denied'
        evidence(db, 'tool.post', status='reported_complete')
        assert json.loads(row.payload_json)['stage'] == 'unknown'


def test_filtered_empty_batch_has_continuation_and_search_order(service):
    client, factory = service
    with factory() as db:
        for i in range(201):
            evidence(db, call=str(i), skill={'behavior':'invocation', 'name':f'sample_{i}', 'basis':'tool_input.skill'})
        db.commit()
    url = '/api/v1/clients/one/aidr/skill-uses'
    params = {'agent':'workbuddy', 'session_id':'session', 'certification':'verified', 'order':'newest'}
    first = client.get(url, params=params).json()
    assert first['items'] == [] and first['has_more'] and first['checked_count'] == 200
    second = client.get(url, params={**params, 'after':first['next_cursor']}).json()
    assert second['items'] == [] and second['search_complete'] and second['checked_count'] == 1
    named = client.get(url, params={**params, 'certification':'', 'keyword':'sample_200'}).json()
    assert [x['skill']['name'] for x in named['items']] == ['sample_200']
    assert client.get(url, params={**params, 'keyword':'%'}).json()['items'] == []


@pytest.mark.parametrize('matching_identity', [True, False])
def test_legacy_turn_filter_repairs_only_exact_source_evidence(service, matching_identity):
    client, factory = service
    with factory() as db:
        source = evidence(db, skill={'behavior':'file_access', 'path':'/skills/sample/SKILL.md', 'basis':'literal_cat'})
        raw = json.loads(source.payload_json)
        raw['event']['turn_id'] = 'native-turn'
        if not matching_identity:
            raw['event']['native_call_id'] = 'unrelated-call'
        source.payload_json = json.dumps(raw)
        original = source.payload_json
        row = db.query(AidrSkillUse).one()
        data = json.loads(row.payload_json)
        data.pop('turn_id')
        for ref in data['evidence']:
            ref.pop('turn_id', None)
        row.payload_json = json.dumps(data)
        source_id, uid = source.id, row.id
        db.commit()
    params = {'agent':'workbuddy', 'session_id':'session', 'turn_id':'native-turn'}
    response = client.get('/api/v1/clients/one/aidr/skill-uses', params=params)
    assert response.status_code == 200, response.text
    assert [item['id'] for item in response.json()['items']] == ([str(uid)] if matching_identity else [])
    with factory() as db:
        from backend.aidr_models import AidrHookEvent
        assert db.get(AidrHookEvent, source_id).payload_json == original
        assert json.loads(db.get(AidrSkillUse, uid).payload_json)['turn_id'] == ('native-turn' if matching_identity else '')


def test_history_records_changes_and_evidence_is_scoped(service, tmp_path, monkeypatch):
    client, factory = service
    monkeypatch.setattr('backend.aidr_skill_usage.verify_signature', lambda *args:True)
    with factory() as db:
        row, entry, manager, _ = setup_certification(db, tmp_path)
        first = refresh(db, row, manager); db.flush()
        refresh(db, row, manager); db.flush()
        assert db.query(AidrSkillCheck).count() == 1
        entry.status = 'RETIRED'
        refresh(db, row, manager); db.flush()
        assert db.query(AidrSkillCheck).count() == 2
        other = evidence(db, call='unrelated', skill={'behavior':'invocation','name':'other','basis':'tool_input.skill'})
        ref = first['evidence'][0]
        uid, other_id = row.id, other.id
        db.commit()
    url = f'/api/v1/clients/one/aidr/skill-uses/{uid}/evidence'
    assert client.get(url, params={'source':ref['source'],'record_id':ref['id']}).status_code == 200
    assert client.get(url, params={'source':'hook','record_id':other_id}).status_code == 404
    assert client.get(url.replace('/one/', '/two/'), params={'source':'hook','record_id':ref['id']}).status_code in {403,404}


def prepare_observation(db):
    evidence(db, skill={'behavior':'file_access', 'path':'/skills/sample/SKILL.md', 'basis':'literal_cat'})
    device = db.query(models.ManagedClient).filter_by(client_id='one').one()
    device.status, device.last_seen_at = 'online', datetime.utcnow()
    db.add(models.ClientAgent(client_id='one', local_agent_id='workbuddy', agent_type='workbuddy', skills_path='/skills', capabilities_json='{"skill_audit_observe":true}'))
    db.flush()
    return db.query(AidrSkillUse).one()


@pytest.mark.parametrize('source', ['log', 'hook'])
def test_skill_evidence_content_identity_opens_body(service, source):
    from backend import auth, iam
    client, factory = service
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        iam.initialize(db)
        record = evidence(db, source=source, skill={'behavior':'invocation', 'name':'sample'})
        raw = json.loads(record.payload_json)
        event = raw['event'] if source == 'hook' else raw
        event['contents'] = [{'kind':'tool_output', 'text':'Skill loaded', 'source_field':'result'}]
        record.payload_json = json.dumps(raw)
        usage_id, record_id = db.query(AidrSkillUse).one().id, record.id
        content_id = str(record.id) if source == 'hook' else record.logical_id
        db.commit()
    base = '/api/v1/clients/one/aidr'
    response = client.get(f'{base}/skill-uses/{usage_id}/evidence', params={'source':source, 'record_id':record_id})
    assert response.status_code == 200
    assert response.json()['content_record_id'] == content_id
    assert 'Skill loaded' not in response.text
    content = client.get(f'{base}/content', params={'source':source, 'record_id':content_id})
    assert content.status_code == 200, content.text
    assert content.json()['contents'][0]['text'] == 'Skill loaded'


@pytest.mark.parametrize('redaction_enabled', [True, False])
def test_observation_idempotency_policy_and_original_preservation(service, monkeypatch, redaction_enabled):
    _, factory = service
    monkeypatch.setattr(review, 'registry_manager', lambda:SimpleNamespace(list_certification_candidates=lambda **kw:[]))
    with factory() as db:
        row = prepare_observation(db)
        policy = review.aidr_policy.current(db)
        policy['enabled'] = redaction_enabled
        review.aidr_policy.write_config(db, review.aidr_policy.KEY, policy)
        assert review.observation_availability(db, row) is None
        original = json.loads(row.payload_json)['skill']
        first = review.create_observation(db, row, 'request-one', 'owner')
        assert review.create_observation(db, row, 'request-two', 'owner')['id'] == first['id']
        task = db.get(models.ClientTask, int(first['id']))
        task.status = 'running'
        policy = review.observation_policy(db, task)
        receipt = SkillObservationReceipt(skill={**original, 'content_digest':'a'*64, 'content_status':'computed', 'content_observed_at':datetime.utcnow().isoformat()+'Z'}, observed_at=datetime.utcnow().isoformat()+'Z', policy_version=policy['audit_policy_version'], resolved_path=original['path'])
        review.complete_observation(db, task, receipt)
        db.flush()
        data = json.loads(row.payload_json)
        assert data['skill'] == original
        assert data['latest_observation']['skill']['content_digest'] == 'a'*64
        assert db.query(AidrSkillCheck).one().usage_id == row.id
        receipt.policy_version = 'stale'
        with pytest.raises(ApiError) as exc:
            review.complete_observation(db, task, receipt)
        assert exc.value.code == 'aidr.skill_observation_policy_changed'
        task.status = 'succeeded'; db.flush()
        assert review.create_observation(db, row, 'request-one', 'owner')['id'] == first['id']
        assert review.create_observation(db, row, 'request-three', 'owner')['id'] != first['id']


def test_expired_task_can_be_replaced_and_capability_required(service):
    _, factory = service
    with factory() as db:
        row = prepare_observation(db)
        first = review.create_observation(db, row, 'one', 'owner')
        task = db.get(models.ClientTask, int(first['id']))
        data = json.loads(task.payload_json); data['expires_at'] = (datetime.utcnow()-timedelta(minutes=1)).isoformat()+'Z'; task.payload_json = json.dumps(data); db.flush()
        second = review.create_observation(db, row, 'two', 'owner')
        assert second['id'] != first['id'] and task.status == 'failed'
        db.query(models.ClientAgent).one().capabilities_json = '{}'; db.flush()
        assert review.observation_availability(db, row) == 'observe_upgrade'


def test_runtime_receipt_replay_and_device_binding(service):
    from backend.routers import clients
    client, factory = service
    client.app.include_router(clients.router, prefix='/api')
    with factory() as db:
        row = prepare_observation(db)
        for token in db.query(models.AccessToken):
            token.scopes_json = '["client:read-tasks"]'
        task = review.create_observation(db, row, 'one', 'owner'); db.commit()
    url = f"/api/v1/clients/one/tasks/{task['id']}"
    headers = {'Authorization':'Bearer test-one'}
    result = client.post(url+'/result', headers=headers, json={'status':'running'})
    assert result.status_code == 200, result.text
    policy = client.get(url+'/skill-observation', headers=headers)
    assert policy.status_code == 200, policy.text
    assert client.get(url+'/skill-observation', headers={'Authorization':'Bearer test-two'}).status_code == 403
    skill = {**policy.json()['skill'], 'content_status':'unavailable', 'content_reason':'source_missing'}
    receipt = {'skill':skill, 'observed_at':datetime.utcnow().isoformat()+'Z', 'resolved_path':skill['path'], 'policy_version':policy.json()['audit_policy_version']}
    result = client.post(url+'/result', headers=headers, json={'status':'succeeded', 'skill_observation':receipt})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'succeeded'
    assert client.post(url+'/result', headers=headers, json={'status':'succeeded','skill_observation':receipt}).json()['ignored']


def test_request_requires_update_permission_and_current_policy(service):
    from backend import auth, iam
    client, factory = service
    with factory() as db:
        iam.initialize(db)
        row = prepare_observation(db)
        uid = row.id
        db.commit()
    actor = models.User(id=1, username='owner', role='admin', is_active=True)
    client.app.dependency_overrides[auth.get_current_active_user] = lambda:actor
    url = f'/api/v1/clients/one/aidr/skill-uses/{uid}/observations'
    result = client.post(url, json={'request_id':'one'})
    assert result.status_code == 200, result.text
    assert client.post(url, json={'request_id':'two'}).json()['id'] == result.json()['id']
    actor.role = 'viewer'
    assert client.post(url, json={'request_id':'three'}).status_code == 403


def test_check_history_expires_with_audit_retention(service):
    from backend.aidr_retention import expire_once
    _, factory = service
    with factory() as db:
        row = prepare_observation(db)
        check = AidrSkillCheck(client_id='one',usage_id=row.id,payload_json='{"check":{"status":"pending"}}',received_at=datetime.utcnow()-timedelta(days=10))
        db.add(check); db.commit()
        assert expire_once(db)['aidr_skill_checks'] == 1
        db.refresh(check)
        assert check.payload_json == '{}' and check.expired_at is not None


def test_equivalent_content_checks_reuse_only_current_pass(service, tmp_path, monkeypatch):
    import backend.aidr_skill_usage as usage
    _, factory = service
    calls = []
    original = usage._certification
    def checked(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(usage, '_certification', checked)
    with factory() as db:
        row, entry, manager, _ = setup_certification(db,tmp_path)
        manager.checks = {}
        usage.certification(db,row,manager)
        usage.certification(db,row,manager)
        assert len(calls) == 1
        manager.checks = {}
        usage.certification(db,row,manager)
        assert len(calls) == 2


def test_windows_installation_path_normalization(service):
    from backend.aidr_skill_usage import certification
    _, factory = service
    queries = []
    with factory() as db:
        evidence(db, skill={'behavior':'file_access','path':'C:/Skills/sample/SKILL.md','basis':'literal_cat','content_digest':'a'*64,'content_observed_at':datetime.utcnow().isoformat()+'Z'})
        row = db.query(AidrSkillUse).one()
        db.add(models.ClientSkillInstall(client_id='one',agent_type='workbuddy',skill_name='sample',skill_path='c:\\skills\\sample',version_id='version-one'))
        db.flush()
        def candidates(**filters):
            queries.append(filters)
            return []
        result = certification(db,row,SimpleNamespace(list_certification_candidates=candidates))
        assert result['reason'] == 'registry_reference_missing'
        assert queries == [{'skill_id':'version-one','name':None}]
