#!/usr/bin/env python3
"""End-to-end Agent Manager correlation demo using only the Python standard library."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent_manager.runtime_trace import RuntimeTraceClient, Timer


class DemoError(RuntimeError):
    """A user-actionable demo failure without response bodies or credentials."""


@dataclass(frozen=True)
class DemoConfig:
    base_url: str
    token: str
    model: str
    mcp_gateway: str
    mcp_tool: str
    mcp_arguments: dict[str, Any]
    mcp_approval_request: str | None = None
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> DemoConfig:
        required = {
            "AGENT_RUNTIME_TOKEN": os.environ.get("AGENT_RUNTIME_TOKEN"),
            "AGENT_MANAGER_MODEL": os.environ.get("AGENT_MANAGER_MODEL"),
            "AGENT_MANAGER_MCP_GATEWAY": os.environ.get("AGENT_MANAGER_MCP_GATEWAY"),
            "AGENT_MANAGER_MCP_TOOL": os.environ.get("AGENT_MANAGER_MCP_TOOL"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise DemoError(f"missing required environment variables: {', '.join(missing)}")
        try:
            arguments = json.loads(os.environ.get("AGENT_MANAGER_MCP_ARGUMENTS", "{}"))
        except json.JSONDecodeError as exc:
            raise DemoError("AGENT_MANAGER_MCP_ARGUMENTS must be a JSON object") from exc
        if not isinstance(arguments, dict):
            raise DemoError("AGENT_MANAGER_MCP_ARGUMENTS must be a JSON object")
        return cls(
            base_url=os.environ.get("AGENT_MANAGER_URL", "http://127.0.0.1:8000").rstrip("/"),
            token=str(required["AGENT_RUNTIME_TOKEN"]),
            model=str(required["AGENT_MANAGER_MODEL"]),
            mcp_gateway=str(required["AGENT_MANAGER_MCP_GATEWAY"]),
            mcp_tool=str(required["AGENT_MANAGER_MCP_TOOL"]),
            mcp_arguments=arguments,
            mcp_approval_request=os.environ.get("AGENT_MANAGER_MCP_APPROVAL_REQUEST") or None,
            timeout_seconds=float(os.environ.get("AGENT_MANAGER_TIMEOUT_SECONDS", "60")),
        )


def _post_json(config: DemoConfig, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{config.base_url}{path}",
        method="POST",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {config.token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DemoError(f"POST {path} failed with HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DemoError(f"POST {path} failed: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise DemoError(f"POST {path} returned a non-object JSON response")
    return value


def _assistant_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    return str(message.get("content") or "") if isinstance(message, dict) else ""


def run_demo(config: DemoConfig) -> dict[str, Any]:
    session_id = f"full-demo-{uuid.uuid4().hex[:12]}"
    trace = RuntimeTraceClient(config.base_url, config.token, timeout=config.timeout_seconds)
    trace_id = trace.create_trace(session_id)
    turn_id = trace.turn_start(payload={"goal": "retrieve, reason, and call governed tools"})
    trace.user_message(turn_id, "请检索智能体安全制度，调用已授权工具，并给出简要结论")

    retrieval_step = trace.step_start(turn_id, payload={"name": "knowledge-retrieval"})
    trace.knowledge_retrieval(
        turn_id,
        retrieval_step,
        knowledge_base="agent-security-policy",
        document_id="policy-demo-2026",
        chunk_ids=["chunk-redacted-7", "chunk-redacted-8"],
        redacted_summary="命中两段已脱敏的智能体安全制度摘要",
    )
    trace.step_end(turn_id, retrieval_step)

    reasoning_step = trace.step_start(turn_id, payload={"name": "model-reasoning"})
    model_call_id = f"call_model_{uuid.uuid4().hex}"
    model_metadata = trace.gateway_metadata(
        turn_id=turn_id,
        step_id=reasoning_step,
        call_id=model_call_id,
    )
    model_response = _post_json(
        config,
        "/v1/chat/completions",
        {
            "model": config.model,
            "messages": [{"role": "user", "content": "基于已检索制度给出一句脱敏摘要"}],
            "metadata": {**model_metadata, "content_sources": ["rag"]},
        },
    )
    assistant_text = _assistant_text(model_response)
    trace.emit(
        "message.assistant",
        turn_id=turn_id,
        step_id=reasoning_step,
        call_id=model_call_id,
        status="completed",
        payload={"content": assistant_text},
        redacted_payload={"content": "[MODEL_OUTPUT_REDACTED]", "content_length": len(assistant_text)},
    )
    trace.step_end(turn_id, reasoning_step)

    local_step = trace.step_start(turn_id, payload={"name": "local-tool"})
    local_timer = Timer()
    local_call_id = trace.tool_call(turn_id, local_step, "local_policy_cache", {"key": "policy-demo"})
    trace.tool_result(
        turn_id,
        local_step,
        local_call_id,
        "local_policy_cache",
        {"found": True, "classification": "internal"},
        duration_ms=local_timer.duration_ms,
    )
    trace.step_end(turn_id, local_step)

    mcp_step = trace.step_start(turn_id, payload={"name": "mcp-tool"})
    mcp_call_id = f"call_mcp_{uuid.uuid4().hex}"
    trace.tool_call(
        turn_id,
        mcp_step,
        config.mcp_tool,
        config.mcp_arguments,
        call_id=mcp_call_id,
    )
    first_flush = trace.flush()
    mcp_metadata = trace.gateway_metadata(
        turn_id=turn_id,
        step_id=mcp_step,
        call_id=mcp_call_id,
    )
    if config.mcp_approval_request:
        mcp_metadata["agent_manager_approval_request"] = config.mcp_approval_request
    mcp_response = _post_json(
        config,
        f"/mcp/{config.mcp_gateway}",
        {
            "jsonrpc": "2.0",
            "id": mcp_call_id,
            "method": "tools/call",
            "params": {
                "name": config.mcp_tool,
                "arguments": config.mcp_arguments,
                "_meta": mcp_metadata,
            },
        },
    )
    if isinstance(mcp_response.get("error"), dict):
        error = mcp_response["error"]
        data = error.get("data") if isinstance(error.get("data"), dict) else {}
        approval_request_id = data.get("approval_request_id") or data.get("request_id")
        trace.emit(
            "tool.error",
            turn_id=turn_id,
            step_id=mcp_step,
            call_id=mcp_call_id,
            tool_name=config.mcp_tool,
            status="blocked" if error.get("code") == -32002 else "error",
            payload={"error_code": error.get("code"), "approval_request_id": approval_request_id},
        )
        trace.step_end(turn_id, mcp_step, status="blocked" if error.get("code") == -32002 else "error")
        trace.turn_end(turn_id, status="blocked" if error.get("code") == -32002 else "error")
        flush_result = trace.flush()
        return {
            "status": "approval_pending" if error.get("code") == -32002 else "mcp_error",
            "trace_id": trace_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "mcp_call_id": mcp_call_id,
            "approval_request_id": approval_request_id,
            "accepted_count": first_flush.get("accepted_count", 0) + flush_result.get("accepted_count", 0),
        }

    trace.tool_result(
        turn_id,
        mcp_step,
        mcp_call_id,
        config.mcp_tool,
        {"jsonrpc_result_received": "result" in mcp_response},
    )
    trace.step_end(turn_id, mcp_step)
    trace.turn_end(turn_id)
    flush_result = trace.flush()
    return {
        "status": "completed",
        "trace_id": trace_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "model_call_id": model_call_id,
        "local_call_id": local_call_id,
        "mcp_call_id": mcp_call_id,
        "accepted_count": first_flush.get("accepted_count", 0) + flush_result.get("accepted_count", 0),
    }


def main() -> None:
    print(json.dumps(run_demo(DemoConfig.from_env()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
