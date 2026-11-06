"""Incremental, evidence-backed runtime findings. No execution authority."""
import asyncio
import hashlib
import json
import logging
import ntpath
import posixpath
import shlex
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Column, DateTime, Integer, String, Text, Index, UniqueConstraint, func
from sqlalchemy.dialects.sqlite import insert

from .sqlite_db import Base
from .aidr_models import AidrEvent, AidrHookEvent, AidrOperation
from .aidr_enforcement import AidrRuntimeRecord
from .aidr_command_rules import parse
from .aidr_operations import operation_key, stamp
from . import aidr_risk_catalog as catalog
from . import aidr_risk_commands as commands
from . import aidr_risk_windows as windows_commands
from .aidr_security_config import Document

RULE_VERSION = 'runtime-risk/5'
SOURCES = {'hooks': AidrHookEvent, 'logs': AidrEvent, 'system': AidrRuntimeRecord}
RISK_CODES = ('destructive_command', 'download_to_shell', 'sensitive_path_read',
              'protected_path_change', 'tool_policy_denied', 'system_access_denied',
              'filesystem_format', 'device_write', 'protected_permissions', 'custom_command', 'custom_tool')


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class RiskConfig(Base):
    __tablename__ = 'aidr_risk_configs'
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('client_id', 'revision'),)


class RiskCursor(Base):
    __tablename__ = 'aidr_risk_cursors'
    source = Column(String(8), primary_key=True)
    position = Column(Integer, nullable=False, default=0)
    checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class GlobalRiskConfig(Base):
    __tablename__ = 'aidr_global_risk_configs'
    revision = Column(Integer, primary_key=True)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RiskDetectionContext(Base):
    __tablename__ = 'aidr_risk_detection_contexts'
    finding_id = Column(String(64), primary_key=True)
    payload = Column(Text, nullable=False)


class RiskFinding(Base):
    __tablename__ = 'aidr_risk_findings'
    id = Column(String(64), primary_key=True)
    client_id = Column(String(128), nullable=False)
    source = Column(String(8), nullable=False)
    anchor_id = Column(Integer, nullable=False)
    agent = Column(String(32), nullable=False, default='')
    session_id = Column(String(256), nullable=False, default='')
    tool = Column(String(256), nullable=False, default='')
    risk_code = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False)
    config_revision = Column(Integer, nullable=False)
    rule_version = Column(String(32), nullable=False)
    policy_revision = Column(String(32), nullable=False, default='')
    rule_ids = Column(Text, nullable=False, default='[]')
    occurred_at = Column(String(64), nullable=False)
    time_basis = Column(String(16), nullable=False)
    result_status = Column(String(32), nullable=False, default='unknown')
    control_status = Column(String(32), nullable=False, default='unknown')
    control_code = Column(String(128), nullable=False, default='')
    disposition = Column(String(32), nullable=False, default='open')
    disposition_revision = Column(Integer, nullable=False, default=0)
    limitations = Column(Text, nullable=False, default='[]')
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index('ix_aidr_risk_client_page', 'client_id', 'occurred_at', 'id'),
                     Index('ix_aidr_risk_client_detected', 'client_id', 'detected_at'),
                     Index('ix_aidr_risk_anchor', 'client_id', 'source', 'anchor_id'))


class RiskDisposition(Base):
    __tablename__ = 'aidr_risk_dispositions'
    finding_id = Column(String(64), primary_key=True)
    revision = Column(Integer, primary_key=True)
    previous = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False)
    actor = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DispositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(ge=0, le=2**31-1)
    status: Literal['open', 'accepted', 'false_positive', 'resolved']
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('reason_required')
        return value


class RiskEvidence(Base):
    __tablename__ = 'aidr_risk_evidence'
    finding_id = Column(String(64), primary_key=True)
    source = Column(String(8), primary_key=True)
    record_id = Column(Integer, primary_key=True)
    digest = Column(String(64), nullable=False)


class DetectionConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_revision: int = Field(default=0, ge=0, le=2**31-1)
    enabled: bool = True
    sensitive_paths: list[str] = Field(default_factory=list, max_length=32)
    protected_paths: list[str] = Field(default_factory=list, max_length=32)
    builtin_ids: list[str] = Field(default_factory=list, max_length=32)
    command_rules: list[str] = Field(default_factory=lambda: list(commands.LEGACY_COMMANDS), max_length=5)
    custom_commands: list[commands.CustomCommandRule] = Field(default_factory=list, max_length=32)
    security: Document | None = None

    @field_validator('custom_commands')
    @classmethod
    def unique_commands(cls, values):
        if len({rule.id for rule in values}) != len(values):
            raise ValueError('duplicate_rule_id')
        return values

    @field_validator('builtin_ids', 'command_rules')
    @classmethod
    def known_rules(cls, values, info):
        allowed = catalog.IDS if info.field_name == 'builtin_ids' else catalog.COMMANDS
        if len(set(values)) != len(values) or any(value not in allowed for value in values):
            raise ValueError('invalid_rules')
        return values

    @field_validator('sensitive_paths', 'protected_paths')
    @classmethod
    def paths(cls, values):
        for value in values:
            windows = bool(ntpath.splitdrive(value)[0])
            path = ntpath if windows else posixpath
            if (not value or len(value.encode()) > 512 or any(ord(c) < 32 for c in value)
                    or not path.isabs(value) or (windows and not ntpath.splitdrive(value)[1].startswith(('\\', '/')))
                    or any(x in value for x in ('*', '?', '[REDACTED]'))
                    or path.normpath(value) != value):
                raise ValueError('invalid_absolute_path')
        if len(set(values)) != len(values):
            raise ValueError('duplicate_path')
        return values


class ClientDetectionConfig(DetectionConfig):
    enabled_mode: Literal['inherit', 'enabled', 'disabled'] | None = None
    rules_mode: Literal['inherit', 'custom'] = 'custom'
    expected_global_revision: int | None = Field(default=None, ge=0)


class CommandTestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    command: str = Field(min_length=1, max_length=32768)
    cwd: str = Field(default='', max_length=512)
    platform: Literal['linux', 'darwin', 'windows']
    configuration: DetectionConfig

    @field_validator('command', 'cwd')
    @classmethod
    def valid_text(cls, value, info):
        if len(value.encode()) > (32768 if info.field_name == 'command' else 512):
            raise ValueError('too_long')
        path = ntpath if ntpath.splitdrive(value)[0] else posixpath
        if info.field_name == 'cwd' and value and (not path.isabs(value) or path.normpath(value) != value):
            raise ValueError('invalid_cwd')
        return value

    @model_validator(mode='after')
    def cwd_platform(self):
        if self.cwd and (any(ord(c) < 32 for c in self.cwd)
                         or (self.platform == 'windows') != windows_commands.absolute(self.cwd)):
            raise ValueError('invalid_cwd_platform')
        return self


def initialize_global_detection(db):
    """Seed recommended paths; upgrade only the untouched legacy baseline."""
    from .models import ManagedClient
    row = db.query(GlobalRiskConfig).order_by(GlobalRiskConfig.revision.desc()).first()
    if row is None:
        upgrading = db.query(ManagedClient.id).first() is not None
        payload = DetectionConfig(builtin_ids=catalog.IDS,
            command_rules=commands.LEGACY_COMMANDS if upgrading else catalog.COMMANDS).model_dump(exclude={'expected_revision'})
        db.execute(insert(GlobalRiskConfig).values(revision=1, payload=dump(payload)).on_conflict_do_nothing())
    elif row.revision == 1:
        payload = json.loads(row.payload)
        baseline = DetectionConfig().model_dump(exclude={'expected_revision'})
        # Revision 1 is the startup seed; later saves may intentionally clear paths.
        if {**baseline, **payload} == baseline:
            db.execute(insert(GlobalRiskConfig).values(revision=2,
                payload=dump({**payload, 'builtin_ids': catalog.IDS})).on_conflict_do_nothing())


def global_configuration(db):
    row = db.query(GlobalRiskConfig).order_by(GlobalRiskConfig.revision.desc()).first()
    defaults = DetectionConfig().model_dump(exclude={'expected_revision'})
    return (row.revision, {**defaults, **json.loads(row.payload)}) if row else (0, defaults)


def configuration_view(db, client_id):
    row = db.query(RiskConfig).filter_by(client_id=client_id).order_by(RiskConfig.revision.desc()).first()
    global_revision, global_config = global_configuration(db)
    local = json.loads(row.payload) if row else {}
    enabled_mode = (local.get('enabled_mode') or ('enabled' if local.get('enabled', True) else 'disabled')) if row else 'inherit'
    rules_mode = local.get('rules_mode', 'custom') if row else 'inherit'
    effective = {**DetectionConfig().model_dump(exclude={'expected_revision'}), **(global_config if rules_mode == 'inherit' else local)}
    effective['enabled'] = global_config['enabled'] if enabled_mode == 'inherit' else enabled_mode == 'enabled'
    return {'revision': row.revision if row else 0, 'global_revision': global_revision,
            'enabled_mode': enabled_mode, 'rules_mode': rules_mode,
            'effective': {key: effective[key] for key in ('enabled', 'sensitive_paths', 'protected_paths', 'builtin_ids', 'command_rules', 'custom_commands', 'security')}}


