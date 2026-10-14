"""Skill provenance, certification, late delivery and alert idempotency."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from backend import models
from backend.aidr_models import AidrEvent, AidrHookEvent, AidrSkillUse
from backend.aidr_skill_usage import certification, merge, refresh
from agent_manager.core.signer import compute_content_digest
from tests.test_aidr_api import service


def evidence(db, kind='tool.pre', source='hook', call='call', skill=None, status='unknown', scope='501'):
    event = dict(agent='workbuddy', session_id='session', native_call_id=call, user_scope=scope, tool='Skill', kind=kind, behavior={'status':status})
    if skill: event['skill_use'] = skill
    n = db.query(AidrHookEvent).count() + db.query(AidrEvent).count() + 1
    if source == 'hook':
        event.pop('user_scope')
        row = AidrHookEvent(client_id='one',stream_id='a'*32,event_id=f'{n:032x}',source_seq=n,content_hash='b'*64,payload_json=json.dumps({'event':event,'user_scope':scope}))
    else:
        row = AidrEvent(client_id='one',logical_id=f'{n:064x}',content_hash='b'*64,agent='workbuddy',kind=kind,payload_json=json.dumps(event))
    db.add(row); db.flush(); merge(db,source,row); db.flush()
    return row


def test_native_identity_dedup_result_before_call_and_user_isolation(service):
    _, factory = service
    with factory() as db:
        evidence(db,'tool.post',status='reported_complete')
        pre = evidence(db,skill={'behavior':'invocation','name':'sample','basis':'tool_input.skill'})
        evidence(db,'tool_call',source='log',skill={'behavior':'invocation','name':'sample','basis':'tool_input.skill'})
        merge(db,'hook',pre)
        rows = db.query(AidrSkillUse).all()
        assert len(rows) == 1
        data = json.loads(rows[0].payload_json)
        assert data['stage'] == 'host_confirmed' and len(data['evidence']) == 3
        evidence(db,call='other',skill=data['skill'])
        evidence(db,scope='502',skill=data['skill'])
        assert db.query(AidrSkillUse).count() == 3


def setup_certification(db, tmp_path):
    root = tmp_path/'sample'; root.mkdir(); (root/'SKILL.md').write_text('---\nname: sample\n---\nBenign text')
    digest = compute_content_digest(root)
    evidence(db, skill={'behavior':'file_access','path':str(root/'SKILL.md'),'basis':'tool_input.path','content_digest':digest,'content_observed_at':datetime.utcnow().isoformat()+'Z'})
    row = db.query(AidrSkillUse).one()
    entry = SimpleNamespace(skill_id='v1',name='sample',family_id='family',version_no=1,skill_path=str(root),status='APPROVED',signature='signature')
    manager = SimpleNamespace(list_certification_candidates=lambda **_:[entry])
    return row, entry, manager, root


def test_missing_source_is_pending_not_unregistered(service):
    _,factory=service
    with factory() as db:
        evidence(db,skill={'behavior':'invocation','name':'sample','basis':'tool_input.skill'})
        row=db.query(AidrSkillUse).one()
        assert certification(db,row,SimpleNamespace(list_certification_candidates=lambda **_:[]))['status']=='pending'
        assert db.query(models.ClientEvent).count()==0


def test_known_path_without_digest_has_specific_pending_reason(service):
    _, factory = service
    with factory() as db:
        evidence(db, skill={'behavior':'file_access', 'path':'/skills/sample/SKILL.md', 'basis':'literal_cat'})
        row = db.query(AidrSkillUse).one()
        result = certification(db, row, None)
        assert result['status'] == 'pending'
        assert result['reason'] == 'content_digest_missing'
        assert result['registered'] is None and result['content_matches'] is None
        assert db.query(models.ClientEvent).count() == 0


@pytest.mark.parametrize('state,expected',[('APPROVED','verified_content'),('PENDING','unapproved'),('REJECTED','unapproved'),('RETIRED','revoked')])
def test_registry_states_and_single_alert(service,tmp_path,monkeypatch,state,expected):
    _,factory=service
    monkeypatch.setattr('backend.aidr_skill_usage.verify_signature',lambda *a:True)
    with factory() as db:
        row,entry,manager,root=setup_certification(db,tmp_path)
        entry.status=state
        assert refresh(db,row,manager)['certification']['status']==expected
        first_alert = db.query(models.ClientEvent).first()
        if first_alert:
            first_alert.last_seen_at = datetime(2020, 1, 1)
            db.flush()
        db.flush(); refresh(db,row,manager); db.flush()
        assert db.query(models.ClientEvent).count()==(expected!='verified_content')
        if first_alert:
            db.refresh(first_alert)
            assert first_alert.last_seen_at == datetime(2020, 1, 1)


def test_content_change_source_ambiguity_and_authorization(service,tmp_path,monkeypatch):
    _,factory=service
    monkeypatch.setattr('backend.aidr_skill_usage.verify_signature',lambda *a:True)
    with factory() as db:
        row,entry,manager,root=setup_certification(db,tmp_path)
        db.add(models.ClientSkillInstall(client_id='one',agent_type='workbuddy',skill_name='sample',skill_path=str(root),version_id='v1'))
        db.add(models.ClientAgent(client_id='one',local_agent_id='workbuddy',agent_type='workbuddy',skills_path=str(root.parent),managed_agent_id='agent'))
        db.add(models.ManagedAgent(agent_id='agent',name='Agent',skill_names_json='[]'));db.flush()
        assert certification(db,row,manager)['status']=='unauthorized'
        agent=db.query(models.ManagedAgent).one(); agent.skill_names_json='["v1"]';db.flush()
        assert certification(db,row,manager)['status']=='verified'
        data=json.loads(row.payload_json);data['skill']['content_digest']='f'*64;row.payload_json=json.dumps(data)
        assert certification(db,row,manager)['status']=='content_changed'
        data['identity_ambiguous']=True;row.payload_json=json.dumps(data)
        assert certification(db,row,manager)['status']=='pending'


def test_query_failure_is_pending_and_rechecked_without_cache(service,tmp_path):
    _,factory=service
    with factory() as db:
        row,entry,manager,root=setup_certification(db,tmp_path)
        def offline(**_): raise OSError('unavailable')
        manager.list_certification_candidates=offline
        assert refresh(db,row,manager)['certification']['reason']=='query_failed'
        manager.list_certification_candidates=lambda **_:[]
        assert refresh(db,row,manager)['certification']['status']=='unregistered'
        db.flush();assert db.query(models.ClientEvent).count()==1


def test_missing_registry_content_and_same_name_are_not_certification(service, tmp_path):
    _, factory = service
    with factory() as db:
        row, entry, manager, root = setup_certification(db, tmp_path)
        entry.skill_path = None
        assert certification(db, row, manager)['reason'] == 'registry_content_unavailable'
        entry.skill_path = str(root)
        other = SimpleNamespace(**vars(entry)); other.skill_id = 'v2'
        manager.list_certification_candidates = lambda **_: [entry, other]
        assert certification(db, row, manager)['reason'] == 'identity_ambiguous'


def test_real_signature_and_revocation_recheck(service, tmp_path, monkeypatch):
    from agent_manager.core.signer import compute_signature
    monkeypatch.setenv('AGENT_MANAGER_DATA_DIR', str(tmp_path/'keys'))
    _, factory = service
    with factory() as db:
        row, entry, manager, root = setup_certification(db, tmp_path)
        entry.signature = compute_signature(root)
        assert refresh(db, row, manager)['certification']['status'] == 'verified_content'
        entry.status = 'RETIRED'
        assert refresh(db, row, manager)['certification']['status'] == 'revoked'
        db.flush()
        assert db.query(models.ClientEvent).count() == 1
        entry.status = 'APPROVED'
        refresh(db, row, manager); db.flush()
        assert json.loads(db.query(models.ClientEvent).one().details_json)['active'] is False


def test_failed_read_and_search_without_skill_evidence(service):
    _, factory = service
    with factory() as db:
        evidence(db, skill={'behavior':'file_access','path':'/tmp/missing/SKILL.md','basis':'literal_cat'})
        evidence(db,'tool.failure',status='reported_error')
        evidence(db,call='search')
        rows = db.query(AidrSkillUse).all()
        assert len(rows) == 1 and json.loads(rows[0].payload_json)['stage'] == 'failed'


def test_codex_turns_and_missing_scope_do_not_join():
    from backend.aidr_skill_usage import identity
    event = {'agent':'codex','session_id':'s','native_call_id':'c','user_scope':'501'}
    assert identity('one',{**event,'turn_id':'t1'},'log',1) != identity('one',{**event,'turn_id':'t2'},'log',2)
    assert identity('one',event,'log',1) != identity('one',event,'hook',1)


def test_metadata_contract_rejects_wrong_host_and_unredacted_fields():
    from backend.aidr_skill_contract import SkillUse
    skill = SkillUse(behavior='invocation', name='sample', basis='tool_input.skill')
    skill.validate_source('workbuddy','Skill','tool_call')
    with pytest.raises(ValueError): skill.validate_source('cursor','Skill','tool_call')
    skill.name = 'api_key=EXAMPLE_SECRET_VALUE'
    with pytest.raises(ValueError): skill.validate_source('workbuddy','Skill','tool_call')


def test_fresh_filter_and_device_scope(service, tmp_path, monkeypatch):
    client, factory = service
    with factory() as db:
        row,entry,manager,root = setup_certification(db,tmp_path)
        db.commit()
    manager.list_certification_candidates = lambda **_: []
    monkeypatch.setattr('backend.aidr_skill_usage.registry_manager',lambda:manager)
    response=client.get('/api/v1/clients/one/aidr/skill-uses',params={'agent':'workbuddy','session_id':'session','certification':'unregistered'})
    assert response.status_code == 200, response.text
    assert len(response.json()['items']) == 1
    denied=client.get('/api/v1/clients/two/aidr/skill-uses',params={'agent':'workbuddy','session_id':'session'})
    assert denied.status_code in {403,404}


def test_empty_and_incomplete_evidence_skip_registry(service, monkeypatch):
    client, factory = service
    def unexpected_registry():
        pytest.fail('Incomplete evidence must not load the registry')
    monkeypatch.setattr('agent_manager.api.router.get_manager', unexpected_registry)
    url = '/api/v1/clients/one/aidr/skill-uses'
    params = {'agent': 'workbuddy', 'session_id': 'session'}
    assert client.get(url, params=params).json()['items'] == []
    with factory() as db:
        evidence(db, skill={'behavior': 'file_access', 'path': '/skills/sample/SKILL.md', 'basis': 'literal_cat'})
        db.commit()
    response = client.get(url, params=params)
    assert response.status_code == 200
    assert response.json()['items'][0]['certification']['reason'] == 'content_digest_missing'


def test_registry_candidates_reused_only_within_request(monkeypatch):
    from backend.aidr_skill_usage import registry_manager
    queries = []
    state = 'APPROVED'
    def candidates(**filters):
        queries.append(filters)
        return [SimpleNamespace(status=state)]
    registry = SimpleNamespace(list_certification_candidates=candidates)
    monkeypatch.setattr('agent_manager.api.router.get_manager', lambda: SimpleNamespace(registry=registry))
    first = registry_manager()
    assert queries == []
    assert first.list_certification_candidates(name='sample')[0].status == 'APPROVED'
    first.list_certification_candidates(name='sample')
    assert len(queries) == 1
    state = 'RETIRED'
    assert registry_manager().list_certification_candidates(name='sample')[0].status == 'RETIRED'
    assert len(queries) == 2


def test_candidate_query_uses_deployment_before_name(service, tmp_path):
    _, factory = service
    with factory() as db:
        row, entry, manager, root = setup_certification(db, tmp_path)
        data = json.loads(row.payload_json)
        data['skill']['name'] = 'sample'
        row.payload_json = json.dumps(data)
        queries = []
        def candidates(**filters):
            queries.append(filters)
            return []
        manager.list_certification_candidates = candidates
        assert certification(db, row, manager)['status'] == 'unregistered'
        assert queries[-1] == {'skill_id': None, 'name': 'sample'}
        db.add(models.ClientSkillInstall(client_id='one', agent_type='workbuddy', skill_name='sample', skill_path=str(root), version_id='v1'))
        db.flush()
        assert certification(db, row, manager)['reason'] == 'registry_reference_missing'
        assert queries[-1] == {'skill_id': 'v1', 'name': None}
