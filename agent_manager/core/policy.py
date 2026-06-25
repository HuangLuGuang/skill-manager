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

logger = logging.getLogger(__name__)

_DEFAULT_POLICY: dict[str, Any] = {
    "auto_approve_max_risk": "benign",
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
        return self._data["scanner_policy"]

    @property
    def skillspector_enabled(self) -> bool:
        return bool(self._data.get("skillspector_enabled", False))

    @property
    def skillspector_timeout_seconds(self) -> int:
        return int(self._data.get("skillspector_timeout_seconds", 120))

    @property
    def skillspector_use_llm(self) -> bool:
        return bool(self._data.get("skillspector_use_llm", False))

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
            ))

        allowlist_lower = {t.lower() for t in self.allowed_tools_allowlist}
        for tool in allowed_tools:
            if tool.lower() not in allowlist_lower:
                violations.append(PolicyViolation(
                    rule="tool_not_in_allowlist",
                    message=f"Tool {tool!r} is not in the company allowlist",
                ))

        for perm in self.blocked_permissions:
            if perm.lower() in [t.lower() for t in allowed_tools]:
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
        """
        Determine the initial status after vetting based on final risk level.

        Returns:
            REJECTED   — risk is malicious or has blocking violations
            VETTED     — risk is suspicious
            APPROVED   — risk is benign
        """
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

        # A malformed or incomplete policy must never turn elevated risk into
        # an approval merely because no configured value matched.
        if risk_level == RiskLevel.MALICIOUS:
            return SkillStatus.REJECTED
        if risk_level == RiskLevel.SUSPICIOUS:
            return SkillStatus.VETTED
        return SkillStatus.APPROVED