def configuration(db, client_id):
    from .models import ManagedClient
    view = configuration_view(db, client_id)
    client = db.query(ManagedClient).filter_by(client_id=client_id).first()
    return view['revision'], {**view['effective'], 'global_revision': view['global_revision'],
                             'rules_mode': view['rules_mode'], 'platform': client.os if client else ''}


def configuration_impact(db):
    from .models import ManagedClient
    latest = db.query(RiskConfig.client_id, func.max(RiskConfig.revision).label('revision')).group_by(RiskConfig.client_id).subquery()
    rows = db.query(RiskConfig.payload).join(latest, (RiskConfig.client_id == latest.c.client_id) & (RiskConfig.revision == latest.c.revision)).join(ManagedClient, ManagedClient.client_id == RiskConfig.client_id).all()
    total = db.query(ManagedClient).count()
    independent_rules = sum(json.loads(row[0]).get('rules_mode', 'custom') == 'custom' for row in rows)
    independent_enabled = sum(json.loads(row[0]).get('enabled_mode') != 'inherit' for row in rows)
    return {'rules': total - independent_rules, 'enabled': total - independent_enabled}


def path_match(value, roots, cwd='', windows=False):
    if not value or '[REDACTED]' in value:
        return False
    path = ntpath if windows else posixpath
    if windows and (not ntpath.splitdrive(value)[0] or not path.isabs(value)):
        if ntpath.splitdrive(value)[0] or value.startswith(('\\', '/')) or not ntpath.isabs(cwd) or not ntpath.splitdrive(cwd)[0]:
            return False
    elif not path.isabs(value) and not path.isabs(cwd):
        return False
    candidate = path.normcase(path.normpath(path.join(cwd, value)))
    for root in roots:
        if isinstance(root, dict):
            if catalog.template_matches(candidate, root, windows):
                return True
            continue
        if windows != bool(ntpath.splitdrive(root)[0]):
            continue
        normalized = path.normcase(path.normpath(root))
        if candidate == normalized or candidate.startswith(normalized.rstrip('/\\') + path.sep):
            return True
    return False


def download_pipe(command):
    parts = parse(command)
    if parts is None:
        return False
    for index, (argv, operator) in enumerate(parts[:-1]):
        if operator != '|' or parts[index + 1][0] not in (['sh'], ['bash']):
            continue
        program = posixpath.basename(argv[0])
        if not any(arg.startswith(('https://', 'http://')) for arg in argv[1:]):
            continue
        if program == 'curl':
            # Only the ordinary stdout form is recognized; output/header options
            # can turn the same pipeline into a file download or header probe.
            options = [arg for arg in argv[1:] if arg.startswith('-')]
            if all(arg in ('-s', '-S', '-sS', '-fsSL', '-fsS', '-f', '-L', '--silent', '--show-error', '--fail', '--location') for arg in options):
                return True
        if program == 'wget' and (any(argv[i:i + 2] == ['-O', '-'] for i in range(1, len(argv))) or '--output-document=-' in argv):
            options = [arg for arg in argv[1:] if arg.startswith('-')]
            if all(arg in ('-O', '-', '--output-document=-', '-q', '--quiet') for arg in options):
                return True
    return False


def destructive_targets(argv):
    if not argv or posixpath.basename(argv[0]) != 'rm':
        return []
    options, paths = True, []
    for arg in argv[1:]:
        if options and arg == '--':
            options = False
        elif options and arg.startswith('-'):
            if arg in ('--recursive', '--force', '--verbose', '--interactive', '--preserve-root', '--no-preserve-root'):
                continue
            elif arg.startswith('--') or not arg[1:] or any(c not in 'rRfivIdP' for c in arg[1:]):
                return None
        else:
            paths.append(arg)
    return paths


def destructive_argv(argv, roots, cwd):
    return any(path_match(p, roots, cwd) for p in destructive_targets(argv) or [])


def match_record(code, severity, *, rule_id=None, name='', condition=None, targets=None):
    return {'risk_code': code, 'severity': severity, 'id': rule_id or code,
            'name': name, 'condition': condition or {}, 'targets': targets or []}


