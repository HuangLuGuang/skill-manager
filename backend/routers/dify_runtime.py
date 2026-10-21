"""Dify application bindings and execution control using shared runtime records."""
import hashlib
import hmac
import json
import uuid
from functools import wraps
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Request

from .. import auth, models
from ..api_errors import ApiError
from ..dify_runtime_schemas import BindingCreate, Call, Consume, Heartbeat, Observation, Policy, PolicyUpdate, Result, Review, RunStart
from ..runtime_trace_schemas import RuntimeTraceBatchCreate, RuntimeTraceEventInput
from ..services.runtime_traces import create_trace, ingest_batch, ingest_transaction
from ..sqlite_db import get_db
from .access_tokens import ensure_token_agent_allowed, resolve_access_token, acquire_access_token_slot, release_access_token_slot
from .runtime_governance import _active_kill_reason

router = APIRouter(prefix="/v1/dify-runtime", tags=["dify-runtime"])


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fail(code, status=409):
    raise ApiError(status, f"dify_runtime.{code}", "Dify 运行请求未通过校验", "Dify runtime request validation failed",
                   params={"reason": code})


transaction = get_db


def atomic(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        db = kwargs["db"]
        # Keep the reentrant ingest lock and SQLite transaction in one worker thread.
        with ingest_transaction(db):
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            return function(*args, **kwargs)
    return wrapped


async def runtime_token(request: Request, authorization: str | None = Header(None), db=Depends(get_db)):
    token = resolve_access_token(db, authorization, required_scope="runtime:trace", request=request,
                                 allowed_token_types={"agent_runtime"})
    ensure_token_agent_allowed(db, token, token.bound_agent_id)
    if len(await request.body()) > token.max_body_kb * 1024:
        fail("body_too_large", 413)
    acquire_access_token_slot(token)
    try:
        yield token
    finally:
        release_access_token_slot(token)


def binding(db, binding_id, token=None):
    row = db.get(models.DifyRuntimeBinding, binding_id)
    if not row:
        fail("binding_not_found", 404)
    if token:
        if token.bound_agent_id != row.agent_id:
            fail("binding_mismatch", 403)
        target = db.query(models.SecurityTarget).filter_by(target_id=row.target_id).one()
        if target.owner_group_id is not None:
            if token.group_id != target.owner_group_id:
                fail("owner_mismatch", 403)
        elif target.owner_user_id != token.user_id:
            fail("owner_mismatch", 403)
        if row.mode == "disabled":
            fail("disabled", 403)
        if row.mode == "enforce" and "runtime:govern" not in json.loads(token.scopes_json):
            fail("scope_required", 403)
    return row


def run_context(db, task_id, token):
    run = db.get(models.DifyRuntimeRun, task_id)
    task = db.query(models.RuntimeTask).filter_by(task_id=task_id).first()
    if not run or not task:
        fail("run_not_found", 404)
    row = binding(db, run.binding_id, token)
    if task.token_id != token.id:
        fail("credential_mismatch", 403)
    return row, run, task


def action_context(db, task_id, action_id, token):
    row, run, task = run_context(db, task_id, token)
    call = db.get(models.DifyRuntimeCall, action_id)
    action = db.query(models.RuntimeAction).filter_by(action_id=action_id, task_id=task_id).first()
    if not call or not action:
        fail("action_not_found", 404)
    return row, run, task, call, action


def event(db, task, call, kind, status, details=None):
    trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=task.trace_id).one()
    payload = json.loads(call.context_json)
    run = db.get(models.DifyRuntimeRun, task.task_id)
    payload.update(graph_digest=run.graph_digest, workflow_id=run.workflow_id)
    payload.update(details or {})
    identifier = "evt_" + uuid.uuid4().hex
    ingest_batch(db, trace, RuntimeTraceBatchCreate(batch_id="bat_" + uuid.uuid4().hex, events=[
        RuntimeTraceEventInput(event_id=identifier, event_time=datetime.utcnow(), source="dify_adapter",
                               type=kind, step_id=call.execution_id, call_id=call.call_id,
                               status=status, tool_name=payload.get("tool") or payload["node_type"],
                               payload=payload, redacted_payload=payload),
    ]), commit=False)


