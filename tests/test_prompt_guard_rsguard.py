import asyncio
import json

import pytest

from backend import models
from backend.prompt_guard import PromptGuardConfig, RSGUARD_CATEGORIES, parse_rsguard_response
from backend.routers import llm_gateway as gateway
from tests.test_prompt_guard_semantic import setup_guard


@pytest.mark.parametrize('raw,state,categories', [
    ('Safety: Safe\nCategories: None', 'safe', []),
    ('Safety: Unsafe\nCategories: PII', 'unsafe', ['pii']),
    ('Safety: Unsafe\nCategories: Sexual Content or Sexual Acts', 'unsafe', ['sexual']),
    ('Safety: Controversial\nCategories: Jailbreak', 'controversial', ['jailbreak']),
    ('Safety: controverial\nCategories: PII Content; Prompt Injection', 'controversial', ['pii', 'injection']),
    ('Safety: Unsafe\nCategories: Violent, PII, PII Content', 'unsafe', ['violent', 'pii']),
])
def test_parse_native_labels(raw, state, categories):
    result = parse_rsguard_response(raw)
    assert result['safety'] == state and result['categories'] == categories
    assert result['raw_categories'] == raw.split('Categories: ')[1]


@pytest.mark.parametrize('raw', [
    'Safe', 'Safety: Unknown\nCategories: None', 'Safety: Unsafe\nCategories: None',
    'Safety: Safe\nCategories: PII', 'Safety: Unsafe\nCategories: Future Category',
    'Safety: Unsafe\nCategories: PII\nExtra: arbitrary',
])
def test_reject_unknown_or_inconsistent_verdicts(raw):
    with pytest.raises((ValueError, KeyError)):
        parse_rsguard_response(raw)


def setup_rs(tmp_path, monkeypatch):
    client, token, factory, model_id = setup_guard(tmp_path, monkeypatch)
    with factory() as db:
        db.get(models.ModelEndpoint, model_id).guard_adapter = 'rsguard'
        db.commit()
    return client, token, factory, model_id


def reply(raw):
    return {'choices': [{'message': {'content': raw}}], 'usage': {'total_tokens': 5}}


def test_native_request_masking_results_and_category_filter(tmp_path, monkeypatch):
    client, _, factory, model_id = setup_rs(tmp_path, monkeypatch)
    config = {'enabled': True, 'model_id': model_id, 'categories': {'injection': {'enabled': False}}, 'rsguard_disabled_categories': ['pii']}
    assert client.put('/v1/prompt-guard/config', json=config).status_code == 200
    seen = []
    async def fake(db, model, payload, **kwargs):
        assert len(payload['messages']) == 1 and payload['messages'][0]['role'] == 'user'
        assert 'max_tokens' not in payload and kwargs['prompt_guard_review']
        assert 'jane@example.com' not in payload['messages'][0]['content']
        seen.append(payload)
        return reply('Safety: Unsafe\nCategories: PII, Violent')
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    result = client.post('/v1/prompt-guard/test', json={'mode': 'warn', 'messages': [
        {'role': 'user', 'content': 'sample jane@example.com'}, {'role': 'tool', 'content': 'another sample'}]}).json()
    assert result['llm_status'] == 'completed' and result['llm_adapter'] == 'rsguard'
    assert len(seen) == 2 and result['llm_usage']['total_tokens'] == 10
    assert [f['category'] for f in result['findings']] == ['violent', 'violent']
    assert all('snippet' not in f and 'reason' not in f for f in result['findings'])
    assert result['llm_reviews'][0]['verdicts'][0]['raw_categories'] == 'PII, Violent'
    assert client.get('/v1/prompt-guard/config').json()['categories']['injection']['enabled'] is False
    assert len(client.get('/v1/prompt-guard/rsguard-categories').json()) == 10


@pytest.mark.parametrize('state,mode,expected', [('Unsafe','block','block'), ('Controversial','block','warn'), ('Safe','block','pass'), ('Unsafe','log','record'), ('Unsafe','warn','warn')])
def test_native_action_including_untrusted_source(tmp_path, monkeypatch, state, mode, expected):
    client, _, _, _ = setup_rs(tmp_path, monkeypatch)
    async def fake(*args, **kwargs):
        return reply(f'Safety: {state}\nCategories: '+('None' if state=='Safe' else 'Unethical Acts'))
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    result = client.post('/v1/prompt-guard/test', json={'mode': mode, 'messages': [{'role': 'tool', 'content': 'sample'}]}).json()
    assert result['llm_status'] == 'completed' and result['action'] == expected


