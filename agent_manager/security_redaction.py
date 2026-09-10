"""Shared credential and PII redaction primitives for backend and scan Worker."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)(\"?[A-Za-z0-9_-]*(?:authorization|cookie|api[_-]?key|token|password|secret|credential)"
        r"[A-Za-z0-9_-]*\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|(?:Bearer\s+)?[^\s,;}]+)"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|clickhouse|mongodb(?:\+srv)?|redis|"
        r"jdbc:[a-z0-9]+)://[^\s'\"<>]+"
    ),
    re.compile(
        r"(?i)\b(?:server|host)\s*=\s*[^;\s]+\s*;[^\r\n]{0,512}"
        r"(?:database|user\s*id|uid|password|pwd)\s*=\s*[^;\s]+"
    ),
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{17}[\dXx](?![\dA-Za-z])"),
    re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
)

SENSITIVE_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "bearer",
    "clientsecret",
    "credential",
    "credentials",
    "cookie",
    "githubtoken",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "token",
}
SENSITIVE_KEY_SUFFIXES = (
    "apikey",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "secret",
    "secretkey",
    "token",
)


def normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def is_sensitive_key(value: Any) -> bool:
    key = normalized_key(value)
    return key in SENSITIVE_KEYS or key.endswith(SENSITIVE_KEY_SUFFIXES)


def redact_sensitive_text(value: Any) -> str:
    text = str(value).replace("\x00", "")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def redact_sensitive_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 16:
        return "[depth-limited]"
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(key) else redact_sensitive_value(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value
