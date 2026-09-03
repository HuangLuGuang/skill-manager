from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..api_errors import ApiError
from ..runtime_trace_schemas import RuntimeTraceInternalEvent
from ..security_audit import append_security_audit
from ..services.runtime_traces import best_effort_trace_publisher, publish_events_best_effort
from ..sqlite_db import get_db
from .access_tokens import ensure_token_agent_allowed, resolve_access_token

router = APIRouter(prefix="/v1/runtime-governance", tags=["runtime-governance"])
logger = logging.getLogger(__name__)

DEFAULT_POLICY = {
    "max_steps": 50,
    "max_retries": 3,
    "max_delegation_depth": 2,
    "max_cost_microunits": 1_000_000,
    "max_data_bytes": 10 * 1024 * 1024,
    "max_duration_seconds": 1800,
    "circuit_failure_threshold": 5,
    "circuit_cooldown_seconds": 300,
    "goal_drift_threshold": 0.85,
}
MUTATING_ACTION_HINTS = {"write", "delete", "send", "execute", "deploy", "install", "update", "create", "invoke"}
MEMORY_SCAN_RULES = (
    ("prompt_injection", re.compile(r"(?i)(ignore|disregard).{0,40}(previous|system|developer).{0,30}(instruction|prompt)")),
    ("credential_material", re.compile(r"(?i)(api[_ -]?key|password|secret|bearer\s+[a-z0-9._-]{12,})")),
    ("command_execution", re.compile(r"(?i)(curl\s+https?://|wget\s+https?://|rm\s+-rf|powershell\s+-enc)")),
)


