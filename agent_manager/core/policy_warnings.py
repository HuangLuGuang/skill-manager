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
        elif rule == "max_allowed_tools":
            values = re.fullmatch(r"Skill declares (\d+) tools; policy allows at most (\d+)", message)
            if values:
                params = {"count": int(values.group(1)), "limit": int(values.group(2))}
        elif rule == "tool_not_in_allowlist":
            value = re.fullmatch(r"Tool (.+) is not in the company allowlist", message)
            if value:
                try:
                    tool = ast.literal_eval(value.group(1))
                except (ValueError, SyntaxError):
                    tool = None
                if isinstance(tool, str):
                    params = {"tool": tool}
        warnings.append({"rule": rule, "params": params, "message": message})
    return warnings


def format_policy_warning(warning: dict[str, Any], language: str) -> str:
    """Translate fixed copy while preserving recorded policy values."""
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
    if warning["rule"] == "max_allowed_tools" and "count" in params and "limit" in params:
        return (
            f"声明的工具数量为 {params['count']}，超过公司允许的上限 {params['limit']}。"
            if language == "zh-CN"
            else f"The Skill declares {params['count']} tools, exceeding the company limit of {params['limit']}."
        )
    if warning["rule"] == "tool_not_in_allowlist" and isinstance(params.get("tool"), str):
        # 只读取报告快照；历史记录缺少列表时明确标记未记录。
        allowed = params.get("allowed_tools_allowlist")
        if isinstance(allowed, list):
            allowed_text = ", ".join(allowed) or ("无" if language == "zh-CN" else "None")
        else:
            allowed_text = "未记录" if language == "zh-CN" else "Not recorded"
        return (
            f"声明的工具 {params['tool']} 不在允许列表中：{allowed_text}。"
            if language == "zh-CN"
            else f"The declared tool {params['tool']} is not in the allowlist: {allowed_text}."
        )
    return warning["message"]
