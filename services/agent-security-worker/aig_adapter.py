from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import html
import ipaddress
import json
import math
import os
import re
import socket
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

try:
    from agent_manager.security_redaction import redact_sensitive_text, redact_sensitive_value
except ImportError:  # Worker image copies the shared module directly into /app.
    from security_redaction import redact_sensitive_text, redact_sensitive_value

AIG_TAG = "v4.6.0"
AIG_COMMIT = "e8931cc68001b66ad024fd87ef07394e9e96524a"
AIG_ENGINE_NAME = "tencent-ai-infra-guard-agent-scan"
AIG_REPORT_SCHEMA = "agent-security-report@1"
SUPPORTED_PROVIDER_TYPES = (
    "dify",
    "coze",
    "coze-com",
    "openai",
    "deepseek",
    "fireworks",
    "groq",
    "litellm",
    "localai",
    "mistral",
    "ollama",
    "openrouter",
    "perplexity",
    "togetherai",
    "anthropic",
    "google",
    "cohere",
    "huggingface",
    "replicate",
    "http",
    "websocket",
)
RISK_CODE_BY_ASI = {
    "ASI01": "agent_goal_hijack",
    "ASI02": "tool_misuse",
    "ASI03": "identity_privilege_abuse",
    "ASI04": "agentic_supply_chain",
    "ASI05": "unexpected_code_execution",
    "ASI06": "memory_context_poisoning",
    "ASI07": "insecure_inter_agent_communication",
    "ASI08": "cascading_failure",
    "ASI09": "human_agent_trust_exploitation",
    "ASI10": "rogue_agent",
}
_SAFE_RESPONSE_HEADERS = {"content-type", "content-length", "x-request-id", "traceparent"}
_UNSAFE_UPSTREAM_LOG_MARKERS = (
    "custom prompt:",
    "executing task with agent",
    "finish called with brief",
    "history compaction skipped due to llm error response",
    "llm response:",
    "final output formatting skipped due to llm error response",
)


class ScanStopped(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class EvaluatorUnavailable(RuntimeError):
    """The evaluator exhausted its own retries; the scan result is not trustworthy."""


class TargetUnavailable(RuntimeError):
    """The target produced no successful dialogue, so a safe conclusion is invalid."""


@dataclass(frozen=True)
class EvaluatorConfig:
    api_key: str
    model: str
    base_url: str
    input_cost_microunits_per_million: int = 0
    output_cost_microunits_per_million: int = 0


def _redact(value: Any, *, limit: int = 16_384) -> str:
    candidate = value
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            candidate = json.loads(value)
        except json.JSONDecodeError:
            candidate = value
    redacted = redact_sensitive_value(candidate)
    text = (
        json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        if isinstance(redacted, (dict, list))
        else redact_sensitive_text(redacted)
    )
    text = html.escape(html.unescape(text), quote=False)
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_upstream_log_text(value: str) -> str:
    text = str(value)
    lowered = text.lower()
    if any(marker in lowered for marker in _UNSAFE_UPSTREAM_LOG_MARKERS):
        return "[upstream message content redacted]"
    return _redact(text, limit=4_096)


def _path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for name, index in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+)\]", path):
        parts.append(name if name else int(index))
    return parts


def _extract_path(value: Any, path: str) -> Any:
    current = value
    for part in _path_parts(path):
        if isinstance(part, int) and isinstance(current, list):
            try:
                current = current[part]
            except IndexError:
                return None
        elif isinstance(part, str) and isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _set_path(value: dict[str, Any], path: str, item: Any) -> None:
    parts = _path_parts(path)
    if not parts or any(isinstance(part, int) for part in parts):
        return
    current = value
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[str(parts[-1])] = item


