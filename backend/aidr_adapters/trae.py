from .contract import Adapter

ADAPTERS = tuple(Adapter(name, resolve_hook_turn=True, unassigned_prompt=True,
                        skill_input=('Skill', 'tool_input.name'), skill_result='result.metadata',
                        inventory_type=name) for name in ('trae', 'trae-cn'))
