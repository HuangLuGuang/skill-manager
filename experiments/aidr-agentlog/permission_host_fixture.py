"""Bounded stdio MCP permission host for one owned native acceptance run.

Always denies; never executes or persists supplied arguments or credentials.
"""
import json
from pathlib import Path
import sys


def serve(destination):
    calls = 0
    for _ in range(32):
        raw = sys.stdin.buffer.readline(16385)
        if not raw:
            break
        if len(raw) > 16384:
            raise ValueError("permission_fixture_input_budget")
        message = json.loads(raw)
        method = message.get("method")
        if "id" not in message:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "aidr-owned-permission-deny", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "deny", "description": "Deny the permission request for this isolated test.",
                "inputSchema": {"type": "object", "properties": {"tool_name": {"type": "string"},
                    "input": {"type": "object"}, "tool_use_id": {"type": "string"}}, "required": ["tool_name", "input"]}}]}
        elif method == "tools/call" and message.get("params", {}).get("name") == "deny":
            calls += 1
            if calls > 4:
                raise ValueError("permission_fixture_call_budget")
            arguments = message["params"].get("arguments", {})
            destination.write_text(json.dumps({"calls": calls, "requested_bash": arguments.get("tool_name") == "Bash",
                                               "decision": "deny"}))
            result = {"content": [{"type": "text", "text": json.dumps({"behavior": "deny",
                "message": "Isolated acceptance permission host denied this request.", "interrupt": False})}]}
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Unsupported test method"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
