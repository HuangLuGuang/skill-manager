"""Standalone macOS trajectory logs; tool IDs are scoped to their source file."""
from .contract import Adapter

ADAPTERS = (Adapter('doubaowork', session_call_identity=True, log_turn_links=True),)