@pytest.mark.parametrize('mode,action', [('block','error'),('warn','warn'),('log','record')])
def test_malformed_native_output_is_failure(tmp_path, monkeypatch, mode, action):
    client, _, _, _ = setup_rs(tmp_path, monkeypatch)
    async def fake(*args, **kwargs):
        return reply('Safety: Unsafe\nCategories: None')
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    result = client.post('/v1/prompt-guard/test', json={'mode': mode, 'messages': [{'role': 'user', 'content': 'sample'}]}).json()
    assert result['llm_status'] == 'failed' and result['action'] == action
    assert result['llm_error_code'] == 'prompt_guard.invalid_response'


def test_native_disabled_categories_skip_and_switch_preserves_config(tmp_path, monkeypatch):
    client, _, factory, model_id = setup_rs(tmp_path, monkeypatch)
    config = {'enabled': True, 'model_id': model_id, 'rsguard_disabled_categories': list(RSGUARD_CATEGORIES),
              'categories': {'privacy': {'enabled': False}}}
    assert client.put('/v1/prompt-guard/config', json=config).status_code == 200
    result = client.post('/v1/prompt-guard/test', json={'mode':'warn','messages':[{'role':'user','content':'sample'}]}).json()
    assert result['llm_status'] == 'skipped_categories_disabled'
    with factory() as db:
        model = db.get(models.ModelEndpoint, model_id)
        generic = models.ModelEndpoint(provider_id=model.provider_id, name='generic', guard_adapter='generic')
        db.add(generic); db.commit(); generic_id=generic.id
    config['model_id'] = generic_id
    assert client.put('/v1/prompt-guard/config', json=config).status_code == 200
    saved = client.get('/v1/prompt-guard/config').json()
    assert saved['rsguard_disabled_categories'] == list(RSGUARD_CATEGORIES)
    assert saved['categories']['privacy']['enabled'] is False
    config['categories']['privacy']={'enabled':True,'model_id':model_id}
    response = client.put('/v1/prompt-guard/config', json=config)
    assert response.status_code == 422 and response.json()['error_code']=='prompt_guard.category_model_adapter'


def test_native_total_timeout_and_partial_result(tmp_path, monkeypatch):
    client, _, _, model_id = setup_rs(tmp_path, monkeypatch)
    assert client.put('/v1/prompt-guard/config', json={'enabled':True,'model_id':model_id,'timeout_seconds':1}).status_code==200
    calls = []
    async def fake(*args, **kwargs):
        calls.append(kwargs['timeout_seconds'])
        if len(calls)>1:
            await asyncio.sleep(2)
        return reply('Safety: Unsafe\nCategories: Violent')
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    result=client.post('/v1/prompt-guard/test',json={'mode':'block','messages':[{'role':'user','content':'one'},{'role':'user','content':'two'}]}).json()
    assert result['llm_error_code']=='prompt_guard.timeout' and result['action']=='error'
    assert len(result['findings'])==1 and len(calls)==2 and calls[1]<=calls[0]


def test_adapter_crud_and_unknown_values(tmp_path, monkeypatch):
    client, _, _, model_id=setup_rs(tmp_path, monkeypatch)
    client.app.include_router(gateway.admin_router, prefix='/admin')
    assert next(m for m in client.get('/admin/v1/models').json() if m['id']==model_id)['guard_adapter']=='rsguard'
    assert client.put(f'/v1/models/{model_id}',json={'guard_adapter':'unknown'}).status_code==422
    assert client.put(f'/v1/models/{model_id}',json={'guard_adapter':None}).status_code==422
    assert client.put(f'/v1/models/{model_id}',json={'guard_adapter':'generic'}).json()['guard_adapter']=='generic'


def test_native_runtime_audit_retains_original_labels(tmp_path, monkeypatch):
    client, token, factory, _=setup_rs(tmp_path, monkeypatch)
    async def fake(*args, **kwargs):
        return reply('Safety: Unsafe\nCategories: PII')
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    response=client.post('/v1/chat/completions',headers={'Authorization':f'Bearer {token}'},json={'model':'mock-model','messages':[{'role':'user','content':'sample'}]})
    assert response.status_code==403
    with factory() as db:
        result=json.loads(db.query(models.LlmRequestAudit).first().prompt_guard_result_json)
    assert result['llm_adapter']=='rsguard'
    assert result['llm_reviews'][0]['verdicts'][0]['raw_categories']=='PII'
