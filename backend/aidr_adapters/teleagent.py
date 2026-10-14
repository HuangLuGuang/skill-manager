from .contract import Adapter

ADAPTERS = (Adapter('teleagent', log_turn_links=True, hook_cwd_from_logs=True, resolve_hook_turn=True, session_call_identity=True, model_source='teleagent.message', inventory_type='teleagent'),)
