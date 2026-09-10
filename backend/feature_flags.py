from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .api_errors import ApiError
from .config import settings

FEATURE_AGENT_SECURITY_SCANNING = "agent_security_scanning"
FEATURE_RUNTIME_TRACE = "runtime_trace"

ERROR_AGENT_SECURITY_FEATURE_DISABLED = "agent_security.feature_disabled"
ERROR_RUNTIME_TRACE_FEATURE_DISABLED = "runtime_trace.feature_disabled"
ERROR_BASELINE_UNAVAILABLE = "agent_security.baseline_unavailable"
ERROR_BASELINE_INVALID = "agent_security.baseline_invalid"

SCAN_TASK_STATUSES = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "blocked",
)
TRACE_COMPLETENESS_VALUES = (
    "full",
    "gateway_partial",
    "model_only",
    "mcp_only",
)
EXECUTION_MODES = (
    "passive",
    "read_only",
    "active_safe",
    "active_full",
)
TRACE_EVENT_SOURCES = (
    "agent_sdk",
    "model_gateway",
    "mcp_gateway",
    "runtime_governance",
    "knowledge_connector",
    "security_worker",
)
AGENT_SECURITY_AUDIT_EVENT_TYPES = (
    "security_target.created",
    "security_target.updated",
    "security_target.credential_rotated",
    "security_target.credential_revoked",
    "security_scan_policy.created",
    "security_scan_policy.updated",
    "security_scan_task.created",
    "security_scan_task.cancelled",
    "security_scan_task.completed",
    "security_scan_task.updated",
    "security_scan_task.recovered",
    "security_scan_report.exported",
    "security_scan_worker.created",
    "security_scan_worker.revoked",
    "security_scan_worker.key_registered",
    "security_finding.disposition_changed",
    "security_scan_artifact.raw_viewed",
    "runtime_trace.raw_payload_viewed",
    "runtime_trace.exported",
)

_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def feature_flags() -> dict[str, bool]:
    return {
        FEATURE_AGENT_SECURITY_SCANNING: bool(settings.AGENT_SECURITY_SCANNING_ENABLED),
        FEATURE_RUNTIME_TRACE: bool(settings.RUNTIME_TRACE_ENABLED),
    }


def _feature_disabled(feature_id: str) -> ApiError:
    if feature_id == FEATURE_RUNTIME_TRACE:
        return ApiError(
            status_code=404,
            code=ERROR_RUNTIME_TRACE_FEATURE_DISABLED,
            zh_message="统一调用轨迹功能未启用",
            en_message="Runtime trace is not enabled",
            params={"feature": feature_id},
        )
    return ApiError(
        status_code=404,
        code=ERROR_AGENT_SECURITY_FEATURE_DISABLED,
        zh_message="智能体安全扫描功能未启用",
        en_message="Agent security scanning is not enabled",
        params={"feature": feature_id},
    )


def require_agent_security_scanning() -> None:
    if not settings.AGENT_SECURITY_SCANNING_ENABLED:
        raise _feature_disabled(FEATURE_AGENT_SECURITY_SCANNING)


def require_runtime_trace() -> None:
    if not settings.RUNTIME_TRACE_ENABLED:
        raise _feature_disabled(FEATURE_RUNTIME_TRACE)


def _validate_integration(name: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"integration {name} must be an object")
    if not isinstance(value.get("repository"), str) or not value["repository"].startswith("https://github.com/"):
        raise ValueError(f"integration {name} has an invalid repository")
    if not isinstance(value.get("tag"), str) or not value["tag"]:
        raise ValueError(f"integration {name} has no locked tag")
    if not _COMMIT_PATTERN.fullmatch(str(value.get("commit", ""))):
        raise ValueError(f"integration {name} has no exact commit")
    license_info = value.get("license")
    if not isinstance(license_info, dict) or not license_info.get("spdx"):
        raise ValueError(f"integration {name} has no SPDX license")


def load_upstream_baseline(path: str | Path | None = None) -> dict[str, Any]:
    baseline_path = Path(path or settings.AGENT_SECURITY_UPSTREAM_LOCK_PATH)
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ApiError(
            status_code=503,
            code=ERROR_BASELINE_UNAVAILABLE,
            zh_message="智能体安全上游版本清单不存在",
            en_message="The Agent Security upstream lock is unavailable",
            params={"path": str(baseline_path)},
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(
            status_code=500,
            code=ERROR_BASELINE_INVALID,
            zh_message="智能体安全上游版本清单无法读取",
            en_message="The Agent Security upstream lock cannot be read",
            params={"path": str(baseline_path)},
        ) from exc

    try:
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported schema_version")
        policy = payload.get("policy")
        if not isinstance(policy, dict) or policy.get("runtime_source_fetch") is not False:
            raise ValueError("runtime_source_fetch must be false")
        integrations = payload.get("integrations")
        if not isinstance(integrations, dict):
            raise ValueError("integrations must be an object")
        for required in ("ai_infra_guard", "deepseek_harness"):
            _validate_integration(required, integrations.get(required))
        if integrations["deepseek_harness"].get("runtime_dependency") is not False:
            raise ValueError("DeepSeek Harness must remain reference-only")
    except ValueError as exc:
        raise ApiError(
            status_code=500,
            code=ERROR_BASELINE_INVALID,
            zh_message="智能体安全上游版本清单校验失败",
            en_message="The Agent Security upstream lock is invalid",
            params={"reason": str(exc)},
        ) from exc
    return payload


def baseline_summary(baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = baseline or load_upstream_baseline()
    integrations = payload["integrations"]
    return {
        "schema_version": payload["schema_version"],
        "locked_at": payload["locked_at"],
        "runtime_source_fetch": payload["policy"]["runtime_source_fetch"],
        "ai_infra_guard": {
            "tag": integrations["ai_infra_guard"]["tag"],
            "commit": integrations["ai_infra_guard"]["commit"],
            "license": integrations["ai_infra_guard"]["license"]["spdx"],
            "provider_types": integrations["ai_infra_guard"]["agent_scan"]["provider_types"],
        },
        "deepseek_harness": {
            "tag": integrations["deepseek_harness"]["tag"],
            "commit": integrations["deepseek_harness"]["commit"],
            "license": integrations["deepseek_harness"]["license"]["spdx"],
            "runtime_dependency": integrations["deepseek_harness"]["runtime_dependency"],
        },
    }
