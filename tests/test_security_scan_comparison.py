import json
from datetime import datetime, timedelta

import pytest

from backend import models
from backend.security_scan_controls import protect_secret
from tests.test_agent_security_p1 import _create_policy, _create_target, p1_api  # noqa: F401

ROOT = '/api/v1/agent-security'


def seed_comparison(client, factory, *, current_risks=('A',), current_inputs=('B', 'A'), current_options=None, error_input=None):
    target, policy = _create_target(client), _create_policy(client)
    with factory() as db:
        for side, inputs, risks in [('baseline', ('A', 'B'), ('A',)), ('current', current_inputs, current_risks)]:
            options = {'datasets': ['dataset-a'], 'num_prompts': 2, 'planned_prompt_count': 2,
                       'techniques': ['Raw'], 'random_seed': 42, 'evaluation_model': 'judge'}
            if side == 'current':
                options.update(current_options or {})
            now = datetime(2026, 9, 8, 1 if side == 'baseline' else 2)
            task = models.SecurityScanTask(task_id=side, target_id=target['target_id'], policy_id=policy['policy_id'],
                scan_kind='llm_redteam_scan', status='succeeded', created_by='admin', idempotency_key=side,
                request_fingerprint=side, created_at=now, completed_at=now + timedelta(minutes=10),
                timeout_at=now + timedelta(hours=1), scan_options_encrypted=protect_secret(json.dumps(options)),
                engine_name='test', engine_version='v1')
            db.add(task)
            db.flush()
            for index, prompt in enumerate(inputs):
                case_id = f'{side}-{index}'
                db.add(models.SecurityScanCase(case_id=case_id, task_id=side, external_case_id=f'aig-llm-prompt:{index}',
                    category='llm_redteam_prompt', title='Test',
                    status='error' if side == 'current' and prompt == error_input else 'failed' if prompt in risks else 'passed',
                    request_summary_json=json.dumps({'prompt_sha256': prompt, 'attack_method': 'Raw', 'vulnerability': 'test'})))
                db.flush()
                if prompt in risks:
                    db.add(models.SecurityFinding(finding_id=f'finding-{case_id}', case_id=case_id, task_id=side,
                        finding_code='llm_redteam.jailbreak_signal', fingerprint='same-risk-code', title='Jailbreak signal',
                        severity='high', description='Test', source='test'))
        db.commit()
    response = client.get(f'{ROOT}/tasks/current/compare/baseline')
    assert response.status_code == 200, response.text
    return response.json()


def test_llm_comparison_matches_prompt_identity_when_report_order_changes(p1_api):
    client, factory, _, _ = p1_api
    result = seed_comparison(client, factory)
    assert result['comparison_status'] == 'complete'
    assert result['summary'] == {'new': 0, 'unchanged': 1, 'resolved': 0, 'unable_to_retest': 0}
    assert result['current_summary']['completed_cases'] == 2


def test_llm_comparison_reports_not_reproduced_only_for_same_evaluated_inputs(p1_api):
    client, factory, _, _ = p1_api
    result = seed_comparison(client, factory, current_risks=())
    assert result['summary']['resolved'] == 1


@pytest.mark.parametrize('kwargs,reason', [
    ({'current_options': {'datasets': ['dataset-b']}}, 'coverage_changed'),
    ({'current_options': {'random_seed': 7}}, 'coverage_changed'),
    ({'current_options': {'techniques': ['BaseEncoding']}}, 'coverage_changed'),
    ({'current_options': {'num_prompts': 3, 'planned_prompt_count': 3}}, 'coverage_incomplete'),
    ({'current_inputs': ('B', 'C')}, 'coverage_changed'),
    ({'current_inputs': ('B',)}, 'coverage_incomplete'),
    ({'error_input': 'A'}, 'coverage_incomplete'),
])
def test_llm_comparison_does_not_infer_resolution_from_changed_or_incomplete_coverage(p1_api, kwargs, reason):
    client, factory, _, _ = p1_api
    result = seed_comparison(client, factory, current_risks=(), **kwargs)
    assert result['comparison_status'] == 'partial'
    assert result['unavailable_reason'] == reason
    assert result['summary']['resolved'] == 0
    assert result['summary']['unable_to_retest'] == 1
