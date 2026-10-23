"""Incremental, evidence-backed runtime findings. No execution authority."""
import asyncio
import hashlib
import json
import logging
import ntpath
import posixpath
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Column, DateTime, Integer, String, Text, Index, UniqueConstraint, func
from sqlalchemy.dialects.sqlite import insert

from .sqlite_db import Base
from .aidr_models import AidrEvent, AidrHookEvent, AidrOperation
from .aidr_enforcement import AidrRuntimeRecord
from .aidr_command_rules import parse
from .aidr_operations import operation_key, stamp

RULE_VERSION = 'runtime-risk/1'
SOURCES = {'hooks': AidrHookEvent, 'logs': AidrEvent, 'system': AidrRuntimeRecord}
RISK_CODES = ('destructive_command', 'download_to_shell', 'sensitive_path_read',
              'protected_path_change', 'tool_policy_denied', 'system_access_denied')


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


def configuration(db, client_id):
    row = db.query(RiskConfig).filter_by(client_id=client_id).order_by(RiskConfig.revision.desc()).first()
    return (row.revision, json.loads(row.payload)) if row else (0, DetectionConfig().model_dump(exclude={'expected_revision'}))


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


def destructive_argv(argv, roots, cwd):
    if not argv or posixpath.basename(argv[0]) != 'rm':
        return False
    recursive, options, paths = False, True, []
    for arg in argv[1:]:
        if options and arg == '--':
            options = False
        elif options and arg.startswith('-'):
            if arg == '--recursive':
                recursive = True
            elif arg in ('--force', '--verbose', '--interactive', '--preserve-root', '--no-preserve-root'):
                continue
            elif arg.startswith('--') or not arg[1:] or any(c not in 'rRfivIdP' for c in arg[1:]):
                return False
            else:
                recursive |= 'r' in arg or 'R' in arg
        else:
            paths.append(arg)
    return recursive and any(path_match(p, roots, cwd) for p in paths)


def detect(event, config, *, windows=False, system=False):
    """Return stable codes; unsupported/truncated syntax never becomes a match."""
    hits = {}
    if not config['enabled']:
        return hits
    if system:
        if event.get('activity_origin') == 'client_probe':
            return hits
        if event.get('kind') == 'authorization' and event.get('decision') == 'deny':
            hits['system_access_denied'] = 'medium'
        if event.get('relation') in ('direct', 'inherited') and not event.get('paths_truncated'):
            if event.get('kind') == 'file' and any(path_match(event.get(k, ''), config['protected_paths'], windows=windows) for k in ('path', 'destination_path')):
                hits['protected_path_change'] = 'high'
            if (event.get('kind') == 'process' and event.get('transition') == 'exec'
                    and not event.get('argv_truncated')
                    and destructive_argv(event.get('argv') or [], config['protected_paths'], event.get('cwd', ''))):
                hits['destructive_command'] = 'high'
        return hits
    if event.get('kind') not in ('tool.pre', 'tool_call'):
        return hits
    if (event.get('control_decision') or {}).get('decision') == 'deny':
        hits['tool_policy_denied'] = 'medium'
    behavior = event.get('behavior') or {}
    if behavior.get('truncated'):
        return hits
    for action in behavior.get('actions') or []:
        category, command = action.get('category'), action.get('command', '')
        if category == 'command' and not windows and '[REDACTED]' not in command:
            parts = parse(command)
            if parts is not None:
                if download_pipe(command):
                    hits['download_to_shell'] = 'medium'
                if any(destructive_argv(argv, config['protected_paths'], action.get('cwd', '')) for argv, _ in parts):
                    hits['destructive_command'] = 'high'
        if category in ('file_read', 'file_write', 'file_edit', 'file_rename', 'patch'):
            reading = category == 'file_read'
            roots = config['sensitive_paths' if reading else 'protected_paths']
            cwd = action.get('cwd') or (event.get('context') or {}).get('cwd', '')
            if any(path_match(t.get('value', ''), roots, cwd, windows) for t in action.get('targets') or []):
                hits['sensitive_path_read' if reading else 'protected_path_change'] = 'medium' if reading else 'high'
    return hits


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
    from .models import ManagedClient
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
    client = db.get(ManagedClient, row.client_id)
    hits = detect(event, config, windows=bool(client and client.os == 'windows'), system=source == 'system')
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
    return {'counts': dict(counts), 'dispositions': dict(dispositions), 'progress': progress, 'scope': 'retained_evidence',
            'enabled': config['enabled'], 'sensitive_path_count': len(config['sensitive_paths']),
            'protected_path_count': len(config['protected_paths'])}


def asset_summaries(db, assets):
    """Count visible device/product pairs once per asset, without instance attribution."""
    from .aidr_adapters import ADAPTERS
    from .aidr_products import BY_ID
    from .schemas import AgentRiskScope, AgentRiskSummary

    client_ids = {instance.client_id for asset in assets for instance in asset.instances}
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
            inventory_type = instance.agent_type.lower()
            products = {a.id for a in ADAPTERS.values() if (a.inventory_type or a.id) == inventory_type}
            products |= {a.id for a in ADAPTERS.values() if a.log_entry and a.log_entry in products}
            if inventory_type in BY_ID:
                products.add(inventory_type)
            if not products:
                unmapped += 1
            for product in sorted(products):
                key = (instance.client_id, product)
                counts = grouped.get(key, {})
                scopes[key] = AgentRiskScope(
                    client_id=instance.client_id, client_name=instance.client_name, agent=product,
                    high=sum(value[0] for key, value in counts.items() if key[0] == 'high'),
                    medium=sum(value[0] for key, value in counts.items() if key[0] == 'medium'),
                    open_count=sum(value[0] for key, value in counts.items() if key[1] == 'open'),
                    latest_at=max((value[1] for value in counts.values()), default=None),
                )
        high = sum(scope.high for scope in scopes.values())
        medium = sum(scope.medium for scope in scopes.values())
        asset.risk_summary = AgentRiskSummary(
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
