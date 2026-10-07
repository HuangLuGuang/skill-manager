"""Bounded Skill metadata projected by an entry-specific host adapter."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillAuditPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = True
    alerts: bool = True


class SkillUse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    behavior: Literal['invocation', 'file_access']
    name: str = Field(default='', max_length=256)
    path: str = Field(default='', max_length=1024)
    basis: Literal['tool_input.skill', 'tool_input.name', 'tool_input.file_path', 'tool_input.path', 'literal_cat', 'result.base_directory', 'result.metadata']
    phase: Literal['host_loaded'] | None = None
    content_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    content_observed_at: str | None = Field(default=None, max_length=40)

    def validate_source(self, agent, tool, kind, redact=True):
        if kind not in {'tool_call', 'tool_result', 'tool.pre', 'tool.post', 'tool.failure', 'permission.request', 'permission.denied'}:
            raise ValueError('skill_event_source_invalid')
        if self.behavior == 'invocation':
            products = {'claude':('Skill','tool_input.skill'), 'workbuddy':('Skill','tool_input.skill'), 'qoder-cli':('Skill','tool_input.skill'), 'opencode':('skill','tool_input.name')}
            if self.basis.startswith('result.'):
                if kind != 'tool_result' or {'workbuddy':'result.base_directory','opencode':'result.metadata'}.get(agent) != self.basis:
                    raise ValueError('skill_result_source_invalid')
            elif products.get(agent) != (tool, self.basis):
                raise ValueError('skill_invocation_source_invalid')
        if redact:
            from .aidr_redaction import redact_values
            if any(redact_values(value) != value for value in (self.name, self.path)):
                raise ValueError('skill_metadata_secret_rejected')

    @model_validator(mode='after')
    def check(self):
        if self.behavior == 'invocation':
            if not ((self.name and not self.path and self.basis in {'tool_input.skill','tool_input.name'} and self.phase is None) or (self.path and self.basis in {'result.base_directory', 'result.metadata'} and self.phase == 'host_loaded')):
                raise ValueError('skill_invocation_invalid')
        elif not self.path.endswith('/SKILL.md') or self.basis not in {'tool_input.path', 'tool_input.file_path', 'literal_cat'} or self.phase:
            raise ValueError('skill_access_invalid')
        if self.path:
            from pathlib import PurePosixPath, PureWindowsPath
            if not self.path.endswith('/SKILL.md') or not (PurePosixPath(self.path).is_absolute() or PureWindowsPath(self.path).is_absolute()):
                raise ValueError('skill_source_invalid')
        if any(ord(c) < 32 for c in self.name + self.path):
            raise ValueError('skill_metadata_invalid')
        if bool(self.content_digest) != bool(self.content_observed_at) or (self.content_digest and not self.path):
            raise ValueError('skill_content_identity_invalid')
        if self.content_observed_at:
            from datetime import datetime
            if datetime.fromisoformat(self.content_observed_at.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('skill_observation_time_invalid')
        return self
