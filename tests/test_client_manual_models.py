import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from backend import models
from backend.routers.access_tokens import _hash_token
from backend.sqlite_db import get_db
from tests.test_clients_api import _client


def setup_client(tmp_path, *, export=True):
    client = _client(tmp_path)
    created = client.post('/api/v1/access/tokens', json={
        'name': 'manual', 'token_type': 'client', 'allow_agent_credential_issuance': True,
        'allow_manual_credential_export': export,
    })
    assert created.status_code == 200, created.text
    headers = {'Authorization': f"Bearer {created.json()['token']}"}
    db = next(client.app.dependency_overrides[get_db]())
    provider = models.ModelProvider(name='manual-provider', base_url='https://example.com/v1', enabled=True)
    db.add(provider)
    db.flush()
    db.add(models.ModelEndpoint(provider_id=provider.id, name='team-chat', enabled=True))
    db.commit()
    db.close()
    response = client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'manual-host', 'name': 'Manual host', 'hostname': 'manual-host',
        'os': 'darwin', 'arch': 'arm64', 'client_version': 'test',
        'agents': [{'local_agent_id': 'custom-one', 'agent_type': 'custom', 'install_path': '/opt/agent',
                    'capabilities': {'model_config_auto_apply': False}}],
    })
    assert response.status_code == 200, response.text
    body = {'local_agent_id': 'custom-one', 'agent_type': 'custom', 'model': 'team-chat',
            'source': 'internal', 'protocol': 'openai', 'request_id': str(uuid4())}
    return client, headers, body, created.json()['record']['id']


URL = '/api/v1/clients/manual-host/manual-model/credential'


def test_manual_issue_is_scoped_idempotent_and_preserves_configuration(tmp_path):
    client, headers, body, parent_id = setup_client(tmp_path)
    response = client.post(URL, headers=headers, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert response.headers['cache-control'] == 'no-store'
    repeated = client.post(URL, headers=headers, json=body)
    assert repeated.status_code == 200 and 'token' not in repeated.json()
    db = next(client.app.dependency_overrides[get_db]())
    key = db.get(models.AccessToken, result['credential_id'])
    assert key.token_hash == _hash_token(result['token'])
    assert key.issued_by_client_token_id == parent_id
    assert json.loads(key.scopes_json) == ['model:chat']
    assert json.loads(key.allowed_models_json) == ['team-chat']
    local = db.query(models.ClientAgent).filter_by(local_agent_id='custom-one').one()
    agent = db.query(models.ManagedAgent).filter_by(agent_id=local.managed_agent_id).one()
    assert local.applied_model is None and agent.default_model is None and agent.runtime_token_id is None
    assert db.query(models.ClientTask).filter_by(task_type='manual_model_credential').count() == 1
    assert result['token'] not in '\n'.join(row.payload_json for row in db.query(models.ClientTask))
    assert result['token'] not in '\n'.join(row.details_json for row in db.query(models.ClientEvent))
    db.close()


def test_manual_permission_required_and_checked_again_on_copy(tmp_path):
    client, headers, body, parent_id = setup_client(tmp_path, export=False)
    status_url = '/api/v1/clients/manual-host/status'
    assert client.get(status_url, headers=headers).json()['model_configuration']['can_export_manual_credentials'] is False
    assert client.post(URL, headers=headers, json=body).status_code == 403
    assert client.put(f'/api/v1/access/tokens/{parent_id}', json={'allow_manual_credential_export': True}).status_code == 200
    assert client.get(status_url, headers=headers).json()['model_configuration']['can_export_manual_credentials'] is True
    assert client.post(URL, headers=headers, json=body).status_code == 200
    client.put(f'/api/v1/access/tokens/{parent_id}', json={'allow_manual_credential_export': False})
    assert client.post(URL, headers=headers, json=body).status_code == 403


def test_manual_invalid_target_model_and_route_do_not_issue(tmp_path):
    client, headers, body, _ = setup_client(tmp_path)
    for change, status in [({'local_agent_id': 'other'}, 404), ({'model': 'unknown'}, 403), ({'source': 'external_gateway'}, 409)]:
        assert client.post(URL, headers=headers, json={**body, **change}).status_code == status
    assert client.post(URL.replace('manual-host', 'another-host'), headers=headers, json=body).status_code in {403, 404}
    db = next(client.app.dependency_overrides[get_db]())
    assert db.query(models.AccessToken).filter_by(token_type='agent_runtime').count() == 0
    db.close()


def test_manual_replacement_only_revokes_previous_manual_credential(tmp_path):
    client, headers, body, parent_id = setup_client(tmp_path)
    first = client.post(URL, headers=headers, json=body).json()
    db = next(client.app.dependency_overrides[get_db]())
    automatic = models.AccessToken(name='automatic', token_hash=_hash_token('existing-automatic'), token_prefix='existing',
                                   token_type='agent_runtime', bound_agent_id=first['bound_agent_id'], issued_by_client_token_id=parent_id)
    db.add(automatic)
    db.commit()
    automatic_id = automatic.id
    db.close()
    next_body = {**body, 'request_id': str(uuid4())}
    assert client.post(URL, headers=headers, json=next_body).status_code == 409
    second = client.post(URL, headers=headers, json={**next_body, 'replace_request_id': body['request_id']})
    assert second.status_code == 200, second.text
    db = next(client.app.dependency_overrides[get_db]())
    assert db.get(models.AccessToken, first['credential_id']).status == 'revoked'
    assert db.get(models.AccessToken, automatic_id).status == 'active'
    db.close()
    assert client.post(URL, headers=headers, json=body).status_code == 403


def test_concurrent_manual_requests_issue_once(tmp_path):
    client, headers, body, _ = setup_client(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(URL, headers=headers, json=body), range(2)))
    assert [item.status_code for item in results] == [200, 200]
    assert sum('token' in item.json() for item in results) == 1