def public_binding(row):
    return {key: getattr(row, key) for key in ("binding_id", "target_id", "agent_id", "instance_id",
                                               "workspace_id", "app_id", "mode", "revision")} | {
        "policy": json.loads(row.policy_json)}


@router.get("/bindings")
def bindings(db=Depends(get_db), user=Depends(auth.get_current_admin_user)):
    return {"items": [public_binding(x) for x in db.query(models.DifyRuntimeBinding).all()]}


@router.post("/bindings")
@atomic
def create_binding(body: BindingCreate, request: Request, db=Depends(transaction), user=Depends(auth.get_current_admin_user)):
    target = db.query(models.SecurityTarget).filter_by(target_id=body.target_id, connector_type="dify").first()
    if not target:
        fail("target_not_found", 404)
    agent = db.query(models.ManagedAgent).filter_by(agent_id=body.agent_id).first()
    if not agent:
        fail("agent_not_found", 404)
    config = json.loads(target.config_json)
    if not config.get("workspace_id") or not config.get("app_id"):
        fail("target_identity_missing", 422)
    existing = db.query(models.DifyRuntimeBinding).filter(
        (models.DifyRuntimeBinding.target_id == body.target_id) |
        (models.DifyRuntimeBinding.agent_id == body.agent_id) |
        ((models.DifyRuntimeBinding.instance_id == body.instance_id) &
         (models.DifyRuntimeBinding.workspace_id == config["workspace_id"]) &
         (models.DifyRuntimeBinding.app_id == config["app_id"]))
    ).first()
    if existing:
        if existing.target_id == body.target_id and existing.agent_id == body.agent_id and existing.instance_id == body.instance_id:
            return public_binding(existing)
        fail("binding_conflict")
    row = models.DifyRuntimeBinding(binding_id="dfr_" + uuid.uuid4().hex, target_id=body.target_id,
                                    agent_id=body.agent_id, instance_id=body.instance_id,
                                    workspace_id=config["workspace_id"], app_id=config["app_id"],
                                    policy_json=encoded(Policy().model_dump()))
    db.add(row)
    from .. import iam
    db.flush()
    iam.audit(db, request, user, "agents", "create", row.binding_id, after=public_binding(row))
    db.commit()
    return public_binding(row)


@router.put("/bindings/{binding_id}")
@atomic
def update_binding(binding_id: str, body: PolicyUpdate, request: Request, db=Depends(transaction),
                   user=Depends(auth.get_current_admin_user)):
    row = binding(db, binding_id)
    if row.revision != body.revision:
        fail("revision_conflict")
    row.mode = body.mode
    row.policy_json = encoded(body.policy.model_dump())
    row.revision += 1
    row.updated_at = datetime.utcnow()
    from .. import iam
    iam.audit(db, request, user, "agents", "update", row.binding_id, after=public_binding(row))
    db.commit()
    return public_binding(row)


@router.post("/bindings/{binding_id}/heartbeat")
@atomic
def heartbeat(binding_id: str, body: Heartbeat, token=Depends(runtime_token), db=Depends(transaction)):
    row = binding(db, binding_id, token)
    process = db.query(models.DifyRuntimeProcess).filter_by(binding_id=binding_id, process_id=body.process_id).first()
    if not process:
        process = models.DifyRuntimeProcess(binding_id=binding_id, process_id=body.process_id)
        db.add(process)
    process.report_json = encoded(body.model_dump())
    process.seen_at = datetime.utcnow()
    db.commit()
    return {"mode": row.mode, "revision": row.revision, "accepted": True}


