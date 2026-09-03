from __future__ import annotations

import hashlib
import re
from typing import Any

from .redaction import redact_structure
from .schema import asset, collected_now, source, stable_hash


_VARIABLE = re.compile(r"\{\{#?([^{}#]+(?:\.[^{}#]+)*)#?\}\}")
_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{8,}"
)
_PROMPT_INJECTION = re.compile(
    r"(?i)(ignore|disregard|override).{0,40}(previous|system|developer).{0,30}(instruction|prompt)|"
    r"(?:忽略|无视|覆盖).{0,30}(?:系统|之前|以上).{0,20}(?:指令|提示词)"
)
_ROLE_CONFUSION = re.compile(r"(?i)(pretend|act as|you are now).{0,40}(admin|system|developer)|扮演.{0,20}(管理员|系统)")
_CAPABILITY_FINDINGS = {
    "sql_execution": ("dify_inventory.sql_execution_surface", "high", "Asset can submit SQL for execution"),
    "code_execution": ("dify_inventory.code_execution_surface", "high", "Asset can execute code"),
    "file_access": ("dify_inventory.file_access_surface", "medium", "Asset can access files"),
    "network_access": ("dify_inventory.network_access_surface", "medium", "Asset can access external networks"),
    "data_exfiltration_surface": ("dify_inventory.data_exfiltration_surface", "high", "Asset can send data externally"),
}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _prompt_values(node_id: str, node_type: str, data: dict[str, Any]) -> list[tuple[str, str, str]]:
    values: list[tuple[str, str, str]] = []
    for index, item in enumerate(_list(data.get("prompt_template"))):
        item = _dict(item)
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            values.append((str(item.get("role") or "unknown"), f"prompt_template[{index}]", text))
    parameters = _dict(data.get("agent_parameters"))
    instruction = parameters.get("instruction")
    if isinstance(instruction, dict):
        instruction = instruction.get("value")
    if isinstance(instruction, str) and instruction.strip():
        values.append(("system", "agent_parameters.instruction", instruction))
    for key in ("system_prompt", "user_prompt", "assistant_prompt", "instruction"):
        text = data.get(key)
        if isinstance(text, str) and text.strip():
            values.append((key.removesuffix("_prompt"), key, text))
    return values


def _capabilities(node_type: str, data: dict[str, Any], tool_name: str = "") -> list[str]:
    haystack = " ".join(
        str(value or "")
        for value in (node_type, data.get("provider_id"), data.get("provider_name"), tool_name, data.get("title"))
    ).lower()
    tags: set[str] = set()
    if node_type == "code" or any(value in haystack for value in ("python", "javascript", "code", "shell")):
        tags.add("code_execution")
    if "sql" in haystack or "database" in haystack:
        tags.add("sql_execution")
    if node_type == "http-request" or any(value in haystack for value in ("http", "web", "request", "mcp")):
        tags.add("network_access")
    if any(value in haystack for value in ("file", "document", "storage")):
        tags.add("file_access")
    if any(value in haystack for value in ("send", "upload", "export", "webhook", "email")):
        tags.add("data_exfiltration_surface")
    return sorted(tags)


