"""
Vetting pipeline — wraps skill-scanner and applies company policy checks.

Produces a VettingResult with risk level, findings summary, and policy notes.
Falls back to a basic static check if skill-scanner is not installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .models import PolicyViolation, RiskLevel, SourceInfo, VettingResult

if TYPE_CHECKING:
    from .policy import CompanyPolicy

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Scanner integration                                                           #
# --------------------------------------------------------------------------- #

def _try_import_scanner():
    try:
        from skill_scanner import SkillScanner
        from skill_scanner.core.scan_policy import ScanPolicy
        return SkillScanner, ScanPolicy
    except ImportError:
        return None, None


def _run_scanner(skill_path: Path, scanner_policy_name: str) -> dict:
    """Run skill-scanner and return the serialized ScanResult dict."""
    SkillScanner, ScanPolicy = _try_import_scanner()
    if SkillScanner is None:
        logger.warning("skill-scanner not installed — using basic file check only")
        return {}

    try:
        policy = ScanPolicy.from_preset(scanner_policy_name)
    except Exception:
        policy = ScanPolicy.default()

    scanner = SkillScanner(policy=policy)
    result = scanner.scan_skill(str(skill_path))
    return result.to_dict()


# --------------------------------------------------------------------------- #
# Manifest loading (no scanner dependency)                                      #
# --------------------------------------------------------------------------- #

def _load_manifest(skill_path: Path) -> tuple[str, str, list[str], str | None]:
    """
    Parse SKILL.md frontmatter.
    Returns (name, description, allowed_tools, license).
    Raises ValueError if SKILL.md is missing or unparseable.
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"SKILL.md not found in {skill_path}")

    try:
        import frontmatter
        post = frontmatter.load(str(skill_md))
        name = post.get("name") or post.get("skill-name") or skill_path.name
        description = post.get("description") or ""
        raw_tools = post.get("allowed-tools") or post.get("allowed_tools") or []
        if isinstance(raw_tools, str):
            raw_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        license_val = post.get("license")
        return str(name), str(description), list(raw_tools), license_val
    except ImportError:
        # Fallback: read SKILL.md manually
        content = skill_md.read_text(encoding="utf-8")
        name = skill_path.name
        description = ""
        allowed_tools: list[str] = []
        license_val = None

        in_frontmatter = False
        fm_lines: list[str] = []
        for i, line in enumerate(content.splitlines()):
            if i == 0 and line.strip() == "---":
                in_frontmatter = True
                continue
            if in_frontmatter:
                if line.strip() == "---":
                    break
                fm_lines.append(line)

        for line in fm_lines:
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"\'')
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"\'')
            elif line.startswith("license:"):
                license_val = line.split(":", 1)[1].strip().strip('"\'')

        return name, description, allowed_tools, license_val


# --------------------------------------------------------------------------- #
# Policy checks (independent of scanner)                                        #
# --------------------------------------------------------------------------- #

def _check_manifest_policy(
    allowed_tools: list[str],
    license_val: str | None,
    policy: "CompanyPolicy",
) -> list[PolicyViolation]:
    violations: list[PolicyViolation] = []

    if policy._data.get("require_license") and not license_val:
        violations.append(PolicyViolation(
            rule="require_license",
            message="Skill manifest is missing a 'license' field (required by policy)",
            blocking=False,
        ))

    accepted = [l.lower() for l in policy._data.get("accepted_licenses", [])]
    if license_val and accepted and license_val.lower() not in accepted:
        violations.append(PolicyViolation(
            rule="unaccepted_license",
            message=f"License {license_val!r} is not in the accepted list: {policy._data['accepted_licenses']}",
            blocking=False,
        ))

    tool_violations = policy.check_tool_declarations(allowed_tools)
    violations.extend(tool_violations)

    return violations


# --------------------------------------------------------------------------- #
# Main vetting entry point                                                      #
# --------------------------------------------------------------------------- #

class VettingPipeline:
    """Orchestrates scanning and policy checks to produce a VettingResult."""

    def __init__(self, policy: "CompanyPolicy"):
        self.policy = policy

    def vet(
        self,
        skill_path: Path,
        source: SourceInfo,
        use_behavioral: bool = False,
        use_llm: bool = False,
    ) -> tuple[VettingResult, list[PolicyViolation], str, str, list[str]]:
        """
        Run the full vetting pipeline.

        Returns:
            (VettingResult, violations, name, description, allowed_tools)
        """
        skill_path = Path(skill_path).resolve()

        # 1. Parse manifest
        try:
            name, description, allowed_tools, license_val = _load_manifest(skill_path)
        except ValueError as e:
            raise ValueError(f"Cannot vet skill: {e}") from e

        # 2. Run scanner
        scan_report = _run_scanner(skill_path, self.policy.scanner_policy)

        # 3. Derive risk level
        max_severity = scan_report.get("max_severity", "SAFE")
        risk_level = RiskLevel.from_severity(max_severity)

        findings = scan_report.get("findings", [])
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev = f.get("severity", "INFO").lower()
            if sev in counts:
                counts[sev] += 1

        # 4. Policy checks
        violations = _check_manifest_policy(allowed_tools, license_val, self.policy)

        policy_notes: list[str] = []
        for v in violations:
            prefix = "[BLOCK]" if v.blocking else "[WARN]"
            policy_notes.append(f"{prefix} {v.rule}: {v.message}")

        # 5. Build result
        result = VettingResult(
            risk_level=risk_level,
            max_severity=max_severity,
            findings_count=len(findings),
            critical_count=counts["critical"],
            high_count=counts["high"],
            medium_count=counts["medium"],
            low_count=counts["low"],
            analyzers_used=scan_report.get("analyzers_used", ["basic"]),
            scan_duration_seconds=scan_report.get("scan_duration_seconds", 0.0),
            scan_report=scan_report,
            policy_notes=policy_notes,
        )

        return result, violations, name, description, allowed_tools
