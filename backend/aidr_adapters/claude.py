from .contract import Adapter

ADAPTERS = (Adapter('claude', session_call_identity=True, model_source='claude.message.model', skill_input=('Skill','tool_input.skill'), inventory_type='claude-code'),)
