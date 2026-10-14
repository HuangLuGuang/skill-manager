from .contract import Adapter

ADAPTERS = (Adapter('qoder-cli', family='qoder', session_entry='qoder-hooks', model_source='qoder-cli.message.model', skill_input=('Skill','tool_input.skill'), inventory_type='qoder'), Adapter('qoder-hooks',family='qoder',log_entry='qoder-cli',resolve_hook_turn=True), Adapter('qoder-ide',family='qoder'), Adapter('qoder-work',family='qoder',inventory_type='qoderwork'),)
