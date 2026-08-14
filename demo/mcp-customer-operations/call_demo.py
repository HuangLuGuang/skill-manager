"""Small MCP gateway caller used by the documentation scenario."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def post(url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Call the Customer Operations MCP scenario through Agent Manager")
    parser.add_argument("action", choices=["list", "search", "suspend"])
    parser.add_argument("--base-url", default=os.getenv("AGENT_MANAGER_BASE_URL", "http://127.0.0.1"))
    parser.add_argument("--token", default=os.getenv("MCP_GATEWAY_TOKEN"))
    parser.add_argument("--gateway-slug", default=os.getenv("MCP_DEMO_GATEWAY_SLUG", "customer-ops"))
    parser.add_argument("--server-slug", default=os.getenv("MCP_DEMO_SERVER_SLUG", "customer-ops"))
    parser.add_argument("--query", default="CUST-1001")
    parser.add_argument("--customer-id", default="CUST-1001")
    parser.add_argument("--reason", default="Customer requested temporary service suspension")
    parser.add_argument("--ticket-id", default="CHG-000123")
    parser.add_argument("--approval-request-id")
    args = parser.parse_args()
    if not args.token:
        parser.error("set MCP_GATEWAY_TOKEN or pass --token")
    endpoint = f"{args.base_url.rstrip('/')}/mcp/{args.gateway_slug}"
    if args.action == "list":
        method, params = "tools/list", {}
    elif args.action == "search":
        method = "tools/call"
        params = {"name": f"{args.server_slug}__customer_search", "arguments": {"query": args.query}}
    else:
        method = "tools/call"
        params = {
            "name": f"{args.server_slug}__customer_suspend",
            "arguments": {"customer_id": args.customer_id, "reason": args.reason, "ticket_id": args.ticket_id},
        }
        if args.approval_request_id:
            params["_meta"] = {"agent_manager_approval_request": args.approval_request_id}
    result = post(endpoint, args.token, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    error = result.get("error") or {}
    if error.get("data", {}).get("approval_required"):
        print("The Tool was not executed. Review the request in MCP Governance > Call Approvals.", file=sys.stderr)
        return 3
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
