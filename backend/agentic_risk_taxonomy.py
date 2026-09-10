from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# OWASP Agentic Security Initiative, Top Ten for Agentic Applications,
# 1st Public Draft. The commit is pinned so stored mappings remain auditable
# if the draft titles or numbering change later.
FRAMEWORK_ID = "OWASP_AGENTIC_TOP10"
FRAMEWORK_VERSION = "first-public-draft"
FRAMEWORK_COMMIT = "e1deaca619dd35608645c0ca8ffce1cc4a019193"
MAPPING_VERSION = "agent-manager-asi-map@1"
MAPPING_SCHEMA_VERSION = "agentic-risk-mapping@1"

ASI_CATEGORIES: dict[str, dict[str, str]] = {
    "ASI01": {"en": "Agent Behaviour Hijack", "zh": "智能体行为劫持"},
    "ASI02": {"en": "Tool Misuse and Exploitation", "zh": "工具滥用与利用"},
    "ASI03": {"en": "Identity & Privilege Abuse", "zh": "身份与权限滥用"},
    "ASI04": {"en": "Agentic Supply Chain Vulnerabilities", "zh": "智能体供应链漏洞"},
    "ASI05": {"en": "Unexpected Code Execution (RCE)", "zh": "意外代码执行"},
    "ASI06": {"en": "Memory & Context Poisoning", "zh": "记忆与上下文投毒"},
    "ASI07": {"en": "Insecure Inter-Agent Communication", "zh": "不安全的智能体间通信"},
    "ASI08": {"en": "Cascading Failures", "zh": "级联故障"},
    "ASI09": {"en": "Human-Agent Trust Exploitation", "zh": "人机信任利用"},
    "ASI10": {"en": "Rogue Agents", "zh": "恶意智能体"},
}

# Only exact, reviewed platform codes are mapped. Unknown upstream or caller
# strings remain unmapped rather than being guessed from display text.
_CODE_TO_ASI: dict[str, tuple[str, ...]] = {
    "agent_goal_hijack": ("ASI01",),
    "prompt_injection.detected": ("ASI01",),
    "prompt_injection": ("ASI01",),
    "system_prompt_leak": ("ASI01",),
    "encoded_instruction": ("ASI01",),
    "runtime.goal_drift_detected": ("ASI01",),
    "tool_misuse": ("ASI02",),
    "tool_abuse": ("ASI02",),
    "mcp_dangerous_tool_unprotected": ("ASI02",),
    "mcp_dangerous_parameters": ("ASI02",),
    "mcp.write_tool_blocked_by_read_only_mode": ("ASI02",),
    "mcp.tool_blocked_by_production_denylist": ("ASI02",),
    "mcp.tool_blocked_by_passive_mode": ("ASI02",),
    "runtime.action_not_in_contract": ("ASI02",),
    "runtime.target_not_in_contract": ("ASI02",),
    "runtime.high_risk_approval_required": ("ASI02",),
    "runtime.preview_side_effect_blocked": ("ASI02",),
    "identity_privilege_abuse": ("ASI03",),
    "agentic_supply_chain": ("ASI04",),
    "mcp_bound_tool_missing": ("ASI04",),
    "mcp_tool_description_injection": ("ASI01", "ASI04"),
    "mcp_schema_drift": ("ASI04",),
    "mcp_schema_unapproved": ("ASI04",),
    "unexpected_code_execution": ("ASI05",),
    "runtime.command_execution": ("ASI05",),
    "memory_context_poisoning": ("ASI06",),
    "secret_exfiltration": ("ASI06",),
    "runtime.credential_material": ("ASI06",),
    "insecure_inter_agent_communication": ("ASI07",),
    "cascading_failure": ("ASI08",),
    "human_agent_trust_exploitation": ("ASI09",),
    "rogue_agent": ("ASI10",),
}


def _source_codes(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()[:128]
        if value and value not in seen:
            seen.add(value)
            result.append(value)
        if len(result) >= 100:
            break
    return result


def map_risk_codes(values: Iterable[str]) -> dict[str, Any]:
    source_codes = _source_codes(values)
    mapped_sources = 0
    asi_codes: set[str] = set()
    for source_code in source_codes:
        upper = source_code.upper()
        if upper in ASI_CATEGORIES:
            asi_codes.add(upper)
            mapped_sources += 1
            continue
        mapped = _CODE_TO_ASI.get(source_code.lower(), ())
        if mapped:
            mapped_sources += 1
            asi_codes.update(mapped)
    if not source_codes:
        status = "not_applicable"
    elif mapped_sources == len(source_codes):
        status = "mapped"
    elif mapped_sources:
        status = "partial"
    else:
        status = "unmapped"
    ordered_asi = sorted(asi_codes)
    return {
        "schema_version": MAPPING_SCHEMA_VERSION,
        "framework": FRAMEWORK_ID,
        "framework_version": FRAMEWORK_VERSION,
        "framework_commit": FRAMEWORK_COMMIT,
        "mapping_version": MAPPING_VERSION,
        "status": status,
        "source_codes": source_codes,
        "risk_codes": ordered_asi,
        "categories": [
            {"code": code, "title_en": ASI_CATEGORIES[code]["en"], "title_zh": ASI_CATEGORIES[code]["zh"]}
            for code in ordered_asi
        ],
    }


def enrich_risk_codes(values: Iterable[str]) -> tuple[list[str], dict[str, Any]]:
    mapping = map_risk_codes(values)
    enriched = list(mapping["source_codes"])
    enriched.extend(code for code in mapping["risk_codes"] if code not in enriched)
    return enriched, mapping
