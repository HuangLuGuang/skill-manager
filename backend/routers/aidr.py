"""P1 device-authenticated device ingestion and bounded management queries."""
from ..aidr_skill_contract import SkillAuditPolicy
import hashlib
import json
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from ..aidr_operations import merge_operation, present, encode_cursor, decode_cursor, stamp
from starlette.concurrency import run_in_threadpool

from .. import auth, models, aidr_policy
from ..aidr_products import BY_ID, LogAgentID
from .. import aidr_hook_queries
from .. import aidr_sessions
from .. import aidr_overview
from .. import aidr_hooks
from .. import aidr_hook_runtime
from .. import aidr_plugin_status
from .. import aidr_hook_control as hook_control
from .. import aidr_tool_policy_scope as tool_scope
from ..aidr_rule_preview import HookRulePreview, preview_hook
from ..aidr_models import AidrHookEvent
from ..aidr_behavior import AuditPolicy
from ..aidr_content import AuditLifecycle, CaptureScope, metadata_view, record_contents
from .. import iam
from ..aidr_contract import MAX_BATCH_BYTES, Event, Reason, logical_projection, parse_batch, same_log_source
from ..api_errors import ApiError
from ..sqlite_db import get_db
from .access_tokens import resolve_access_token
from .clients import _client_or_404, _ensure_visible, _operation

router = APIRouter(prefix="/v1/clients/{client_id}/aidr", tags=["aidr"])
global_tool_router = APIRouter(prefix='/v1/aidr/tool-policy', tags=['aidr'])


def tool_policy_admin(user=Depends(auth.get_current_admin_user)):
    if user.role not in ('admin', 'super_admin'):
        fail(403, 'hook_admin_required', '需要管理员权限', 'Administrator role required')
    return user


@global_tool_router.get('')
def global_tool_policy(db: Session = Depends(get_db), user=Depends(tool_policy_admin)):
    return {**tool_scope.global_view(db), 'can_edit': True, 'impact': tool_scope.impact(db)}


@global_tool_router.post('/preview')
def preview_global_tools(body: HookRulePreview, user=Depends(tool_policy_admin)):
    return preview_hook(body)


@global_tool_router.put('')
def publish_global_tools(body: hook_control.ToolPolicyInput, db: Session = Depends(get_db), user=Depends(tool_policy_admin)):
    value = tool_scope.publish_global(db, body, user.username)
    _operation(db, user, 'aidr.hook.global_policy', 'global', dump({'revision': value['revision'], 'rule_count': len(body.rules)}))
    db.commit()
    return {**value, 'can_edit': True, 'impact': tool_scope.impact(db)}


