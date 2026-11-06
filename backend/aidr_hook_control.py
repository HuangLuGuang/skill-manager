"""Plugin tool control; signed authorities are scoped to one receiver attempt."""
from . import aidr_adapters
import hashlib
import json
import time
import uuid
from typing import Literal
from .aidr_products import HookAgentID, BY_ID
from .aidr_command_rules import CommandCondition, SHELL_TOOLS

from pydantic import Field, model_validator
from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint, tuple_
from sqlalchemy.dialects.sqlite import insert

from .aidr_behavior import Strict
from .aidr_enforcement import canonical, sign
from .aidr_models import AidrHookEvent
from .api_errors import ApiError
from .sqlite_db import Base


class HookPolicyRow(Base):
    __tablename__ = "aidr_hook_policies"
    __table_args__ = (UniqueConstraint("client_id", "revision", name="uq_aidr_hook_policy"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), nullable=False)
    revision = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False)
    envelope = Column(Text, nullable=False)
    created_by = Column(String(128), nullable=False)


class HookApprovalRow(Base):
    __tablename__ = "aidr_hook_approvals"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "event_id", name="uq_aidr_hook_approval_attempt"),)
    id = Column(String(32), primary_key=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), nullable=False, index=True)
    stream_id = Column(String(32), nullable=False)
    event_id = Column(String(32), nullable=False)
    receiver_instance = Column(String(32), nullable=False)
    scope = Column(Text, nullable=False)
    nonce = Column(String(32), nullable=False, unique=True)
    revision = Column(Integer, nullable=False, default=1)
    state = Column(String(16), nullable=False, default="pending")
    created_at = Column(Integer, nullable=False)
    expires_at = Column(Integer, nullable=False)
    envelope = Column(Text, nullable=True)
    decided_by = Column(String(128), nullable=True)


class HookApprovalReceipt(Base):
    __tablename__ = "aidr_hook_approval_receipts"
    __table_args__ = (UniqueConstraint("client_id", "request_id", name="uq_aidr_hook_approval_receipt"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), nullable=False)
    request_id = Column(String(32), nullable=False)
    digest = Column(String(64), nullable=False)
    response = Column(Text, nullable=False)


