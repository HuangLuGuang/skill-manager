"""Record failed management operations without logging request bodies."""
import uuid

from . import iam
from .iam_routes import route_permission
from .sqlite_db import SessionLocal


async def management_audit_middleware(request, call_next):
    if not getattr(request.state, "request_id", None):
        request.state.request_id = str(uuid.uuid4())
    try:
        response = await call_next(request)
    except Exception:
        record_management_audit(request, 500)
        raise
    response.headers["X-Request-ID"] = request.state.request_id
    record_management_audit(request, response.status_code)
    return response


def record_management_audit(request, status_code):
    path = request.url.path
    is_management = path.startswith("/api/v1/iam/") or path == "/api/auth/users/me/password" or bool(getattr(request.state, "iam_permission", None))
    mutation = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    denied = status_code >= 400
    permission = getattr(request.state, "iam_permission", None)
    sensitive_read = request.method == "GET" and ("/audit/" in path or bool(permission and permission.endswith(":raw")))
    if is_management and (denied or sensitive_read or mutation) and (not getattr(request.state, "iam_audited", False) or denied):
        permission = getattr(request.state, "iam_permission", None) or route_permission(request)
        if permission:
            module, action = permission.split(":", 1)
        elif path.startswith("/api/v1/iam/"):
            module = path[len("/api/v1/iam/"):].split("/")[0]
            action = request.method.lower()
        elif path == "/api/auth/users/me/password":
            module, action = "auth", "change_password"
        else:
            module, action = "http", request.method.lower()
        with SessionLocal() as db:
            iam.audit(db, request, getattr(request.state, "security_actor", "anonymous"), module, action, path,
                      outcome="denied" if status_code in {401, 403} else "failed" if denied else "success",
                      details={"status_code": status_code})
            db.commit()
