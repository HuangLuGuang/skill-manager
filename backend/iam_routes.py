"""Map existing management endpoints to stable operation permissions.

Runtime credential routes retain their own scope validation. These rules apply
to management JWT authentication after FastAPI has selected an endpoint.
"""


def route_permission(request):
    path = getattr(request.scope.get("route"), "path", request.url.path)
    method = request.method
    if path == "/api/v1/clients/{client_id}/diagnostics/logs":
        return "clients:diagnostics"
    if path == "/api/v1/dify-runtime/bindings":
        return "agents:view" if method == "GET" else "agents:update"
    if path.startswith("/api/v1/dify-runtime/") and path.endswith("/review"):
        return "runtime:execute"
    if path in {"/api/v1/access/tokens/privacy-policies", "/api/v1/access/tokens/device-users"} and method == "GET":
        return None  # Each options endpoint checks its permitted credential operations.
    if path.startswith("/api/v1/prompt-guard/rules"):
        return "privacy:test" if method == "GET" else "privacy:update"
    if path == "/api/v1/prompt-guard/config":
        return "privacy:test" if method == "GET" else "privacy:update"
    if path == "/api/v1/prompt-guard/model-test":
        return "privacy:update"
    if method == "POST" and path == "/api/v1/external-access/deliveries/{delivery_id}/retry":
        return "external_access:update"
    if method == "POST" and path in {"/api/v1/external-access/callbacks/{callback_id:path}/test",
                                    "/api/v1/external-access/gateways/{gateway_id:path}/test"}:
        return "external_access:update"
    if path.startswith("/api/v1/license/"):
        return None if method == "GET" else "license:update"
    if path.startswith("/api/v1/iam/") or path.startswith("/api/auth/"):
        return None
    if path in {"/api/system/capabilities", "/api/system/logo", "/api/system/branding"} and method == "GET":
        return None
    if path == "/api/system/logo" and method in {"POST", "DELETE"}:
        return "settings:update"
    if path == "/api/v1/policy/simulate" and method == "POST":
        return "policy:view"
    if path == "/api/v1/privacy-policies" and method == "POST":
        return None  # The upsert checks create/update after resolving the target row.
    if path == "/api/config/docs-assistant/ask" and method == "POST":
        return "docs:view"
    if path == "/api/config/docs-assistant" and method == "GET":
        return None  # Configuration readers and editors are checked by the handler.
    if method == "POST" and path in {
        "/api/v1/clients/{client_id}/aidr/hook-policy/preview",
        "/api/v1/clients/{client_id}/aidr/enforcement/policy/preview",
        "/api/v1/clients/{client_id}/aidr/risks/commands/test",
    }:
        return "clients:view"
    if method == "POST" and path in {"/api/v1/clients/{client_id}/aidr/enforcement/policy", "/api/v1/clients/{client_id}/aidr/enforcement/collection", "/api/v1/clients/{client_id}/aidr/enforcement/collection/rediscover"}:
        return "clients:update"
    if method == "POST" and path == "/api/v1/clients/{client_id}/aidr/enforcement/terminate":
        return "clients:execute"
    if method == "POST" and path == "/api/v1/clients/{client_id}/aidr/hook-approvals/{approval_id}/decision":
        return "clients:execute"
    if method == "GET" and path.startswith("/api/v1/agent-security/tasks/"):
        if path.endswith("/mcp-calls") or ("/inventory/items/" in path and path.endswith("/content")):
            return "privacy_audit:raw"
        if "/artifacts/" in path and path.endswith("/content"):
            return "scans:raw"
    if method == "DELETE" and path.startswith(("/api/v1/privacy/mappings", "/api/v1/privacy/conversations")):
        return "privacy:delete"
    rules = [
        ("/api/v1/external-access", "external_access", None),
        ("/api/v1/security-audit/verify", "audit", "verify"),
        ("/api/v1/security-audit", "audit", "security"),
        ("/api/v1/privacy/traces", "privacy_audit", "raw"),
        ("/api/v1/privacy/mappings", "privacy_audit", "raw"),
        ("/api/v1/privacy/conversations", "privacy_audit", "raw"),
        ("/api/v1/privacy/stats", "privacy_audit", "view"),
        ("/api/v1/llm-stats", "privacy_audit", "view"),
        ("/api/v1/model-gateway/skill-alerts", "privacy", "view"),
        ("/api/v1/external-ai-gateways", "external_gateways", None),
        ("/api/v1/model-providers", "providers", None),
        ("/api/v1/models", "models", None),
        ("/api/v1/privacy-policies", "privacy", None),
        ("/api/v1/prompt-guard", "privacy", "test"),
        ("/api/v1/users", "users", None),
        ("/api/v1/groups", "groups", None),
        ("/api/v1/access/tokens", "credentials", None),
        ("/api/v1/llm-api-keys", "credentials", None),
        ("/api/v1/scanner-tokens", "credentials", None),
        ("/api/v1/scanner", "credentials", None),
        ("/api/v1/agent-security/schedules", "schedules", None),
        ("/api/v1/agent-security/scan-schedules", "schedules", None),
        ("/api/v1/agent-security/targets", "targets", None),
        ("/api/v1/agent-security/asset-sources", "targets", None),
        ("/api/v1/agent-security/asset-sync-runs", "targets", None),
        ("/api/v1/agent-security/managed-agents", "targets", None),
        ("/api/v1/agent-security", "scans", None),
        ("/api/v1/runtime-traces", "traces", None),
        ("/api/v1/runtime-governance", "runtime", None),
        ("/api/v1/dify-runtime", "runtime", None),
        ("/api/v1/mcp", "mcp", None),
        ("/api/agents", "agents", None),
        ("/api/clients", "clients", None),
        ("/api/v1/clients", "clients", None),
        ("/api/v1/policy", "policy", None),
        ("/api/v1/llm-config", "settings", None),
        ("/api/v1/sandbox-config", "settings", None),
        ("/api/v1/sandbox-images", "settings", "view"),
        ("/api/v1/system", "settings", None),
        ("/api/v1/skills", "skills", None),
        ("/api/v1/deployments", "skills", "deploy"),
        ("/api/v1/review", "skills", None),
        ("/api/v1/audit", "skills", "view"),
        ("/api/v1/audit-trail", "skills", "view"),
        ("/api/v1/dashboard", "dashboard", "view"),
        ("/api/config/docs-assistant", "docs", None),
        ("/api/config", "settings", None),
        ("/api/tasks", "tasks", None),
        ("/api/system", "settings", None),
    ]
    for prefix, module, fixed in rules:
        if path != prefix and not path.startswith(prefix + "/"):
            continue
        if fixed:
            return f"{module}:{fixed}"
        action = {"GET": "view", "HEAD": "view", "POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}.get(method, "view")
        tail = path.rsplit("/", 1)[-1]
        if module == "traces":
            action = "raw" if "raw" in path else ("delete" if method == "DELETE" or "cleanup" in path else "view")
        elif method == "POST":
            if tail == "reveal" and module == "external_gateways":
                action = "reveal"
            elif tail in {"test", "connection-tests"}:
                action = "test" if module in {"providers", "models", "privacy", "external_gateways"} else "execute" if module == "scans" else "sync"
            elif tail in {"approve", "reject", "deploy", "sign"}:
                action = tail
            elif tail in {"rescan", "scan", "scan-batch", "rescan-batch"} and module == "skills":
                action = "scan"
            elif tail in {"cancel", "stop", "kill", "emergency-stop", "kill-switch"}:
                action = "stop" if module == "scans" and tail != "cancel" else "cancel" if module == "scans" else "sync" if module == "targets" else "update" if module == "skills" else "execute"
            elif tail in {"run", "execute", "retry", "start", "runs"} or (module == "clients" and tail == "tasks"):
                action = "execute"
            elif "sync-runs" in path:
                action = "sync"
            elif tail in {"revoke", "rotate"}:
                action = "update"
            elif tail in {"preview", "test-connectivity", "compare"}:
                action = "view"
            elif module == "scans" and tail == "tasks":
                action = "execute"
            elif module == "scans" and tail == "scan-approvals":
                action = "approve"
            elif module == "scans" and tail == "export":
                action = "view"
            elif module == "skills" and tail == "verify-signature":
                action = "sign"
            elif module == "skills" and tail in {"retire", "refresh"}:
                action = "update"
            elif module == "mcp" and (tail in {"discover", "upstream"}):
                action = "execute"
            elif module == "mcp" and tail == "approvals":
                action = "approve"
        if module in {"settings", "docs", "policy"} and action != "view":
            action = "update"
        return f"{module}:{action}"
    return None
