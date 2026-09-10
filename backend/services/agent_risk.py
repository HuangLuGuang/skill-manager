"""Evidence-backed scoring. All writers participate in their caller's transaction."""

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .. import models
from ..security_scan_controls import AGENT_SCAN_SKILLS, hash_value, json_dumps, new_resource_id

SCORE_VERSION = "agent-risk-score@1"
WEIGHTS = {"info": (0, 0), "low": (10, 1), "medium": (35, 3), "high": (65, 5), "critical": (90, 8)}


def managed_agent(db: Session, target_id: str) -> models.SecurityAgentAsset:
    agent = db.query(models.SecurityAgentAsset).filter_by(target_id=target_id).first()
    if agent is None:
        agent = models.SecurityAgentAsset(agent_id=new_resource_id("mag"), target_id=target_id, external_id=target_id)
        db.add(agent)
        db.flush()
    return agent


def bind_scan(db: Session, task: models.SecurityScanTask, options: dict) -> None:
    target = db.query(models.SecurityTarget).filter_by(target_id=task.target_id).first()
    if not target or target.asset_type != "agent":
        return
    agent = managed_agent(db, task.target_id)
    db.add(
        models.AgentScanBinding(
            task_id=task.task_id,
            agent_id=agent.agent_id,
            config_fingerprint=agent.config_fingerprint,
            scope_json=json_dumps(
                {
                    "skills": options.get("skills") or list(AGENT_SCAN_SKILLS),
                    "conversation_mode": options.get("conversation_mode", "single_turn"),
                }
            ),
        )
    )


def enqueue(db: Session, target_id: str, *, kind: str, task_id: str | None = None) -> None:
    db.add(models.AssetLifecycleEvent(event_id=new_resource_id("ale"), target_id=target_id, task_id=task_id, kind=kind))


def _configuration(value):
    if isinstance(value, dict):
        return {
            key: _configuration(item)
            for key, item in sorted(value.items())
            if key
            not in {
                "sources",
                "collected_at",
                "last_collected_at",
                "executed",
                "verification_status",
                "execution_evidence",
                "runtime_evidence",
                "inferred_intent",
                "intent_alignment",
                "runtime",
                "mcp_server_discovered_at",
                "mcp_mapping_status",
                "schema_change_verification",
                "discovered_at",
                "last_checked_at",
            }
        }
    if isinstance(value, list):
        return [_configuration(item) for item in value]
    return value


def record_inventory(db: Session, task: models.SecurityScanTask, report: dict, snapshot_id: str) -> None:
    agent = managed_agent(db, task.target_id)
    if agent.snapshot_id:
        previous = db.query(models.SecurityAssetInventorySnapshot).filter_by(snapshot_id=agent.snapshot_id).first()
        previous_task = (
            db.query(models.SecurityScanTask).filter_by(task_id=previous.task_id).first() if previous else None
        )
        if previous_task and previous_task.created_at > task.created_at:
            return
    config = []
    for section in ("nodes", "prompts", "mcp", "tools", "knowledge_bases"):
        for item in report.get(section, []):
            config.append(
                {
                    "asset_id": item["asset_id"],
                    "type": item["asset_type"],
                    "details": _configuration(item.get("details", {})),
                }
            )
    fingerprint = hash_value(
        json_dumps(
            {
                "assets": sorted(config, key=lambda x: x["asset_id"]),
                "configuration_sha256": report.get("configuration_sha256"),
                "edges": sorted(report.get("edges", []), key=json_dumps),
            }
        )
    )
    if agent.config_fingerprint != fingerprint:
        agent.revision += 1
    agent.config_fingerprint = fingerprint
    name_field = report.get("agent_profile", {}).get("name", {})
    if isinstance(name_field, dict) and isinstance(name_field.get("value"), str):
        agent.display_name = name_field["value"][:512]
    agent.snapshot_id = snapshot_id
    agent.last_observed_at = datetime.utcnow()
    agent.observation_status = "observed"
    binding = db.query(models.AgentScanBinding).filter_by(task_id=task.task_id).first()
    if binding:
        binding.config_fingerprint = fingerprint
    enqueue(db, task.target_id, kind="inventory_updated", task_id=task.task_id)


def issue_key(finding: models.SecurityFinding) -> str:
    evidence = json.loads(finding.evidence_json or "{}")
    # Stable locations distinguish separate vulnerabilities; prose and model titles are not identity.
    location = {
        key: evidence[key]
        for key in ("location", "path", "parameter", "node_id", "tool_name", "rule_id")
        if key in evidence
    }
    if isinstance(evidence.get("asset"), dict):
        location["asset"] = {
            key: evidence["asset"].get(key) for key in ("gateway_id", "server_id", "tool_id", "tool_name")
        }
    return hash_value(
        json_dumps(
            {"asset": finding.asset_id, "code": finding.finding_code, "source": finding.source, "location": location}
        )
    )


