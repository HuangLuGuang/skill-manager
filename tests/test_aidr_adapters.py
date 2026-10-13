from backend import aidr_adapters
from backend.aidr_products import PRODUCTS, validate_hook, validate_log


def test_enabled_products_have_independent_semantics():
    for product in PRODUCTS:
        if product['logs'] or product['hooks']:
            assert product['id'] in aidr_adapters.ADAPTERS
    assert aidr_adapters.get('codex').turn_required
    assert aidr_adapters.get('claude').session_call_identity
    assert aidr_adapters.get('qoder-hooks').log_entry == 'qoder-cli'
    assert aidr_adapters.get('qoder-cli').session_entry == 'qoder-hooks'
    assert aidr_adapters.get('teleagent').model_source == 'teleagent.message'


def test_teleagent_capabilities_do_not_claim_managed_approval():
    assert validate_log('teleagent') == validate_hook('teleagent') == 'teleagent'
    product = next(p for p in PRODUCTS if p['id'] == 'teleagent')
    assert product['block']
    assert not product['managed']
    assert not product['approval']
