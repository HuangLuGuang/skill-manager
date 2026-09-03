"""Small ASGI request-body guards for internal high-volume endpoints."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any


class WorkerCompletionBodyLimitMiddleware:
    def __init__(self, app: Any, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]):
        path = str(scope.get("path", ""))
        if not (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and path.startswith("/api/v1/agent-security/worker/tasks/")
            and path.endswith("/complete")
        ):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared = headers.get(b"content-length")
        if declared:
            try:
                if int(declared) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        messages: list[dict] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        index = 0

        async def replay_receive() -> dict:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: dict, receive, send) -> None:
        payload = json.dumps(
            {
                "detail": "Worker completion request body exceeds 16 MiB",
                "error_code": "agent_security.worker_completion_body_too_large",
                "error_params": {"max_bytes": self.max_bytes},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": payload})
