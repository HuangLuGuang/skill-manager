"""Read-only draft matching; no publication, approval or device action."""
from .aidr_products import HookAgentID
from typing import Literal

from pydantic import Field, field_validator

from .aidr_enforcement import Strict, PolicyInput, absolute_path
from .aidr_hook_control import ToolPolicyInput, evaluate
from .aidr_command_rules import observe, keyword_hits
from .aidr_command_networks import network_hits


class HookRulePreview(Strict):
    command: str = Field(default='', max_length=32768)
    cwd: str = Field(default='', max_length=1024)
    policy: ToolPolicyInput
    agent: HookAgentID
    tool: str = Field(min_length=1, max_length=256, pattern=r'^\S+$')


class SystemRulePreview(Strict):
    policy: PolicyInput
    path: str
    actor: Literal['agent', 'unknown']
    _path = field_validator('path')(absolute_path)


def preview_hook(body: HookRulePreview):
    policy = body.policy.model_dump()
    observation = observe(policy, body.agent, body.tool, body.command, body.cwd)
    result = evaluate(policy, body.agent, body.tool, observation)
    rows = []
    for rule in policy['rules']:
        agent = rule['agent'] in ('*', body.agent)
        tool = rule['tool'] in ('*', body.tool)
        if rule.get('command') and agent and tool:
            state = 'unresolved' if rule['id'] in observation['unresolved'] else 'matched' if rule['id'] in observation['matched'] else 'command'
            rows.append(dict(id=rule['id'], matched=state == 'matched', reason=state, decision=rule['decision']))
            continue
        rows.append(dict(id=rule['id'], matched=agent and tool,
                         reason='matched' if agent and tool else 'agent_and_tool' if not agent and not tool else 'agent' if not agent else 'tool',
                         decision=rule['decision']))
    keywords = [{'rule_id': rule['id'], 'terms': keyword_hits(rule['command']['keywords'], body.command)}
                for rule in policy['rules'] if rule['id'] in observation['matched'] and (rule.get('command') or {}).get('keywords')]
    networks = [{'rule_id': rule['id'], 'addresses': network_hits(rule['command']['networks'], body.command)}
                for rule in policy['rules'] if rule['id'] in observation['matched'] and (rule.get('command') or {}).get('networks')]
    return dict(**result, network_matches=networks, rules=rows, basis='hook', used_default=result['rule_id'] == 'default', keyword_matches=keywords)


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