@best_effort_trace_publisher
def _publish_governance_event(
    db: Session,
    task: models.RuntimeTask,
    event_type: str,
    *,
    status: str,
    payload: dict[str, Any],
    request_id: str | None = None,
    call_id: str | None = None,
    parent_call_id: str | None = None,
    risk_codes: list[str] | None = None,
) -> None:
    publish_events_best_effort(
        db,
        [
            RuntimeTraceInternalEvent(
                trace_id=task.trace_id,
                tenant_id=task.tenant_id,
                agent_id=task.agent_id,
                session_id=task.session_id,
                owner_user_id=int(task.user_id) if str(task.user_id).isdigit() else None,
                source="runtime_governance",
                type=event_type,
                request_id=request_id or task.task_id,
                call_id=call_id,
                parent_call_id=parent_call_id,
                status=status,
                risk_codes=risk_codes or [],
                payload=payload,
            )
        ],
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _digest(value: Any) -> str:
    raw = value if isinstance(value, str) else _json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _runtime_token(
    request: Request,
    authorization: str | None,
    db: Session,
    scope: str,
) -> models.AccessToken:
    token = resolve_access_token(
        db,
        authorization,
        required_scope=scope,
        request=request,
        allowed_token_types={"agent_runtime"},
    )
    request.state.security_actor = f"access-token:{token.token_prefix}"
    return token


def _ensure_subject_binding(token: models.AccessToken, tenant_id: str, user_id: str) -> None:
    if token.group_id is not None and tenant_id != str(token.group_id):
        raise ApiError(403, "runtime.tenant_binding_mismatch", "凭证绑定的租户不匹配", "The credential tenant binding does not match")
    if token.user_id is not None and user_id != str(token.user_id):
        raise ApiError(403, "runtime.user_binding_mismatch", "凭证绑定的用户不匹配", "The credential user binding does not match")


def _policy_dict(row: models.RuntimePolicy | None) -> dict[str, Any]:
    if not row:
        return dict(DEFAULT_POLICY)
    return {key: getattr(row, key) for key in DEFAULT_POLICY}


def _get_policy(db: Session, agent_id: str) -> dict[str, Any]:
    return _policy_dict(db.query(models.RuntimePolicy).filter(models.RuntimePolicy.agent_id == agent_id).first())


def _task(db: Session, task_id: str, token: models.AccessToken | None = None) -> models.RuntimeTask:
    row = db.query(models.RuntimeTask).filter(models.RuntimeTask.task_id == task_id).first()
    if not row:
        raise ApiError(404, "runtime.task_not_found", "运行时任务不存在", "Runtime task not found")
    if token and row.token_id != token.id:
        raise ApiError(403, "runtime.task_token_mismatch", "该凭证无权访问此任务", "The credential cannot access this task")
    return row


def _action(db: Session, action_id: str, task: models.RuntimeTask) -> models.RuntimeAction:
    row = db.query(models.RuntimeAction).filter(
        models.RuntimeAction.action_id == action_id,
        models.RuntimeAction.task_id == task.task_id,
    ).first()
    if not row:
        raise ApiError(404, "runtime.action_not_found", "运行时动作不存在", "Runtime action not found")
    return row


def _target_allowed(target: str, allowed_targets: list[str]) -> bool:
    if not allowed_targets:
        return True
    value = target.rstrip("/")
    return any(value == item.rstrip("/") or value.startswith(item.rstrip("/") + "/") for item in allowed_targets)


def _goal_tokens(value: str) -> set[str]:
    lowered = value.lower()
    words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    words.update(cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
    return words


def _drift_score(goal: str, plan_step: str) -> float:
    goal_tokens = _goal_tokens(goal)
    plan_tokens = _goal_tokens(plan_step)
    if not goal_tokens or not plan_tokens:
        return 0.0
    overlap = len(goal_tokens & plan_tokens) / max(1, len(plan_tokens))
    return round(max(0.0, 1.0 - overlap), 4)


def _active_kill_reason(db: Session, task: models.RuntimeTask, action_type: str) -> str | None:
    candidates = {
        ("global", "*"),
        ("tenant", task.tenant_id),
        ("user", task.user_id),
        ("agent", task.agent_id),
        ("tool", action_type),
    }
    rows = db.query(models.RuntimeKillSwitch).filter(models.RuntimeKillSwitch.active.is_(True)).all()
    for row in rows:
        if (row.scope_type, row.scope_id) in candidates:
            return row.reason
    return None


def _circuit_open(db: Session, subject_type: str, subject_id: str) -> bool:
    row = db.query(models.RuntimeCircuit).filter(
        models.RuntimeCircuit.subject_type == subject_type,
        models.RuntimeCircuit.subject_id == subject_id,
    ).first()
    if not row or row.state != "open":
        return False
    if row.open_until and row.open_until <= datetime.utcnow():
        row.state = "closed"
        row.failure_count = 0
        row.updated_at = datetime.utcnow()
        db.commit()
        return False
    return True


def _audit(event_type: str, task: models.RuntimeTask, outcome: str, details: dict[str, Any]) -> None:
    try:
        append_security_audit(
            event_type=event_type,
            actor=f"agent:{task.agent_id}",
            resource_type="runtime_task",
            resource_id=task.task_id,
            action="authorize",
            outcome=outcome,
            details=details,
        )
    except Exception:
        logger.exception("Failed to append runtime governance audit for task %s", task.task_id)


def _task_response(row: models.RuntimeTask) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "agent_id": row.agent_id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "trace_id": row.trace_id,
        "original_goal": row.original_goal,
        "goal_digest": row.goal_digest,
        "allowed_actions": _loads(row.allowed_actions_json, []),
        "allowed_targets": _loads(row.allowed_targets_json, []),
        "status": row.status,
        "preview": row.preview,
        "usage": {
            "steps": row.step_count,
            "retries": row.retry_count,
            "delegation_depth": row.max_delegation_seen,
            "cost_microunits": row.cost_microunits,
            "data_bytes": row.data_bytes,
        },
        "policy": _loads(row.policy_snapshot_json, {}),
        "stop_reason": row.stop_reason,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
    }


def _action_response(row: models.RuntimeAction) -> dict[str, Any]:
    return {
        "action_id": row.action_id,
        "task_id": row.task_id,
        "parent_action_id": row.parent_action_id,
        "stage": row.stage,
        "action_type": row.action_type,
        "target": row.target,
        "resource": row.resource,
        "risk_level": row.risk_level,
        "plan_step": row.plan_step,
        "parameters_hash": row.parameters_hash,
        "expected_side_effects": _loads(row.expected_side_effects_json, []),
        "approval_context": _loads(row.approval_context_json, {}),
        "decision": row.decision,
        "decision_reasons": _loads(row.decision_reasons_json, []),
        "drift_score": row.drift_score,
        "status": row.status,
        "result": _loads(row.result_json, {}),
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


@router.get("/policies/{agent_id}")
async def get_runtime_policy(
    agent_id: str,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    return {"agent_id": agent_id, **_get_policy(db, agent_id)}


@router.put("/policies/{agent_id}")
async def update_runtime_policy(
    agent_id: str,
    body: schemas.RuntimePolicyUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    if not db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == agent_id).first():
        raise ApiError(404, "agent.not_found", "智能体不存在", "Agent not found")
    row = db.query(models.RuntimePolicy).filter(models.RuntimePolicy.agent_id == agent_id).first()
    if not row:
        row = models.RuntimePolicy(agent_id=agent_id, created_by=current_user.username)
        db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return {"agent_id": agent_id, **_policy_dict(row)}


@router.post("/approvals")
async def create_runtime_approval(
    body: schemas.RuntimeApprovalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    task = _task(db, body.task_id)
    if task.status != "active":
        raise ApiError(409, "runtime.task_not_active", "运行时任务已停止", "The runtime task is not active")
    row = models.RuntimeApproval(
        approval_id="rap_" + uuid.uuid4().hex,
        task_id=body.task_id,
        action_type=body.action_type,
        target=body.target,
        parameters_hash=_digest(body.parameters),
        expires_at=datetime.utcnow() + timedelta(seconds=body.ttl_seconds),
        approved_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _publish_governance_event(
        db,
        task,
        "approval.resolved",
        status="approved",
        payload={
            "approval_id": row.approval_id,
            "action_type": row.action_type,
            "target": row.target,
            "expires_at": row.expires_at.isoformat(),
            "approved_by": row.approved_by,
        },
    )
    return {
        "approval_id": row.approval_id,
        "task_id": row.task_id,
        "action_type": row.action_type,
        "target": row.target,
        "parameters_hash": row.parameters_hash,
        "expires_at": row.expires_at,
        "approved_by": row.approved_by,
    }


@router.post("/tasks/start")
async def start_runtime_task(
    body: schemas.RuntimeTaskStart,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:govern")
    ensure_token_agent_allowed(db, token, body.agent_id)
    _ensure_subject_binding(token, body.tenant_id, body.user_id)
    policy = _get_policy(db, body.agent_id)
    row = models.RuntimeTask(
        task_id="rt_" + uuid.uuid4().hex,
        token_id=token.id,
        agent_id=body.agent_id,
        tenant_id=body.tenant_id,
        user_id=body.user_id,
        session_id=body.session_id,
        trace_id=body.trace_id or "trc_" + uuid.uuid4().hex,
        original_goal=body.original_goal,
        goal_digest=_digest(body.original_goal),
        allowed_actions_json=_json(sorted(set(body.allowed_actions))),
        allowed_targets_json=_json(sorted(set(body.allowed_targets))),
        preview=body.preview,
        policy_snapshot_json=_json(policy),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _audit("runtime_task_started", row, "success", {"preview": row.preview})
    _publish_governance_event(
        db,
        row,
        "policy.decision",
        status="active",
        payload={"task_id": row.task_id, "preview": row.preview, "policy": policy},
    )
    return _task_response(row)


@router.post("/tasks/{task_id}/actions/authorize")
async def authorize_runtime_action(
    task_id: str,
    body: schemas.RuntimeActionAuthorize,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:govern")
    task = _task(db, task_id, token)
    ensure_token_agent_allowed(db, token, task.agent_id)
    policy = _loads(task.policy_snapshot_json, DEFAULT_POLICY)
    reasons: list[str] = []
    now = datetime.utcnow()
    if task.status != "active":
        reasons.append("task_not_active")
    if (now - task.created_at).total_seconds() > int(policy["max_duration_seconds"]):
        reasons.append("duration_limit_exceeded")
    kill_reason = _active_kill_reason(db, task, body.action_type)
    if kill_reason:
        reasons.append("kill_switch_active")
    if _circuit_open(db, "agent", task.agent_id) or _circuit_open(db, "tool", body.action_type):
        reasons.append("circuit_open")
    allowed_actions = _loads(task.allowed_actions_json, [])
    if allowed_actions and body.action_type not in allowed_actions:
        reasons.append("action_not_in_contract")
    if not _target_allowed(body.target, _loads(task.allowed_targets_json, [])):
        reasons.append("target_not_in_contract")
    if body.parent_action_id and not db.query(models.RuntimeAction).filter(
        models.RuntimeAction.action_id == body.parent_action_id,
        models.RuntimeAction.task_id == task.task_id,
    ).first():
        reasons.append("parent_action_not_found")
    if body.stage == "executor":
        if task.step_count + 1 > int(policy["max_steps"]):
            reasons.append("step_limit_exceeded")
        if body.retry_count > int(policy["max_retries"]):
            reasons.append("retry_limit_exceeded")
        if body.delegation_depth > int(policy["max_delegation_depth"]):
            reasons.append("delegation_limit_exceeded")
        if task.cost_microunits + body.estimated_cost_microunits > int(policy["max_cost_microunits"]):
            reasons.append("cost_limit_exceeded")
        if task.data_bytes + body.estimated_data_bytes > int(policy["max_data_bytes"]):
            reasons.append("data_limit_exceeded")
    drift = _drift_score(task.original_goal, body.plan_step)
    if drift > float(policy["goal_drift_threshold"]):
        reasons.append("goal_drift_detected")
    approval = None
    if body.risk_level == "high":
        approval_id = str(body.approval_context.get("approval_id") or "")
        approval = db.query(models.RuntimeApproval).filter(
            models.RuntimeApproval.approval_id == approval_id,
            models.RuntimeApproval.task_id == task.task_id,
            models.RuntimeApproval.action_type == body.action_type,
            models.RuntimeApproval.target == body.target,
            models.RuntimeApproval.parameters_hash == _digest(body.parameters),
            models.RuntimeApproval.status == "active",
            models.RuntimeApproval.expires_at > now,
        ).first()
        if not approval:
            reasons.append("high_risk_approval_required")
    inferred_mutation = any(hint in body.action_type.lower() for hint in MUTATING_ACTION_HINTS)
    if task.preview and (body.network_access or body.state_change or inferred_mutation):
        reasons.append("preview_side_effect_blocked")

    decision = "deny" if reasons else ("preview" if task.preview or body.stage == "planner" else "allow")
    if decision == "allow" and body.stage == "executor":
        updated = db.query(models.RuntimeTask).filter(
            models.RuntimeTask.id == task.id,
            models.RuntimeTask.status == "active",
            models.RuntimeTask.step_count < int(policy["max_steps"]),
            models.RuntimeTask.cost_microunits + body.estimated_cost_microunits <= int(policy["max_cost_microunits"]),
            models.RuntimeTask.data_bytes + body.estimated_data_bytes <= int(policy["max_data_bytes"]),
        ).update({
            models.RuntimeTask.step_count: models.RuntimeTask.step_count + 1,
            models.RuntimeTask.cost_microunits: models.RuntimeTask.cost_microunits + body.estimated_cost_microunits,
            models.RuntimeTask.data_bytes: models.RuntimeTask.data_bytes + body.estimated_data_bytes,
            models.RuntimeTask.updated_at: now,
        }, synchronize_session=False)
        if updated != 1:
            reasons.append("concurrent_budget_limit_exceeded")
            decision = "deny"
        else:
            db.refresh(task)
    plain_authorization = None
    expires_at = None
    if decision == "allow":
        plain_authorization = "rta_" + secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=60)
    row = models.RuntimeAction(
        action_id="ra_" + uuid.uuid4().hex,
        task_id=task.task_id,
        parent_action_id=body.parent_action_id,
        stage=body.stage,
        action_type=body.action_type,
        target=body.target,
        resource=body.resource,
        risk_level=body.risk_level,
        plan_step=body.plan_step,
        parameters_hash=_digest(body.parameters),
        parameters_json=_json(body.parameters),
        expected_side_effects_json=_json(body.expected_side_effects),
        estimated_cost_microunits=body.estimated_cost_microunits,
        estimated_data_bytes=body.estimated_data_bytes,
        approval_context_json=_json({
            **body.approval_context,
            **({"approved_by": approval.approved_by, "approval_expires_at": approval.expires_at.isoformat()} if approval else {}),
        }),
        decision=decision,
        decision_reasons_json=_json(reasons),
        drift_score=drift,
        authorization_hash=_digest(plain_authorization) if plain_authorization else None,
        authorization_expires_at=expires_at,
        status="authorized" if decision == "allow" else decision,
    )
    db.add(row)
    if body.stage == "executor" and decision == "allow":
        task.retry_count = max(task.retry_count, body.retry_count)
        task.max_delegation_seen = max(task.max_delegation_seen, body.delegation_depth)
        task.updated_at = now
        if approval:
            approval.status = "used"
            approval.used_at = now
    if reasons and any(reason.endswith("limit_exceeded") for reason in reasons):
        task.status = "stopped"
        task.stop_reason = reasons[0]
        task.updated_at = now
    db.commit()
    db.refresh(row)
    _audit("runtime_action_authorized", task, decision, {
        "action_id": row.action_id,
        "action_type": body.action_type,
        "risk_level": body.risk_level,
        "decision_reasons": reasons,
        "parameters_hash": row.parameters_hash,
    })
    _publish_governance_event(
        db,
        task,
        "policy.decision",
        status=decision,
        request_id=row.action_id,
        call_id=row.action_id,
        parent_call_id=row.parent_action_id,
        risk_codes=[f"runtime.{reason}" for reason in reasons],
        payload={
            "action_id": row.action_id,
            "action_type": row.action_type,
            "target": row.target,
            "risk_level": row.risk_level,
            "decision": decision,
            "reasons": reasons,
            "budget": {
                "steps": task.step_count,
                "cost_microunits": task.cost_microunits,
                "data_bytes": task.data_bytes,
            },
            "parameters_hash": row.parameters_hash,
        },
    )
    if decision == "deny":
        _publish_governance_event(
            db,
            task,
            "runtime.blocked",
            status="blocked",
            request_id=row.action_id,
            call_id=row.action_id,
            parent_call_id=row.parent_action_id,
            risk_codes=[f"runtime.{reason}" for reason in reasons],
            payload={"action_id": row.action_id, "reasons": reasons},
        )
    return {
        **_action_response(row),
        "context": {
            "agent_id": task.agent_id,
            "tenant_id": task.tenant_id,
            "user_id": task.user_id,
            "session_id": task.session_id,
            "goal_digest": task.goal_digest,
            "target": row.target,
            "resource": row.resource,
            "risk_level": row.risk_level,
            "approval": _loads(row.approval_context_json, {}),
        },
        "authorization_token": plain_authorization,
        "authorization_expires_at": expires_at,
    }


@router.post("/tasks/{task_id}/actions/{action_id}/consume")
async def consume_runtime_authorization(
    task_id: str,
    action_id: str,
    body: schemas.RuntimeActionConsume,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:govern")
    task = _task(db, task_id, token)
    row = _action(db, action_id, task)
    now = datetime.utcnow()
    if task.status != "active" or _active_kill_reason(db, task, row.action_type):
        raise ApiError(403, "runtime.execution_stopped", "任务已被停止，动作授权失效", "The task has been stopped and the action authorization is invalid")
    if row.decision != "allow" or row.status != "authorized":
        raise ApiError(409, "runtime.authorization_not_active", "动作授权不可用", "The action authorization is not active")
    if not row.authorization_expires_at or row.authorization_expires_at <= now:
        row.status = "expired"
        db.commit()
        raise ApiError(403, "runtime.authorization_expired", "动作授权已过期", "The action authorization has expired")
    if _digest(body.authorization_token) != row.authorization_hash or _digest(body.parameters) != row.parameters_hash:
        raise ApiError(403, "runtime.authorization_mismatch", "动作授权与执行参数不匹配", "The authorization does not match the action parameters")
    updated = db.query(models.RuntimeAction).filter(
        models.RuntimeAction.id == row.id,
        models.RuntimeAction.status == "authorized",
        models.RuntimeAction.authorization_used_at.is_(None),
    ).update({"status": "executing", "authorization_used_at": now}, synchronize_session=False)
    if updated != 1:
        db.rollback()
        raise ApiError(409, "runtime.authorization_replayed", "动作授权已被使用", "The action authorization has already been used")
    db.commit()
    return {"action_id": action_id, "authorized": True, "consumed_at": now}


def _record_circuit_result(db: Session, subject_type: str, subject_id: str, succeeded: bool, error: str | None, policy: dict[str, Any]) -> None:
    row = db.query(models.RuntimeCircuit).filter(
        models.RuntimeCircuit.subject_type == subject_type,
        models.RuntimeCircuit.subject_id == subject_id,
    ).first()
    if not row:
        row = models.RuntimeCircuit(subject_type=subject_type, subject_id=subject_id)
        db.add(row)
    if succeeded:
        row.state = "closed"
        row.failure_count = 0
        row.opened_at = None
        row.open_until = None
        row.last_error = None
    else:
        row.failure_count += 1
        row.last_error = (error or "execution failed")[:2000]
        if row.failure_count >= int(policy["circuit_failure_threshold"]):
            row.state = "open"
            row.opened_at = datetime.utcnow()
            row.open_until = row.opened_at + timedelta(seconds=int(policy["circuit_cooldown_seconds"]))
    row.updated_at = datetime.utcnow()


@router.post("/tasks/{task_id}/actions/{action_id}/result")
async def record_runtime_action_result(
    task_id: str,
    action_id: str,
    body: schemas.RuntimeActionResult,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:govern")
    task = _task(db, task_id, token)
    row = _action(db, action_id, task)
    if row.status != "executing":
        raise ApiError(409, "runtime.action_not_executing", "动作尚未进入执行状态", "The action is not executing")
    now = datetime.utcnow()
    row.status = body.status
    row.result_json = _json({**body.result, **({"error": body.error} if body.error else {})})
    row.completed_at = now
    task.cost_microunits += body.actual_cost_microunits - row.estimated_cost_microunits
    task.data_bytes += body.actual_data_bytes - row.estimated_data_bytes
    task.updated_at = now
    policy = _loads(task.policy_snapshot_json, DEFAULT_POLICY)
    if task.cost_microunits > int(policy["max_cost_microunits"]) or task.data_bytes > int(policy["max_data_bytes"]):
        task.status = "stopped"
        task.stop_reason = "actual_budget_exceeded"
    succeeded = body.status == "succeeded"
    _record_circuit_result(db, "agent", task.agent_id, succeeded, body.error, policy)
    _record_circuit_result(db, "tool", row.action_type, succeeded, body.error, policy)
    db.commit()
    return _action_response(row)


@router.post("/tasks/{task_id}/complete")
async def complete_runtime_task(
    task_id: str,
    body: schemas.RuntimeTaskComplete,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:govern")
    row = _task(db, task_id, token)
    row.status = body.status
    row.stop_reason = body.reason
    row.completed_at = datetime.utcnow()
    row.updated_at = row.completed_at
    db.commit()
    return _task_response(row)


@router.get("/tasks")
async def list_runtime_tasks(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.RuntimeTask)
    if agent_id:
        query = query.filter(models.RuntimeTask.agent_id == agent_id)
    if status:
        query = query.filter(models.RuntimeTask.status == status)
    return [_task_response(row) for row in query.order_by(models.RuntimeTask.id.desc()).limit(limit).all()]


@router.get("/tasks/{task_id}")
async def get_runtime_task(
    task_id: str,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    task = _task(db, task_id)
    actions = db.query(models.RuntimeAction).filter(models.RuntimeAction.task_id == task_id).order_by(models.RuntimeAction.id).all()
    return {**_task_response(task), "actions": [_action_response(row) for row in actions]}


@router.post("/tasks/{task_id}/kill")
async def kill_runtime_task(
    task_id: str,
    reason: str = "管理员终止",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = _task(db, task_id)
    row.status = "killed"
    row.stop_reason = reason
    row.completed_at = datetime.utcnow()
    row.updated_at = row.completed_at
    db.commit()
    _audit("runtime_task_killed", row, "success", {"reason": reason, "actor": current_user.username})
    _publish_governance_event(
        db,
        row,
        "runtime.killed",
        status="killed",
        payload={"reason": reason, "actor": current_user.username},
    )
    return _task_response(row)


@router.get("/kill-switches")
async def list_kill_switches(
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    return [{
        "id": row.id, "scope_type": row.scope_type, "scope_id": row.scope_id, "reason": row.reason,
        "active": row.active, "created_by": row.created_by, "created_at": row.created_at,
        "released_by": row.released_by, "released_at": row.released_at,
    } for row in db.query(models.RuntimeKillSwitch).order_by(models.RuntimeKillSwitch.id.desc()).all()]


@router.post("/kill-switches")
async def create_kill_switch(
    body: schemas.RuntimeKillSwitchCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    scope_id = body.scope_id.strip() or "*"
    existing = db.query(models.RuntimeKillSwitch).filter(
        models.RuntimeKillSwitch.scope_type == body.scope_type,
        models.RuntimeKillSwitch.scope_id == scope_id,
        models.RuntimeKillSwitch.active.is_(True),
    ).first()
    if existing:
        return {"id": existing.id, "active": True}
    row = models.RuntimeKillSwitch(
        scope_type=body.scope_type, scope_id=scope_id, reason=body.reason, created_by=current_user.username,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    affected = db.query(models.RuntimeTask).filter(
        models.RuntimeTask.status == "active",
        models.RuntimeTask.trace_id.is_not(None),
    ).all()
    for task in affected:
        matches = (
            body.scope_type == "global"
            or (body.scope_type == "tenant" and task.tenant_id == scope_id)
            or (body.scope_type == "user" and task.user_id == scope_id)
            or (body.scope_type == "agent" and task.agent_id == scope_id)
            or (
                body.scope_type == "tool"
                and db.query(models.RuntimeAction).filter(
                    models.RuntimeAction.task_id == task.task_id,
                    models.RuntimeAction.action_type == scope_id,
                ).first()
                is not None
            )
        )
        if matches:
            _publish_governance_event(
                db,
                task,
                "runtime.blocked",
                status="kill_switch_active",
                payload={
                    "kill_switch_id": row.id,
                    "scope_type": body.scope_type,
                    "scope_id": scope_id,
                    "reason": body.reason,
                    "actor": current_user.username,
                },
                risk_codes=["runtime.kill_switch_active"],
            )
    return {"id": row.id, "active": True}


@router.delete("/kill-switches/{switch_id}")
async def release_kill_switch(
    switch_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.RuntimeKillSwitch).filter(models.RuntimeKillSwitch.id == switch_id).first()
    if not row:
        raise ApiError(404, "runtime.kill_switch_not_found", "紧急停止开关不存在", "Kill switch not found")
    row.active = False
    row.released_by = current_user.username
    row.released_at = datetime.utcnow()
    db.commit()
    return {"id": row.id, "active": False}


def _scan_memory(content: str) -> list[dict[str, str]]:
    findings = []
    for rule, pattern in MEMORY_SCAN_RULES:
        if pattern.search(content):
            findings.append({"rule": rule, "severity": "high" if rule != "command_execution" else "medium"})
    return findings


def _memory_response(db: Session, row: models.RuntimeMemory, include_content: bool = True) -> dict[str, Any]:
    revision = db.query(models.RuntimeMemoryRevision).filter(
        models.RuntimeMemoryRevision.memory_id == row.memory_id,
        models.RuntimeMemoryRevision.version == row.current_version,
    ).first()
    result = {
        "memory_id": row.memory_id, "tenant_id": row.tenant_id, "user_id": row.user_id,
        "session_id": row.session_id, "agent_id": row.agent_id, "source_type": row.source_type,
        "source_ref": row.source_ref, "trust_status": row.trust_status, "current_version": row.current_version,
        "expires_at": row.expires_at, "quarantined_reason": row.quarantined_reason,
        "content_hash": revision.content_hash if revision else None,
        "provenance": _loads(revision.provenance_json, {}) if revision else {},
        "scan_findings": _loads(revision.scan_findings_json, []) if revision else [],
        "created_at": row.created_at, "updated_at": row.updated_at,
    }
    if include_content:
        result["content"] = revision.content if revision else None
    return result


@router.post("/memory/ingest")
async def ingest_runtime_memory(
    body: schemas.RuntimeMemoryIngest,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:memory")
    ensure_token_agent_allowed(db, token, body.agent_id)
    _ensure_subject_binding(token, body.tenant_id, body.user_id)
    findings = _scan_memory(body.content)
    trust_status = "quarantined" if findings else "untrusted"
    preview_result = {
        "persisted": False, "content_hash": _digest(body.content), "scan_findings": findings,
        "trust_status": trust_status, "network_access": False, "state_changes": False,
    }
    if body.preview:
        return preview_result
    memory_id = body.memory_id or "mem_" + uuid.uuid4().hex
    row = db.query(models.RuntimeMemory).filter(models.RuntimeMemory.memory_id == memory_id).first()
    if row and any((row.tenant_id != body.tenant_id, row.user_id != body.user_id, row.session_id != body.session_id, row.agent_id != body.agent_id)):
        raise ApiError(403, "memory.isolation_violation", "Memory 隔离边界不匹配", "Memory isolation boundary mismatch")
    version = (row.current_version + 1) if row else 1
    if not row:
        row = models.RuntimeMemory(
            memory_id=memory_id, tenant_id=body.tenant_id, user_id=body.user_id,
            session_id=body.session_id, agent_id=body.agent_id, source_type=body.source_type,
        )
        db.add(row)
    row.source_type = body.source_type
    row.source_ref = body.source_ref
    row.trust_status = trust_status
    row.current_version = version
    row.expires_at = body.expires_at
    row.quarantined_reason = findings[0]["rule"] if findings else None
    row.updated_at = datetime.utcnow()
    db.add(models.RuntimeMemoryRevision(
        memory_id=memory_id, version=version, content=body.content, content_hash=_digest(body.content),
        provenance_json=_json({**body.provenance, "source_type": body.source_type, "source_ref": body.source_ref}),
        scan_findings_json=_json(findings), created_by=f"agent:{body.agent_id}",
    ))
    db.commit()
    db.refresh(row)
    return {**_memory_response(db, row), "persisted": True}


@router.get("/memory/query")
async def query_runtime_memory(
    agent_id: str,
    tenant_id: str,
    user_id: str,
    session_id: str,
    request: Request,
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _runtime_token(request, authorization, db, "runtime:memory")
    ensure_token_agent_allowed(db, token, agent_id)
    _ensure_subject_binding(token, tenant_id, user_id)
    query = db.query(models.RuntimeMemory).filter(
        models.RuntimeMemory.agent_id == agent_id,
        models.RuntimeMemory.tenant_id == tenant_id,
        models.RuntimeMemory.user_id == user_id,
        models.RuntimeMemory.session_id == session_id,
        models.RuntimeMemory.trust_status != "quarantined",
    ).filter((models.RuntimeMemory.expires_at.is_(None)) | (models.RuntimeMemory.expires_at > datetime.utcnow()))
    query = query.filter(models.RuntimeMemory.trust_status == "trusted")
    rows = query.order_by(models.RuntimeMemory.updated_at.desc()).limit(200).all()
    return [_memory_response(db, row) for row in rows]


@router.get("/memories")
async def list_runtime_memories(
    trust_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    query = db.query(models.RuntimeMemory)
    if trust_status:
        query = query.filter(models.RuntimeMemory.trust_status == trust_status)
    return [_memory_response(db, row) for row in query.order_by(models.RuntimeMemory.id.desc()).limit(limit).all()]


@router.post("/memories/{memory_id}/review")
async def review_runtime_memory(
    memory_id: str,
    body: schemas.RuntimeMemoryReview,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    row = db.query(models.RuntimeMemory).filter(models.RuntimeMemory.memory_id == memory_id).first()
    if not row:
        raise ApiError(404, "memory.not_found", "Memory 不存在", "Memory not found")
    row.trust_status = body.trust_status
    row.quarantined_reason = body.reason if body.trust_status == "quarantined" else None
    row.updated_at = datetime.utcnow()
    db.commit()
    result = _memory_response(db, row)
    result["reviewed_by"] = current_user.username
    return result


@router.get("/memories/{memory_id}/revisions")
async def list_memory_revisions(
    memory_id: str,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    rows = db.query(models.RuntimeMemoryRevision).filter(
        models.RuntimeMemoryRevision.memory_id == memory_id,
    ).order_by(models.RuntimeMemoryRevision.version.desc()).all()
    return [{
        "version": row.version, "content": row.content, "content_hash": row.content_hash,
        "provenance": _loads(row.provenance_json, {}), "scan_findings": _loads(row.scan_findings_json, []),
        "created_by": row.created_by, "created_at": row.created_at,
    } for row in rows]


@router.post("/memories/{memory_id}/rollback")
async def rollback_runtime_memory(
    memory_id: str,
    body: schemas.RuntimeMemoryRollback,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_admin_user),
):
    memory = db.query(models.RuntimeMemory).filter(models.RuntimeMemory.memory_id == memory_id).first()
    source = db.query(models.RuntimeMemoryRevision).filter(
        models.RuntimeMemoryRevision.memory_id == memory_id,
        models.RuntimeMemoryRevision.version == body.version,
    ).first()
    if not memory or not source:
        raise ApiError(404, "memory.revision_not_found", "Memory 版本不存在", "Memory revision not found")
    new_version = memory.current_version + 1
    db.add(models.RuntimeMemoryRevision(
        memory_id=memory_id, version=new_version, content=source.content, content_hash=source.content_hash,
        provenance_json=_json({**_loads(source.provenance_json, {}), "rollback_from": body.version}),
        scan_findings_json=source.scan_findings_json, created_by=current_user.username,
    ))
    memory.current_version = new_version
    memory.trust_status = "untrusted"
    memory.updated_at = datetime.utcnow()
    db.commit()
    return _memory_response(db, memory)


@router.post("/replay/{task_id}")
async def replay_runtime_task(
    task_id: str,
    db: Session = Depends(get_db),
    _current_user: models.User = Depends(auth.get_current_admin_user),
):
    task = _task(db, task_id)
    policy = _get_policy(db, task.agent_id)
    actions = db.query(models.RuntimeAction).filter(models.RuntimeAction.task_id == task_id).order_by(models.RuntimeAction.id).all()
    replayed = []
    allowed_steps = 0
    for row in actions:
        reasons = []
        if row.stage == "executor":
            allowed_steps += 1
            if allowed_steps > int(policy["max_steps"]):
                reasons.append("step_limit_exceeded")
        if row.drift_score > float(policy["goal_drift_threshold"]):
            reasons.append("goal_drift_detected")
        if task.preview and (row.expected_side_effects_json != "[]" or any(hint in row.action_type.lower() for hint in MUTATING_ACTION_HINTS)):
            reasons.append("preview_side_effect_blocked")
        replayed.append({"action_id": row.action_id, "original_decision": row.decision, "replay_decision": "deny" if reasons else "allow", "reasons": reasons})
    changed = [item for item in replayed if item["original_decision"] != item["replay_decision"]]
    return {
        "task_id": task_id, "isolated": True, "network_access": False, "state_changes": False,
        "actions": replayed, "changed_count": len(changed), "blast_radius": [item["action_id"] for item in changed],
    }
