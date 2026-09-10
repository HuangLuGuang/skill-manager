from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable

import yaml

from agent_manager.core.dify_console_client import (
    DifyConsoleClient,
    DifyConsoleClientConfig,
    DifyConsoleError,
)
from agent_manager.core.dify_inventory import (
    apply_intent_inference,
    build_intent_inference_summary,
    build_inventory,
    collect_dsl,
)
from agent_manager.core.dify_inventory.redaction import redact_structure


ENGINE_NAME = "agent-manager-dify-inventory"
ENGINE_VERSION = "1"
MAX_DSL_BYTES = 10 * 1024 * 1024


def _uuid_text(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError):
        return None


def _knowledge_resolution_key(node_id: Any, reference: Any) -> str:
    return f"{str(node_id or '')}\x00{str(reference or '')}"


def _knowledge_reference_resolution(
    reference: str,
    bindings: list[dict[str, Any]],
    draft_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    direct = _uuid_text(reference)
    if direct:
        candidates[direct] = {
            "source_type": "dsl",
            "source_identifier": "workflow.graph.nodes.data.dataset_ids",
            "limitations": [],
        }
    normalized_draft = [
        normalized for value in (draft_candidate or {}).get("dataset_ids", [])
        if (normalized := _uuid_text(value))
    ]
    for dataset_id in normalized_draft:
        candidates.setdefault(dataset_id, {
            "source_type": "dify_console_draft_workflow",
            "source_identifier": (draft_candidate or {}).get("source_identifier"),
            "limitations": ["draft_may_differ_from_published_workflow"],
        })
    for binding in bindings:
        if isinstance(binding, dict) and str(binding.get("dsl_reference") or "") == reference:
            dataset_id = _uuid_text(binding.get("dataset_id"))
            if dataset_id:
                candidates.setdefault(dataset_id, {
                    "source_type": "target_config",
                    "source_identifier": "target.config.knowledge_bindings",
                    "limitations": [],
                })
    if len(candidates) == 1:
        dataset_id, evidence = next(iter(candidates.items()))
        return {
            "status": "resolved", "dataset_id": dataset_id, "error_code": None,
            **evidence,
        }
    if len(candidates) > 1:
        return {
            "status": "ambiguous", "dataset_id": None,
            "error_code": "dify_inventory.dataset_reference_ambiguous",
        }
    return {
        "status": "unmapped", "dataset_id": None,
        "error_code": "dify_inventory.dataset_reference_unmapped",
    }


def _node_dataset_values(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    values: list[Any] = []
    for key in ("dataset_id", "dataset_ids"):
        value = data.get(key)
        values.extend(value if isinstance(value, list) else [value])
    datasets = data.get("datasets")
    if isinstance(datasets, list):
        for item in datasets:
            if isinstance(item, dict):
                nested = item.get("dataset") if isinstance(item.get("dataset"), dict) else {}
                values.extend((item.get("id"), nested.get("id")))
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _draft_knowledge_candidates(
    knowledge_assets: list[dict[str, Any]], draft_workflow: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    graph = draft_workflow.get("graph") if isinstance(draft_workflow, dict) else None
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        return {}
    official_by_node: dict[str, list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if str(data.get("type") or "").replace("_", "-").lower() != "knowledge-retrieval":
            continue
        dataset_ids = [normalized for value in _node_dataset_values(data) if (normalized := _uuid_text(value))]
        if node_id and dataset_ids:
            official_by_node[node_id] = dataset_ids

    references_by_node: dict[str, list[str]] = {}
    for item in knowledge_assets:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        node_id = str(details.get("node_id") or "")
        reference = str(details.get("dsl_reference") or "")
        node_type = str(details.get("node_type") or "").replace("_", "-").lower()
        if node_id and reference and node_type == "knowledge-retrieval":
            references_by_node.setdefault(node_id, []).append(reference)

    candidates: dict[str, dict[str, Any]] = {}
    for node_id, references in references_by_node.items():
        official = official_by_node.get(node_id, [])
        if len(references) == 1 and official:
            candidates[_knowledge_resolution_key(node_id, references[0])] = {
                "dataset_ids": list(official),
                "source_identifier": f"workflow.graph.nodes[{node_id}].data.dataset_ids",
            }
        elif official:
            for reference in references:
                candidates[_knowledge_resolution_key(node_id, reference)] = {
                    "dataset_ids": list(official),
                    "source_identifier": f"workflow.graph.nodes[{node_id}].data.dataset_ids",
                }
    return candidates


def _case(key: str, status: str, *, source: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "external_case_id": f"dify-inventory:{key}",
        "category": "asset_inventory" if key != "asset_risk_analysis" else "risk_analysis",
        "title": key.replace("_", " "),
        "status": status,
        "request_summary": {"source": source, "read_only": True},
        "response_summary": {"reason": reason} if reason else {},
        "round_count": 1 if status in {"passed", "failed"} else 0,
    }


def _client(target: dict[str, Any], secret: str) -> DifyConsoleClient:
    config = target.get("config") if isinstance(target.get("config"), dict) else {}
    timeout = max(1.0, float(config.get("timeout_ms", 30_000)) / 1000.0)
    return DifyConsoleClient(DifyConsoleClientConfig(
        base_url=str(config["console_base_url"]), workspace_id=str(config["workspace_id"]),
        app_id=str(config["app_id"]), admin_api_key=secret,
        connect_timeout_seconds=min(timeout, 10.0), read_timeout_seconds=timeout,
        max_response_bytes=MAX_DSL_BYTES, max_retries=2,
        allow_insecure_transport=bool(target.get("allow_insecure_transport", False)),
        allowed_cidrs=tuple(target.get("allowed_cidrs") or ()),
        allowed_redirect_hosts=tuple(config.get("allowed_redirect_hosts") or ()),
        expected_ips=tuple(config.get("console_resolved_ips") or ()),
    ))


def _manual_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > MAX_DSL_BYTES:
        raise DifyConsoleError("dify_inventory.dsl_invalid")
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise DifyConsoleError("dify_inventory.dsl_invalid") from exc
    if not isinstance(parsed, dict):
        raise DifyConsoleError("dify_inventory.dsl_invalid")
    return parsed


def execute_dify_inventory(
    claim: dict[str, Any], credential_secrets: dict[str, str],
    heartbeat: Callable[[dict[str, int]], dict[str, Any]], *, initial_usage: dict[str, int] | None = None,
    infer_intent: Callable[[dict[str, Any], dict[str, int]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target = claim.get("target") or {}
    options = claim.get("scan_options") or {}
    config = target.get("config") if isinstance(target.get("config"), dict) else {}
    usage = dict(initial_usage or {"rounds": 0, "tokens": 0, "cost_microunits": 0, "concurrent_requests": 0, "response_bytes": 0})
    usage["concurrent_requests"] = max(usage.get("concurrent_requests", 0), 1)
    cases: list[dict[str, Any]] = []
    app_detail: dict[str, Any] | None = None
    draft_workflow: dict[str, Any] | None = None
    draft_workflow_error: str | None = None
    knowledge_details: dict[str, dict[str, Any]] = {}
    knowledge_findings: list[dict[str, Any]] = []
    knowledge_errors: list[str] = []
    knowledge_resolution: dict[str, dict[str, Any]] = {}

    def check() -> None:
        response = heartbeat(usage)
        if not response.get("continue_allowed", False):
            from aig_adapter import ScanStopped
            raise ScanStopped(str(response.get("stop_reason") or "scan_stopped"))

    check()
    if options.get("inventory_source", "console_api") == "manual_dsl":
        document = _manual_document(options.get("manual_dsl"))
        cases.append(_case("dify_console_api", "unverified", source="manual_dsl", reason="manual_fallback_used"))
        usage["rounds"] += 1
    else:
        console_secret = credential_secrets.get("dify_console_api")
        if not console_secret:
            raise DifyConsoleError("dify_inventory.console_auth_failed")
        client = _client(target, console_secret)
        try:
            app_detail = client.get_app_detail(config.get("app_id"))
            cases.append(_case("dify_console_api", "passed", source="dify_console_api"))
            usage["rounds"] += 1
            usage["response_bytes"] += len(json.dumps(app_detail, ensure_ascii=False).encode("utf-8"))
        except DifyConsoleError as exc:
            if exc.code not in {"dify_inventory.app_not_found", "dify_inventory.response_invalid"}:
                raise
            cases.append(_case("dify_console_api", "error", source="dify_console_api", reason=exc.code))
        check()
        document = client.export_dsl(config.get("app_id"), config.get("workflow_id"))
        usage["rounds"] += 1
        usage["response_bytes"] += len(json.dumps(document, ensure_ascii=False).encode("utf-8"))
        check()
        try:
            draft_workflow = client.get_draft_workflow(config.get("app_id"))
            usage["rounds"] += 1
            usage["response_bytes"] += len(json.dumps(draft_workflow, ensure_ascii=False).encode("utf-8"))
        except DifyConsoleError as exc:
            draft_workflow_error = exc.code
            draft_workflow = None
        check()

    dsl = collect_dsl(
        document, app_id=str(config.get("app_id") or ""),
        include_prompt_text=bool(options.get("include_prompt_text", False)),
    )
    inference_summary: dict[str, Any] | None = None
    if options.get("infer_agent_intent"):
        inference_dsl = collect_dsl(
            document,
            app_id=str(config.get("app_id") or ""),
            include_prompt_text=True,
            collected_at=str(dsl["collected_at"]),
        )
        try:
            inference_summary = build_intent_inference_summary(inference_dsl)
        finally:
            inference_dsl.clear()
    cases.append(_case("dsl", "passed", source="dsl"))
    check()

    knowledge_items = list(dsl.get("knowledge_bases", []))
    knowledge_assets = []
    for item in knowledge_items:
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        reference = str(details.get("dsl_reference") or "")
        if reference:
            knowledge_assets.append((
                _knowledge_resolution_key(details.get("node_id"), reference), reference,
            ))
    draft_candidates = _draft_knowledge_candidates(knowledge_items, draft_workflow)
    bindings = list(config.get("knowledge_bindings") or [])
    for resolution_key, reference in knowledge_assets:
        knowledge_resolution[resolution_key] = _knowledge_reference_resolution(
            reference, bindings, draft_candidates.get(resolution_key),
        )
        if draft_workflow_error and knowledge_resolution[resolution_key]["status"] in {"unmapped", "ambiguous"}:
            knowledge_resolution[resolution_key]["mapping_context_error_code"] = draft_workflow_error

    knowledge_secret = credential_secrets.get("dify_knowledge_api")
    knowledge_api_accessible = False
    if knowledge_secret:
        knowledge_client = _client(target, knowledge_secret)
        unresolved = [
            resolution_key for resolution_key, resolution in knowledge_resolution.items()
            if resolution["status"] in {"unmapped", "ambiguous"}
        ]
        if unresolved:
            try:
                datasets = knowledge_client.list_datasets(limit=1)
                knowledge_api_accessible = True
                usage["rounds"] += 1
                usage["response_bytes"] += len(json.dumps(datasets, ensure_ascii=False).encode("utf-8"))
                check()
            except DifyConsoleError as exc:
                knowledge_errors.append(exc.code)
                for resolution_key in unresolved:
                    knowledge_resolution[resolution_key] = {
                        "status": "unavailable", "dataset_id": None, "error_code": exc.code,
                    }
        for knowledge in dsl.get("knowledge_bases", []):
            details = knowledge.get("details") if isinstance(knowledge.get("details"), dict) else {}
            reference = str(details.get("dsl_reference") or "")
            resolution_key = _knowledge_resolution_key(details.get("node_id"), reference)
            resolution = knowledge_resolution.get(resolution_key, {})
            dataset_id = str(resolution.get("dataset_id") or "")
            if not dataset_id or dataset_id in knowledge_details:
                continue
            knowledge["asset_id"] = f"knowledge:{dataset_id}:{str(details.get('node_id') or 'unknown')}"
            try:
                detail = knowledge_client.get_dataset_detail(dataset_id)
                knowledge_api_accessible = True
                record = {
                    "name": detail.get("name"), "document_count": detail.get("document_count"),
                    "segment_count": detail.get("segment_count"), "indexing_status": detail.get("indexing_status"),
                }
                if options.get("knowledge_content_authorized"):
                    document_limit = int(options.get("max_knowledge_documents", 100))
                    documents = knowledge_client.list_dataset_documents(dataset_id, limit=document_limit)
                    segment_limit = int(options.get("max_knowledge_segments", 1000))
                    byte_limit = int(options.get("max_knowledge_bytes", 10 * 1024 * 1024))
                    segments_seen = 0
                    bytes_seen = 0
                    document_records = []
                    for document_item in documents:
                        document_id = str(document_item.get("id") or "")
                        document_record = {
                            "id": document_id or None, "name": document_item.get("name"),
                            "status": document_item.get("indexing_status") or document_item.get("status"),
                            "segment_count": document_item.get("segment_count"),
                        }
                        segment_records = []
                        if document_id and segments_seen < segment_limit and bytes_seen < byte_limit:
                            segments = knowledge_client.list_document_segments(
                                dataset_id, document_id, limit=segment_limit - segments_seen
                            )
                            for segment in segments:
                                content = str(segment.get("content") or "")
                                content_size = len(content.encode("utf-8"))
                                if bytes_seen + content_size > byte_limit:
                                    break
                                bytes_seen += content_size
                                segments_seen += 1
                                segment_records.append({
                                    "id": segment.get("id"),
                                    "status": segment.get("status") or segment.get("indexing_status"),
                                    "content_bytes": content_size,
                                    "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                                    "metadata": redact_structure(segment.get("keywords") or segment.get("metadata") or {}),
                                })
                                lowered = content.lower()
                                if any(marker in lowered for marker in ("ignore previous instructions", "忽略之前的指令", "忽略以上指令")):
                                    knowledge_findings.append({
                                        "finding_code": "dify_inventory.knowledge_poisoning_signal",
                                        "severity": "medium", "status": "open",
                                        "title": "Knowledge segment contains an instruction-override signal",
                                        "description": "Authorized knowledge inspection observed a potential instruction-override pattern. This is a risk signal requiring review, not a confirmed exploit.",
                                        "evidence": {
                                            "dataset_id": dataset_id, "document_id": document_id,
                                            "segment_id": segment.get("id"), "content_sha256": segment_records[-1]["content_sha256"],
                                        },
                                        "source": "dify_knowledge_api", "confidence": 0.7,
                                        "asset_id": knowledge.get("asset_id"),
                                    })
                            if segment_records:
                                document_record["segments"] = segment_records
                        document_records.append(document_record)
                    record["documents"] = document_records
                    record["content_scan"] = {
                        "authorized": True,
                        "documents_scanned": len(document_records),
                        "segments_scanned": segments_seen,
                        "bytes_scanned": bytes_seen,
                        "document_limit": document_limit,
                        "segment_limit": segment_limit,
                        "byte_limit": byte_limit,
                    }
                knowledge_details[dataset_id] = record
                usage["rounds"] += 1
                usage["response_bytes"] += len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                check()
            except DifyConsoleError as exc:
                knowledge_errors.append(exc.code)
                if exc.code == "dify_inventory.dataset_not_found":
                    knowledge_api_accessible = True
                knowledge_resolution[resolution_key].update({"error_code": exc.code})
        mapping_codes = [
            resolution["error_code"] for resolution in knowledge_resolution.values()
            if resolution.get("status") in {"unmapped", "ambiguous"} and resolution.get("error_code")
        ]
        if mapping_codes and not knowledge_errors:
            knowledge_status, knowledge_reason = "unverified", mapping_codes[0]
        elif knowledge_errors:
            knowledge_reason = knowledge_errors[0]
            knowledge_status = (
                "unverified"
                if set(knowledge_errors) <= {"dify_inventory.dataset_not_found"}
                else "error"
            )
        elif knowledge_details:
            knowledge_status, knowledge_reason = "passed", None
        else:
            knowledge_status, knowledge_reason = "unverified", "no_dataset_metadata_collected"
        cases.append(_case("dify_knowledge_api", knowledge_status, source="dify_knowledge_api", reason=knowledge_reason))
    else:
        cases.append(_case("dify_knowledge_api", "unverified", source="dify_knowledge_api", reason="credential_not_configured"))

    if draft_workflow is not None:
        draft_workflow.clear()

    inventory = build_inventory(
        dsl, target=target, app_detail=app_detail, knowledge_details=knowledge_details,
        mcp_servers=target.get("dify_mcp_servers") or [],
        runtime_events=target.get("dify_runtime_events") or [],
        collection_source="manual_dsl" if options.get("inventory_source") == "manual_dsl" else "dify_console_api",
        knowledge_resolution=knowledge_resolution,
    )
    if options.get("infer_agent_intent"):
        inference: dict[str, Any]
        if infer_intent is None or inference_summary is None:
            inference = {
                "status": "unavailable",
                "error_code": "dify_inventory.intent_inference_unavailable",
            }
        else:
            inference = infer_intent(inference_summary, dict(usage))
        returned_usage = inference.get("usage") if isinstance(inference.get("usage"), dict) else {}
        for key in usage:
            usage[key] = max(usage[key], max(0, int(returned_usage.get(key) or 0)))
        if not inference.get("continue_allowed", True):
            from aig_adapter import ScanStopped
            raise ScanStopped(str(inference.get("stop_reason") or "scan_stopped"))
        try:
            inventory["agent_profile"] = apply_intent_inference(
                inventory["agent_profile"],
                inference,
                collected_at=str(inference.get("collected_at") or dsl["collected_at"]),
            )
        except (TypeError, ValueError):
            inference = {
                "status": "unavailable",
                "error_code": "dify_inventory.intent_output_invalid",
                "diagnostic_code": "unexpected_fields",
                "model": inference.get("model"),
                "provider": inference.get("provider"),
            }
            inventory["agent_profile"] = apply_intent_inference(
                inventory["agent_profile"], inference, collected_at=str(dsl["collected_at"]),
            )
        inference_status = "passed" if inference.get("status") == "inferred" else "unverified"
        inference_error = inference.get("error_code")
        cases.append(_case(
            "intent_inference", inference_status, source="system_inference", reason=inference_error,
        ))
        inventory["coverage"]["intent_inference"] = (
            "completed" if inference.get("status") == "inferred" else "unavailable"
        )
        if inference_error:
            inventory["limitations"].append(inference_error)
        inference_summary.clear()
    unresolved_knowledge = any(
        resolution.get("status") in {"unmapped", "ambiguous"} or resolution.get("error_code")
        for resolution in knowledge_resolution.values()
    )
    if unresolved_knowledge:
        inventory["coverage"]["dify_knowledge_api"] = (
            "partial" if knowledge_secret and knowledge_api_accessible else "unavailable"
        )
        for resolution in knowledge_resolution.values():
            if resolution.get("error_code") and resolution["error_code"] not in inventory["limitations"]:
                inventory["limitations"].append(resolution["error_code"])
    if knowledge_errors:
        inventory["coverage"]["dify_knowledge_api"] = (
            "partial" if knowledge_details or knowledge_api_accessible else "unavailable"
        )
        inventory["limitations"].append("dify_knowledge_api_collection_incomplete")
    if draft_workflow_error and draft_workflow_error not in inventory["limitations"]:
        inventory["limitations"].append(draft_workflow_error)
    if any(
        resolution.get("source_type") == "dify_console_draft_workflow"
        for resolution in knowledge_resolution.values()
    ):
        inventory["limitations"].append("draft_may_differ_from_published_workflow")
    mcp_coverage = inventory["coverage"]["mcp_tools_list"]
    runtime_coverage = inventory["coverage"]["runtime_trace"]
    cases.append(_case("mcp_tools_list", "passed" if mcp_coverage == "completed" else "unverified", source="mcp_tools_list", reason=mcp_coverage))
    cases.append(_case("runtime_trace", "passed" if runtime_coverage in {"completed", "partial"} else "unverified", source="runtime_trace", reason=runtime_coverage))
    findings = [*inventory.pop("findings", []), *knowledge_findings]
    inventory["summary"]["findings"] = len(findings)
    for finding in findings:
        finding["case_external_id"] = "dify-inventory:asset_risk_analysis"
    cases.append(_case("asset_risk_analysis", "failed" if findings else "passed", source="agent-manager-dify-inventory"))
    content = json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = content.encode("utf-8")
    usage["response_bytes"] += len(encoded)
    check()
    return {
        "status": "succeeded", "usage": usage, "cases": cases, "findings": findings,
        "artifacts": [{
            "artifact_type": "dify-asset-inventory", "uri": f"artifact://{claim['task']['task_id']}/dify-asset-inventory.json",
            "sha256": hashlib.sha256(encoded).hexdigest(), "size_bytes": len(encoded), "redacted": not bool(options.get("include_prompt_text")),
            "metadata": {
                "schema_version": "dify-asset-inventory@1", "engine_name": ENGINE_NAME,
                "summary": inventory["summary"], "coverage": inventory["coverage"],
                "prompt_text_included": bool(options.get("include_prompt_text")),
                "intent_inference_enabled": bool(options.get("infer_agent_intent")),
            },
            "content": content,
        }],
        "engine_name": ENGINE_NAME, "engine_version": ENGINE_VERSION,
    }
