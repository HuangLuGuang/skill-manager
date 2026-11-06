"""Shared literal matching vectors, risk/preview parity and receiver upgrade gate."""
import json
from pathlib import Path

import pytest

from backend.aidr_command_rules import CommandCondition, command_match
from backend.aidr_rule_preview import HookRulePreview, preview_hook
from backend.aidr_security_rules import clean_document, control_rules
from backend import aidr_risk as risk
from tests.test_aidr_hook_control import control, base_control, service
from tests.test_aidr_security_rules import unified, unified_payload, GLOBAL

VECTORS = json.loads((Path(__file__).parents[1] / 'scanner/internal/aidr/hooks/testdata/command_keywords.json').read_text())


@pytest.mark.parametrize('case', VECTORS)
def test_shared_keyword_vectors(case):
    condition = CommandCondition(keywords=case['keywords']).model_dump(exclude_none=True)
    assert command_match(condition, case['command']) == case['want']


@pytest.mark.parametrize('terms', [[], [''], ['   '], ['x\ny'], ['密' * 86], ['x'] * 17])
def test_keyword_bounds(terms):
    with pytest.raises(ValueError):
        CommandCondition(keywords={'terms': terms})


@pytest.mark.parametrize('extra', [{'executable': 'rm'}, {'args_all': ['-f']}, {'args_any': ['-r']}, {'path_prefix': '/tmp'}, {'pipe_to': ['sh']}])
def test_keyword_condition_has_one_matching_semantic(extra):
    with pytest.raises(ValueError):
        CommandCondition(keywords={'terms': ['rm']}, **extra)


def test_legacy_condition_retains_wire_shape():
    value = CommandCondition(executable='rm').model_dump(exclude_none=True)
    assert value == dict(executable='rm', args_all=[], args_any=[], path_prefix='', pipe_to=[])


@pytest.mark.parametrize('example', json.loads((Path(__file__).parents[1] / 'web/src/utils/securityRuleExamples.json').read_text()))
def test_editor_examples_match_their_published_conditions(example):
    if not example.get('command'):
        return
    condition = CommandCondition(networks=example['networks']) if example.get('networks') else CommandCondition(keywords=example['keywords']) if example.get('keywords') else CommandCondition(executable=example['executable'], args_all=example.get('args_all', []))
    value = condition.model_dump(exclude_none=True)
    assert command_match(value, example['command']) == 'matched'
    assert command_match(value, example['miss']) == 'unmatched'


@pytest.mark.parametrize('platform', ['linux', 'darwin', 'windows'])
def test_keyword_draft_preview_and_risk_use_literal_command_only(platform):
    condition = {'keywords': {'terms': ['test.txt', '删除'], 'mode': 'any', 'ignore_case': True}}
    row = dict(id='keyword', name='keyword', kind='command', severity='medium', action='deny', condition=condition)
    document = clean_document({'rules': [row], 'path_sets': []})
    command = 'powershell.exe -Command "Remove-Item TEST.TXT"'
    result = preview_hook(HookRulePreview(command=command, agent='qoder-hooks', tool='Bash', policy=dict(expected_revision='0', default_action='allow', rules=control_rules(document))))
    assert result['decision'] == 'deny'
    assert result['keyword_matches'][0]['terms'] == ['test.txt']
    config = risk.DetectionConfig(enabled=True, security=document).model_dump() | {'platform': platform}
    assert risk.command_assessment(command, '', config, platform)['status'] == 'matched'
    legacy = risk.DetectionConfig(enabled=True, command_rules=[], custom_commands=[dict(id='custom_keyword', name='Keyword', enabled=True, platforms=[platform], severity='medium', condition=condition)]).model_dump()
    assert risk.command_assessment(command, '', legacy, platform)['status'] == 'matched'
    event = {'kind': 'tool.pre', 'agent': 'qoder-hooks', 'tool': 'Bash', 'behavior': {'actions': [{'category': 'command', 'command': command}]}}
    assert len(risk.detect_matches(event, config, windows=platform == 'windows')) == 1
    event['tool'] = 'Read'
    assert risk.detect_matches(event, config, windows=platform == 'windows') == []
    event['tool'] = 'Bash'; event['behavior']['actions'] = [{'category': 'file_write', 'command': command}]
    assert risk.detect_matches(event, config, windows=platform == 'windows') == []


def test_keyword_policy_requires_capable_receiver(control):
    from backend.aidr_hook_runtime import HookRuntimeRow
    client, factory, _ = control
    body = dict(expected_revision='0', default_action='allow', rules=[dict(id='keyword', agent='*', tool='*', decision='deny', command={'keywords': {'terms': ['test.txt']}})])
    with factory() as db:
        report = db.query(HookRuntimeRow).one()
        report.payload = json.dumps({**json.loads(report.payload), 'command_rules_schema': 1})
        db.commit()
    response = client.put('/api/v1/clients/one/aidr/hook-policy', json=body)
    assert response.status_code == 409 and response.json()['error_code'] == 'aidr.hook_command_keywords_upgrade_required'
    with factory() as db:
        report = db.query(HookRuntimeRow).one()
        report.payload = json.dumps({**json.loads(report.payload), 'command_keywords_schema': 1})
        db.commit()
    response = client.put('/api/v1/clients/one/aidr/hook-policy', json=body)
    assert response.status_code == 200, response.text


def test_keyword_rule_saves_and_reloads_without_losing_conditions(unified):
    client, _ = unified
    body = unified_payload(client.get(GLOBAL).json())
    condition = {'keywords': {'terms': ['test.txt', '删除'], 'mode': 'all', 'ignore_case': True}}
    body['document'] = {'rules': [dict(id='keyword', name='Keyword rule', kind='command', condition=condition, severity='medium', action='deny')], 'path_sets': []}
    response = client.put(GLOBAL, json=body)
    assert response.status_code == 200, response.text
    saved = client.get(GLOBAL).json()
    assert saved['rules'][0]['condition']['keywords'] == condition['keywords']
    assert saved['control']['policy']['rules'][0]['command']['keywords'] == condition['keywords']