def test_export_flag_requires_client_issuance(tmp_path):
    client = _client(tmp_path)
    for token_type in ['client', 'model_gateway']:
        response = client.post('/api/v1/access/tokens', json={'name': 'invalid', 'token_type': token_type, 'allow_manual_credential_export': True})
        assert response.status_code == 400
    (tmp_path / 'valid').mkdir()
    client, headers, body, parent_id = setup_client(tmp_path / 'valid')
    update_url = f'/api/v1/access/tokens/{parent_id}'
    assert client.put(update_url, json={'allow_manual_credential_export': None}).status_code == 400
    response = client.put(update_url, json={'allow_agent_credential_issuance': False})
    assert response.status_code == 200 and response.json()['allow_manual_credential_export'] is False
    assert client.post(URL, headers=headers, json=body).status_code == 403


def test_external_handoff_uses_escrow_without_rotating_key(tmp_path, monkeypatch):
    from backend.routers import clients
    from backend.security_scan_controls import protect_secret
    client, headers, body, parent_id = setup_client(tmp_path)
    db = next(client.app.dependency_overrides[get_db]())
    local = db.query(models.ClientAgent).filter_by(local_agent_id='custom-one').one()
    gateway = models.ExternalAIGateway(name='external', management_base_url='https://admin.example.com',
        model_base_url='https://gateway.example.com/v1', token_id='management', token_value_encrypted=protect_secret('management-secret'))
    db.add(gateway)
    db.flush()
    gateway_id = gateway.id
    db.add(models.ExternalGatewayAgentBinding(gateway_id=gateway_id, managed_agent_id=local.managed_agent_id,
        client_id='manual-host', external_agent_id='external-agent', key_id='external-key',
        api_key_encrypted=protect_secret('external-test-key'), status='active'))
    db.commit()
    db.close()
    original = clients.client_governance.policy_view
    def policy(db, client_id):
        result = original(db, client_id)
        result['model_routing'] = {'external_gateway_enabled': True, 'external_gateway_id': gateway_id, 'client_select_model': True}
        return result
    monkeypatch.setattr(clients.client_governance, 'policy_view', policy)
    monkeypatch.setattr(clients, 'binding_models', lambda *args: [{'id': 'team-chat', 'name': 'Team chat'}])
    body['source'] = 'external_gateway'
    first = client.post(URL, headers=headers, json=body)
    assert first.status_code == 200, first.text
    assert first.json()['token'] == 'external-test-key'
    again = client.post(URL, headers=headers, json={**body, 'request_id': str(uuid4()), 'replace_request_id': body['request_id']})
    assert again.status_code == 200 and again.json()['token'] == 'external-test-key'
    db = next(client.app.dependency_overrides[get_db]())
    assert db.query(models.AccessToken).filter_by(token_type='agent_runtime').count() == 0
    assert db.query(models.ExternalGatewayAgentBinding).one().key_id == 'external-key'
    assert 'external-test-key' not in '\n'.join(row.payload_json for row in db.query(models.ClientTask))
    db.close()
    monkeypatch.setattr(clients, 'binding_models', lambda *args: [])
    assert client.post(URL, headers=headers, json=body).status_code == 403


def test_options_expose_metadata_only_and_parent_revoke_invalidates_key(tmp_path):
    client, headers, body, parent_id = setup_client(tmp_path)
    target = {key: body[key] for key in ('agent_type', 'local_agent_id')}
    options = client.post(URL.replace('credential', 'options'), headers=headers, json=target)
    assert options.status_code == 200 and options.json()['models'][0]['name'] == 'team-chat'
    issued = client.post(URL, headers=headers, json=body).json()
    options = client.post(URL.replace('credential', 'options'), headers=headers, json=target)
    assert options.json()['handoff']['request_id'] == body['request_id']
    assert issued['token'] not in options.text
    client.post(f'/api/v1/access/tokens/{parent_id}/revoke')
    db = next(client.app.dependency_overrides[get_db]())
    assert db.get(models.AccessToken, issued['credential_id']).status == 'revoked'
    db.close()
