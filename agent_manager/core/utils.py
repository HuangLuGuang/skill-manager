"""Shared helpers used across Agent Manager core and integration hooks."""

from __future__ import annotations


def tool_parent_name(value: str) -> str:
    """Return the coarse tool name for declarations like ``Bash(python:*)``."""
    return str(value).split("(", 1)[0].strip()


def tool_matches(allowed_tool: str, requested_tool: str) -> bool:
    """Match exact tool names or parameterized child declarations by parent."""
    return (
        allowed_tool == requested_tool
        or tool_parent_name(allowed_tool) == tool_parent_name(requested_tool)
    )
