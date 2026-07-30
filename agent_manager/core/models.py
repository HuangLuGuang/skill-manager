"""
Data models for the agent manager lifecycle.

Tracks skills from submission through vetting, approval, deployment, and retirement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    """Risk classification assigned after vetting."""

    BENIGN = "benign"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"

    @classmethod
    def _missing_(cls, value: object) -> "RiskLevel" | None:
        """Accept legacy severity-style values when reading persisted payloads."""
        if not isinstance(value, str):
            return None

        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member

        severity = value.strip().upper()
        if not severity:
            return None
        return cls.from_severity(severity)

    @classmethod
    def from_severity(cls, severity: str) -> "RiskLevel":
        """Map skill-scanner Severity to RiskLevel.
        
        Mapping rules:
        - SAFE, INFO, LOW → benign
        - MEDIUM → suspicious
        - HIGH, EXTREME → malicious
        """
        upper_severity = severity.upper() if severity else ""
        
        if upper_severity in ("SAFE", "INFO", "LOW"):
            return cls.BENIGN
        elif upper_severity in ("HIGH", "CRITICAL", "EXTREME"):
            return cls.MALICIOUS
        else:
            # MEDIUM or any unknown value → suspicious
            return cls.SUSPICIOUS

    def is_at_least(self, other: "RiskLevel") -> bool:
        order = [RiskLevel.BENIGN, RiskLevel.SUSPICIOUS, RiskLevel.MALICIOUS]
        return order.index(self) >= order.index(other)


class SkillStatus(str, Enum):
    """Lifecycle state of a skill in the registry."""

    PENDING = "PENDING"       # Submitted, vetting in progress
    VETTED = "VETTED"         # Scanned, awaiting human review
    APPROVED = "APPROVED"     # Approved and signed, ready to deploy
    DEPLOYED = "DEPLOYED"     # Active in production
    REJECTED = "REJECTED"     # Rejected at gate
    RETIRED = "RETIRED"       # Withdrawn from use


class SkillOrigin(str, Enum):
    """Where the skill came from."""

    LOCAL = "local"
    GITHUB = "github"
    CLAWHUB = "clawhub"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class SourceInfo(BaseModel):
    """Provenance information for a skill."""

    origin: SkillOrigin = SkillOrigin.UNKNOWN
    author: Optional[str] = None
    channel: Optional[str] = None
    url: Optional[str] = None
    version: Optional[str] = None
    commit_sha: Optional[str] = None
    token_name: Optional[str] = None


class VettingResult(BaseModel):
    """Output of the vetting pipeline for a skill."""

    risk_level: RiskLevel = RiskLevel.BENIGN
    findings_count: int = 0
    analyzers_used: list[str] = Field(default_factory=list)
    sandbox_triggered: bool = False
    sandbox_required_by_policy: bool = False
    sandbox_runtime: Optional[str] = None
    scan_duration_seconds: float = 0.0
    vetted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Full scan report (serialized ScanResult.to_dict())
    scan_report: dict[str, Any] = Field(default_factory=dict)
    # Vetting notes from policy checks
    policy_notes: list[str] = Field(default_factory=list)


class RegistryEntry(BaseModel):
    """A skill record in the registry."""

    skill_id: str                       # UUID
    family_id: Optional[str] = None      # Stable identity shared by all versions
    version_no: int = 1
    source_version: Optional[str] = None
    name: str                           # From SKILL.md manifest
    description: str                    # From SKILL.md manifest
    source: SourceInfo
    skill_path: Optional[str] = None       # Absolute path (local skills)
    status: SkillStatus = SkillStatus.PENDING
    risk_level: Optional[RiskLevel] = None
    vetting: Optional[VettingResult] = None
    allowed_tools: list[str] = Field(default_factory=list)
    declared_tools_valid: bool = True   # All declared tools are in policy allowlist

    # Signing
    signature: Optional[str] = None        # HMAC-SHA256 of skill content tree

    # Timestamps
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    deployed_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None

    # Review
    approved_by: Optional[str] = None
    approval_note: Optional[str] = None
    rejection_reason: Optional[str] = None
    retire_reason: Optional[str] = None

    # Scan cache / dedupe metadata
    content_fingerprint: Optional[str] = None
    scan_context_fingerprint: Optional[str] = None
    scan_cache_key: Optional[str] = None
    scan_reused: bool = False
    reused_from_skill_id: Optional[str] = None
    latest_version: bool = False
    latest_trusted_version: bool = False

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("skill name must not be empty")
        return v.strip()

    def is_loadable(self) -> bool:
        """True if the skill can be loaded by an agent."""
        return self.status in (SkillStatus.APPROVED, SkillStatus.DEPLOYED)

    def summary(self) -> dict[str, Any]:
        return {
            "skill_id": self.family_id or self.skill_id,
            "version_id": self.skill_id,
            "version_no": self.version_no,
            "source_version": self.source_version,
            "name": self.name,
            "status": self.status.value,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "vetting": {
                "sandbox_triggered": self.vetting.sandbox_triggered if self.vetting else False,
                "sandbox_required_by_policy": self.vetting.sandbox_required_by_policy if self.vetting else False,
                "sandbox_runtime": self.vetting.sandbox_runtime if self.vetting else None,
            } if self.vetting else None,
            "sandbox_triggered": self.vetting.sandbox_triggered if self.vetting else False,
            "sandbox_required_by_policy": self.vetting.sandbox_required_by_policy if self.vetting else False,
            "sandbox_runtime": self.vetting.sandbox_runtime if self.vetting else None,
            "approved_by": self.approved_by,
            "rejection_reason": self.rejection_reason,
            "submitted_at": self.submitted_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
        }


class ScanRun(BaseModel):
    """One persistent scan execution record for a concrete Skill version."""

    scan_run_id: str
    version_id: str
    scan_context_fingerprint: str
    status: str = "PENDING"
    forced: bool = False
    reused_from_scan_run_id: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    result: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(BaseModel):
    """An immutable audit log entry."""

    event_id: str
    event_type: str   # skill_submitted | skill_vetted | skill_approved | skill_rejected
                      # skill_deployed | skill_retired | skill_load_allowed
                      # skill_load_blocked | tool_invoked | tool_blocked
    skill_id: str
    skill_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Optional[str] = None     # user or agent ID
    details: dict[str, Any] = Field(default_factory=dict)

    def to_log_line(self) -> str:
        return (
            f"[{self.timestamp.isoformat()}] {self.event_type} "
            f"skill={self.skill_name!r} actor={self.actor!r} "
            f"details={self.details}"
        )


class PolicyViolation(BaseModel):
    """A policy check failure."""

    rule: str
    message: str
    blocking: bool = True     # If True, prevents approval


class ReviewRequest(BaseModel):
    """A pending human review request."""

    skill_id: str
    skill_name: str
    risk_level: RiskLevel
    findings_summary: dict[str, int]   # severity -> count
    submitted_at: datetime
    queued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None
