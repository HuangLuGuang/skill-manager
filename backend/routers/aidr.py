"""P1 device-authenticated device ingestion and bounded management queries."""
from ..aidr_skill_contract import SkillAuditPolicy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, lambda_stmt, case
from ..aidr_operations import merge_operations, present, encode_cursor, decode_cursor, stamp
from starlette.concurrency import run_in_threadpool
from ..services.gateway_db import run_db
from ..services.aidr_ingest import run_ingest

from .. import auth, models, aidr_policy
from ..aidr_products import BY_ID, LogAgentID
from .. import aidr_hook_queries
from .. import aidr_sessions
from ..aidr_turns import present as present_log
from .. import aidr_overview
from .. import aidr_risk
from .. import aidr_security_rules as security_rules
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

_BATCH_INSERT = lambda_stmt(lambda: insert(models.AidrBatch.__table__).on_conflict_do_nothing(
    index_elements=['client_id', 'stream_id', 'batch_id']))
_EVENT_INSERT = lambda_stmt(lambda: insert(models.AidrEvent.__table__).on_conflict_do_nothing(
    index_elements=['client_id', 'logical_id']))
global_tool_router = APIRouter(prefix='/v1/aidr/tool-policy', tags=['aidr'])
global_risk_router = APIRouter(prefix='/v1/aidr/risks', tags=['aidr'])
security_router = APIRouter(prefix='/v1/aidr/security-rules', tags=['aidr'])


def risk_settings_admin(db, user, write=False):
    iam.check(db, user, 'settings:update' if write else 'settings:view')
    if user.role not in ('admin', 'super_admin'):
        raise ApiError(403, 'aidr.risk.admin_required', '需要管理员权限', 'Administrator role required')


def risk_config_input(body, client=False):
    from pydantic import ValidationError
    try:
        return (aidr_risk.ClientDetectionConfig if client else aidr_risk.DetectionConfig).model_validate(body)
    except ValidationError:
        raise ApiError(422, 'aidr.risk.invalid_config', '请检查路径格式、数量、规则及检测设置', 'Check paths, limits, rules and detection settings') from None


def risk_config_conflict():
    raise ApiError(409, 'aidr.risk.config_conflict', '检测配置已更新，请重新读取后保存', 'Detection configuration changed; reload before saving')


def test_risk_command(body):
    from pydantic import ValidationError
    try:
        value = aidr_risk.CommandTestInput.model_validate(body)
    except ValidationError:
        raise ApiError(422, 'aidr.risk.invalid_command_test', '请检查命令、工作目录及规则条件', 'Check command, working directory and rule conditions') from None
    return aidr_risk.command_assessment(value.command, value.cwd, value.configuration.model_dump(), value.platform)


