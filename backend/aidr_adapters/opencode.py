from .contract import Adapter

ADAPTERS = (Adapter('opencode', model_source='opencode.message', skill_input=('skill','tool_input.name'), skill_result='result.metadata', inventory_type='opencode'),)
