"""Shared authentication, attribution and recording for external API requests."""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.routing import Match

from . import models, sqlite_db
from .api_errors import ApiError, api_error_handler

OPENAPI_SCOPES = ["openapi:skill-submit", "openapi:skill-read", "openapi:agent-manage",
                  "openapi:agent-read", "openapi:connection-test", "openapi:evaluation-submit", "openapi:evaluation-read"]
logger = logging.getLogger(__name__)


def validate_binding(db, platform_id, department_ids, *, require_enabled=False):
    platform = db.get(models.ExternalPlatform, platform_id) if platform_id else None
    if not platform:
        raise ApiError(400, "external_access.platform_not_found", "接入方不存在", "Integration partner not found")
    if require_enabled and not platform.enabled:
        raise ApiError(400, "external_access.platform_unavailable", "请选择已启用的接入方", "Select an enabled integration partner")
    mapping = {d["department_id"]: d["group_id"] for d in json.loads(platform.departments_json)}
    if not department_ids or any(d not in mapping for d in department_ids):
        raise ApiError(400, "external_access.department_invalid", "请选择接入方已配置的部门", "Select configured departments for this partner")
    if db.query(models.UserGroup).filter(models.UserGroup.id.in_([mapping[d] for d in department_ids])).count() != len(set(mapping[d] for d in department_ids)):
        raise ApiError(400, "external_access.department_invalid", "部门映射的用户组不存在", "A mapped user group no longer exists")
    return platform


@dataclass(frozen=True)
class ExternalAccessContext:
    platform_id: str
    token_id: int
    scopes: tuple[str, ...]
    departments: dict[str, int]
    request_id: str

    @property
    def username(self):
        return "openapi:" + self.platform_id

    def department_group(self, department_id: str) -> int:
        if department_id not in self.departments:
            raise ApiError(403, "external_access.department_denied", "凭证未授权该部门", "The credential is not authorized for this department")
        return self.departments[department_id]

    def agent_source(self, external_agent_id: str):
        return {"registration_source": "external_api", "source_platform_id": self.platform_id,
                "external_agent_id": external_agent_id, "source_token_id": self.token_id, "source_request_id": self.request_id}

    def task_source(self, external_task_id: str | None = None, business_request_id: str | None = None):
        return {"trigger_source": "external_api", "source_platform_id": self.platform_id,
                "business_request_id": business_request_id,
                "external_task_id": external_task_id, "source_token_id": self.token_id, "source_request_id": self.request_id}


def require_openapi_scope(scope: str):
    if scope not in OPENAPI_SCOPES:
        raise ValueError("Unknown external API scope")

    def dependency(request: Request) -> ExternalAccessContext:
        context = getattr(request.state, "external_access", None)
        if context is None:
            raise ApiError(401, "external_access.authentication_required", "请提供 ACCESS_TOKEN", "Provide an ACCESS_TOKEN")
        if scope not in context.scopes:
            raise ApiError(403, "credential.scope_missing", "凭证缺少接口权限", "The credential lacks the required API permission", params={"scopes": [scope]})
        return context
    return dependency


def link_external_resource(request: Request, resource_type: str, resource_id: str, department_id: str | None = None, business_request_id: str | None = None):
    """Called by a business handler after resolving its authorized resource."""
    if resource_type not in {"agent", "skill", "evaluation"} or len(resource_id) > 128 or (business_request_id is not None and len(business_request_id) > 128):
        raise ValueError("Invalid external API resource reference")
    context = request.state.external_access
    if department_id is not None:
        context.department_group(department_id)
    request.state.external_resource = {"resource_type": resource_type, "resource_id": resource_id, "department_id": department_id, "business_request_id": business_request_id}


