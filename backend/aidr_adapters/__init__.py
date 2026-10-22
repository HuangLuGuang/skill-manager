"""Explicit product registry shared by validation, correlation and presentation."""
from . import claude, codex, cursor, workbuddy, qoder, opencode, teleagent, doubaowork
from .contract import Adapter

ADAPTERS = {a.id: a for module in (claude, codex, cursor, workbuddy, qoder, opencode, teleagent, doubaowork) for a in module.ADAPTERS}

def get(agent):
    return ADAPTERS.get(agent, Adapter(agent))

def validate_model_source(value):
    if not value or value not in {a.model_source for a in ADAPTERS.values()}:
        raise ValueError('model_context_source_invalid')
    return value

def sql_ids(field):
    # Values originate only in the checked-in adapter registry.
    return ','.join("'" + a.id + "'" for a in ADAPTERS.values() if getattr(a, field)) or "NULL"

def log_entry_sql(expression):
    cases = ' '.join("WHEN '" + a.id + "' THEN '" + a.log_entry + "'" for a in ADAPTERS.values() if a.log_entry)
    return f"CASE {expression} {cases} ELSE {expression} END"

def session_entry_sql(expression, requested):
    cases = ' '.join("WHEN '" + a.id + "' THEN '" + a.session_entry + "'" for a in ADAPTERS.values() if a.session_entry and a.id != requested)
    return f"CASE {expression} {cases} ELSE {expression} END" if cases else expression

def family_filter_sql(agent):
    members = [a.id for a in ADAPTERS.values() if a.family == agent and agent]
    return "agent IN (" + ','.join("'" + name + "'" for name in members) + ")" if members else "(:agent = '' OR agent = :agent)"

def session_source_ids(requested, *, logs=False):
    """Raw source IDs that map to the requested session entry or product family."""
    members = {a.id for a in ADAPTERS.values() if a.family == requested} or {requested}
    if not logs:
        return sorted(members)
    def entry(source):
        adapter = get(source)
        return adapter.session_entry if adapter.session_entry and source != requested else source
    return sorted(source for source in members | ADAPTERS.keys() if entry(source) in members)
