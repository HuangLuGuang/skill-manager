from .contract import Adapter

ADAPTERS = (Adapter('codebuddy', model_source='codebuddy.message.extra',
                    skill_input=('Skill', 'tool_input.command'),
                    skill_result='result.base_directory', inventory_type='codebuddy'),)
