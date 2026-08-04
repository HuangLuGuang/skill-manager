"""
Data models for agent prompt lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from .models import RiskLevel, VettingResult


class PromptStatus(str, Enum):
    """Lifecycle state of an agent prompt."""

    PENDING = "PENDING"
    VETTED = "VETTED"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class PromptEntry(BaseModel):
    """An agent prompt record in the registry."""

    prompt_id: str                      # UUID
    name: str                           # Unique prompt name
    description: str = ""               # Human-readable description
    agent_id: str = ""                  # Target agent identifier
    content: str = ""                   # The actual prompt text
    status: PromptStatus = PromptStatus.PENDING
    risk_level: Optional[RiskLevel] = None
    vetting: Optional[VettingResult] = None

    # Signing
    signature: Optional[str] = None     # Ed25519 envelope over the content digest

    # Timestamps
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    deployed_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None

    # Review
    approved_by: Optional[str] = None
    approval_note: Optional[str] = None
    rejection_reason: Optional[str] = None
    retire_reason: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("prompt name must not be empty")
        return v.strip()

    def is_loadable(self) -> bool:
        return self.status in (PromptStatus.APPROVED, PromptStatus.DEPLOYED)

    def summary(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "name": self.name,
            "description": self.description,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "risk_level": self.risk_level.value if self.risk_level else None,
            "approved_by": self.approved_by,
            "submitted_at": self.submitted_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
        }


class PromptAuditEvent(BaseModel):
    """An immutable audit log entry for prompts."""

    event_id: str
    event_type: str
    prompt_id: str
    prompt_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)

    def to_log_line(self) -> str:
        return (
            f"[{self.timestamp.isoformat()}] {self.event_type} "
            f"prompt={self.prompt_name!r} actor={self.actor!r} "
            f"details={self.details}"
        )


class PromptReviewRequest(BaseModel):
    """A pending human review request for a prompt."""

    prompt_id: str
    prompt_name: str
    risk_level: RiskLevel
    findings_summary: dict[str, int]
    submitted_at: datetime
    queued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None


def make_prompt_event(
    event_type: str,
    entry: PromptEntry,
    actor: str | None = None,
    details: dict[str, Any] | None = None,
) -> PromptAuditEvent:
    return PromptAuditEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        prompt_id=entry.prompt_id,
        prompt_name=entry.name,
        actor=actor,
        details=details or {},
    )