@router.get("/bindings/{binding_id}/status")
def status(binding_id: str, db=Depends(get_db), user=Depends(auth.get_current_admin_user)):
    row = binding(db, binding_id)
    processes = db.query(models.DifyRuntimeProcess).filter_by(binding_id=binding_id).all()
    runs = db.query(models.DifyRuntimeRun).filter_by(binding_id=binding_id).order_by(
        models.DifyRuntimeRun.task_id.desc()).limit(100).all()
    task_ids = [r.task_id for r in runs]
    calls = db.query(models.DifyRuntimeCall).filter(models.DifyRuntimeCall.task_id.in_(task_ids)).all()
    actions = {x.action_id: x for x in db.query(models.RuntimeAction).filter(
        models.RuntimeAction.task_id.in_(task_ids)).all()}
    return {"binding": public_binding(row),
            "processes": [json.loads(x.report_json) | {"seen_at": x.seen_at,
                "healthy": (datetime.utcnow() - x.seen_at).total_seconds() < 90} for x in processes],
            "runs": [{"task_id": x.task_id, "run_id": x.run_id, "workflow_id": x.workflow_id,
                      "graph_digest": x.graph_digest,
                      "trace_id": db.query(models.RuntimeTask).filter_by(task_id=x.task_id).one().trace_id} for x in runs],
            "calls": [{"action_id": c.action_id, "task_id": c.task_id, **json.loads(c.context_json),
                       "status": actions[c.action_id].status, "decision": actions[c.action_id].decision,
                       "reasons": json.loads(actions[c.action_id].decision_reasons_json),
                       "approval_status": ("expired" if c.approval_status == "pending" and c.approval_deadline < datetime.utcnow()
                                           else c.approval_status)} for c in calls]}


@router.post("/bindings/{binding_id}/runs")
@atomic
def start_run(binding_id: str, body: RunStart, token=Depends(runtime_token), db=Depends(transaction)):
    row = binding(db, binding_id, token)
    if (body.workspace_id, body.app_id) != (row.workspace_id, row.app_id):
        fail("application_mismatch", 403)
    run = db.query(models.DifyRuntimeRun).filter_by(binding_id=binding_id, run_id=body.run_id).first()
    if run:
        if (run.graph_digest, run.workflow_id) != (body.graph_digest, body.workflow_id):
            fail("run_conflict")
        task = db.query(models.RuntimeTask).filter_by(task_id=run.task_id).one()
        if task.token_id != token.id:
            fail("credential_mismatch", 403)
    else:
        trace = create_trace(db, tenant_id=str(token.group_id or "default"), agent_id=row.agent_id,
                             session_id=body.run_id, owner_user_id=token.user_id, owner_group_id=token.group_id,
                             created_by=token.name, commit=False)
        task = models.RuntimeTask(task_id="rt_" + uuid.uuid4().hex, token_id=token.id, agent_id=row.agent_id,
                                  tenant_id=str(token.group_id or "default"), user_id=str(token.user_id or ""),
                                  session_id=body.run_id, trace_id=trace.trace_id,
                                  original_goal="Dify workflow execution", goal_digest=body.graph_digest,
                                  policy_snapshot_json=row.policy_json)
        db.add(task)
        db.flush()
        db.add(models.DifyRuntimeRun(task_id=task.task_id, binding_id=binding_id, run_id=body.run_id,
                                     workflow_id=body.workflow_id, graph_digest=body.graph_digest))
        db.commit()
    return {"task_id": task.task_id, "trace_id": task.trace_id, "mode": row.mode, "revision": row.revision}


def evaluate(db, row, run, task, body):
    policy = Policy.model_validate_json(row.policy_json)
    if task.status != "active" or _active_kill_reason(db, task, body.node_type):
        return "deny", "stopped"
    if policy.approved_graphs and run.graph_digest not in policy.approved_graphs:
        return "deny", "unapproved_graph"
    if task.step_count >= policy.max_actions:
        return "deny", "action_limit"
    for rule in policy.rules:
        fields = ("node_type", "node_id", "tool", "host", "method", "code_digest")
        if any(getattr(rule, k) and getattr(rule, k) != getattr(body, k) for k in fields):
            continue
        if rule.dataset and rule.dataset not in [body.dataset, *body.datasets]:
            continue
        if rule.after_node_type:
            prior = db.query(models.RuntimeAction).filter_by(task_id=task.task_id,
                action_type=rule.after_node_type, status="succeeded").first()
            if not prior:
                continue
        return rule.effect, rule.rule_id
    return policy.default, "default"


