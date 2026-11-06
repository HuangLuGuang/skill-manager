import json
import time

import pytest

from backend import aidr_rule_execution as execution, models
from backend.aidr_hooks import HookEvent
from backend.aidr_hook_queries import present
from backend.aidr_hook_control import HookAttemptReportRow
from backend.aidr_models import AidrHookEvent
from tests.test_aidr_hook_control import control, base_control, service
from tests.test_aidr_security_rules import unified, CLIENT
from tests.test_aidr_hook_queries import insert
from tests.test_aidr_hooks import hook_batch


@pytest.mark.parametrize('modes,age,ready,want', [
    (['audit'], 0, True, 'audit'), (['plugin_pre_tool'], 0, True, 'ready'),
    (['plugin_pre_tool'], 0, False, 'pending'), (['audit', 'plugin_pre_tool'], 0, True, 'mixed'),
    (['plugin_pre_tool'], 91, True, 'unknown'), ([], 0, True, 'unknown'),
])
def test_execution_uses_fresh_receiver_evidence(monkeypatch, modes, age, ready, want):
    monkeypatch.setattr(execution, 'policy_view', lambda *_: {
        'runtime_governance': {'enabled': True, 'channels': {'hooks': True}, 'modes': {'hooks': 'intercept'}},
        'runtime_governance_configured': True, 'runtime_governance_source': 'client'})
    reports = [{'received_at': str(int(time.time()) - age), 'control_mode': mode,
                'control_code': 'aidr_hook_policy_ready', 'matches_published_revision': ready} for mode in modes]
    result = execution.view(None, 'one', {'runtime': {'items': reports}})
    assert result['state'] == want
    assert result['source'] == 'client' and result['target_mode'] == 'intercept'


def test_preview_separates_deny_match_from_device_audit_mode(unified):
    client, factory = unified
    with factory() as db:
        from backend.client_governance import default_runtime_governance
        for scope, mode in [('@default', 'intercept'), ('one', 'audit')]:
            row = db.get(models.ClientGovernancePolicy, scope)
            if row is None:
                row = models.ClientGovernancePolicy(scope=scope)
                db.add(row)
            row.runtime_governance_json = json.dumps(default_runtime_governance() | {'enabled': True, 'modes': {'hooks': mode, 'system': 'audit'}})
        db.commit()
    view = client.get(CLIENT).json()
    assert view['execution']['source'] == 'client'
    assert view['execution']['target_mode'] == 'audit'
    assert view['execution']['state'] == 'audit'
    body = {'document': {'rules': [{'id': 'delete', 'name': 'Delete', 'kind': 'command',
        'condition': {'executable': 'rm'}, 'action': 'deny'}], 'path_sets': []},
        'command': 'rm ./fixture', 'cwd': '', 'platform': 'windows', 'agent': 'qoder-hooks',
        'tool': 'Bash', 'enabled': True, 'default_action': 'allow'}
    response = client.post(CLIENT + '/preview', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['control']['decision'] == 'deny'
    assert result['execution']['state'] == 'audit'


def test_hook_mode_contract_keeps_legacy_unknown_and_checks_scope():
    event = hook_batch()['records'][0]['event']
    assert HookEvent.model_validate(event).control_mode is None
    with pytest.raises(ValueError):
        HookEvent.model_validate({**event, 'control_mode': 'audit'})
    pre = {**event, 'agent': 'qoder-hooks', 'kind': 'tool.pre', 'hook_event': 'PreToolUse',
           'tool': 'Bash', 'native_call_id': 'call', 'input_digest': 'b'*64,
           'behavior': {'version': 3, 'policy': event['policy'], 'body_omitted': False,
               'category': 'command', 'method': 'direct_fields', 'actions': [], 'status': 'unknown',
               'result_basis': [], 'redacted': False, 'truncated': False, 'uncertainty': []}}
    assert HookEvent.model_validate({**pre, 'control_mode': 'audit'}).control_mode == 'audit'
    with pytest.raises(ValueError):
        HookEvent.model_validate({**pre, 'control_mode': 'audit', 'control_decision': {
            'decision': 'deny', 'code': 'aidr_hook_rule_deny', 'matched_rule_ids': []}})


def test_approval_receipt_is_projected_for_exact_call(unified):
    client, factory = unified
    row_id = insert(factory, 909, event={'kind': 'tool.pre', 'hook_event': 'PreToolUse',
        'control_decision': {'decision': 'ask'}, 'control_mode': 'plugin_pre_tool'})
    with factory() as db:
        row = db.get(AidrHookEvent, row_id)
        db.add(HookAttemptReportRow(client_id='one', stream_id=row.stream_id, event_id=row.event_id,
            digest='a'*64, received_at=int(time.time()), payload=json.dumps({
                'state': 'denied', 'code': 'aidr_hook_approval_timeout'})))
        db.commit()
        item = present(row, db)
        assert item['control_result'] == {'state': 'denied', 'code': 'aidr_hook_approval_timeout', 'source': 'client_report'}
        old = insert(factory, 910, event={'kind': 'tool.pre', 'hook_event': 'PreToolUse'})
        assert 'control_result' not in present(db.get(AidrHookEvent, old), db)
