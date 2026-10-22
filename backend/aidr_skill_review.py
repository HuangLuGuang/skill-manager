"""Read-only Skill observations and evidence navigation, scoped to one device."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath

from sqlalchemy import func

from . import aidr_adapters, aidr_policy, models
from .aidr_models import AidrSkillUse, AidrSkillCheck
from .aidr_skill_usage import dump, refresh, registry_manager
from .api_errors import ApiError


def fail(code, zh, en, status=409):
    raise ApiError(status, 'aidr.skill_' + code, zh, en)


def usage(db, client_id, usage_id):
    row = db.query(AidrSkillUse).filter_by(id=usage_id, client_id=client_id, expired_at=None).first()
    if not row:
        fail('record_unavailable', '记录不存在或已过期', 'Record is unavailable or expired', 404)
    return row


def path_type(path):
    return PureWindowsPath if PureWindowsPath(path).drive else PurePosixPath


def observe_target(db, row):
    data = json.loads(row.payload_json)
    path = data['skill'].get('path')
    if not path or data.get('identity_ambiguous'):
        return None, 'source_unknown'
    cls = path_type(path)
    root = cls(path).parent
    product = aidr_adapters.get(row.agent).inventory_type
    agents = db.query(models.ClientAgent).filter_by(client_id=row.client_id, agent_type=product).all()
    matches = []
    for agent in agents:
        caps = json.loads(agent.capabilities_json or '{}')
        roots = caps.get('skill_roots') or [agent.skills_path]
        if any(p and root.is_relative_to(cls(p)) for p in roots):
            matches.append(agent)
    if len(matches) != 1:
        return None, 'agent_identity_unknown'
    if not json.loads(matches[0].capabilities_json or '{}').get('skill_audit_observe'):
        return None, 'observe_upgrade'
    return matches[0], None


def observation_availability(db, row):
    policy = aidr_policy.current(db, row.client_id)
    if not policy['skill_audit']['enabled']:
        return 'audit_disabled'
    client = db.query(models.ManagedClient).filter_by(client_id=row.client_id).first()
    if not client or client.status != 'online' or not client.last_seen_at or client.last_seen_at < datetime.utcnow() - timedelta(minutes=2):
        return 'observe_offline'
    return observe_target(db, row)[1]


def task_view(task):
    value = json.loads(task.payload_json)
    return {'id':str(task.id), 'status':task.status, 'error_code':task.error,
            'created_at':task.created_at.isoformat()+'Z',
            'finished_at':task.finished_at.isoformat()+'Z' if task.finished_at else None,
            'observation':value.get('observation')}


def detail(db, row, before=0):
    item = refresh(db, row, registry_manager(), hydrate=True)
    db.flush()
    query = db.query(AidrSkillCheck).filter_by(usage_id=row.id, client_id=row.client_id, expired_at=None)
    if before:
        query = query.filter(AidrSkillCheck.id < before)
    checks = query.order_by(AidrSkillCheck.id.desc()).limit(51).all()
    tasks = db.query(models.ClientTask).filter_by(client_id=row.client_id, task_type='aidr_skill_observe').filter(
        func.json_extract(models.ClientTask.payload_json, '$.usage_id') == row.id).order_by(models.ClientTask.id.desc()).limit(20).all()
    for task in tasks:
        expire_task(task)
    return {**item, 'checks':[{'id':str(c.id), **json.loads(c.payload_json)} for c in checks[:50]],
            'checks_more':len(checks) > 50, 'checks_cursor':str(checks[49].id) if len(checks) > 50 else '',
            'tasks':[task_view(t) for t in tasks], 'observe_unavailable':observation_availability(db, row)}


def create_observation(db, row, request_id, actor):
    # Acquire the SQLite writer before checking active tasks, serializing double
    # clicks from separate requests without relying on a disabled UI button.
    db.query(AidrSkillUse).filter_by(id=row.id).update({'next_check_at':AidrSkillUse.next_check_at})
    key = hashlib.sha256(dump([row.client_id, row.id, request_id]).encode()).hexdigest()
    previous = db.query(models.ClientTask).filter_by(request_key=key).first()
    if previous:
        return task_view(previous)
    active = db.query(models.ClientTask).filter_by(client_id=row.client_id, task_type='aidr_skill_observe').filter(
        models.ClientTask.status.in_(['pending','running']), func.json_extract(models.ClientTask.payload_json, '$.usage_id') == row.id).all()
    for task in active:
        if expire_task(task):
            continue
        return task_view(task)
    reason = observation_availability(db, row)
    if reason:
        fail(reason, '当前不能重新采集，请检查设备、路径与审计策略', 'Recollection is unavailable; check the device, path and audit policy')
    agent, _ = observe_target(db, row)
    data = json.loads(row.payload_json)
    payload = {'usage_id':row.id, 'call_key':row.call_key, 'skill':data['skill'], 'agent_type':agent.agent_type,
               'local_agent_id':agent.local_agent_id, 'actor':actor, 'expires_at':(datetime.utcnow()+timedelta(minutes=5)).isoformat()+'Z'}
    task = models.ClientTask(client_id=row.client_id, task_type='aidr_skill_observe', payload_json=dump(payload), request_key=key)
    db.add(task)
    db.flush()
    return task_view(task)


def expire_task(task):
    if task.status not in {'pending', 'running'}:
        return False
    # Allow an already-started 30-second read to finish before expiring it.
    deadline = datetime.fromisoformat(json.loads(task.payload_json)['expires_at'].removesuffix('Z'))
    if datetime.utcnow() <= deadline + timedelta(seconds=30):
        return False
    task.status, task.error, task.finished_at = 'failed', 'aidr_skill_observation_expired', datetime.utcnow()
    return True


def observation_policy(db, task):
    if task.task_type != 'aidr_skill_observe' or task.status != 'running':
        fail('observation_task_invalid', '采集任务已失效', 'Observation task is no longer active')
    payload = json.loads(task.payload_json)
    if datetime.fromisoformat(payload['expires_at'].removesuffix('Z')) < datetime.utcnow():
        fail('observation_expired', '采集任务已过期，请重新请求', 'Observation task expired; request again')
    row = usage(db, task.client_id, payload['usage_id'])
    policy = aidr_policy.current(db, task.client_id)
    if not policy['skill_audit']['enabled']:
        fail('audit_disabled', 'Skill 认证核对已关闭', 'Skill audit is disabled')
    target, reason = observe_target(db, row)
    if reason or target.local_agent_id != payload['local_agent_id']:
        fail('source_unknown', '无法确认当前来源路径', 'Current source path cannot be verified')
    payload['audit_policy'] = policy['skill_audit']
    payload['audit_policy_version'] = str(policy['version'])
    task.payload_json = dump(payload)
    return payload


def complete_observation(db, task, receipt):
    payload = json.loads(task.payload_json)
    db.query(AidrSkillUse).filter_by(id=payload['usage_id'], client_id=task.client_id).update({'next_check_at':AidrSkillUse.next_check_at})
    row = usage(db, task.client_id, payload['usage_id'])
    db.refresh(row)
    policy = aidr_policy.current(db, task.client_id)
    if not policy['skill_audit']['enabled'] or receipt.policy_version != str(policy['version']) or receipt.policy_version != payload.get('audit_policy_version'):
        fail('observation_policy_changed', '审计策略已变化，请重新采集', 'Audit policy changed; request a new observation')
    data = json.loads(row.payload_json)
    skill = receipt.skill.model_dump(exclude_none=True)
    if row.call_key != payload['call_key'] or any(skill.get(k, '') != payload['skill'].get(k, '') for k in ('path','name','behavior','basis','phase')):
        fail('observation_mismatch', '采集回执与原记录不一致', 'Observation receipt does not match the record')
    observation = {'task_id':str(task.id), **receipt.model_dump(exclude_none=True)}
    data['latest_observation'] = observation
    row.payload_json = dump(data)
    db.flush()
    refresh(db, row, registry_manager())
    payload['observation'] = observation
    task.payload_json = dump(payload)
