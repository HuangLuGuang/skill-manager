"""Deterministic Streamable HTTP MCP server for the documentation scenario."""

from __future__ import annotations

import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response


app = FastAPI(title="Customer Operations MCP Demo", docs_url=None, redoc_url=None)
_lock = threading.Lock()
_initial_customers = {
    "CUST-1001": {
        "customer_id": "CUST-1001",
        "company": "Northwind Demo Manufacturing",
        "contact": "Demo User A",
        "email": "buyer@example.invalid",
        "service_status": "active",
        "plan": "enterprise-demo",
    },
    "CUST-1002": {
        "customer_id": "CUST-1002",
        "company": "Contoso Demo Retail",
        "contact": "Demo User B",
        "email": "ops@example.invalid",
        "service_status": "active",
        "plan": "standard-demo",
    },
}
_customers = deepcopy(_initial_customers)


TOOLS = [
    {
        "name": "customer_search",
        "description": "Search fictitious demo customers by ID, company, or contact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "customer_suspend",
        "description": "Suspend a fictitious customer's service after an approved change ticket.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "pattern": "^CUST-[0-9]{4}$"},
                "reason": {"type": "string", "minLength": 8, "maxLength": 200},
                "ticket_id": {"type": "string", "pattern": "^CHG-[0-9]{6}$"},
            },
            "required": ["customer_id", "reason", "ticket_id"],
            "additionalProperties": False,
        },
    },
]


def _check_authorization(value: str | None) -> None:
    expected = os.environ.get("MCP_DEMO_TOKEN", "mcp-demo-change-me")
    if value != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid demo MCP credential")


def _text_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _json_text(payload)}],
        "structuredContent": payload,
    }


def _json_text(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip().lower()
    if not query:
        raise ValueError("query is required")
    with _lock:
        matches = [
            deepcopy(customer)
            for customer in _customers.values()
            if query in " ".join(str(value).lower() for value in customer.values())
        ]
    return {"count": len(matches), "customers": matches, "data_classification": "fictitious-demo-data"}


def _suspend(arguments: dict[str, Any]) -> dict[str, Any]:
    customer_id = str(arguments.get("customer_id") or "").strip()
    reason = str(arguments.get("reason") or "").strip()
    ticket_id = str(arguments.get("ticket_id") or "").strip()
    if customer_id not in _customers:
        raise ValueError("customer does not exist")
    if len(reason) < 8:
        raise ValueError("reason must contain at least 8 characters")
    if not ticket_id.startswith("CHG-") or len(ticket_id) != 10:
        raise ValueError("ticket_id must use CHG-000000 format")
    with _lock:
        customer = _customers[customer_id]
        previous_status = customer["service_status"]
        customer["service_status"] = "suspended"
        customer["last_change_ticket"] = ticket_id
        customer["last_change_reason"] = reason
        customer["changed_at"] = datetime.now(timezone.utc).isoformat()
        result = deepcopy(customer)
    return {
        "changed": previous_status != "suspended",
        "previous_status": previous_status,
        "customer": result,
        "data_classification": "fictitious-demo-data",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(payload: dict[str, Any], authorization: str | None = Header(None)):
    _check_authorization(authorization)
    request_id = payload.get("id")
    method = payload.get("method")
    if payload.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}}
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        requested = (payload.get("params") or {}).get("protocolVersion")
        version = requested if requested in {"2025-11-25", "2025-06-18", "2025-03-26"} else "2025-11-25"
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "customer-operations-demo", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            if name == "customer_search":
                result = _text_result(_search(arguments))
            elif name == "customer_suspend":
                result = _text_result(_suspend(arguments))
            else:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Tool not found"}}
        except ValueError as exc:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8091)
