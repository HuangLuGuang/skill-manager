"""Serializable security rules shared by the editor and risk evaluator."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .aidr_risk_commands import DetectionCommandCondition
from .aidr_products import HookAgentID


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class PathSet(Strict):
    id: str = Field(pattern=r'^[A-Za-z0-9_:-]{1,100}$')
    name: str = Field(min_length=1, max_length=100)
    paths: list[str] = Field(default_factory=list, max_length=32)
    builtin_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode='after')
    def valid(self):
        from .aidr_risk import DetectionConfig
        DetectionConfig(sensitive_paths=self.paths, builtin_ids=self.builtin_ids)
        if not self.name.strip():
            raise ValueError('empty_path_set_name')
        return self


class Rule(Strict):
    id: str = Field(pattern=r'^[A-Za-z0-9_:-]{1,100}$')
    name: str = Field(default='', max_length=100)
    kind: Literal['builtin', 'command', 'tool']
    code: str = Field(default='', max_length=100)
    enabled: bool = True
    severity: Literal['medium', 'high'] | None = None
    action: Literal['none', 'allow', 'ask', 'deny'] = 'none'
    agent: HookAgentID | Literal['*'] | list[HookAgentID] = '*'
    tool: str = Field(default='*', min_length=1, max_length=256, pattern=r'^\S+$')
    platforms: list[Literal['linux', 'darwin', 'windows']] = Field(default_factory=lambda: ['linux', 'darwin', 'windows'], min_length=1, max_length=3)
    condition: DetectionCommandCondition | None = None
    path_set: str | None = Field(default=None, max_length=100)
    control_id: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,64}$')

    @model_validator(mode='after')
    def valid(self):
        from .aidr_risk import RISK_CODES
        if isinstance(self.agent, list) and (not self.agent or len(set(self.agent)) != len(self.agent)):
            raise ValueError('invalid_agent_selection')
        if self.kind != 'builtin' and not self.name.strip() or any(ord(c) < 32 for c in self.name + self.tool):
            raise ValueError('invalid_rule_name')
        if self.kind == 'builtin' and self.code not in set(RISK_CODES) - {'custom_command', 'custom_tool'}:
            raise ValueError('unknown_builtin')
        if self.kind == 'command' and (self.condition is None or self.condition.path_prefix):
            raise ValueError('command_requires_condition_and_path_reference')
        if self.condition and (self.condition.keywords or self.condition.networks) and self.path_set:
            raise ValueError('text_rule_has_no_path_condition')
        if self.kind != 'command' and self.condition is not None:
            raise ValueError('unexpected_command_condition')
        if self.kind == 'tool' and self.path_set:
            raise ValueError('tool_has_no_path_condition')
        if self.kind == 'builtin' and self.path_set and self.code not in ('sensitive_path_read', 'protected_path_change', 'destructive_command', 'protected_permissions'):
            raise ValueError('behavior_has_no_path_condition')
        if len(set(self.platforms)) != len(self.platforms):
            raise ValueError('duplicate_platform')
        return self


class Document(Strict):
    rules: list[Rule] = Field(default_factory=list, max_length=169)
    path_sets: list[PathSet] = Field(default_factory=list, max_length=192)

    @model_validator(mode='after')
    def valid(self):
        ids = {p.id for p in self.path_sets}
        if len(ids) != len(self.path_sets) or len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError('duplicate_id')
        if any(r.path_set and r.path_set not in ids for r in self.rules):
            raise ValueError('missing_path_set')
        paths = {p.id: p for p in self.path_sets}
        if sum(r.kind == 'command' and r.severity is not None for r in self.rules) > 32:
            raise ValueError('too_many_recorded_command_rules')
        if any(r.kind == 'command' and r.path_set and paths[r.path_set].builtin_ids for r in self.rules):
            raise ValueError('custom_command_requires_literal_paths')
        return self
