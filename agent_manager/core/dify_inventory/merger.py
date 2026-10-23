from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from agent_manager.core.mcp_parameter_risk import classify_mcp_parameter

from .schema import asset, field, source


def _first(mapping: dict[str, Any], *keys: str) -> tuple[Any, str | None]:
    for key in keys:
        value: Any = mapping
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, "", []):
            return value, key
    return None, None


def _profile_field(
    detail: dict[str, Any], dsl_app: dict[str, Any], *, detail_keys: tuple[str, ...], dsl_keys: tuple[str, ...],
    collected_at: str, missing_reason: str,
) -> dict[str, Any]:
    value, path = _first(detail, *detail_keys)
    if path:
        return field(value, source="dify_console_api", status="verified", collected_at=collected_at, source_identifier=path)
    value, path = _first(dsl_app, *dsl_keys)
    if path:
        return field(value, source="dsl", status="verified", collected_at=collected_at, source_identifier=f"app.{path}")
    return field(None, source=None, status="unavailable", collected_at=collected_at, missing_reason=missing_reason)


def _apply_runtime(items: list[dict[str, Any]], runtime_events: list[dict[str, Any]]) -> None:
    tool_counts = Counter(
        str(item.get("details", {}).get("tool_name") or "")
        for item in items if item.get("details", {}).get("tool_name")
    )
    for item in items:
        details = item.get("details", {})
        node_id = str(details.get("node_id") or "")
        tool_name = str(details.get("tool_name") or "")
        matches = [
            event for event in runtime_events
            if (node_id and str(event.get("node_id") or "") == node_id)
            or (
                tool_name and tool_counts[tool_name] == 1
                and not event.get("node_id")
                and str(event.get("tool_name") or "") == tool_name
            )
        ]
        if not matches:
            continue
        executed = [event for event in matches if (
            event.get("type") in {"tool.result", "tool.error", "model.response", "model.error", "knowledge.retrieval"}
            or (event.get("type") == "tool.call" and event.get("status") in {"started", "running"})
            or (not event.get("type") and event.get("status") == "succeeded")
        )]
        item["executed"] = bool(executed)
        item["sources"].append(source("runtime_trace", metadata={"event_count": len(matches)}))
        item["details"]["runtime"] = {
            "call_count": len(matches),
            "execution_event_count": len(executed),
            "blocked_count": sum(event.get("type") == "runtime.blocked" for event in matches),
            "first_executed_at": min((str(event.get("event_time") or "") for event in executed), default=None),
            "last_executed_at": max((str(event.get("event_time") or "") for event in executed), default=None),
            "statuses": dict(Counter(str(event.get("status") or "unknown") for event in matches)),
        }


def _mcp_parameter_signals(schema: Any, *, path: str = "$") -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    if isinstance(schema, dict):
        for raw_name, value in schema.items():
            name = str(raw_name)
            child_path = f"{path}.{name}"
            description = str(value.get("description") or "") if isinstance(value, dict) else ""
            for category in classify_mcp_parameter(name, description=description, parent_path=path):
                signals.append({"path": child_path, "category": category})
            signals.extend(_mcp_parameter_signals(value, path=child_path))
    elif isinstance(schema, list):
        for index, value in enumerate(schema[:100]):
            signals.extend(_mcp_parameter_signals(value, path=f"{path}[{index}]"))
    unique = {(item["path"], item["category"]): item for item in signals}
    return list(unique.values())[:100]


def _mcp_risk_findings(item: dict[str, Any], discovered_tool: dict[str, Any]) -> list[dict[str, Any]]:
    signals = _mcp_parameter_signals(discovered_tool.get("input_schema") or {})
    if not signals:
        return []
    controls = []
    if discovered_tool.get("requires_approval"):
        controls.append({"control": "requires_approval", "value": True})
    if discovered_tool.get("rate_limit_per_minute"):
        controls.append({"control": "rate_limit_per_minute", "value": discovered_tool["rate_limit_per_minute"]})
    if discovered_tool.get("max_concurrent"):
        controls.append({"control": "max_concurrent", "value": discovered_tool["max_concurrent"]})
    return [{
        "asset_id": item["asset_id"],
        "finding_code": "dify_inventory.mcp_sensitive_parameter_surface",
        "severity": "medium", "status": "open",
        "title": f"MCP Tool exposes security-sensitive parameters: {item['name']}",
        "description": "The tools/list schema exposes security-sensitive input surfaces. No Tool call was performed, so this is a metadata risk signal rather than a confirmed vulnerability.",
        "evidence": {
            "asset_id": item["asset_id"], "parameter_signals": signals,
            "schema_hash": discovered_tool.get("schema_hash"), "tool_calls_performed": 0,
            "signal_only": True, "confirmed_vulnerability": False,
            "compensating_controls": controls,
            "mitigation_status": "partially_mitigated" if discovered_tool.get("requires_approval") else "unmitigated",
        },
        "source": "agent-manager-dify-inventory", "confidence": 0.75,
    }]