def command_assessment(command, cwd, config, platform):
    if config.get('security') is not None:
        from .aidr_security_rules import assess_command
        return assess_command(command, cwd, config, platform)
    if not config['enabled']:
        return {'status': 'disabled', 'matches': [], 'unresolved_rules': []}
    text_rules = [rule for rule in config.get('custom_commands', []) if (rule['condition'].get('keywords') or rule['condition'].get('networks'))]
    if text_rules:
        remaining = [rule for rule in config['custom_commands'] if not (rule['condition'].get('keywords') or rule['condition'].get('networks'))]
        result = command_assessment(command, cwd, {**config, 'custom_commands': remaining}, platform) if remaining or config.get('command_rules', commands.LEGACY_COMMANDS) else {'status': 'unmatched', 'matches': [], 'unresolved_rules': []}
        for rule, state in commands.custom_matches(command, cwd, platform, text_rules):
            if state == 'matched':
                result['matches'].append(match_record('custom_command', rule['severity'], rule_id=rule['id'], name=rule['name'], condition=rule['condition']))
            elif state == 'unresolved':
                result['unresolved_rules'].append(rule['id'])
        result['status'] = 'matched' if result['matches'] else 'unresolved' if result['unresolved_rules'] or result['status'] == 'unresolved' else 'unmatched'
        return result
    if platform == 'windows':
        return windows_assessment(command, cwd, config)
    if platform not in ('linux', 'darwin') or '[REDACTED]' in command or parse(command) is None:
        return {'status': 'unresolved', 'matches': [], 'unresolved_rules': []}
    parts = parse(command)
    hits, unresolved = [], []
    enabled = config.get('command_rules', commands.LEGACY_COMMANDS)
    protected = catalog.roots({**config, 'platform': platform}, 'protected')
    if 'download_to_shell' in enabled and download_pipe(command):
        hits.append(match_record('download_to_shell', 'medium'))
    if 'destructive_command' in enabled:
        matched = [root for root in protected if any(destructive_argv(argv, [root], cwd) for argv, _ in parts)]
        if matched:
            hits.append(match_record('destructive_command', 'high', condition={'paths': [root['path'] if isinstance(root, dict) else root for root in matched]}))
        for argv, _ in parts:
            targets = destructive_targets(argv)
            if targets is None or (protected and not posixpath.isabs(cwd) and any(not posixpath.isabs(target) for target in targets)):
                unresolved.append('destructive_command')
    for argv, _ in parts:
        for code, checker in (('filesystem_format', commands.format_target), ('device_write', commands.write_target)):
            if code in enabled:
                state, target = checker(argv, platform)
                if state == 'matched':
                    hits.append(match_record(code, 'high', targets=[target]))
                elif state == 'unresolved':
                    unresolved.append(code)
        if 'protected_permissions' in enabled:
            state, targets = commands.permission_targets(argv)
            if state == 'matched':
                matched = [target for target in targets if path_match(target, protected, cwd)]
                if matched:
                    hits.append(match_record('protected_permissions', 'high', targets=matched))
                elif any(not posixpath.isabs(target) for target in targets) and not posixpath.isabs(cwd):
                    unresolved.append('protected_permissions')
            elif state == 'unresolved':
                unresolved.append('protected_permissions')
    for rule, state in commands.custom_matches(command, cwd, platform, config.get('custom_commands', [])):
        if state == 'matched':
            hits.append(match_record('custom_command', rule['severity'], rule_id=rule['id'], name=rule['name'], condition=rule['condition']))
        elif state == 'unresolved':
            unresolved.append(rule['id'])
    hits = list({dump(hit): hit for hit in hits}.values())
    return {'status': 'matched' if hits else 'unresolved' if unresolved else 'unmatched',
            'matches': hits, 'unresolved_rules': sorted(set(unresolved))}


def windows_assessment(command, cwd, config):
    parts = windows_commands.parse(command)
    if parts is None:
        return {'status': 'unresolved', 'matches': [], 'unresolved_rules': []}
    hits, unresolved = [], []
    protected = catalog.roots({**config, 'platform': 'windows'}, 'protected')
    for argv, _ in parts:
        code, state, targets = windows_commands.builtin(argv)
        condition = {'executable': argv[0]}
        if code not in config.get('command_rules', commands.LEGACY_COMMANDS):
            continue
        if state == 'matched' and code in ('destructive_command', 'protected_permissions'):
            resolved = [(target, windows_commands.target_path(target, cwd)) for target in targets]
            condition['paths'] = [root['path'] if isinstance(root, dict) else root for root in protected
                                  if any(path and path_match(path, [root], windows=True) for _, path in resolved)]
            targets = [target for target, path in resolved if path and path_match(path, protected, windows=True)]
            if any(path is None for _, path in resolved):
                unresolved.append(code)
            state = 'matched' if targets else 'unmatched'
        if state == 'matched':
            hits.append(match_record(code, 'high', condition=condition, targets=targets))
        elif state == 'unresolved':
            unresolved.append(code)
    for rule in config.get('custom_commands', []):
        if not rule['enabled'] or 'windows' not in rule['platforms']:
            continue
        state = windows_commands.custom_match(rule['condition'], parts, cwd)
        if state == 'matched':
            hits.append(match_record('custom_command', rule['severity'], rule_id=rule['id'], name=rule['name'], condition=rule['condition']))
        elif state == 'unresolved':
            unresolved.append(rule['id'])
    hits = list({dump(hit): hit for hit in hits}.values())
    return {'status': 'matched' if hits else 'unresolved' if unresolved else 'unmatched',
            'matches': hits, 'unresolved_rules': sorted(set(unresolved))}


