"""P2 control plane: existing device credentials and device visibility apply."""
import hashlib
import base64
import json
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives import serialization

from .. import auth, models
from ..aidr_enforcement import (Strict, PolicyInput, AidrEnforcementRevision, AidrRuntimeRecord,
                                AidrResponseCommand, canonical, create_snapshot, latest, sign)
from ..sqlite_db import get_db
from ..aidr_rule_preview import SystemRulePreview, preview_system
from .aidr import runtime_device, fail
from .clients import _client_or_404, _ensure_visible, _operation

router = APIRouter(prefix='/v1/clients/{client_id}/aidr/enforcement', tags=['aidr-enforcement'])
_AUTO_RENEW_ACTOR = 'system:auto-renew'
_AUTO_RENEW_WINDOW_SECONDS = 6 * 60 * 60


def latest_configuration(db: Session, client_id: str):
    return db.query(AidrEnforcementRevision).filter_by(client_id=client_id).filter(
        AidrEnforcementRevision.created_by != _AUTO_RENEW_ACTOR
    ).order_by(AidrEnforcementRevision.revision.desc()).first()


def renew_if_needed(db: Session, client_id: str, row):
    """Refresh an unchanged signed policy lease for an authenticated device."""
    if row is None:
        return None
    try:
        current = json.loads(row.policy_json)
        issued_at = int(current['issued_at'])
        expires_at = int(current['expires_at'])
        lifetime = expires_at - issued_at
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return row
    now = int(time.time())
    if not current.get('agent_executables') or lifetime < 60 or lifetime > 30 * 86400:
        return row
    renew_window = min(_AUTO_RENEW_WINDOW_SECONDS, lifetime // 4)
    if expires_at - now > renew_window:
        return row

    body = PolicyInput(
        expected_revision=str(row.revision),
        lifetime_seconds=lifetime,
        unknown_actor_action=current['unknown_actor_action'],
        expired_action=current['expired_action'],
        agent_executables=current['agent_executables'],
        rules=current['rules'],
    )
    value = create_snapshot(client_id, body, row.revision + 1)
    envelope = sign(value)
    renewed = AidrEnforcementRevision(
        client_id=client_id,
        revision=row.revision + 1,
        policy_json=canonical(value),
        envelope_json=canonical(envelope),
        created_by=_AUTO_RENEW_ACTOR,
        created_at=now_text(),
    )
    db.add(renewed)
    _operation(db, SimpleNamespace(username=_AUTO_RENEW_ACTOR), 'aidr.enforcement.renew', client_id,
               canonical({'from_revision': str(row.revision), 'revision': value['revision'],
                          'expires_at': value['expires_at']}))
    try:
        db.commit()
        return renewed
    except IntegrityError:
        # Another authenticated request may have renewed the same revision.
        db.rollback()
        return latest(db, client_id)


@router.get('/bootstrap')
def collection_bootstrap(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    """Authenticated first-install trust bootstrap; never returns signing secrets."""
    from ..aidr_enforcement import signing_key
    from ..client_governance import policy_view
    runtime_device(db, client_id, authorization, request, 'aidr:heartbeat')
    configured = policy_view(db, client_id)
    target = configured['runtime_governance']
    if not target['enabled'] or not (target.get('channels') or {}).get('system', False):
        fail(409, 'system_collection_disabled', '平台未启用系统采集', 'System collection is disabled by platform policy')
    row = renew_if_needed(db, client_id, latest(db, client_id))
    policy = json.loads(row.policy_json) if row else None
    if not policy or not policy['agent_executables'] or int(policy['expires_at']) <= int(time.time()):
        fail(409, 'system_policy_required', '请在平台配置有效的系统进程归属策略', 'Configure a valid system process attribution policy on the platform')
    key = signing_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return dict(public_key=base64.b64encode(key).decode(), revision=str(row.revision), runtime_policy_version=configured['runtime_governance_version'], mode=(target.get('modes') or {}).get('system') or 'audit')


def visible(db, client_id, user):
    _ensure_visible(_client_or_404(db, client_id), user)


def now_text():
    return datetime.now(timezone.utc).isoformat()


@router.post('/policy/preview')
def system_rule_preview(client_id: str, body: SystemRulePreview, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    return preview_system(body)


@router.get('/policy')
def get_policy(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    row = latest(db, client_id)
    configured = latest_configuration(db, client_id)
    return dict(revision=str(row.revision) if row else '0', policy=json.loads(row.policy_json) if row else None,
                configuration_revision=str(configured.revision) if configured else '0',
                created_by=configured.created_by if configured else None, created_at=configured.created_at if configured else None,
                can_edit=user.role in ('admin','super_admin'))


@router.get('/history')
def history(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db,client_id,user)
    rows=db.query(AidrEnforcementRevision).filter_by(client_id=client_id).filter(
        AidrEnforcementRevision.created_by != _AUTO_RENEW_ACTOR
    ).order_by(AidrEnforcementRevision.revision.desc()).limit(30).all()
    return dict(items=[dict(revision=str(r.revision),policy=json.loads(r.policy_json),created_at=r.created_at,created_by=r.created_by) for r in rows])


@router.get('/status')
def runtime_status(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    client = _client_or_404(db, client_id)
    _ensure_visible(client, user)
    platform = (client.os or '').lower()
    platform_support = 'macos_endpoint_security' if platform in {'darwin', 'macos'} else 'unsupported_platform' if platform in {'windows', 'linux'} else 'unreported_platform'
    latest_policy=latest(db,client_id)
    row=db.query(AidrRuntimeRecord).filter_by(client_id=client_id,kind='health',expired_at=None).order_by(AidrRuntimeRecord.id.desc()).first()
    record=json.loads(row.payload_json) if row else None
    # Backfilled old heartbeats are history, not evidence of current protection.
    fresh=bool(row and abs(time.time()-int(record['time_ns'])/1e9)<10 and (datetime.now(timezone.utc)-datetime.fromisoformat(row.received_at)).total_seconds()<10)
    state='unknown' if not row else 'stale' if not fresh else 'active' if record['reason_code']=='aidr_enforcement_active' and record['gaps']=='0' else 'degraded'
    if fresh and record['reason_code']=='aidr_enforcement_collection_only' and record['gaps']=='0':state='collecting'
    if record and record['reason_code']=='aidr_enforcement_stopped':state='stopped'
    if record and record['reason_code']=='aidr_enforcement_native_exit':state='failed'
    configured_roots = json.loads(latest_policy.policy_json).get('agent_executables', []) if latest_policy else []
    return dict(platform=platform, platform_support=platform_support, state=state,target_revision=str(latest_policy.revision) if latest_policy else '0',reported_revision=record['revision'] if record else None,
                configured_roots=configured_roots, health=record,last_received_at=row.received_at if row else None,can_edit=user.role in ('admin','super_admin'))


def target_context(db, client_id, user):
    status = runtime_status(client_id, db, user)
    return status, db, client_id


def target_reason(target, context):
    status, db, client_id = context
    if status['state'] == 'collecting':
        return 'enforcement_control_not_enabled'
    if status['state'] != 'active':
        return 'enforcement_executor_inactive'
    health = status['health']
    if any(target[k] != health[k] for k in ('boot_id', 'monitor_id')):
        return 'enforcement_monitor_changed'
    query = db.query(AidrRuntimeRecord).filter_by(client_id=client_id, monitor_id=target['monitor_id'], kind='process')
    for field, value in target['process'].items():
        query = query.filter(func.json_extract(AidrRuntimeRecord.payload_json, '$.process.' + field) == value)
    # Decimal strings preserve uint64 precision. Order by source sequence, not arrival order.
    row = query.order_by(func.length(AidrRuntimeRecord.sequence).desc(), AidrRuntimeRecord.sequence.desc()).first()
    known = json.loads(row.payload_json) if row else None
    if not known or known['boot_id'] != target['boot_id'] or known['relation'] == 'unknown':
        return 'enforcement_target_unverified'
    if known['transition'] == 'exit':
        return 'enforcement_target_exited'
    return ''


@router.post('/policy')
def publish(client_id: str, body: PolicyInput, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    if user.role not in ('admin', 'super_admin'):
        fail(403, 'enforcement_admin_required', '需要管理员权限', 'Administrator role required')
    for _ in range(3):
        current = latest(db, client_id)
        previous = current.revision if current else 0
        configured = latest_configuration(db, client_id)
        configuration_revision = str(configured.revision) if configured else '0'
        expected = body.expected_configuration_revision
        conflict = expected != configuration_revision if expected is not None else body.expected_revision != str(previous)
        if conflict:
            fail(409, 'enforcement_revision_conflict', '采集配置已被修改，请刷新后重新编辑', 'Collection configuration changed; refresh before editing again')
        value = create_snapshot(client_id, body, previous + 1)
        envelope = sign(value)
        if len(canonical(envelope).encode()) > 65536:
            fail(422, 'enforcement_policy_too_large', '策略超过大小限制', 'Policy exceeds the size limit')
        row = AidrEnforcementRevision(client_id=client_id, revision=previous + 1, policy_json=canonical(value),
                                      envelope_json=canonical(envelope), created_by=user.username, created_at=now_text())
        db.add(row)
        _operation(db, user, 'aidr.enforcement.publish', client_id, canonical({'revision':value['revision'], 'rule_count':len(body.rules)}))
        try:
            db.commit()
            return dict(revision=value['revision'], configuration_revision=value['revision'], policy=value,
                        created_by=row.created_by, created_at=row.created_at)
        except IntegrityError:
            db.rollback()
            # A concurrent lease renewal may advance the signed revision while
            # the administrator's configuration is still current.
            if expected is None:
                break
    fail(409, 'enforcement_revision_conflict', '采集配置已被修改，请刷新后重新编辑', 'Collection configuration changed; refresh before editing again')


@router.get('/snapshot')
def snapshot(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, 'aidr:heartbeat')
    row = latest(db, client_id)
    return dict(envelope=json.loads(row.envelope_json) if row else None)


class Identity(Strict):
    pid: str = Field(pattern=r'^[1-9][0-9]{0,9}$')
    pidversion: str = Field(pattern=r'^(0|[1-9][0-9]{0,9})$')
    start_us: str = Field(pattern=r'^[1-9][0-9]{0,19}$')

    @model_validator(mode='after')
    def limits(self):
        if int(self.pid) > 2147483647 or int(self.pidversion) > 4294967295 or int(self.start_us) > 18446744073709551615:
            raise ValueError('aidr_enforcement_identity_invalid')
        return self


class Target(Strict):
    boot_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    monitor_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    process: Identity

    @field_validator('boot_id', 'monitor_id')
    @classmethod
    def uuid_value(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError('aidr_enforcement_uuid_invalid')
        return value


class NetworkSnapshot(Strict):
    source: str = Field(pattern=r'^libproc_snapshot$')
    observation_id: str = Field(pattern=r'^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$')
    protocol: str = Field(pattern=r'^(tcp|udp)$')
    direction: str = Field(pattern=r'^unknown$')
    local_ip: str = Field(max_length=45)
    local_port: int = Field(ge=0, le=65535)
    remote_ip: str = Field(max_length=45)
    remote_port: int = Field(ge=1, le=65535)
    state: str = Field(pattern=r'^(unknown|closed|syn_sent|syn_received|established|close_wait|fin_wait_1|closing|last_ack|fin_wait_2|time_wait)$')

    @field_validator('local_ip', 'remote_ip')
    @classmethod
    def address(cls, value):
        import ipaddress
        ipaddress.ip_address(value)
        return value

    @model_validator(mode='after')
    def transport_state(self):
        if self.protocol == 'udp' and self.state != 'unknown':
            raise ValueError('aidr_network_state_invalid')
        return self


class NetworkHealth(Strict):
    source: str = Field(pattern=r'^libproc_snapshot$')
    state: str = Field(pattern=r'^(starting|sampled|waiting_for_process|partial|permission_denied|stopped)$')
    sampled_at_ns: str = Field(pattern=r'^(0|[1-9][0-9]{0,19})$')

    @field_validator('sampled_at_ns')
    @classmethod
    def timestamp(cls, value):
        if int(value) > 18446744073709551615:
            raise ValueError('aidr_enforcement_integer_invalid')
        return value


class Record(Target):
    network: NetworkSnapshot | None = None
    network_health: NetworkHealth | None = None
    detail_schema: int | None = Field(default=None, ge=1, le=1)
    schema_version: int = Field(default=1, ge=1, le=1)
    sequence: str = Field(pattern=r'^[1-9][0-9]{0,19}$')
    time_ns: str = Field(pattern=r'^[1-9][0-9]{0,19}$')
    kind: str = Field(pattern=r'^(network|process|file|authorization|health|policy|response)$')
    root: Identity | None = None
    relation: str = Field(default='unknown', pattern=r'^(direct|inherited|unknown)$')
    transition: str = Field(default='', pattern=r'^$|^(fork|exec|exit|observed)$')
    path: str = Field(default='', max_length=1023)
    revision: str = Field(default='0', pattern=r'^(0|[1-9][0-9]{0,19})$')
    rule_id: str = Field(default='', pattern=r'^[A-Za-z0-9_-]{0,64}$')
    decision: str = Field(default='unknown', pattern=r'^(allow|deny|unknown)$')
    result: str = Field(default='unknown', pattern=r'^(unknown|responded|failed|applied|executed|verified|rejected|observed)$')
    reason_code: str = Field(pattern=r'^aidr_[a-z0-9_]{1,100}$')
    command_id: str = Field(default='', pattern=r'^$|^[0-9a-f-]{36}$')
    latency_us: str = Field(default='0', pattern=r'^(0|[1-9][0-9]{0,19})$')
    deadline_remaining_us: str = Field(default='0', pattern=r'^(0|[1-9][0-9]{0,19})$')
    gaps: str = Field(default='0', pattern=r'^(0|[1-9][0-9]{0,19})$')
    # Optional additions keep canonical legacy records and replay hashes stable.
    argv: list[str] | None = Field(default=None, max_length=256)
    argv_truncated: bool | None = None
    paths_truncated: bool | None = None
    cwd: str | None = Field(default=None, max_length=1023)
    executable: str | None = Field(default=None, max_length=1023)
    root_path: str | None = Field(default=None, max_length=1023)
    parent: Identity | None = None
    parent_pid: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,9})$')
    exit_code: int | None = Field(default=None, ge=0, le=255)
    exit_signal: int | None = Field(default=None, ge=1, le=127)
    duration_ms: str | None = Field(default=None, pattern=r'^(0|[1-9][0-9]{0,19})$')
    operation: str | None = Field(default=None, pattern=r'^(create|modify|rename|delete)$')
    destination_path: str | None = Field(default=None, max_length=1023)
    activity_origin: str | None = Field(default=None, pattern=r'^client_probe$')

    @model_validator(mode='after')
    def bounded(self):
        for name in ('sequence','time_ns','revision','latency_us','deadline_remaining_us','gaps','duration_ms'):
            if getattr(self,name) is not None and int(getattr(self,name)) > 18446744073709551615:
                raise ValueError('aidr_enforcement_integer_invalid')
        if self.kind == 'response' and not self.command_id:
            raise ValueError('aidr_enforcement_command_missing')
        if self.argv and sum(len(arg.encode('utf-8')) for arg in self.argv) > 8192:
            raise ValueError('aidr_enforcement_argv_too_large')
        if self.exit_code is not None and self.exit_signal is not None:
            raise ValueError('aidr_enforcement_exit_invalid')
        if (self.kind == 'network') != (self.network is not None) or (self.network and (self.relation == 'unknown' or self.root is None)) or (self.network_health and self.kind != 'health'):
            raise ValueError('aidr_network_record_invalid')
        if self.kind == 'file' and not self.operation:
            raise ValueError('aidr_enforcement_operation_missing')
        return self


class Records(Strict):
    records: list[Record] = Field(min_length=1, max_length=128)


@router.post('/records')
async def records(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    # Bound the body before JSON decoding, as on the P1 ingestion endpoint.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1048576:
            fail(413, 'enforcement_batch_too_large', '系统事件批次过大', 'Runtime event batch exceeds the limit')
    runtime_device(db, client_id, authorization, request, 'aidr:report-events')
    try:
        body = Records.model_validate_json(raw)
    except ValueError:
        fail(422, 'enforcement_records_invalid', '系统事件格式无效', 'Invalid runtime event records')
    values = [r.model_dump(exclude_none=True) for r in body.records]
    for record,value in zip(body.records,values):
        payload = canonical(value)
        existing = db.query(AidrRuntimeRecord).filter_by(client_id=client_id, monitor_id=record.monitor_id, sequence=record.sequence).first()
        if existing:
            if (existing.content_hash or hashlib.sha256(existing.payload_json.encode()).hexdigest()) != hashlib.sha256(payload.encode()).hexdigest():
                fail(409, 'enforcement_record_conflict', '系统事件身份与内容冲突', 'Runtime event identity conflicts with its content')
            continue
        if record.kind == 'response':
            command = db.get(AidrResponseCommand, record.command_id)
            target = {k:value[k] for k in ('boot_id','monitor_id','process')}
            if not command or command.client_id != client_id or json.loads(command.target_json) != target or record.result not in ('executed','verified','rejected'):
                fail(409, 'enforcement_response_mismatch', '响应命令与目标不匹配', 'Response command and target do not match')
            rank = {'queued':0,'dispatched':1,'executed':2,'rejected':3,'verified':4}
            if rank[record.result] > rank.get(command.state,0):
                command.state = record.result
        db.add(AidrRuntimeRecord(client_id=client_id, monitor_id=record.monitor_id, sequence=record.sequence,
                                 kind=record.kind, payload_json=payload, received_at=now_text()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, 'enforcement_record_conflict', '系统事件身份发生并发冲突，请重试原批次', 'Concurrent runtime identity conflict; retry the original batch')
    return dict(schema_version=1, client_id=client_id, durable=True, accepted=len(values), digest=hashlib.sha256(raw).hexdigest())


@router.get('/record-agents')
def record_agents(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    root = func.json_extract(AidrRuntimeRecord.payload_json, '$.root_path')
    rows = db.query(root).filter(
        AidrRuntimeRecord.client_id == client_id, AidrRuntimeRecord.expired_at.is_(None),
        AidrRuntimeRecord.kind.in_(['process', 'file', 'network', 'authorization', 'response']),
        root.isnot(None), root != '',
    ).distinct().order_by(root).all()
    return dict(items=[dict(root_path=row[0]) for row in rows])


@router.get('/records')
def query_records(client_id: str, before: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), kind: str = Query('', pattern=r'^$|^(activity|network|process|file|authorization|health|policy|response)$'), include_probes: bool = True, root_path: str = Query('', max_length=1023), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    query = db.query(AidrRuntimeRecord).filter_by(client_id=client_id,expired_at=None)
    if root_path:
        query = query.filter(func.json_extract(AidrRuntimeRecord.payload_json, '$.root_path') == root_path)
    if kind == 'activity':
        query = query.filter(AidrRuntimeRecord.kind.in_(['process', 'file', 'network', 'authorization', 'response']))
        query = query.filter(func.coalesce(func.json_extract(AidrRuntimeRecord.payload_json, '$.transition'), '') != 'fork')
    elif kind:
        query = query.filter_by(kind=kind)
    if not include_probes:
        query = query.filter(func.coalesce(func.json_extract(AidrRuntimeRecord.payload_json, '$.activity_origin'), '') != 'client_probe')
    if before:
        query = query.filter(AidrRuntimeRecord.id < before)
    rows = query.order_by(AidrRuntimeRecord.id.desc()).limit(limit+1).all()
    context = target_context(db, client_id, user)
    items = []
    for row in rows[:limit]:
        value = json.loads(row.payload_json)
        reason = target_reason(value, context) if row.kind == 'process' else 'enforcement_target_unverified'
        items.append(dict(id=row.id, record=value, received_at=row.received_at, can_terminate=not reason,
                          termination_reason=reason))
    return dict(items=items,
                has_more=len(rows)>limit, next_before=rows[limit-1].id if len(rows)>limit else None)


@router.get('/records/{record_id}/context')
def record_context(client_id: str, record_id: int, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    row = db.query(AidrRuntimeRecord).filter_by(id=record_id, client_id=client_id, expired_at=None).first()
    if row is None:
        fail(404, 'enforcement_record_not_found', '事件不存在或已过期', 'Event not found or expired')
    target = json.loads(row.payload_json)
    query = db.query(AidrRuntimeRecord).filter_by(client_id=client_id, monitor_id=row.monitor_id, expired_at=None)
    for key in ('pid', 'pidversion', 'start_us'):
        query = query.filter(func.json_extract(AidrRuntimeRecord.payload_json, '$.process.' + key) == target['process'][key])
    query = query.filter(func.json_extract(AidrRuntimeRecord.payload_json, '$.boot_id') == target['boot_id'])
    rows = query.order_by(func.length(AidrRuntimeRecord.sequence).desc(), AidrRuntimeRecord.sequence.desc()).limit(201).all()
    return dict(items=[dict(id=r.id, record=json.loads(r.payload_json)) for r in reversed(rows[:200])], truncated=len(rows)>200)


class Terminate(Target):
    request_id: str = Field(pattern=r'^[0-9a-f-]{36}$')


@router.post('/terminate')
def terminate(client_id: str, body: Terminate, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db, client_id, user)
    if user.role not in ('admin','super_admin'):
        fail(403, 'enforcement_admin_required', '需要管理员权限', 'Administrator role required')
    target = body.model_dump(exclude={'request_id'})
    previous = db.query(AidrResponseCommand).filter_by(client_id=client_id,request_id=body.request_id).first()
    if previous:
        if previous.target_json != canonical(target):
            fail(409, 'enforcement_command_conflict', '请求标识已用于其他目标', 'Request ID already belongs to a different target')
        return dict(id=previous.id,state=previous.state)
    reason = target_reason(target, target_context(db, client_id, user))
    if reason == 'enforcement_control_not_enabled':
        fail(409, reason, '系统通道仅采集，未启用进程响应', 'System channel is collection-only; process response is not enabled')
    if reason:
        fail(409, reason, '当前执行器或目标进程实例无法确认可操作，请刷新', 'Current executor or target instance is not actionable; refresh status')
    ident=str(uuid.uuid4());now=int(time.time())
    payload=dict(schema=1,device=client_id,command_id=ident,action='terminate',issued_at=str(now),expires_at=str(now+120),**target)
    row=AidrResponseCommand(id=ident,client_id=client_id,request_id=body.request_id,target_json=canonical(target),
                            envelope_json=canonical(sign(payload)),created_by=user.username,created_at=now_text(),expires_at=now+120)
    db.add(row);_operation(db,user,'aidr.enforcement.terminate',client_id,canonical({'command_id':ident,'target':target}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409,'enforcement_command_conflict','请求发生并发冲突，请重试','Concurrent request conflict; retry')
    return dict(id=row.id,state=row.state)


@router.get('/commands')
def commands(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db,client_id,authorization,request,'aidr:heartbeat')
    rows=db.query(AidrResponseCommand).filter(AidrResponseCommand.client_id==client_id,AidrResponseCommand.state.in_(['queued','dispatched']),AidrResponseCommand.expires_at>int(time.time())).order_by(AidrResponseCommand.created_at).limit(16).all()
    for row in rows:row.state='dispatched'
    db.commit()
    return dict(items=[json.loads(row.envelope_json) for row in rows])


@router.get('/responses')
def responses(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    visible(db,client_id,user)
    rows=db.query(AidrResponseCommand).filter_by(client_id=client_id).order_by(AidrResponseCommand.created_at.desc()).limit(100).all()
    return dict(items=[dict(id=r.id,state=r.state,expired=r.expires_at<int(time.time()),
                display_state='expired_unconfirmed' if r.state in ('queued','dispatched') and r.expires_at<int(time.time()) else r.state,
                expires_at=r.expires_at,target=json.loads(r.target_json),created_by=r.created_by,created_at=r.created_at) for r in rows])
