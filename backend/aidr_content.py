"""Bounded, explicitly selected audit text and separate content presentation."""
import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

CONTENT_FIELDS = {
    'command_body': {'input.command', 'input.cmd', 'input.code'},
    'prompt': {'hook.prompt', 'hook.prompt.request', 'hook.prompt.context',
               'message.input', 'message.input.request', 'message.input.context'},
    'model_response': {'message.output'},
    'tool_output': {'result.text', 'result.stdout', 'result.stderr', 'result.output', 'result.content.text'},
    'file_body': {'input.content', 'input.old_string', 'input.new_string', 'input.edits.old_string', 'input.edits.new_string', 'input.patch', 'input.command', 'result.file.text'},
}


class CaptureScope(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    prompt: bool = False
    tool_output: bool = False
    file_body: bool = False
    model_response: bool = False
    command_body: bool = False
    max_fragment_bytes: int = Field(default=1024, ge=256, le=32768)
    max_event_bytes: int = Field(default=2048, ge=256, le=32768)

    @model_validator(mode='after')
    def check_limits(self):
        if self.max_fragment_bytes > self.max_event_bytes:
            raise ValueError('audit_content_limit_invalid')
        return self

    @model_serializer(mode='wrap')
    def compatible_scope(self, handler):
        value = handler(self)
        if not self.model_response:
            value.pop('model_response', None)
        if not self.command_body:
            value.pop('command_body', None)
        for key, default in (('max_fragment_bytes', 1024), ('max_event_bytes', 2048)):
            if value.get(key) == default:
                value.pop(key, None)
        return value


class AuditLifecycle(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = True
    retention_days: int = Field(default=7, ge=1, le=365)


class Content(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['prompt', 'model_response', 'tool_output', 'file_body', 'command_body']
    source_field: str = Field(max_length=64)
    block: int = Field(ge=0, le=65535)
    text: str = Field(max_length=32768)
    source_bytes: int = Field(ge=0, le=4 << 20)
    redacted: bool
    truncated: bool

    @model_validator(mode='after')
    def check(self):
        if self.source_field not in CONTENT_FIELDS[self.kind] or len(self.text.encode()) > 32768:
            raise ValueError('audit_content_field_invalid')
        if any(ord(c) < 32 and c not in '\n\t' for c in self.text):
            raise ValueError('audit_content_control_invalid')
        return self


ContentStatus = Literal['not_requested', 'not_provided', 'unsupported', 'captured', 'partial']


def validate_contents(contents, status, policy):
    if len(contents or []) > 4 or sum(len(item.text.encode()) for item in contents or []) > (policy.capture.max_event_bytes if policy.capture else 2048):
        raise ValueError('audit_content_limit')
    if bool(contents) != (status in {'captured', 'partial'}):
        raise ValueError('audit_content_status_invalid')
    from .aidr_redaction import redact_values
    for item in contents or []:
        if len(item.text.encode()) > (policy.capture.max_fragment_bytes if policy.capture else 1024):
            raise ValueError('audit_content_limit')
        if not policy.capture or not getattr(policy.capture, item.kind):
            raise ValueError('audit_content_scope_invalid')
        if policy.enabled and redact_values(item.text) != item.text:
            raise ValueError('audit_content_secret_rejected')


def command_summaries(behavior):
    """Legacy/action command text is audit content, including wrapper actions."""
    captured = behavior.get('contents') or []
    if any(item.get('kind') == 'command_body' and item.get('source_field') in ('input.command', 'input.cmd') for item in captured):
        return []
    return [dict(kind='command_body', source_field='behavior.actions.command', block=index,
                 text=action['command'], source_bytes=len(action['command'].encode()),
                 redacted=bool(behavior.get('redacted')), truncated=bool(behavior.get('truncated')),
                 command_summary=True)
            for index, action in enumerate(behavior.get('actions') or []) if action.get('command')]


def metadata_view(value):
    """No list, operation, approval or projection-JSON response contains body text."""
    value = copy.deepcopy(value)
    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get('actions'), list):
                summaries = command_summaries(node)
                if summaries:
                    node['contents'] = [*(node.get('contents') or []), *summaries]
                for action in node['actions']:
                    action.pop('command', None)
                    action.pop('command_analysis', None)
            for key, child in node.items():
                if key == 'contents' and isinstance(child, list):
                    for item in child:
                        if isinstance(item, dict):
                            text = item.pop('text', '')
                            item['stored_bytes'] = len(text.encode())
                else:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return value


def record_contents(value):
    event = value.get('event', value)
    behavior = event.get('behavior') or {}
    return [*(event.get('contents') or []), *(behavior.get('contents') or []),
            *((event.get('message') or {}).get('contents') or []), *command_summaries(behavior)]