def path_matches(value, config, category, cwd='', windows=False):
    code = 'sensitive_path_read' if category == 'sensitive' else 'protected_path_change'
    severity = 'medium' if category == 'sensitive' else 'high'
    matches = []
    if 'security_roots' in config:
        return [match_record(code, severity, condition={'paths': [root['path'] if isinstance(root, dict) else root]}, targets=[value])
                for root in config['security_roots'] if path_match(value, [root], cwd, windows)]
    for root in config[category + '_paths']:
        if path_match(value, [root], cwd, windows):
            identifier = 'path_' + hashlib.sha256((category + root).encode()).hexdigest()[:16]
            matches.append(match_record(code, severity, rule_id=identifier,
                condition={'paths': [root]}, targets=[value]))
    for item in catalog.CATALOG:
        if item['id'] not in config.get('builtin_ids', []) or item['category'] != category:
            continue
        specs = [spec for spec in item['paths'] if spec['os'] == config.get('platform', 'windows' if windows else 'linux')]
        for spec in specs:
            if path_match(value, [spec], cwd, windows):
                matches.append(match_record(code, severity, rule_id=item['id'],
                    condition={'paths': [spec['path']], 'directory': spec['directory']}, targets=[value]))
    return matches


def detect_matches(event, config, *, windows=False, system=False):
    if config.get('security') is not None:
        from .aidr_security_rules import detect
        return detect(event, config, windows=windows, system=system)
    hits = []
    if not config['enabled']:
        return hits
    platform = config.get('platform', 'windows' if windows else 'linux')
    if system:
        if event.get('activity_origin') == 'client_probe':
            return hits
        if event.get('kind') == 'authorization' and event.get('decision') == 'deny':
            hits.append(match_record('system_access_denied', 'medium'))
        if event.get('relation') in ('direct', 'inherited') and not event.get('paths_truncated'):
            if event.get('kind') == 'file':
                for key in ('path', 'destination_path'):
                    hits.extend(path_matches(event.get(key, ''), config, 'protected', windows=windows))
            if event.get('kind') == 'process' and event.get('transition') == 'exec' and not event.get('argv_truncated'):
                hits.extend(command_assessment(shlex.join(event.get('argv') or []), event.get('cwd', ''), config, platform)['matches'])
        return hits
    if event.get('kind') not in ('tool.pre', 'tool_call'):
        return hits
    if (event.get('control_decision') or {}).get('decision') == 'deny':
        hits.append(match_record('tool_policy_denied', 'medium'))
    behavior = event.get('behavior') or {}
    if behavior.get('truncated'):
        return hits
    for action in behavior.get('actions') or []:
        category = action.get('category')
        cwd = action.get('cwd') or (event.get('context') or {}).get('cwd', '')
        if category == 'command':
            hits.extend(command_assessment(action.get('command', ''), cwd, config, platform)['matches'])
        if category in ('file_read', 'file_write', 'file_edit', 'file_rename', 'patch'):
            for target in action.get('targets') or []:
                hits.extend(path_matches(target.get('value', ''), config, 'sensitive' if category == 'file_read' else 'protected', cwd, windows))
    return list({dump(hit): hit for hit in hits}.values())


def severities(matches):
    return {code: 'high' if any(hit['severity'] == 'high' for hit in matches if hit['risk_code'] == code) else 'medium'
            for code in {hit['risk_code'] for hit in matches}}


def detect(event, config, *, windows=False, system=False):
    return severities(detect_matches(event, config, windows=windows, system=system))


