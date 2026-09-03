from __future__ import annotations

import json
import os
from typing import Any, Callable

from aig_scan_common import (
    ENGINE_COMMIT,
    ENGINE_TAG,
    artifact,
    bounded_text,
    run_upstream_task,
    sha256_text,
    usage_snapshot,
)
from aig_service_client import AigServiceClient, AigServiceError


_RESULT_STATUSES = {"Safe", "Jailbreak", "Exception", "SimulationFailed"}


def _client() -> AigServiceClient:
    return AigServiceClient(
        os.environ.get("AIG_SERVICE_URL", ""),
        os.environ.get("AIG_SERVICE_TOKEN", ""),
    )


def _reports(raw: dict[str, Any]) -> list[dict[str, Any]]:
    content = raw.get("content")
    if isinstance(content, list):
        values = content
    elif isinstance(raw.get("results"), list):
        values = [raw]
    else:
        raise AigServiceError("agent_security.llm_result_invalid")
    if not values or any(not isinstance(value, dict) for value in values):
        raise AigServiceError("agent_security.llm_result_invalid")
    return values


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_llm_redteam_result(
    *, claim: dict[str, Any], raw_result: dict[str, Any], session_id: str, initial_usage: dict[str, int]
) -> dict[str, Any]:
    reports = _reports(raw_result)
    cases: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    target_tokens = 0
    evaluator_tokens = 0
    completed_evaluations = 0
    jailbreaks = 0
    case_index = 0

    for report in reports:
        results = report.get("results")
        if not isinstance(results, list):
            raise AigServiceError("agent_security.llm_result_invalid")
        usage = report.get("usage") if isinstance(report.get("usage"), dict) else {}
        target_tokens += _safe_int(usage.get("target_tokens"))
        evaluator_tokens += _safe_int(usage.get("evaluator_tokens"))
        for item in results:
            if not isinstance(item, dict) or item.get("status") not in _RESULT_STATUSES:
                raise AigServiceError("agent_security.llm_result_invalid")
            case_index += 1
            external_id = f"aig-llm-prompt:{case_index}"
            upstream_status = item["status"]
            if upstream_status == "Safe":
                case_status = "passed"
                assessment = "attack_resisted"
                completed_evaluations += 1
            elif upstream_status == "Jailbreak":
                case_status = "failed"
                assessment = "jailbreak_signal_detected"
                completed_evaluations += 1
                jailbreaks += 1
            elif upstream_status == "Exception":
                case_status = "error"
                assessment = "unverified"
            else:
                case_status = "unverified"
                assessment = "unverified"

            attack_method = bounded_text(item.get("attackMethod"), limit=128) or "unknown"
            vulnerability = bounded_text(item.get("vulnerability"), limit=256) or "unspecified"
            cases.append(
                {
                    "external_case_id": external_id,
                    "category": "llm_redteam_prompt",
                    "title": f"{attack_method}: {vulnerability}"[:512],
                    "status": case_status,
                    "request_summary": {
                        "attack_method": attack_method,
                        "vulnerability": vulnerability,
                        "prompt_sha256": sha256_text(item.get("input")),
                        "original_prompt_sha256": sha256_text(item.get("originalInput")),
                    },
                    "response_summary": {
                        "execution_status": "completed" if case_status in {"passed", "failed"} else case_status,
                        "assessment_status": assessment,
                        "response_sha256": sha256_text(item.get("output")),
                        "evaluator_reason": bounded_text(item.get("reason"), limit=1024),
                        "error_type": bounded_text(item.get("error"), limit=128) or None,
                    },
                    "round_count": 1 if case_status in {"passed", "failed"} else 0,
                }
            )
            if upstream_status == "Jailbreak":
                findings.append(
                    {
                        "case_external_id": external_id,
                        "finding_code": "llm_redteam.jailbreak_signal",
                        "severity": "high",
                        "status": "open",
                        "title": "LLM red-team jailbreak signal detected",
                        "description": "The evaluator observed a jailbreak signal for this executed attack prompt.",
                        "evidence": {
                            "attack_method": attack_method,
                            "vulnerability": vulnerability,
                            "prompt_sha256": sha256_text(item.get("input")),
                            "response_sha256": sha256_text(item.get("output")),
                            "engine_commit": ENGINE_COMMIT,
                        },
                        "source": "ai-infra-guard",
                        "confidence": 0.8,
                    }
                )

    if not cases:
        cases.append(
            {
                "external_case_id": "aig-llm-evidence-insufficient",
                "category": "llm_redteam_summary",
                "title": "LLM red-team execution evidence is insufficient",
                "status": "unverified",
                "request_summary": {},
                "response_summary": {"execution_status": "unverified", "assessment_status": "unverified"},
                "round_count": 0,
            }
        )

    raw_bytes = len(json.dumps(raw_result, ensure_ascii=False).encode("utf-8"))
    usage = usage_snapshot(
        initial_usage,
        rounds_delta=sum(item["round_count"] for item in cases),
        tokens_delta=target_tokens + evaluator_tokens,
        response_bytes_delta=raw_bytes,
        concurrency=int((claim.get("scan_options") or {}).get("scan_concurrency") or 1),
    )
    denominator = completed_evaluations
    metadata = {
        "scan_mode": "dynamic_model_redteam",
        "planned_cases": int((claim.get("scan_options") or {}).get("num_prompts") or len(cases)),
        "executed_cases": sum(item["round_count"] for item in cases),
        "completed_evaluations": completed_evaluations,
        "attack_resisted": completed_evaluations - jailbreaks,
        "jailbreak_signals": jailbreaks,
        "attack_success_rate": (jailbreaks / denominator) if denominator else None,
        "target_model_tokens": target_tokens,
        "evaluator_model_tokens": evaluator_tokens,
        "token_accounting": "reported_by_engine" if target_tokens or evaluator_tokens else "unavailable_from_upstream",
    }
    return {
        "status": "succeeded",
        "usage": usage,
        "cases": cases,
        "findings": findings,
        "artifacts": [
            artifact(
                task_id=claim["task"]["task_id"],
                artifact_type="aig-llm-redteam-report",
                raw_result=raw_result,
                metadata=metadata,
            )
        ],
        "session_state": session_id,
        "engine_name": "tencent-ai-infra-guard-model-redteam",
        "engine_version": f"{ENGINE_TAG}+{ENGINE_COMMIT[:12]}",
    }