def call_response(row, task, call, action):
    response = {"task_id": task.task_id, "action_id": action.action_id, "decision": action.decision,
                "status": action.status, "approval_status": call.approval_status,
                "reasons": json.loads(action.decision_reasons_json), "mode": row.mode, "revision": row.revision}
    # A deterministic capability can be returned again after a lost response; only its hash is stored.
    if action.status == "authorized":
        from ..config import settings
        value = hmac.new(settings.SECRET_KEY.encode(), action.action_id.encode(), hashlib.sha256).hexdigest()
        response["authorization_token"] = value
    return response


@router.post("/runs/{task_id}/authorize")
@atomic
def authorize(task_id: str, body: Call, token=Depends(runtime_token), db=Depends(transaction)):
    row, run, task = run_context(db, task_id, token)
    context = body.model_dump()
    call = db.query(models.DifyRuntimeCall).filter_by(task_id=task_id, call_id=body.call_id).first()
    if call:
        if json.loads(call.context_json) != context:
            fail("call_conflict")
        action = db.query(models.RuntimeAction).filter_by(action_id=call.action_id).one()
        if call.revision != row.revision:
            if action.status in {"pending", "authorized"}:
                action.status = "blocked"
                action.decision = "deny"
                action.decision_reasons_json = encoded(["policy_changed"])
                call.approval_status = "revoked"
                db.commit()
            return call_response(row, task, call, action)
        if call.approval_status == "pending" and call.approval_deadline <= datetime.utcnow():
            call.approval_status = "expired"
            action.status = "expired"
            db.commit()
        return call_response(row, task, call, action)
    decision, reason = evaluate(db, row, run, task, body)
    effective = decision if row.mode == "enforce" else "allow"
    action_id = "ra_" + uuid.uuid4().hex
    from ..config import settings
    capability = hmac.new(settings.SECRET_KEY.encode(), action_id.encode(), hashlib.sha256).hexdigest()
    action = models.RuntimeAction(action_id=action_id, task_id=task_id, stage="executor",
        action_type=body.node_type, target=body.host or body.tool or body.dataset or body.node_id,
        risk_level="high" if decision != "allow" else "low", plan_step=body.node_id,
        parameters_hash=body.input_digest, parameters_json="{}", decision=effective,
        decision_reasons_json=encoded([reason]), drift_score=0,
        authorization_hash=digest(capability) if effective == "allow" else None,
        authorization_expires_at=datetime.utcnow() + timedelta(seconds=60),
        status={"allow": "authorized", "deny": "blocked", "approval": "pending"}[effective])
    call = models.DifyRuntimeCall(action_id=action_id, task_id=task_id, call_id=body.call_id,
        node_id=body.node_id, execution_id=body.execution_id, revision=row.revision,
        context_json=encoded(context), approval_status="pending" if effective == "approval" else "none",
        approval_deadline=datetime.utcnow() + timedelta(seconds=Policy.model_validate_json(row.policy_json).approval_seconds))
    db.add_all([action, call])
    db.flush()
    event(db, task, call, "policy.decision", effective, {"would_decide": decision, "rule_id": reason})
    if effective == "deny":
        event(db, task, call, "runtime.blocked", "blocked")
    if effective == "approval":
        event(db, task, call, "approval.requested", "pending")
    db.commit()
    return call_response(row, task, call, action)


@router.post("/runs/{task_id}/actions/{action_id}/consume")
@atomic
def consume(task_id: str, action_id: str, body: Consume, token=Depends(runtime_token), db=Depends(transaction)):
    row, run, task, call, action = action_context(db, task_id, action_id, token)
    if task.status != "active" or _active_kill_reason(db, task, action.action_type):
        fail("stopped", 403)
    if row.revision != call.revision:
        fail("policy_changed", 403)
    if action.status != "authorized" or action.authorization_expires_at <= datetime.utcnow():
        fail("authorization_inactive", 403)
    if not hmac.compare_digest(digest(body.authorization_token), action.authorization_hash or "") or body.input_digest != action.parameters_hash:
        fail("authorization_mismatch", 403)
    decision, reason = evaluate(db, row, run, task, Call.model_validate_json(call.context_json))
    if row.mode == "enforce" and (decision == "deny" or (decision == "approval" and call.approval_status != "approved")):
        fail(reason if reason in {"action_limit", "stopped", "unapproved_graph"} else "policy_denied", 403)
    action.status = "executing"
    action.authorization_used_at = datetime.utcnow()
    for approval in db.query(models.RuntimeApproval).filter_by(task_id=task_id, action_type=action.action_type,
            parameters_hash=action.parameters_hash, target=action.target, status="active").all():
        approval.status = "used"
        approval.used_at = datetime.utcnow()
    task.step_count += 1
    event(db, task, call, "tool.call", "started")
    db.commit()
    return {"authorized": True, "action_id": action_id}


