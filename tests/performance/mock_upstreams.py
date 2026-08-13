#!/usr/bin/env python3
"""Deterministic OpenAI-compatible and MCP upstreams for gateway benchmarks."""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DELAY_SECONDS = max(0.0, float(os.environ.get("BENCH_UPSTREAM_DELAY_MS", "50")) / 1000.0)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok", "delay_ms": round(DELAY_SECONDS * 1000)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        time.sleep(DELAY_SECONDS)
        if self.path.rstrip("/") in {"/v1/chat/completions", "/chat/completions"}:
            self._json(
                200,
                {
                    "id": "chatcmpl-benchmark",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.get("model", "bench-model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "benchmark-ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
                },
            )
            return

        if self.path.rstrip("/") == "/mcp":
            request_id = body.get("id")
            method = body.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "benchmark-upstream", "version": "1.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Return the supplied text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                }
            elif method == "tools/call":
                arguments = (body.get("params") or {}).get("arguments") or {}
                result = {"content": [{"type": "text", "text": str(arguments.get("text", ""))}]}
            elif method == "notifications/initialized":
                self._json(202, {})
                return
            else:
                result = {}
            self._json(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
            return

        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 19090), Handler).serve_forever()