def _apply_mcp(
    items: list[dict[str, Any]], mcp_bindings: list[dict[str, Any]], mcp_servers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    servers = {str(item.get("server_id")): item for item in mcp_servers}
    bindings = {str(item.get("provider_id")): item for item in mcp_bindings}
    findings: list[dict[str, Any]] = []
    configured_items = [item for item in items if item.get("asset_type") == "mcp"]
    for item in configured_items:
        provider_id = str(item.get("details", {}).get("provider_id") or "")
        binding = bindings.get(provider_id)
        if not binding:
            item["details"]["mcp_mapping_status"] = "unverified"
            continue
        server = servers.get(str(binding.get("server_id")))
        if not server:
            item["details"]["mcp_mapping_status"] = "unverified"
            continue
        discovered_tools = [tool for tool in server.get("tools", []) if isinstance(tool, dict) and tool.get("name")]
        configured_name = str(item.get("details", {}).get("tool_name") or "")
        matching_tool = next((tool for tool in discovered_tools if str(tool.get("name")) == configured_name), None)
        item["discovered"] = matching_tool is not None
        item["verification_status"] = "verified" if matching_tool is not None else "unverified"
        item["details"]["mcp_mapping_status"] = "verified" if matching_tool is not None else "configured_tool_not_discovered"
        item["details"]["mcp_server_id"] = server.get("server_id")
        item["details"]["mcp_server_discovered_at"] = server.get("discovered_at")
        item["details"]["schema_change_verification"] = "unavailable_without_explicit_approved_schema"
        if matching_tool is not None:
            item["details"]["discovered_tool"] = matching_tool
            item["sources"].append(source("mcp_tools_list", f"mcp_server:{server.get('server_id')}/tool:{configured_name}"))
            findings.extend(_mcp_risk_findings(item, matching_tool))

        node_id = str(item.get("details", {}).get("node_id") or "unknown")
        for discovered_tool in discovered_tools:
            tool_name = str(discovered_tool["name"])
            discovered_asset_id = f"tool:{node_id}:{provider_id}:{tool_name}"
            if discovered_asset_id == item["asset_id"]:
                continue
            discovered_item = asset(
                asset_id=discovered_asset_id, asset_type="mcp", name=tool_name,
                configured=False, discovered=True, executed=False, verification_status="verified",
                sources=[source("mcp_tools_list", f"mcp_server:{server.get('server_id')}/tool:{tool_name}")],
                details={
                    "node_id": node_id, "provider_id": provider_id, "tool_name": tool_name,
                    "mcp_mapping_status": "verified", "mcp_server_id": server.get("server_id"),
                    "mcp_server_discovered_at": server.get("discovered_at"),
                    "schema_change_verification": "unavailable_without_explicit_approved_schema",
                    "discovered_tool": discovered_tool,
                },
            )
            items.append(discovered_item)
            findings.extend(_mcp_risk_findings(discovered_item, discovered_tool))
    return findings


def build_inventory(
    dsl: dict[str, Any], *, target: dict[str, Any], app_detail: dict[str, Any] | None = None,
    knowledge_details: dict[str, dict[str, Any]] | None = None,
    mcp_servers: list[dict[str, Any]] | None = None, runtime_events: list[dict[str, Any]] | None = None,
    collection_source: str | None = None,
    knowledge_resolution: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    detail = app_detail or {}
    config = target.get("config") if isinstance(target.get("config"), dict) else {}
    app = dsl.get("app") if isinstance(dsl.get("app"), dict) else {}
    timestamp = str(dsl["collected_at"])
    declared_intent = config.get("declared_intent")
    explicit_intent, explicit_path = _first(detail, "intent", "metadata.intent")
    dsl_intent, dsl_path = _first(app, "intent")
    if explicit_path:
        verified_intent = field(explicit_intent, source="dify_console_api", status="verified", collected_at=timestamp, source_identifier=explicit_path)
    elif dsl_path:
        verified_intent = field(dsl_intent, source="dsl", status="verified", collected_at=timestamp, source_identifier=f"app.{dsl_path}")
    else:
        verified_intent = field(None, source=None, status="unverified", collected_at=timestamp, missing_reason="dify_has_no_standard_intent_field")
    declared_intent_field = field(
        declared_intent or None,
        source="platform_admin" if declared_intent else None,
        status="declared" if declared_intent else "unverified",
        collected_at=timestamp,
        source_identifier="target.config.declared_intent" if declared_intent else None,
        missing_reason=None if declared_intent else "not_declared",
    )
    inferred_intent = field(
        None, source="system_inference", status="unverified", collected_at=timestamp,
        missing_reason="intent_inference_not_enabled", rule_version="intent-inference@1",
    )
    if verified_intent.get("value"):
        intent = verified_intent
    elif declared_intent_field.get("value"):
        intent = declared_intent_field
    else:
        intent = field(None, source=None, status="unverified", collected_at=timestamp, missing_reason="dify_has_no_standard_intent_field")

    workspace_id = str(config.get("workspace_id") or "")
    app_id = str(config.get("app_id") or "")
    dsl_version = dsl.get("workflow", {}).get("dsl_version")
    profile = {
        "asset_id": field(f"agent:{app_id}", source="target_config", status="verified", collected_at=timestamp, source_identifier="target.config.app_id"),
        "name": _profile_field(detail, app, detail_keys=("name",), dsl_keys=("name",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "app_id": field(config.get("app_id"), source="target_config", status="declared", collected_at=timestamp, source_identifier="target.config.app_id"),
        "workspace_id": field(workspace_id or None, source="target_config", status="declared" if workspace_id else "unavailable", collected_at=timestamp, missing_reason=None if workspace_id else "not_configured"),
        "mode": _profile_field(detail, app, detail_keys=("mode", "app_mode"), dsl_keys=("mode",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "created_at": _profile_field(detail, app, detail_keys=("created_at", "created_time"), dsl_keys=("created_at",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "updated_at": _profile_field(detail, app, detail_keys=("updated_at", "updated_time"), dsl_keys=("updated_at",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "description": _profile_field(detail, app, detail_keys=("description",), dsl_keys=("description",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "intent": intent,
        "verified_intent": verified_intent,
        "declared_intent": declared_intent_field,
        "inferred_intent": inferred_intent,
        "intent_alignment": field("not_assessed", source="inventory_merger", status="unverified", collected_at=timestamp),
        "author": _profile_field(detail, app, detail_keys=("author_name", "created_by_name"), dsl_keys=("author_name",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "tags": _profile_field(detail, app, detail_keys=("tags",), dsl_keys=("tags",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "dsl_version": field(dsl_version, source="dsl", status="verified" if dsl_version else "unavailable", collected_at=timestamp, source_identifier="version", missing_reason=None if dsl_version else "not_exposed_by_source"),
        "workflow_id": field(dsl.get("workflow", {}).get("workflow_id"), source="dsl", status="verified" if dsl.get("workflow", {}).get("workflow_id") else "unavailable", collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "workflow_version": field(dsl.get("workflow", {}).get("version"), source="dsl", status="verified" if dsl.get("workflow", {}).get("version") else "unavailable", collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "published_status": _profile_field(detail, dsl.get("workflow", {}), detail_keys=("status", "published_at"), dsl_keys=("published",), collected_at=timestamp, missing_reason="not_exposed_by_source"),
        "environment": field(target.get("environment"), source="target_config", status="declared", collected_at=timestamp),
        "dify_base_url": field(config.get("console_base_url") or target.get("endpoint_url"), source="target_config", status="declared", collected_at=timestamp),
        "owner": field(config.get("platform_owner"), source="platform_admin", status="declared" if config.get("platform_owner") else "unavailable", collected_at=timestamp, missing_reason="not_declared"),
        "owner_group": field(config.get("platform_owner_group"), source="platform_admin", status="declared" if config.get("platform_owner_group") else "unavailable", collected_at=timestamp, missing_reason="not_declared"),
        "last_collected_at": field(timestamp, source="inventory_task", status="verified", collected_at=timestamp),
        "data_source": field(collection_source or ("dify_console_api" if app_detail is not None else "manual_dsl"), source="inventory_task", status="verified", collected_at=timestamp),
        "verification_status": field("partially_verified", source="inventory_merger", status="verified", collected_at=timestamp),
    }
    items = [*dsl.get("nodes", []), *dsl.get("prompts", []), *dsl.get("tools", []), *dsl.get("knowledge_bases", [])]
    knowledge_details = knowledge_details or {}
    knowledge_resolution = knowledge_resolution or {}
    for item in items:
        if item.get("asset_type") != "knowledge":
            continue
        details = item.get("details", {})
        reference = str(details.pop("dsl_reference", "") or "")
        resolution_key = f"{str(details.get('node_id') or '')}\x00{reference}"
        resolution = knowledge_resolution.get(resolution_key, knowledge_resolution.get(reference, {}))
        dataset_id = str(resolution.get("dataset_id") or "")
        node_id = str(details.get("node_id") or "unknown")
        details.update({
            "export_reference": {
                "sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                "redacted": True,
            } if reference else None,
            "dataset_reference_status": resolution.get("status", "unmapped"),
            "dataset_id": dataset_id or None,
            "resolved_dataset_id": dataset_id or None,
            "dataset_mapping_source": resolution.get("source_type"),
            "limitations": list(resolution.get("limitations") or []),
            **({"dataset_reference_error_code": resolution["error_code"]} if resolution.get("error_code") else {}),
            **({"mapping_context_error_code": resolution["mapping_context_error_code"]} if resolution.get("mapping_context_error_code") else {}),
        })
        if dataset_id:
            item["asset_id"] = f"knowledge:{dataset_id}:{node_id}"
        if resolution.get("source_type") and resolution.get("source_type") != "dsl":
            item["sources"].append(source(
                str(resolution["source_type"]),
                str(resolution.get("source_identifier") or "target.config.knowledge_bindings"),
            ))
        if dataset_id and dataset_id in knowledge_details:
            details["dataset"] = knowledge_details[dataset_id]
            item["name"] = str(knowledge_details[dataset_id].get("name") or item["name"])
            item["verification_status"] = (
                "partially_verified"
                if resolution.get("source_type") == "dify_console_draft_workflow"
                else "verified"
            )
            item["sources"].append(source("dify_knowledge_api", f"dataset:{dataset_id}"))
        elif resolution.get("status") in {"resolved", "unmapped", "ambiguous"}:
            item["verification_status"] = "unverified"
        elif resolution.get("status") == "unavailable":
            item["verification_status"] = "unavailable"
    findings = [*dsl.get("findings", []), *_apply_mcp(items, list(config.get("mcp_bindings") or []), mcp_servers or [])]
    matching_runtime = [e for e in (runtime_events or []) if not e.get("graph_digest")
                        or e["graph_digest"] == dsl.get("graph_sha256")]
    _apply_runtime(items, matching_runtime)
    grouped = {name: [item for item in items if item.get("asset_type") == kind] for name, kind in (
        ("nodes", "node"), ("prompts", "prompt"), ("mcp", "mcp"), ("tools", "tool"), ("knowledge_bases", "knowledge")
    )}
    coverage = {
        "dsl": "completed",
        "dify_console_api": "completed" if app_detail is not None else ("partial" if collection_source == "dify_console_api" else "unavailable"),
        "dify_knowledge_api": "completed" if knowledge_details else "unavailable",
        "mcp_tools_list": "completed" if grouped["mcp"] and all(item["details"].get("mcp_mapping_status") == "verified" for item in grouped["mcp"]) else ("partial" if grouped["mcp"] else "unavailable"),
        "runtime_trace": "partial" if runtime_events else "unavailable",
    }
    return {
        "schema_version": "dify-asset-inventory@1",
        "configuration_sha256": dsl.get("configuration_sha256"),
        "engine_name": "agent-manager-dify-inventory",
        "agent_profile": profile,
        "summary": {
            "nodes": len(grouped["nodes"]), "prompts": len(grouped["prompts"]),
            "mcp": len(grouped["mcp"]), "tools": len(grouped["tools"]),
            "knowledge_bases": len(grouped["knowledge_bases"]), "findings": len(findings),
        },
        "coverage": coverage,
        "edges": dsl.get("edges", []),
        **grouped,
        "findings": findings,
        "limitations": [
            "scan_success_does_not_mean_all_assets_verified",
            "prompt_text_omitted_by_default",
            "runtime_trace_does_not_override_dsl_configuration",
            *( ["mcp_provider_mapping_unverified"] if coverage["mcp_tools_list"] == "partial" else []),
            *( ["mcp_schema_change_requires_explicit_approved_schema_or_snapshot_comparison"] if grouped["mcp"] else []),
        ],
    }