@router.post("/runs/{task_id}/actions/{action_id}/result")
@atomic
def result(task_id: str, action_id: str, body: Result, token=Depends(runtime_token), db=Depends(transaction)):
    row, run, task, call, action = action_context(db, task_id, action_id, token)
    saved = encoded(body.model_dump())
    if action.completed_at:
        if action.result_json != saved:
            fail("result_conflict")
        return {"accepted": True}
    if action.status != "executing":
        fail("action_not_executing")
    action.status = body.status
    action.completed_at = datetime.utcnow()
    action.result_json = saved
    event(db, task, call, "tool.result" if body.status == "succeeded" else "tool.error", body.status,
          {"duration_ms": body.duration_ms})
    db.commit()
    return {"accepted": True}


@router.post("/actions/{action_id}/review")
@atomic
def review(action_id: str, body: Review, db=Depends(transaction), user=Depends(auth.get_current_admin_user)):
    call = db.get(models.DifyRuntimeCall, action_id)
    if not call:
        fail("action_not_found", 404)
    action = db.query(models.RuntimeAction).filter_by(action_id=action_id).one()
    task = db.query(models.RuntimeTask).filter_by(task_id=call.task_id).one()
    run = db.get(models.DifyRuntimeRun, task.task_id)
    row = binding(db, run.binding_id)
    if call.approval_status != "pending" or call.approval_deadline <= datetime.utcnow():
        fail("approval_inactive")
    if row.revision != call.revision or row.mode != "enforce" or task.status != "active":
        fail("policy_changed")
    call.approval_status = "approved" if body.approve else "rejected"
    action.decision = "allow" if body.approve else "deny"
    action.status = "authorized" if body.approve else "blocked"
    if body.approve:
        from ..config import settings
        value = hmac.new(settings.SECRET_KEY.encode(), action_id.encode(), hashlib.sha256).hexdigest()
        action.authorization_hash = digest(value)
        action.authorization_expires_at = min(call.approval_deadline, datetime.utcnow() + timedelta(seconds=60))
        db.add(models.RuntimeApproval(approval_id="rap_" + uuid.uuid4().hex, task_id=task.task_id,
            action_type=action.action_type, target=action.target, parameters_hash=action.parameters_hash,
            status="active", expires_at=action.authorization_expires_at, approved_by=user.username))
    event(db, task, call, "approval.resolved", call.approval_status, {"reviewed_by": user.username})
    db.commit()
    return {"status": call.approval_status}


@router.post("/bindings/{binding_id}/observations")
@atomic
def observation(binding_id: str, body: Observation, token=Depends(runtime_token), db=Depends(transaction)):
    run = start_run.__wrapped__(binding_id, body.run, token, db)
    trace = db.query(models.RuntimeTraceSession).filter_by(trace_id=run["trace_id"]).one()
    payload = {"node_id": body.node_id, "node_type": body.node_type,
               "workflow_id": body.run.workflow_id, "graph_digest": body.run.graph_digest}
    if body.type == "turn.end" and body.status in {"succeeded", "failed", "cancelled"}:
        task = db.query(models.RuntimeTask).filter_by(task_id=run["task_id"]).one()
        if task.status == "active":
            task.status = body.status
            task.completed_at = datetime.utcnow()
        trace.status = body.status
    ingest_batch(db, trace, RuntimeTraceBatchCreate(batch_id=body.event_id, events=[
        RuntimeTraceEventInput(event_id=body.event_id, event_time=body.event_time, source="dify_adapter",
            type=body.type, step_id=body.execution_id, status=body.status, payload=payload,
            redacted_payload=payload)
    ]))
    return {"accepted": True}
