import asyncio
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models, schemas
from backend.api_errors import ApiError
from backend.routers import llm_gateway as gateway
from backend.sqlite_db import Base


def configured_provider(**kwargs):
    data = dict(auth_type='raw', custom_headers=[{'name': 'Host', 'value': 'customer.test'}, {'name': 'X-Key', 'value': 'header-secret'}])
    data.update(kwargs)
    gateway._prepare_provider_settings(data)
    return models.ModelProvider(name='test', base_url='http://customer.test:8080/prefix/v1', api_key='key', **data)


def test_storage_edit_and_backward_compatibility():
    provider = configured_provider()
    assert 'header-secret' not in provider.custom_headers_encrypted
    data = {'custom_headers': [{'name': 'HOST', 'value': ''}, {'name': 'X-New', 'value': 'new-secret'}]}
    gateway._prepare_provider_settings(data, provider)
    provider.custom_headers_encrypted = data['custom_headers_encrypted']
    assert gateway._provider_headers(provider) == {'host': 'customer.test', 'x-new': 'new-secret'}
    data = {'name': 'renamed'}
    gateway._prepare_provider_settings(data, provider)
    assert data == {'name': 'renamed'}
    gateway._prepare_provider_settings(data := {'custom_headers': []}, provider)
    assert data['custom_headers_encrypted'] is None
    legacy = models.ModelProvider(base_url='http://example.test/v1', api_key='key')
    assert gateway._upstream_request(legacy, {})[2]['authorization'] == 'Bearer key'


@pytest.mark.parametrize('entries', [
    [{'name': 'X-Key', 'value': 'secret\r\nInjected: value'}],
    [{'name': 'X-Key', 'value': 'secret'}, {'name': 'x-key', 'value': 'other'}],
    [{'name': 'Content-Length', 'value': '123'}],
    [{'name': 'Bad Name', 'value': 'secret'}],
    [{'name': 'X-Key', 'value': ''}],
    [{'name': 'X-Key', 'value': ' secret'}],
])
def test_invalid_headers_do_not_echo_values(entries):
    with pytest.raises(ApiError) as caught:
        gateway._prepare_provider_settings({'custom_headers': entries})
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('protocol', ['openai', 'responses_api', 'anthropic'])
def test_protocol_defaults_and_case_insensitive_override(protocol):
    provider = configured_provider(custom_headers=[{'name': 'AUTHORIZATION', 'value': 'override'}])
    provider.api_format = protocol
    _, _, headers = gateway._upstream_request(provider, {'model': 'm', 'messages': [{'role': 'user', 'content': 'hello'}]})
    assert headers['authorization'] == 'override'
    if protocol == 'anthropic':
        assert headers['x-api-key'] == 'key'
        assert headers['anthropic-version'] == '2023-06-01'


def test_discovery_test_runtime_and_skill_gateway_use_same_headers(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/headers.db')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        provider = configured_provider()
        db.add(provider)
        db.flush()
        provider_id = provider.id
        model = models.ModelEndpoint(provider_id=provider.id, name='test-model', enabled=True)
        db.add(model)
        db.commit()
    seen = []
    def transport(request):
        seen.append(request)
        assert request.headers['authorization'] == 'key'
        assert request.headers['host'] == 'customer.test'
        assert request.headers['x-key'] == 'header-secret'
        if request.method == 'GET':
            return httpx.Response(200, json={'data': [{'id': 'test-model'}]})
        payload = json.loads(request.content)
        if payload.get('stream'):
            return httpx.Response(200, text='data: {"choices":[{"index":0,"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': '{"probes": []}'}}]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw))
    async def exercise():
        with factory() as db:
            model = db.query(models.ModelEndpoint).one()
            await gateway.discover_provider_models(provider_id, db, None)
            result = await gateway.test_model_provider(provider_id, schemas.ModelProviderTestRequest(model='test-model'), db, None)
            assert result['ok']
            await gateway._call_upstream(db, model, {'model': 'test-model', 'messages': []})
    asyncio.run(exercise())
    from agent_manager.core.llm import _call_llm, LLMConfig, generate_sandbox_probes_with_llm
    import backend.sqlite_db
    monkeypatch.setattr(backend.sqlite_db, 'SessionLocal', factory)
    monkeypatch.delenv('AGENT_MANAGER_LLM_GATEWAY_URL', raising=False)
    config = LLMConfig(provider='model-gateway', model='test-model', enabled=True)
    assert _call_llm(config, 'system', 'scan skill')[0] == {'probes': []}
    skill = tmp_path / 'sample-skill'
    skill.mkdir()
    (skill / 'SKILL.md').write_text('# Test skill\nRun main.py to print a greeting.')
    (skill / 'main.py').write_text('print("hello")')
    generate_sandbox_probes_with_llm(skill_path=skill, entrypoint='main.py', config=config)
    assert len(seen) == 5
    assert seen[0].url.path == '/prefix/v1/models'
    assert all(r.url.path == '/prefix/v1/chat/completions' for r in seen[1:])
