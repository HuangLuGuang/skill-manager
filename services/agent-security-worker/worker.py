#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _configure_source_runtime() -> None:
    parents = list(Path(__file__).resolve().parents)
    if len(parents) < 3:
        return
    project_root = parents[2]
    if not (
        (project_root / "pyproject.toml").is_file()
        and (project_root / "agent_manager").is_dir()
    ):
        return

    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)

    load_dotenv(project_root / ".env", override=False)


_configure_source_runtime()

WORKER_DIR = str(Path(__file__).resolve().parent)
if WORKER_DIR not in sys.path:
    sys.path.insert(0, WORKER_DIR)

_aig_adapter = importlib.import_module("aig_adapter")
_mcp_adapter = importlib.import_module("mcp_adapter")
_llm_redteam_adapter = importlib.import_module("llm_redteam_adapter")
_ai_infrastructure_adapter = importlib.import_module("ai_infrastructure_adapter")
_dify_inventory_adapter = importlib.import_module("dify_inventory_adapter")
_aig_scan_common = importlib.import_module("aig_scan_common")
_aig_service_client = importlib.import_module("aig_service_client")
_credential_envelope = importlib.import_module("credential_envelope")
EvaluatorConfig = _aig_adapter.EvaluatorConfig
EvaluatorUnavailable = _aig_adapter.EvaluatorUnavailable
ScanStopped = _aig_adapter.ScanStopped
TargetUnavailable = _aig_adapter.TargetUnavailable
execute_agent_scan = _aig_adapter.execute_agent_scan
execute_mcp_scan = _mcp_adapter.execute_mcp_scan
execute_llm_redteam_scan = _llm_redteam_adapter.execute_llm_redteam_scan
execute_infrastructure_scan = _ai_infrastructure_adapter.execute_infrastructure_scan
execute_dify_inventory = _dify_inventory_adapter.execute_dify_inventory
DifyConsoleError = importlib.import_module("agent_manager.core.dify_console_client").DifyConsoleError
AigScanStopped = _aig_scan_common.AigScanStopped
AigServiceError = _aig_service_client.AigServiceError
ALGORITHM = _credential_envelope.ALGORITHM
WorkerKeyPair = _credential_envelope.WorkerKeyPair
decrypt_secret_envelope = _credential_envelope.decrypt_secret_envelope
generate_worker_key_pair = _credential_envelope.generate_worker_key_pair

CONTROL_PLANE_URL = os.environ.get(
    "AGENT_SECURITY_CONTROL_PLANE_URL",
    "http://backend:8000/api/v1/agent-security",
).rstrip("/")
WORKER_TOKEN = os.environ.get("AGENT_SECURITY_WORKER_TOKEN", "").strip()
POLL_SECONDS = max(1.0, float(os.environ.get("AGENT_SECURITY_WORKER_POLL_SECONDS", "5")))
HEALTH_PATH = Path("/tmp/agent-security-worker.healthy")
HEALTH_LOCK = threading.Lock()
RUNNING = True
_USAGE_KEYS = ("rounds", "tokens", "cost_microunits", "concurrent_requests", "response_bytes")
_TERMINAL_LEASE_ERROR_CODES = {
    "agent_security.task_lease_invalid",
    "agent_security.task_lease_expired",
}


class ControlPlaneError(RuntimeError):
    def __init__(self, status: int, code: str):
        super().__init__(f"control plane returned HTTP {status} ({code})")
        self.status = status
        self.code = code


def _stop(_signum, _frame) -> None:
    global RUNNING
    RUNNING = False


