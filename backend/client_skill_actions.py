"""Authorize content-bound client remediation tasks."""

import hashlib
import json
from pathlib import Path

from sqlalchemy.dialects.sqlite import insert

from agent_manager.core.models import SkillStatus
from . import client_governance, models, schemas
from .api_errors import ApiError
from .client_signing import compute_content_signature


def create_action(db, client, body: schemas.ClientSkillActionRequest, actor: str, manager):
    request = body.model_dump(mode="json")
    key = hashlib.sha256(json.dumps([client.client_id, body.request_id]).encode()).hexdigest()
    previous = db.query(models.ClientTask).filter_by(request_key=key).first()
    if previous:
        if json.loads(previous.payload_json).get("request") != request:
            raise ApiError(409, "client.action_request_conflict", "请求 ID 已用于其他操作", "The request ID was used for another action")
        return previous
    policy = client_governance.policy_view(db, client.client_id)
    if not policy["supported"]:
        raise ApiError(409, "client.action_protocol_unsupported", "请先升级并同步客户端", "Upgrade and synchronize the Client first")
    agents = db.query(models.ClientAgent).filter_by(client_id=client.client_id, agent_type=body.agent_type)
    if body.local_agent_id:
        agents = agents.filter_by(local_agent_id=body.local_agent_id)
    target = next((agent for agent in agents.all() if agent.skill_management_supported and agent.skills_path
                   and json.loads(agent.capabilities_json or "{}").get("path_available") is not False), None)
    if not target:
        raise ApiError(409, "client.action_target_unavailable", "目标 Agent 目录不可用", "The target Agent directory is unavailable")
    skill = db.query(models.ClientSkillInstall).filter_by(
        client_id=client.client_id, agent_type=body.agent_type, skill_path=body.path,
    ).first()
    recovery = None
    if body.action in {"restore_quarantine", "restore_backup"}:
        record = db.query(models.ClientRecoveryRecord).filter_by(client_id=client.client_id, record_id=body.quarantine_id).first()
        recovery = json.loads(record.details_json) if record else None
        if not recovery or recovery["agent_type"] != body.agent_type or recovery["original_path"] != body.path or recovery["signature"] != body.expected_signature:
            raise ApiError(409, "client.recovery_content_changed", "恢复副本不存在或内容已变化，请同步后重试", "The recovery copy is missing or changed; synchronize and retry")
        if body.action == "restore_backup":
            if recovery["status"] != "backed_up" or (skill.signature if skill else None) != body.expected_target_signature:
                raise ApiError(409, "client.skill_content_changed", "目标目录内容已变化，请同步后重试", "Target directory content changed; synchronize and retry")
        elif skill:
            raise ApiError(409, "client.recovery_path_occupied", "原目录已有内容，请先处理当前文件", "The original directory contains content; handle the current files first")
    elif not skill or skill.signature != body.expected_signature:
        raise ApiError(409, "client.skill_content_changed", "清单内容已变化，请同步后重试", "Inventory content changed; synchronize and retry")
    payload = {
        "action": body.action, "agent_type": body.agent_type, "local_agent_id": target.local_agent_id,
        "path": body.path, "expected_signature": body.expected_signature, "skill_name": recovery["skill_name"] if recovery else skill.skill_name,
        "managed_agent_id": target.managed_agent_id, "policy_version": policy["version"],
        "source": "manual", "actor": actor, "request": request,
    }
    if recovery:
        payload["quarantine_id"] = body.quarantine_id
        if body.action == "restore_backup":
            payload["expected_target_signature"] = body.expected_target_signature
    if body.action == "restore_trusted":
        observation = json.loads(skill.governance_json or "{}")
        version_id = body.version_id or observation.get("trusted_version_id")
        entry = manager.get_skill(version_id) if version_id else None
        if not entry or entry.status not in (SkillStatus.APPROVED, SkillStatus.DEPLOYED) or not entry.skill_path:
            raise ApiError(409, "client.trusted_version_unavailable", "没有可恢复的可信版本", "No trusted version is available for recovery")
        bound_agent = db.query(models.ManagedAgent).filter_by(agent_id=target.managed_agent_id).first() if target.managed_agent_id else None
        allowed = {str(value) for value in json.loads(bound_agent.skill_names_json or "[]")} if bound_agent else set()
        family = getattr(entry, "family_id", None) or entry.skill_id
        expected_family = observation.get("trusted_skill_id") or skill.skill_id
        if expected_family and expected_family not in {entry.skill_id, family}:
            raise ApiError(409, "client.trusted_version_mismatch", "指定版本不属于当前 Skill", "The selected version does not belong to this Skill")
        if not expected_family and entry.name != skill.skill_name:
            raise ApiError(409, "client.trusted_version_mismatch", "指定版本不属于当前 Skill", "The selected version does not belong to this Skill")
        if client.governance_mode == "strict" and not {entry.name, entry.skill_id, family}.intersection(allowed):
            raise ApiError(403, "client.skill_not_authorized", "Agent 未获授权使用此可信版本", "The Agent is not authorized to use this trusted version")
        payload.update(skill_id=family, version_id=entry.skill_id,
                       trusted_signature=compute_content_signature(Path(entry.skill_path)))
    serialized = json.dumps(payload, ensure_ascii=False)
    db.execute(insert(models.ClientTask).values(
        client_id=client.client_id, task_type="skill_action", payload_json=serialized, request_key=key,
    ).on_conflict_do_nothing(index_elements=[models.ClientTask.request_key]))
    task = db.query(models.ClientTask).filter_by(request_key=key).one()
    if json.loads(task.payload_json).get("request") != request:
        raise ApiError(409, "client.action_request_conflict", "请求 ID 已用于其他操作", "The request ID was used for another action")
    return task
