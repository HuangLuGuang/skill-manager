"""Strict allowlist for readable log intent; reject unredacted secret patterns."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .aidr_content import AuditLifecycle, CaptureScope, Content, ContentStatus, validate_contents
from .aidr_skill_contract import SkillAuditPolicy

PATTERNS = [
 r'(?is)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)',
 r'(?i)(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*[^\r\n]+',
 r'''(?i)(?:[A-Za-z0-9_]*(?:token|password|passwd|secret|api[_-]?key|credential)[A-Za-z0-9_]*["']?\s*(?:=|:|\s)\s*)(?:"(?:\\.|[^"\\])*"|'[^']*'|[^\s;,]+)''',
 r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+',
 r'\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|AKIA[A-Z0-9]{16}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b',
 r'(?i)https?://[^\s/@]+:[^\s/@]+@',
 r'''\?[^\s"']+''',
]
CATEGORIES = {'Bash':'command','exec_command':'command','shell_command':'command','Read':'file_read','read_file':'file_read','Write':'file_write','write_file':'file_write','Edit':'file_edit','MultiEdit':'file_edit','edit_file':'file_edit','rename_file':'file_rename','move_file':'file_rename','WebFetch':'network_request','fetch':'network_request','apply_patch':'patch'}
CATEGORIES.update({'bash': 'command', 'Shell': 'command', 'read': 'file_read', 'write': 'file_write', 'edit': 'file_edit', 'webfetch': 'network_request'})
Category = Literal['unknown','command','file_read','file_write','file_edit','file_rename','network_request','patch','wrapper']
Status = Literal['unknown','reported_complete','reported_error','reported_success','reported_cancelled']


def safe(value, limit, redact=True):
    if len(value.encode('utf-8'))>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise ValueError('behavior_text_limit')
    if redact and any(re.search(p,value) for p in PATTERNS):
        raise ValueError('behavior_secret_rejected')
    return value


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Target(Strict):
    kind: Literal['file','url','old_path','new_path']
    value: str = Field(min_length=1,max_length=512)
    @model_validator(mode='after')
    def check(self):
        safe(self.value,512,False)
        return self


class Action(Strict):
    tool: str = Field(max_length=128)
    category: Category
    command: str = Field(default='',max_length=1536)
    cwd: str = Field(default='',max_length=512)
    targets: list[Target] = Field(max_length=4)
    source_fields: list[Literal['command','cmd','workdir','cwd','file_path','path','old_path','new_path','url','patch','patch.header','record.cwd']] = Field(max_length=8)
    @model_validator(mode='after')
    def check(self):
        if CATEGORIES.get(self.tool)!=self.category:
            raise ValueError('behavior_tool_invalid')
        safe(self.command,1536,False);safe(self.cwd,512,False)
        if self.category!='command' and self.command:
            raise ValueError('behavior_field_not_allowed')
        kinds=[target.kind for target in self.targets]
        limits={'command':(0,set()),'file_read':(1,{'file'}),'file_write':(1,{'file'}),'file_edit':(1,{'file'}),'file_rename':(2,{'old_path','new_path'}),'network_request':(1,{'url'}),'patch':(4,{'file'})}
        limit, allowed=limits[self.category]
        if len(kinds)>limit or not set(kinds)<=allowed:
            raise ValueError('behavior_target_invalid')
        return self


class AuditPolicy(Strict):
    skill_audit: SkillAuditPolicy | None = None
    model_context_schema: Literal[1] | None = None
    message_schema: Literal[1] | None = None
    version: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    enabled: bool
    receipt: str = Field(pattern=r"^$|^[0-9a-f]{32}$")
    capture: CaptureScope | None = None
    lifecycle: AuditLifecycle | None = None

    @model_validator(mode='after')
    def check(self):
        if self.version == '0' and (not self.enabled or self.receipt or self.capture is not None or self.lifecycle is not None or self.skill_audit is not None):
            raise ValueError('audit_policy_initial_invalid')
        if self.lifecycle is not None and self.capture is None:
            raise ValueError('audit_policy_lifecycle_invalid')
        return self


class Behavior(Strict):
    version: Literal[1, 2, 3, 4, 5]
    contents: list[Content] | None = Field(default=None, max_length=4)
    content_status: ContentStatus | None = None
    policy: AuditPolicy | None = None
    body_omitted: bool | None = None
    category: Category
    method: Literal['unsupported','direct_fields','literal_wrapper','result_fields']
    actions: list[Action] = Field(max_length=4)
    status: Status
    exit_code: int | None = Field(default=None,ge=-2147483648,le=2147483647)
    result_basis: list[Literal['is_error_false','is_error_true','structured_exit_code','error_exit_header','cancelled','interrupted']] = Field(max_length=8)
    redacted: bool
    truncated: bool
    uncertainty: list[Literal['wrapper_execution_unknown','unsupported_arguments','multiple_result_codes','result_semantics_unknown','host_result_not_provided','result_format_unsupported','result_fields_conflict']] = Field(max_length=8)
    @model_validator(mode='after')
    def check(self):
        if self.version < 3 and (self.policy is not None or self.body_omitted is not None):
            raise ValueError('behavior_policy_invalid')
        if self.version >= 3 and (self.policy is None or (self.policy.version == "0" and (not self.policy.enabled or self.policy.receipt))):
            raise ValueError('behavior_policy_invalid')
        if self.version < 4 and (self.contents is not None or self.content_status is not None or (self.policy and self.policy.capture is not None)):
            raise ValueError('behavior_content_version_invalid')
        if self.version < 5 and self.policy and self.policy.lifecycle is not None:
            raise ValueError('behavior_lifecycle_version_invalid')
        if self.version == 5 and (self.policy.lifecycle is None or not self.policy.lifecycle.enabled):
            raise ValueError('behavior_collection_disabled')
        if self.version >= 4:
            if not self.policy.capture or self.content_status is None:
                raise ValueError('behavior_content_policy_missing')
            validate_contents(self.contents, self.content_status, self.policy)
            for item in self.contents or []:
                if item.kind == 'command_body':
                    if self.method == 'result_fields' or self.category not in {'command', 'wrapper'} or (item.source_field == 'input.code') != (self.category == 'wrapper'):
                        raise ValueError('behavior_content_source_invalid')
                    continue
                if item.source_field == 'input.command' and (self.category != 'patch' or not any(action.tool == 'apply_patch' for action in self.actions)):
                    raise ValueError('behavior_content_source_invalid')
                if item.kind == 'prompt' or (item.source_field.startswith('input.') and self.category not in {'file_write', 'file_edit', 'patch'}) or (item.source_field.startswith('result.') and self.method != 'result_fields'):
                    raise ValueError('behavior_content_source_invalid')
        for action in self.actions:
            values = [(action.command,1536),(action.cwd,512)] + [(target.value,512) for target in action.targets]
            if self.version < 3:
                for value,limit in values:
                    safe(value,limit)
                if '<<' in action.command:
                    raise ValueError('behavior_payload_rejected')
                for quoted in re.findall(r'''"(?:\\.|[^"\\])*"|'[^']*' ''', action.command, re.S | re.X):
                    value=quoted[1:-1]
                    if value!='[REDACTED]' and not re.fullmatch(r'(?:exit [0-9]{1,3}|%[sd](?:\\n)?)',value) and not ((value.startswith('/') or value.startswith('./')) and '\n' not in value and '\r' not in value):
                        raise ValueError('behavior_payload_rejected')
            else:
                from .aidr_redaction import redact_values, bound_command
                if bound_command(action.command) != action.command:
                    raise ValueError('behavior_payload_rejected')
                if self.policy.enabled and any(redact_values(value)!=value for value,_ in values):
                    raise ValueError('behavior_secret_rejected')
        if type(self.version) is not int:
            raise ValueError('behavior_version_invalid')
        if self.method=='result_fields' and self.actions:
            raise ValueError('behavior_result_actions_invalid')
        if set(self.uncertainty) & {'host_result_not_provided', 'result_format_unsupported', 'result_fields_conflict'} and self.method != 'result_fields':
            raise ValueError('behavior_result_uncertainty_conflict')
        if set(self.uncertainty) & {'result_format_unsupported', 'result_fields_conflict'} and (self.status != 'unknown' or self.exit_code is not None):
            raise ValueError('behavior_result_uncertainty_conflict')
        if 'host_result_not_provided' in self.uncertainty and (self.status != 'unknown' or self.exit_code is not None or self.result_basis):
            raise ValueError('behavior_result_uncertainty_conflict')
        if self.method!='result_fields' and (self.status!='unknown' or self.exit_code is not None or self.result_basis):
            raise ValueError('behavior_call_result_invalid')
        if self.status=='reported_success' and self.exit_code!=0:
            raise ValueError('behavior_result_basis_missing')
        if self.status=='reported_complete' and 'is_error_false' not in self.result_basis:
            raise ValueError('behavior_result_basis_missing')
        if self.status=='reported_cancelled' and not set(self.result_basis)&{'cancelled','interrupted'}:
            raise ValueError('behavior_result_basis_missing')
        if self.status=='reported_error' and 'is_error_true' not in self.result_basis and (self.exit_code is None or self.exit_code==0):
            raise ValueError('behavior_result_basis_missing')
        if self.exit_code is not None and not set(self.result_basis)&{'structured_exit_code','error_exit_header'}:
            raise ValueError('behavior_result_basis_missing')
        return self
