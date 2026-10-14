from .contract import Adapter

ADAPTERS = (Adapter('codex', turn_required=True, model_source='codex.turn_context', inventory_type='codex'),)
