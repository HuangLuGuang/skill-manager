"""Platform-managed Agent discovery catalog, delivered with client policy."""
import hashlib
import json
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from . import models
from .api_errors import ApiError

KEY = 'client_agent_discovery'
REQUIRED_BUILTIN_TYPES = {'teleagent'}
SEEDS = [
    ('global-skills', 'Shared Skills', '.agents/skills'),
    ('claude-code', 'Claude Code', '.claude/skills'), ('codex', 'Codex', '.codex/skills'),
    ('gemini', 'Gemini CLI', '.gemini/skills'), ('opencode', 'OpenCode', '.opencode/skills'),
    ('openclaw', 'OpenClaw', '.openclaw/skills'), ('hermes', 'Hermes', '.hermes/skills'),
    ('trae-cn', 'TRAE CN', '.trae-cn/skills'), ('trae', 'TRAE', '.trae/skills'),
    ('cursor', 'Cursor', '.cursor/skills'), ('codebuddy', 'CodeBuddy', '.codebuddy/skills'),
    ('workbuddy', 'WorkBuddy', '.workbuddy/skills'),
    ('teleagent', 'TeleAgent', '.config/TeleAgent/users/*/skills'),
    ('qoder', 'Qoder', '.qoder/skills'), ('qoder-cn', 'Qoder CN', '.qoder-cn/skills'),
    ('qoderwork', 'QoderWork', '.qoderwork/skills'), ('zcode', 'ZCode', '.zcode/skills'),
    ('claude-desktop', 'Claude Desktop', ''), ('kimi-work', 'Kimi Work', ''), ('doubao-work', 'Doubao Work', ''),
]

class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    agent_type: str = Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    systems: list[Literal['darwin', 'windows', 'linux']] = Field(default_factory=lambda: ['darwin', 'windows', 'linux'], min_length=1)
    skill_roots: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def valid_roots(self):
        self.name = self.name.strip()
        if not self.name or (self.enabled and not self.skill_roots):
            raise ValueError('Enabled Agent requires a name and Skill directory')
        self.skill_roots = list(dict.fromkeys(root.strip() for root in self.skill_roots))
        for root in self.skill_roots:
            value = root.replace('\\', '/')
            parts = PurePosixPath(value).parts
            wildcard_parts = [part for part in parts if any(char in part for char in '*?[]')]
            invalid = (
                not value.strip() or len(value) > 512 or '..' in parts
                or any(c in value for c in ['\0', '\n', '\r', '?', '[', ']'])
                or any(part != '*' for part in wildcard_parts)
            )
            if invalid:
                raise ValueError('Invalid Skill directory')
        return self

class CatalogChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: str
    agents: list[AgentDefinition] = Field(max_length=100)

    @model_validator(mode='after')
    def unique_types(self):
        if len({a.agent_type for a in self.agents}) != len(self.agents):
            raise ValueError('Agent identifiers must be unique')
        return self

def defaults():
    result = []
    for kind, name, root in SEEDS:
        roots = [root] if root else []
        if kind == 'opencode':
            roots.append('.config/opencode/skills')
        result.append(AgentDefinition(agent_type=kind, name=name, enabled=bool(root), skill_roots=roots).model_dump())
    return result

def view(db: Session, client=None):
    row = db.get(models.SystemConfig, KEY)
    agents = json.loads(row.value) if row else defaults()
    existing_types = {agent.get('agent_type') for agent in agents}
    agents.extend(
        agent for agent in defaults()
        if agent['agent_type'] in REQUIRED_BUILTIN_TYPES and agent['agent_type'] not in existing_types
    )
    global_agents = agents
    overrides = json.loads(client.discovery_overrides_json or '[]') if client else []
    by_type = {agent['agent_type']: agent for agent in global_agents}
    by_type.update({agent['agent_type']: agent for agent in overrides})
    agents = list(by_type.values())
    version = hashlib.sha256(json.dumps(agents, sort_keys=True).encode()).hexdigest()
    if client is None:
        return {'version': version, 'agents': agents}
    edit_version = hashlib.sha256(json.dumps([global_agents, overrides], sort_keys=True).encode()).hexdigest()
    return {'version': version, 'edit_version': edit_version, 'agents': agents,
            'global_agents': global_agents, 'overrides': overrides}

def save(db: Session, body: CatalogChange, client=None):
    current = view(db, client)
    if body.expected_version != current.get('edit_version', current['version']):
        raise ApiError(409, 'client.discovery_conflict', 'Agent 配置已更新，请重新打开后修改', 'Agent configuration changed; reopen it before editing')
    value = json.dumps([a.model_dump() for a in body.agents], ensure_ascii=False)
    if client:
        result = db.execute(update(models.ManagedClient).where(
            models.ManagedClient.id == client.id,
            models.ManagedClient.discovery_overrides_json == client.discovery_overrides_json,
        ).values(discovery_overrides_json=value))
        if result.rowcount != 1:
            raise ApiError(409, 'client.discovery_conflict', 'Agent 配置已更新，请重新打开后修改', 'Agent configuration changed; reopen it before editing')
        db.flush()
        db.refresh(client)
        return view(db, client)
    row = db.get(models.SystemConfig, KEY)
    if row:
        result = db.execute(update(models.SystemConfig).where(models.SystemConfig.key == KEY, models.SystemConfig.value == row.value).values(value=value))
        if result.rowcount != 1:
            raise ApiError(409, 'client.discovery_conflict', 'Agent 配置已更新，请重新打开后修改', 'Agent configuration changed; reopen it before editing')
    else:
        db.add(models.SystemConfig(key=KEY, value=value))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, 'client.discovery_conflict', 'Agent 配置已更新，请重新打开后修改', 'Agent configuration changed; reopen it before editing') from exc
    return view(db)
