"""Platform and receiver share the same IP-literal/CIDR contract."""
import json
from pathlib import Path

import pytest

from backend.aidr_command_rules import CommandCondition, command_match
from backend.aidr_command_networks import network_hits
from backend.aidr_rule_preview import HookRulePreview, preview_hook
from backend.aidr_security_rules import clean_document, control_rules
from backend import aidr_risk as risk
from tests.test_aidr_hook_control import control, base_control, service
from tests.test_aidr_security_rules import unified, unified_payload, GLOBAL

VECTORS = json.loads((Path(__file__).parents[1] / 'scanner/internal/aidr/hooks/testdata/command_networks.json').read_text())


@pytest.mark.parametrize('case', VECTORS)
def test_shared_network_vectors(case):
    condition = CommandCondition(networks=case['networks']).model_dump(exclude_none=True)
    assert command_match(condition, case['command']) == case['want']


@pytest.mark.parametrize('subnets', [[], [''], ['10.0.0.0'], ['10.0.0.0/33'], ['::/129'], ['host/24'], ['10.0.0.0/024'], ['::/032'], [' 10.0.0.0/8'], ['::1%eth0/128'], ['010.0.0.0/8'], ['10.0.0.0/255.0.0.0'], ['::/0'] * 17])
def test_network_bounds(subnets):
    with pytest.raises(ValueError):
        CommandCondition(networks={'subnets': subnets})


@pytest.mark.parametrize('extra', [{'keywords': {'terms': ['IP']}}, {'executable': 'curl'}, {'args_all': ['-f']}, {'args_any': ['-r']}, {'path_prefix': '/tmp'}, {'pipe_to': ['sh']}])
def test_network_condition_is_independent(extra):
    with pytest.raises(ValueError):
        CommandCondition(networks={'subnets': ['::/0']}, **extra)


def test_network_size_and_evidence():
    condition = {'networks': {'subnets': ['10.0.0.0/8', '2001:db8::/32']}}
    assert command_match(condition, 'x' * 32769) == 'unresolved'
    assert network_hits(condition['networks'], 'ping 10.1.2.3; ping 10.1.2.3; ping 2001:DB8::1') == [
        {'ip': '10.1.2.3', 'subnet': '10.0.0.0/8'}, {'ip': '2001:db8::1', 'subnet': '2001:db8::/32'}]


@pytest.mark.parametrize('platform', ['linux', 'darwin', 'windows'])
@pytest.mark.parametrize('address', ['10.10.71.23', '[2001:db8::23]'])
def test_network_draft_preview_and_risk(platform, address):
    condition = {'networks': {'subnets': ['10.10.71.0/24', '2001:db8::/32']}}
    document = clean_document({'rules': [dict(id='network', name='Subnet rule', kind='command', condition=condition, severity='medium', action='deny')], 'path_sets': []})
    command = f'powershell.exe -Command "curl http://{address}"'
    policy = dict(expected_revision='0', default_action='allow', rules=control_rules(document))
    result = preview_hook(HookRulePreview(policy=policy, agent='qoder-hooks', tool='Bash', command=command))
    assert result['decision'] == 'deny'
    assert result['network_matches'][0]['addresses'][0]['ip'] == address.strip('[]')
    config = risk.DetectionConfig(enabled=True, security=document).model_dump() | {'platform': platform}
    assert risk.command_assessment(command, '', config, platform)['status'] == 'matched'
    legacy = risk.DetectionConfig(enabled=True, command_rules=[], custom_commands=[dict(id='custom_network', name='Network', enabled=True, platforms=[platform], severity='medium', condition=condition)]).model_dump()
    assert risk.command_assessment(command, '', legacy, platform)['status'] == 'matched'
    event = {'kind': 'tool.pre', 'agent': 'qoder-hooks', 'tool': 'Bash', 'behavior': {'actions': [{'category': 'command', 'command': command}]}}
    assert len(risk.detect_matches(event, config, windows=platform == 'windows')) == 1
    event['tool'] = 'Read'
    assert risk.detect_matches(event, config, windows=platform == 'windows') == []


def test_network_policy_requires_capable_receiver(control):
    from backend.aidr_hook_runtime import HookRuntimeRow
    client, factory, _ = control
    body = dict(expected_revision='0', default_action='allow', rules=[dict(id='network', agent='*', tool='*', decision='deny', command={'networks': {'subnets': ['10.0.0.0/8']}})])
    with factory() as db:
        report = db.query(HookRuntimeRow).one()
        report.payload = json.dumps({**json.loads(report.payload), 'command_rules_schema': 1})
        db.commit()
    response = client.put('/api/v1/clients/one/aidr/hook-policy', json=body)
    assert response.status_code == 409 and response.json()['error_code'] == 'aidr.hook_command_networks_upgrade_required'
    with factory() as db:
        report = db.query(HookRuntimeRow).one()
        report.payload = json.dumps({**json.loads(report.payload), 'command_networks_schema': 1})
        db.commit()
    assert client.put('/api/v1/clients/one/aidr/hook-policy', json=body).status_code == 200


def test_network_rule_round_trip(unified):
    client, _ = unified
    body = unified_payload(client.get(GLOBAL).json())
    condition = {'networks': {'subnets': ['10.10.71.0/24', '2001:db8::/32']}}
    body['document'] = {'rules': [dict(id='network', name='Subnet', kind='command', condition=condition, severity='medium', action='deny')], 'path_sets': []}
    response = client.put(GLOBAL, json=body)
    assert response.status_code == 200, response.text
    saved = client.get(GLOBAL).json()
    assert saved['rules'][0]['condition']['networks'] == condition['networks']
    assert saved['control']['policy']['rules'][0]['command']['networks'] == condition['networks']
