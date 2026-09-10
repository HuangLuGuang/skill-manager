"""Read-only inventory extraction from an exported Dify application DSL."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from .dify_inventory.dsl_collector import collect_dsl as collect_inventory_dsl


MAX_DSL_BYTES = 10 * 1024 * 1024


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _prompt_record(
    text: Any,
    *,
    location: str,
    role: str,
    node_id: str | None,
    node_type: str | None,
    include_prompt_text: bool,
) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text.strip():
        return None
    record: dict[str, Any] = {
        "location": location,
        "node_id": node_id,
        "node_type": node_type,
        "role": role,
        "length": len(text),
        "sha256": _sha256_text(text),
    }
    if include_prompt_text:
        record["text"] = text
    return record


def _node_prompts(node_id: str, node_type: str, data: dict[str, Any], include_prompt_text: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, template in enumerate(_as_list(data.get("prompt_template"))):
        template = _as_dict(template)
        record = _prompt_record(
            template.get("text"),
            location=f"workflow.graph.nodes[{node_id}].data.prompt_template[{index}]",
            role=str(template.get("role") or "unknown"),
            node_id=node_id,
            node_type=node_type,
            include_prompt_text=include_prompt_text,
        )
        if record:
            records.append(record)

    agent_parameters = _as_dict(data.get("agent_parameters"))
    instruction = agent_parameters.get("instruction")
    if isinstance(instruction, dict):
        instruction = instruction.get("value")
    record = _prompt_record(
        instruction,
        location=f"workflow.graph.nodes[{node_id}].data.agent_parameters.instruction",
        role="system",
        node_id=node_id,
        node_type=node_type,
        include_prompt_text=include_prompt_text,
    )
    if record:
        records.append(record)
    return records


def _node_tools(node_id: str, node_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    if node_type == "tool":
        tools.append(
            {
                "node_id": node_id,
                "source": "tool_node",
                "provider_id": data.get("provider_id"),
                "provider_name": data.get("provider_name"),
                "provider_type": data.get("provider_type"),
                "tool_name": data.get("tool_name"),
                "tool_label": data.get("tool_label"),
            }
        )

    agent_tools = _as_dict(_as_dict(data.get("agent_parameters")).get("tools")).get("value")
    for tool in _as_list(agent_tools):
        tool = _as_dict(tool)
        tools.append(
            {
                "node_id": node_id,
                "source": "agent_node",
                "provider_id": tool.get("provider_id"),
                "provider_name": tool.get("provider_name"),
                "provider_type": tool.get("provider_type"),
                "tool_name": tool.get("tool_name"),
                "tool_label": tool.get("tool_label"),
                "enabled": tool.get("enabled"),
            }
        )
    return tools


def _dataset_ids(data: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("dataset_id", "dataset_ids"):
        value = data.get(key)
        values.extend(value if isinstance(value, list) else [value])
    datasets = data.get("datasets")
    if isinstance(datasets, list):
        for dataset in datasets:
            dataset = _as_dict(dataset)
            values.extend([dataset.get("id"), _as_dict(dataset.get("dataset")).get("id")])
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _profile_field(value: Any, *, source: str | None, missing_reason: str | None = None) -> dict[str, Any]:
    collected = value not in (None, "", [])
    return {
        "value": value if collected else None,
        "status": "collected" if collected else "unavailable",
        "source": source if collected else None,
        "missing_reason": None if collected else missing_reason,
    }


def _agent_profile(app: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    explicit_intent = app.get("intent") or _as_dict(document.get("metadata")).get("intent")
    return {
        "name": _profile_field(app.get("name"), source="dsl.app.name", missing_reason="not_present_in_dsl"),
        "created_at": _profile_field(
            app.get("created_at"),
            source="dsl.app.created_at",
            missing_reason="not_exposed_by_dsl_or_public_app_info_api",
        ),
        "description": _profile_field(
            app.get("description"), source="dsl.app.description", missing_reason="not_declared_in_dsl"
        ),
        "mode": _profile_field(app.get("mode"), source="dsl.app.mode", missing_reason="not_present_in_dsl"),
        "author_name": _profile_field(
            app.get("author_name"),
            source="dsl.app.author_name",
            missing_reason="available_from_get_info_api_not_dsl",
        ),
        "tags": _profile_field(app.get("tags"), source="dsl.app.tags", missing_reason="available_from_get_info_api_not_dsl"),
        "intent": {
            "value": explicit_intent if explicit_intent not in (None, "") else None,
            "status": "declared" if explicit_intent not in (None, "") else "unverified",
            "source": "dsl.app.intent" if app.get("intent") else ("dsl.metadata.intent" if explicit_intent else None),
            "confidence": "authoritative" if explicit_intent else None,
            "evidence": [],
            "missing_reason": None if explicit_intent else "dify_has_no_standard_declared_intent_field",
        },
    }


def collect_dify_dsl(document: dict[str, Any], *, include_prompt_text: bool = False) -> dict[str, Any]:
    """Return a secret-minimized inventory from a parsed Dify DSL document."""
    if not isinstance(document, dict):
        raise ValueError("Dify DSL root must be an object")

    app = _as_dict(document.get("app"))
    workflow = _as_dict(document.get("workflow"))
    graph = _as_dict(workflow.get("graph"))
    raw_nodes = _as_list(graph.get("nodes"))
    nodes: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    knowledge_bases: list[dict[str, Any]] = []

    for raw_node in raw_nodes:
        raw_node = _as_dict(raw_node)
        data = _as_dict(raw_node.get("data"))
        node_id = str(raw_node.get("id") or "unknown")
        node_type = str(data.get("type") or "unknown")
        nodes.append({"node_id": node_id, "type": node_type, "title": data.get("title")})
        prompts.extend(_node_prompts(node_id, node_type, data, include_prompt_text))
        tools.extend(_node_tools(node_id, node_type, data))
        for dataset_id in _dataset_ids(data):
            knowledge_bases.append(
                {
                    "node_id": node_id,
                    "source": "workflow_node",
                    "dataset_id": dataset_id,
                    "retrieval_mode": data.get("retrieval_mode"),
                }
            )

    model_config = _as_dict(document.get("model_config"))
    legacy_prompt = _prompt_record(
        model_config.get("pre_prompt"),
        location="model_config.pre_prompt",
        role="system",
        node_id=None,
        node_type="legacy_model_config",
        include_prompt_text=include_prompt_text,
    )
    if legacy_prompt:
        prompts.append(legacy_prompt)

    legacy_dataset_config = _as_dict(model_config.get("dataset_configs"))
    for dataset_id in _dataset_ids(legacy_dataset_config):
        knowledge_bases.append(
            {"node_id": None, "source": "legacy_model_config", "dataset_id": dataset_id, "retrieval_mode": None}
        )

    unique_knowledge: list[dict[str, Any]] = []
    seen_knowledge: set[tuple[Any, Any]] = set()
    for item in knowledge_bases:
        key = (item["node_id"], item["dataset_id"])
        if key not in seen_knowledge:
            seen_knowledge.add(key)
            unique_knowledge.append(item)

    return {
        "schema_version": "dify-control-plane-inventory@1",
        "agent_profile": _agent_profile(app, document),
        "app": {
            "name": app.get("name"),
            "mode": app.get("mode"),
            "description": app.get("description"),
            "dsl_version": document.get("version"),
        },
        "summary": {
            "nodes": len(nodes),
            "prompts": len(prompts),
            "tools": len(tools),
            "knowledge_bases": len(unique_knowledge),
        },
        "nodes": nodes,
        "prompts": prompts,
        "tools": tools,
        "knowledge_bases": unique_knowledge,
        "collection_semantics": "configured_not_runtime_verified",
        "prompt_text_included": include_prompt_text,
        "limitations": [
            "exported_dsl_only",
            "knowledge_document_content_not_collected",
            "tool_implementation_not_collected",
            "runtime_execution_not_verified",
        ],
    }


def collect_dify_asset_inventory_dsl(
    document: dict[str, Any], *, app_id: str, include_prompt_text: bool = False
) -> dict[str, Any]:
    """Compatibility entrypoint for the evidence-aware inventory collector."""
    return collect_inventory_dsl(document, app_id=app_id, include_prompt_text=include_prompt_text)


def collect_dify_dsl_file(path: str | Path, *, include_prompt_text: bool = False) -> dict[str, Any]:
    source = Path(path)
    if source.stat().st_size > MAX_DSL_BYTES:
        raise ValueError(f"Dify DSL exceeds {MAX_DSL_BYTES} bytes")
    raw = source.read_bytes()
    document = yaml.safe_load(raw) or {}
    result = collect_dify_dsl(document, include_prompt_text=include_prompt_text)
    result["source"] = {"filename": source.name, "sha256": hashlib.sha256(raw).hexdigest()}
    return result
