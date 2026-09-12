"""Versioned Client classification policies and migration previews."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from . import models
from .api_errors import ApiError

DEFAULT_SCOPE = "@default"
ACTIONS = {
    "trusted_scan_rejected": {"record_only", "record", "quarantine", "restore_trusted"},
    "unverified_scan_rejected": {"record_only", "record", "quarantine"},
    "unverified": {"record_only", "record", "submit_scan", "quarantine"},
    "malicious": {"record_only", "record", "quarantine", "uninstall"},
    "trusted_content_changed": {"record_only", "record", "submit_scan", "quarantine", "restore_trusted"},
    "unverified_content_changed": {"record_only", "record", "submit_scan", "quarantine"},
}
DEFAULT_RULES = {trigger: "record" for trigger in ACTIONS}
FILE_ACTIONS = {"quarantine", "uninstall", "restore_trusted"}


def content_rejected(entry, content_matches: bool) -> bool:
    if not entry or not content_matches or getattr(entry.status, "value", entry.status) != "REJECTED":
        return False
    report = entry.vetting.scan_report if entry.vetting else {}
    return not bool((report or {}).get("vetting_failed"))


def incompatible_rules(rules, protocol):
    if protocol >= 2:
        return []
    required = {trigger for trigger, action in rules.items()
                if action == "record_only" or (trigger.endswith("scan_rejected") and action != "record")}
    for trigger, action in rules.items():
        if action == "submit_scan":
            required.add("trusted_scan_rejected" if trigger == "trusted_content_changed" else "unverified_scan_rejected")
    return sorted(required)


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: dict[str, str] = Field(default_factory=dict)
    expected_version: str
    preview_id: str | None = None

    @model_validator(mode="after")
    def valid_actions(self):
        for trigger, action in self.rules.items():
            if trigger not in ACTIONS or action not in ACTIONS[trigger]:
                raise ApiError(400, "client.policy_invalid_rule", "处置规则或动作无效", "Invalid governance trigger or action")
        return self


def record_protocol(db: Session, client_id: str, protocol: int, *, is_new=False):
    row = db.get(models.ClientGovernancePolicy, client_id)
    if row is None:
        row = models.ClientGovernancePolicy(scope=client_id, enabled=False, protocol=protocol, revision=0)
        db.add(row)
    else:
        row.protocol = protocol
    if protocol in (1, 2) and not row.enabled:
        if not is_new:
            client = db.query(models.ManagedClient).filter_by(client_id=client_id).one()
            row.rules_json = json.dumps(legacy_policy_rules(client.policy_mode), sort_keys=True)
            row.revision += 1
        row.enabled = True
        row.updated_at = datetime.utcnow()
    db.flush()
    return row


def policy_view(db: Session, client_id: str | None = None):
    default = db.get(models.ClientGovernancePolicy, DEFAULT_SCOPE)
    custom = db.get(models.ClientGovernancePolicy, client_id) if client_id else None
    defaults = {**DEFAULT_RULES, **(json.loads(default.rules_json) if default else {})}
    overrides = json.loads(custom.rules_json) if custom else {}
    rules = {**defaults, **overrides}
    default_revision = default.revision if default else 0
    revision = custom.revision if custom else 0
    return {
        "protocol": custom.protocol if custom else 2,
        "advanced_supported": client_id is None or bool(custom and custom.protocol == 2),
        "incompatible_rules": incompatible_rules(rules, custom.protocol) if custom else [],
        "supported": client_id is None or bool(custom and custom.protocol in (1, 2)),
        "enabled": client_id is None or bool(custom and custom.enabled and custom.protocol in (1, 2)),
        "version": f"{default_revision}:{revision}",
        "rules": rules,
        "defaults": defaults,
        "overrides": overrides if client_id else (json.loads(default.rules_json) if default else {}),
        "sources": {trigger: "client" if trigger in overrides else "default" for trigger in ACTIONS},
        "updated_by": custom.updated_by if custom and custom.updated_by else default.updated_by if default else None,
        "updated_at": custom.updated_at if custom and custom.revision else default.updated_at if default else None,
    }


def legacy_policy_rules(mode: str):
    if mode == "block":
        return {**DEFAULT_RULES, **{trigger: "quarantine" for trigger in ACTIONS if not trigger.endswith("scan_rejected")}}
    if mode == "repair":
        return {**DEFAULT_RULES, "trusted_content_changed": "restore_trusted"}
    return dict(DEFAULT_RULES)


def preview(db: Session, scope: str, change: PolicyChange):
    default_scope = scope == DEFAULT_SCOPE
    current = policy_view(db, None if default_scope else scope)
    if current["version"] != change.expected_version:
        raise ApiError(409, "client.policy_changed", "策略已变化，请重新加载预览", "Policy changed; reload the preview")
    if not current["supported"]:
        raise ApiError(409, "client.policy_upgrade_required", "请先升级客户端以支持分类策略", "Upgrade the Client before enabling classification policies")
    clients = db.query(models.ManagedClient)
    if not default_scope:
        clients = clients.filter(models.ManagedClient.client_id == scope)
    items, scopes, excluded_clients, incompatible_clients = [], [], [], []
    for client in clients.order_by(models.ManagedClient.client_id).all():
        view = policy_view(db, client.client_id)
        if default_scope and not view["enabled"]:
            excluded_clients.append({"client_id": client.client_id, "client_name": client.name,
                                     "reason": "heartbeat_required" if view["supported"] else "upgrade_required"})
            continue
        scopes.append({"client_id": client.client_id, "client_name": client.name, "version": view["version"]})
        defaults = policy_view(db)["rules"]
        rules = {**DEFAULT_RULES, **change.rules, **view["overrides"]} if default_scope else {**defaults, **change.rules}
        unsupported = incompatible_rules(rules, view["protocol"])
        if unsupported:
            incompatible_clients.append({"client_id": client.client_id, "client_name": client.name, "rules": unsupported})
        skills = db.query(models.ClientSkillInstall).filter(models.ClientSkillInstall.client_id == client.client_id)
        for skill in skills.order_by(models.ClientSkillInstall.id).all():
            observation = json.loads(skill.governance_json or "{}")
            trigger = observation.get("trigger")
            try:
                observed_at = datetime.fromisoformat(observation.get("last_seen_at", "").replace("Z", "+00:00"))
                age = datetime.now(timezone.utc) - observed_at
                fresh = timedelta(0) <= age <= timedelta(seconds=1800)
            except (TypeError, ValueError):
                fresh = False
            valid = bool(skill.signature and observation.get("signature") == skill.signature
                         and observation.get("policy_version") == view["version"] and fresh
                         and observation.get("certification") in {"certified", "unverified", "changed"})
            known = valid and (trigger in ACTIONS or (not trigger and observation.get("certification") == "certified"))
            reason = None
            if not known:
                if skill.status in {"broken_link", "unscannable", "external_link"}:
                    reason = skill.status
                elif not observation or not skill.signature:
                    reason = "missing_observation"
                elif observation.get("signature") != skill.signature:
                    reason = "content_changed"
                elif observation.get("policy_version") != view["version"]:
                    reason = "policy_changed"
                elif not fresh:
                    reason = "observation_expired"
                else:
                    reason = "classification_pending"
            before = view["rules"][trigger] if known and trigger else "none" if known else None
            after = rules[trigger] if known and trigger else "none" if known else None
            overridden = bool(default_scope and trigger in view["overrides"])
            items.append({"client_id": client.client_id, "client_name": client.name, "agent_type": skill.agent_type,
                          "skill_name": skill.skill_name, "path": skill.skill_path, "signature": skill.signature,
                          "trigger": trigger if known else None, "current_action": before, "proposed_action": after,
                          "effect": "recheck" if not known else "changed" if before != after else "unchanged",
                          "recheck_reason": reason,
                          "client_override": overridden, "observed_at": observation.get("last_seen_at")})
    digest = hashlib.sha256(json.dumps({"scope": scope, "version": current["version"], "rules": change.rules,
                                        "clients": scopes, "excluded_clients": excluded_clients, "incompatible_clients": incompatible_clients,
                                        "items": [{key: value for key, value in item.items() if key != "observed_at"} for item in items]}, sort_keys=True).encode()).hexdigest()
    return {"preview_id": digest, "version": current["version"], "items": items, "clients": scopes, "client_count": len(scopes),
            "candidate_count": len(items), "excluded_clients": excluded_clients,
            "incompatible_clients": incompatible_clients, "rules": change.rules, "contains_uninstall": "uninstall" in change.rules.values()}


def save_policy(db: Session, scope: str, change: PolicyChange, user):
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    result = preview(db, scope, change)
    if result["incompatible_clients"]:
        raise ApiError(409, "client.policy_capability_required", "部分客户端不支持所选动作，请升级客户端后重新预览", "Some clients do not support the selected actions. Upgrade them and preview again")
    if change.preview_id != result["preview_id"]:
        raise ApiError(409, "client.policy_preview_required", "请确认最新影响范围后保存策略", "Confirm the latest impact preview before saving")
    previous = {item["client_id"]: policy_view(db, item["client_id"]) for item in result["clients"]}
    row = db.get(models.ClientGovernancePolicy, scope)
    if row is None:
        row = models.ClientGovernancePolicy(scope=scope, revision=0)
        db.add(row)
    row.rules_json = json.dumps(change.rules, sort_keys=True)
    row.revision += 1
    row.enabled = True
    row.updated_by = user.username
    row.updated_at = datetime.utcnow()
    db.flush()
    for client_id, before in previous.items():
        after = policy_view(db, client_id)
        outstanding = db.query(models.ClientTask.id).filter(
            models.ClientTask.client_id == client_id, models.ClientTask.task_type == "sync_policy",
            models.ClientTask.status.in_(("pending", "running")),
        ).first()
        if before["rules"] == after["rules"] and before["enabled"] == after["enabled"] and not outstanding:
            continue
        db.query(models.ClientTask).filter(
            models.ClientTask.client_id == client_id, models.ClientTask.task_type == "sync_policy",
            models.ClientTask.status.in_(("pending", "running")),
        ).update({"status": "cancelled", "error": "policy_superseded", "finished_at": datetime.utcnow()}, synchronize_session=False)
        payload = {"reason": "classification_policy_changed", "target_version": after["version"], "previous_version": before["version"]}
        db.add(models.ClientTask(client_id=client_id, task_type="sync_policy", payload_json=json.dumps(payload),
                                request_key=hashlib.sha256(f"policy:{client_id}:{after['version']}".encode()).hexdigest()))
    db.flush()
    return policy_view(db, None if scope == DEFAULT_SCOPE else scope)
