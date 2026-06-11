"""Tests for core data models."""

from datetime import datetime, timezone

import pytest

from agent_manager.core.models import (
    AuditEvent,
    PolicyViolation,
    RegistryEntry,
    ReviewRequest,
    RiskLevel,
    SkillOrigin,
    SkillStatus,
    SourceInfo,
    VettingResult,
)


class TestRiskLevel:
    def test_from_severity_mapping(self):
        assert RiskLevel.from_severity("SAFE") == RiskLevel.BENIGN
        assert RiskLevel.from_severity("INFO") == RiskLevel.BENIGN
        assert RiskLevel.from_severity("LOW") == RiskLevel.SUSPICIOUS
        assert RiskLevel.from_severity("MEDIUM") == RiskLevel.SUSPICIOUS
        assert RiskLevel.from_severity("HIGH") == RiskLevel.MALICIOUS
        assert RiskLevel.from_severity("CRITICAL") == RiskLevel.MALICIOUS

    def test_from_severity_case_insensitive(self):
        assert RiskLevel.from_severity("safe") == RiskLevel.BENIGN
        assert RiskLevel.from_severity("Critical") == RiskLevel.MALICIOUS

    def test_is_at_least(self):
        assert RiskLevel.MALICIOUS.is_at_least(RiskLevel.SUSPICIOUS)
        assert RiskLevel.MALICIOUS.is_at_least(RiskLevel.MALICIOUS)
        assert not RiskLevel.SUSPICIOUS.is_at_least(RiskLevel.MALICIOUS)
        assert not RiskLevel.BENIGN.is_at_least(RiskLevel.SUSPICIOUS)


class TestRegistryEntry:
    def _make_entry(self, status=SkillStatus.APPROVED):
        return RegistryEntry(
            skill_id="test-id-1234",
            name="my-skill",
            description="Does things",
            source=SourceInfo(origin=SkillOrigin.LOCAL),
            status=status,
        )

    def test_is_loadable_approved(self):
        entry = self._make_entry(SkillStatus.APPROVED)
        assert entry.is_loadable()

    def test_is_loadable_deployed(self):
        entry = self._make_entry(SkillStatus.DEPLOYED)
        assert entry.is_loadable()

    def test_not_loadable_vetted(self):
        entry = self._make_entry(SkillStatus.VETTED)
        assert not entry.is_loadable()

    def test_not_loadable_rejected(self):
        entry = self._make_entry(SkillStatus.REJECTED)
        assert not entry.is_loadable()

    def test_not_loadable_retired(self):
        entry = self._make_entry(SkillStatus.RETIRED)
        assert not entry.is_loadable()

    def test_name_stripped(self):
        entry = self._make_entry()
        entry.name = "  my-skill  "
        # Validator strips on construction
        entry2 = RegistryEntry(
            skill_id="x", name="  spaced  ", description="d",
            source=SourceInfo(), status=SkillStatus.APPROVED,
        )
        assert entry2.name == "spaced"

    def test_empty_name_rejected(self):
        with pytest.raises(Exception):
            RegistryEntry(
                skill_id="x", name="   ", description="d",
                source=SourceInfo(), status=SkillStatus.APPROVED,
            )

    def test_summary_keys(self):
        entry = self._make_entry()
        s = entry.summary()
        assert "skill_id" in s
        assert "status" in s
        assert "risk_level" in s

    def test_model_validate_accepts_legacy_severity_risk_level(self):
        entry = RegistryEntry.model_validate(
            {
                "skill_id": "legacy-id",
                "name": "legacy-skill",
                "description": "legacy payload",
                "source": {"origin": "local"},
                "status": "APPROVED",
                "risk_level": "HIGH",
            }
        )
        assert entry.risk_level == RiskLevel.MALICIOUS


class TestAuditEvent:
    def test_to_log_line(self):
        ev = AuditEvent(
            event_id="ev-1",
            event_type="skill_approved",
            skill_id="s-1",
            skill_name="my-skill",
            actor="alice",
            details={"note": "LGTM"},
        )
        line = ev.to_log_line()
        assert "skill_approved" in line
        assert "my-skill" in line
        assert "alice" in line
