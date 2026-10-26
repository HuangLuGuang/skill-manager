"""Platform policy and device-stream delivery receipts; never store command content here."""
import json
import uuid
from datetime import datetime

from . import models
from .api_errors import ApiError
from .aidr_skill_contract import skill_audit_policy

KEY = "aidr_audit_redaction"
CLIENT_KEY = "aidr_audit_client:"
REVISION_KEY = "aidr_audit_revision"


def current(db, client_id=None):
    row = db.get(models.SystemConfig, KEY)
    value = json.loads(row.value) if row else {"enabled": True, "version": "1", "updated_by": None, "updated_at": None,
                                            "capture": {"prompt": False, "tool_output": False, "file_body": False, "command_body": True}}
    policy = {**value, 'skill_audit': skill_audit_policy(value.get('skill_audit')), 'capture': value.get('capture', {'prompt': False, 'tool_output': False, 'file_body': False}),
            'lifecycle': value.get('lifecycle', {'enabled': True, 'retention_days': 7})}
    if client_id is None:
        return policy
    row = db.get(models.SystemConfig, CLIENT_KEY + client_id)
    local = json.loads(row.value) if row else None
    if local and 'skill_audit_inherit' in local:
        result = {**(policy if local['inherit'] else local)}
        result['skill_audit'] = policy['skill_audit'] if local['skill_audit_inherit'] else skill_audit_policy(local.get('skill_audit'))
        result.update(inherit=local['inherit'], skill_audit_inherit=local['skill_audit_inherit'])
        source = policy if (local['inherit'] or local['skill_audit_inherit']) and int(policy['version']) > int(local['version']) else local
        result.update({key: source[key] for key in ('version', 'updated_by', 'updated_at')})
        return result
    if local and not local['inherit']:
        return {**local, 'skill_audit': skill_audit_policy(local.get('skill_audit'))}
    # Keep the restoration revision so an endpoint never sees its version go backwards.
    return {**policy, 'inherit': True, **({
        'version': str(max(int(policy['version']), int(local['version']))),
        'updated_by': local['updated_by'], 'updated_at': local['updated_at'],
    } if local and int(local['version']) > int(policy['version']) else {})}


def conflict():
    raise ApiError(409, 'aidr.policy_version_conflict', '配置已变化，请刷新', 'Configuration changed; please refresh')


def write_config(db, key, value):
    row = db.get(models.SystemConfig, key)
    encoded = json.dumps(value)
    if row:
        changed = db.query(models.SystemConfig).filter_by(key=key, value=row.value).update({'value': encoded}, synchronize_session=False)
        if changed != 1:
            conflict()
        db.expire(row)
    else:
        db.add(models.SystemConfig(key=key, value=encoded))
    db.flush()


def next_version(db, previous):
    revision = max(int(json.loads(previous)) if previous is not None else 1, int(current(db)['version'])) + 1
    encoded = json.dumps(str(revision))
    if previous is None:
        db.add(models.SystemConfig(key=REVISION_KEY, value=encoded))
    else:
        changed = db.query(models.SystemConfig).filter_by(key=REVISION_KEY, value=previous).update({'value': encoded}, synchronize_session=False)
        if changed != 1:
            conflict()
    db.flush()
    return str(revision)


def save(db, body, user, request, client_id=None):
    from . import iam
    from sqlalchemy.exc import IntegrityError
    if user.role not in {'admin', 'super_admin'}:
        raise ApiError(403, 'aidr.policy_admin_required', '仅管理员可修改审计采集与脱敏策略', 'Only administrators may change audit collection and redaction policy')
    revision_row = db.get(models.SystemConfig, REVISION_KEY)
    previous_revision = revision_row.value if revision_row else None
    before = current(db, client_id)
    if before['version'] != body.version:
        conflict()
    inherit = client_id is not None and body.inherit
    section = getattr(body, 'section', None)
    skill_inherit = inherit
    if inherit:
        target = current(db)
        if body.global_version != target['version']:
            conflict()
    else:
        target = {'enabled': body.enabled, 'skill_audit': body.skill_audit.model_dump() if getattr(body, 'skill_audit', None) is not None else before['skill_audit'],
                  'capture': body.capture.model_dump() if body.capture is not None else before['capture'],
                  'lifecycle': body.lifecycle.model_dump() if body.lifecycle is not None else before['lifecycle']}
        if body.capture is not None:
            # Stored choices remain explicit; wire receipts retain legacy omission semantics.
            target['capture']['command_body'] = body.capture.command_body
    if section == 'skill':
        target = {**before, 'skill_audit': target['skill_audit']}
        inherit = before.get('inherit', False)
    elif section == 'content':
        target['skill_audit'] = before['skill_audit']
        skill_inherit = before.get('skill_audit_inherit', before.get('inherit', False))
    if all(before[key] == target[key] for key in ('enabled', 'capture', 'lifecycle', 'skill_audit')) and (client_id is None or (before['inherit'] == inherit and before.get('skill_audit_inherit', before['inherit']) == skill_inherit)):
        return before
    key = CLIENT_KEY + client_id if client_id is not None else KEY
    try:
        after = {**{key: target[key] for key in ('enabled', 'capture', 'lifecycle', 'skill_audit')},
                 'version': next_version(db, previous_revision), 'updated_by': user.username, 'updated_at': datetime.utcnow().isoformat() + 'Z'}
        if client_id is not None:
            after['inherit'] = inherit
            after['skill_audit_inherit'] = skill_inherit
        stored = after
        write_config(db, key, stored)
        if before['skill_audit'] != target['skill_audit'] or (client_id and before.get('skill_audit_inherit', before['inherit']) != skill_inherit):
            from .aidr_models import AidrSkillUse
            due = db.query(AidrSkillUse).filter(AidrSkillUse.expired_at.is_(None))
            if client_id:
                due = due.filter(AidrSkillUse.client_id == client_id)
            due.update({'next_check_at': datetime.utcnow()}, synchronize_session=False)
        iam.audit(db, request, user, 'clients' if client_id else 'settings', 'update', key, before=before, after=after)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, 'aidr.policy_version_conflict', '配置已变化，请刷新', 'Configuration changed; please refresh') from exc
    return after


