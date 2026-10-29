"""Bounded Skill metadata projected by an entry-specific host adapter."""
from . import aidr_adapters
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillAlertRules(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    content_changed: Literal['record', 'alert'] = 'alert'
    approval: Literal['record', 'alert'] = 'alert'
    unauthorized: Literal['record', 'alert'] = 'alert'


class SkillAuditPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = True
    alerts: bool = True
    check_mode: Literal['on_change', 'every_use'] = 'on_change'
    digest_cache_seconds: int = Field(default=300, ge=60, le=3600)
    status_refresh_seconds: int = Field(default=30, ge=5, le=3600)
    max_concurrency: int = Field(default=1, ge=1, le=8)
    max_files: int = Field(default=256, ge=1, le=10000)
    max_file_bytes: int = Field(default=2 << 20, ge=1 << 20, le=100 << 20)
    max_total_bytes: int = Field(default=8 << 20, ge=1 << 20, le=1 << 30)
    alert_rules: SkillAlertRules = Field(default_factory=SkillAlertRules)

    @model_validator(mode='after')
    def check_limits(self):
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError('skill_audit_limits_invalid')
        return self


def skill_audit_policy(value=None):
    return SkillAuditPolicy.model_validate(value or {}).model_dump()


class SkillUse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    behavior: Literal['invocation', 'file_access']
    name: str = Field(default='', max_length=256)
    path: str = Field(default='', max_length=1024)
    basis: Literal['tool_input.skill', 'tool_input.name', 'tool_input.command', 'tool_input.file_path', 'tool_input.path', 'literal_cat', 'result.base_directory', 'result.metadata']
    phase: Literal['host_loaded'] | None = None
    content_digest: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    content_observed_at: str | None = Field(default=None, max_length=40)
    content_status: Literal['computed', 'reused', 'unavailable', 'disabled'] | None = None
    content_reason: Literal['source_missing', 'source_unreadable', 'source_symlink', 'source_changed', 'file_limit', 'file_size_limit', 'total_size_limit', 'entry_limit', 'check_cancelled', 'audit_disabled'] | None = None

    def validate_source(self, agent, tool, kind, redact=True):
        if kind not in {'tool_call', 'tool_result', 'tool.pre', 'tool.post', 'tool.failure', 'permission.request', 'permission.denied'}:
            raise ValueError('skill_event_source_invalid')
        if self.behavior == 'invocation':

            if self.basis.startswith('result.'):
                if kind != 'tool_result' or aidr_adapters.get(agent).skill_result != self.basis:
                    raise ValueError('skill_result_source_invalid')
            elif aidr_adapters.get(agent).skill_input != (tool, self.basis):
                raise ValueError('skill_invocation_source_invalid')
        if redact:
            from .aidr_redaction import redact_values
            if any(redact_values(value) != value for value in (self.name, self.path)):
                raise ValueError('skill_metadata_secret_rejected')

    @model_validator(mode='after')
    def check(self):
        if self.content_status in {'computed', 'reused'} and (not self.content_digest or self.content_reason):
            raise ValueError('skill_content_status_invalid')
        if self.content_status in {'unavailable', 'disabled'} and (self.content_digest or not self.content_reason):
            raise ValueError('skill_content_status_invalid')
        if self.content_reason and self.content_status not in {'unavailable', 'disabled'}:
            raise ValueError('skill_content_status_invalid')
        if self.behavior == 'invocation':
            if not ((self.name and not self.path and self.basis in {'tool_input.skill','tool_input.name','tool_input.command'} and self.phase is None) or (self.path and self.basis in {'result.base_directory', 'result.metadata'} and self.phase == 'host_loaded')):
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


class SkillObservationReceipt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    skill: SkillUse
    policy_version: str = Field(min_length=1, max_length=128)
    observed_at: str = Field(min_length=1, max_length=40)
    resolved_path: str = Field(min_length=1, max_length=1024)

    @model_validator(mode='after')
    def check_observation(self):
        from datetime import datetime
        from pathlib import PurePosixPath, PureWindowsPath
        from .aidr_redaction import redact_values
        if datetime.fromisoformat(self.observed_at.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('skill_observation_time_invalid')
        if not (PurePosixPath(self.resolved_path).is_absolute() or PureWindowsPath(self.resolved_path).is_absolute()):
            raise ValueError('skill_source_invalid')
        if any(ord(c) < 32 for c in self.resolved_path) or redact_values(self.resolved_path) != self.resolved_path or redact_values(self.skill.path) != self.skill.path:
            raise ValueError('skill_metadata_secret_rejected')
        if self.skill.content_status not in {'computed', 'unavailable'}:
            raise ValueError('skill_observation_status_invalid')
        return self
