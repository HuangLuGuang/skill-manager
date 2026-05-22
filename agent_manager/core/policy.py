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
    "auto_approve_max_risk": "LOW",
    "require_human_review": ["HIGH", "EXTREME"],
    "auto_reject_risk": ["EXTREME"],
    "require_sandbox_for_risk": ["HIGH", "EXTREME"],
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
}


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
    def auto_approve_max_risk(self) -> RiskLevel:
        return RiskLevel(self._data["auto_approve_max_risk"])

    @property
    def require_human_review(self) -> list[RiskLevel]:
        return [RiskLevel(r) for r in self._data["require_human_review"]]

    @property
    def auto_reject_risk(self) -> list[RiskLevel]:
        return [RiskLevel(r) for r in self._data["auto_reject_risk"]]

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

    def requires_sandbox(self, risk_level: RiskLevel) -> bool:
        return risk_level in self.require_sandbox_for_risk

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
        source: SourceInfo,
        violations: list[PolicyViolation],
    ) -> SkillStatus:
        """
        Determine the initial status after vetting.

        Returns:
            REJECTED   — auto-reject risk or blocking violations
            VETTED     — needs human review
            APPROVED   — auto-approved
        """
        blocking = [v for v in violations if v.blocking]
        if blocking:
            return SkillStatus.REJECTED

        if risk_level in self.auto_reject_risk:
            return SkillStatus.REJECTED

        if risk_level in self.require_human_review:
            # Trusted authors with MEDIUM can skip review
            if risk_level == RiskLevel.MEDIUM and source.author in self.trusted_authors:
                return SkillStatus.APPROVED
            return SkillStatus.VETTED

        # Auto-approve if at or below threshold
        threshold = self.auto_approve_max_risk
        if not risk_level.is_at_least(RiskLevel.MEDIUM) or not threshold.is_at_least(RiskLevel.MEDIUM):
            return SkillStatus.APPROVED
        if risk_level == threshold or not risk_level.is_at_least(threshold):
            return SkillStatus.APPROVED

        return SkillStatus.VETTED