class HookAttemptReportRow(Base):
    __tablename__ = "aidr_hook_attempt_reports"
    __table_args__ = (UniqueConstraint("client_id", "stream_id", "event_id", name="uq_aidr_hook_attempt_report"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(String(128), ForeignKey("managed_clients.client_id"), nullable=False)
    stream_id = Column(String(32), nullable=False)
    event_id = Column(String(32), nullable=False)
    digest = Column(String(64), nullable=False)
    payload = Column(Text, nullable=False)
    received_at = Column(Integer, nullable=False)


class AttemptReport(Strict):
    schema_version: Literal[1]
    client_id: str = Field(min_length=1, max_length=128)
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receiver_instance: str = Field(pattern=r"^[0-9a-f]{32}$")
    approval_id: str = Field(pattern=r"^([0-9a-f]{32})?$")
    state: Literal["consumed", "denied"]
    code: Literal["aidr_hook_approval_consumed", "aidr_hook_approval_cancelled", "aidr_hook_approval_timeout", "aidr_hook_policy_changed", "aidr_hook_receiver_restarted", "aidr_hook_grant_deny", "aidr_hook_grant_revoke", "aidr_hook_grant_expired", "aidr_hook_grant_consumed", "aidr_hook_grant_scope_mismatch"]
    reported_at: str = Field(pattern=r"^[1-9][0-9]{0,11}$")

    @model_validator(mode="after")
    def consistent(self):
        if (self.state == "consumed") != (self.code == "aidr_hook_approval_consumed") or (self.state == "consumed" and not self.approval_id):
            raise ValueError("hook_attempt_state_invalid")
        return self


def save_attempt_report(db, client_id, raw):
    try:
        if len(raw) > 4096:
            raise ValueError("oversized")
        body = AttemptReport.model_validate_json(raw)
    except ValueError:
        reject("hook_attempt_report_invalid", "客户端审批回执无效", "Invalid client approval receipt", 422)
    if body.client_id != client_id:
        reject("hook_attempt_device_mismatch", "回执设备不匹配", "Receipt device mismatch", 403)
    event = db.query(AidrHookEvent).filter_by(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id).first()
    if event is None or event.expired_at is not None:
        reject("hook_evidence_missing", "回执所需插件证据尚未到达", "Plugin evidence for receipt has not arrived", 404)
    evidence = json.loads(event.payload_json)
    if evidence.get("receiver_instance") != body.receiver_instance or evidence["event"]["kind"] != "tool.pre":
        reject("hook_attempt_scope_mismatch", "回执调用范围不匹配", "Receipt call scope mismatch", 422)
    approval = db.query(HookApprovalRow).filter_by(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id).first()
    if body.approval_id and (approval is None or approval.id != body.approval_id):
        reject("hook_attempt_scope_mismatch", "回执审批身份不匹配", "Receipt approval identity mismatch", 422)
    if body.state == "consumed" and approval.state not in ("approved", "revoked"):
        reject("hook_attempt_state_invalid", "回执没有对应的平台批准", "Receipt has no corresponding platform approval", 422)
    digest = hashlib.sha256(raw).hexdigest()
    db.execute(insert(HookAttemptReportRow).values(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id, digest=digest, payload=canonical(body.model_dump()), received_at=int(time.time())).on_conflict_do_nothing(index_elements=["client_id", "stream_id", "event_id"]))
    row = db.query(HookAttemptReportRow).filter_by(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id).one()
    if row.digest != digest:
        reject("hook_attempt_report_conflict", "同一尝试的客户端回执发生冲突", "Client receipt conflicts for the same attempt")
    db.commit()
    return {"schema_version": 1, "client_id": client_id, "stream_id": body.stream_id, "event_id": body.event_id, "digest": digest, "durable": True}


class ToolRule(Strict):
    command: CommandCondition | None = None
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    agent: HookAgentID | Literal["*"]
    tool: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")
    decision: Literal["allow", "deny", "ask"]

    @model_validator(mode="after")
    def check_tool(self):
        if self.agent != "*" and self.decision == "ask" and not BY_ID[self.agent]["approval"]:
            raise ValueError("hook_approval_unsupported")
        if any(ord(c)<32 or ord(c)==127 for c in self.tool):
            raise ValueError("hook_tool_invalid")
        return self


class ToolPolicyInput(Strict):
    approval_wait_seconds: int = Field(default=180, ge=30, le=300, strict=True)
    expected_revision: str = Field(pattern=r"^(0|[1-9][0-9]{0,17})$")
    # Accepted for older management UIs; published rules persist until replaced.
    lifetime_seconds: int | None = Field(default=None, ge=60, le=86400, exclude=True)
    default_action: Literal["allow", "deny", "ask"]
    rules: list[ToolRule] = Field(max_length=128)

    @model_validator(mode="after")
    def check_rules(self):
        if len({r.id for r in self.rules}) != len(self.rules) or any(r.id == "default" for r in self.rules):
            raise ValueError("hook_rule_identity_invalid")
        return self


class ApprovalRequest(Strict):
    expires_at: int | None = Field(default=None, gt=0, strict=True)
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    event_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receiver_instance: str = Field(pattern=r"^[0-9a-f]{32}$")
    policy_revision: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    rule_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ApprovalDecision(Strict):
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_revision: str = Field(pattern=r"^[1-9][0-9]{0,17}$")
    decision: Literal["allow", "deny", "revoke"]


class ControlRequest(Strict):
    stream_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    receiver_instance: str = Field(pattern=r"^[0-9a-f]{32}$")
    after: str = Field(default="", pattern=r"^$|^[0-9a-f]{32}$")


def reject(code, zh, en, status=409):
    raise ApiError(status, "aidr."+code, zh, en)


def latest_policy(db, client_id):
    return db.query(HookPolicyRow).filter_by(client_id=client_id).order_by(HookPolicyRow.revision.desc()).first()


def compatible_policy(db, client_id, revision):
    current = latest_policy(db, client_id)
    original = db.query(HookPolicyRow).filter_by(client_id=client_id, revision=int(revision)).first()
    if current is None or original is None:
        return None
    policy = json.loads(original.payload)
    # Every intervening rule set must match; changing away and back cannot revive an attempt.
    for row in db.query(HookPolicyRow).filter(HookPolicyRow.client_id == client_id, HookPolicyRow.revision > original.revision):
        candidate = json.loads(row.payload)
        if any(candidate[k] != policy[k] for k in ('default_action', 'rules')):
            return None
    return original


def evaluate(policy, agent, tool, observation=None):
    matched = []
    unresolved = False
    for rule in policy['rules']:
        if rule['agent'] not in (agent, '*') or rule['tool'] not in (tool, '*'):
            continue
        if rule.get('command'):
            if tool.lower().split('.')[-1] not in SHELL_TOOLS:
                continue
            if not observation or observation.get('policy_revision') != str(policy.get('revision', '1')) or rule['id'] in observation.get('unresolved', []):
                unresolved = True
                continue
            if rule['id'] not in observation.get('matched', []):
                continue
        matched.append(rule)
    matched.sort(key=lambda r: r['id'])
    # Restrictive decisions win independent of list order. All matched rule IDs
    # remain available for explaining a conflict or a wider effective permission.
    for decision in ("deny", "ask", "allow"):
        winner = next((r for r in matched if r["decision"] == decision), None)
        if winner:
            return {"decision": decision, "rule_id": winner["id"], "matched_rule_ids": [r["id"] for r in matched], **({'unresolved': True} if unresolved else {})}
    return {"decision": policy["default_action"], "rule_id": "default", "matched_rule_ids": [], **({'unresolved': True} if unresolved else {})}


def publish(db, client_id, body, username):
    previous = latest_policy(db, client_id)
    revision = previous.revision if previous else 0
    if body.expected_revision != str(revision):
        reject("hook_policy_conflict", "工具策略版本已变化", "Tool policy revision changed")
    now = int(time.time())
    command_rules = any(r.command for r in body.rules)
    if command_rules:
        from .aidr_hook_runtime import HookRuntimeRow
        reports = db.query(HookRuntimeRow).filter_by(client_id=client_id).filter(HookRuntimeRow.received_at >= now-90).all()
        if not reports or any(json.loads(r.payload).get('command_rules_schema') != 1 for r in reports):
            reject('hook_command_upgrade_required', '请先升级本地接收器并等待能力报告，再发布命令规则', 'Upgrade the local receiver and wait for its capability report before publishing command rules', 409)
        if any(r.command and r.command.keywords for r in body.rules) and any(json.loads(r.payload).get('command_keywords_schema') != 1 for r in reports):
            reject('hook_command_keywords_upgrade_required', '请先升级客户端并等待命令关键词能力报告', 'Upgrade the client and wait for command keyword capability reporting', 409)
    if command_rules and any(r.command and r.command.networks for r in body.rules) and any(json.loads(r.payload).get('command_networks_schema') != 1 for r in reports):
        reject('hook_command_networks_upgrade_required', '请先升级客户端并等待 IP 网段匹配能力报告', 'Upgrade the client and wait for IP subnet capability reporting', 409)
    from .aidr_hook_runtime import HookRuntimeRow
    reports = db.query(HookRuntimeRow).filter_by(client_id=client_id).filter(HookRuntimeRow.received_at >= now-90).all()
    if not reports or any(json.loads(r.payload).get('approval_wait_schema') != 1 for r in reports):
        reject('hook_approval_wait_upgrade_required', '请升级客户端并等待审批等待时长能力报告', 'Upgrade the client and wait for approval timeout capability reporting')
    schema = 4
    policy = {"schema": schema, "domain": f"aidr.tool-policy/{schema}", "device": client_id, "revision": str(revision+1), "issued_at": str(now), "approval_wait_seconds": body.approval_wait_seconds, "default_action": body.default_action, "rules": [r.model_dump(exclude_none=True) for r in body.rules]}
    envelope = sign(policy)
    if len(canonical(envelope).encode())>32768:
        reject("hook_policy_too_large", "工具策略超过大小限制", "Tool policy exceeds the size limit", 422)
    result = db.execute(insert(HookPolicyRow).values(client_id=client_id, revision=revision+1, payload=canonical(policy), envelope=canonical(envelope), created_by=username).on_conflict_do_nothing())
    if not result.rowcount:
        reject("hook_policy_conflict", "工具策略版本已变化", "Tool policy revision changed")
    return policy


def approval_view(row, report=None):
    state = "expired" if row.expires_at <= int(time.time()) and row.state in ("pending", "approved") else row.state
    if report and report.get("code") == "aidr_hook_approval_timeout":
        state = "timed_out"
    return {"id": row.id, "revision": str(row.revision), "state": state, "recorded_state": row.state, "scope": json.loads(row.scope), "created_at": str(row.created_at), "expires_at": str(row.expires_at), "decided_by": row.decided_by, "evidence_type": "agent_hook", "execution_point": "plugin_pre_tool"}


def approval_views(db, rows):
    keys = [(row.client_id, row.stream_id, row.event_id) for row in rows]
    reports = db.query(HookAttemptReportRow).filter(tuple_(HookAttemptReportRow.client_id,
        HookAttemptReportRow.stream_id, HookAttemptReportRow.event_id).in_(keys)).all() if keys else []
    indexed = {(r.client_id, r.stream_id, r.event_id): json.loads(r.payload) for r in reports}
    return [approval_view(row, indexed.get((row.client_id, row.stream_id, row.event_id))) for row in rows]


def request_approval(db, client_id, body):
    from .aidr_tool_policy_scope import require_current
    require_current(db, client_id)
    event = db.query(AidrHookEvent).filter_by(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id).first()
    if event is None or event.expired_at is not None:
        reject("hook_evidence_missing", "审批所需插件证据尚未到达", "Plugin evidence for approval has not arrived", 404)
    record = json.loads(event.payload_json)
    evidence = record["event"]
    if not BY_ID[evidence["agent"]]["approval"]:
        reject("aidr_hook_approval_unsupported", "此产品未接入工具审批", "Tool approval is not available for this product", 422)
    # CodeBuddy approvals bind the exact receiver attempt; its Hook has no native call ID.
    codebuddy = evidence["agent"] == "codebuddy"
    if record.get("receiver_instance") != body.receiver_instance or evidence["kind"] != "tool.pre" or not evidence.get("input_digest") or (not codebuddy and not evidence.get("native_call_id")) or ((codebuddy or aidr_adapters.get(evidence["agent"]).turn_required) and not evidence.get("turn_id")) or (codebuddy and not evidence.get("session_id")):
        reject("hook_scope_unverified", "调用身份不足以建立审批范围", "Call identity is insufficient for an approval scope", 422)
    policy_row = compatible_policy(db, client_id, body.policy_revision)
    now = int(time.time())
    if policy_row is None or str(policy_row.revision) != body.policy_revision:
        reject("hook_policy_conflict", "工具策略版本已变化", "Tool policy revision changed")
    policy = json.loads(policy_row.payload)
    decision = evaluate(policy, evidence["agent"], evidence["tool"], evidence.get('command_match'))
    if decision["decision"] != "ask" or decision["rule_id"] != body.rule_id:
        reject("hook_approval_not_applicable", "当前规则不接受此审批请求", "The current rule does not accept this approval request")
    scope = {"device": client_id, "stream": body.stream_id, "receiver_instance": body.receiver_instance, "user_scope": record["user_scope"], "agent": evidence["agent"], "session_id": evidence["session_id"], "turn_id": evidence.get("turn_id", ""), "native_call_id": evidence.get("native_call_id", ""), "native_agent_id": evidence.get("native_agent_id", ""), "tool": evidence["tool"], "input_digest": evidence["input_digest"], "attempt_nonce": body.event_id, "rule_id": body.rule_id, "policy_revision": body.policy_revision, "execution_point": "plugin_pre_tool"}
    expires = body.expires_at
    budget = policy['approval_wait_seconds'] if policy.get('schema') == 4 else 300
    if (policy.get('schema') == 4 and expires is None) or (expires is not None and expires > now + budget):
        reject('hook_approval_deadline_invalid', '审批截止时间无效', 'Invalid approval deadline', 422)
    expires = expires if expires is not None else now + 45
    if expires <= now:
        reject('hook_approval_expired', '审批已过期', 'Approval expired')
    result = db.execute(insert(HookApprovalRow).values(id=uuid.uuid4().hex, client_id=client_id, stream_id=body.stream_id, event_id=body.event_id, receiver_instance=body.receiver_instance, scope=canonical(scope), nonce=uuid.uuid4().hex, revision=1, state="pending", created_at=now, expires_at=expires).on_conflict_do_nothing(index_elements=["client_id", "stream_id", "event_id"]))
    row = db.query(HookApprovalRow).filter_by(client_id=client_id, stream_id=body.stream_id, event_id=body.event_id).one()
    if result.rowcount and db.query(HookApprovalRow).filter_by(client_id=client_id, state="pending").filter(HookApprovalRow.expires_at>now).count()>1000:
        reject("hook_approval_capacity", "待处理审批达到上限", "Pending approval capacity reached", 429)
    if row.scope != canonical(scope):
        reject("hook_approval_conflict", "同一尝试的审批范围发生冲突", "Approval scope conflicts for the same attempt")
    return approval_view(row), bool(result.rowcount)


def decide(db, client_id, approval_id, body, username):
    if body.decision == 'allow':
        from .aidr_tool_policy_scope import require_current
        require_current(db, client_id)
    content = canonical([approval_id, username, body.model_dump()])
    digest = hashlib.sha256(content.encode()).hexdigest()
    inserted = db.execute(insert(HookApprovalReceipt).values(client_id=client_id, request_id=body.request_id, digest=digest, response="{}").on_conflict_do_nothing())
    receipt = db.query(HookApprovalReceipt).filter_by(client_id=client_id, request_id=body.request_id).one()
    if not inserted.rowcount:
        if receipt.digest != digest:
            reject("hook_decision_conflict", "审批请求标识对应不同内容", "Approval request ID has different content")
        return json.loads(receipt.response), False
    row = db.query(HookApprovalRow).filter_by(client_id=client_id, id=approval_id).first()
    if row is None:
        reject("hook_approval_missing", "审批不存在", "Approval not found", 404)
    if db.query(HookAttemptReportRow).filter_by(client_id=client_id, stream_id=row.stream_id, event_id=row.event_id).first():
        reject("hook_attempt_finished", "客户端已报告本次尝试结束", "Client already reported this attempt as finished")
    now = int(time.time())
    scope = json.loads(row.scope)
    policy = compatible_policy(db, client_id, scope['policy_revision'])
    if row.revision != int(body.expected_revision):
        reject("hook_approval_version_conflict", "审批版本已变化，请刷新", "Approval revision changed; refresh")
    if row.expires_at <= now:
        reject("hook_approval_expired", "审批已过期", "Approval expired")
    if (body.decision in ("allow", "deny") and row.state != "pending") or (body.decision == "revoke" and row.state != "approved"):
        reject("hook_approval_terminal", "当前审批状态不允许此变更", "The approval state does not permit this change")
    if body.decision == "allow" and (policy is None or str(policy.revision) != scope["policy_revision"]):
        reject("hook_policy_conflict", "工具策略版本已变化", "Tool policy revision changed")
    next_revision = row.revision+1
    grant = {"schema": 1, "domain": "aidr.tool-grant/1", "grant_id": row.id, "nonce": row.nonce, "revision": str(next_revision), "decision": body.decision, "issued_at": str(now), "expires_at": str(row.expires_at), "scope": scope}
    row.envelope = canonical(sign(grant))
    row.revision = next_revision
    row.state = {"allow": "approved", "deny": "denied", "revoke": "revoked"}[body.decision]
    row.decided_by = username
    response = approval_view(row)
    receipt.response = canonical(response)
    return response, True


def snapshot(db, client_id, body):
    from .aidr_tool_policy_scope import reconcile
    try:
        reconcile(db, client_id)
        db.commit()
    except ApiError as error:
        db.rollback()
        if error.code not in ('aidr.hook_command_upgrade_required', 'aidr.hook_approval_wait_upgrade_required', 'aidr.hook_command_keywords_upgrade_required', 'aidr.hook_command_networks_upgrade_required'):
            raise
        return {"policy": None, "grants": [], "more_grants": False, "next_after": body.after}
    policy = latest_policy(db, client_id)
    rows = db.query(HookApprovalRow).filter_by(client_id=client_id, stream_id=body.stream_id, receiver_instance=body.receiver_instance).filter(HookApprovalRow.id>body.after, HookApprovalRow.expires_at>int(time.time()), HookApprovalRow.envelope.isnot(None)).order_by(HookApprovalRow.id).limit(101).all()
    result = {"policy": json.loads(policy.envelope) if policy else None, "grants": [], "more_grants": False, "next_after": body.after}
    size = len(canonical(result).encode())
    for row in rows[:100]:
        envelope = json.loads(row.envelope)
        extra = len(canonical(envelope).encode())+1
        if size+extra>60000:
            break
        result["grants"].append(envelope)
        result["next_after"] = row.id
        size += extra
    result["more_grants"] = len(rows)>len(result["grants"])
    return result
