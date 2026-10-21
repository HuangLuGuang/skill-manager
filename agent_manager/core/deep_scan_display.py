"""Attach language-neutral display metadata without changing scan decisions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from string import Formatter
from typing import Any


_CATALOG = json.loads(Path(__file__).with_name("deep_scan_catalog.json").read_text(encoding="utf-8"))
_EXACT: dict[tuple[str, str, str], dict[str, str]] = {}
_PATTERNS: dict[tuple[str, str, str], list[tuple[str, re.Pattern[str]]]] = {}
_TAINT_PARAMETER_CODES = {
    "credential/environment": "taint_credential_environment",
    "file read": "taint_file_read",
    "network input": "taint_network_input",
    "user input": "taint_user_input",
    "network output": "taint_network_output",
    "code execution": "taint_code_execution",
    "file write": "taint_file_write",
    "data source": "taint_data_source",
    "data sink": "taint_data_sink",
}

for _code, _entry in _CATALOG["texts"].items():
    _parts = list(Formatter().parse(_entry["template"]))
    _dynamic = any(field is not None for _, field, _, _ in _parts)
    _pattern = "".join(
        re.escape(literal) + (f"(?P<{field}>.*?)" if field is not None else "")
        for literal, field, _, _ in _parts
    )
    for _field in _entry["fields"]:
        _key = (_entry["source"], _entry["rule"], _field)
        if _dynamic:
            _PATTERNS.setdefault(_key, []).append((_code, re.compile(_pattern, re.DOTALL)))
        else:
            _EXACT.setdefault(_key, {})[_entry["template"]] = _code


def with_deep_scan_display(finding: dict[str, Any]) -> dict[str, Any]:
    """Copy a finding and identify only complete, known scanner templates.

    Original fields, evidence, severity and classification remain untouched.
    The same function handles new findings and read-only historical responses.
    """
    source = finding.get("source")
    rule = finding.get("rule") or finding.get("rule_id")
    if not isinstance(source, str) or source not in {"skillspector", "agent-manager-local"} or not isinstance(rule, str):
        return finding
    display: dict[str, Any] = {}
    if source == "skillspector" and rule in _CATALOG["rules"]:
        display["rule"] = rule
    for field in ("title", "message", "explanation", "remediation"):
        value = finding.get(field)
        if not isinstance(value, str) or not value:
            continue
        # 归一化可能以 finding 证据补 message；证据即使恰好等于固定短语也保留原文。
        if field in {"title", "message"} and value == finding.get("finding"):
            continue
        # 仅编号的历史标题使用可读规则名，正文仍优先保留该次检测的实际解释。
        if source == "skillspector" and field == "title" and value == rule and rule in _CATALOG["rules"]:
            display[field] = {"code": f"{rule}_name", "params": {}}
            continue
        key = (source, rule, field)
        code = _EXACT.get(key, {}).get(value)
        if code:
            display[field] = {"code": code, "params": {}}
            continue
        for code, pattern in _PATTERNS.get(key, []):
            match = pattern.fullmatch(value)
            if match:
                display[field] = {"code": code, "params": match.groupdict()}
                # 污点来源与去向是扫描器固定分类，调用名和变量名仍为原始证据。
                slots = ()
                if rule in {"TT1", "TT2", "TT3", "TT4", "TT5"}:
                    if code.endswith("_direct_flow"):
                        slots = ("p1", "p3")
                    elif code.endswith("_tainted_flow"):
                        slots = ("p3", "p5")
                labels = {
                    slot: _TAINT_PARAMETER_CODES[match[slot]]
                    for slot in slots if match[slot] in _TAINT_PARAMETER_CODES
                }
                if labels:
                    display[field]["param_codes"] = labels
                break
    # 展示元数据由原始字段重建，避免历史元数据与实际文本不一致。
    return {**finding, "display": display}


def with_deep_scan_analysis_display(analysis: dict[str, Any]) -> dict[str, Any]:
    """Enrich findings on a copy; never write historical reports back."""
    findings = analysis.get("findings")
    if not isinstance(findings, list):
        return analysis
    return {
        **analysis,
        "findings": [with_deep_scan_display(item) if isinstance(item, dict) else item for item in findings],
    }
