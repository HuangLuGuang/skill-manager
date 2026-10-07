"""Product contracts and real backend ingestion; fixtures contain synthetic data."""
import json
import subprocess
from pathlib import Path

import pytest

from backend.aidr_contract import Event
from backend.api_errors import ApiError
from backend.aidr_products import PRODUCTS
from backend.client_governance import RuntimeGovernanceConfig
from backend.aidr_hook_control import ToolRule
from backend.aidr_behavior import Action
from tests.test_aidr_api import service, batch, submit
from tests.test_aidr_hooks import hook_batch, send


def test_generated_catalogs_match():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['python3', str(root/'scripts/sync-aidr-products.py'), '--check'], check=True)
    assert len({p['id'] for p in PRODUCTS}) == len(PRODUCTS)


@pytest.mark.parametrize('agent', ['workbuddy', 'qoder-cli', 'opencode'])
def test_new_log_product_ingestion_session_and_replay(service, agent):
    client, _ = service
    value = batch()
    event = value['records'][0]['payload']
    event['agent'] = agent
    event['session_id'] = 'product-native-session'
    assert Event.model_validate(event).agent == agent
    first = submit(client, value)
    assert first.status_code == 200, first.text
    assert submit(client, value).status_code == 200
    sessions = client.get('/api/v1/clients/one/aidr/sessions', params={'agent': agent}).json()
    assert len(sessions['items']) == 1
    timeline = client.get('/api/v1/clients/one/aidr/session-timeline', params={'agent': agent, 'session_id': 'product-native-session', 'source': 'logs'})
    assert timeline.status_code == 200, timeline.text


@pytest.mark.parametrize('agent,event', [('cursor','sessionStart'), ('workbuddy','SessionStart'), ('qoder-hooks','SessionStart'), ('qoder-work','SessionStart')])
def test_hook_product_protocol_and_ack(service, agent, event):
    client, _ = service
    value = hook_batch()
    value['records'][0]['event'].update(agent=agent, hook_event=event)
    response = send(client,value)
    assert response.status_code == 200 and response.json()['durable'], response.text
    assert send(client,value).status_code == 200
    rows = client.get('/api/v1/clients/one/aidr/hooks',params={'agent':agent}).json()['items']
    assert len(rows) == 1


def test_capabilities_do_not_invent_approval_or_managed_installation():
    assert RuntimeGovernanceConfig(hosts=['cursor','workbuddy','qoder-hooks'],log_sources=['claude','codex','workbuddy','qoder-cli','opencode'])
    for changes in ({'hosts':['traework']}, {'hosts':['cursor'],'access_mode':'managed'}, {'log_sources':['cursor']}, {'log_sources':[]}):
        with pytest.raises((ValueError, ApiError)):
            RuntimeGovernanceConfig(**changes)
    with pytest.raises(ValueError):
        ToolRule(id='test',agent='cursor',tool='Shell',decision='ask')


@pytest.mark.parametrize('tool,category', [('Shell','command'), ('bash','command'), ('read','file_read'), ('write','file_write'), ('edit','file_edit'), ('webfetch','network_request')])
def test_product_tool_semantics_accepted_by_platform(tool, category):
    assert Action(tool=tool,category=category,targets=[],source_fields=[]).category == category


def test_older_clients_do_not_silently_ignore_new_collection_scope():
    from backend.runtime_governance import check_product_policy
    policy = {'runtime_governance_configured': True, 'runtime_governance': {'hosts': ['claude', 'codex']}}
    check_product_policy(policy, 4)
    for target in ({'hosts': ['workbuddy']}, {'hosts': ['claude'], 'log_sources': ['workbuddy']}):
        policy['runtime_governance'] = target
        with pytest.raises(ApiError) as exc:
            check_product_policy(policy, 4)
        assert exc.value.code == 'aidr.runtime_product_upgrade_required'
        check_product_policy(policy, 5)


def test_product_policy_delivery_requires_protocol_five(tmp_path):
    from tests.test_runtime_governance import setup_device, report, heartbeat, save_runtime_policy
    api, headers = setup_device(tmp_path)
    assert heartbeat(api, headers, report() | {'protocol': 4}).status_code == 200
    target = api.get('/api/v1/clients/governance/default').json()['runtime_governance']
    assert save_runtime_policy(api, target | {'log_sources': ['workbuddy']}).status_code == 200
    old = heartbeat(api, headers, report() | {'protocol': 4})
    assert old.status_code == 409 and old.json()['error_code'] == 'aidr.runtime_product_upgrade_required'
    view = api.get('/api/v1/clients/runtime-test/runtime-governance').json()
    assert view['channels']['logs']['health']['state'] == 'product_upgrade_required'
    current = heartbeat(api, headers, report() | {'protocol': 5})
    assert current.status_code == 200, current.text
    assert current.json()['policy']['classification']['runtime_governance']['log_sources'] == ['workbuddy']
