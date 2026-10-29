from .contract import Adapter

ADAPTERS = (Adapter('qwenwork', resolve_hook_turn=True,
                    model_source='qwenwork.message.model',
                    skill_input=('Skill', 'tool_input.skill'),
                    inventory_type='qwenwork'),)
