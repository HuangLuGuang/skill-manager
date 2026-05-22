"""Tests for Prompt models — validation, enums, state machine."""

import pytest

from agent_manager.core.models import (
    RiskLevel,
    VettingResult,
)
from agent_manager.core.prompt_models import (
    PromptAuditEvent,
    PromptEntry,
    PromptReviewRequest,
    PromptStatus,
)


class TestPromptStatus:
    def test_pending_is_default(self):
        entry = PromptEntry(
            prompt_id="p-001",
            name="test-prompt",
            agent_id="agent-1",
        )
        assert entry.status == PromptStatus.PENDING

    def test_lifecycle_state_machine(self):
        # Valid transitions for a prompt
        assert PromptStatus.PENDING.value == "PENDING"
        assert PromptStatus.VETTED.value == "VETTED"
        assert PromptStatus.APPROVED.value == "APPROVED"
        assert PromptStatus.DEPLOYED.value == "DEPLOYED"
        assert PromptStatus.REJECTED.value == "REJECTED"
        assert PromptStatus.RETIRED.value == "RETIRED"

    def test_is_loadable(self):
        entry = PromptEntry(prompt_id="p-001", name="test", agent_id="a1")
        entry.status = PromptStatus.PENDING
        assert not entry.is_loadable()
        entry.status = PromptStatus.VETTED
        assert not entry.is_loadable()
        entry.status = PromptStatus.APPROVED
        assert entry.is_loadable()
        entry.status = PromptStatus.DEPLOYED
        assert entry.is_loadable()
        entry.status = PromptStatus.REJECTED
        assert not entry.is_loadable()
        entry.status = PromptStatus.RETIRED
        assert not entry.is_loadable()


class TestPromptEntry:
    def test_name_required(self):
        with pytest.raises(ValueError, match="prompt name must not be empty"):
            PromptEntry(prompt_id="p-001", name="", agent_id="a1")

        with pytest.raises(ValueError, match="prompt name must not be empty"):
            PromptEntry(prompt_id="p-001", name="   ", agent_id="a1")

    def test_name_stripped(self):
        entry = PromptEntry(prompt_id="p-001", name="  my-prompt  ", agent_id="a1")
        assert entry.name == "my-prompt"

    def test_full_entry_serialization(self):
        vetting = VettingResult(
            verdict="benign",
            findings_count=2,
            analyzers_used=["llm", "regex"],
        )
        entry = PromptEntry(
            prompt_id="p-001",
            name="customer-service-prompt",
            description="System prompt for customer service agent",
            agent_id="cs-agent-v2",
            content="You are a helpful customer service assistant. Be polite and professional.",
            status=PromptStatus.APPROVED,
            risk_level=RiskLevel.LOW,
            vetting=vetting,
            signature="abc123def456",
            approved_by="auto-policy",
        )
        data = entry.model_dump(mode="json")
        assert data["prompt_id"] == "p-001"
        assert data["status"] == "APPROVED"
        assert data["risk_level"] == "LOW"
        assert data["content"] == "You are a helpful customer service assistant. Be polite and professional."

    def test_summary_excludes_content(self):
        entry = PromptEntry(
            prompt_id="p-001",
            name="test",
            agent_id="a1",
            content="secret prompt text",
            status=PromptStatus.APPROVED,
            risk_level=RiskLevel.LOW,
        )
        summary = entry.summary()
        assert "prompt_id" in summary
        assert "name" in summary
        assert "status" in summary
        assert "content" not in summary, "summary must not expose prompt content"

    def test_two_prompts_same_name_different_agents(self):
        a = PromptEntry(prompt_id="p-1", name="shared-name", agent_id="agent-a")
        b = PromptEntry(prompt_id="p-2", name="shared-name", agent_id="agent-b")
        assert a.name == b.name
        assert a.agent_id != b.agent_id
        assert a.prompt_id != b.prompt_id


class TestPromptAuditEvent:
    def test_create_event(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        event = PromptAuditEvent(
            event_id="evt-001",
            event_type="prompt_submitted",
            prompt_id="p-001",
            prompt_name="test-prompt",
            timestamp=now,
            actor="admin",
            details={"agent_id": "agent-1"},
        )
        assert event.event_type == "prompt_submitted"
        assert event.prompt_name == "test-prompt"
        assert event.actor == "admin"

    def test_to_log_line(self):
        from datetime import datetime, timezone

        event = PromptAuditEvent(
            event_id="evt-001",
            event_type="prompt_approved",
            prompt_id="p-001",
            prompt_name="test-prompt",
            timestamp=datetime.now(timezone.utc),
            actor="admin",
        )
        log = event.to_log_line()
        assert "prompt_approved" in log
        assert "test-prompt" in log
        assert "admin" in log


class TestPromptReviewRequest:
    def test_create(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        req = PromptReviewRequest(
            prompt_id="p-001",
            prompt_name="test-prompt",
            risk_level=RiskLevel.HIGH,
            findings_summary={"total": 3, "CRITICAL": 1, "HIGH": 2},
            submitted_at=now,
            notes="Found prompt injection patterns",
        )
        data = req.model_dump(mode="json")
        assert data["risk_level"] == "HIGH"
        assert data["findings_summary"]["total"] == 3
        assert data["notes"] == "Found prompt injection patterns"


class TestRiskLevelMapping:
    def test_from_severity(self):
        assert RiskLevel.from_severity("SAFE") == RiskLevel.LOW
        assert RiskLevel.from_severity("INFO") == RiskLevel.LOW
        assert RiskLevel.from_severity("LOW") == RiskLevel.LOW
        assert RiskLevel.from_severity("MEDIUM") == RiskLevel.MEDIUM
        assert RiskLevel.from_severity("HIGH") == RiskLevel.HIGH
        assert RiskLevel.from_severity("CRITICAL") == RiskLevel.EXTREME

    def test_is_at_least(self):
        assert RiskLevel.HIGH.is_at_least(RiskLevel.MEDIUM)
        assert RiskLevel.HIGH.is_at_least(RiskLevel.HIGH)
        assert not RiskLevel.LOW.is_at_least(RiskLevel.HIGH)
        assert RiskLevel.EXTREME.is_at_least(RiskLevel.LOW)
