from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEYS = re.compile(r"(?i)(api[_-]?key|authorization|cookie|password|secret|token|credential)")


def redact_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEYS.search(str(key)) else redact_structure(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    return value


def public_prompt(prompt: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in prompt.items() if key not in {"text", "sensitive_content"}}