def linked_target_ids(db: Session, agent: models.SecurityAgentAsset) -> list[str]:
    owner = db.query(models.SecurityTarget).filter_by(target_id=agent.target_id).first()
    rows = (
        db.query(models.SecurityTarget)
        .join(models.AgentAssetLink, models.AgentAssetLink.target_id == models.SecurityTarget.target_id)
        .filter(
            models.AgentAssetLink.agent_id == agent.agent_id,
            models.SecurityTarget.owner_user_id == owner.owner_user_id,
            models.SecurityTarget.owner_group_id == owner.owner_group_id,
        )
        .all()
    )
    return [row.target_id for row in rows]


def reconcile_issues(db: Session, agent: models.SecurityAgentAsset) -> list[models.AgentRiskIssue]:
    target_ids = [agent.target_id, *linked_target_ids(db, agent)]
    findings = (
        db.query(models.SecurityFinding)
        .join(models.SecurityScanTask)
        .filter(
            models.SecurityScanTask.target_id.in_(target_ids),
        )
        .order_by(models.SecurityFinding.created_at, models.SecurityFinding.finding_id)
        .all()
    )
    issues = {row.dedup_key: row for row in db.query(models.AgentRiskIssue).filter_by(agent_id=agent.agent_id).all()}
    for finding in findings:
        key = issue_key(finding)
        issue = issues.get(key)
        if issue is None:
            issue = models.AgentRiskIssue(
                issue_id=new_resource_id("ari"),
                agent_id=agent.agent_id,
                dedup_key=key,
                severity=finding.severity,
                finding_id=finding.finding_id,
                status="open",
                evidence_json="[]",
            )
            db.add(issue)
            issues[key] = issue
        evidence_ids = json.loads(issue.evidence_json)
        if finding.finding_id not in evidence_ids:
            evidence_ids.append(finding.finding_id)
            issue.evidence_json = json_dumps(evidence_ids)
            issue.finding_id = finding.finding_id
            observed_binding = db.get(models.AgentScanBinding, finding.task_id)
            if (
                issue.reviewed_at
                and finding.created_at > issue.reviewed_at
                and issue.status in {"accepted", "false_positive"}
            ):
                if observed_binding and observed_binding.config_fingerprint != issue.reviewed_config_fingerprint:
                    issue.status = "open"
            if WEIGHTS[finding.severity][0] > WEIGHTS[issue.severity][0]:
                issue.severity = finding.severity
            if issue.status == "resolved" and issue.reviewed_at and finding.created_at > issue.reviewed_at:
                issue.status = "open"
                issue.closure_task_id = None
        # Legacy manual 'resolved' is a repair declaration, not a verified closure.
        if not issue.reviewed_at and finding.disposition_at:
            issue.status = {"resolved": "pending_verification"}.get(finding.status, finding.status)
    db.flush()
    current_findings = {finding.finding_id for finding in findings}
    return [issue for issue in issues.values() if issue.finding_id in current_findings]


def score_issues(issues: list[dict]) -> tuple[int, list[dict]]:
    ordered = sorted(issues, key=lambda x: (-WEIGHTS[x["severity"]][0], x["issue_id"]))
    contributions = []
    extra = 0
    total = 0
    for index, item in enumerate(ordered):
        base, increment = WEIGHTS[item["severity"]]
        points = base if index == 0 else min(increment, 20 - extra, 100 - total)
        if index:
            extra += points
        total += points
        contributions.append({**item, "points": points})
    return min(100, total), contributions


def assessment_scope(db: Session, agent: models.SecurityAgentAsset) -> dict:
    source = db.get(models.AssetSource, agent.source_id) if agent.source_id else None
    config = json.loads(source.config_json) if source else {}
    return {
        "skills": config.get("skills") or list(AGENT_SCAN_SKILLS),
        "validity_hours": config.get("validity_hours", 168),
    }


def mcp_result_current(db: Session, task: models.SecurityScanTask) -> bool:
    from ..api_errors import ApiError
    from ..routers.security_scans import _target_snapshot

    target = db.query(models.SecurityTarget).filter_by(target_id=task.target_id, status="active").first()
    if not target:
        return False
    try:
        current = _target_snapshot(db, target).get("mcp_assets")
    except (ApiError, KeyError, ValueError):
        return False
    original = json.loads(task.target_snapshot_json).get("mcp_assets")
    return bool(original and current) and _configuration(original) == _configuration(current)


