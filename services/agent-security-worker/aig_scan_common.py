from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from aig_service_client import AIG_FAILURE_MESSAGES, AigServiceClient, AigServiceError, TERMINAL_STATUSES


ENGINE_TAG = "v4.6.0"
ENGINE_COMMIT = "e8931cc68001b66ad024fd87ef07394e9e96524a"


class AigScanStopped(RuntimeError):
    pass


def artifact(
    *,
    task_id: str,
    artifact_type: str,
    raw_result: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    content = json.dumps(raw_result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    encoded = content.encode("utf-8")
    return {
        "artifact_type": artifact_type,
        "uri": f"encrypted://agent-security/{task_id}/{artifact_type}.json",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
        "redacted": False,
        "metadata": {
            "engine_tag": ENGINE_TAG,
            "engine_commit": ENGINE_COMMIT,
            "content_encrypted_at_rest": True,
            **metadata,
        },
        "content": content,
    }


def usage_snapshot(
    baseline: dict[str, int],
    *,
    rounds_delta: int = 0,
    tokens_delta: int = 0,
    response_bytes_delta: int = 0,
    concurrency: int = 1,
) -> dict[str, int]:
    return {
        "rounds": int(baseline.get("rounds", 0)) + max(0, int(rounds_delta)),
        "tokens": int(baseline.get("tokens", 0)) + max(0, int(tokens_delta)),
        "cost_microunits": int(baseline.get("cost_microunits", 0)),
        "concurrent_requests": max(int(baseline.get("concurrent_requests", 0)), max(0, int(concurrency))),
        "response_bytes": int(baseline.get("response_bytes", 0)) + max(0, int(response_bytes_delta)),
    }


def run_upstream_task(
    *,
    claim: dict[str, Any],
    client: AigServiceClient,
    task_type: str,
    content: dict[str, Any],
    heartbeat: Callable[[dict[str, int], str | None], dict[str, Any]],
    initial_usage: dict[str, int],
    poll_seconds: float = 2.0,
    monotonic_clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[str, dict[str, Any]]:
    options = claim.get("scan_options") or {}
    session_id = str(options.get("upstream_session_id") or "").strip()
    if not session_id:
        session_id = client.create_task(
            task_type=task_type,
            content=content,
            idempotency_key=f"agent-manager:{claim['task']['task_id']}"[:128],
        )

    response = heartbeat(initial_usage, session_id)
    if not response.get("continue_allowed", False):
        client.cancel_task(session_id)
        raise AigScanStopped(str(response.get("stop_reason") or "task_stopped"))

    policy = claim.get("policy") or {}
    timeout_seconds = min(
        max(1, int(policy.get("task_timeout_seconds") or 3600)),
        max(1, int(policy.get("max_duration_seconds") or 1800)),
    )
    deadline = monotonic_clock() + timeout_seconds
    while monotonic_clock() < deadline:
        if claim.get("background_stop_reason"):
            client.cancel_task(session_id)
            raise AigScanStopped(str(claim["background_stop_reason"]))
        status_body = client.get_status(session_id)
        status = str(status_body.get("status") or "").strip().lower()
        if status in TERMINAL_STATUSES:
            if status not in {"complete", "completed", "done"}:
                progress = status_body.get("progress") or {}
                code = progress.get("error_code") if isinstance(progress, dict) else None
                if code not in AIG_FAILURE_MESSAGES:
                    code = "agent_security.aig_task_failed"
                raise AigServiceError(code, retryable=code in {
                    "agent_security.aig_model_rate_limited", "agent_security.aig_model_timeout",
                    "agent_security.aig_model_connection_failed",
                })
            return session_id, client.get_result(session_id)
        response = heartbeat(initial_usage, session_id)
        if not response.get("continue_allowed", False):
            client.cancel_task(session_id)
            raise AigScanStopped(str(response.get("stop_reason") or "task_stopped"))
        sleeper(max(0.1, float(poll_seconds)))

    client.cancel_task(session_id)
    raise AigServiceError("agent_security.aig_scan_timeout", retryable=True)


def sha256_text(value: Any) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def bounded_text(value: Any, *, limit: int = 2048) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]
