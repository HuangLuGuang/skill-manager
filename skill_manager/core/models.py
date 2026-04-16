"""
Data models for the skill manager lifecycle.

Tracks skills from submission through vetting, approval, deployment, and retirement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, Enum):
    """Risk classification assigned after vetting."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"

    @classmethod
    def from_severity(cls, severity: str) -> "RiskLevel":
        """Map skill-scanner Severity to RiskLevel."""
        mapping = {
            "SAFE": cls.LOW,
            "INFO": cls.LOW,
            "LOW": cls.LOW,
            "MEDIUM": cls.MEDIUM,
            "HIGH": cls.HIGH,
            "CRITICAL": cls.EXTREME,
        }
        return mapping.get(severity.upper(), cls.HIGH)

    def is_at_least(self, other: "RiskLevel") -> bool:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.EXTREME]
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
    author: str | None = None
    url: str | None = None
    version: str | None = None
    commit_sha: str | None = None


class VettingResult(BaseModel):
    """Output of the vetting pipeline for a skill."""

    risk_level: RiskLevel
    max_severity: str
    findings_count: int
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    analyzers_used: list[str] = Field(default_factory=list)
    sandbox_triggered: bool = False
    sandbox_required_by_policy: bool = False
    sandbox_runtime: str | None = None
    scan_duration_seconds: float = 0.0
    vetted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Full scan report (serialized ScanResult.to_dict())
    scan_report: dict[str, Any] = Field(default_factory=dict)
    # Vetting notes from policy checks
    policy_notes: list[str] = Field(default_factory=list)


class RegistryEntry(BaseModel):
    """A skill record in the registry."""

    skill_id: str                       # UUID
    name: str                           # From SKILL.md manifest
    description: str                    # From SKILL.md manifest
    source: SourceInfo
    skill_path: str | None = None       # Absolute path (local skills)
    status: SkillStatus = SkillStatus.PENDING
    risk_level: RiskLevel | None = None
    vetting: VettingResult | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    declared_tools_valid: bool = True   # All declared tools are in policy allowlist

    # Signing
    signature: str | None = None        # HMAC-SHA256 of skill content tree

    # Timestamps
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: datetime | None = None
    deployed_at: datetime | None = None
    retired_at: datetime | None = None

    # Review
    approved_by: str | None = None
    approval_note: str | None = None
    rejection_reason: str | None = None
    retire_reason: str | None = None

    # Scan cache / dedupe metadata
    content_fingerprint: str | None = None
    scan_context_fingerprint: str | None = None
    scan_cache_key: str | None = None
    scan_reused: bool = False
    reused_from_skill_id: str | None = None

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
            "skill_id": self.skill_id,
            "name": self.name,
            "status": self.status.value,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "sandbox_triggered": self.vetting.sandbox_triggered if self.vetting else False,
            "sandbox_required_by_policy": self.vetting.sandbox_required_by_policy if self.vetting else False,
            "sandbox_runtime": self.vetting.sandbox_runtime if self.vetting else None,
            "approved_by": self.approved_by,
            "submitted_at": self.submitted_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
        }


class AuditEvent(BaseModel):
    """An immutable audit log entry."""

    event_id: str
    event_type: str   # skill_submitted | skill_vetted | skill_approved | skill_rejected
                      # skill_deployed | skill_retired | skill_load_allowed
                      # skill_load_blocked | tool_invoked | tool_blocked
    skill_id: str
    skill_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str | None = None     # user or agent ID
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
    notes: str | None = None