def coverage(db: Session, agent: models.SecurityAgentAsset, now: datetime) -> list[dict]:
    scope = assessment_scope(db, agent)
    latest = {}
    tasks = (
        db.query(models.SecurityScanTask, models.AgentScanBinding)
        .join(
            models.AgentScanBinding,
            models.AgentScanBinding.task_id == models.SecurityScanTask.task_id,
        )
        .filter(
            models.AgentScanBinding.agent_id == agent.agent_id, models.SecurityScanTask.scan_kind == "agent_risk_scan"
        )
        .order_by(
            models.SecurityScanTask.created_at.desc(),
            models.SecurityScanTask.task_id.desc(),
        )
        .all()
    )
    for task, binding in tasks:
        cases = {c.external_case_id: c for c in db.query(models.SecurityScanCase).filter_by(task_id=task.task_id).all()}
        for skill in json.loads(binding.scope_json).get("skills", []):
            if skill in latest:
                continue
            case = cases.get(f"aig-rule:{skill}")
            state = "pending"
            if task.status in {"failed", "cancelled", "timed_out", "blocked"}:
                state = "failed"
            elif not agent.config_fingerprint or binding.config_fingerprint != agent.config_fingerprint:
                state = "stale"
            elif task.status == "succeeded":
                if not task.completed_at or task.completed_at + timedelta(hours=scope["validity_hours"]) <= now:
                    state = "expired"
                else:
                    execution = json.loads(case.response_summary_json) if case else {}
                    tested = (
                        case
                        and case.status in {"passed", "failed"}
                        and execution.get("execution_status") == "completed"
                        and execution.get("dialogue_calls", 0) > 0
                    )
                    state = "completed" if tested else "unverified"
            latest[skill] = {"check": skill, "status": state, "task_id": task.task_id}
    result = [latest.get(skill, {"check": skill, "status": "pending", "task_id": None}) for skill in scope["skills"]]
    snapshot = None
    if agent.snapshot_id:
        snapshot = db.query(models.SecurityAssetInventorySnapshot).filter_by(snapshot_id=agent.snapshot_id).first()
    source_coverage = json.loads(snapshot.coverage_json) if snapshot else {}
    summary = json.loads(snapshot.summary_json) if snapshot else {}
    required = ["dsl", "dify_console_api"]
    if summary.get("mcp"):
        required.append("mcp_tools_list")
    if summary.get("knowledge_bases"):
        required.append("dify_knowledge_api")
    inventory_complete = bool(snapshot) and all(source_coverage.get(x) == "completed" for x in required)
    result.append(
        {
            "check": "inventory",
            "status": "completed" if inventory_complete and agent.observation_status == "observed" else "unverified",
            "task_id": snapshot.task_id if snapshot else None,
        }
    )
    for target_id in linked_target_ids(db, agent):
        latest_task = (
            db.query(models.SecurityScanTask)
            .filter_by(target_id=target_id, scan_kind="mcp_risk_scan")
            .order_by(models.SecurityScanTask.created_at.desc())
            .first()
        )
        state = "pending"
        if latest_task:
            state = "unverified"
            cases = db.query(models.SecurityScanCase).filter_by(task_id=latest_task.task_id).all()
            if (
                latest_task.status == "succeeded"
                and cases
                and all(case.status in {"passed", "failed"} for case in cases)
            ):
                state = (
                    "completed"
                    if latest_task.completed_at
                    and latest_task.completed_at + timedelta(hours=scope["validity_hours"]) > now
                    else "expired"
                )
                if not mcp_result_current(db, latest_task):
                    state = "stale"
        result.append(
            {
                "check": "mcp_risk_scan",
                "target_id": target_id,
                "status": state,
                "task_id": latest_task.task_id if latest_task else None,
            }
        )
    return result


