"""TRAE native Skill fields validated against the ingestion contract."""
import json
from pathlib import Path

import pytest

from backend.aidr_skill_contract import SkillUse
from tests.test_aidr_api import service, batch, submit
from tests.test_aidr_hooks import send
from backend.aidr_contract import Event
from tests.test_aidr_content import configure


def test_native_trae_wire_ingestion(service):
    # Real Go adapter output from the isolated 3.6.4 probe, with paths sanitized.
    fixture = json.loads((Path(__file__).parent / 'fixtures/trae-3.6.4-wire.json').read_text())
    client, factory = service
    configure(factory, capture={'prompt': True, 'tool_output': True, 'file_body': False, 'command_body': True})
    response = client.post('/api/v1/clients/one/aidr/audit-policy',
        json={'stream_id': fixture['hooks']['stream_id'], 'last_sequence': '0'},
        headers={'authorization': 'Bearer test-one', 'X-AIDR-Policy-Schema': '2', 'X-AIDR-Content-Options': '1'})
    assert response.status_code == 200, response.text
    policy = response.json()
    for record in fixture['hooks']['records']:
        event = record['event']
        event['policy'] = policy
        if 'behavior' in event:
            event['behavior']['policy'] = policy
    response = send(client, fixture['hooks'])
    assert response.status_code == 200, response.text
    assert response.json()['durable'] is True
    assert send(client, fixture['hooks']).status_code == 200
    for event in fixture['logs']:
        Event.model_validate(event)
    logs = {'schema_version': 1, 'records': [
        {'sequence': str(i), 'kind': 'event', 'record_id': event['logical_event_id'], 'payload': event}
        for i, event in enumerate(fixture['logs'], 1)]}
    response = submit(client, logs)
    assert response.status_code == 200, response.text
    assert response.json()['durable'] is True
    assert submit(client, logs).status_code == 200
    rows = client.get('/api/v1/clients/one/aidr/events', params={'agent': 'trae'}).json()['items']
    assert len(rows) == len(fixture['logs'])
    decisions = [r['event'].get('control_decision', {}) for r in fixture['hooks']['records']]
    assert any(d.get('decision') == 'deny' and d.get('rule_id') == 'deny-marker' for d in decisions)
    assert any(d.get('unresolved') for d in decisions)


def test_trae_command_rules_match_and_report_unresolved():
    from backend.aidr_command_rules import observe
    policy = {'revision': '1', 'rules': [{'id': 'deny', 'agent': 'trae', 'tool': 'RunCommand',
               'decision': 'deny', 'command': {'executable': 'printf', 'args_all': ['denied']}}]}
    assert observe(policy, 'trae', 'RunCommand', 'printf denied')['matched'] == ['deny']
    assert observe(policy, 'trae', 'RunCommand', 'printf denied > marker')['unresolved'] == ['deny']


@pytest.mark.parametrize('agent', ['trae', 'trae-cn'])
@pytest.mark.parametrize('kind,skill', [
    ('tool_call', {'behavior': 'invocation', 'name': 'aidr-probe', 'basis': 'tool_input.name'}),
    ('tool_result', {'behavior': 'invocation', 'path': '/test/.trae/skills/aidr-probe/SKILL.md',
                     'basis': 'result.metadata', 'phase': 'host_loaded'}),
])
def test_trae_skill_ingestion_and_replay(service, agent, kind, skill):
    client, _ = service
    SkillUse.model_validate(skill).validate_source(agent, 'Skill', kind)
    value = batch()
    event = value['records'][0]['payload']
    event.update(agent=agent, tool='Skill', kind=kind, skill_use=skill)
    response = submit(client, value)
    assert response.status_code == 200, response.text
    assert submit(client, value).status_code == 200


def test_trae_skill_input_does_not_infer_another_host_field():
    with pytest.raises(ValueError, match='skill_invocation_source_invalid'):
        SkillUse(behavior='invocation', name='sample', basis='tool_input.skill').validate_source('trae', 'Skill', 'tool.pre')