def _request(path: str, payload: dict[str, Any], *, timeout_seconds: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{CONTROL_PLANE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WORKER_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = "unknown"
        try:
            body = json.loads(exc.read().decode("utf-8"))
            code = str(body.get("error_code") or body.get("code") or "unknown")[:128]
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise ControlPlaneError(exc.code, code) from exc


def _touch_health() -> None:
    with HEALTH_LOCK:
        temporary = HEALTH_PATH.with_name(f".{HEALTH_PATH.name}.tmp")
        temporary.write_text(str(time.time()), encoding="utf-8")
        temporary.replace(HEALTH_PATH)


def _healthcheck() -> int:
    try:
        age = time.time() - float(HEALTH_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    return 0 if age < max(30.0, POLL_SECONDS * 4) else 1


def _task_usage_baseline(task: dict[str, Any]) -> dict[str, int]:
    nested = task.get("usage") if isinstance(task.get("usage"), dict) else {}

    def value(flat_key: str, nested_key: str) -> int:
        raw = task.get(flat_key)
        if raw is None:
            raw = nested.get(nested_key)
        try:
            return max(0, int(raw or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "rounds": value("rounds_used", "rounds"),
        "tokens": value("tokens_used", "tokens"),
        "cost_microunits": value("cost_microunits_used", "cost_microunits"),
        "concurrent_requests": value("max_concurrency_seen", "concurrent_requests"),
        "response_bytes": value("response_bytes_used", "response_bytes"),
    }


def _monotonic_usage(previous: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    return {key: max(int(previous.get(key, 0)), int(current.get(key, 0))) for key in _USAGE_KEYS}


def _control_plane_usage(task: dict[str, Any]) -> dict[str, int]:
    baseline = _task_usage_baseline(task)
    return {
        **baseline,
        "rounds": baseline["rounds"] + 1,
        "concurrent_requests": max(baseline["concurrent_requests"], 1),
    }


def _complete_control_plane_validation(claim: dict[str, Any]) -> None:
    task = claim["task"]
    task_id = task["task_id"]
    lease_token = claim["lease_token"]
    usage = _control_plane_usage(task)
    claim["last_usage"] = usage
    heartbeat = _request(
        f"/worker/tasks/{task_id}/heartbeat",
        {"lease_token": lease_token, "usage": usage},
    )
    if not heartbeat.get("continue_allowed"):
        return
    _request(
        f"/worker/tasks/{task_id}/complete",
        {
            "lease_token": lease_token,
            "status": "succeeded",
            "usage": usage,
            "cases": [
                {
                    "external_case_id": "p1-control-plane",
                    "category": "infrastructure",
                    "title": "P1 worker lease and budget protocol",
                    "status": "passed",
                    "round_count": 1,
                }
            ],
            "findings": [],
            "artifacts": [],
            "engine_name": "agent-manager-control-plane",
            "engine_version": "p1",
        },
    )


def _evaluator_config(claim: dict[str, Any]) -> EvaluatorConfig:
    options = claim.get("scan_options") or {}
    return EvaluatorConfig(
        api_key=claim["lease_token"],
        model=options.get("evaluation_model") or "",
        input_cost_microunits_per_million=max(0, int(os.environ.get("AGENT_SECURITY_EVALUATOR_INPUT_COST_MICRO_PER_MILLION", "0"))),
        output_cost_microunits_per_million=max(0, int(os.environ.get("AGENT_SECURITY_EVALUATOR_OUTPUT_COST_MICRO_PER_MILLION", "0"))),
        base_url=f"{CONTROL_PLANE_URL}/worker/tasks/{claim['task']['task_id']}/evaluator/v1",
    )


def _complete_failure(claim: dict[str, Any], *, code: str, retryable: bool) -> None:
    from aig_service_client import AIG_FAILURE_MESSAGES
    task_id = claim["task"]["task_id"]
    _request(
        f"/worker/tasks/{task_id}/complete",
        {
            "lease_token": claim["lease_token"],
            "status": "failed",
            "retryable": retryable,
            "error_code": code[:128],
            "error_message": AIG_FAILURE_MESSAGES.get(code, "Security scan Worker execution failed; inspect the stable error code and Worker health."),
            "usage": claim.get("last_usage") or _task_usage_baseline(claim["task"]),
            "cases": [],
            "findings": [],
            "artifacts": [],
        },
    )


def _run_agent_scan(claim: dict[str, Any], key_pair: WorkerKeyPair, worker_id: str) -> None:
    credential = claim.get("credential") or {}
    credential_secret: str | None = None
    if credential.get("configured"):
        envelope = credential.get("secret_envelope")
        if credential.get("secret_delivery") != "sealed_envelope" or not isinstance(envelope, dict):
            raise ValueError("credential envelope missing")
        credential_secret = decrypt_secret_envelope(
            envelope,
            key_pair,
            worker_id=worker_id,
            task_id=claim["task"]["task_id"],
            credential_id=credential["credential_id"],
        )

    heartbeat_lock = threading.Lock()
    keepalive_stop = threading.Event()
    initial_usage = _task_usage_baseline(claim["task"])
    claim["last_usage"] = initial_usage

    def heartbeat(usage: dict[str, int]) -> dict[str, Any]:
        with heartbeat_lock:
            if claim.get("background_stop_reason"):
                return {
                    "continue_allowed": False,
                    "stop_reason": claim["background_stop_reason"],
                }
            previous = claim.get("last_usage") or initial_usage
            monotonic_usage = _monotonic_usage(previous, usage)
            response = _request(
                f"/worker/tasks/{claim['task']['task_id']}/heartbeat",
                {"lease_token": claim["lease_token"], "usage": monotonic_usage},
            )
            _touch_health()
            claim["last_usage"] = monotonic_usage
            if not response.get("continue_allowed", False):
                claim["background_stop_reason"] = response.get("stop_reason") or "task_stopped"
            return response

    def keepalive() -> None:
        lease_seconds = max(3.0, float(claim.get("lease_seconds") or 60))
        interval = max(1.0, min(10.0, lease_seconds / 3.0))
        consecutive_failures = 0
        while not keepalive_stop.wait(interval):
            try:
                response = heartbeat(claim.get("last_usage") or initial_usage)
                if consecutive_failures:
                    print(
                        "agent-security worker lease heartbeat recovered "
                        f"after failures={consecutive_failures}",
                        file=sys.stderr,
                    )
                    consecutive_failures = 0
                if not response.get("continue_allowed", False):
                    return
            except (ControlPlaneError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                consecutive_failures += 1
                status = exc.status if isinstance(exc, ControlPlaneError) else "transport"
                code = exc.code if isinstance(exc, ControlPlaneError) else type(exc).__name__
                print(
                    "agent-security worker lease heartbeat failed "
                    f"count={consecutive_failures} type={type(exc).__name__} status={status} code={code}",
                    file=sys.stderr,
                )
                if isinstance(exc, ControlPlaneError) and exc.code in _TERMINAL_LEASE_ERROR_CODES:
                    claim["background_stop_reason"] = exc.code
                    return

                continue

    keepalive_thread = threading.Thread(
        target=keepalive,
        name=f"agent-security-lease-{claim['task']['task_id']}",
        daemon=True,
    )
    keepalive_thread.start()

    try:
        result = execute_agent_scan(
            claim,
            credential_secret,
            _evaluator_config(claim),
            heartbeat,
            initial_usage=initial_usage,
        )
        _request(
            f"/worker/tasks/{claim['task']['task_id']}/complete",
            {"lease_token": claim["lease_token"], **result},
        )
    finally:
        keepalive_stop.set()
        keepalive_thread.join(timeout=2)
        credential_secret = None


def _run_mcp_scan(claim: dict[str, Any]) -> None:
    task_id = claim["task"]["task_id"]
    lease_token = claim["lease_token"]
    initial_usage = _task_usage_baseline(claim["task"])
    claim["last_usage"] = initial_usage

    def heartbeat(usage: dict[str, int]) -> dict[str, Any]:
        monotonic_usage = _monotonic_usage(claim.get("last_usage") or initial_usage, usage)
        response = _request(
            f"/worker/tasks/{task_id}/heartbeat",
            {"lease_token": lease_token, "usage": monotonic_usage},
        )
        claim["last_usage"] = monotonic_usage
        _touch_health()
        return response

    result = execute_mcp_scan(claim, heartbeat, initial_usage=initial_usage)
    _request(
        f"/worker/tasks/{task_id}/complete",
        {"lease_token": lease_token, **result},
    )


def _claim_credential_secret(
    claim: dict[str, Any], key_pair: WorkerKeyPair, worker_id: str
) -> str | None:
    credential = claim.get("credential") or {}
    if not credential.get("configured"):
        return None
    envelope = credential.get("secret_envelope")
    if credential.get("secret_delivery") != "sealed_envelope" or not isinstance(envelope, dict):
        raise ValueError("credential envelope missing")
    return decrypt_secret_envelope(
        envelope,
        key_pair,
        worker_id=worker_id,
        task_id=claim["task"]["task_id"],
        credential_id=credential["credential_id"],
    )


def _claim_credential_secrets(
    claim: dict[str, Any], key_pair: WorkerKeyPair, worker_id: str
) -> dict[str, str]:
    secrets_by_purpose: dict[str, str] = {}
    for credential in claim.get("credentials") or []:
        envelope = credential.get("secret_envelope")
        purpose = str(credential.get("purpose") or "")
        if not purpose or credential.get("secret_delivery") != "sealed_envelope" or not isinstance(envelope, dict):
            raise ValueError("credential envelope missing")
        secrets_by_purpose[purpose] = decrypt_secret_envelope(
            envelope, key_pair, worker_id=worker_id, task_id=claim["task"]["task_id"],
            credential_id=credential["credential_id"],
        )
    return secrets_by_purpose


def _run_dify_inventory(claim: dict[str, Any], key_pair: WorkerKeyPair, worker_id: str) -> None:
    credential_secrets = _claim_credential_secrets(claim, key_pair, worker_id)
    initial_usage = _task_usage_baseline(claim["task"])
    claim["last_usage"] = initial_usage
    heartbeat_lock = threading.Lock()
    keepalive_stop = threading.Event()

    def heartbeat(usage: dict[str, int]) -> dict[str, Any]:
        with heartbeat_lock:
            if claim.get("background_stop_reason"):
                return {"continue_allowed": False, "stop_reason": claim["background_stop_reason"]}
            monotonic_usage = _monotonic_usage(claim.get("last_usage") or initial_usage, usage)
            response = _request(
                f"/worker/tasks/{claim['task']['task_id']}/heartbeat",
                {"lease_token": claim["lease_token"], "usage": monotonic_usage},
            )
            claim["last_usage"] = monotonic_usage
            _touch_health()
            if not response.get("continue_allowed", False):
                claim["background_stop_reason"] = response.get("stop_reason") or "task_stopped"
            return response

    def keepalive() -> None:
        interval = max(1.0, min(10.0, float(claim.get("lease_seconds") or 60) / 3.0))
        failures = 0
        while not keepalive_stop.wait(interval):
            try:
                response = heartbeat(claim.get("last_usage") or initial_usage)
                failures = 0
                if not response.get("continue_allowed", False):
                    return
            except (ControlPlaneError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                failures += 1
                status = exc.status if isinstance(exc, ControlPlaneError) else "transport"
                code = exc.code if isinstance(exc, ControlPlaneError) else type(exc).__name__
                print(f"agent-security Dify heartbeat failed count={failures} status={status} code={code}", file=sys.stderr)
                if isinstance(exc, ControlPlaneError) and exc.code in _TERMINAL_LEASE_ERROR_CODES:
                    claim["background_stop_reason"] = exc.code
                    return

    def infer_intent(summary: dict[str, Any], usage: dict[str, int]) -> dict[str, Any]:
        if claim.get("background_stop_reason"):
            return {
                "status": "unavailable",
                "error_code": "dify_inventory.intent_inference_stopped",
                "continue_allowed": False,
                "stop_reason": claim["background_stop_reason"],
                "usage": claim.get("last_usage") or initial_usage,
            }
        with heartbeat_lock:
            request_usage = _monotonic_usage(claim.get("last_usage") or initial_usage, usage)
        try:
            response = _request(
                f"/worker/tasks/{claim['task']['task_id']}/infer-intent",
                {"lease_token": claim["lease_token"], "usage": request_usage, "summary": summary},
                timeout_seconds=630,
            )
        except (ControlPlaneError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if isinstance(exc, ControlPlaneError) and exc.code in _TERMINAL_LEASE_ERROR_CODES:
                claim["background_stop_reason"] = exc.code
                return {
                    "status": "unavailable", "error_code": "dify_inventory.intent_inference_stopped",
                    "continue_allowed": False, "stop_reason": exc.code,
                    "usage": claim.get("last_usage") or request_usage,
                }
            code = exc.code if isinstance(exc, ControlPlaneError) else type(exc).__name__
            print(
                f"agent-security Dify intent inference unavailable type={type(exc).__name__} code={code}",
                file=sys.stderr,
            )
            return {
                "status": "unavailable", "error_code": "dify_inventory.intent_model_unavailable",
                "continue_allowed": True, "usage": claim.get("last_usage") or request_usage,
            }
        with heartbeat_lock:
            response_usage = response.get("usage") if isinstance(response.get("usage"), dict) else request_usage
            claim["last_usage"] = _monotonic_usage(claim.get("last_usage") or request_usage, response_usage)
            response["usage"] = claim["last_usage"]
            if not response.get("continue_allowed", True):
                claim["background_stop_reason"] = response.get("stop_reason") or "task_stopped"
        return response

    thread = threading.Thread(target=keepalive, name=f"agent-security-dify-lease-{claim['task']['task_id']}", daemon=True)
    thread.start()
    try:
        result = execute_dify_inventory(
            claim,
            credential_secrets,
            heartbeat,
            initial_usage=initial_usage,
            infer_intent=infer_intent if (claim.get("scan_options") or {}).get("infer_agent_intent") else None,
        )
        _request(f"/worker/tasks/{claim['task']['task_id']}/complete", {"lease_token": claim["lease_token"], **result})
    finally:
        keepalive_stop.set()
        thread.join(timeout=2)
        credential_secrets.clear()


def _run_aig_service_scan(
    claim: dict[str, Any],
    key_pair: WorkerKeyPair,
    worker_id: str,
    execute_scan,
) -> None:
    credential_secret = _claim_credential_secret(claim, key_pair, worker_id)
    initial_usage = _task_usage_baseline(claim["task"])
    claim["last_usage"] = initial_usage
    heartbeat_lock = threading.Lock()
    keepalive_stop = threading.Event()

    def heartbeat(usage: dict[str, int], session_state: str | None = None) -> dict[str, Any]:
        with heartbeat_lock:
            if session_state:
                claim["upstream_session_id"] = session_state
            if claim.get("background_stop_reason"):
                return {"continue_allowed": False, "stop_reason": claim["background_stop_reason"]}
            monotonic_usage = _monotonic_usage(claim.get("last_usage") or initial_usage, usage)
            payload: dict[str, Any] = {
                "lease_token": claim["lease_token"],
                "usage": monotonic_usage,
            }
            if claim.get("upstream_session_id"):
                payload["session_state"] = claim["upstream_session_id"]
            if claim.get("scan_progress") and claim["scan_progress"] != claim.get("reported_scan_progress"):
                payload["scan_progress"] = claim["scan_progress"]
            response = _request(
                f"/worker/tasks/{claim['task']['task_id']}/heartbeat",
                payload,
            )
            _touch_health()
            claim["last_usage"] = monotonic_usage
            if "scan_progress" in payload:
                claim["reported_scan_progress"] = payload["scan_progress"]
            if not response.get("continue_allowed", False):
                claim["background_stop_reason"] = response.get("stop_reason") or "task_stopped"
            return response

    def keepalive() -> None:
        lease_seconds = max(3.0, float(claim.get("lease_seconds") or 60))
        interval = max(1.0, min(10.0, lease_seconds / 3.0))
        consecutive_failures = 0
        while not keepalive_stop.wait(interval):
            try:
                response = heartbeat(
                    claim.get("last_usage") or initial_usage,
                    claim.get("upstream_session_id"),
                )
                if consecutive_failures:
                    print(
                        "agent-security AIG lease heartbeat recovered "
                        f"after failures={consecutive_failures}",
                        file=sys.stderr,
                    )
                    consecutive_failures = 0
                if not response.get("continue_allowed", False):
                    return
            except (ControlPlaneError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                consecutive_failures += 1
                status = exc.status if isinstance(exc, ControlPlaneError) else "transport"
                code = exc.code if isinstance(exc, ControlPlaneError) else type(exc).__name__
                print(
                    "agent-security AIG lease heartbeat failed "
                    f"count={consecutive_failures} type={type(exc).__name__} status={status} code={code}",
                    file=sys.stderr,
                )
                if isinstance(exc, ControlPlaneError) and exc.code in _TERMINAL_LEASE_ERROR_CODES:
                    claim["background_stop_reason"] = exc.code
                    return

    thread = threading.Thread(
        target=keepalive,
        name=f"agent-security-aig-lease-{claim['task']['task_id']}",
        daemon=True,
    )
    thread.start()
    try:
        result = execute_scan(
            claim,
            credential_secret,
            _evaluator_config(claim),
            heartbeat,
            initial_usage=initial_usage,
        )
        _request(
            f"/worker/tasks/{claim['task']['task_id']}/complete",
            {"lease_token": claim["lease_token"], **result},
        )
    finally:
        keepalive_stop.set()
        thread.join(timeout=2)
        credential_secret = None


def _register_key(key_pair: WorkerKeyPair) -> str:
    response = _request(
        "/worker/key",
        {"algorithm": ALGORITHM, "public_key": key_pair.public_key},
    )
    if response.get("public_key_fingerprint") != key_pair.fingerprint:
        raise ValueError("control-plane worker key fingerprint mismatch")
    return str(response["worker_id"])


def run() -> int:
    if not WORKER_TOKEN:
        print("AGENT_SECURITY_WORKER_TOKEN is required", file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    key_pair = generate_worker_key_pair()
    worker_id: str | None = None
    while RUNNING:
        try:
            if not worker_id:
                worker_id = _register_key(key_pair)
            _request("/worker/heartbeat", {})
            claim = _request(
                "/worker/claim",
                {
                    "capabilities": [
                        "control_plane_validation",
                        "agent_risk_scan",
                        "mcp_risk_scan",
                        "llm_redteam_scan",
                        "ai_infrastructure_vulnerability_scan",
                        "dify_asset_inventory",
                    ]
                },
            )
            _touch_health()
            if claim.get("task"):
                try:
                    if claim["task"]["scan_kind"] == "agent_risk_scan":
                        _run_agent_scan(claim, key_pair, worker_id)
                    elif claim["task"]["scan_kind"] == "mcp_risk_scan":
                        _run_mcp_scan(claim)
                    elif claim["task"]["scan_kind"] == "llm_redteam_scan":
                        _run_aig_service_scan(claim, key_pair, worker_id, execute_llm_redteam_scan)
                    elif claim["task"]["scan_kind"] == "ai_infrastructure_vulnerability_scan":
                        _run_aig_service_scan(claim, key_pair, worker_id, execute_infrastructure_scan)
                    elif claim["task"]["scan_kind"] == "dify_asset_inventory":
                        _run_dify_inventory(claim, key_pair, worker_id)
                    else:
                        _complete_control_plane_validation(claim)
                except ScanStopped:
                    # The heartbeat endpoint already persisted the terminal stop reason.
                    pass
                except AigScanStopped:
                    # The adapter synchronously stopped the upstream process
                    # after the control plane denied continuation.
                    pass
                except AigServiceError as exc:
                    reason = _aig_service_client.AIG_FAILURE_MESSAGES.get(exc.code, "Check scanning service availability.")
                    print(f"agent-security worker AIG service error: code={exc.code}; reason={reason}", file=sys.stderr)
                    _complete_failure(claim, code=exc.code, retryable=exc.retryable)
                except DifyConsoleError as exc:
                    print(f"agent-security worker Dify inventory error: code={exc.code}", file=sys.stderr)
                    _complete_failure(claim, code=exc.code, retryable=exc.retryable)
                except EvaluatorUnavailable as exc:
                    print(f"agent-security worker evaluator error: {type(exc).__name__}", file=sys.stderr)
                    _complete_failure(claim, code="agent_security.evaluator_unavailable", retryable=True)
                except TargetUnavailable as exc:
                    print(f"agent-security worker target error: {type(exc).__name__}", file=sys.stderr)
                    _complete_failure(claim, code="agent_security.target_unavailable", retryable=True)
                except (ValueError, KeyError) as exc:
                    print(f"agent-security worker task configuration error: {type(exc).__name__}", file=sys.stderr)
                    _complete_failure(claim, code="agent_security.worker_configuration_invalid", retryable=False)
                except (ControlPlaneError, urllib.error.URLError, TimeoutError) as exc:
                    print(f"agent-security worker task transport error: {type(exc).__name__}", file=sys.stderr)
                    try:
                        _complete_failure(claim, code="agent_security.worker_transport_failure", retryable=True)
                    except (ControlPlaneError, urllib.error.URLError, TimeoutError):
                        pass
                except Exception as exc:
                    print(f"agent-security worker task error: {type(exc).__name__}", file=sys.stderr)
                    _complete_failure(claim, code="agent_security.worker_execution_failure", retryable=False)
        except (ControlPlaneError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            print(f"agent-security worker control-plane error: {type(exc).__name__}", file=sys.stderr)
            if isinstance(exc, ControlPlaneError) and exc.status == 401:
                worker_id = None
        if RUNNING:
            time.sleep(POLL_SECONDS)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--healthcheck":
        raise SystemExit(_healthcheck())
    raise SystemExit(run())
