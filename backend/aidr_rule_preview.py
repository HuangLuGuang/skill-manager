"""Read-only draft matching; no publication, approval or device action."""
from typing import Literal

from pydantic import Field, field_validator

from .aidr_enforcement import Strict, PolicyInput, absolute_path
from .aidr_hook_control import ToolPolicyInput, evaluate


class HookRulePreview(Strict):
    policy: ToolPolicyInput
    agent: Literal['claude', 'codex']
    tool: str = Field(min_length=1, max_length=256, pattern=r'^\S+$')


class SystemRulePreview(Strict):
    policy: PolicyInput
    path: str
    actor: Literal['agent', 'unknown']
    _path = field_validator('path')(absolute_path)


def preview_hook(body: HookRulePreview):
    policy = body.policy.model_dump()
    result = evaluate(policy, body.agent, body.tool)
    rows = []
    for rule in policy['rules']:
        agent = rule['agent'] in ('*', body.agent)
        tool = rule['tool'] in ('*', body.tool)
        rows.append(dict(id=rule['id'], matched=agent and tool,
                         reason='matched' if agent and tool else 'agent_and_tool' if not agent and not tool else 'agent' if not agent else 'tool',
                         decision=rule['decision']))
    return dict(**result, rules=rows, basis='hook', used_default=not result['matched_rule_ids'])


def preview_system(body: SystemRulePreview):
    # Native AUTH_OPEN also matches device/inode. The server only has draft paths.
    rows, matched, winner, denied = [], [], None, False
    for rule in body.policy.rules:
        matches = rule.path == body.path
        unknown = rule.actor == 'agent' and body.actor == 'unknown'
        decision = body.policy.unknown_actor_action if unknown else rule.decision
        rows.append(dict(id=rule.id, matched=matches, decision=decision,
                         reason='path' if not matches else 'unknown_actor' if unknown else 'matched'))
        if matches:
            if not matched or decision == 'deny':
                winner = rule.id
            matched.append(rule.id)
            denied |= decision == 'deny'
    return dict(decision='deny' if denied else 'allow', rule_id=winner,
                matched_rule_ids=matched, rules=rows, basis='system_path', used_default=not matched)
