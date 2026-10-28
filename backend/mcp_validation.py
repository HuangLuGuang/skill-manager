"""MCP 服务字段规则及可本地化的字段错误。"""

import re
from typing import Any

from pydantic_core import PydanticCustomError

from .api_errors import ApiError

LIMITS = {
    "name": 128, "slug": 128, "endpoint": 1024,
    "authorization_header": 128, "authorization_value": 4096, "description": 2000,
}
FIELDS = {
    "name": ("名称", "Name"), "slug": ("唯一标识", "Identifier"),
    "endpoint": ("Streamable HTTP Endpoint", "Streamable HTTP Endpoint"),
    "authorization_header": ("鉴权 Header", "Authentication header"),
    "authorization_value": ("鉴权值", "Authentication value"),
    "status": ("状态", "Status"), "timeout_seconds": ("超时秒数", "Timeout (seconds)"),
    "max_response_kb": ("最大响应 KB", "Maximum response (KB)"),
    "description": ("描述", "Description"),
}
REASONS = {
    "whitespace": ("不能仅包含空白字符", "must not contain only whitespace"),
    "required": ("不能为空", "is required"),
    "length": ("最多 {limit} 个字符", "must not exceed {limit} characters"),
    "text": ("必须是文本", "must be text"),
    "slug": ("全文只能包含小写字母、数字、下划线（_）和连字符（-）；首字符必须是小写字母或数字", "must contain only lowercase letters, digits, underscores (_) and hyphens (-) throughout; the first character must be a lowercase letter or digit"),
    "header": ("须为合法 HTTP Header 名称", "must be a valid HTTP header name"),
    "value": ("仅允许可打印 ASCII 字符，不允许换行", "must contain printable ASCII characters without line breaks"),
    "status": ("须为草稿、启用或停用", "must be Draft, Enabled or Disabled"),
    "integer": ("须为 {min}–{max} 范围内的整数", "must be an integer between {min} and {max}"),
    "url": ("须为有效 HTTP/HTTPS 地址，不含空白、用户名、密码或片段", "must be a valid HTTP/HTTPS URL without whitespace, user information or fragments"),
    "https": ("当前配置要求使用 HTTPS", "must use HTTPS under the current configuration"),
    "address": ("不允许使用该目标地址", "uses a prohibited destination address"),
    "duplicate": ("已存在，请使用其他标识", "already exists; choose another identifier"),
    "immutable": ("创建后不可修改", "cannot be changed after creation"),
}


def field_issue(field: str, reason: str, **params: Any) -> dict[str, Any]:
    return {"field": field, "reason": reason, **params}


def fields_error(issues: list[dict[str, Any]], status_code: int = 422) -> ApiError:
    messages = []
    for language in (0, 1):
        messages.append("; ".join(
            f"{FIELDS[item['field']][language]}: "
            + REASONS[item["reason"]][language].format(**item)
            for item in issues
        ))
    return ApiError(status_code, "mcp.server.invalid_fields", *messages, params={"errors": issues})


def validate_field(field: str, value: Any) -> Any:
    """校验实际输入，保留可选原文，不在错误中包含鉴权值。"""
    def fail(reason: str, **params: Any) -> None:
        raise PydanticCustomError("mcp_field", "Invalid MCP field", field_issue(field, reason, **params))

    if field not in FIELDS:
        return value
    if value is None:
        if field in {"description", "authorization_value"}:
            return value
        fail("required")
    if field in {"timeout_seconds", "max_response_kb"}:
        maximum = 300 if field == "timeout_seconds" else 10240
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            fail("integer", min=1, max=maximum)
        digits = str(value).lstrip("0") or "0"
        if len(digits) > len(str(maximum)):
            fail("integer", min=1, max=maximum)
        value = int(digits)
        if not 1 <= value <= maximum:
            fail("integer", min=1, max=maximum)
        return value
    if not isinstance(value, str):
        fail("text")
    if field in {"name", "slug", "endpoint", "authorization_header"}:
        value = value.strip()
        if not value:
            fail("required")
    if field in LIMITS and len(value) > LIMITS[field]:
        fail("length", limit=LIMITS[field])
    if field == "slug" and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", value):
        fail("slug")
    if field == "authorization_header" and not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", value):
        fail("header")
    if field == "authorization_value" and any(not 32 <= ord(char) <= 126 for char in value):
        fail("value")
    if field == "status" and value not in {"draft", "active", "disabled"}:
        fail("status")
    return value