def evidence_group(db, source, row):
    """Only same-source, validated identities may contribute an outcome."""
    raw = json.loads(row.payload_json)
    if source == 'system':
        if raw.get('kind') not in ('file', 'authorization', 'process'):
            return None
        return row, raw, [row], raw.get('result', 'unknown'), []
    if source == 'logs':
        if raw.get('kind') not in ('tool_call', 'tool_result') or raw.get('completion'):
            return None
        op = db.query(AidrOperation).filter_by(client_id=row.client_id, operation_key=operation_key(row.client_id, raw), expired_at=None).first()
        if not op:
            return None
        view = json.loads(op.payload_json)
        call = view.get('call')
        if not call:
            return None
        ids = [e['logical_event_id'] for e in (call, view.get('result')) if e]
        rows = db.query(AidrEvent).filter(AidrEvent.client_id == row.client_id, AidrEvent.logical_id.in_(ids), AidrEvent.expired_at.is_(None)).all()
        anchor = next((r for r in rows if r.logical_id == call['logical_event_id']), None)
        if not anchor:
            return None
        limitations = [k for k in ('conflicting_evidence', 'evidence_truncated') if view.get(k)]
        return anchor, call, rows, op.result_status, limitations
    from .aidr_hook_queries import related_records
    event = raw['event']
    if event.get('kind') not in ('tool.pre', 'tool.post', 'tool.failure'):
        return None
    relation, rows = related_records(db, row.client_id, row)
    rows = rows or [row]
    calls = [r for r in rows if json.loads(r.payload_json)['event']['kind'] == 'tool.pre']
    if not calls:
        return None
    anchor = row if event['kind'] == 'tool.pre' else calls[0]
    result = 'unknown'
    limitations = []
    posts = [r for r in rows if json.loads(r.payload_json)['event']['kind'] in ('tool.post', 'tool.failure')]
    turns = {json.loads(r.payload_json)['event'].get('turn_id') or '' for r in rows}
    if len(calls) == len(posts) == 1 and not (event['agent'] == 'codex' and '' in turns):
        post = next((json.loads(r.payload_json)['event'] for r in rows if r.id != anchor.id), {})
        result = (post.get('behavior') or {}).get('status', 'unknown')
    else:
        limitations.append('conflicting_evidence' if len(calls) > 1 or len(posts) > 1 else 'result_unverified')
        if relation['truncated']:
            limitations.append('evidence_truncated')
    return anchor, json.loads(anchor.payload_json)['event'], rows, result, limitations


def process(db, source, row):
    group = evidence_group(db, source, row)
    if group is None:
        return
    anchor, event, evidence, outcome, limitations = group
    if source == 'hooks' and 'conflicting_evidence' in limitations:
        anchors = [r.id for r in evidence if json.loads(r.payload_json)['event']['kind'] == 'tool.pre']
        db.query(RiskFinding).filter(RiskFinding.client_id == row.client_id, RiskFinding.source == source,
            RiskFinding.anchor_id.in_(anchors)).update({'result_status': 'conflicting_evidence',
                'limitations': dump(limitations), 'updated_at': datetime.utcnow()}, synchronize_session=False)
        outcome = 'conflicting_evidence'
    existing = db.query(RiskFinding).filter_by(client_id=row.client_id, source=source, anchor_id=anchor.id).all()
    revision, config = configuration(db, row.client_id)
    matches = detect_matches(event, config, windows=config['platform'] == 'windows', system=source == 'system')
    hits = severities(matches)
    # Later evidence updates existing conclusions with their original rule version.
    if row.id == anchor.id and not existing:
        control = event.get('control_decision') or {}
        raw = json.loads(anchor.payload_json)
        occurred = event.get('observed_at') or (event.get('time_ns') if source == 'system' else raw.get('received_at'))
        if source == 'system' and occurred:
            from datetime import timezone
            occurred = datetime.fromtimestamp(int(occurred) / 1e9, timezone.utc).isoformat()
        for code, severity in hits.items():
            ident = hashlib.sha256(dump([row.client_id, source, anchor.id, code]).encode()).hexdigest()
            finding = RiskFinding(id=ident, client_id=row.client_id, source=source, anchor_id=anchor.id,
                agent=event.get('agent', ''), session_id=event.get('session_id', ''), tool=event.get('tool', ''),
                risk_code=code, severity=severity, config_revision=revision, rule_version=RULE_VERSION,
                policy_revision=str(control.get('policy_revision') or event.get('revision') or ''),
                rule_ids=dump(control.get('matched_rule_ids') or ([event['rule_id']] if event.get('rule_id') else [])),
                occurred_at=stamp(occurred) if occurred else anchor.received_at.isoformat() + '+00:00',
                time_basis='received' if source == 'hooks' else 'collection' if event.get('observed_at_source') == 'collection' else 'observed')
            db.add(finding)
            db.add(RiskDetectionContext(finding_id=ident, payload=dump({
                'client_revision': revision, 'global_revision': config['global_revision'],
                'rules_mode': config['rules_mode'], 'catalog_version': catalog.VERSION,
                'rule_version': RULE_VERSION,
                'matches': [hit for hit in matches if hit['risk_code'] == code]})))
            existing.append(finding)
    for finding in existing:
        behavior = event.get('behavior') or {}
        limits = limitations + [name for name in ('redacted', 'truncated') if behavior.get(name)]
        finding.result_status = outcome
        finding.control_status = ('deny_reported' if (event.get('control_decision') or {}).get('decision') == 'deny'
            else 'deny_responded' if source == 'system' and event.get('decision') == 'deny' and event.get('result') == 'responded'
            else 'deny_failed' if source == 'system' and event.get('decision') == 'deny' and event.get('result') == 'failed' else 'unknown')
        finding.limitations = dump(limits)
        finding.control_code = (event.get('control_decision') or {}).get('code') or event.get('reason_code', '')
        finding.updated_at = datetime.utcnow()
        db.flush()
        for item in evidence:
            db.execute(insert(RiskEvidence).values(finding_id=finding.id, source=source, record_id=item.id,
                digest=item.content_hash or hashlib.sha256(item.payload_json.encode()).hexdigest()).on_conflict_do_nothing())


