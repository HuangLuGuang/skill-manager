"""
Company policy enforcement for skill approval.

Loaded from a YAML file; controls auto-approval thresholds, blocked permissions,
trusted authors, and tool allowlists.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .models import PolicyViolation, RiskLevel, SkillStatus, SourceInfo
from .utils import tool_parent_name

logger = logging.getLogger(__name__)

DEFAULT_RISK_CLASSIFICATION: dict[str, str] = {
    "data_exfiltration": "risk",
    "supply_chain": "risk",
    "prompt_injection": "risk",
    "tool_misuse": "risk",
    "network": "risk",
    "credential_access": "risk",
    "dynamic_execution": "risk",
    "excessive_permissions": "risk",
    "documented_external_api": "noise",
    "dependency": "risk",
    "runtime": "risk",
}

_VALID_FINDING_CLASSIFICATIONS = {"blocking", "risk", "noise"}

_DEFAULT_POLICY: dict[str, Any] = {
    "scan_result_reuse_enabled": True,
    "auto_approve_max_risk": "benign",
    "auto_approve_risk": ["benign"],
    "require_human_review": ["suspicious"],
    "auto_reject_risk": ["malicious"],
    "require_sandbox_for_risk": ["suspicious", "malicious"],
    "blocked_permissions": ["read_credentials", "write_memory", "read_identity"],
    "trusted_authors": [],
    "allowed_tools_allowlist": [
        "Bash", "Read", "Write", "Edit", "Glob", "Grep",
        "WebFetch", "WebSearch", "Agent", "TodoWrite", "TodoRead",
    ],
    "max_allowed_tools": 20,
    "require_license": False,
    "accepted_licenses": ["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "internal"],
    "scanner_policy": "balanced",
    "judgement_mode": "balanced",
    "risk_classification": DEFAULT_RISK_CLASSIFICATION,
    "skillspector_enabled": False,
    "skillspector_fail_open": True,
    "skillspector_timeout_seconds": 120,
    "skillspector_min_blocking_severity": "HIGH",
    "skillspector_use_llm": False,
}

_SEVERITY_TO_RISK = {
    "SAFE": RiskLevel.BENIGN,
    "INFO": RiskLevel.BENIGN,
    "LOW": RiskLevel.BENIGN,
    "MEDIUM": RiskLevel.SUSPICIOUS,
    "HIGH": RiskLevel.MALICIOUS,
    "CRITICAL": RiskLevel.MALICIOUS,
    "EXTREME": RiskLevel.MALICIOUS,
}


def _normalized_policy_risks(values: Any) -> set[RiskLevel]:
    if not isinstance(values, (list, tuple, set)):
        return set()

    normalized: set[RiskLevel] = set()
    for value in values:
        text = str(value).strip()
        semantic = text.lower()
        if semantic in {risk.value for risk in RiskLevel}:
            normalized.add(RiskLevel(semantic))
            continue
        mapped = _SEVERITY_TO_RISK.get(text.upper())
        if mapped:
            normalized.add(mapped)
        else:
            logger.warning("Ignoring unknown policy risk value: %r", value)
    return normalized


class CompanyPolicy:
    """Loaded company policy with enforcement methods."""

    def __init__(self, data: dict[str, Any]):
        self._data = {**_DEFAULT_POLICY, **data}

    @classmethod
    def load(cls, path: str | Path) -> "CompanyPolicy":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        logger.info("Loaded company policy from %s", path)
        return cls(data)

    @classmethod
    def default(cls) -> "CompanyPolicy":
        return cls({})

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=False)

    # ------------------------------------------------------------------ #
    # Public accessors                                                     #
    # ------------------------------------------------------------------ #

    @property
    def require_sandbox_for_risk(self) -> list[RiskLevel]:
        return [RiskLevel(r) for r in self._data.get("require_sandbox_for_risk", [])]

    @property
    def scan_result_reuse_enabled(self) -> bool:
        return bool(self._data.get("scan_result_reuse_enabled", True))

    @property
    def blocked_permissions(self) -> list[str]:
        return self._data["blocked_permissions"]

    @property
    def trusted_authors(self) -> list[str]:
        return self._data["trusted_authors"]

    @property
    def allowed_tools_allowlist(self) -> list[str]:
        return self._data["allowed_tools_allowlist"]

    @property
    def max_allowed_tools(self) -> int:
        return int(self._data["max_allowed_tools"])

    @property
    def scanner_policy(self) -> str:
        return self.judgement_mode

    @property
    def judgement_mode(self) -> str:
        value = str(self._data.get("judgement_mode", "balanced")).strip().lower()
        return value if value in {"strict", "balanced", "permissive"} else "balanced"

    @property
    def skillspector_enabled(self) -> bool:
        return bool(self._data.get("skillspector_enabled", False))

    @property
    def skillspector_timeout_seconds(self) -> int:
        return int(self._data.get("skillspector_timeout_seconds", 120))

    @property
    def skillspector_use_llm(self) -> bool:
        """Legacy config field; SkillSpector model calls are disabled by vetting."""
        return bool(self._data.get("skillspector_use_llm", False))

    @property
    def risk_classification(self) -> dict[str, str]:
        raw = self._data.get("risk_classification")
        if not isinstance(raw, dict):
            raw = self._data.get("risk_classification_overrides")
        merged = dict(DEFAULT_RISK_CLASSIFICATION)
        if isinstance(raw, dict):
            for key, value in raw.items():
                normalized = str(value).strip().lower()
                if normalized in _VALID_FINDING_CLASSIFICATIONS:
                    merged[str(key)] = normalized
        return merged

    def finding_classification(self, finding: dict[str, Any]) -> str | None:
        key = self.finding_policy_key(finding)
        if not key:
            return None
        mapping = self.risk_classification
        value = mapping.get(key)
        if value in _VALID_FINDING_CLASSIFICATIONS:
            return value
        return None

    def finding_policy_key(self, finding: dict[str, Any]) -> str | None:
        mapping = self.risk_classification
        for key in _finding_policy_keys(finding):
            if key in mapping:
                return key
        return None

    def requires_sandbox(self, risk_level: RiskLevel) -> bool:
        return risk_level in self.require_sandbox_for_risk

    def should_auto_approve_prompt(self, entry: Any) -> bool:
        """Check if a prompt can be auto-approved based on its risk level."""
        if not entry.risk_level:
            return False
        risk_order = {"benign": 0, "suspicious": 1, "malicious": 2}
        threshold = self._data.get("auto_approve_max_risk", "benign")
        return risk_order.get(entry.risk_level.value, 999) <= risk_order.get(threshold, 0)

    # ------------------------------------------------------------------ #
    # Enforcement                                                          #
    # ------------------------------------------------------------------ #

    def check_tool_declarations(self, allowed_tools: list[str]) -> list[PolicyViolation]:
        """Validate a skill's declared tool list against policy."""
        violations: list[PolicyViolation] = []

        if len(allowed_tools) > self.max_allowed_tools:
            violations.append(PolicyViolation(
                rule="max_allowed_tools",
                message=f"Skill declares {len(allowed_tools)} tools; policy allows at most {self.max_allowed_tools}",
                # 数量超限仅提示，并保留本次计数和策略上限。
                blocking=False,
                params={"count": len(allowed_tools), "limit": self.max_allowed_tools},
            ))

        allowlist_lower = {t.lower() for t in self.allowed_tools_allowlist}
        allowlist_parent_lower = {tool_parent_name(t).lower() for t in self.allowed_tools_allowlist}
        for tool in allowed_tools:
            tool_lower = tool.lower()
            parent_lower = tool_parent_name(tool).lower()
            if tool_lower not in allowlist_lower and parent_lower not in allowlist_parent_lower:
                violations.append(PolicyViolation(
                    rule="tool_not_in_allowlist",
                    message=f"Tool {tool!r} is not in the company allowlist",
                    blocking=False,
                    # 保存本次允许列表，供历史报告按实际扫描依据展示。
                    params={"tool": tool, "allowed_tools_allowlist": list(self.allowed_tools_allowlist)},
                ))

        declared_lower = {t.lower() for t in allowed_tools}
        declared_parent_lower = {tool_parent_name(t).lower() for t in allowed_tools}
        for perm in self.blocked_permissions:
            perm_lower = perm.lower()
            if perm_lower in declared_lower or perm_lower in declared_parent_lower:
                violations.append(PolicyViolation(
                    rule="blocked_permission",
                    message=f"Tool/permission {perm!r} is explicitly blocked by policy",
                    blocking=True,
                ))

        return violations

    def decide(
        self,
        risk_level: RiskLevel,
        violations: list[PolicyViolation],
    ) -> SkillStatus:
        """Apply admission actions to final risk after blocking permission checks."""
        blocking = [v for v in violations if v.blocking]
        if blocking:
            return SkillStatus.REJECTED

        auto_reject = _normalized_policy_risks(
            self._data.get("auto_reject_risk", ["malicious"])
        )
        require_review = _normalized_policy_risks(
            self._data.get("require_human_review", ["suspicious"])
        )
        if risk_level in auto_reject:
            return SkillStatus.REJECTED
        if risk_level in require_review:
            return SkillStatus.VETTED

        auto_approve = _normalized_policy_risks(self._data["auto_approve_risk"])
        if risk_level in {RiskLevel.BENIGN, RiskLevel.SUSPICIOUS} and risk_level in auto_approve:
            return SkillStatus.APPROVED

        if risk_level == RiskLevel.MALICIOUS:
            return SkillStatus.REJECTED
        if risk_level == RiskLevel.SUSPICIOUS:
            return SkillStatus.VETTED
        return SkillStatus.APPROVED


