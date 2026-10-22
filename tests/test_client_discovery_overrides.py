from tests.test_clients_api import _client


URL = '/api/v1/clients/discovery-config'


def register(client, name):
    token = client.post('/api/v1/access/tokens', json={'name': name, 'token_type': 'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    response = client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': name, 'name': name, 'hostname': name,
        'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'agents': [],
    })
    assert response.status_code == 200, response.text
    return headers


def save(client, agents, client_id=None, version=None):
    params = {'client_id': client_id} if client_id else {}
    current = client.get(URL, params=params).json()
    response = client.put(URL, params=params, json={
        'expected_version': version or current.get('edit_version', current['version']), 'agents': agents,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_discovery_overrides_sync_only_effective_changes_and_restore(tmp_path):
    client = _client(tmp_path)
    one = register(client, 'one')
    two = register(client, 'two')
    global_agents = client.get(URL).json()['agents']
    codex = next(agent for agent in global_agents if agent['agent_type'] == 'codex')
    local = {**codex, 'enabled': False, 'skill_roots': ['/custom/skills']}
    saved = save(client, [local], 'one')
    assert saved['overrides'] == [local]
    assert next(a for a in saved['agents'] if a['agent_type'] == 'claude-code') == next(a for a in global_agents if a['agent_type'] == 'claude-code')
    def tasks(name, headers):
        return [t for t in client.get(f'/api/v1/clients/{name}/tasks', headers=headers).json() if 'agent_discovery_version' in t['payload']]
    assert len(tasks('one', one)) == 1
    assert not tasks('two', two)
    for agent in global_agents:
        if agent['agent_type'] == 'codex':
            agent['skill_roots'] = ['/global/new']
    latest_global = save(client, global_agents)
    assert len(tasks('one', one)) == 1
    assert len(tasks('two', two)) == 1
    policy = client.get('/api/v1/clients/one/policy', headers=one).json()['agent_discovery']
    assert policy == {'version': saved['version'], 'agents': saved['agents']}
    restored = save(client, [], 'one')
    assert restored['agents'] == latest_global['agents']
    assert restored['version'] == latest_global['version']
    assert len(tasks('one', one)) == 2
    heartbeat = client.post('/api/v1/clients/one/heartbeat', headers=one, json={'client_id': 'one'})
    assert heartbeat.json()['policy']['agent_discovery'] == latest_global
    save(client, [], 'one')
    assert len(tasks('one', one)) == 2


def test_client_only_agent_validation_and_conflicts(tmp_path):
    client = _client(tmp_path)
    register(client, 'one')
    current = client.get(URL, params={'client_id': 'one'}).json()
    agent = {'agent_type': 'company', 'name': 'Company', 'enabled': True, 'systems': ['linux'], 'skill_roots': ['/company/skills']}
    saved = save(client, [agent], 'one')
    assert agent in saved['agents']
    assert agent not in client.get(URL).json()['agents']
    assert client.put(URL, params={'client_id': 'one'}, json={'expected_version': current['edit_version'], 'agents': []}).status_code == 409
    for definitions in [[agent, agent], [{**agent, 'skill_roots': ['../escape']}], [{**agent, 'systems': []}]]:
        assert client.put(URL, params={'client_id': 'one'}, json={'expected_version': saved['edit_version'], 'agents': definitions}).status_code == 422
    global_agents = client.get(URL).json()['agents']
    global_agents[0]['name'] = 'New global name'
    save(client, global_agents)
    assert client.put(URL, params={'client_id': 'one'}, json={'expected_version': saved['edit_version'], 'agents': []}).status_code == 409
    assert client.get(URL, params={'client_id': 'missing'}).status_code == 404
    assert client.put(URL, params={'client_id': 'missing'}, json={'expected_version': 'x', 'agents': []}).status_code == 404
    assert agent not in save(client, [], 'one')['agents']


def test_inheritance_change_with_identical_effective_values_is_versioned(tmp_path):
    client = _client(tmp_path)
    headers = register(client, 'one')
    initial = client.get(URL, params={'client_id': 'one'}).json()
    agent = initial['agents'][0]
    overridden = save(client, [agent], 'one')
    assert overridden['version'] == initial['version']
    assert overridden['edit_version'] != initial['edit_version']
    assert not client.get('/api/v1/clients/one/tasks', headers=headers).json()
    restored = save(client, [], 'one')
    assert restored['edit_version'] == initial['edit_version']
