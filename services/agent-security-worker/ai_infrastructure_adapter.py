from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from aig_scan_common import ENGINE_COMMIT, ENGINE_TAG, artifact, bounded_text, run_upstream_task, usage_snapshot
from aig_service_client import AigServiceClient, AigServiceError


_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?)(?!\d)")
_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def _client() -> AigServiceClient:
    return AigServiceClient(os.environ.get("AIG_SERVICE_URL", ""), os.environ.get("AIG_SERVICE_TOKEN", ""))


def _fingerprint_parts(value: Any) -> tuple[str | None, str | None]:
    fingerprint = bounded_text(value, limit=512)
    if not fingerprint:
        return None, None
    match = _VERSION_PATTERN.search(fingerprint)
    version = match.group(1) if match else None
    component = fingerprint[: match.start()].rstrip(" @:/-_") if match else fingerprint
    return (component[:128] or None), version


def _severity(value: Any) -> str:
    normalized = str(value or "").lower()
    return normalized if normalized in _SEVERITIES else "medium"


def normalize_infrastructure_result(
    *, claim: dict[str, Any], raw_result: dict[str, Any], session_id: str, initial_usage: dict[str, int]
) -> dict[str, Any]:
    raw_entries = raw_result.get("results")
    if not isinstance(raw_entries, list):
        raise AigServiceError("agent_security.infra_result_invalid")
    by_endpoint: dict[str, dict[str, Any]] = {}
    for value in raw_entries:
        if not isinstance(value, dict):
            raise AigServiceError("agent_security.infra_result_invalid")
        endpoint = str(value.get("target_url") or "").strip()
        if endpoint:
            by_endpoint[endpoint.rstrip("/")] = value

    target = claim.get("target") or {}
    endpoints = (target.get("config") or {}).get("endpoints") or [target.get("endpoint_url")]
    cases: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    confirmed_vulnerabilities = 0
    for index, endpoint_value in enumerate(endpoints):
        endpoint = str(endpoint_value).strip()
        external_id = f"aig-infra-endpoint:{index + 1}"
        entry = by_endpoint.get(endpoint.rstrip("/"))
        if not entry:
            cases.append(
                {
                    "external_case_id": external_id,
                    "category": "ai_infrastructure_endpoint",
                    "title": endpoint[:512],
                    "status": "error",
                    "request_summary": {"endpoint": endpoint},
                    "response_summary": {
                        "execution_status": "error",
                        "assessment_status": "unverified",
                        "reason_code": "endpoint_result_missing",
                    },
                    "round_count": 0,
                }
            )
            continue

        fingerprint = bounded_text(entry.get("fingerprint"), limit=512)
        component, version = _fingerprint_parts(fingerprint)
        vulnerabilities = entry.get("vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise AigServiceError("agent_security.infra_result_invalid")
        mapped = 0
        for vuln_index, vulnerability in enumerate(vulnerabilities):
            if not isinstance(vulnerability, dict):
                raise AigServiceError("agent_security.infra_result_invalid")
            cve = bounded_text(vulnerability.get("cve"), limit=128)
            vuln_component = bounded_text(vulnerability.get("name"), limit=128) or component
            # AI-Infra-Guard emits a vulnerability only after its version rule
            # matches. We still require the observed fingerprint to expose a
            # concrete version before representing it as a confirmed Finding.
            if not cve or not vuln_component or not version:
                continue
            raw_references = vulnerability.get("references") or []
            if not isinstance(raw_references, list) or any(
                not isinstance(item, (str, int, float, bool)) for item in raw_references
            ):
                raise AigServiceError("agent_security.infra_result_invalid")
            mapped += 1
            confirmed_vulnerabilities += 1
            findings.append(
                {
                    "case_external_id": external_id,
                    "finding_code": cve,
                    "severity": _severity(vulnerability.get("severity")),
                    "status": "open",
                    "title": bounded_text(vulnerability.get("summary"), limit=512) or cve,
                    "description": bounded_text(vulnerability.get("details"), limit=8192)
                    or "AI-Infra-Guard matched a version-specific vulnerability rule.",
                    "evidence": {
                        "endpoint": endpoint,
                        "component": vuln_component,
                        "component_version": version,
                        "fingerprint": fingerprint,
                        "cve": cve,
                        "cvss": bounded_text(vulnerability.get("cvss"), limit=256),
                        "affected_version_match": True,
                        "rule_match_source": "ai-infra-guard-version-advisory",
                        "references": [bounded_text(item, limit=2048) for item in raw_references[:20]],
                        "engine_commit": ENGINE_COMMIT,
                    },
                    "source": "ai-infra-guard",
                    "confidence": 0.9,
                }
            )

        if mapped:
            status = "failed"
            assessment = "risk_signal_detected"
        elif not fingerprint or not version:
            status = "unverified"
            assessment = "unverified"
        else:
            status = "passed"
            assessment = "no_risk_observed"
        cases.append(
            {
                "external_case_id": external_id,
                "category": "ai_infrastructure_endpoint",
                "title": endpoint[:512],
                "status": status,
                "request_summary": {"endpoint": endpoint},
                "response_summary": {
                    "execution_status": "completed",
                    "assessment_status": assessment,
                    "component": component,
                    "component_version": version,
                    "fingerprint": fingerprint,
                    "reported_vulnerability_count": len(vulnerabilities),
                    "confirmed_finding_count": mapped,
                },
                "round_count": 1,
            }
        )

    raw_bytes = len(json.dumps(raw_result, ensure_ascii=False).encode("utf-8"))
    usage = usage_snapshot(
        initial_usage,
        rounds_delta=sum(item["round_count"] for item in cases),
        response_bytes_delta=raw_bytes,
        concurrency=int((claim.get("scan_options") or {}).get("scan_concurrency") or 1),
    )
    metadata = {
        "scan_mode": "explicit_url_fingerprint_and_cve",
        "planned_endpoints": len(endpoints),
        "executed_endpoints": sum(item["round_count"] for item in cases),
        "confirmed_vulnerabilities": confirmed_vulnerabilities,
        "unknown_or_unversioned_endpoints": sum(item["status"] == "unverified" for item in cases),
    }
    return {
        "status": "succeeded",
        "usage": usage,
        "cases": cases,
        "findings": findings,
        "artifacts": [
            artifact(
                task_id=claim["task"]["task_id"],
                artifact_type="aig-infrastructure-scan-report",
                raw_result=raw_result,
                metadata=metadata,
            )
        ],
        "session_state": session_id,
        "engine_name": "tencent-ai-infra-guard-infrastructure-scan",
        "engine_version": f"{ENGINE_TAG}+{ENGINE_COMMIT[:12]}",
    }


def execute_infrastructure_scan(
    claim: dict[str, Any],
    credential_secret: str | None,
    evaluator: Any,
    heartbeat: Callable[[dict[str, int], str | None], dict[str, Any]],
    *,
    initial_usage: dict[str, int],
    client: AigServiceClient | None = None,
) -> dict[str, Any]:
    target = claim.get("target") or {}
    config = target.get("config") or {}
    options = claim.get("scan_options") or {}
    endpoints = config.get("endpoints") or [target.get("endpoint_url")]
    if not endpoints or any(not endpoint for endpoint in endpoints):
        raise AigServiceError("agent_security.infra_target_required")
    headers = dict(config.get("headers") or {})
    if credential_secret:
        header = str(config.get("credential_header") or "Authorization")
        prefix = str(config.get("credential_prefix") or "Bearer ")
        headers[header] = prefix + credential_secret
    model = {
        "model": getattr(evaluator, "model", ""),
        "token": getattr(evaluator, "api_key", ""),
        "base_url": getattr(evaluator, "base_url", ""),
        "limit": int(options.get("scan_concurrency") or 1),
    }
    content = {
        "target": list(endpoints),
        "headers": headers,
        "timeout": int(options.get("scan_timeout_seconds") or int(config.get("timeout_ms", 30_000)) // 1000),
        "model": model,
        "network_policy": {
            "expected_ips": list(target.get("resolved_ips") or []),
            "allowed_cidrs": list(target.get("allowed_cidrs") or []),
            "policy_allowed_cidrs": list(target.get("policy_outbound_allowlist") or []),
            "allow_http": bool(options.get("http_authorized", False)),
        },
    }
    session_id, raw = run_upstream_task(
        claim=claim,
        client=client or _client(),
        task_type="ai_infra_scan",
        content=content,
        heartbeat=heartbeat,
        initial_usage=initial_usage,
    )
    return normalize_infrastructure_result(
        claim=claim,
        raw_result=raw,
        session_id=session_id,
        initial_usage=initial_usage,
    )