def _finding_policy_keys(finding: dict[str, Any]) -> list[str]:
    rule = str(finding.get("rule") or finding.get("rule_id") or "").strip().lower()
    category = str(finding.get("category") or "").strip().lower()
    file_path = str(finding.get("file") or finding.get("file_path") or "").strip().lower()
    text = " ".join(
        str(finding.get(key) or "")
        for key in ("title", "message", "evidence", "category", "pattern", "finding", "explanation", "code_snippet")
    ).lower()
    haystack = f"{rule} {category} {text}"

    keys: list[str] = []
    if _is_documented_external_api_example(rule, file_path, haystack):
        return ["documented_external_api"]
    if rule in {"dependency_missing", "missing_dependency"} or category == "dependency":
        keys.append("dependency")
    if category == "runtime":
        keys.append("runtime")
    if "数据外传" in haystack or "data exfiltration" in haystack or "exfiltrat" in haystack or rule in {"data_exfiltration", "credential_exfiltration", "e1", "e2", "e3"}:
        keys.append("data_exfiltration")
    if "credential access" in haystack or "凭据访问" in haystack or "窃取凭据" in haystack or "steal credential" in haystack or rule == "credential_file_access":
        keys.append("credential_access")
    if "prompt injection" in haystack or "提示词注入" in haystack or "system prompt" in haystack or "系统提示词" in haystack:
        keys.append("prompt_injection")
    if "tool misuse" in haystack or "工具投毒" in haystack or "工具滥用" in haystack or rule == "agent_manager_bypass":
        keys.append("tool_misuse")
    if "supply chain" in haystack or "供应链" in haystack or "download and execute" in haystack or "下载后执行" in haystack or rule == "download_and_execute":
        keys.append("supply_chain")
    if category == "network" or "network access" in haystack or "网络访问" in haystack:
        keys.append("network")
    if rule in {"dynamic_code_execution", "os_command_execution", "subprocess_shell_true"} or "动态代码执行" in haystack:
        keys.append("dynamic_execution")
    if "最小权限" in haystack or "通配权限" in haystack or rule in {"tool_not_in_allowlist", "blocked_permission"}:
        keys.append("excessive_permissions")
    return keys


def _is_documented_external_api_example(rule: str, file_path: str, haystack: str) -> bool:
    if rule != "e1":
        return False
    if Path(file_path).name not in {"skill.md", "skill-card.md"}:
        return False
    if "http://" not in haystack and "https://" not in haystack:
        return False
    return any(token in haystack for token in ("curl ", "api ", "endpoint", "端点", "接口"))
