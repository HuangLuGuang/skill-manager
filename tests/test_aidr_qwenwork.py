from backend import aidr_adapters, client_discovery
from backend.aidr_products import PRODUCTS, validate_hook, validate_log
from backend.aidr_command_rules import observe
from backend.aidr_hook_control import evaluate


def test_qwenwork_scope_and_native_command():
    assert validate_hook('qwenwork') == validate_log('qwenwork') == 'qwenwork'
    product = next(p for p in PRODUCTS if p['id'] == 'qwenwork')
    assert product['os'] == ['darwin'] and product['approval'] and not product['managed']
    adapter = aidr_adapters.get('qwenwork')
    assert adapter.resolve_hook_turn and not adapter.turn_required
    assert adapter.skill_input == ('Skill', 'tool_input.skill')
    definition = next(a for a in client_discovery.defaults() if a['agent_type'] == 'qwenwork')
    assert definition['systems'] == ['darwin']
    assert '.qwenworkcn/identity-data/v1/*/skills' in definition['skill_roots']
    policy = dict(revision='1', default_action='allow', rules=[dict(id='review', agent='qwenwork', tool='*', decision='ask', command={'executable':'touch'})])
    tool = 'mcp__qw-builtin__mcp_workspace_bash'
    observation = observe(policy, 'qwenwork', tool, 'touch probe', '/tmp')
    assert evaluate(policy, 'qwenwork', tool, observation)['decision'] == 'ask'
