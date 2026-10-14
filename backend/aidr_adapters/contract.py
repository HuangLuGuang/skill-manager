"""Product-owned identity and evidence semantics; no database or policy engine."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Adapter:
    id: str
    family: str = ''
    log_entry: str = ''
    session_entry: str = ''
    turn_required: bool = False
    session_call_identity: bool = False
    resolve_hook_turn: bool = False
    log_turn_links: bool = False
    hook_cwd_from_logs: bool = False
    unassigned_prompt: bool = False
    model_source: str = ''
    skill_input: tuple[str, str] | None = None
    skill_result: str = ''
    inventory_type: str = ''