def verify_worker_dns_pin(target: dict[str, Any]) -> None:
    parsed = urlsplit(str(target.get("endpoint_url", "")))
    hostname = parsed.hostname
    if not hostname:
        raise ScanStopped("target_host_missing")
    try:
        addresses = {str(ipaddress.ip_address(hostname.strip("[]")))}
    except ValueError:
        try:
            addresses = {
                str(ipaddress.ip_address(record[4][0]))
                for record in socket.getaddrinfo(hostname, parsed.port, type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise ScanStopped("target_dns_failed") from exc
    expected = {str(ipaddress.ip_address(value)) for value in target.get("resolved_ips", [])}
    if not expected or addresses != expected:
        raise ScanStopped("dns_rebinding_detected")


def build_provider_document(
    target: dict[str, Any],
    credential_type: str | None,
    credential_secret: str | None,
    *,
    max_response_bytes: int,
) -> dict[str, Any]:
    target_type = str(target.get("target_type", ""))
    if target_type not in SUPPORTED_PROVIDER_TYPES:
        raise ValueError(f"unsupported provider type: {target_type}")
    source = copy.deepcopy(target.get("config") or {})
    endpoint_url = str(target["endpoint_url"])
    headers = dict(source.get("headers") or {})
    if credential_secret:
        if credential_type == "bearer":
            headers["Authorization"] = f"Bearer {credential_secret}"
        elif credential_type == "basic":
            encoded = base64.b64encode(credential_secret.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        elif credential_type in {"api_key", "custom"}:
            header = str(source.get("credential_header", "X-API-Key"))
            prefix = str(source.get("credential_prefix", ""))
            headers[header] = f"{prefix}{credential_secret}"

    extra = dict(source.get("extra") or {})
    extra["max_response_bytes"] = max_response_bytes
    config: dict[str, Any] = {
        "headers": headers,
        "timeout_ms": int(source.get("timeout_ms", 30_000)),
        "extra": extra,
    }
    model = str(source.get("model", "")).strip()
    if target_type in {"http", "websocket"}:
        config.update(
            {
                "url": endpoint_url,
                "endpoint": source.get("endpoint"),
                "method": source.get("method", "POST"),
                "body": source.get("body", source.get("message_template", {"message": "{{prompt}}"})),
                "transform_response": source.get("transform_response"),
            }
        )
    else:
        config["apiBaseUrl"] = endpoint_url
        config["model"] = model or None
        if credential_secret:
            config["apiKey"] = credential_secret
    provider_id = target_type
    if model and target_type not in {"dify", "coze", "coze-com", "http", "websocket"}:
        provider_id = f"{target_type}:{model}"
    return {
        "targets": [
            {
                "id": provider_id,
                "config": {
                    "label": str(target.get("target_id", "agent-target")),
                    **config,
                },
            }
        ]
    }


class ScanRuntime:
    def __init__(
        self,
        heartbeat: Callable[[dict[str, int]], dict[str, Any]],
        *,
        conversation_mode: str,
        initial_session_id: str | None,
        input_cost_rate: int,
        output_cost_rate: int,
        initial_usage: dict[str, int] | None = None,
        target_check: Callable[[], None] | None = None,
    ) -> None:
        self.heartbeat = heartbeat
        self.conversation_mode = conversation_mode
        self.session_id = initial_session_id
        self.input_cost_rate = input_cost_rate
        self.output_cost_rate = output_cost_rate
        self.target_check = target_check
        self.model_errors = 0
        self.successful_target_calls = 0
        self.failed_target_calls = 0
        baseline = initial_usage or {}
        self.rounds = max(0, int(baseline.get("rounds", 0)))
        self.tokens = max(0, int(baseline.get("tokens", 0)))
        self.cost_microunits = max(0, int(baseline.get("cost_microunits", 0)))
        self.max_concurrency = max(0, int(baseline.get("concurrent_requests", 0)))
        self.response_bytes = max(0, int(baseline.get("response_bytes", 0)))
        self._active = 0
        self._state_lock = threading.RLock()
        self._session_lock = threading.Lock()
        self.turns: list[dict[str, Any]] = []
        self.target_calls_by_stage: dict[str, int] = {}

    def snapshot(self) -> dict[str, int]:
        with self._state_lock:
            return {
                "rounds": self.rounds,
                "tokens": self.tokens,
                "cost_microunits": self.cost_microunits,
                "concurrent_requests": self.max_concurrency,
                "response_bytes": self.response_bytes,
            }

    def check(self) -> None:
        response = self.heartbeat(self.snapshot())
        if not response.get("continue_allowed", False):
            raise ScanStopped(str(response.get("stop_reason") or response.get("status") or "scan_stopped"))

    def record_stage_target_call(self, stage_id: str | None) -> None:
        if not stage_id:
            return
        with self._state_lock:
            self.target_calls_by_stage[stage_id] = self.target_calls_by_stage.get(stage_id, 0) + 1

    def _begin(self, *, target_round: bool) -> None:
        with self._state_lock:
            if target_round:
                self.rounds += 1
            self._active += 1
            self.max_concurrency = max(self.max_concurrency, self._active)
        self.check()

    def _end(self, *, response_bytes: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._state_lock:
            self._active = max(0, self._active - 1)
            self.response_bytes += max(0, response_bytes)
            self.tokens += max(0, input_tokens) + max(0, output_tokens)
            self.cost_microunits += math.ceil(
                (max(0, input_tokens) * self.input_cost_rate + max(0, output_tokens) * self.output_cost_rate)
                / 1_000_000
            )
        self.check()

    def call_target(
        self, client: Any, provider: Any, prompt: str, *, stage_id: str | None = None
    ) -> Any:
        lock = self._session_lock if self.conversation_mode == "multi_turn" else _NullLock()
        with lock:
            if self.target_check:
                self.target_check()
            config = provider.config
            extra = dict(config.extra or {})
            if self.conversation_mode == "single_turn":
                self.session_id = None
                extra.pop("conversation_id", None)
            elif self.session_id:
                extra["conversation_id"] = self.session_id
                session_request_path = str(extra.get("session_request_path", ""))
                if session_request_path and isinstance(config.body, dict):
                    body = copy.deepcopy(config.body)
                    _set_path(body, session_request_path, self.session_id)
                    config.body = body
            config.extra = extra
            self._begin(target_round=True)
            try:
                self.record_stage_target_call(stage_id)
                result = client.call_provider(provider, prompt)
            except Exception:
                with self._state_lock:
                    self._active = max(0, self._active - 1)
                raise
            response = result.provider_response if result else None
            raw = response.raw if response else None
            output = response.output if response else ""
            response_bytes = (
                len(json.dumps(raw, ensure_ascii=False, default=str).encode("utf-8")) if raw is not None else 0
            )
            session_id = response.session_id if response else None
            session_response_path = str(extra.get("session_response_path", ""))
            if not session_id and session_response_path:
                session_id = _extract_path(raw, session_response_path)
            if self.conversation_mode == "multi_turn" and session_id:
                self.session_id = str(session_id)[:2048]
            if result and result.success:
                self.successful_target_calls += 1
            else:
                self.failed_target_calls += 1
            self.turns.append(
                {
                    "prompt": str(prompt)[:65_536],
                    "response": str(output or "")[:65_536],
                    "success": bool(result.success),
                    "session_id_hash": hashlib.sha256(str(self.session_id).encode()).hexdigest()
                    if self.session_id
                    else None,
                }
            )
            self._end(response_bytes=response_bytes)
            return result

    def model_call_started(self) -> None:
        self._begin(target_round=False)

    def model_call_finished(self, messages: list[dict[str, Any]], response: str) -> None:
        input_bytes = len(json.dumps(messages, ensure_ascii=False, default=str).encode("utf-8"))
        output_bytes = len(str(response).encode("utf-8"))
        self._end(
            response_bytes=output_bytes,
            input_tokens=max(1, math.ceil(input_bytes / 4)),
            output_tokens=max(1, math.ceil(output_bytes / 4)),
        )

    def model_call_failed(self) -> None:
        with self._state_lock:
            self.model_errors += 1

    def ensure_trustworthy_result(self) -> None:
        if self.model_errors:
            raise EvaluatorUnavailable("evaluator returned terminal error responses")
        if self.rounds < 1 or self.successful_target_calls < 1:
            raise TargetUnavailable("target produced no successful dialogue response")


class _NullLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None


def _configure_upstream_logging() -> None:
    from loguru import logger

    logger.remove()
    logger.add(
        lambda message: print(
            _safe_upstream_log_text(message.record.get("message", "")),
            file=os.sys.stderr,
        ),
        level=os.environ.get("AIG_AGENT_SCAN_LOG_LEVEL", "WARNING"),
    )


def _upstream_types() -> tuple[Any, Any, Any, Any, Any]:
    from agent_scan.core.agent import Agent
    from agent_scan.core.agent_adapter.adapter import (
        AIProviderClient,
        ProviderResponseInfo,
        ProviderTestResult,
    )
    from agent_scan.utils.llm import LLM

    _configure_upstream_logging()
    return Agent, AIProviderClient, ProviderResponseInfo, ProviderTestResult, LLM


def _provider_types() -> tuple[Any, Any, Any]:
    from agent_scan.core.agent_adapter.adapter import (
        AIProviderClient,
        ProviderResponseInfo,
        ProviderTestResult,
    )

    return AIProviderClient, ProviderResponseInfo, ProviderTestResult


def _bounded_client_class(max_response_bytes: int) -> type:
    AIProviderClient, ProviderResponseInfo, ProviderTestResult = _provider_types()

    class BoundedAIProviderClient(AIProviderClient):
        """Agent Manager modification: bound HTTP reads and remove untrusted bodies from logs."""

        def _make_http_request(
            self, url: str, method: str, headers: dict, body: Any, transform_response: str | None = None
        ):
            start = __import__("time").time()
            safe_url = _safe_url(url)
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream(
                        method=method,
                        url=url,
                        headers=headers,
                        json=body if isinstance(body, dict) else None,
                        content=body if isinstance(body, str) else None,
                    ) as response:
                        declared = int(response.headers.get("content-length", "0") or 0)
                        if declared > max_response_bytes:
                            return ProviderTestResult(
                                success=False,
                                message="Response exceeded the configured size limit",
                                provider_response=ProviderResponseInfo(
                                    error="response_size_limit", metadata={"url": safe_url}
                                ),
                            )
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > max_response_bytes:
                                return ProviderTestResult(
                                    success=False,
                                    message="Response exceeded the configured size limit",
                                    provider_response=ProviderResponseInfo(
                                        error="response_size_limit", metadata={"url": safe_url}
                                    ),
                                )
                            chunks.append(chunk)
                        content = b"".join(chunks)
                        text = content.decode(response.encoding or "utf-8", errors="replace")
                        content_type = response.headers.get("content-type", "").lower()
                        if "text/event-stream" in content_type:
                            raw_response, token_usage = self._parse_sse_response(text)
                        else:
                            try:
                                raw_response = json.loads(text)
                            except json.JSONDecodeError:
                                raw_response = text
                            token_usage = raw_response.get("usage") if isinstance(raw_response, dict) else None
                        output = self._extract_output(raw_response, transform_response)
                        response_headers = {
                            key: value
                            for key, value in response.headers.items()
                            if key.lower() in _SAFE_RESPONSE_HEADERS
                        }
                        provider_response = ProviderResponseInfo(
                            raw=raw_response,
                            output=output,
                            headers=response_headers,
                            token_usage=token_usage,
                            metadata={
                                "status_code": response.status_code,
                                "elapsed_time": f"{__import__('time').time() - start:.2f}s",
                                "url": safe_url,
                                "method": method,
                                "response_bytes": size,
                            },
                        )
                        return ProviderTestResult(
                            success=200 <= response.status_code < 300 and bool(output),
                            message=f"HTTP status {response.status_code}",
                            provider_response=provider_response,
                        )
            except httpx.TimeoutException:
                return ProviderTestResult(
                    success=False,
                    message="Target request timed out",
                    provider_response=ProviderResponseInfo(error="timeout", metadata={"url": safe_url}),
                )
            except httpx.HTTPError as exc:
                return ProviderTestResult(
                    success=False,
                    message=f"Target request failed: {type(exc).__name__}",
                    provider_response=ProviderResponseInfo(error=type(exc).__name__, metadata={"url": safe_url}),
                )

    return BoundedAIProviderClient


def _instrumented_llm_class(runtime: ScanRuntime) -> type:
    from agent_scan.utils.llm import LLM, is_llm_error_response

    class InstrumentedLLM(LLM):
        def chat(self, message: list[dict[str, Any]], p: bool = False, language: str = "zh") -> str:
            runtime.model_call_started()
            try:
                result = super().chat(message, p=p, language=language)
            except Exception:
                with runtime._state_lock:
                    runtime._active = max(0, runtime._active - 1)
                raise
            runtime.model_call_finished(message, result)
            if is_llm_error_response(result):
                runtime.model_call_failed()
            return result

    return InstrumentedLLM


def _normalize_report(
    report: dict[str, Any], runtime: ScanRuntime, *, task_id: str, skills: list[str]
) -> dict[str, Any]:
    def nonnegative_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    transcript = [
        {
            "round": index,
            "prompt": _redact(str(turn.get("prompt", "")), limit=8_192),
            "response": _redact(str(turn.get("response", "")), limit=8_192),
            "success": bool(turn.get("success")),
            "session_id_hash": turn.get("session_id_hash"),
        }
        for index, turn in enumerate(runtime.turns[:100], start=1)
    ]
    raw_executions = report.get("detection_executions")
    has_execution_evidence = isinstance(raw_executions, list) and bool(raw_executions)
    executions_by_skill: dict[str, dict[str, Any]] = {}
    if has_execution_evidence:
        for item in raw_executions:
            if not isinstance(item, dict):
                continue
            skill_name = str(item.get("skill_name") or "")
            if skill_name not in skills or skill_name in executions_by_skill:
                continue
            executions_by_skill[skill_name] = {
                "skill_name": skill_name,
                "stage_id": _redact(str(item.get("stage_id") or ""), limit=64),
                "status": str(item.get("status") or "unknown").lower(),
                "dialogue_calls": nonnegative_int(item.get("dialogue_calls")),
                "candidate_finding_count": nonnegative_int(item.get("finding_count")),
                "error_type": _redact(str(item.get("error_type") or ""), limit=128) or None,
                "error_message": _redact(str(item.get("error_message") or ""), limit=512) or None,
            }

    confirmed_by_skill = {skill: 0 for skill in skills}
    unmapped_finding_count = 0
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(report.get("results") or [], start=1):
        external_id = str(item.get("id") or f"finding-{index}")[:256]
        owasp = [str(value).upper() for value in item.get("owasp") or []]
        upstream_type = str(item.get("type") or "")
        explicit_asi_match = re.search(r"(?i)(?:^|[^A-Z0-9])ASI0?(10|[1-9])(?:[^0-9]|$)", upstream_type)
        explicit_asi = f"ASI{int(explicit_asi_match.group(1)):02d}" if explicit_asi_match else None
        # Locked upstream v4.6.0 defaults any unclassified risk_type to ASI10.
        # Require the finding type itself to carry an explicit ASI code so a
        # future/unknown upstream type cannot silently become rogue_agent.
        asi = explicit_asi if explicit_asi in owasp and explicit_asi in RISK_CODE_BY_ASI else None
        finding_code = RISK_CODE_BY_ASI.get(asi or "", "unmapped")
        level = str(item.get("level", "")).lower()
        severity = level if level in {"critical", "high", "medium", "low", "info"} else "medium"
        if finding_code == "unmapped" and severity == "low":
            severity = "medium"
        conversation = item.get("conversation") or []
        if not conversation:
            conversation = runtime.turns[-10:]
        redacted_turns = [
            {
                "prompt": _redact(str(turn.get("prompt", "")), limit=8_192),
                "response": _redact(str(turn.get("response", "")), limit=8_192),
            }
            for turn in conversation[:50]
        ]
        title = _redact(str(item.get("title") or finding_code), limit=512)
        source_skill = str(item.get("source_skill") or "")
        source_is_controlled = item.get("source_mapping") == "worker_context"
        if source_is_controlled and source_skill in executions_by_skill:
            case_external_id = f"aig-rule:{source_skill}"
            confirmed_by_skill[source_skill] += 1
            source_mapping = "mapped"
        else:
            case_external_id = "aig-rule:unmapped"
            source_skill = ""
            unmapped_finding_count += 1
            source_mapping = "unmapped"
        findings.append(
            {
                "case_external_id": case_external_id,
                "finding_code": finding_code,
                "severity": severity,
                "status": "open",
                "title": title,
                "description": _redact(item.get("description") or "No description"),
                "evidence": {
                    "upstream_finding_id": external_id,
                    "upstream_type": _redact(upstream_type, limit=256),
                    "owasp": owasp,
                    "suggestion": _redact(str(item.get("suggestion") or ""), limit=8_192),
                    "conversation": redacted_turns,
                    "engine_tag": AIG_TAG,
                    "engine_commit": AIG_COMMIT,
                    "mapping_status": source_mapping,
                    "risk_taxonomy_mapping_status": (
                        "mapped" if finding_code != "unmapped" else "unmapped"
                    ),
                    "source_skill": source_skill or None,
                },
                "source": "ai_infra_guard",
                "confidence": 0.85 if finding_code != "unmapped" else 0.5,
            }
        )

    cases: list[dict[str, Any]] = []
    rule_statuses: list[str] = []
    if has_execution_evidence:
        for skill_name in skills:
            execution = executions_by_skill.get(skill_name)
            if not execution:
                execution = {
                    "skill_name": skill_name,
                    "stage_id": "",
                    "status": "missing",
                    "dialogue_calls": 0,
                    "candidate_finding_count": 0,
                    "error_type": None,
                    "error_message": None,
                }
            finding_count = confirmed_by_skill.get(skill_name, 0)
            execution_status = execution["status"]
            if finding_count:
                case_status = "failed"
            elif execution_status == "blocked":
                case_status = "blocked"
            elif execution_status == "error":
                case_status = "error"
            elif execution_status == "completed" and execution["dialogue_calls"] > 0:
                case_status = "passed"
            else:
                case_status = "unverified"
            rule_statuses.append(case_status)
            cases.append(
                {
                    "external_case_id": f"aig-rule:{skill_name}",
                    "category": "agent_detection_skill",
                    "title": skill_name,
                    "status": case_status,
                    "request_summary": {
                        "skill_name": skill_name,
                        "stage_id": execution["stage_id"],
                    },
                    "response_summary": {
                        "dialogue_calls": execution["dialogue_calls"],
                        "finding_count": finding_count,
                        "candidate_finding_count": execution["candidate_finding_count"],
                        "execution_status": execution_status,
                        "error_type": execution["error_type"],
                        "error_message": execution["error_message"],
                    },
                    "round_count": execution["dialogue_calls"],
                }
            )
    else:
        cases.append(
            {
                "external_case_id": "aig-rule:unverified-summary",
                "category": "agent_detection_skill",
                "title": "AI-Infra-Guard detection evidence unavailable",
                "status": "unverified",
                "request_summary": {"planned_skills": skills},
                "response_summary": {
                    "reason": "legacy_report_missing_detection_executions",
                    "finding_count": 0,
                },
                "round_count": 0,
            }
        )
        rule_statuses = ["unverified"] * len(skills)

    if unmapped_finding_count:
        cases.append(
            {
                "external_case_id": "aig-rule:unmapped",
                "category": "unmapped",
                "title": "Findings without verified detection-skill provenance",
                "status": "unverified",
                "request_summary": {},
                "response_summary": {
                    "finding_count": unmapped_finding_count,
                    "reason": "source_skill_unavailable",
                },
                "round_count": 0,
            }
        )

    coverage = {
        "planned_rules": len(skills),
        "executed_rules": sum(status in {"passed", "failed"} for status in rule_statuses),
        "passed_rules": rule_statuses.count("passed"),
        "failed_rules": rule_statuses.count("failed"),
        "error_rules": rule_statuses.count("error"),
        "blocked_rules": rule_statuses.count("blocked"),
        "unverified_rules": rule_statuses.count("unverified"),
    }
    artifact_report = dict(report)
    artifact_report["execution_evidence"] = {
        "transcript": transcript,
        "successful_calls": runtime.successful_target_calls,
        "failed_calls": runtime.failed_target_calls,
        "transcript_truncated": len(runtime.turns) > len(transcript),
    }
    raw_content = json.dumps(
        artifact_report,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    raw_bytes = raw_content.encode("utf-8")
    return {
        "status": "succeeded",
        "usage": runtime.snapshot(),
        "cases": cases,
        "findings": findings,
        "artifacts": [
            {
                "artifact_type": "aig-agent-scan-report",
                "uri": f"artifact://{task_id}/aig-agent-scan-report.json",
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "size_bytes": len(raw_bytes),
                "redacted": False,
                "metadata": {
                    "schema_version": report.get("schema_version", AIG_REPORT_SCHEMA),
                    "engine_tag": AIG_TAG,
                    "engine_commit": AIG_COMMIT,
                    "rules": skills,
                    "coverage": coverage,
                    "upstream_score_signal": report.get("score"),
                    "upstream_risk_type_signal": report.get("risk_type"),
                    "token_accounting": "character_estimate; gateway audit is authoritative when used",
                },
                "content": raw_content,
            }
        ],
        "session_state": runtime.session_id,
        "engine_name": AIG_ENGINE_NAME,
        "engine_version": f"{AIG_TAG}+{AIG_COMMIT[:12]}",
    }


def execute_agent_scan(
    claim: dict[str, Any],
    credential_secret: str | None,
    evaluator: EvaluatorConfig,
    heartbeat: Callable[[dict[str, int]], dict[str, Any]],
    *,
    initial_usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not evaluator.api_key or not evaluator.model or not evaluator.base_url:
        raise ValueError("agent scan evaluator API key, model, and base URL are required")
    target = claim["target"]
    policy = claim["policy"]
    options = claim.get("scan_options") or {}
    verify_worker_dns_pin(target)
    max_response_bytes = int(policy.get("max_response_bytes", 10 * 1024 * 1024))
    provider_document = build_provider_document(
        target,
        (claim.get("credential") or {}).get("credential_type"),
        credential_secret,
        max_response_bytes=max_response_bytes,
    )
    runtime = ScanRuntime(
        heartbeat,
        conversation_mode=str(options.get("conversation_mode", "single_turn")),
        initial_session_id=options.get("initial_session_id") if not options.get("reset_session", True) else None,
        input_cost_rate=evaluator.input_cost_microunits_per_million,
        output_cost_rate=evaluator.output_cost_microunits_per_million,
        initial_usage=initial_usage,
        target_check=lambda: verify_worker_dns_pin(target),
    )
    Agent, _Client, _Response, _Result, _LLM = _upstream_types()
    BoundedClient = _bounded_client_class(max_response_bytes)
    InstrumentedLLM = _instrumented_llm_class(runtime)
    import agent_scan.core.agent as agent_module
    from agent_scan.utils.tool_context import ToolContext

    original_call_provider = ToolContext.call_provider
    original_concurrency = agent_module._WORKER_CONCURRENCY

    def call_provider(context: Any, prompt: str) -> Any:
        return runtime.call_target(
            BoundedClient(timeout=max(1, int(target["config"].get("timeout_ms", 30_000)) // 1000)),
            context.agent_provider,
            prompt,
            stage_id=getattr(context, "stage_id", None),
        )

    provider_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(provider_document, handle, ensure_ascii=False)
            provider_path = Path(handle.name)
        ToolContext.call_provider = call_provider
        agent_module._WORKER_CONCURRENCY = max(1, min(4, int(policy.get("max_concurrent_requests", 1))))
        llm = InstrumentedLLM(model=evaluator.model, api_key=evaluator.api_key, base_url=evaluator.base_url)
        scanner = Agent(
            llm=llm,
            specialized_llms={"thinking": llm, "coding": llm},
            debug=False,
            language=str(options.get("language", "zh")),
            agent_provider=str(provider_path),
            skills=list(options.get("skills") or []),
        )
        report = asyncio.run(scanner.scan("", str(options.get("prompt", ""))))
        for execution in report.get("detection_executions") or []:
            stage_id = str(execution.get("stage_id") or "")
            execution["dialogue_calls"] = runtime.target_calls_by_stage.get(stage_id, 0)
        runtime.ensure_trustworthy_result()
        normalized = _normalize_report(
            report,
            runtime,
            task_id=claim["task"]["task_id"],
            skills=list(options.get("skills") or scanner.skills),
        )
        artifact_size = sum(int(item["size_bytes"]) for item in normalized["artifacts"])
        with runtime._state_lock:
            runtime.response_bytes += artifact_size
        runtime.check()
        normalized["usage"] = runtime.snapshot()
        return normalized
    finally:
        ToolContext.call_provider = original_call_provider
        agent_module._WORKER_CONCURRENCY = original_concurrency
        if provider_path:
            provider_path.unlink(missing_ok=True)
