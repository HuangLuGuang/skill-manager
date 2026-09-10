from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_manager.core.mcp_parameter_risk import classify_mcp_parameter, normalize_mcp_identifier
from aig_adapter import ScanStopped

AIG_TAG = "v4.6.0"
AIG_COMMIT = "e8931cc68001b66ad024fd87ef07394e9e96524a"
MCP_METADATA_ENGINE_NAME = "agent-manager-mcp-metadata-adapter"
MCP_METADATA_REPORT_SCHEMA = "agent-security-mcp-metadata-report@1"
VENDOR_ROOT = Path(__file__).resolve().parent / "vendor" / "ai-infra-guard" / "mcp-scan"
if not VENDOR_ROOT.is_dir():
    VENDOR_ROOT = Path("/opt/ai-infra-guard/mcp-scan")

MCP_RULES = {
    "MCP02": "Privilege Escalation & Scope Creep",
    "MCP03": "Tool Poisoning Attack",
    "MCP05": "Command Injection & Execution",
    "MCP06": "Prompt Injection Attack",
    "MCP10": "Context Injection & Over-sharing",
    "RUG_PULL": "Rug Pull Attack",
}

_LOCAL_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|above)\s+instructions?"),
    re.compile(r"(?i)(?:system|developer)\s*(?:prompt|message|override)\s*:"),
    re.compile(r"(?i)(?:send|upload|exfiltrate)\s+.*(?:secret|token|credential|password|environment)"),
    re.compile(r"(?:忽略|无视).{0,20}(?:之前|以上|系统).{0,20}(?:指令|提示)"),
    re.compile(r"(?:系统|开发者).{0,10}(?:指令|提示词).{0,5}[:：]"),
)

_SIDE_EFFECT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("delete", re.compile(r"(?i)(?:^|[_\-\s])(delete|remove|drop|destroy|purge|revoke)(?:$|[_\-\s])|删除|清空|销毁|撤销")),
    ("write", re.compile(r"(?i)(?:^|[_\-\s])(write|create|update|modify|set|execute|run|deploy)(?:$|[_\-\s])|写入|创建|修改|执行|发布")),
    ("transfer", re.compile(r"(?i)(?:^|[_\-\s])(transfer|pay|payment|withdraw|refund|trade)(?:$|[_\-\s])|转账|付款|支付|提现|退款|交易")),
    ("external_send", re.compile(r"(?i)(?:^|[_\-\s])(send|email|message|upload|export|publish)(?:$|[_\-\s])|发送|外发|上传|导出")),
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def _upstream_sanitize_description(value: str) -> str:
    patterns, max_length = _upstream_description_contract()
    sanitized = value
    for pattern in patterns:
        sanitized = re.sub(pattern, "[REMOVED]", sanitized)
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "... [truncated]"
    return sanitized


@lru_cache(maxsize=1)
def _upstream_description_contract() -> tuple[tuple[str, ...], int]:
    """Load the locked upstream sanitizer constants without importing its network SDK."""
    source_path = VENDOR_ROOT / "mcp_scan" / "utils" / "mcp_tools.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MCPTools":
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1 and isinstance(item.targets[0], ast.Name):
                    if item.targets[0].id in {"_INJECTION_PATTERNS", "_MAX_DESC_LEN"}:
                        values[item.targets[0].id] = ast.literal_eval(item.value)
    patterns = tuple(str(value) for value in values.get("_INJECTION_PATTERNS", ()))
    max_length = int(values.get("_MAX_DESC_LEN", 0))
    if not patterns or max_length < 1:
        raise RuntimeError("locked AI-Infra-Guard MCP sanitizer contract is unavailable")
    return patterns, max_length


def _redact(value: str, limit: int = 4096) -> str:
    text = str(value).replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", text)
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _normalize_identifier_text(value: str) -> str:
    return normalize_mcp_identifier(value)


def _asset(gateway: dict[str, Any], server: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "gateway_id": gateway.get("gateway_id"),
        "gateway_slug": gateway.get("gateway_slug"),
        "server_id": server.get("server_id"),
        "server_slug": server.get("server_slug"),
        "tool_id": tool.get("tool_id"),
        "tool_name": tool.get("name"),
        "exposed_name": tool.get("exposed_name"),
        "schema_hash": tool.get("schema_hash"),
        "approved_schema_hash": tool.get("approved_schema_hash"),
        "access_mode": tool.get("access_mode"),
        "risk_level": tool.get("risk_level"),
        "requires_approval": bool(tool.get("requires_approval")),
        "rate_limit_per_minute": tool.get("rate_limit_per_minute"),
        "max_concurrent": tool.get("max_concurrent"),
    }


