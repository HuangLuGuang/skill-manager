"""Recorded non-blocking admission notices shared by API and PDF."""

from __future__ import annotations

import ast
import re
from typing import Any


def get_policy_warnings(report: dict, notes: list[str]) -> list[dict[str, Any]]:
    """Read this scan's notices without applying today's policy."""
    if isinstance(report.get("policy_warnings"), list):
        return report["policy_warnings"]
    warnings = []
    # 旧报告仅在读取时解析已保存备注，不修改历史证据。
    for note in notes:
        match = re.fullmatch(r"\[WARN\]\s+([^:]+):\s*(.*)", str(note), re.DOTALL)
        if not match:
            continue
        rule, message = match.groups()
        params = {}
        if rule == "unaccepted_license":
            values = re.fullmatch(
                r"License (.+) is not in the accepted list: (.+)", message,
            )
            license_value, accepted = None, None
            if values:
                try:
                    license_value, accepted = (
                        ast.literal_eval(value) for value in values.groups()
                    )
                except (ValueError, SyntaxError):
                    pass
            if (
                isinstance(license_value, str)
                and isinstance(accepted, list)
                and all(isinstance(item, str) for item in accepted)
            ):
                params = {"license": license_value, "accepted_licenses": accepted}
            else:
                rule = "legacy_warning"
        warnings.append({"rule": rule, "params": params, "message": message})
    return warnings


def format_policy_warning(warning: dict[str, Any], language: str) -> str:
    """Translate fixed copy while preserving recorded license identifiers."""
    params = warning.get("params", {})
    if warning["rule"] == "require_license":
        return (
            "Skill 声明缺少策略要求的许可证字段。"
            if language == "zh-CN"
            else "The Skill manifest is missing the license field required by policy."
        )
    if warning["rule"] == "unaccepted_license":
        accepted = ", ".join(params["accepted_licenses"])
        license_value = params["license"]
        return (
            f"许可证 {license_value} 不在本次扫描接受的许可证列表中：{accepted}。"
            if language == "zh-CN"
            else f"License {license_value} is not in the licenses accepted for this scan: {accepted}."
        )
    return warning["message"]