def reject():
    raise ApiError(409, "aidr.redaction_policy_invalid", "脱敏策略凭据或序列范围不匹配", "Redaction policy receipt or sequence range does not match")


def issue(db, client_id, stream, frontier, applied_receipt="", applied_after=0, content_supported=False, lifecycle_supported=False, message_supported=False, content_options_supported=False, model_context_supported=False, skill_audit_supported=False, completion_supported=False, command_completion_supported=False, message_links_supported=False):
    policy = current(db, client_id)
    rows = db.query(models.AidrPolicyReceipt).filter_by(client_id=client_id, stream_id=stream, end_sequence=None).order_by(models.AidrPolicyReceipt.created_at).all()
    if applied_receipt:
        applied = next((row for row in rows if row.id == applied_receipt), None)
        if not applied or applied.end_sequence is not None or not applied.start_sequence - 1 <= applied_after <= frontier:
            reject()
        # Close only after durable client application is acknowledged. A lost
        # delivery response cannot strand records collected under the cached policy.
        for previous in rows:
            if (int(previous.version), bool(previous.capture_json), bool(previous.lifecycle_json), bool(previous.skill_audit_json)) < (int(applied.version), bool(applied.capture_json), bool(applied.lifecycle_json), bool(applied.skill_audit_json)) and previous.end_sequence is None:
                previous.end_sequence = applied_after
    capture_scope = dict(policy['capture'])
    if not content_options_supported:
        for key in ('command_body', 'max_fragment_bytes', 'max_event_bytes'):
            capture_scope.pop(key, None)
    if not message_supported:
        capture_scope.pop('model_response', None)
    if not capture_scope.get('model_response'):
        capture_scope.pop('model_response', None)
    capture = json.dumps(capture_scope, sort_keys=True, separators=(',', ':')) if content_supported else None
    lifecycle = json.dumps(policy['lifecycle'], sort_keys=True, separators=(',', ':')) if lifecycle_supported else None
    skill_audit = json.dumps(policy['skill_audit'], sort_keys=True, separators=(',', ':')) if skill_audit_supported else None
    row = next((row for row in rows if row.version == policy["version"] and row.capture_json == capture and row.lifecycle_json == lifecycle and row.skill_audit_json == skill_audit and row.end_sequence is None), None)
    if row is None:
        row = models.AidrPolicyReceipt(id=uuid.uuid4().hex, client_id=client_id, stream_id=stream,
                                      version=policy["version"], enabled=policy["enabled"], capture_json=capture, lifecycle_json=lifecycle, skill_audit_json=skill_audit, start_sequence=frontier + 1)
        db.add(row)
    db.flush()
    return {**({"message_link_schema": 1} if message_supported and message_links_supported else {}), **({"completion_schema": 2 if command_completion_supported else 1} if completion_supported else {}), **({"model_context_schema": 1} if model_context_supported else {}), "version": row.version, "enabled": row.enabled, "receipt": row.id, **({"message_schema": 1} if message_supported else {}), **({'capture': json.loads(row.capture_json)} if row.capture_json else {}),
            **({'lifecycle': json.loads(row.lifecycle_json)} if row.lifecycle_json else {}),
            **({'skill_audit': json.loads(row.skill_audit_json)} if row.skill_audit_json else {})}


def load_receipts(db, policies):
    """Keep a batch-local snapshot inside the ingestion write transaction."""
    ids = list({policy.receipt for policy in policies if policy and policy.receipt})
    receipts = {}
    for offset in range(0, len(ids), 500):
        receipts.update({row.id: row for row in db.query(models.AidrPolicyReceipt).filter(
            models.AidrPolicyReceipt.id.in_(ids[offset:offset + 500])).all()})
    return receipts


def validate(db, client_id, stream, sequence, behavior, *, receipts=None):
    if not behavior or behavior.version < 3:
        return  # Legacy contracts always require redaction.
    policy = behavior.policy
    return validate_receipt(db, client_id, stream, sequence, policy, receipts=receipts)


def validate_receipt(db, client_id, stream, sequence, policy, *, receipts=None):
    if policy.version == "0" and policy.enabled and not policy.receipt:
        return  # First-contact fail-closed projection, still checked for secrets.
    row = db.get(models.AidrPolicyReceipt, policy.receipt) if receipts is None else receipts.get(policy.receipt)
    if (not row or row.client_id != client_id or row.stream_id != stream or row.version != policy.version
            or row.enabled != policy.enabled or (json.loads(row.capture_json) if row.capture_json else None) != (policy.capture.model_dump() if policy.capture else None) or sequence < row.start_sequence
            or (json.loads(row.lifecycle_json) if row.lifecycle_json else None) != (policy.lifecycle.model_dump() if policy.lifecycle else None)
            or (json.loads(row.skill_audit_json) if row.skill_audit_json else None) != (policy.skill_audit.model_dump() if policy.skill_audit else None)
            or (row.end_sequence is not None and sequence > row.end_sequence)):
        reject()
