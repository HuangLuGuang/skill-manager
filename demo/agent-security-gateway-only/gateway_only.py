#!/usr/bin/env python3
"""Gateway-only Runtime Trace demo; it never emits Agent SDK Turn/Step events."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class DemoError(RuntimeError):
    """A safe, user-actionable error that excludes credentials and response bodies."""


GatewayMode = Literal["model", "mcp", "combined"]
EXPECTED_COMPLETENESS = {
    "model": "model_only",
    "mcp": "mcp_only",
    "combined": "gateway_partial",
}


@dataclass(frozen=True)
class DemoConfig:
    base_url: str
    gateway_token: str
    mode: GatewayMode
    model: str | None = None
    mcp_gateway: str | None = None
    mcp_tool: str | None = None
    mcp_arguments: dict[str, Any] | None = None
    trace_read_token: str | None = None
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> DemoConfig:
        token = os.environ.get("AGENT_RUNTIME_TOKEN")
        if not token:
            raise DemoError("missing required environment variable: AGENT_RUNTIME_TOKEN")
        mode = os.environ.get("AGENT_MANAGER_GATEWAY_ONLY_MODE", "combined").lower()
        if mode not in EXPECTED_COMPLETENESS:
            raise DemoError("AGENT_MANAGER_GATEWAY_ONLY_MODE must be model, mcp, or combined")
        model = os.environ.get("AGENT_MANAGER_MODEL")
        mcp_gateway = os.environ.get("AGENT_MANAGER_MCP_GATEWAY")
        mcp_tool = os.environ.get("AGENT_MANAGER_MCP_TOOL")
        if mode in {"model", "combined"} and not model:
            raise DemoError("AGENT_MANAGER_MODEL is required for model and combined modes")
        if mode in {"mcp", "combined"} and (not mcp_gateway or not mcp_tool):
            raise DemoError("AGENT_MANAGER_MCP_GATEWAY and AGENT_MANAGER_MCP_TOOL are required for MCP modes")
        try:
            arguments = json.loads(os.environ.get("AGENT_MANAGER_MCP_ARGUMENTS", "{}"))
        except json.JSONDecodeError as exc:
            raise DemoError("AGENT_MANAGER_MCP_ARGUMENTS must be a JSON object") from exc
        if not isinstance(arguments, dict):
            raise DemoError("AGENT_MANAGER_MCP_ARGUMENTS must be a JSON object")
        return cls(
            base_url=os.environ.get("AGENT_MANAGER_URL", "http://127.0.0.1:8000").rstrip("/"),
            gateway_token=token,
            mode=mode,
            model=model,
            mcp_gateway=mcp_gateway,
            mcp_tool=mcp_tool,
            mcp_arguments=arguments,
            trace_read_token=os.environ.get("AGENT_MANAGER_TRACE_READ_TOKEN") or None,
            timeout_seconds=float(os.environ.get("AGENT_MANAGER_TIMEOUT_SECONDS", "60")),
        )


def _request_json(
    config: DemoConfig,
    method: str,
    path: str,
    *,
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = Request(
        f"{config.base_url}{path}",
        method=method,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DemoError(f"{method} {path} failed with HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DemoError(f"{method} {path} failed: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise DemoError(f"{method} {path} returned a non-object JSON response")
    return value


def _verify_gateway_only_trace(config: DemoConfig, trace_id: str, expected: str) -> dict[str, Any]:
    if not config.trace_read_token:
        return {
            "verification": "not_requested",
            "expected_completeness": expected,
            "actual_completeness": None,
            "event_count": None,
        }
    detail = _request_json(
        config,
        "GET",
        f"/api/v1/runtime-traces/{quote(trace_id, safe='')}",
        token=config.trace_read_token,
    )
    events_response = _request_json(
        config,
        "GET",
        f"/api/v1/runtime-traces/{quote(trace_id, safe='')}/events?limit=200",
        token=config.trace_read_token,
    )
    events = events_response.get("items")
    if not isinstance(events, list):
        raise DemoError("runtime trace event query returned no items list")
    actual = detail.get("completeness")
    if actual != expected:
        raise DemoError(f"unexpected trace completeness: expected {expected}, got {actual}")
    if not events:
        raise DemoError("gateway-only trace contains no events")
    if any(item.get("source") == "agent_sdk" for item in events if isinstance(item, dict)):
        raise DemoError("gateway-only trace unexpectedly contains agent_sdk events")
    if any(
        item.get("turn_id") is not None or item.get("step_id") is not None
        for item in events
        if isinstance(item, dict)
    ):
        raise DemoError("gateway-only trace contains fabricated Turn/Step identifiers")
    sources = sorted({str(item.get("source")) for item in events if isinstance(item, dict)})
    expected_sources = {
        "model_only": {"model_gateway"},
        "mcp_only": {"mcp_gateway"},
        "gateway_partial": {"model_gateway", "mcp_gateway"},
    }[expected]
    if not expected_sources <= set(sources):
        raise DemoError(f"gateway-only trace is missing expected sources: {sorted(expected_sources - set(sources))}")
    return {
        "verification": "passed",
        "expected_completeness": expected,
        "actual_completeness": actual,
        "event_count": len(events),
        "sources": sources,
        "turn_step_absent": True,
    }


def run_demo(config: DemoConfig) -> dict[str, Any]:
    trace_id = f"trc_gateway_demo_{uuid.uuid4().hex}"
    session_id = f"gateway-demo-{uuid.uuid4().hex[:12]}"
    model_status = "not_requested"
    mcp_status = "not_requested"

    if config.mode in {"model", "combined"}:
        _request_json(
            config,
            "POST",
            "/v1/chat/completions",
            token=config.gateway_token,
            body={
                "model": config.model,
                "messages": [{"role": "user", "content": "请返回一句健康检查结果"}],
                "metadata": {
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "content_sources": ["user"],
                },
            },
        )
        model_status = "completed"

    if config.mode in {"mcp", "combined"}:
        call_id = f"call_gateway_demo_{uuid.uuid4().hex}"
        response = _request_json(
            config,
            "POST",
            f"/mcp/{quote(str(config.mcp_gateway), safe='')}",
            token=config.gateway_token,
            body={
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {
                    "name": config.mcp_tool,
                    "arguments": config.mcp_arguments or {},
                    "_meta": {"trace_id": trace_id, "session_id": session_id, "call_id": call_id},
                },
            },
        )
        error = response.get("error") if isinstance(response.get("error"), dict) else None
        mcp_status = "approval_pending" if error and error.get("code") == -32002 else ("error" if error else "completed")

    expected = EXPECTED_COMPLETENESS[config.mode]
    verification = _verify_gateway_only_trace(config, trace_id, expected)
    return {
        "status": "verified" if verification["verification"] == "passed" else "submitted_unverified",
        "mode": config.mode,
        "trace_id": trace_id,
        "session_id": session_id,
        "model_status": model_status,
        "mcp_status": mcp_status,
        **verification,
    }


def main() -> None:
    print(json.dumps(run_demo(DemoConfig.from_env()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
