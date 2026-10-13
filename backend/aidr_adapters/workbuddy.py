from .contract import Adapter

ADAPTERS = (Adapter('workbuddy', resolve_hook_turn=True, unassigned_prompt=True, model_source='workbuddy.providerData.model', skill_input=('Skill','tool_input.skill'), skill_result='result.base_directory', inventory_type='workbuddy'),)