def _start_request(request):
    from .routers.access_tokens import resolve_access_token, _extract_bearer, _hash_token

    with sqlite_db.SessionLocal() as db:
        record = models.ExternalApiRequest(request_id=request.state.external_record_id,
                                           client_request_id=request.state.client_request_id, method=request.method,
                                           source_ip=request.client.host if request.client else None)
        for route in request.app.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                record.route = getattr(route, "path", None)
                break
        db.add(record)
        db.commit()
        if getattr(request.state, "invalid_request_id", False):
            raise ApiError(422, "INVALID_ARGUMENT", "X-Request-ID 格式无效", "Invalid X-Request-ID",
                           params={"details": [{"field": "X-Request-ID", "reason": "string_pattern_mismatch"}]})
        candidate = db.query(models.AccessToken).filter_by(token_hash=_hash_token(_extract_bearer(request.headers.get("authorization"))), token_type="openapi").first()
        if candidate:
            record.token_id, record.token_name, record.token_prefix = candidate.id, candidate.name, candidate.token_prefix
            record.platform_id = candidate.platform_id
            platform = db.get(models.ExternalPlatform, candidate.platform_id)
            record.platform_name = platform.name if platform else None
        db.commit()
        token = resolve_access_token(db, request.headers.get("authorization"), required_scope=tuple(OPENAPI_SCOPES),
                                     request=request, allowed_token_types={"openapi"})
        platform = db.get(models.ExternalPlatform, token.platform_id)
        if not platform or not platform.enabled:
            raise ApiError(403, "external_access.platform_disabled", "接入方未启用", "The integration partner is disabled")
        permitted = set(json.loads(token.allowed_department_ids_json))
        departments = {d["department_id"]: d["group_id"] for d in json.loads(platform.departments_json) if d["department_id"] in permitted}
        existing_groups = {row.id for row in db.query(models.UserGroup.id).filter(models.UserGroup.id.in_(departments.values()))}
        departments = {k: v for k, v in departments.items() if v in existing_groups}
        if not departments:
            raise ApiError(403, "external_access.department_denied", "凭证没有可用的部门授权", "The credential has no available department authorization")
        request.state.external_access = ExternalAccessContext(platform.platform_id, token.id,
            tuple(json.loads(token.scopes_json)), departments, request.state.external_record_id)


def _finish_request(request, status, duration):
    with sqlite_db.SessionLocal() as db:
        row = db.query(models.ExternalApiRequest).filter_by(request_id=request.state.external_record_id).one()
        # Route templates exclude caller-supplied identifiers and query strings.
        route = request.scope.get("route")
        row.route = getattr(route, "path", None) or row.route
        row.status_code, row.duration_ms = status, duration
        row.error_code = getattr(request.state, "external_error_code", None) or (f"http.{status}" if status >= 400 else None)
        for key, value in getattr(request.state, "external_resource", {}).items():
            setattr(row, key, value)
        db.commit()


class ExternalAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/openapi/v1" or scope["path"].startswith("/openapi/v1/")):
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        request.state.external_record_id = str(uuid.uuid4())
        supplied = request.headers.getlist("x-request-id")
        valid = len(supplied) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied[0]) is not None
        request.state.client_request_id = supplied[0] if valid else None
        request.state.invalid_request_id = bool(supplied) and not valid
        request.state.request_id = request.state.client_request_id or request.state.external_record_id
        started = time.monotonic()
        status = 500
        response_started = False

        async def tracked_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": headers + [(b"x-request-id", request.state.request_id.encode())]}
            await send(message)

        # Commit the received record before dispatching business work.
        try:
            await run_in_threadpool(_start_request, request)
        except ApiError as exc:
            request.state.external_error_code = exc.code
            response = await api_error_handler(request, exc)
            await response(scope, receive, tracked_send)
            await run_in_threadpool(_finish_request, request, status, int((time.monotonic() - started) * 1000))
            return
        except Exception as exc:
            logger.error("External API authentication unavailable request_id=%s type=%s", request.state.request_id, type(exc).__name__)
            response = await api_error_handler(request, ApiError(503, "SERVICE_UNAVAILABLE", "接入认证服务暂不可用", "Access authentication is temporarily unavailable"))
            await response(scope, receive, tracked_send)
            return
        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            request.state.external_error_code = "server.internal_error"
            logger.error("External API failure request_id=%s type=%s", request.state.request_id, type(exc).__name__)
            if not response_started:
                response = await api_error_handler(request, ApiError(500, "server.internal_error", "服务器内部错误", "Internal server error"))
                await response(scope, receive, tracked_send)
            else:
                raise RuntimeError("External API response interrupted") from None
        finally:
            await run_in_threadpool(_finish_request, request, status, int((time.monotonic() - started) * 1000))