@router.get('/overview')
def audit_overview(client_id: str, response: Response, source: str = Query('hooks', pattern='^(hooks|logs)$'),
                   agent: str = Query('', pattern='^(|qoder|' + '|'.join(BY_ID) + ')$'), hours: int = Query(24, ge=1, le=720),
                   db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    return aidr_overview.cached_overview(db, client_id, source, agent, hours)


@router.get('/overview/tasks')
def audit_overview_tasks(client_id: str, before: int | None = Query(None, ge=1),
                         db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    return aidr_overview.task_summary(db, client_id, before)


@router.get('/overview/entry')
def audit_overview_entry(client_id: str, source: str = Query('hooks', pattern='^(hooks|logs)$'),
                        record_id: int = Query(ge=1), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    result = aidr_overview.detail_entry(db, client_id, source, record_id)
    if result is None:
        fail(404, 'overview_entry_unavailable', '记录不存在或已过期', 'Record is unavailable or expired')
    return result


@router.get('/overview/details')
def audit_overview_details(client_id: str, source: str = Query('hooks', pattern='^(hooks|logs)$'),
                           agent: str = Query('', pattern='^(|qoder|' + '|'.join(BY_ID) + ')$'),
                           since: int = Query(ge=0), until: int = Query(ge=0),
                           dimension: str = Query('', pattern='^(|commands|tools|agents|failures|sessions)$'),
                           value: str = Query('', max_length=256), cursor: str = Query('', pattern='^([0-9]{1,12}:[a-f0-9]{64})?$'),
                           db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if not 0 < until - since <= 720 * 3600:
        fail(422, 'overview_range_invalid', '统计时间范围无效', 'Invalid statistics time range')
    return aidr_overview.details(db, client_id, source, since, until, agent, dimension, value, cursor)


@router.post("/hooks:batch")
async def hook_batch(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    device = await run_in_threadpool(runtime_device, db, client_id, authorization, request, "aidr:report-events")
    raw = await bounded_body(request)
    return await run_in_threadpool(aidr_hooks.save, db, device, raw)


@router.get("/hooks")
def hook_events(client_id: str, after: int | None = Query(None, ge=0, le=2**63-1),
                before: int | None = Query(None, ge=1, le=2**63-1), snapshot_id: int | None = Query(None, ge=0, le=2**63-1),
                limit: int = Query(100, ge=1, le=100), agent: str | None = Query(None, pattern='^(' + '|'.join(BY_ID) + ')$'),
                hook_event: str | None = Query(None, min_length=1, max_length=32), session_id: str | None = Query(None, min_length=1, max_length=256),
                tool: str | None = Query(None, min_length=1, max_length=256), native_call_id: str | None = Query(None, min_length=1, max_length=256),
                event_id: str | None = Query(None, pattern='^[0-9a-f]{32}$'), keyword: str | None = Query(None, min_length=1, max_length=256),
                db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if after is not None and (before is not None or snapshot_id is not None):
        fail(422, 'hook_cursor_conflict', '升序游标不能与历史快照游标混用', 'Ascending and historical snapshot cursors cannot be combined')
    filters = dict(agent=agent, hook_event=hook_event, session_id=session_id, tool=tool, native_call_id=native_call_id, event_id=event_id)
    return aidr_hook_queries.page(db, client_id, after=after, before=before, snapshot_id=snapshot_id, limit=limit, filters=filters, keyword=keyword)


@router.get('/sessions')
def audit_sessions(client_id: str, response: Response, cursor: str = Query('', max_length=2048), limit: int = Query(20, ge=1, le=100),
                   keyword: str = Query('', max_length=256), agent: str = Query('', pattern='^(|qoder|' + '|'.join(BY_ID) + ')$'),
                   include_questions: bool = False,
                   db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if include_questions:
        iam.check(db, user, 'clients:read-audit-content')
    try:
        result = aidr_sessions.sessions(db, client_id, cursor=cursor, limit=limit, keyword=keyword, agent=agent, include_questions=include_questions)
    except ValueError:
        fail(422, 'session_cursor_invalid', '会话翻页条件已失效，请刷新后重试', 'Invalid session cursor; refresh and retry')
    audit_question_view(db, user, client_id, response, result, include_questions)
    return result


def audit_question_view(db, user, client_id, response, result, include_questions):
    response.headers['Cache-Control'] = 'no-store'
    if include_questions:
        _operation(db, user, 'aidr.question_view', client_id, dump({'record_ids': [r['prompt_id'] for r in result['items'] if r.get('prompt_id')]}))
        db.commit()


@router.get('/session-turns')
def audit_session_turns(client_id: str, response: Response, agent: str = Query(pattern='^(' + '|'.join(BY_ID) + ')$'),
                        session_id: str = Query('', max_length=256), orphan_id: int = Query(0, ge=0, le=2**63-1),
                        cursor: str = Query('', max_length=2048), limit: int = Query(100, ge=1, le=100),
                        include_questions: bool = False, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if include_questions:
        iam.check(db, user, 'clients:read-audit-content')
    try:
        result = aidr_sessions.turns(db, client_id, agent=agent, session_id=session_id, orphan_id=orphan_id,
            cursor=cursor, limit=limit, include_questions=include_questions)
    except ValueError:
        fail(422, 'session_cursor_invalid', '会话翻页条件已失效，请刷新后重试', 'Invalid session cursor; refresh and retry')
    audit_question_view(db, user, client_id, response, result, include_questions)
    return result


@router.get('/session-timeline')
def audit_session_timeline(client_id: str, source: str = Query(pattern='^(logs|hooks)$'),
                           agent: str = Query(pattern='^(' + '|'.join(BY_ID) + ')$'), session_id: str = Query('', max_length=256),
                           orphan_id: int = Query(0, ge=0, le=2**63-1), cursor: str = Query('', max_length=2048),
                           limit: int = Query(30, ge=1, le=100), keyword: str = Query('', max_length=256),
                           order: str = Query('oldest', pattern='^(oldest|newest)$'),
                           turn_key: str = Query('', max_length=300),
                           db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    try:
        return aidr_sessions.timeline(db, client_id, source=source, agent=agent, session_id=session_id,
            orphan_id=orphan_id, cursor=cursor, limit=limit, keyword=keyword, order=order, turn_key=turn_key)
    except ValueError:
        fail(422, 'session_cursor_invalid', '会话翻页条件已失效，请刷新后重试', 'Invalid session cursor; refresh and retry')


@router.get('/skill-uses')
def skill_uses(client_id: str, agent: str = Query(max_length=32), session_id: str = Query(max_length=256),
               behavior: str = Query('', pattern='^(|invocation|file_access)$'),
               certification: str = Query('', pattern='^(|pending|verified|verified_content|unregistered|unapproved|content_changed|revoked|unauthorized)$'),
               after: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
               db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    from ..aidr_models import AidrSkillUse
    from ..aidr_skill_usage import refresh, registry_manager
    entries = ('qoder-hooks', 'qoder-cli') if agent == 'qoder-hooks' else (agent,)
    query = db.query(AidrSkillUse).filter_by(client_id=client_id, session_id=session_id, expired_at=None).filter(AidrSkillUse.agent.in_(entries), AidrSkillUse.id > after)
    if behavior: query = query.filter_by(behavior=behavior)
    # Evaluate the selected state after rechecking, not against a stale cache.
    rows = query.order_by(AidrSkillUse.id).limit(201).all()
    items, cursor = [], after
    manager = registry_manager()
    settings = aidr_policy.current(db, client_id)['skill_audit']
    for row in rows[:200]:
        item = refresh(db, row, manager, settings)
        cursor = row.id
        if not certification or item.get('certification', {}).get('status') == certification:
            items.append(item)
        if len(items) == limit:
            break
    more = bool(rows and cursor < rows[-1].id)
    db.commit()
    return {'items':items,'has_more':more,'next_cursor':str(cursor) if more else '',
            'checks':'fresh_registry_with_observed_content','mode':'audit'}


@router.get('/hooks/{record_id}/related')
def hook_related(client_id: str, record_id: int = Path(ge=1, le=2**63-1), db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    row = db.query(AidrHookEvent).filter_by(client_id=client_id, id=record_id, expired_at=None).first()
    if row is None:
        fail(404, 'hook_event_not_found', 'Hook 记录不存在或不可访问', 'Hook record not found or inaccessible')
    return aidr_hook_queries.related(db, client_id, row)


@router.get('/content')
def audit_content(client_id: str, response: Response, source: str = Query(pattern='^(hook|log)$'), record_id: str = Query(min_length=1, max_length=64), db: Session = Depends(get_db), user=Depends(iam.require('clients:read-audit-content'))):
    device_for_user(db, client_id, user)
    if source == 'hook' and re.fullmatch(r'[1-9][0-9]{0,18}', record_id) and int(record_id) < 2**63:
        row = db.query(AidrHookEvent).filter_by(client_id=client_id, id=int(record_id)).first()
    elif source == 'log' and re.fullmatch(r'[0-9a-f]{64}', record_id):
        row = db.query(models.AidrEvent).filter_by(client_id=client_id, logical_id=record_id).first()
    else:
        fail(422, 'content_identity_invalid', '正文记录身份无效', 'Invalid audit content record identity')
    if row is None:
        fail(404, 'content_not_found', '正文记录不存在或不可访问', 'Audit content record not found or not accessible')
    if row.expired_at is not None:
        fail(410, 'content_expired', '正文已按审计保留策略淘汰', 'Content expired under the audit retention policy')
    # Access audit records only identity and count, never the selected text.
    values = record_contents(json.loads(row.payload_json))
    _operation(db, user, 'aidr.content_view', client_id, dump({'source': source, 'record_id': record_id, 'count': len(values)}))
    db.commit()
    response.headers['Cache-Control'] = 'no-store'
    return {'source': source, 'record_id': record_id, 'contents': values}


def fail(status, code, zh, en):
    raise ApiError(status, "aidr." + code, zh, en)


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def device_for_user(db, client_id, user):
    _ensure_visible(_client_or_404(db, client_id), user)
    device = db.get(models.AidrDevice, client_id)
    return device


class ClientAuditPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    inherit: bool
    version: str = Field(pattern=r'^[1-9][0-9]{0,18}$')
    global_version: str = Field(pattern=r'^[1-9][0-9]{0,18}$')
    enabled: bool
    capture: CaptureScope
    lifecycle: AuditLifecycle
    skill_audit: 'SkillAuditPolicy | None' = None


def client_audit_policy_view(db, client_id, user):
    permissions = iam.permission_codes(db, user)
    device = db.get(models.AidrDevice, client_id)
    health = json.loads(device.health_json or '{}') if device else {}
    report = health.get('audit_policy') or {}
    reported = report.get('policy') or {}
    runtime = {'version': reported.get('version'), 'skill_audit': reported.get('skill_audit'),
               'code': report.get('code'), 'refreshed_at': report.get('refreshed_at'),
               'reported_at': device.last_seen_at.isoformat() + 'Z' if device and device.last_seen_at else None}
    return {**aidr_policy.current(db, client_id), 'global_policy': aidr_policy.current(db),
            'skill_audit_runtime': runtime,
            'can_edit': user.role in {'admin', 'super_admin'} and {'clients:update', 'settings:update'} <= permissions}


@router.get('/audit-policy')
def get_client_audit_policy(client_id: str, db: Session = Depends(get_db), user=Depends(iam.require('settings:view'))):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    return client_audit_policy_view(db, client_id, user)


@router.put('/audit-policy')
def update_client_audit_policy(client_id: str, body: ClientAuditPolicyUpdate, request: Request,
                               db: Session = Depends(get_db), user=Depends(iam.require('settings:update'))):
    iam.check(db, user, 'clients:update')
    device_for_user(db, client_id, user)
    aidr_policy.save(db, body, user, request, client_id)
    return client_audit_policy_view(db, client_id, user)


def runtime_device(db, client_id, authorization, request, scope, *, allow_paused=False):
    token = resolve_access_token(db, authorization, required_scope=scope, request=request)
    device = db.get(models.AidrDevice, client_id)
    if token.token_type != "client" or not token.bound_client_id or token.bound_client_id != client_id:
        fail(403, "device_binding_mismatch", "凭证绑定的设备不匹配", "Credential device binding mismatch")
    _client_or_404(db, client_id)
    if not device or (not device.enabled and not allow_paused):
        fail(403, "reporting_disabled", "设备未允许上报", "Reporting is not enabled for this device")
    return device


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True


@router.put("/configuration")
def configure(client_id: str, body: Configuration, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    _ensure_visible(_client_or_404(db, client_id), user)
    device = db.get(models.AidrDevice, client_id)
    if not device:
        device = models.AidrDevice(client_id=client_id, created_by=user.username)
        db.add(device)
    device.enabled = body.enabled
    _operation(db, user, "aidr.configure", client_id, dump(body.model_dump()))
    db.commit()
    return {"client_id": client_id, "enabled": device.enabled}


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent: LogAgentID
    version: str = Field(max_length=80)
    status: str = Field(pattern="^(available|unavailable|unverified)$")
    parser_status: str | None = Field(default=None, pattern="^(available|unverified)$")
    parser_version: str | None = Field(default=None, max_length=80)


class DiscoveryProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    known_sources: int = Field(ge=0,le=16384)
    pending_sources: int = Field(ge=0,le=16384)
    pending_directories: int = Field(ge=0,le=8192)
    scanned_entries: int = Field(ge=0,le=10000)
    status: str = Field(pattern="^(complete|partial|unavailable)$")
    reason_codes: list[Reason] = Field(max_length=16)
    historical_missing: int | None = Field(default=None, ge=0, le=16384)
    unread_missing: int | None = Field(default=None, ge=0, le=16384)
    missing_directories: int | None = Field(default=None, ge=0, le=8192)


class DiscoveryStatus(BaseModel):
    source_id: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    model_config = ConfigDict(extra="forbid", strict=True)
    agent: LogAgentID
    status: str = Field(pattern="^(complete|partial|unavailable)$")
    reason_codes: list[Reason] = Field(max_length=32)
    progress: DiscoveryProgress | None = None


class PolicyHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    policy: AuditPolicy
    code: str = Field(pattern="^aidr_policy_(applied|cached|response_invalid)$")
    refreshed_at: str = Field(max_length=40)


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stream_id: str = Field(pattern="^[0-9a-f]{32}$")
    capabilities: list[Capability] = Field(max_length=16)
    queued_records: int = Field(ge=0, le=3000000)
    logical_events: int = Field(ge=0, le=1000000)
    evicted_event_payloads: int = Field(ge=0, le=1000000)
    intake_code: str = Field(default="", max_length=100, pattern="^$|^aidr_[a-z0-9_]+$")
    recovery_code: str = Field(default="", max_length=100, pattern="^$|^aidr_[a-z0-9_]+$")
    upload_code: str = Field(default="", max_length=100, pattern="^$|^aidr_[a-z0-9_]+$")
    audit_policy: PolicyHealth | None = None
    discovery: list[DiscoveryStatus] = Field(default_factory=list, max_length=64)


@router.post("/heartbeat")
def heartbeat(client_id: str, body: Heartbeat, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    device = runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    device.last_seen_at = datetime.utcnow()
    device.health_json = dump(body.model_dump(exclude={"capabilities"}))
    device.capabilities_json = dump([c.model_dump() for c in body.capabilities])
    db.commit()
    return {"schema_version": 2, "client_id": client_id, "stream_id": body.stream_id, "server_received_at": device.last_seen_at.isoformat() + "Z"}


async def bounded_body(request):
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        fail(415, "encoding_unsupported", "此接口仅接收未压缩 JSON", "Only uncompressed JSON is accepted")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BATCH_BYTES:
            fail(413, "batch_too_large", "事件批次超过 1 MiB", "Event batch exceeds 1 MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def save_batch(db, device, stream_id, batch_id, raw):
    body_digest = hashlib.sha256(raw).hexdigest()
    batch, values = parse_batch(raw)
    # SQLite upsert obtains a writer lock before checking duplicates, keeping
    # concurrent retries and a crash before commit atomic at the database level.
    result = db.execute(insert(models.AidrBatch).values(client_id=device.client_id, stream_id=stream_id, batch_id=batch_id, digest=body_digest, record_count=len(batch.records)).on_conflict_do_nothing(index_elements=["client_id", "stream_id", "batch_id"]))
    row = db.query(models.AidrBatch).filter_by(client_id=device.client_id, stream_id=stream_id, batch_id=batch_id).one()
    if row.digest != body_digest:
        db.rollback()
        fail(409, "idempotency_conflict", "同一批次标识对应不同内容", "Idempotency key has different content")
    if result.rowcount:
        for record, value in zip(batch.records, values):
            payload = dump(value.model_dump(exclude_none=True))
            if isinstance(value, Event):
                aidr_policy.validate(db, device.client_id, stream_id, int(record.sequence), value.behavior)
                if value.message:
                    aidr_policy.validate_receipt(db, device.client_id, stream_id, int(record.sequence), value.message.policy)
                identity_hash = digest(logical_projection(value))
                inserted_event = db.execute(insert(models.AidrEvent).values(client_id=device.client_id, logical_id=value.logical_event_id, content_hash=identity_hash, agent=value.agent, kind=value.kind, payload_json=payload).on_conflict_do_nothing(index_elements=["client_id", "logical_id"]))
                existing = db.query(models.AidrEvent).filter_by(client_id=device.client_id, logical_id=value.logical_event_id).one()
                if existing.expired_at is None and existing.content_hash != identity_hash and not same_log_source(existing.payload_json, value):
                    db.rollback()
                    fail(409, "event_conflict", "逻辑事件身份对应不同内容", "Logical event identity has different content")
                if inserted_event.rowcount:
                    merge_operation(db.connection(),device.client_id,value.model_dump(exclude_none=True))
                    from ..aidr_skill_usage import merge as merge_skill_use
                    merge_skill_use(db, "log", existing)
            else:
                content_hash = digest(payload)
                db.execute(insert(models.AidrCoverageRecord).values(client_id=device.client_id, stream_id=stream_id, record_id=record.record_id, payload_json=payload, content_hash=content_hash).on_conflict_do_nothing(index_elements=["client_id", "stream_id", "record_id"]))
                existing = db.query(models.AidrCoverageRecord).filter_by(client_id=device.client_id, stream_id=stream_id, record_id=record.record_id).one()
                if existing.content_hash != content_hash:
                    db.rollback()
                    fail(409, "coverage_conflict", "覆盖版本对应不同内容", "Coverage revision has different content")
                statement = insert(models.AidrSource).values(client_id=device.client_id, stream_id=stream_id, source_id=value.source_id, revision=int(value.revision), payload_json=payload)
                db.execute(statement.on_conflict_do_update(index_elements=["client_id", "stream_id", "source_id"], set_={"revision": int(value.revision), "payload_json": payload, "received_at": datetime.utcnow()}, where=models.AidrSource.revision < int(value.revision)))
    db.commit()
    return {"schema_version": 2, "client_id": device.client_id, "stream_id": stream_id, "batch_id": batch_id, "digest": body_digest, "accepted": len(batch.records), "durable": True}


@router.post("/events:batch")
async def events_batch(client_id: str, request: Request, authorization: str | None = Header(None), idempotency_key: str = Header(""), x_aidr_stream_id: str = Header(""), db: Session = Depends(get_db)):
    device = await run_in_threadpool(runtime_device, db, client_id, authorization, request, "aidr:report-events")
    if not re.fullmatch(r"[0-9a-f]{64}", idempotency_key) or not re.fullmatch(r"[0-9a-f]{32}", x_aidr_stream_id):
        fail(400, "batch_identity_invalid", "缺少有效的批次或采集实例标识", "Invalid batch or collection stream identity")
    raw = await bounded_body(request)
    return await run_in_threadpool(save_batch, db, device, x_aidr_stream_id, idempotency_key, raw)


@router.get("/status")
def status(client_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user), include_retention: bool = True):
    device = device_for_user(db, client_id, user)
    from ..client_governance import policy_view
    from ..runtime_governance import Observation, channel_view
    policy = policy_view(db, client_id)
    runtime = db.get(Observation, client_id)
    report = json.loads(runtime.report_json) if runtime else None
    log_channel = channel_view(policy, report)['logs']
    online = bool(device and device.enabled and device.last_seen_at and datetime.utcnow() - device.last_seen_at <= timedelta(seconds=90))
    if log_channel['health']['state'] == 'running' and not online:
        log_channel['health'] = {'state': 'transport_offline', 'code': 'aidr_channel_transport_offline', 'severity': 'warning'}
    audit_policy = aidr_policy.current(db, client_id)
    if log_channel['target_enabled'] is True and audit_policy.get('lifecycle', {}).get('enabled') is False:
        log_channel['health'] = {'state': 'audit_paused', 'code': 'aidr_channel_audit_paused', 'severity': 'info'}
    elif log_channel['target_enabled'] is True and device and not device.enabled:
        log_channel['health'] = {'state': 'reporting_paused', 'code': 'aidr_channel_reporting_paused', 'severity': 'info'}
    if not device:
        return {"configured": False, "log_channel": log_channel, "audit_redaction": audit_policy}
    # Metadata only: a reader heartbeat is not evidence of each product's delivery.
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    arrivals = db.query(models.AidrEvent.agent, models.AidrEvent.kind,
                        func.max(models.AidrEvent.received_at), func.count(models.AidrEvent.id)).filter(
        models.AidrEvent.client_id == client_id, models.AidrEvent.expired_at.is_(None),
        models.AidrEvent.received_at >= cutoff, models.AidrEvent.received_at <= datetime.utcnow()
    ).group_by(models.AidrEvent.agent, models.AidrEvent.kind).all()
    receipts = [{"agent": agent, "kind": kind, "last_received_at": at.isoformat() + "Z", "count": count}
                for agent, kind, at, count in arrivals]
    result = {"audit_redaction": audit_policy, "configured": True, "enabled": device.enabled,
            "online": online, "log_channel": log_channel, "product_receipts": receipts, "receipt_window_seconds": 900,
            "last_seen_at": device.last_seen_at, "capabilities": json.loads(device.capabilities_json), "health": json.loads(device.health_json)}
    # Collection status polls live health; history totals are only needed by diagnostics.
    if include_retention:
        from ..aidr_retention import view as retention_view
        result["retention"] = retention_view(db, client_id)
    return result


@router.post("/state-migration")
def state_migration(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:report-events", allow_paused=True)
    legacy = db.get(models.AidrLegacyDestination, client_id)
    return {"schema_version": 2, "client_id": client_id, "legacy_suffix": legacy.suffix if legacy else None}


@router.get("/events")
def events(client_id: str, after: int = Query(0, ge=0, le=2**63-1), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    device = device_for_user(db, client_id, user)
    if not device:
        return {"items": [], "next_after": str(after), "has_more": False}
    rows = db.query(models.AidrEvent).filter(models.AidrEvent.client_id == client_id, models.AidrEvent.expired_at.is_(None), models.AidrEvent.id > after).order_by(models.AidrEvent.id).limit(limit + 1).all()
    return {"items": [{"id": str(row.id), "server_received_at": row.received_at, "event": metadata_view(json.loads(row.payload_json))} for row in rows[:limit]], "next_after": str(rows[min(len(rows), limit) - 1].id) if rows else str(after), "has_more": len(rows) > limit}


@router.get("/sources")
def sources(client_id: str, after: int = Query(0, ge=0, le=2**63-1), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    device = device_for_user(db, client_id, user)
    if not device:
        return {"items": [], "next_after": str(after), "has_more": False}
    rows = db.query(models.AidrSource).filter(models.AidrSource.client_id == client_id, models.AidrSource.id > after).order_by(models.AidrSource.id).limit(limit + 1).all()
    return {"items": [{"id": str(row.id), "stream_id": row.stream_id, "server_received_at": row.received_at, **json.loads(row.payload_json)} for row in rows[:limit]], "next_after": str(rows[min(len(rows), limit) - 1].id) if rows else str(after), "has_more": len(rows) > limit}


@router.get("/operations")
def operations(client_id: str, cursor: str = Query('',max_length=256), limit: int = Query(20,ge=1,le=100), agent: str = Query('',max_length=16), session: str = Query('',max_length=256), tool: str = Query('',max_length=256), result: str = Query('',max_length=32), since: str = Query('',max_length=40), until: str = Query('',max_length=40), db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    device_for_user(db,client_id,user)
    query=db.query(models.AidrOperation).filter(models.AidrOperation.client_id==client_id,models.AidrOperation.expired_at.is_(None))
    for column,value in ((models.AidrOperation.agent,agent),(models.AidrOperation.session_id,session),(models.AidrOperation.tool,tool),(models.AidrOperation.result_status,result)):
        if value:query=query.filter(column==value)
    try:
        if since:query=query.filter(models.AidrOperation.latest_at>=stamp(since))
        if until:query=query.filter(models.AidrOperation.latest_at<=stamp(until))
        if cursor:
            at,ident=decode_cursor(cursor)
            query=query.filter(or_(models.AidrOperation.latest_at<at,and_(models.AidrOperation.latest_at==at,models.AidrOperation.id<ident)))
    except (ValueError,TypeError,KeyError,OverflowError):
        fail(422,'operation_filter_invalid','操作查询条件无效','Invalid operation query filter')
    rows=query.order_by(models.AidrOperation.latest_at.desc(),models.AidrOperation.id.desc()).limit(limit+1).all()
    gaps=db.query(models.AidrSource).filter(models.AidrSource.client_id==client_id,func.json_extract(models.AidrSource.payload_json,'$.coverage.status')!='complete').count()
    items=rows[:limit]
    from ..aidr_correlation import hook_evidence
    views = [metadata_view(present(r)) for r in items]
    for view in views:
        view['hook_evidence'] = hook_evidence(db, client_id, view)
    return {'items':views,'has_more':len(rows)>limit,'next_cursor':encode_cursor(items[-1]) if items else '', 'coverage_gap_sources':gaps}


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stream_id: str = Field(pattern="^[0-9a-f]{32}$")
    applied_receipt: str = Field(default="", pattern="^$|^[0-9a-f]{32}$")
    applied_after: str = Field(default="0", pattern="^(0|[1-9][0-9]{0,18})$")
    last_sequence: str = Field(pattern="^(0|[1-9][0-9]{0,18})$")


@router.post("/audit-policy")
def audit_policy(client_id: str, body: PolicyRequest, request: Request, authorization: str | None = Header(None), x_aidr_policy_schema: str = Header('1'), x_aidr_audit_lifecycle: str = Header(''), x_aidr_message_capture: str = Header(''), x_aidr_content_options: str = Header(''), x_aidr_model_context: str = Header(''), x_aidr_skill_audit: str = Header(''), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    frontier = int(body.last_sequence)
    if frontier >= 2**63 - 1:
        aidr_policy.reject()
    if x_aidr_policy_schema not in {'1', '2'}:
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_audit_lifecycle not in {'', '1'} or (x_aidr_audit_lifecycle and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_message_capture not in {'', '1'} or (x_aidr_message_capture and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_content_options not in {'', '1'} or (x_aidr_content_options and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_model_context not in {'', '1'} or (x_aidr_model_context and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_skill_audit not in {'', '1'} or (x_aidr_skill_audit and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    policy = aidr_policy.issue(db, client_id, body.stream_id, frontier, body.applied_receipt, int(body.applied_after), content_supported=x_aidr_policy_schema == '2', lifecycle_supported=x_aidr_audit_lifecycle == '1', message_supported=x_aidr_message_capture == '1', content_options_supported=x_aidr_content_options == '1', model_context_supported=x_aidr_model_context == '1', skill_audit_supported=x_aidr_skill_audit == '1')
    db.commit()
    return policy


@router.get("/hook-policy")
def hook_policy_view(client_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    row = hook_control.latest_policy(db, client_id)
    from ..aidr_hook_drift import policy_analysis
    revision = str(row.revision) if row else "0"
    return {**tool_scope.scope_view(db, client_id), "revision": revision, "policy": json.loads(row.payload) if row else None, "can_edit": user.role in ("admin", "super_admin"), "analysis": policy_analysis(db, client_id, row.revision) if row else None, "runtime": aidr_hook_runtime.view(db, client_id, revision), "plugins": aidr_plugin_status.view(db, client_id)}


@router.post("/hook-plugin-status")
def hook_plugin_status(client_id: str, body: aidr_plugin_status.PluginReport, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    return aidr_plugin_status.receive(db, client_id, body)


@router.post("/hook-runtime")
def hook_runtime_report(client_id: str, body: aidr_hook_runtime.RuntimeReport, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    return aidr_hook_runtime.receive(db, client_id, body)


@router.post("/hook-policy/preview")
def hook_rule_preview(client_id: str, body: HookRulePreview, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    return preview_hook(body)


@router.put("/hook-policy")
def hook_policy_publish(client_id: str, body: tool_scope.ClientPolicyInput, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if user.role not in ("admin", "super_admin"):
        fail(403, "hook_admin_required", "需要管理员权限", "Administrator role required")
    tool_scope.publish_client(db, client_id, body, user.username)
    _operation(db, user, "aidr.hook.policy", client_id, dump({"inherit": body.inherit, "rule_count": len(body.rules)}))
    db.commit()
    return hook_policy_view(client_id, db, user)


@router.post("/hook-control/bootstrap")
def hook_control_bootstrap(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    import base64
    from cryptography.hazmat.primitives import serialization
    from ..aidr_enforcement import signing_key
    runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    key = signing_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"public_key": base64.b64encode(key).decode()}


@router.post("/hook-control/snapshot")
def hook_control_snapshot(client_id: str, body: hook_control.ControlRequest, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:heartbeat", allow_paused=True)
    return hook_control.snapshot(db, client_id, body)


@router.post("/hook-approvals")
def hook_approval_request(client_id: str, body: hook_control.ApprovalRequest, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    runtime_device(db, client_id, authorization, request, "aidr:report-events")
    response, _ = hook_control.request_approval(db, client_id, body)
    db.commit()
    return response


@router.get("/hook-approvals")
def hook_approval_list(client_id: str, before: int = Query(2**63-1, ge=1, le=2**63-1), before_id: str = Query("f"*32, pattern=r"^[0-9a-f]{32}$"), limit: int = Query(50, ge=1, le=100), agent: str = Query('', max_length=80), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    table = hook_control.HookApprovalRow
    query = db.query(table).filter_by(client_id=client_id)
    if agent:
        query = query.filter(func.json_extract(table.scope, '$.agent') == agent)
    rows = query.filter(or_(table.created_at<before, and_(table.created_at==before, table.id<before_id))).order_by(table.created_at.desc(), table.id.desc()).limit(limit+1).all()
    items = rows[:limit]
    return {"items": [hook_control.approval_view(row) for row in items], "has_more": len(rows)>limit, "next_before": str(items[-1].created_at) if items else None, "next_before_id": items[-1].id if items else None}


@router.post("/hook-approvals/{approval_id}/decision")
def hook_approval_decision(client_id: str, approval_id: str, body: hook_control.ApprovalDecision, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if user.role not in ("admin", "super_admin"):
        fail(403, "hook_admin_required", "需要管理员权限", "Administrator role required")
    response, changed = hook_control.decide(db, client_id, approval_id, body, user.username)
    if changed:
        _operation(db, user, "aidr.hook.approval", client_id, dump({"approval_id": approval_id, "revision": response["revision"], "decision": body.decision}))
    db.commit()
    return response


@router.get("/hook-approvals/{approval_id}")
def hook_approval_detail(client_id: str, approval_id: str, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    row = db.query(hook_control.HookApprovalRow).filter_by(client_id=client_id, id=approval_id).first()
    if row is None:
        fail(404, "hook_approval_missing", "审批不存在", "Approval not found")
    event = db.query(AidrHookEvent).filter_by(client_id=client_id, stream_id=row.stream_id, event_id=row.event_id).first()
    report = db.query(hook_control.HookAttemptReportRow).filter_by(client_id=client_id, stream_id=row.stream_id, event_id=row.event_id).first()
    return {"approval": hook_control.approval_view(row), "evidence": metadata_view(json.loads(event.payload_json)) if event and event.expired_at is None else None, "evidence_code": 'aidr_audit_history_retention' if event and event.expired_at is not None else '', "client_report": {"record": json.loads(report.payload), "received_at": str(report.received_at), "evidence_type": "client_report"} if report else None}


@router.post("/hook-attempt-reports")
async def hook_attempt_report(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    await run_in_threadpool(runtime_device, db, client_id, authorization, request, "aidr:report-events")
    raw = await bounded_body(request)
    return await run_in_threadpool(hook_control.save_attempt_report, db, client_id, raw)