def _compensating_controls(asset: dict[str, Any]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    if asset.get("requires_approval"):
        controls.append({"control": "requires_approval", "value": True})
    if asset.get("risk_level") not in {None, "", "unknown"}:
        controls.append({"control": "risk_level", "value": asset["risk_level"]})
    if asset.get("access_mode") not in {None, "", "unknown"}:
        controls.append({"control": "access_mode", "value": asset["access_mode"]})
    for key in ("rate_limit_per_minute", "max_concurrent"):
        value = asset.get(key)
        if isinstance(value, int) and value > 0:
            controls.append({"control": key, "value": value})
    return controls


def _remediation(asset: dict[str, Any], *actions: str) -> list[dict[str, Any]]:
    messages = {
        "require_approval": "Require explicit approval before calls to this tool.",
        "disable_tool": "Disable this tool until the finding is reviewed.",
        "restrict_call_policy": "Restrict callers, arguments, and rate limits for this tool.",
        "review_schema": "Review and approve the current schema hash before exposing the tool again.",
        "rewrite_description": "Remove executable or model-directed instructions from the tool description.",
    }
    if asset.get("requires_approval"):
        actions = tuple(action for action in actions if action != "require_approval")
    return [
        {
            "action": action,
            "execution": "suggestion_only",
            "message": messages[action],
            "target": {
                key: asset.get(key)
                for key in ("gateway_id", "server_id", "tool_id", "exposed_name")
                if asset.get(key) is not None
            },
        }
        for action in actions
    ]


def _finding(
    *,
    code: str,
    rule: str,
    severity: str,
    title: str,
    description: str,
    asset: dict[str, Any],
    evidence: dict[str, Any],
    remediation: list[dict[str, Any]],
    confidence: float,
) -> dict[str, Any]:
    return {
        "finding_code": code,
        "severity": severity,
        "status": "open",
        "title": title,
        "description": description,
        "evidence": {
            "asset": asset,
            "upstream_rule": rule,
            "upstream_rule_name": MCP_RULES[rule],
            "engine_tag": AIG_TAG,
            "engine_commit": AIG_COMMIT,
            "scan_mode": "metadata_snapshot_only",
            "tool_calls_performed": 0,
            "automatic_policy_changes": False,
            "remediation": remediation,
            **evidence,
        },
        "source": "agent_manager_mcp_metadata",
        "confidence": confidence,
    }


def _parameter_signals(schema: Any, *, path: str = "$") -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if isinstance(schema, dict):
        for raw_key, value in schema.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            description = str(value.get("description") or "") if isinstance(value, dict) else ""
            for category in classify_mcp_parameter(key, description=description, parent_path=path):
                signals.append({"path": child_path, "category": category})
            signals.extend(_parameter_signals(value, path=child_path))
    elif isinstance(schema, list):
        for index, value in enumerate(schema[:100]):
            signals.extend(_parameter_signals(value, path=f"{path}[{index}]"))
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in signals:
        unique[(item["path"], item["category"])] = item
    return list(unique.values())[:100]


def analyze_mcp_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    if not any(
        isinstance(server, dict) and isinstance(server.get("tools"), list) and server["tools"]
        for server in snapshot.get("servers", [])
    ):
        raise ValueError("MCP gateway asset snapshot contains no bound tools")
    cases: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    report_tools: list[dict[str, Any]] = []
    for server in snapshot.get("servers", []):
        for tool in server.get("tools", []):
            asset = _asset(snapshot, server, tool)
            exposed_name = str(tool.get("exposed_name") or tool.get("name") or "unknown")
            tool_findings: list[dict[str, Any]] = []
            if tool.get("missing"):
                tool_findings.append(
                    _finding(
                        code="mcp_bound_tool_missing",
                        rule="RUG_PULL",
                        severity="high",
                        title=f"Bound MCP tool is missing: {exposed_name}",
                        description="A tool recorded in the Gateway binding is no longer present in the discovered server inventory.",
                        asset=asset,
                        evidence={"inventory_state": "missing"},
                        remediation=_remediation(asset, "disable_tool", "review_schema"),
                        confidence=1.0,
                    )
                )
            else:
                description = str(tool.get("description") or "")
                raw_analysis = tool.get("raw_analysis") if isinstance(tool.get("raw_analysis"), dict) else {}
                projection = tool.get("projection") if isinstance(tool.get("projection"), dict) else {}
                upstream_sanitized = _upstream_sanitize_description(description)
                upstream_patterns, upstream_max_length = _upstream_description_contract()
                matched_upstream_patterns = [
                    pattern for pattern in upstream_patterns if re.search(pattern, description)
                ]
                matched_injections = [pattern.pattern for pattern in _LOCAL_INJECTION_PATTERNS if pattern.search(description)]
                full_description_injection = bool(raw_analysis.get("description_injection_detected"))
                if matched_upstream_patterns or matched_injections or full_description_injection:
                    tool_findings.append(
                        _finding(
                            code="mcp_tool_description_injection",
                            rule="MCP03",
                            severity="high",
                            title=f"Tool description contains model-directed instructions: {exposed_name}",
                            description="The MCP Tool description contains instruction-like content that can influence an Agent outside the declared Tool contract.",
                            asset=asset,
                            evidence={
                                "description_sha256": tool.get("description_sha256") or _sha256_text(description),
                                "sanitized_preview": _redact(upstream_sanitized, 512),
                                "matched_indicators": matched_injections[:20],
                                "matched_upstream_patterns": matched_upstream_patterns[:20],
                                "full_metadata_signal": full_description_injection,
                                "description_truncated_by_upstream_contract": len(description) > upstream_max_length,
                                "related_upstream_rules": ["MCP03", "MCP06"],
                            },
                            remediation=_remediation(asset, "rewrite_description", "disable_tool", "require_approval"),
                            confidence=0.95,
                        )
                    )

                operation_text = _normalize_identifier_text(f"{tool.get('name', '')} {description}")
                side_effect_categories = sorted(
                    {
                        *[category for category, pattern in _SIDE_EFFECT_RULES if pattern.search(operation_text)],
                        *[str(value) for value in raw_analysis.get("side_effect_categories", [])],
                    }
                )
                if side_effect_categories and bool(tool.get("enabled", True)) and (
                    not bool(tool.get("requires_approval")) or str(tool.get("risk_level", "low")) not in {"high", "critical"}
                ):
                    severity = "critical" if "transfer" in side_effect_categories else "high"
                    tool_findings.append(
                        _finding(
                            code="mcp_dangerous_tool_unprotected",
                            rule="MCP02",
                            severity=severity,
                            title=f"Side-effect MCP tool lacks high-risk controls: {exposed_name}",
                            description="The exposed Tool appears able to change state or send data but is not both classified high risk and protected by approval.",
                            asset=asset,
                            evidence={
                                "side_effect_categories": side_effect_categories,
                                "enabled": bool(tool.get("enabled", True)),
                                "risk_level": tool.get("risk_level"),
                                "requires_approval": bool(tool.get("requires_approval")),
                            },
                            remediation=_remediation(asset, "require_approval", "restrict_call_policy", "disable_tool"),
                            confidence=0.85,
                        )
                    )

                if str(tool.get("access_mode") or "unknown") == "unknown":
                    tool_findings.append(
                        _finding(
                            code="mcp_access_mode_unclassified",
                            rule="MCP02",
                            severity="info",
                            title=f"MCP Tool access mode has not been classified: {exposed_name}",
                            description="The metadata snapshot does not classify this Tool as read-only or state-changing. This is a governance gap, not evidence that the Tool is destructive.",
                            asset=asset,
                            evidence={"access_mode": "unknown", "destructive_behavior_confirmed": False},
                            remediation=_remediation(asset, "restrict_call_policy"),
                            confidence=1.0,
                        )
                    )

                parameter_signals = _parameter_signals(tool.get("input_schema") or {})
                for signal in raw_analysis.get("parameter_signals", []):
                    if isinstance(signal, dict) and signal.get("path") and signal.get("category"):
                        parameter_signals.append(
                            {"path": str(signal["path"])[:512], "category": str(signal["category"])[:128]}
                        )
                parameter_signals = list(
                    {
                        (item["path"], item["category"]): item
                        for item in parameter_signals
                    }.values()
                )[:100]
                if parameter_signals:
                    parameter_categories = {item["category"] for item in parameter_signals}
                    external_destination_only = parameter_categories == {"external_destination"}
                    controls = _compensating_controls(asset)
                    tool_findings.append(
                        _finding(
                            code="mcp_dangerous_parameters",
                            rule="MCP05",
                            severity="medium",
                            title=(
                                f"MCP Tool accepts an external destination and requires egress validation: {exposed_name}"
                                if external_destination_only
                                else f"MCP Tool exposes security-sensitive parameters: {exposed_name}"
                            ),
                            description=(
                                "The metadata declares an external-address input surface. No Tool call was performed, so this does not confirm SSRF or any exploitable vulnerability."
                                if external_destination_only
                                else "The Tool schema exposes parameters associated with sensitive operations. This metadata signal requires validation and is not a confirmed vulnerability."
                            ),
                            asset=asset,
                            evidence={
                                "parameter_signals": parameter_signals,
                                "risk_signal_only": True,
                                "confirmed_vulnerability": False,
                                "confirmed_ssrf": False if "external_destination" in parameter_categories else None,
                                "external_destination_input_surface": "external_destination" in parameter_categories,
                                "verification_required": (
                                    [
                                        "allowed_protocols",
                                        "dns_rebinding_protection",
                                        "private_network_address_blocking",
                                        "url_uuid_binding",
                                    ]
                                    if "external_destination" in parameter_categories
                                    else []
                                ),
                                "compensating_controls": controls,
                                "mitigation_status": "partially_mitigated" if asset.get("requires_approval") else "unmitigated",
                            },
                            remediation=_remediation(asset, "restrict_call_policy", "require_approval"),
                            confidence=0.75,
                        )
                    )

                projection_incomplete = bool(raw_analysis.get("analysis_limited")) or any(
                    bool(projection.get(key))
                    for key in ("description_truncated", "truncated_strings", "dropped_items", "depth_limited")
                )
                if projection_incomplete:
                    tool_findings.append(
                        _finding(
                            code="mcp_metadata_projection_incomplete",
                            rule="MCP10",
                            severity="high",
                            title=f"MCP Tool metadata exceeds safe projection limits: {exposed_name}",
                            description="The Tool metadata was too long, wide, or deep for the bounded Worker projection and requires manual review.",
                            asset=asset,
                            evidence={
                                "projection": projection,
                                "full_metadata_analysis_limited": bool(raw_analysis.get("analysis_limited")),
                            },
                            remediation=_remediation(asset, "disable_tool", "review_schema", "require_approval"),
                            confidence=1.0,
                        )
                    )

                current_hash = tool.get("schema_hash")
                approved_hash = tool.get("approved_schema_hash")
                if not approved_hash or current_hash != approved_hash:
                    tool_findings.append(
                        _finding(
                            code="mcp_schema_drift" if approved_hash else "mcp_schema_unapproved",
                            rule="RUG_PULL",
                            severity="high",
                            title=f"MCP Tool schema is not the approved schema: {exposed_name}",
                            description="The current Tool schema hash differs from the Gateway-approved snapshot or has no approved snapshot.",
                            asset=asset,
                            evidence={"schema_changed": bool(approved_hash and current_hash != approved_hash)},
                            remediation=_remediation(asset, "disable_tool", "review_schema"),
                            confidence=1.0,
                        )
                    )

            external_case_id = f"mcp-tool-{server.get('server_id')}-{tool.get('tool_id') or tool.get('name')}"[:256]
            for item in tool_findings:
                item["case_external_id"] = external_case_id
            findings.extend(tool_findings)
            cases.append(
                {
                    "external_case_id": external_case_id,
                    "category": "mcp_tool_metadata",
                    "title": f"MCP Tool metadata scan: {exposed_name}",
                    "status": "failed" if tool_findings else "passed",
                    "request_summary": {"asset": asset, "metadata_only": True},
                    "response_summary": {
                        "finding_codes": [item["finding_code"] for item in tool_findings],
                        "execution_status": "completed",
                        "assessment_status": "risk_signal_detected" if tool_findings else "no_risk_observed",
                        "finding_count": len(tool_findings),
                        "active_finding_count": len(tool_findings),
                        "scan_mode": "metadata_snapshot_only",
                        "tool_calls_performed": 0,
                    },
                    "round_count": 1,
                }
            )
            report_tools.append(
                {
                    "asset": asset,
                    "enabled": tool.get("enabled"),
                    "risk_level": tool.get("risk_level"),
                    "requires_approval": tool.get("requires_approval"),
                    "access_mode": tool.get("access_mode"),
                    "rate_limit_per_minute": tool.get("rate_limit_per_minute"),
                    "max_concurrent": tool.get("max_concurrent"),
                    "missing": bool(tool.get("missing")),
                    "description_sha256": tool.get("description_sha256")
                    or _sha256_text(str(tool.get("description") or "")),
                    "finding_codes": [item["finding_code"] for item in tool_findings],
                }
            )
    return {
        "schema_version": MCP_METADATA_REPORT_SCHEMA,
        "engine": {"name": MCP_METADATA_ENGINE_NAME, "version": "1"},
        "upstream_contract_reference": {
            "repository": "https://github.com/Tencent/AI-Infra-Guard",
            "tag": AIG_TAG,
            "commit": AIG_COMMIT,
            "reused_contracts": ["mcp_risk_taxonomy_labels", "tool_description_sanitizer"],
            "full_upstream_scan_executed": False,
        },
        "upstream_rules": MCP_RULES,
        "scan_mode": "metadata_snapshot_only",
        "safety": {
            "upstream_dynamic_mode": "disabled_by_policy",
            "tools_call_capability_exposed": False,
            "tool_calls_performed": 0,
            "automatic_policy_changes": False,
        },
        "gateway": {
            "gateway_id": snapshot.get("gateway_id"),
            "gateway_slug": snapshot.get("gateway_slug"),
            "gateway_status": snapshot.get("gateway_status"),
        },
        "tools": report_tools,
        "cases": cases,
        "findings": findings,
    }


def execute_mcp_scan(
    claim: dict[str, Any],
    heartbeat: Callable[[dict[str, int]], dict[str, Any]],
    *,
    initial_usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    options = claim.get("scan_options") or {}
    if not options.get("metadata_only") or options.get("side_effect_tool_calls") != "forbidden":
        raise ValueError("MCP scan must be metadata-only with side-effect calls forbidden")
    snapshot = (claim.get("target") or {}).get("mcp_assets")
    if not isinstance(snapshot, dict):
        raise ValueError("MCP gateway asset snapshot is missing")
    baseline = initial_usage or {
        "rounds": 0,
        "tokens": 0,
        "cost_microunits": 0,
        "concurrent_requests": 0,
        "response_bytes": 0,
    }
    status = heartbeat(baseline)
    if not status.get("continue_allowed", False):
        raise ScanStopped(str(status.get("stop_reason") or "scan_stopped"))
    report = analyze_mcp_snapshot(snapshot)
    raw_content = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    raw_bytes = raw_content.encode("utf-8")
    usage = {
        "rounds": int(baseline.get("rounds", 0)) + 1,
        "tokens": int(baseline.get("tokens", 0)),
        "cost_microunits": int(baseline.get("cost_microunits", 0)),
        "concurrent_requests": max(int(baseline.get("concurrent_requests", 0)), 1),
        "response_bytes": int(baseline.get("response_bytes", 0)) + len(raw_bytes),
    }
    status = heartbeat(usage)
    if not status.get("continue_allowed", False):
        raise ScanStopped(str(status.get("stop_reason") or "scan_stopped"))
    return {
        "status": "succeeded",
        "usage": usage,
        "cases": report["cases"],
        "findings": report["findings"],
        "artifacts": [
            {
                "artifact_type": "mcp-metadata-scan-report",
                "uri": f"artifact://{claim['task']['task_id']}/mcp-metadata-scan-report.json",
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "size_bytes": len(raw_bytes),
                "redacted": True,
                "metadata": {
                    "schema_version": MCP_METADATA_REPORT_SCHEMA,
                    "upstream_contract_tag": AIG_TAG,
                    "upstream_contract_commit": AIG_COMMIT,
                    "full_upstream_scan_executed": False,
                    "scan_mode": "metadata_snapshot_only",
                    "tool_calls_performed": 0,
                    "automatic_policy_changes": False,
                },
                "content": raw_content,
            }
        ],
        "engine_name": MCP_METADATA_ENGINE_NAME,
        "engine_version": f"1+aig-contract-{AIG_TAG}.{AIG_COMMIT[:12]}",
    }