def calculate(db: Session, agent: models.SecurityAgentAsset, *, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    issues = reconcile_issues(db, agent)
    checks = coverage(db, agent, now)
    active = [
        {"issue_id": x.issue_id, "severity": x.severity, "status": x.status, "finding_id": x.finding_id}
        for x in issues
        if x.status not in {"resolved", "false_positive"}
    ]
    score, contributions = score_issues(active)
    complete = all(x["status"] == "completed" for x in checks)
    stale = any(x["status"] in {"stale", "expired"} for x in checks)
    status = (
        "complete"
        if complete
        else "stale"
        if stale
        else "partial"
        if active or any(x["status"] == "completed" for x in checks)
        else "unassessed"
    )
    score = score if score > 0 or complete else None
    payload = {
        "agent_id": agent.agent_id,
        "related_target_ids": linked_target_ids(db, agent),
        "score": score,
        "status": status,
        "algorithm_version": SCORE_VERSION,
        "config_fingerprint": agent.config_fingerprint,
        "revision": agent.revision,
        "scope": assessment_scope(db, agent),
        "coverage": checks,
        "contributions": contributions,
        "issue_count": len(active),
        "level": "unassessed"
        if score is None
        else "critical"
        if score >= 90
        else "high"
        if score >= 65
        else "medium"
        if score >= 35
        else "low"
        if score
        else "info",
    }
    pending = (
        db.query(models.AssetLifecycleEvent)
        .filter_by(target_id=agent.target_id, processed_at=None)
        .filter(models.AssetLifecycleEvent.error_code.is_not(None))
        .order_by(models.AssetLifecycleEvent.created_at.desc())
        .first()
    )
    payload["rescan_error_code"] = pending.error_code if pending else None
    input_hash = hash_value(json_dumps(payload))
    existing = (
        db.query(models.AgentRiskAssessment)
        .filter_by(agent_id=agent.agent_id)
        .order_by(models.AgentRiskAssessment.created_at.desc(), models.AgentRiskAssessment.assessment_id.desc())
        .first()
    )
    if existing and existing.input_hash == input_hash:
        payload["assessed_at"] = existing.created_at.isoformat() + "Z"
        payload["assessment_id"] = existing.assessment_id
        return payload
    row = models.AgentRiskAssessment(
        assessment_id=new_resource_id("ara"),
        agent_id=agent.agent_id,
        input_hash=input_hash,
        payload_json=json_dumps(payload),
        created_at=now,
    )
    db.add(row)
    db.flush()
    payload.update(assessment_id=row.assessment_id, assessed_at=now.isoformat() + "Z")
    return payload


def verify_closure(db: Session, agent: models.SecurityAgentAsset, issue: models.AgentRiskIssue, task_id: str) -> bool:
    finding = db.query(models.SecurityFinding).filter_by(finding_id=issue.finding_id).first()
    original_task = db.query(models.SecurityScanTask).filter_by(task_id=finding.task_id).first() if finding else None
    if not original_task or original_task.target_id not in [agent.target_id, *linked_target_ids(db, agent)]:
        return False
    task = (
        db.query(models.SecurityScanTask)
        .filter_by(task_id=task_id, target_id=original_task.target_id, status="succeeded")
        .first()
    )
    if task and task.scan_kind == "mcp_risk_scan":
        if (
            not mcp_result_current(db, task)
            or task.engine_version != original_task.engine_version
            or not task.completed_at
            or task.completed_at <= finding.created_at
        ):
            return False
        original_case = db.query(models.SecurityScanCase).filter_by(case_id=finding.case_id).first()
        if not original_case:
            return False
        clean_case = (
            db.query(models.SecurityScanCase)
            .filter_by(task_id=task_id, external_case_id=original_case.external_case_id, status="passed")
            .first()
        )
        remaining = db.query(models.SecurityFinding).filter_by(task_id=task_id).all()
        return bool(clean_case) and not any(issue_key(x) == issue.dedup_key for x in remaining)
    binding = db.get(models.AgentScanBinding, task_id)
    finding = db.query(models.SecurityFinding).filter_by(finding_id=issue.finding_id).first()
    original = db.get(models.AgentScanBinding, finding.task_id) if finding else None
    if (
        not task
        or not binding
        or not original
        or not agent.config_fingerprint
        or binding.config_fingerprint != agent.config_fingerprint
    ):
        return False
    if not task.completed_at or task.completed_at <= finding.created_at:
        return False
    if json.loads(binding.scope_json) != json.loads(original.scope_json):
        return False
    original_task = db.query(models.SecurityScanTask).filter_by(task_id=finding.task_id).first()
    if (
        not task.engine_version
        or task.engine_version != original_task.engine_version
        or task.scan_kind != original_task.scan_kind
    ):
        return False
    original_case = db.query(models.SecurityScanCase).filter_by(case_id=finding.case_id).first()
    if not original_case:
        return False
    clean_case = (
        db.query(models.SecurityScanCase)
        .filter_by(task_id=task_id, external_case_id=original_case.external_case_id, status="passed")
        .first()
    )
    remaining = db.query(models.SecurityFinding).filter_by(task_id=task_id).all()
    if task.scan_kind == "agent_risk_scan":
        execution = json.loads(clean_case.response_summary_json) if clean_case else {}
        if execution.get("execution_status") != "completed" or execution.get("dialogue_calls", 0) <= 0:
            return False
    return bool(clean_case) and not any(issue_key(x) == issue.dedup_key for x in remaining)
