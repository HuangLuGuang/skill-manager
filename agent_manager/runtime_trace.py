"""Minimal runtime-trace@1 client for external Agent runtimes.

The client intentionally uses only the Python standard library so an Agent can
emit lifecycle events without importing the backend package.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RuntimeTraceError(RuntimeError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class RuntimeTraceClient:
    schema_version = "runtime-trace@1"

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        tenant_id: str = "default",
        timeout: float = 10.0,
        best_effort: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.tenant_id = tenant_id
        self.timeout = timeout
        self.best_effort = best_effort
        self.trace_id: str | None = None
        self.session_id: str | None = None
        self._events: list[dict[str, Any]] = []

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            if self.best_effort:
                return {}
            raise RuntimeTraceError(f"runtime trace request failed: {type(exc).__name__}") from exc

    def create_trace(self, session_id: str, *, retention_days: int = 30) -> str:
        response = self._request(
            "POST",
            "/api/v1/runtime-traces",
            {
                "schema_version": self.schema_version,
                "session_id": session_id,
                "tenant_id": self.tenant_id,
                "retention_days": retention_days,
            },
        )
        self.trace_id = response.get("trace_id")
        self.session_id = session_id
        if not self.trace_id and not self.best_effort:
            raise RuntimeTraceError("runtime trace API returned no trace_id")
        return self.trace_id or ""

    def emit(
        self,
        event_type: str,
        *,
        source: str = "agent_sdk",
        turn_id: str | None = None,
        step_id: str | None = None,
        request_id: str | None = None,
        call_id: str | None = None,
        parent_call_id: str | None = None,
        status: str | None = None,
        tool_name: str | None = None,
        duration_ms: float | None = None,
        severity: str | None = None,
        risk_codes: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        redacted_payload: dict[str, Any] | None = None,
        flush: bool = False,
    ) -> str:
        event_id = _id("evt")
        event = {
            "schema_version": self.schema_version,
            "event_id": event_id,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "type": event_type,
            "turn_id": turn_id,
            "step_id": step_id,
            "request_id": request_id,
            "call_id": call_id,
            "parent_call_id": parent_call_id,
            "status": status,
            "tool_name": tool_name,
            "duration_ms": duration_ms,
            "severity": severity,
            "risk_codes": risk_codes or [],
            "payload": payload or {},
            "redacted_payload": redacted_payload,
        }
        self._events.append({key: value for key, value in event.items() if value is not None})
        if flush:
            self.flush()
        return event_id

    def flush(self) -> dict[str, Any]:
        if not self._events:
            return {"accepted_count": 0}
        if not self.trace_id:
            raise RuntimeTraceError("create_trace must be called before flush")
        events, self._events = self._events, []
        try:
            response = self._request(
                "POST",
                f"/api/v1/runtime-traces/{self.trace_id}/events:batch",
                {"schema_version": self.schema_version, "batch_id": _id("bat"), "events": events},
            )
        except Exception:
            self._events[0:0] = events
            raise
        if not response and self.best_effort:
            self._events[0:0] = events
        return response

    def turn_start(self, *, turn_id: str | None = None, payload: dict[str, Any] | None = None) -> str:
        turn_id = turn_id or _id("turn")
        self.emit("turn.start", turn_id=turn_id, status="running", payload=payload)
        return turn_id

    def turn_end(self, turn_id: str, *, status: str = "completed", duration_ms: float | None = None) -> str:
        return self.emit("turn.end", turn_id=turn_id, status=status, duration_ms=duration_ms)

    def step_start(self, turn_id: str, *, step_id: str | None = None, payload: dict[str, Any] | None = None) -> str:
        step_id = step_id or _id("step")
        self.emit("step.start", turn_id=turn_id, step_id=step_id, status="running", payload=payload)
        return step_id

    def step_end(self, turn_id: str, step_id: str, *, status: str = "completed", duration_ms: float | None = None) -> str:
        return self.emit("step.end", turn_id=turn_id, step_id=step_id, status=status, duration_ms=duration_ms)

    def user_message(self, turn_id: str, content: str) -> str:
        return self.emit("message.user", turn_id=turn_id, payload={"content": content})

    def tool_call(
        self,
        turn_id: str,
        step_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str | None = None,
        parent_call_id: str | None = None,
    ) -> str:
        call_id = call_id or _id("call")
        self.emit(
            "tool.call",
            turn_id=turn_id,
            step_id=step_id,
            call_id=call_id,
            parent_call_id=parent_call_id,
            tool_name=tool_name,
            status="running",
            payload={"arguments": arguments},
        )
        return call_id

    def tool_result(
        self,
        turn_id: str,
        step_id: str,
        call_id: str,
        tool_name: str,
        result: Any,
        *,
        duration_ms: float | None = None,
    ) -> str:
        return self.emit(
            "tool.result",
            turn_id=turn_id,
            step_id=step_id,
            call_id=call_id,
            tool_name=tool_name,
            status="completed",
            duration_ms=duration_ms,
            payload={"result": result},
        )

    def knowledge_retrieval(
        self,
        turn_id: str,
        step_id: str,
        *,
        knowledge_base: str,
        document_id: str,
        chunk_ids: list[str],
        redacted_summary: str,
        duration_ms: float | None = None,
    ) -> str:
        return self.emit(
            "knowledge.retrieval",
            turn_id=turn_id,
            step_id=step_id,
            source="knowledge_connector",
            duration_ms=duration_ms,
            payload={
                "knowledge_base": knowledge_base,
                "document_id": document_id,
                "chunk_ids": chunk_ids,
                "summary": redacted_summary,
            },
            redacted_payload={
                "knowledge_base": knowledge_base,
                "document_id": document_id,
                "chunk_ids": chunk_ids,
                "summary": redacted_summary,
            },
        )

    def gateway_metadata(
        self,
        *,
        turn_id: str | None = None,
        step_id: str | None = None,
        call_id: str | None = None,
        parent_call_id: str | None = None,
    ) -> dict[str, str]:
        """Correlation metadata to pass in OpenAI request metadata or MCP params._meta."""
        values = {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": turn_id,
            "step_id": step_id,
            "call_id": call_id,
            "parent_call_id": parent_call_id,
        }
        return {key: str(value) for key, value in values.items() if value}


class Timer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000