def advance(db, limit=50):
    # Serialize cursor and findings in the same short transaction across workers.
    db.connection().exec_driver_sql('UPDATE aidr_risk_cursors SET position=position WHERE 0')
    more = False
    for source, model in SOURCES.items():
        cursor = db.get(RiskCursor, source)
        if cursor is None:
            cursor = RiskCursor(source=source, position=0)
            db.add(cursor)
            db.flush()
        rows = db.query(model).filter(model.id > cursor.position).order_by(model.id).limit(limit).all()
        for row in rows:
            if row.expired_at is None:
                process(db, source, row)
            cursor.position = row.id
        cursor.checked_at = datetime.utcnow()
        more |= len(rows) == limit
    db.commit()
    return more


def summary(db, client_id):
    progress = []
    for source, model in SOURCES.items():
        cursor = db.get(RiskCursor, source)
        ceiling = db.query(func.max(model.id)).filter_by(client_id=client_id).scalar() or 0
        progress.append({'source': source, 'caught_up': cursor is not None and cursor.position >= ceiling,
                         'fresh': cursor is not None and (datetime.utcnow() - cursor.checked_at).total_seconds() <= 30,
                         'checked_at': cursor.checked_at.isoformat() + 'Z' if cursor else None})
    counts = db.query(RiskFinding.severity, func.count()).filter_by(client_id=client_id).group_by(RiskFinding.severity).all()
    dispositions = db.query(RiskFinding.disposition, func.count()).filter_by(client_id=client_id).group_by(RiskFinding.disposition).all()
    _, config = configuration(db, client_id)
    agents = [row[0] for row in db.query(RiskFinding.agent).filter(
        RiskFinding.client_id == client_id, RiskFinding.agent != '').distinct().order_by(RiskFinding.agent).all()]
    return {'counts': dict(counts), 'dispositions': dict(dispositions), 'progress': progress, 'scope': 'retained_evidence',
            'agents': agents,
            'rules_mode': config['rules_mode'],
            'enabled': config['enabled'], 'sensitive_path_count': len(catalog.roots(config, 'sensitive')),
            'protected_path_count': len(catalog.roots(config, 'protected'))}


def risk_products(agent_type):
    """Resolve an installation type to its recorded product identities."""
    from .aidr_adapters import ADAPTERS
    from .aidr_products import BY_ID
    inventory_type = agent_type.lower()
    products = {a.id for a in ADAPTERS.values() if (a.inventory_type or a.id) == inventory_type}
    products |= {a.id for a in ADAPTERS.values() if a.log_entry and a.log_entry in products}
    if inventory_type in BY_ID:
        products.add(inventory_type)
    return sorted(products)


