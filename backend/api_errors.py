from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


SUPPORTED_LOCALES = {"zh-CN", "en-US"}
logger = logging.getLogger(__name__)

_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str, str, str], ...] = (
    (re.compile(r"Upload import job is active", re.I), "upload.job_active", "导入任务正在执行，暂时无法删除上传会话", "The import job is active; its upload session cannot be deleted yet"),
    (re.compile(r"ZIP symlink confirmation required", re.I), "upload.symlink_confirmation_required", "请先确认跳过软链接", "Confirm skipping symbolic links first"),
    (re.compile(r"Upload import session not found", re.I), "upload.session_not_found", "上传会话不存在，请重新选择 ZIP", "Upload session not found. Select the ZIP again"),
    (re.compile(r"scanner token can only read own submissions", re.I), "scanner.submission_not_owned", "当前凭证无权读取该提交记录", "The current credential cannot read this submission"),
    (re.compile(r"Skill not found|Skill 不存在", re.I), "skill.not_found", "Skill 不存在", "Skill not found"),
    (re.compile(r"SKILL\.md not found|SKILL\.md 不存在", re.I), "skill.manifest_not_found", "SKILL.md 不存在", "SKILL.md not found"),
    (re.compile(r"Skill path is not available|Skill 路径不可用", re.I), "skill.path_unavailable", "Skill 路径不可用", "Skill path is unavailable"),
    (re.compile(r"Skill directory not found|Skill 目录不存在", re.I), "skill.directory_not_found", "Skill 目录不存在", "Skill directory not found"),
    (re.compile(r"File too large|文件过大", re.I), "upload.file_too_large", "上传文件超过大小限制", "The uploaded file exceeds the size limit"),
    (re.compile(r"too many files|文件数量超过限制", re.I), "upload.too_many_files", "Skill 文件数量超过限制", "The Skill contains too many files"),
    (re.compile(r"Unsafe path|路径.*不安全|路径超出", re.I), "upload.unsafe_path", "压缩包包含不安全路径", "The archive contains an unsafe path"),
    (re.compile(r"Symlinks are not allowed|不允许.*软链接", re.I), "upload.symlink_not_allowed", "压缩包不允许包含软链接", "Symbolic links are not allowed in the archive"),
    (re.compile(r"Invalid .*status|无效的.*状态", re.I), "request.invalid_status", "状态参数无效", "The status value is invalid"),
    (re.compile(r"客户端不存在|Client not found", re.I), "client.not_found", "客户端不存在", "Client not found"),
    (re.compile(r"任务不存在|Task not found", re.I), "client.task_not_found", "任务不存在", "Task not found"),
    (re.compile(r"模型不存在|Model not found", re.I), "model.not_found", "模型不存在", "Model not found"),
    (re.compile(r"模型供应商不存在|Provider not found", re.I), "model.provider_not_found", "模型供应商不存在", "Model provider not found"),
    (re.compile(r"用户不存在|User not found", re.I), "user.not_found", "用户不存在", "User not found"),
    (re.compile(r"用户组不存在|Group not found", re.I), "group.not_found", "用户组不存在", "User group not found"),
    (re.compile(r"隐私策略不存在|Privacy policy not found", re.I), "privacy.policy_not_found", "隐私策略不存在", "Privacy policy not found"),
    (re.compile(r"权限不足|Permission denied", re.I), "auth.permission_denied", "权限不足", "Permission denied"),
)


def request_locale(request: Request) -> str:
    values = request.headers.get("accept-language", "").lower()
    for item in values.split(","):
        language = item.split(";", 1)[0].strip()
        if language.startswith("en"):
            return "en-US"
        if language.startswith("zh"):
            return "zh-CN"
    return "zh-CN"


def classify_http_error(status_code: int, detail: Any) -> tuple[str, str | None, str | None]:
    if isinstance(detail, str):
        for pattern, code, zh_message, en_message in _ERROR_PATTERNS:
            if pattern.search(detail):
                return code, zh_message, en_message
    return f"http.{status_code}", None, None


class ApiError(HTTPException):
    """HTTP error with a stable machine code and localized fallback messages."""

    def __init__(
        self,
        status_code: int,
        code: str,
        zh_message: str,
        en_message: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.zh_message = zh_message
        self.en_message = en_message
        self.params = params or {}
        super().__init__(
            status_code=status_code,
            detail=zh_message,
            headers=headers,
        )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    locale = request_locale(request)
    message = exc.en_message if locale == "en-US" else exc.zh_message
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": message,
            "error_code": exc.code,
            "error_params": jsonable_encoder(exc.params),
        },
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Keep legacy errors readable while giving every API failure a stable envelope."""

    detail = exc.detail
    code, zh_message, en_message = classify_http_error(exc.status_code, detail)
    locale = request_locale(request)
    params = {}
    if code == "upload.symlink_not_allowed" and isinstance(detail, str):
        prefix = "Symlinks are not allowed in ZIP: "
        if detail.startswith(prefix):
            params["path"] = detail[len(prefix):]
    if zh_message and en_message:
        detail = en_message if locale == "en-US" else zh_message
        if "path" in params:
            detail = f"{detail}: {params['path']}"
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": jsonable_encoder(detail),
            "error_code": code,
            "error_params": params,
        },
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    locale = request_locale(request)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request parameters" if locale == "en-US" else "请求参数无效",
            "error_code": "request.validation_failed",
            "error_params": {"errors": jsonable_encoder(exc.errors())},
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled API error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    locale = request_locale(request)
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": request.state.request_id} if getattr(request.state, "request_id", None) else None,
        content={
            "detail": "Internal server error" if locale == "en-US" else "服务器内部错误",
            "error_code": "server.internal_error",
            "error_params": {},
        },
    )