@global_risk_router.post('/commands/test')
def global_risk_command_test(body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    risk_settings_admin(db, user)
    response.headers['Cache-Control'] = 'no-store'
    return test_risk_command(body)


@router.post('/risks/commands/test')
def client_risk_command_test(client_id: str, body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    iam.check(db, user, 'settings:view')
    response.headers['Cache-Control'] = 'no-store'
    return test_risk_command(body)


@global_risk_router.get('/configuration')
def global_risk_configuration(response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    risk_settings_admin(db, user)
    response.headers['Cache-Control'] = 'no-store'
    revision, config = aidr_risk.global_configuration(db)
    return {'revision': revision, **config, 'catalog': aidr_risk.catalog.CATALOG,
            'impact': aidr_risk.configuration_impact(db), 'can_edit': 'settings:update' in iam.permission_codes(db, user)}


@global_risk_router.put('/configuration')
def save_global_risk_configuration(body: dict, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    value = persist_global_risk_configuration(body, db, user)
    db.commit()
    return value


def persist_global_risk_configuration(body, db, user):
    risk_settings_admin(db, user, True)
    config = risk_config_input(body)
    db.connection().exec_driver_sql('UPDATE aidr_global_risk_configs SET revision=revision WHERE 0')
    revision, _ = aidr_risk.global_configuration(db)
    if revision != config.expected_revision:
        risk_config_conflict()
    payload = config.model_dump(exclude={'expected_revision'})
    db.add(aidr_risk.GlobalRiskConfig(revision=revision + 1, payload=dump(payload)))
    _operation(db, user, 'aidr.risk.configure_global', 'global', dump({'revision': revision + 1}))
    db.flush()
    return {'revision': revision + 1, **payload}


@router.get('/risks/configuration')
def risk_configuration(client_id: str, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    iam.check(db, user, 'settings:view')
    response.headers['Cache-Control'] = 'no-store'
    view = aidr_risk.configuration_view(db, client_id)
    permissions = iam.permission_codes(db, user)
    return {**view, **view['effective'], 'catalog': aidr_risk.catalog.CATALOG,
            'platform': _client_or_404(db, client_id).os,
            'global_config': aidr_risk.global_configuration(db)[1],
            'can_edit': user.role in ('admin', 'super_admin') and {'clients:update', 'settings:update'} <= permissions}


@router.put('/risks/configuration')
def save_risk_configuration(client_id: str, body: dict, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    value = persist_risk_configuration(client_id, body, db, user)
    db.commit()
    return value


def persist_risk_configuration(client_id, body, db, user):
    device_for_user(db, client_id, user)
    iam.check(db, user, 'clients:update')
    iam.check(db, user, 'settings:update')
    if user.role not in ('admin', 'super_admin'):
        raise ApiError(403, 'aidr.risk.admin_required', '需要管理员权限', 'Administrator role required')
    config = risk_config_input(body, True)
    db.connection().exec_driver_sql('UPDATE aidr_risk_configs SET revision=revision WHERE 0')
    revision, _ = aidr_risk.configuration(db, client_id)
    if revision != config.expected_revision:
        risk_config_conflict()
    if (config.enabled_mode is not None or config.rules_mode == 'inherit') and config.expected_global_revision != aidr_risk.global_configuration(db)[0]:
        risk_config_conflict()
    payload = config.model_dump(exclude={'expected_revision', 'expected_global_revision'})
    db.add(aidr_risk.RiskConfig(client_id=client_id, revision=revision + 1, payload=dump(payload)))
    _operation(db, user, 'aidr.risk.configure', client_id, dump({'revision': revision + 1}))
    db.flush()
    view = aidr_risk.configuration_view(db, client_id)
    return {**view, **view['effective']}


@router.get('/risks/summary')
def risk_summary(client_id: str, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    return aidr_risk.summary(db, client_id)


def validate_overview_range(since, until):
    if since is None and until is None:
        return
    if since is None or until is None or not 0 < until - since <= 720 * 3600 or until > 253402300799:
        fail(422, 'overview_range_invalid', '统计时间范围无效', 'Invalid statistics time range')


@router.get('/risks/overview')
def risk_overview(client_id: str, response: Response, agent: str = Query('', max_length=32), days: int = Query(7, ge=7, le=30),
                  offset_minutes: int = Query(0, ge=-840, le=840),
                  since: int | None = Query(None, ge=0), until: int | None = Query(None, ge=0),
                  db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    from ..aidr_risk_overview import overview
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    validate_overview_range(since, until)
    return overview(db, client_id, days, offset_minutes, since=since, until=until, agent=agent)


@router.get('/risks')
def risk_list(client_id: str, response: Response, page: int = Query(1, ge=1, le=100000),
              page_size: int = Query(20, ge=1, le=100), severity: str = Query('', pattern='^(|medium|high)$'),
              risk_code: str = Query('', pattern='^(|' + '|'.join(aidr_risk.RISK_CODES) + ')$'),
              agent: str = Query('', max_length=32), source: str = Query('', pattern='^(|hooks|logs|system)$'),
              disposition: str = Query('', pattern='^(|open|accepted|false_positive|resolved)$'),
              sort_by: str = Query('occurred_at', pattern='^(occurred_at|detected_at|severity|agent)$'),
              sort_order: str = Query('desc', pattern='^(asc|desc)$'),
              since: datetime | None = None, until: datetime | None = None,
              detected_since: datetime | None = None, detected_before: datetime | None = None,
              agent_type: str = Query('', max_length=32), unknown_agent: bool = False,
              db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    query = db.query(aidr_risk.RiskFinding).filter_by(client_id=client_id)
    if any(value is not None and value.tzinfo is None for value in (detected_since, detected_before)) or (detected_since and detected_before and detected_since > detected_before):
        raise ApiError(422, 'aidr.risk.invalid_range', '时间范围必须带时区，且开始时间不能晚于结束时间', 'Use timezone-aware times with start no later than end')
    if detected_since:
        query = query.filter(aidr_risk.RiskFinding.detected_at >= detected_since.astimezone(timezone.utc).replace(tzinfo=None))
    if detected_before:
        query = query.filter(aidr_risk.RiskFinding.detected_at < detected_before.astimezone(timezone.utc).replace(tzinfo=None))
    if agent_type:
        query = query.filter(aidr_risk.RiskFinding.agent.in_(aidr_risk.risk_products(agent_type)))
    if unknown_agent:
        query = query.filter(aidr_risk.RiskFinding.agent == '')
    if any(value is not None and value.tzinfo is None for value in (since, until)) or (since and until and since > until):
        raise ApiError(422, 'aidr.risk.invalid_range', '时间范围必须带时区，且开始时间不能晚于结束时间', 'Use timezone-aware times with start no later than end')
    if since:
        query = query.filter(aidr_risk.RiskFinding.occurred_at >= stamp(since.isoformat()))
    if until:
        query = query.filter(aidr_risk.RiskFinding.occurred_at <= stamp(until.isoformat()))
    for name, value in (('severity', severity), ('risk_code', risk_code), ('agent', agent), ('source', source), ('disposition', disposition)):
        if value:
            query = query.filter(getattr(aidr_risk.RiskFinding, name) == value)
    total = query.count()
    field = case((aidr_risk.RiskFinding.severity == 'high', 2), else_=1) if sort_by == 'severity' else getattr(aidr_risk.RiskFinding, sort_by)
    order = field.asc() if sort_order == 'asc' else field.desc()
    rows = query.order_by(order, aidr_risk.RiskFinding.occurred_at.desc(), aidr_risk.RiskFinding.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': aidr_risk.present_rows(db, rows), 'total': total, 'page': page, 'page_size': page_size}


@router.get('/risks/{finding_id}')
def risk_detail(client_id: str, finding_id: str, response: Response, include_evidence: bool = False,
                db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    finding = db.query(aidr_risk.RiskFinding).filter_by(id=finding_id, client_id=client_id).first()
    if not finding:
        raise ApiError(404, 'aidr.risk.not_found', '风险记录不存在或不可访问', 'Risk record is unavailable')
    if include_evidence:
        iam.check(db, user, 'clients:read-audit-content')
    evidence = []
    result_reasons = []
    result_feedback = False
    refs = db.query(aidr_risk.RiskEvidence).filter_by(finding_id=finding.id).order_by(aidr_risk.RiskEvidence.record_id).all()
    for ref in refs:
        row = db.query(aidr_risk.SOURCES[ref.source]).filter_by(id=ref.record_id, client_id=client_id).first()
        item = {'source': ref.source, 'record_id': str(ref.record_id), 'digest': ref.digest,
                'expired': row is None or row.expired_at is not None}
        item['changed'] = not item['expired'] and (row.content_hash or hashlib.sha256(row.payload_json.encode()).hexdigest()) != ref.digest
        if not item['expired'] and not item['changed']:
            raw_result = json.loads(row.payload_json)
            result_event = raw_result.get('event', raw_result) if ref.source == 'hooks' else raw_result
            if result_event.get('kind') in ('tool.post', 'tool.failure', 'tool_result'):
                result_feedback = True
                result_reasons.extend(reason for reason in (result_event.get('behavior') or {}).get('uncertainty', [])
                    if reason in ('host_result_not_provided', 'result_format_unsupported', 'result_fields_conflict'))
        if include_evidence and not item['expired'] and not item['changed']:
            raw = json.loads(row.payload_json)
            event = raw.get('event', raw) if ref.source == 'hooks' else raw
            behavior = event.get('behavior') or {}
            item['event'] = {name: event[name] for name in ('kind', 'tool', 'session_id', 'native_call_id',
                'path', 'destination_path', 'operation', 'relation', 'root_path', 'executable', 'argv',
                'decision', 'result', 'reason_code') if name in event}
            item['event']['actions'] = behavior.get('actions') or []
            item['event']['status'] = behavior.get('status', event.get('result', {'success': 'reported_complete', 'error': 'reported_error'}.get(event.get('outcome'), 'unknown')))
            item['event']['exit_code'] = behavior.get('exit_code', event.get('exit_code'))
            item['event']['control_decision'] = event.get('control_decision')
        evidence.append(item)
    if include_evidence:
        _operation(db, user, 'aidr.risk.evidence_view', client_id, dump({'finding_id': finding.id, 'count': len(evidence)}))
        db.commit()
    context = db.get(aidr_risk.RiskDetectionContext, finding.id)
    snapshot = json.loads(context.payload) if context else {}
    matches = snapshot.get('matches')
    if matches is not None and not include_evidence:
        matches = [{key: hit[key] for key in ('id', 'name', 'risk_code', 'severity')} for hit in matches]
    return {**aidr_risk.present_rows(db, [finding])[0], 'evidence': evidence, 'result_reasons': sorted(set(result_reasons)),
            'result_feedback': result_feedback,
            'detection_source': snapshot.get('rules_mode'), 'detection_matches': matches,
            'detection_revisions': {key: snapshot[key] for key in ('global_revision', 'client_revision') if key in snapshot}}


@router.get('/risks/{finding_id}/dispositions')
def risk_dispositions(client_id: str, finding_id: str, response: Response,
                      page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
                      db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'clients:view')
    device_for_user(db, client_id, user)
    if not db.query(aidr_risk.RiskFinding.id).filter_by(id=finding_id, client_id=client_id).first():
        raise ApiError(404, 'aidr.risk.not_found', '风险记录不存在或不可访问', 'Risk record is unavailable')
    response.headers['Cache-Control'] = 'no-store'
    query = db.query(aidr_risk.RiskDisposition).filter_by(finding_id=finding_id)
    total = query.count()
    rows = query.order_by(aidr_risk.RiskDisposition.revision.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [{name: getattr(row, name) for name in ('revision', 'previous', 'status', 'reason', 'actor')} |
                      {'created_at': row.created_at.isoformat() + 'Z'} for row in rows],
            'total': total, 'page': page, 'page_size': page_size}


@router.put('/risks/{finding_id}/disposition')
def risk_dispose(client_id: str, finding_id: str, body: dict, db: Session = Depends(get_db),
                 user=Depends(auth.get_current_admin_user)):
    from pydantic import ValidationError
    iam.check(db, user, 'clients:view')
    iam.check(db, user, 'clients:update')
    device_for_user(db, client_id, user)
    try:
        value = aidr_risk.DispositionInput.model_validate(body)
    except ValidationError:
        raise ApiError(422, 'aidr.risk.invalid_disposition', '请选择有效状态并填写1至1000个字符的非空原因',
                       'Select a valid status and provide a nonblank reason of 1 to 1000 characters') from None
    finding = db.query(aidr_risk.RiskFinding).filter_by(id=finding_id, client_id=client_id).first()
    if finding is None:
        raise ApiError(404, 'aidr.risk.not_found', '风险记录不存在或不可访问', 'Risk record is unavailable')
    previous = finding.disposition
    if finding.disposition_revision != value.expected_revision or previous == value.status:
        raise ApiError(409, 'aidr.risk.disposition_conflict', '处置状态已变化或与目标相同，请重新读取后选择',
                       'Disposition changed or already matches the target; reload before selecting')
    changed = db.query(aidr_risk.RiskFinding).filter_by(id=finding_id, client_id=client_id,
        disposition_revision=value.expected_revision).update({
            'disposition': value.status, 'disposition_revision': value.expected_revision + 1,
        }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise ApiError(409, 'aidr.risk.disposition_conflict', '处置状态已变化，请重新读取后选择',
                       'Disposition changed; reload before selecting')
    db.add(aidr_risk.RiskDisposition(finding_id=finding_id, revision=value.expected_revision + 1,
                                   previous=previous, status=value.status, reason=value.reason, actor=user.username))
    _operation(db, user, 'aidr.risk.dispose', client_id, dump({'finding_id': finding_id,
        'revision': value.expected_revision + 1, 'previous': previous, 'status': value.status}))
    db.commit()
    db.refresh(finding)
    return aidr_risk.present_rows(db, [finding])[0]


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
                   since: int | None = Query(None, ge=0), until: int | None = Query(None, ge=0),
                   db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    response.headers['Cache-Control'] = 'no-store'
    validate_overview_range(since, until)
    return aidr_overview.cached_overview(db, client_id, source, agent, hours, since, until)


@router.get('/overview/tasks')
def audit_overview_tasks(client_id: str, before: int | None = Query(None, ge=1),
                         since: int | None = Query(None, ge=0), until: int | None = Query(None, ge=0),
                         status: str = Query('', pattern='^(|pending|running|succeeded|failed|cancelled)$'),
                         db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    validate_overview_range(since, until)
    return aidr_overview.task_summary(db, client_id, before, since, until, status)


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
                           dimension: str = Query('', pattern='^(|commands|command_occurrences|tools|agents|failures|sessions)$'),
                           value: str = Query('', max_length=256), page: int = Query(1, ge=1),
                           page_size: int = Query(30, ge=1, le=100),
                           db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    if not 0 < until - since <= 720 * 3600:
        fail(422, 'overview_range_invalid', '统计时间范围无效', 'Invalid statistics time range')
    return aidr_overview.details(db, client_id, source, since, until, agent, dimension, value, page, page_size)


@router.post("/hooks:batch")
async def hook_batch(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    device = await run_db(db, runtime_device, db, client_id, authorization, request, "aidr:report-events")
    raw = await bounded_body(request)
    return await run_ingest(db, aidr_hooks.save, db, device, raw)


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
               keyword: str = Query('', max_length=256), result: str = Query('', pattern='^(|attempted|denied|failed|host_confirmed|unknown)$'),
               order: str = Query('oldest', pattern='^(oldest|newest)$'), turn_id: str = Query('', max_length=256),
               after: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
               db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    from ..aidr_models import AidrSkillUse
    from ..aidr_skill_usage import refresh_batch, registry_manager
    entries = ('qoder-hooks', 'qoder-cli') if agent == 'qoder-hooks' else (agent,)
    query = db.query(AidrSkillUse).filter_by(client_id=client_id, session_id=session_id, expired_at=None).filter(AidrSkillUse.agent.in_(entries))
    session_total = query.count()
    if after:
        query = query.filter(AidrSkillUse.id < after if order == 'newest' else AidrSkillUse.id > after)
    if behavior: query = query.filter_by(behavior=behavior)
    if keyword.strip():
        query = query.filter(or_(*(func.coalesce(func.json_extract(AidrSkillUse.payload_json, path), '').contains(keyword.strip(), autoescape=True)
                                 for path in ('$.skill.name', '$.skill.path', '$.certification.name'))))
    if turn_id:
        native_turn = func.json_extract(AidrSkillUse.payload_json, '$.turn_id')
        query = query.filter(or_(native_turn == turn_id, native_turn.is_(None)))
    # Evaluate the selected state after rechecking, not against a stale cache.
    rows = query.order_by(AidrSkillUse.id.desc() if order == 'newest' else AidrSkillUse.id).limit(201).all()
    items, cursor = [], after
    manager = registry_manager()
    settings = aidr_policy.current(db, client_id)['skill_audit']
    checked = 0
    while checked < min(len(rows), 200) and len(items) < limit:
        # Compute registry/file checks before the first write, then commit a
        # bounded group. Never inspect more rows than the remaining page slots.
        group = rows[checked:checked + min(25, limit - len(items), 200 - checked)]
        refreshed = refresh_batch(db, group, manager, settings)
        for item in refreshed:
            if (item.get('stage') and (not turn_id or item.get('turn_id') == turn_id)
                    and (not certification or item.get('certification', {}).get('status') == certification)
                    and (not result or item['stage'] == result)):
                items.append(item)
        cursor = group[-1].id
        checked += len(group)
        db.commit()
    more = bool(rows and cursor != rows[-1].id)
    return {'items':items,'has_more':more,'next_cursor':str(cursor) if more else '',
            'search_complete':not more, 'checked_count':checked, 'session_total':session_total,
            'checks':'fresh_registry_with_observed_content','mode':'audit'}


@router.get('/skill-uses/{usage_id}')
def skill_use_detail(client_id: str, usage_id: int = Path(ge=1), before: int = Query(0, ge=0),
                     db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    from .. import aidr_skill_review
    value = aidr_skill_review.detail(db, aidr_skill_review.usage(db, client_id, usage_id), before)
    db.commit()
    return value


class SkillObservationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=128)


@router.get('/skill-uses/{usage_id}/evidence')
def skill_use_evidence(client_id: str, usage_id: int = Path(ge=1), source: str = Query(pattern='^(hook|log)$'),
                       record_id: int = Query(ge=1), db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    device_for_user(db, client_id, user)
    from .. import aidr_skill_review
    from ..aidr_models import AidrEvent
    from ..aidr_skill_usage import identity
    row = aidr_skill_review.usage(db, client_id, usage_id)
    model = AidrHookEvent if source == 'hook' else AidrEvent
    record = db.query(model).filter_by(id=record_id, client_id=client_id, expired_at=None).first()
    if not record:
        fail(404, 'skill_record_unavailable', '证据不存在或已过期', 'Evidence is unavailable or expired')
    raw = json.loads(record.payload_json)
    event = {**raw.get('event', {}), 'user_scope':raw.get('user_scope')} if source == 'hook' else raw
    if identity(client_id, event, source, record_id) != row.call_key:
        fail(404, 'skill_record_unavailable', '证据不属于此记录', 'Evidence does not belong to this record')
    return {'source':source, 'record_id':str(record_id),
            'content_record_id':str(record.id) if source == 'hook' else record.logical_id,
            'event':metadata_view(event)}


@router.post('/skill-uses/{usage_id}/observations')
def request_skill_observation(client_id: str, body: SkillObservationRequest, usage_id: int = Path(ge=1),
                              db: Session = Depends(get_db), user=Depends(iam.require('clients:update'))):
    device_for_user(db, client_id, user)
    from .. import aidr_skill_review
    value = aidr_skill_review.create_observation(db, aidr_skill_review.usage(db, client_id, usage_id), body.request_id, user.username)
    _operation(db, user, 'aidr.skill_observation_requested', client_id, dump({'usage_id':usage_id, 'task_id':value['id']}))
    db.commit()
    return value


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
    from ..aidr_commands import content_commands
    for item in values:
        parsed = content_commands(item)
        if parsed is not None:
            item['command_analysis'] = parsed
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
    section: str | None = Field(default=None, pattern=r'^(content|skill)$')
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


def policy_allows_reporting(policy):
    target = policy["runtime_governance"]
    channels = target.get("channels")
    return not policy["runtime_governance_builtin"] and target["enabled"] and (channels is None or any(channels.values()))


def runtime_device(db, client_id, authorization, request, scope, *, allow_paused=False):
    token = resolve_access_token(db, authorization, required_scope=scope, request=request)
    if token.token_type != "client" or not token.bound_client_id or token.bound_client_id != client_id:
        fail(403, "device_binding_mismatch", "凭证绑定的设备不匹配", "Credential device binding mismatch")
    _client_or_404(db, client_id)
    device = db.get(models.AidrDevice, client_id)
    # A device without a configuring user follows the effective collection policy.
    if device is not None and device.created_by:
        enabled = device.enabled
    else:
        from ..client_governance import policy_view
        enabled = policy_allows_reporting(policy_view(db, client_id))
        if device is None and enabled:
            db.execute(insert(models.AidrDevice).values(client_id=client_id, created_by="")
                       .on_conflict_do_nothing(index_elements=["client_id"]))
            db.commit()
            device = db.get(models.AidrDevice, client_id)
            if device.created_by:
                enabled = device.enabled
    if not device or (not enabled and not allow_paused):
        fail(403, "reporting_disabled", "设备未允许上报", "Reporting is not enabled for this device")
    return device


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = True


@router.put("/configuration")
def configure(client_id: str, body: Configuration, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user)):
    _ensure_visible(_client_or_404(db, client_id), user)
    values = {"enabled": body.enabled, "created_by": user.username}
    db.execute(insert(models.AidrDevice).values(client_id=client_id, **values)
               .on_conflict_do_update(index_elements=["client_id"], set_=values))
    _operation(db, user, "aidr.configure", client_id, dump(body.model_dump()))
    db.commit()
    return {"client_id": client_id, "enabled": body.enabled}


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


def _save_events(db, client_id, stream_id, records, receipts):
    """Persist one consecutive event group under the batch's existing writer lock."""
    from ..aidr_skill_usage import merge_many

    for record, value, _, _, _ in records:
        aidr_policy.validate(db, client_id, stream_id, int(record.sequence), value.behavior, receipts=receipts)
        if value.message:
            aidr_policy.validate_receipt(db, client_id, stream_id, int(record.sequence), value.message.policy, receipts=receipts)
    logical_ids = {value.logical_event_id for _, value, _, _, _ in records}
    existing = {row.logical_id: row for row in db.query(models.AidrEvent).filter(
        models.AidrEvent.client_id == client_id, models.AidrEvent.logical_id.in_(logical_ids)).all()}
    new = {}
    for _, value, _, payload, identity_hash in records:
        if value.logical_event_id not in existing:
            new.setdefault(value.logical_event_id, dict(client_id=client_id, logical_id=value.logical_event_id,
                content_hash=identity_hash, agent=value.agent, kind=value.kind, payload_json=payload))
    if new:
        db.execute(_EVENT_INSERT, list(new.values()))
        existing.update({row.logical_id: row for row in db.query(models.AidrEvent).filter(
            models.AidrEvent.client_id == client_id, models.AidrEvent.logical_id.in_(new)).all()})
    events, rows = [], []
    for _, value, projected, _, identity_hash in records:
        row = existing[value.logical_event_id]
        if row.expired_at is None and row.content_hash != identity_hash and not same_log_source(row.payload_json, value):
            db.rollback()
            fail(409, "event_conflict", "逻辑事件身份对应不同内容", "Logical event identity has different content")
        if value.logical_event_id in new:
            new.pop(value.logical_event_id)
            events.append(projected)
            rows.append(row)
    merge_operations(db.connection(), client_id, events)
    merge_many(db, "log", rows)


def save_batch(db, device, stream_id, batch_id, raw):
    from itertools import groupby

    body_digest = hashlib.sha256(raw).hexdigest()
    batch, values = parse_batch(raw)
    prepared = []
    policies = []
    for record, value in zip(batch.records, values):
        projected = value.model_dump(exclude_none=True)
        payload = dump(projected)
        prepared.append((record, value, projected, payload, digest(logical_projection(value)) if isinstance(value, Event) else digest(payload)))
        if isinstance(value, Event):
            if value.behavior and value.behavior.version >= 3:
                policies.append(value.behavior.policy)
            if value.message:
                policies.append(value.message.policy)
    # SQLite upsert obtains a writer lock before checking duplicates, keeping
    # concurrent retries and a crash before commit atomic at the database level.
    result = db.execute(_BATCH_INSERT, dict(client_id=device.client_id, stream_id=stream_id,
        batch_id=batch_id, digest=body_digest, record_count=len(batch.records)))
    row = db.query(models.AidrBatch).filter_by(client_id=device.client_id, stream_id=stream_id, batch_id=batch_id).one()
    if row.digest != body_digest:
        db.rollback()
        fail(409, "idempotency_conflict", "同一批次标识对应不同内容", "Idempotency key has different content")
    if result.rowcount:
        receipts = aidr_policy.load_receipts(db, policies)
        # Coverage can repair prior events, so preserve its position between groups.
        for is_event, group in groupby(prepared, key=lambda item: isinstance(item[1], Event)):
            if is_event:
                _save_events(db, device.client_id, stream_id, list(group), receipts)
                continue
            for record, value, _, payload, content_hash in group:
                from ..aidr_turns import apply as apply_turn_links
                apply_turn_links(db, device.client_id, value)
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
    device = await run_db(db, runtime_device, db, client_id, authorization, request, "aidr:report-events")
    if not re.fullmatch(r"[0-9a-f]{64}", idempotency_key) or not re.fullmatch(r"[0-9a-f]{32}", x_aidr_stream_id):
        fail(400, "batch_identity_invalid", "缺少有效的批次或采集实例标识", "Invalid batch or collection stream identity")
    raw = await bounded_body(request)
    return await run_ingest(db, save_batch, db, device, x_aidr_stream_id, idempotency_key, raw)


@router.get("/status")
def status(client_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_admin_user), include_retention: bool = True):
    device = device_for_user(db, client_id, user)
    from ..client_governance import policy_view
    from ..runtime_governance import Observation, channel_view
    policy = policy_view(db, client_id)
    runtime = db.get(Observation, client_id)
    report = json.loads(runtime.report_json) if runtime else None
    log_channel = channel_view(policy, report)['logs']
    enabled = device.enabled if device and device.created_by else policy_allows_reporting(policy)
    online = bool(device and enabled and device.last_seen_at and datetime.utcnow() - device.last_seen_at <= timedelta(seconds=90))
    if log_channel['health']['state'] == 'running' and not online:
        log_channel['health'] = {'state': 'transport_offline', 'code': 'aidr_channel_transport_offline', 'severity': 'warning'}
    audit_policy = aidr_policy.current(db, client_id)
    if log_channel['target_enabled'] is True and audit_policy.get('lifecycle', {}).get('enabled') is False:
        log_channel['health'] = {'state': 'audit_paused', 'code': 'aidr_channel_audit_paused', 'severity': 'info'}
    elif log_channel['target_enabled'] is True and device and not enabled:
        log_channel['health'] = {'state': 'reporting_paused', 'code': 'aidr_channel_reporting_paused', 'severity': 'info'}
    if not device:
        return {"configured": False, "enabled": enabled, "log_channel": log_channel, "audit_redaction": audit_policy}
    # Metadata only: a reader heartbeat is not evidence of each product's delivery.
    cutoff = datetime.utcnow() - timedelta(minutes=15)
    arrivals = db.query(models.AidrEvent.agent, models.AidrEvent.kind,
                        func.max(models.AidrEvent.received_at), func.count(models.AidrEvent.id)).filter(
        models.AidrEvent.client_id == client_id, models.AidrEvent.expired_at.is_(None),
        models.AidrEvent.received_at >= cutoff, models.AidrEvent.received_at <= datetime.utcnow()
    ).group_by(models.AidrEvent.agent, models.AidrEvent.kind).all()
    receipts = [{"agent": agent, "kind": kind, "last_received_at": at.isoformat() + "Z", "count": count}
                for agent, kind, at, count in arrivals]
    result = {"audit_redaction": audit_policy, "configured": True, "enabled": enabled,
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
    return {"items": [{"id": str(row.id), "server_received_at": row.received_at, "event": metadata_view(present_log(db, row))} for row in rows[:limit]], "next_after": str(rows[min(len(rows), limit) - 1].id) if rows else str(after), "has_more": len(rows) > limit}


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
def audit_policy(client_id: str, body: PolicyRequest, request: Request, authorization: str | None = Header(None), x_aidr_policy_schema: str = Header('1'), x_aidr_audit_lifecycle: str = Header(''), x_aidr_message_capture: str = Header(''), x_aidr_message_links: str = Header(''), x_aidr_content_options: str = Header(''), x_aidr_model_context: str = Header(''), x_aidr_skill_audit: str = Header(''), x_aidr_tool_completion: str = Header(''), x_aidr_command_completion: str = Header(''), db: Session = Depends(get_db)):
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
    if x_aidr_message_links not in {'', '1'} or (x_aidr_message_links and x_aidr_message_capture != '1'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_content_options not in {'', '1'} or (x_aidr_content_options and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_model_context not in {'', '1'} or (x_aidr_model_context and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_skill_audit not in {'', '1'} or (x_aidr_skill_audit and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_tool_completion not in {'', '1'} or (x_aidr_tool_completion and x_aidr_policy_schema != '2'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    if x_aidr_command_completion not in {'', '1'} or (x_aidr_command_completion and x_aidr_tool_completion != '1'):
        fail(422, 'policy_schema_unsupported', '审计策略契约不支持', 'Unsupported audit policy schema')
    policy = aidr_policy.issue(db, client_id, body.stream_id, frontier, body.applied_receipt, int(body.applied_after), content_supported=x_aidr_policy_schema == '2', lifecycle_supported=x_aidr_audit_lifecycle == '1', message_supported=x_aidr_message_capture == '1', message_links_supported=x_aidr_message_links == '1', content_options_supported=x_aidr_content_options == '1', model_context_supported=x_aidr_model_context == '1', skill_audit_supported=x_aidr_skill_audit == '1', completion_supported=x_aidr_tool_completion == '1', command_completion_supported=x_aidr_command_completion == '1')
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
    return {"items": hook_control.approval_views(db, items), "has_more": len(rows)>limit, "next_before": str(items[-1].created_at) if items else None, "next_before_id": items[-1].id if items else None}


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
    return {"approval": hook_control.approval_view(row, json.loads(report.payload) if report else None), "evidence_record_id": str(event.id) if event else None, "evidence": metadata_view(json.loads(event.payload_json)) if event and event.expired_at is None else None, "evidence_code": 'aidr_audit_history_retention' if event and event.expired_at is not None else '', "client_report": {"record": json.loads(report.payload), "received_at": str(report.received_at), "evidence_type": "client_report"} if report else None}


@router.post("/hook-attempt-reports")
async def hook_attempt_report(client_id: str, request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    await run_in_threadpool(runtime_device, db, client_id, authorization, request, "aidr:report-events")
    raw = await bounded_body(request)
    return await run_in_threadpool(hook_control.save_attempt_report, db, client_id, raw)


# Read-through migration keeps old signed policies and independent inheritance authoritative.
def security_configuration(client_id, response, db, user):
    response.headers['Cache-Control'] = 'no-store'
    if client_id:
        iam.check(db, user, 'clients:view')
        device_for_user(db, client_id, user)
    else:
        tool_policy_admin(user)
    permissions = iam.permission_codes(db, user)
    detection = None
    if 'settings:view' in permissions:
        detection = (risk_configuration(client_id, response, db, user) if client_id
                     else global_risk_configuration(response, db, user))
    control = hook_policy_view(client_id, db, user) if client_id else global_tool_policy(db, user)
    control['can_edit'] = control['can_edit'] and (not client_id or 'clients:update' in permissions)
    from ..aidr_rule_execution import view as execution_view
    return {'detection': detection, 'control': control, 'execution': execution_view(db, client_id, control),
            **security_rules.document_view(db, detection, control, client_id)}


@security_router.get('')
def global_security_configuration(response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return security_configuration('', response, db, user)


@router.get('/security-rules')
def client_security_configuration(client_id: str, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return security_configuration(client_id, response, db, user)


def save_security_configuration(client_id, body, response, db, user):
    from pydantic import ValidationError
    if 'document' in body:
        return save_security_document(client_id, body, response, db, user)
    if not body or set(body) - {'detection', 'control'} or any(not isinstance(value, dict) for value in body.values()):
        raise ApiError(422, 'aidr.security.invalid_config', '请检查安全规则配置', 'Check security rule configuration')
    if client_id:
        device_for_user(db, client_id, user)
        iam.check(db, user, 'clients:update')
    tool_policy_admin(user)
    # Serialize version checks and both writes; any failure rolls back the whole request.
    db.connection().exec_driver_sql('UPDATE aidr_global_risk_configs SET revision=revision WHERE 0')
    try:
        if 'detection' in body:
            if client_id:
                persist_risk_configuration(client_id, body['detection'], db, user)
            else:
                persist_global_risk_configuration(body['detection'], db, user)
        if 'control' in body:
            model = tool_scope.ClientPolicyInput if client_id else hook_control.ToolPolicyInput
            value = model.model_validate(body['control'])
            if client_id:
                tool_scope.publish_client(db, client_id, value, user.username)
            else:
                tool_scope.publish_global(db, value, user.username)
            _operation(db, user, 'aidr.hook.policy' if client_id else 'aidr.hook.global_policy',
                       client_id or 'global', dump({'rule_count': len(value.rules)}))
        db.flush()
        result = security_configuration(client_id, response, db, user)
        db.commit()
        return result
    except ValidationError:
        db.rollback()
        raise ApiError(422, 'aidr.security.invalid_config', '请检查安全规则配置', 'Check security rule configuration') from None
    except Exception:
        db.rollback()
        raise


def security_versions(view):
    return {'risk': view['detection']['revision'], 'risk_global': view['detection'].get('global_revision'),
            'control': view['control']['revision'], 'control_global': view['control'].get('global_revision'),
            'scope': view['control'].get('scope_revision')}


def save_security_document(client_id, body, response, db, user):
    from pydantic import ValidationError
    tool_policy_admin(user)
    iam.check(db, user, 'settings:update')
    if client_id:
        device_for_user(db, client_id, user)
        iam.check(db, user, 'clients:update')
    db.connection().exec_driver_sql('UPDATE aidr_global_risk_configs SET revision=revision WHERE 0')
    try:
        view = security_configuration(client_id, response, db, user)
        if view['detection'] is None:
            iam.check(db, user, 'settings:view')
        if set(body) - {'approval_wait_seconds'} != {'document', 'expected', 'source', 'enabled_mode', 'enabled', 'default_action'}:
            security_rules.invalid()
        if body['expected'] != security_versions(view):
            raise ApiError(409, 'aidr.security.config_conflict', '安全规则已更新，请重新读取后保存', 'Security rules changed; reload before saving')
        document = security_rules.clean_document(body['document'])
        source = body['source']
        if source not in ('inherit', 'custom', 'mixed') or not client_id and source != 'custom':
            security_rules.invalid()
        d, c = view['detection'], view['control']
        if source == 'mixed':
            if (d['rules_mode'] == 'inherit') == c['inherit']:
                security_rules.invalid()
            previous = {r['id']: r for r in view['rules']}
            current = {r['id']: r for r in document['rules']}
            if current.keys() - previous.keys():
                security_rules.invalid()
            for key, row in previous.items():
                if row['source'] != 'client' and current.get(key) != {k: v for k, v in row.items() if k != 'source'}:
                    security_rules.invalid()
            new_paths = {p['id']: p for p in document['path_sets']}
            for row in view['path_sets']:
                if row['source'] != 'client' and new_paths.get(row['id']) != {k: v for k, v in row.items() if k != 'source'}:
                    security_rules.invalid()
        rules_mode = d.get('rules_mode', 'custom') if source == 'mixed' else source
        inherit = c.get('inherit', False) if source == 'mixed' else source == 'inherit'
        # Validate referenced collections even for disabled rules before publishing either engine.
        for rule in document['rules']:
            security_rules.rule_configuration(rule, document, 'linux')
        compiled = security_rules.control_rules(document)
        detection = {key: d[key] for key in ('sensitive_paths', 'protected_paths', 'builtin_ids', 'command_rules', 'custom_commands')}
        detection.update(enabled=body['enabled'], security=document, expected_revision=d['revision'])
        if client_id:
            detection.update(rules_mode=rules_mode, enabled_mode=body['enabled_mode'], expected_global_revision=d['global_revision'])
        if client_id:
            persist_risk_configuration(client_id, detection, db, user)
        else:
            persist_global_risk_configuration(detection, db, user)
        wait = body.get('approval_wait_seconds', security_rules.editor_policy(c, bool(client_id))['approval_wait_seconds'])
        policy = {'default_action': body['default_action'], 'approval_wait_seconds': wait, 'rules': compiled}
        control_body = {**policy, 'expected_revision': c['revision']}
        hook_control.ToolPolicyInput.model_validate(control_body)
        previous_policy = security_rules.editor_policy(c, bool(client_id))
        stored_policy = (c.get('global_policy') if client_id and c['inherit'] else c.get('policy')) or {}
        upgrade_wait = 'approval_wait_seconds' in body and 'approval_wait_seconds' not in stored_policy
        changed = upgrade_wait or wait != previous_policy['approval_wait_seconds'] or security_rules.digest(policy) != security_rules.digest(previous_policy) or client_id and inherit != c['inherit']
        if changed:
            if client_id:
                control_body.update(inherit=inherit, expected_scope_revision=c['scope_revision'], expected_global_revision=c['global_revision'])
                tool_scope.publish_client(db, client_id, tool_scope.ClientPolicyInput.model_validate(control_body), user.username)
            else:
                tool_scope.publish_global(db, hook_control.ToolPolicyInput.model_validate(control_body), user.username)
            _operation(db, user, 'aidr.hook.policy' if client_id else 'aidr.hook.global_policy', client_id or 'global', dump({'rule_count': len(compiled)}))
        security_rules.save_metadata(db, client_id, document, policy)
        db.flush()
        result = security_configuration(client_id, response, db, user)
        db.commit()
        return result
    except ValidationError:
        db.rollback()
        security_rules.invalid()
    except Exception:
        db.rollback()
        raise


@security_router.put('')
def save_global_security_configuration(body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return save_security_configuration('', body, response, db, user)


@router.put('/security-rules')
def save_client_security_configuration(client_id: str, body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return save_security_configuration(client_id, body, response, db, user)


def preview_security_document(client_id, body, response, db, user):
    from pydantic import ValidationError
    configuration_view = security_configuration(client_id, response, db, user)
    iam.check(db, user, 'settings:view')
    try:
        if set(body) != {'document', 'command', 'cwd', 'platform', 'agent', 'tool', 'enabled', 'default_action'}:
            security_rules.invalid()
        document = security_rules.clean_document(body['document'])
        config = aidr_risk.CommandTestInput.model_validate({key: body[key] for key in ('cwd', 'platform')} | {'command': body['command'] or 'true', 'configuration': {'enabled': body['enabled'], 'security': document}})
        policy = hook_control.ToolPolicyInput(expected_revision='0', default_action=body['default_action'], rules=security_rules.control_rules(document))
        control = preview_hook(HookRulePreview(policy=policy, agent=body['agent'], tool=body['tool'], command=body['command'], cwd=body['cwd']))
        control['security_rule_ids'] = [r['id'] for r in document['rules'] if set(security_rules.control_ids(r)).intersection(control['matched_rule_ids'])]
        configuration = config.configuration.model_dump() | {'platform': config.platform}
        event = {'kind': 'tool.pre', 'agent': body['agent'], 'tool': body['tool'], 'behavior': {'actions': [{'category': 'command', 'command': body['command'], 'cwd': body['cwd']}] if body['command'] else []}}
        assessment = aidr_risk.command_assessment(config.command, config.cwd, configuration, config.platform) if body['command'] else {'status': 'unmatched', 'matches': [], 'unresolved_rules': []}
        assessment['matches'] = aidr_risk.detect_matches(event, configuration, windows=config.platform == 'windows')
        assessment['status'] = 'matched' if assessment['matches'] else 'disabled' if not body['enabled'] else 'unresolved' if assessment['unresolved_rules'] else 'unmatched'
        return {'risk': assessment, 'control': control, 'execution': configuration_view['execution']}
    except ValidationError:
        security_rules.invalid()


@security_router.post('/preview')
def global_security_preview(body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return preview_security_document('', body, response, db, user)


@router.post('/security-rules/preview')
def client_security_preview(client_id: str, body: dict, response: Response, db: Session = Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return preview_security_document(client_id, body, response, db, user)