def asset_summaries(db, assets):
    """Count visible device/product pairs once per asset, without instance attribution."""
    from .schemas import AgentRiskScope, AgentRiskSummary

    client_ids = {instance.client_id for asset in assets for instance in asset.instances}
    default_enabled = global_configuration(db)[1]['enabled']
    detection = {cid: 'pending' if default_enabled else 'disabled' for cid in client_ids}
    latest = db.query(RiskConfig.client_id, func.max(RiskConfig.revision).label('revision')).filter(
        RiskConfig.client_id.in_(client_ids)).group_by(RiskConfig.client_id).subquery()
    for cid, payload in db.query(RiskConfig.client_id, RiskConfig.payload).join(latest,
            (RiskConfig.client_id == latest.c.client_id) & (RiskConfig.revision == latest.c.revision)):
        config = json.loads(payload)
        mode = config.get('enabled_mode')
        enabled = default_enabled if mode == 'inherit' else mode == 'enabled' if mode else config.get('enabled', True)
        detection[cid] = 'pending' if enabled else 'disabled'
    seen, pending = set(), set()
    for source, model in SOURCES.items():
        cursor = db.get(RiskCursor, source)
        for cid in client_ids:
            # A single-client MAX uses the index endpoint instead of scanning grouped history.
            ceiling = db.query(func.max(model.id)).filter(model.client_id == cid).scalar()
            if ceiling is None:
                continue
            seen.add(cid)
            if cursor is None or cursor.position < ceiling or (datetime.utcnow() - cursor.checked_at).total_seconds() > 30:
                pending.add(cid)
    for cid in seen - pending:
        if detection[cid] != 'disabled':
            detection[cid] = 'ready'
    grouped = {}
    if client_ids:
        for client_id, agent, severity, disposition, count, latest in db.query(
            RiskFinding.client_id, RiskFinding.agent, RiskFinding.severity, RiskFinding.disposition,
            func.count(), func.max(RiskFinding.occurred_at),
        ).filter(RiskFinding.client_id.in_(client_ids)).group_by(
            RiskFinding.client_id, RiskFinding.agent, RiskFinding.severity, RiskFinding.disposition,
        ):
            grouped.setdefault((client_id, agent), {})[(severity, disposition)] = (count, latest)
    for asset in assets:
        scopes, unmapped = {}, 0
        for instance in asset.instances:
            products = risk_products(instance.agent_type)
            if not products:
                unmapped += 1
            for product in sorted(products):
                key = (instance.client_id, product)
                counts = grouped.get(key, {})
                scopes[key] = AgentRiskScope(
                    detection_status=detection[instance.client_id],
                    client_id=instance.client_id, client_name=instance.client_name, agent=product,
                    high=sum(value[0] for key, value in counts.items() if key[0] == 'high'),
                    medium=sum(value[0] for key, value in counts.items() if key[0] == 'medium'),
                    open_count=sum(value[0] for key, value in counts.items() if key[1] == 'open'),
                    latest_at=max((value[1] for value in counts.values()), default=None),
                )
        high = sum(scope.high for scope in scopes.values())
        medium = sum(scope.medium for scope in scopes.values())
        asset.risk_summary = AgentRiskSummary(
            detection_disabled=sum(detection[cid] == 'disabled' for cid in {scope.client_id for scope in scopes.values()}),
            detection_pending=sum(detection[cid] == 'pending' for cid in {scope.client_id for scope in scopes.values()}),
            status='product_only' if scopes else 'unmapped' if asset.instances else 'no_instance',
            high=high, medium=medium, highest_severity='high' if high else 'medium' if medium else None,
            open_count=sum(scope.open_count for scope in scopes.values()),
            latest_at=max((scope.latest_at for scope in scopes.values() if scope.latest_at), default=None),
            unmapped_instances=unmapped, scopes=list(scopes.values()),
        )


def present(row):
    return {name: getattr(row, name) for name in ('id', 'source', 'agent', 'session_id', 'tool', 'risk_code',
        'severity', 'config_revision', 'rule_version', 'policy_revision', 'occurred_at', 'time_basis', 'result_status', 'control_status', 'control_code', 'disposition', 'disposition_revision')} | {
        'rule_ids': json.loads(row.rule_ids), 'limitations': json.loads(row.limitations),
        'detected_at': row.detected_at.isoformat() + 'Z', 'updated_at': row.updated_at.isoformat() + 'Z',
        'attribution_status': 'product_only' if row.agent else 'device_only'}


def present_rows(db, rows):
    from .aidr_hook_control import HookAttemptReportRow
    anchors = [row.anchor_id for row in rows if row.source == 'hooks']
    reports = {}
    if anchors:
        receipts = db.query(AidrHookEvent.id, AidrHookEvent.client_id, HookAttemptReportRow.payload).join(
            HookAttemptReportRow,
            (HookAttemptReportRow.client_id == AidrHookEvent.client_id)
            & (HookAttemptReportRow.stream_id == AidrHookEvent.stream_id)
            & (HookAttemptReportRow.event_id == AidrHookEvent.event_id),
        ).filter(AidrHookEvent.id.in_(anchors)).all()
        reports = {(anchor, client): json.loads(payload) for anchor, client, payload in receipts}
    result = []
    for row in rows:
        view = present(row)
        receipt = reports.get((row.anchor_id, row.client_id)) if row.source == 'hooks' else None
        if receipt:
            view['control_status'] = 'approval_consumed' if receipt['state'] == 'consumed' else 'deny_reported'
            view['control_code'] = receipt['code']
        result.append(view)
    return result


async def detection_loop():
    from .sqlite_db import SessionLocal
    from .services.gateway_db import run_sync
    from .services.aidr_ingest import admission
    def tick():
        with SessionLocal() as db:
            return advance(db)
    while True:
        try:
            async with admission():
                more = await run_sync(tick)
        except Exception:
            logging.getLogger(__name__).exception('aidr_risk_detection_failed')
            more = False
        await asyncio.sleep(0.2 if more else 5)
