"""Stable product/entry identities and adapter capabilities, not runtime health.

Qoder's shared settings entry has its own identity: its Hook payload does not
reliably identify CLI versus IDE. Never relabel it using a nearby log timestamp.
Catalog changes are deployed with the backend and generated client catalogs.
"""
import json
from pathlib import Path
from typing import Annotated
from pydantic import AfterValidator

PRODUCTS = json.loads(Path(__file__).with_name('aidr_products.json').read_text())
BY_ID = {p['id']: p for p in PRODUCTS}

def validate_product(value):
    if value not in BY_ID or not (BY_ID[value]['logs'] or BY_ID[value]['hooks']):
        raise ValueError('aidr_product_unsupported')
    return value

AgentID = Annotated[str, AfterValidator(validate_product)]

def validate_log(value):
    if not BY_ID[validate_product(value)]['logs']:
        raise ValueError('aidr_log_agent_unsupported')
    return value

def validate_hook(value):
    if not BY_ID[validate_product(value)]['hooks']:
        raise ValueError('aidr_hook_agent_unsupported')
    return value

LogAgentID = Annotated[str, AfterValidator(validate_log)]
HookAgentID = Annotated[str, AfterValidator(validate_hook)]
