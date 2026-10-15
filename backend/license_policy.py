"""Operation boundaries: reads/exports and existing protection survive expiry."""
import re

from fastapi import Request

from agent_manager.core.licensing import LicenseError, require_license
from .api_errors import ApiError, api_error_handler


async def license_error_handler(request, exc):
    return await api_error_handler(request, ApiError(403, exc.code, exc.zh, exc.en, params=exc.params))


def requirement(method, path):
    if path.startswith("/mcp/"):
        return ("mcp_gateway", True)
    path = re.sub(r"^/api(?:/v1)?(?=/)", "", path)
    # Runtime data plane and protection control plane keep their signed module entitlement.
    if path.startswith(("/v1/", "/v1beta/", "/client-models/", "/runtime/external-model/")) or path in {"/chat/completions", "/responses", "/messages", "/llm/chat/completions"} or (path == "/" and method == "POST"):
        return ("model_gateway", True)
    if path.startswith(("/runtime/", "/access/runtime/", "/hook/")):
        return ("skill_governance", True)
    if "/aidr/" in path or path.startswith(("/aidr/", "/runtime-governance/")):
        if method in {"POST", "PUT", "PATCH"} or path.endswith(("/policy", "/snapshot", "/bootstrap", "/commands")):
            return ("aidr", True)
        return None
    if method in {"GET", "HEAD", "OPTIONS", "DELETE"}:
        return None
    if method == "POST" and path in {"/iam/users", "/tasks"}:
        return (None, False)
    if path.startswith(("/license", "/auth/", "/system/", "/config/", "/iam/")):
        return None
    if path.startswith("/agent-security/worker/"):
        # Worker lease/heartbeat/completion handlers enforce execution and preserve reports.
        return None
    if path.endswith(("/export", "/exports", "/raw-authorization", "/verify-signature", "/compare", "/cancel", "/stop", "/kill", "/emergency-stop", "/kill-switch", "/reject", "/revoke")):
        return None
    if path.startswith(("/runtime-traces/", "/security-audit/")):
        return None
    if path.startswith("/clients/"):
        if method in {"PUT", "POST"} and ("/governance" in path or path.endswith("/policy")):
            return ("skill_governance", True)
        # Register and task payloads require record-aware decisions in their handlers.
        return None
    if path.startswith("/agent-security/"):
        return ("security_scanning", False)
    if path.startswith(("/skills/", "/prompts/")):
        if any(x in path for x in ("submit", "rescan", "prepare", "confirm-upload")):
            return ("security_scanning", False)
        return ("skill_governance", False)
    if path == "/scanner/imports":
        return ("security_scanning", False)
    if path.startswith("/mcp/"):
        existing = method in {"PUT", "PATCH"} or "/approval" in path
        return ("mcp_gateway", existing)
    if path.startswith(("/model-providers", "/models", "/llm-api-keys", "/privacy-policies", "/prompt-guard", "/external-ai-gateways")):
        return ("model_gateway", method in {"PUT", "PATCH"} or path == "/privacy-policies")
    if path.startswith(("/agents", "/access/tokens", "/scanner/tokens", "/users", "/groups")):
        return (None, False) if method == "POST" else None
    return None


def enforce_license_request(request: Request):
    needed = requirement(request.method, request.url.path)
    if needed:
        feature, runtime = needed
        require_license(feature, runtime=runtime)