def execute_llm_redteam_scan(
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
    if not target.get("endpoint_url") or not config.get("model"):
        raise AigServiceError("agent_security.llm_target_required")
    if not getattr(evaluator, "api_key", "") or not getattr(evaluator, "model", ""):
        raise AigServiceError("agent_security.llm_evaluator_unavailable", retryable=True)
    content = {
        "model": [
            {
                "base_url": target["endpoint_url"],
                "token": credential_secret or "",
                "model": config["model"],
                "limit": int(options.get("scan_concurrency") or 1),
            }
        ],
        "eval_model": {
            "base_url": evaluator.base_url,
            "token": evaluator.api_key,
            "model": options.get("evaluation_model") or evaluator.model,
            "limit": 1,
        },
        "dataset": {
            "dataFile": list(options.get("datasets") or []),
            "numPrompts": int(options.get("num_prompts") or 10),
            "randomSeed": int(options.get("random_seed") or 42),
            "promptColumn": "prompt",
        },
        "prompt": str(options.get("prompt") or ""),
        "techniques": list(options.get("techniques") or ["Raw"]),
    }
    session_id, raw = run_upstream_task(
        claim=claim,
        client=client or _client(),
        task_type="model_redteam_report",
        content=content,
        heartbeat=heartbeat,
        initial_usage=initial_usage,
    )
    return normalize_llm_redteam_result(
        claim=claim,
        raw_result=raw,
        session_id=session_id,
        initial_usage=initial_usage,
    )
