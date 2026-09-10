from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


FIELD_STATUSES = {"verified", "declared", "inferred", "unverified", "unavailable"}


def collected_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def field(
    value: Any,
    *,
    source: str | None,
    status: str,
    collected_at: str,
    missing_reason: str | None = None,
    source_identifier: str | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    if status not in FIELD_STATUSES:
        raise ValueError(f"unsupported Dify inventory field status: {status}")
    return {
        "value": value,
        "source": source,
        "status": status,
        "collected_at": collected_at,
        "missing_reason": missing_reason,
        **({"source_identifier": source_identifier} if source_identifier else {}),
        **metadata,
    }


def source(source_type: str, source_identifier: str | None = None, **metadata: Any) -> dict[str, Any]:
    return {
        "source_type": source_type,
        **({"source_identifier": source_identifier} if source_identifier else {}),
        **metadata,
    }


def asset(
    *,
    asset_id: str,
    asset_type: str,
    name: str,
    configured: bool,
    discovered: bool,
    executed: bool,
    verification_status: str,
    sources: list[dict[str, Any]],
    details: dict[str, Any],
    sensitive_content: str | None = None,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "asset_type": asset_type,
        "name": name,
        "configured": configured,
        "discovered": discovered,
        "executed": executed,
        "verification_status": verification_status,
        "sources": sources,
        "details": details,
        **({"sensitive_content": sensitive_content} if sensitive_content is not None else {}),
    }