def _dataset_ids(data: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("dataset_id", "dataset_ids"):
        value = data.get(key)
        values.extend(value if isinstance(value, list) else [value])
    for entry in _list(data.get("datasets")):
        entry = _dict(entry)
        values.extend((entry.get("id"), _dict(entry.get("dataset")).get("id")))
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _variable_descriptors(value: Any) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    if isinstance(value, dict):
        candidates = [
            {"name": key, **(item if isinstance(item, dict) else {})}
            for key, item in value.items()
        ]
    elif isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
    else:
        candidates = []
    for item in candidates[:128]:
        name = item.get("name") or item.get("variable") or item.get("label")
        if not isinstance(name, str) or not name.strip():
            continue
        variable_type = item.get("type") or item.get("value_type") or item.get("variable_type")
        descriptors.append({
            "name": name.strip()[:128],
            "type": str(variable_type)[:64] if variable_type not in (None, "") else None,
            "required": bool(item.get("required")) if "required" in item else None,
        })
    return descriptors


def _capability_findings(item: dict[str, Any], *, location: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for capability in item.get("details", {}).get("capabilities", []):
        rule = _CAPABILITY_FINDINGS.get(str(capability))
        if not rule:
            continue
        code, severity, title = rule
        findings.append({
            "asset_id": item["asset_id"], "finding_code": code, "severity": severity, "status": "open",
            "title": title,
            "description": "The configured asset exposes a security-sensitive capability. This is a static risk signal, not evidence that the capability was exploited.",
            "evidence": {
                "asset_id": item["asset_id"], "capability": capability, "location": location,
                "configured": True, "executed": False, "signal_only": True, "confirmed_vulnerability": False,
            },
            "source": "agent-manager-dify-inventory", "confidence": 0.75,
        })
    return findings


def collect_dsl(
    document: dict[str, Any],
    *,
    app_id: str,
    include_prompt_text: bool = False,
    collected_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("Dify DSL root must be an object")
    timestamp = collected_at or collected_now()
    app = _dict(document.get("app"))
    workflow = _dict(document.get("workflow"))
    graph = _dict(workflow.get("graph"))
    nodes: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    knowledge: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for raw in _list(graph.get("nodes")):
        raw = _dict(raw)
        data = _dict(raw.get("data"))
        node_id = str(raw.get("id") or "unknown")
        node_type = str(data.get("type") or raw.get("type") or "unknown")
        node_asset = asset(
            asset_id=f"node:{node_id}", asset_type="node", name=str(data.get("title") or node_id),
            configured=True, discovered=True, executed=False, verification_status="verified",
            sources=[source("dsl", f"workflow.graph.nodes[{node_id}]")],
            details={
                "node_id": node_id, "node_type": node_type,
                "capabilities": _capabilities(node_type, data),
                "control_flow": node_type if node_type in {"if-else", "iteration", "loop", "variable-aggregator"} else None,
                "model": redact_structure(_dict(data.get("model"))),
                "input_variables": _variable_descriptors(
                    data.get("input_variables") if data.get("input_variables") is not None else data.get("variables")
                ),
                "output_variables": _variable_descriptors(
                    data.get("output_variables") if data.get("output_variables") is not None else data.get("outputs")
                ),
            },
        )
        nodes.append(node_asset)
        if node_type in {"code", "http-request"}:
            findings.extend(_capability_findings(node_asset, location=f"workflow.graph.nodes[{node_id}]"))
        for role, location, text in _prompt_values(node_id, node_type, data):
            full_location = f"workflow.graph.nodes[{node_id}].data.{location}"
            prompt_id = f"prompt:{node_id}:{role}:{stable_hash(full_location)}"
            prompt = asset(
                asset_id=prompt_id, asset_type="prompt", name=f"{data.get('title') or node_id} · {role}",
                configured=True, discovered=True, executed=False, verification_status="verified",
                sources=[source("dsl", full_location)],
                details={
                    "node_id": node_id, "role": role, "location": full_location, "length": len(text),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "variable_references": sorted(set(_VARIABLE.findall(text))),
                },
                sensitive_content=text if include_prompt_text else None,
            )
            prompts.append(prompt)
            for code, severity, title, pattern in (
                ("dify_prompt_injection_instruction", "medium", "Prompt contains instruction-override patterns", _PROMPT_INJECTION),
                ("dify_prompt_hardcoded_secret", "high", "Prompt may contain a hard-coded secret", _SECRET),
                ("dify_prompt_role_confusion", "medium", "Prompt contains role-confusion patterns", _ROLE_CONFUSION),
            ):
                if pattern.search(text):
                    findings.append({
                        "asset_id": prompt_id, "finding_code": code, "severity": severity, "status": "open",
                        "title": title,
                        "description": "A static inventory rule observed a risk signal in configured Prompt text; this is not a confirmed exploit.",
                        "evidence": {"asset_id": prompt_id, "prompt_sha256": prompt["details"]["sha256"], "location": full_location, "signal_only": True},
                        "source": "agent-manager-dify-inventory", "confidence": 0.7,
                    })

        tool_records: list[dict[str, Any]] = []
        if node_type == "tool":
            tool_records.append(data)
        for entry in _list(_dict(_dict(data.get("agent_parameters")).get("tools")).get("value")):
            tool_records.append(_dict(entry))
        for entry in tool_records:
            provider_id = str(entry.get("provider_id") or data.get("provider_id") or "unknown")
            tool_name = str(entry.get("tool_name") or data.get("tool_name") or data.get("title") or "unknown")
            kind = "mcp" if "mcp" in f"{provider_id} {entry.get('provider_type', '')}".lower() else "tool"
            tool_asset = asset(
                asset_id=f"tool:{node_id}:{provider_id}:{tool_name}", asset_type=kind, name=tool_name,
                configured=True, discovered=kind != "mcp", executed=False,
                verification_status="unverified" if kind == "mcp" else "verified",
                sources=[source("dsl", f"workflow.graph.nodes[{node_id}].data")],
                details={
                    "node_id": node_id, "provider_id": provider_id,
                    "provider_name": entry.get("provider_name") or data.get("provider_name"),
                    "provider_type": entry.get("provider_type") or data.get("provider_type"),
                    "tool_name": tool_name,
                    "input_parameters": redact_structure(entry.get("tool_parameters") or data.get("tool_parameters") or {}),
                    "capabilities": _capabilities(node_type, data, tool_name),
                    "mcp_mapping_status": "unverified" if kind == "mcp" else None,
                },
            )
            tools.append(tool_asset)
            findings.extend(_capability_findings(tool_asset, location=f"workflow.graph.nodes[{node_id}].data"))
        for dataset_id in _dataset_ids(data):
            reference_hash = stable_hash(dataset_id)
            knowledge.append(asset(
                asset_id=f"knowledge:{reference_hash}:{node_id}", asset_type="knowledge", name=f"Knowledge reference {reference_hash[:8]}",
                configured=True, discovered=True, executed=False, verification_status="partially_verified",
                sources=[source("dsl", f"workflow.graph.nodes[{node_id}]")],
                details={
                    "node_id": node_id, "node_type": node_type, "dsl_reference": dataset_id,
                    "dataset_reference_status": "unmapped", "resolved_dataset_id": None,
                    "retrieval_mode": data.get("retrieval_mode"),
                    "top_k": data.get("top_k") or _dict(data.get("multiple_retrieval_config")).get("top_k"),
                    "score_threshold": data.get("score_threshold"),
                },
            ))

    edges = [
        {"source": str(edge.get("source")), "target": str(edge.get("target")), "id": edge.get("id")}
        for edge in _list(graph.get("edges")) if isinstance(edge, dict)
    ]
    return {
        "app": app,
        "workflow": {
            "workflow_id": workflow.get("id") or document.get("workflow_id"),
            "version": workflow.get("version") or document.get("version"),
            "dsl_version": document.get("version"),
            "published": workflow.get("published") or workflow.get("status"),
        },
        "nodes": nodes,
        "edges": edges,
        "prompts": prompts,
        "tools": tools,
        "knowledge_bases": knowledge,
        "findings": findings,
        "collected_at": timestamp,
    }
