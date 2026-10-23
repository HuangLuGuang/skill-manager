"""Versioned Client classification policies and migration previews."""

from .aidr_products import HookAgentID, LogAgentID, BY_ID
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from . import models
from .api_errors import ApiError
from .client_desktop_menu import DEFAULT_MENUS, MenuVisibility

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


class PromptGuardConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["off", "log", "warn", "block"] = "log"
    llm_review: bool = False


class CompressionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    level: Literal["auto", "conservative", "aggressive"] = "auto"


class ReceiverRetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["none", "fixed", "continuous"] = "fixed"
    retries: int = Field(default=2, ge=0, le=20)
    max_interval_seconds: int = Field(default=300, ge=10, le=3600)


class RuntimeCollectionChannels(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    logs: bool = False
    hooks: bool = False
    system: bool = False


class RuntimeProtectionModes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hooks: Literal["audit", "intercept"] | None = "audit"
    system: Literal["audit", "intercept"] | None = "audit"


class SystemCollectionTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selection_mode: Literal["client", "platform"] = "client"
    products: list[Literal["codex", "claude", "workbuddy", "custom"]] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def unique_products(self):
        if len(set(self.products)) != len(self.products):
            raise ValueError("aidr_system_duplicate_product")
        return self


class RuntimeGovernanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: RuntimeCollectionChannels | None = None
    # Null preserves pre-mode installations until an administrator selects modes.
    modes: RuntimeProtectionModes | None = None
    enabled: bool = True
    system_targets: SystemCollectionTargets | None = None
    hosts: list[HookAgentID] = Field(default_factory=list, max_length=32)
    allow_user_enrollment: bool = True
    log_sources: list[LogAgentID] | None = Field(default=None, min_length=1, max_length=32)
    installation: Literal["automatic", "manual"] = "manual"
    access_mode: Literal["ordinary", "managed"] = "ordinary"
    updates: Literal["automatic", "manual"] = "manual"
    retry: ReceiverRetryConfig = Field(default_factory=ReceiverRetryConfig)

    @model_validator(mode="after")
    def unique_hosts(self):
        if len(set(self.hosts)) != len(self.hosts):
            raise ApiError(422, "aidr.runtime_duplicate_host", "宿主重复", "Duplicate host")
        if self.log_sources is not None and len(set(self.log_sources)) != len(self.log_sources):
            raise ApiError(422, "aidr.runtime_duplicate_source", "日志来源重复", "Duplicate log source")
        if self.access_mode == 'managed' and any(not BY_ID[h]['managed'] for h in self.hosts):
            raise ApiError(422, "aidr.managed_product_unsupported", "所选产品不支持系统级受管安装", "A selected product does not support managed installation")
        return self


def default_runtime_governance():
    """Effective onboarding policy when no administrator override exists."""
    return RuntimeGovernanceConfig(
        channels=RuntimeCollectionChannels(logs=True, hooks=True),
        modes=RuntimeProtectionModes(), hosts=["codex", "claude"],
        installation="automatic", updates="automatic",
    ).model_dump()


class ModelRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_gateway_enabled: bool = False
    external_gateway_id: int | None = Field(default=None, ge=1)
    auto_register_agent: bool = True
    client_select_model: bool = True

    @model_validator(mode="after")
    def gateway_required_when_enabled(self):
        if self.external_gateway_enabled and self.external_gateway_id is None:
            raise ApiError(
                422,
                "client.external_gateway_required",
                "启用外部网关时必须选择网关连接",
                "An external gateway connection is required when external routing is enabled",
            )
        return self


def effective_model_routing(default: dict | None, override: dict | None) -> dict:
    """Apply a client override without allowing it to widen the platform policy."""
    platform = {**ModelRoutingConfig().model_dump(), **(default or {})}
    if not override:
        return platform
    effective = {**platform, **override}
    effective["external_gateway_enabled"] = bool(
        platform["external_gateway_enabled"] and override.get("external_gateway_enabled", True)
    )
    if override.get("external_gateway_id") not in (None, platform.get("external_gateway_id")):
        effective["external_gateway_enabled"] = False
    effective["external_gateway_id"] = platform.get("external_gateway_id")
    effective["auto_register_agent"] = bool(
        platform["auto_register_agent"] and override.get("auto_register_agent", True)
    )
    effective["client_select_model"] = bool(
        platform["client_select_model"] and override.get("client_select_model", True)
    )
    return effective


def automatic_credentials(db: Session, client_id: str):
    return db.query(models.AccessToken).filter(
        models.AccessToken.token_type == "agent_runtime",
        models.AccessToken.created_by == f"client:{client_id}",
        models.AccessToken.issued_by_client_token_id.isnot(None),
        models.AccessToken.status == "active",
    )


class PolicyChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: dict[str, str] = Field(default_factory=dict)
    expected_version: str
    preview_id: str | None = None
    prompt_guard: PromptGuardConfig | None = None
    compression: CompressionConfig | None = None
    model_routing: ModelRoutingConfig | None = None
    runtime_governance: RuntimeGovernanceConfig | None = None
    desktop_menu_visibility: MenuVisibility = Field(default_factory=dict)

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
            row.runtime_revision = row.revision
        row.enabled = True
        row.updated_at = datetime.utcnow()
    db.flush()
    return row


def policy_view(db: Session, client_id: str | None = None):
    default = db.get(models.ClientGovernancePolicy, DEFAULT_SCOPE)
    custom = db.get(models.ClientGovernancePolicy, client_id) if client_id else None
    from .runtime_governance import HookEnrollment
    enrollment = db.get(HookEnrollment, client_id) if client_id else None
    return _policy_view(default, custom, enrollment, client_id)


def record_desktop_menus(db, client_id, protocol, applied):
    row = db.get(models.ClientGovernancePolicy, client_id)
    row.desktop_menu_protocol = protocol
    if protocol == 1 and applied is not None and set(applied) == set(DEFAULT_MENUS):
        row.desktop_menu_applied_json = json.dumps(applied, sort_keys=True)
        row.desktop_menu_reported_at = datetime.utcnow()
    elif protocol == 0:
        row.desktop_menu_applied_json = None
        row.desktop_menu_reported_at = None
    else:
        row.desktop_menu_applied_json = None


def policy_views(db: Session, client_ids):
    """Request-local policy reads for a bounded group of visible clients."""
    from .runtime_governance import HookEnrollment
    policies = {row.scope: row for row in db.query(models.ClientGovernancePolicy).filter(
        models.ClientGovernancePolicy.scope.in_([DEFAULT_SCOPE, *client_ids]))}
    enrollments = {row.client_id: row for row in db.query(HookEnrollment).filter(
        HookEnrollment.client_id.in_(client_ids))}
    return {cid: _policy_view(policies.get(DEFAULT_SCOPE), policies.get(cid), enrollments.get(cid), cid)
            for cid in client_ids}


def _policy_view(default, custom, enrollment, client_id):
    menu_default = {**DEFAULT_MENUS, **(json.loads(default.desktop_menu_visibility_json) if default else {})}
    menu_override = json.loads(custom.desktop_menu_visibility_json) if custom else {}
    menu_effective = {**menu_default, **menu_override}
    menu_supported = bool(custom and custom.desktop_menu_protocol == 1)
    menu_applied = json.loads(custom.desktop_menu_applied_json) if custom and custom.desktop_menu_applied_json else None
    defaults = {**DEFAULT_RULES, **(json.loads(default.rules_json) if default else {})}
    overrides = json.loads(custom.rules_json) if custom else {}
    rules = {**defaults, **overrides}
    default_revision = default.revision if default else 0
    runtime_default = (json.loads(default.runtime_governance_json) if default else None)
    runtime_builtin = runtime_default is None
    if runtime_default is None:
        runtime_default = default_runtime_governance()
    runtime_override = json.loads(custom.runtime_governance_json) if custom else None
    runtime_default = {"allow_user_enrollment": True, **runtime_default}
    if runtime_override is not None:
        runtime_override = {"allow_user_enrollment": True, **runtime_override}
    runtime = dict(runtime_override if runtime_override is not None else runtime_default)
    from .runtime_governance import hook_target
    user_hosts = json.loads(enrollment.hosts_json) if enrollment else []
    if runtime["allow_user_enrollment"] and runtime["access_mode"] == "ordinary" and hook_target(runtime):
        runtime["hosts"] = list(dict.fromkeys([*runtime["hosts"], *user_hosts]))
        # Products may enroll a paired log source. Channel permission remains
        # platform-owned; preserve explicitly selected sources and legacy defaults.
        if (runtime.get("channels") or {}).get("logs"):
            from .aidr_products import BY_ID
            paired = [BY_ID[host]["enrollment_log_source"] for host in user_hosts
                      if host in BY_ID and BY_ID[host].get("enrollment_log_source")]
            if paired:
                runtime["log_sources"] = list(dict.fromkeys([*(runtime.get("log_sources") or ["claude", "codex"]), *paired]))

    revision = custom.revision if custom else 0
    runtime_default_revision = default.runtime_revision if default and default.runtime_revision is not None else default_revision
    runtime_client_revision = custom.runtime_revision if custom and custom.runtime_revision is not None else revision
    guard_default = (json.loads(default.prompt_guard_json) if default else None) or PromptGuardConfig().model_dump()
    guard_override = json.loads(custom.prompt_guard_json) if custom else None
    compression_default = (json.loads(default.compression_json) if default else None) or CompressionConfig().model_dump()
    compression_override = json.loads(custom.compression_json) if custom else None
    routing_default = (json.loads(default.model_routing_json) if default else None) or ModelRoutingConfig().model_dump()
    routing_override = json.loads(custom.model_routing_json) if custom else None
    effective_routing = effective_model_routing(routing_default, routing_override)
    return {
        "desktop_menu_visibility": menu_effective,
        "desktop_menu_defaults": menu_default,
        "desktop_menu_overrides": menu_override,
        "desktop_menu_sources": {key: "client" if key in menu_override else "default" for key in DEFAULT_MENUS},
        "desktop_menu_supported": client_id is None or menu_supported,
        "desktop_menu_sync_status": "unsupported" if not menu_supported else "synced" if menu_applied == menu_effective else "pending",
        "desktop_menu_reported_at": custom.desktop_menu_reported_at if custom else None,
        "protocol": custom.protocol if custom else 2,
        "advanced_supported": client_id is None or bool(custom and custom.protocol == 2),
        "incompatible_rules": incompatible_rules(rules, custom.protocol) if custom else [],
        "supported": client_id is None or bool(custom and custom.protocol in (1, 2)),
        "enabled": client_id is None or bool(custom and custom.enabled and custom.protocol in (1, 2)),
        "version": f"{default_revision}:{revision}",
        "scan_version": f"{runtime_default_revision}:{runtime_client_revision}",
        "runtime_governance": runtime or RuntimeGovernanceConfig().model_dump(),
        "runtime_channels_protocol": 3,
        "runtime_governance_configured": runtime is not None,
        "runtime_governance_version": f"{runtime_default_revision}:{runtime_client_revision}" if runtime_override is not None or enrollment else str(runtime_default_revision),
        "runtime_user_hosts": user_hosts,
        "runtime_governance_default": runtime_default,
        "runtime_governance_override": runtime_override,
        "runtime_governance_source": "client" if runtime_override is not None else "default",
        "runtime_governance_builtin": runtime_builtin and runtime_override is None,
        "rules": rules,
        "prompt_guard": guard_override or guard_default,
        "prompt_guard_default": guard_default,
        "prompt_guard_override": guard_override,
        "prompt_guard_source": "client" if guard_override else "default",
        "compression": compression_override or compression_default,
        "compression_default": compression_default,
        "compression_override": compression_override,
        "compression_source": "client" if compression_override else "default",
        "model_routing": effective_routing,
        "model_routing_default": routing_default,
        "model_routing_override": routing_override,
        "model_routing_source": "client" if routing_override else "default",
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
    if default_scope and "runtime_governance" in change.model_fields_set and change.runtime_governance is None:
        raise ApiError(422, "aidr.runtime_policy_required", "请提供明确的运行治理目标", "An explicit runtime governance target is required")
    current = policy_view(db, None if default_scope else scope)
    menu_impacts = []
    if current["version"] != change.expected_version:
        raise ApiError(409, "client.policy_changed", "策略已变化，请重新加载预览", "Policy changed; reload the preview")
    menu_only_request = ("desktop_menu_visibility" in change.model_fields_set
                         and change.model_fields_set <= {"desktop_menu_visibility", "rules", "expected_version", "preview_id"}
                         and change.rules == current["overrides"])
    if not current["supported"] and not menu_only_request:
        raise ApiError(409, "client.policy_upgrade_required", "请先升级客户端以支持分类策略", "Upgrade the Client before enabling classification policies")
    clients = db.query(models.ManagedClient)
    if not default_scope:
        clients = clients.filter(models.ManagedClient.client_id == scope)
    items, scopes, excluded_clients, incompatible_clients, prompt_impacts, compression_impacts, model_routing_impacts = [], [], [], [], [], [], []
    if "model_routing" in change.model_fields_set and change.model_routing and change.model_routing.external_gateway_enabled:
        gateway = db.get(models.ExternalAIGateway, change.model_routing.external_gateway_id)
        if not gateway or not gateway.enabled:
            raise ApiError(
                409,
                "client.external_gateway_unavailable",
                "所选外部 AI 网关不存在或未启用",
                "The selected external AI gateway is missing or disabled",
            )
    for client in clients.order_by(models.ManagedClient.client_id).all():
        view = policy_view(db, client.client_id)
        proposed_menus = view["desktop_menu_visibility"]
        if "desktop_menu_visibility" in change.model_fields_set:
            proposed_menus = ({**DEFAULT_MENUS, **change.desktop_menu_visibility, **view["desktop_menu_overrides"]}
                              if default_scope else {**view["desktop_menu_defaults"], **change.desktop_menu_visibility})
        menu_impacts.append({"client_id": client.client_id, "client_name": client.name,
                             "current": view["desktop_menu_visibility"], "proposed": proposed_menus,
                             "supported": view["desktop_menu_supported"],
                             "preserved_overrides": [key for key in view["desktop_menu_overrides"]
                                 if default_scope and "desktop_menu_visibility" in change.model_fields_set
                                 and view["desktop_menu_defaults"][key] != change.desktop_menu_visibility.get(key, True)]})
        proposed_guard = view["prompt_guard"]
        if "prompt_guard" in change.model_fields_set:
            configured = change.prompt_guard.model_dump() if change.prompt_guard else None
            proposed_guard = ((view["prompt_guard_override"] or configured or PromptGuardConfig().model_dump())
                              if default_scope else (configured or view["prompt_guard_default"]))
        credentials = automatic_credentials(db, client.client_id).all()
        changed_credentials = sum(
            token.prompt_guard_mode != proposed_guard["mode"] or token.prompt_guard_llm_review != proposed_guard["llm_review"]
            for token in credentials
        ) if "prompt_guard" in change.model_fields_set else 0
        prompt_impacts.append({"client_id": client.client_id, "client_name": client.name,
                               "current": view["prompt_guard"], "proposed": proposed_guard,
                               "credential_count": len(credentials), "changed_credentials": changed_credentials})
        proposed_compression = view["compression"]
        if "compression" in change.model_fields_set:
            configured = change.compression.model_dump() if change.compression else None
            proposed_compression = ((view["compression_override"] or configured or CompressionConfig().model_dump())
                                    if default_scope else (configured or view["compression_default"]))
        compression_impacts.append({
            "client_id": client.client_id, "client_name": client.name,
            "current": view["compression"], "proposed": proposed_compression,
            "credential_count": len(credentials),
            "changed_credentials": sum(
                token.enable_compression != proposed_compression["enabled"] or token.compression_level != proposed_compression["level"]
                for token in credentials
            ) if "compression" in change.model_fields_set else 0,
        })
        proposed_routing = view["model_routing"]
        if "model_routing" in change.model_fields_set:
            configured = change.model_routing.model_dump() if change.model_routing else None
            if default_scope:
                proposed_routing = effective_model_routing(
                    configured or ModelRoutingConfig().model_dump(),
                    view["model_routing_override"],
                )
            else:
                proposed_routing = effective_model_routing(view["model_routing_default"], configured)
        model_routing_impacts.append({
            "client_id": client.client_id,
            "client_name": client.name,
            "current": view["model_routing"],
            "proposed": proposed_routing,
        })
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
    runtime_proposed = current["runtime_governance"]
    if "runtime_governance" in change.model_fields_set:
        runtime_proposed = change.runtime_governance.model_dump() if change.runtime_governance else current["runtime_governance_default"] or RuntimeGovernanceConfig().model_dump()
    digest = hashlib.sha256(json.dumps({"scope": scope, "version": current["version"], "rules": change.rules,
                                        "desktop_menu_visibility": change.desktop_menu_visibility,
                                        "desktop_menu_set": "desktop_menu_visibility" in change.model_fields_set,
                                        "desktop_menu_impacts": menu_impacts,
                                        "runtime_governance": change.runtime_governance.model_dump() if change.runtime_governance else None,
                                        "runtime_governance_set": "runtime_governance" in change.model_fields_set,
                                        "prompt_guard": change.prompt_guard.model_dump() if change.prompt_guard else None,
                                        "prompt_guard_set": "prompt_guard" in change.model_fields_set, "prompt_impacts": prompt_impacts,
                                        "compression": change.compression.model_dump() if change.compression else None,
                                        "compression_set": "compression" in change.model_fields_set, "compression_impacts": compression_impacts,
                                        "model_routing": change.model_routing.model_dump() if change.model_routing else None,
                                        "model_routing_set": "model_routing" in change.model_fields_set,
                                        "model_routing_impacts": model_routing_impacts,
                                        "clients": scopes, "excluded_clients": excluded_clients, "incompatible_clients": incompatible_clients,
                                        "items": [{key: value for key, value in item.items() if key != "observed_at"} for item in items]}, sort_keys=True).encode()).hexdigest()
    return {"preview_id": digest, "version": current["version"], "items": items, "clients": scopes, "client_count": len(scopes),
            "desktop_menu_impacts": menu_impacts,
            "desktop_menu_current": current["desktop_menu_visibility"],
            "desktop_menu_proposed": (menu_impacts[0]["proposed"] if not default_scope and menu_impacts else
                                      {**DEFAULT_MENUS, **change.desktop_menu_visibility} if "desktop_menu_visibility" in change.model_fields_set else current["desktop_menu_visibility"]),
            "runtime_current": current["runtime_governance"],
            "runtime_proposed": runtime_proposed,
            "prompt_impacts": prompt_impacts,
            "compression_impacts": compression_impacts,
            "model_routing_impacts": model_routing_impacts,
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
    previous_scope = policy_view(db, None if scope == DEFAULT_SCOPE else scope)
    row = db.get(models.ClientGovernancePolicy, scope)
    if row is None:
        row = models.ClientGovernancePolicy(scope=scope, revision=0)
        db.add(row)
    row.rules_json = json.dumps(change.rules, sort_keys=True)
    if "desktop_menu_visibility" in change.model_fields_set:
        row.desktop_menu_visibility_json = json.dumps(change.desktop_menu_visibility, sort_keys=True)
    if "prompt_guard" in change.model_fields_set:
        row.prompt_guard_json = json.dumps(change.prompt_guard.model_dump() if change.prompt_guard else None, sort_keys=True)
    if "compression" in change.model_fields_set:
        row.compression_json = json.dumps(change.compression.model_dump() if change.compression else None, sort_keys=True)
    if "model_routing" in change.model_fields_set:
        row.model_routing_json = json.dumps(change.model_routing.model_dump() if change.model_routing else None, sort_keys=True)
    if "runtime_governance" in change.model_fields_set:
        row.runtime_governance_json = json.dumps(change.runtime_governance.model_dump() if change.runtime_governance else None, sort_keys=True)
    previous_runtime_revision = row.runtime_revision if row.runtime_revision is not None else row.revision
    row.revision += 1
    if previous_scope["supported"]:
        row.enabled = True
    row.updated_by = user.username
    row.updated_at = datetime.utcnow()
    db.flush()
    saved_scope = policy_view(db, None if scope == DEFAULT_SCOPE else scope)
    menu_only = "desktop_menu_visibility" in change.model_fields_set and all(previous_scope[key] == saved_scope[key] for key in (
        "rules", "overrides", "prompt_guard", "prompt_guard_override", "compression", "compression_override",
        "model_routing", "model_routing_override", "runtime_governance", "enabled",
    ))
    row.runtime_revision = previous_runtime_revision if menu_only else row.revision
    db.flush()
    for item in result["prompt_impacts"]:
        view = policy_view(db, item["client_id"])
        updates = {}
        if "prompt_guard" in change.model_fields_set:
            updates.update(prompt_guard_mode=view["prompt_guard"]["mode"], prompt_guard_llm_review=view["prompt_guard"]["llm_review"])
        if "compression" in change.model_fields_set:
            updates.update(enable_compression=view["compression"]["enabled"], compression_level=view["compression"]["level"])
        if updates:
            automatic_credentials(db, item["client_id"]).update(updates, synchronize_session="fetch")
    for client_id, before in previous.items():
        after = policy_view(db, client_id)
        outstanding = db.query(models.ClientTask).filter(
            models.ClientTask.client_id == client_id, models.ClientTask.task_type == "sync_policy",
            models.ClientTask.status.in_(("pending", "running")),
        ).all()
        routing_changed = before["model_routing"] != after["model_routing"]
        menus_changed = (before["desktop_menu_visibility"] != after["desktop_menu_visibility"]
                         or before["desktop_menu_sources"] != after["desktop_menu_sources"])
        if (before["rules"] == after["rules"] and before["prompt_guard"] == after["prompt_guard"]
                and before["prompt_guard_source"] == after["prompt_guard_source"]
                and before["compression"] == after["compression"] and before["compression_source"] == after["compression_source"]
                and not routing_changed and not menus_changed
                and before["enabled"] == after["enabled"] and not outstanding):
            continue
        db.query(models.ClientTask).filter(
            models.ClientTask.client_id == client_id, models.ClientTask.task_type == "sync_policy",
            models.ClientTask.status.in_(("pending", "running")),
        ).update({"status": "cancelled", "error": "policy_superseded", "finished_at": datetime.utcnow()}, synchronize_session=False)
        only_routing_changed = routing_changed and (
            before["rules"] == after["rules"]
            and before["prompt_guard"] == after["prompt_guard"]
            and before["prompt_guard_source"] == after["prompt_guard_source"]
            and before["compression"] == after["compression"]
            and before["compression_source"] == after["compression_source"]
            and before["enabled"] == after["enabled"]
        )
        payload = {
            "reason": "model_routing_policy_changed" if only_routing_changed else "classification_policy_changed",
            "target_version": after["version"],
            "previous_version": before["version"],
        }
        if (menus_changed or outstanding) and all(json.loads(task.payload_json).get("reason") == "desktop_menu_visibility_changed" for task in outstanding) and all(before[key] == after[key] for key in (
            "rules", "prompt_guard", "prompt_guard_source", "compression", "compression_source",
            "model_routing", "runtime_governance", "enabled",
        )):
            payload["reason"] = "desktop_menu_visibility_changed"
        db.add(models.ClientTask(client_id=client_id, task_type="sync_policy", payload_json=json.dumps(payload),
                                request_key=hashlib.sha256(f"policy:{client_id}:{after['version']}".encode()).hexdigest()))
    db.flush()
    return policy_view(db, None if scope == DEFAULT_SCOPE else scope)
