"""Political topic checks share existing category routing and risk treatment."""
import json

import pytest

from backend.prompt_guard import CATEGORIES, PromptGuardConfig, semantic_prompt
from backend.routers import llm_gateway as gateway
from tests.test_prompt_guard_semantic import setup_guard

TOPIC_RULES = ('political_system_discussion', 'political_figure_discussion', 'public_policy_discussion')


def test_topic_defaults_and_disabled_category():
    config = PromptGuardConfig(model_id=7)
    assert all(config.category_config('politics').rule_severities[r] == 'MEDIUM' for r in TOPIC_RULES)
    assert set(TOPIC_RULES) <= set(config.model_rules()[7])
    disabled = PromptGuardConfig(model_id=7, categories={'politics': {'enabled': False}})
    assert not set(TOPIC_RULES) & set(disabled.model_rules()[7])
    prompt = semantic_prompt(['harmful_guidance'])
    assert 'Genuine prohibitions' in prompt and 'rhetorical solicitation' in prompt
    assert "- political_system_discussion:" not in prompt


@pytest.mark.parametrize('rule', TOPIC_RULES)
@pytest.mark.parametrize('severity,action', [('MEDIUM', 'warn'), ('HIGH', 'block'), ('AI', 'warn')])
def test_political_findings_use_configured_risk(tmp_path, monkeypatch, rule, severity, action):
    client, _, _, model = setup_guard(tmp_path, monkeypatch)
    categories = {key: {'enabled': False} for key in CATEGORIES}
    categories['politics'] = {'enabled': True, 'rule_severities': {rule: severity},
                              'disabled_rules': [r for r in TOPIC_RULES if r != rule]}
    assert client.put('/v1/prompt-guard/config', json={'enabled': True, 'model_id': model, 'categories': categories}).status_code == 200
    async def fake(db, selected, payload, **kwargs):
        prompt = payload['messages'][0]['content']
        assert f'- {rule}:' in prompt
        assert all(f'- {other}:' not in prompt for other in TOPIC_RULES if other != rule)
        return {'choices': [{'message': {'content': json.dumps({'findings': [{
            'category': rule, 'severity': 'MEDIUM', 'message_index': 0,
            'evidence': 'policy discussion', 'reason': 'Topic review',
        }]})}}]}
    monkeypatch.setattr(gateway, '_call_upstream', fake)
    data = client.post('/v1/prompt-guard/test', json={'mode': 'block', 'messages': [{'role': 'user', 'content': 'policy discussion'}]}).json()
    assert data['action'] == action and data['llm_status'] == 'completed'
    assert data['findings'][0]['category'] == 'politics'
    assert data['findings'][0]['model_severity'] == 'MEDIUM'
    saved = client.get('/v1/prompt-guard/config').json()
    assert saved['categories']['politics']['rule_severities'][rule] == severity
