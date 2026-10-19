"""Response adapters for the agreed external API contract."""
from fastapi.responses import JSONResponse


def is_openapi(request):
    return request.url.path.startswith("/openapi/v1/")


def success(request, data):
    return {"request_id": request.state.request_id, "data": data}


def error_response(request, status, code, message, *, details=None, headers=None):
    if code in {"credential.invalid_or_disabled", "credential.expired", "credential.missing"}:
        status = 401
    elif code in {"agent_security.production_active_safe_approval_required", "agent_security.production_active_safe_approval_invalid",
                  "agent_security.target_disabled", "agent_security.policy_disabled", "agent_security.credential_revoked",
                  "agent_security.active_scan_forbidden_by_policy"}:
        status = 403
    public_codes = {"INVALID_ARGUMENT", "UNAUTHORIZED", "FORBIDDEN", "RESOURCE_NOT_FOUND",
                    "RESULT_NOT_READY", "REPORT_UNAVAILABLE", "PAYLOAD_TOO_LARGE", "RATE_LIMITED", "SERVICE_UNAVAILABLE",
                    "AGENT_ALREADY_EXISTS", "TARGET_REVISION_CONFLICT", "CONNECTION_TEST_REQUIRED"}
    public_code = code if code in public_codes else {
        400: "INVALID_ARGUMENT", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "RESOURCE_NOT_FOUND", 405: "INVALID_ARGUMENT",
        413: "PAYLOAD_TOO_LARGE", 422: "INVALID_ARGUMENT", 429: "RATE_LIMITED",
    }.get(status, "SERVICE_UNAVAILABLE")
    if public_code == "SERVICE_UNAVAILABLE":
        status = 503
    if status == 429 and not any(key.lower() == "retry-after" for key in (headers or {})):
        headers = {**(headers or {}), "Retry-After": "5"}
    request.state.external_error_code = code
    error = {"code": public_code, "message": message, "retryable": public_code in {"RESULT_NOT_READY", "RATE_LIMITED", "SERVICE_UNAVAILABLE"}}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status, headers=headers,
                        content={"request_id": request.state.request_id, "error": error})
