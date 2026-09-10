from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit


SUPPORTED_TASK_TYPES = {"model_redteam_report", "ai_infra_scan"}
TERMINAL_STATUSES = {"complete", "completed", "done", "error", "failed", "cancelled", "terminated"}
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
AIG_FAILURE_MESSAGES = {
    "agent_security.aig_model_not_found": "Model request returned HTTP 404. Check the API base URL, chat_completions_path and model name.",
    "agent_security.aig_model_auth_failed": "Model request returned HTTP 401/403. Check model credentials and access permissions.",
    "agent_security.aig_model_rate_limited": "Model request returned HTTP 429. Check model quota and concurrency.",
    "agent_security.aig_model_timeout": "Model request timed out. Check model availability and response time.",
    "agent_security.aig_model_connection_failed": "Could not connect to the model service. Check connectivity from the scanner container.",
    "agent_security.aig_model_initialization_failed": "Model initialization failed. Check target and evaluator configuration and scanner session logs.",
    "agent_security.aig_scan_timeout": "The scan exceeded the task duration limit.",
    "agent_security.aig_task_failed": "AI-Infra-Guard failed without a recognized diagnostic. Inspect the upstream session error events.",
}


@dataclass(frozen=True)
class AigServiceError(RuntimeError):
    code: str
    retryable: bool = False
    http_status: int | None = None

    def __str__(self) -> str:
        status = f" HTTP {self.http_status}" if self.http_status is not None else ""
        return f"AI-Infra-Guard service error{status} ({self.code})"


def _validated_service_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise AigServiceError("agent_security.aig_service_unavailable")
    return normalized


class AigServiceClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.base_url = _validated_service_url(base_url)
        self._token = token.strip()
        if not self._token:
            raise AigServiceError("agent_security.aig_service_unavailable")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
        self.max_response_bytes = max(1024, min(int(max_response_bytes), 64 * 1024 * 1024))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > self.max_response_bytes:
                    raise AigServiceError("agent_security.aig_result_invalid")
                raw = response.read(self.max_response_bytes + 1)
        except AigServiceError:
            raise
        except urllib.error.HTTPError as exc:
            code = "agent_security.aig_task_failed"
            try:
                raw_error = exc.read(min(self.max_response_bytes, 64 * 1024))
                body = json.loads(raw_error.decode("utf-8"))
                candidate = str(body.get("error_code") or "")
                if candidate.startswith("agent_security.") and len(candidate) <= 128:
                    code = candidate[:128]
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError):
                pass
            raise AigServiceError(
                code,
                retryable=exc.code >= 500,
                http_status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AigServiceError(
                "agent_security.aig_service_unavailable",
                retryable=True,
            ) from exc

        if len(raw) > self.max_response_bytes:
            raise AigServiceError("agent_security.aig_result_invalid")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AigServiceError("agent_security.aig_result_invalid") from exc
        if not isinstance(body, dict):
            raise AigServiceError("agent_security.aig_result_invalid")
        return body

    def health(self) -> dict[str, Any]:
        body = self._request("GET", "/healthz")
        if body.get("status") != "ok" or not isinstance(body.get("engine"), dict):
            raise AigServiceError("agent_security.aig_service_unavailable", retryable=True)
        return body

    def create_task(
        self,
        *,
        task_type: str,
        content: dict[str, Any],
        idempotency_key: str,
    ) -> str:
        if task_type not in SUPPORTED_TASK_TYPES or not isinstance(content, dict):
            raise AigServiceError("agent_security.aig_task_failed")
        body = self._request(
            "POST",
            "/v1/tasks",
            {"task_type": task_type, "content": content},
            idempotency_key=idempotency_key,
        )
        session_id = str(body.get("session_id") or "").strip()
        if not session_id or len(session_id) > 128:
            raise AigServiceError("agent_security.aig_result_invalid")
        return session_id

    def get_status(self, session_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/v1/tasks/{quote(session_id, safe='')}/status")
        if body.get("session_id") != session_id or not isinstance(body.get("status"), str):
            raise AigServiceError("agent_security.aig_result_invalid")
        return body

    def get_result(self, session_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/v1/tasks/{quote(session_id, safe='')}/result")
        if body.get("session_id") != session_id or not isinstance(body.get("result"), dict):
            raise AigServiceError("agent_security.aig_result_invalid")
        return body["result"]

    def cancel_task(self, session_id: str) -> None:
        body = self._request("POST", f"/v1/tasks/{quote(session_id, safe='')}/cancel", {})
        if body.get("session_id") != session_id or body.get("execution_stopped") is not True:
            raise AigServiceError("agent_security.aig_task_cancel_failed")
