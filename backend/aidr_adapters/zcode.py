from .contract import Adapter

ADAPTERS = (Adapter('zcode', model_source='zcode.message',
                    skill_input=('Skill', 'tool_input.skill'), inventory_type='zcode'),)
