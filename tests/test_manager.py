"""Integration tests for the AgentManager high-level API."""

import textwrap
from pathlib import Path

import pytest

from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RiskLevel, SkillOrigin, SkillStatus, SourceInfo, VettingResult
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.registry import Registry


@pytest.fixture
def skill_dir(tmp_path):
    d = tmp_path / "my-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: my-skill
        description: A safe test skill
        license: MIT
        allowed-tools: Read, Grep
        ---
        # My Skill
        Reads files only.
    """))
    return d


@pytest.fixture
def mgr(tmp_path):
    policy = CompanyPolicy({"auto_approve_max_risk": "MEDIUM"})
    registry = Registry(data_dir=tmp_path / "registry")
    return AgentManager(policy=policy, registry=registry)


class TestSubmit:
    def test_submit_creates_entry(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        assert entry.skill_id
        assert entry.name == "my-skill"
        assert entry.status in SkillStatus.__members__.values()

    def test_submit_auto_approves_low_risk(self, mgr, skill_dir):
        # With no scanner installed, risk defaults to LOW → auto-approved
        entry = mgr.submit(skill_dir)
        assert entry.status == SkillStatus.APPROVED
        assert entry.signature is not None

    def test_submit_registers_in_registry(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        found = mgr.get_skill(entry.skill_id)
        assert found is not None
        assert found.name == entry.name

    def test_submit_logs_audit(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        events = mgr.audit()
        types = {e.event_type for e in events}
        assert "skill_submitted" in types

    def test_submit_missing_path_raises(self, mgr, tmp_path):
        with pytest.raises(Exception):
            mgr.submit(tmp_path / "nonexistent")


class TestApproveReject:
    def test_approve_vetted_skill(self, tmp_path, skill_dir):
        policy = CompanyPolicy({"auto_approve_max_risk": "LOW", "require_human_review": ["MEDIUM", "HIGH", "EXTREME"]})
        registry = Registry(data_dir=tmp_path / "reg")
        mgr = AgentManager(policy=policy, registry=registry)

        # Force VETTED by making scanner return MEDIUM (we mock via low threshold)
        # In practice, without scanner, LOW → APPROVED; we test the approve path via direct status manipulation
        entry = mgr.submit(skill_dir)
        if entry.status == SkillStatus.APPROVED:
            # Manually move to VETTED for test
            entry.status = SkillStatus.VETTED
            registry.update(entry)
            registry.enqueue_review(
                __import__("agent_manager.core.models", fromlist=["ReviewRequest"]).ReviewRequest(
                    skill_id=entry.skill_id,
                    skill_name=entry.name,
                    risk_level=RiskLevel.SUSPICIOUS,
                    findings_summary={},
                    submitted_at=entry.submitted_at,
                )
            )

        entry = mgr.approve(entry.skill_id, approver="alice", note="LGTM")
        assert entry.status == SkillStatus.APPROVED
        assert entry.approved_by == "alice"
        assert entry.signature is not None

    def test_approve_wrong_status_raises(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        # Already APPROVED → can't approve again
        if entry.status == SkillStatus.APPROVED:
            with pytest.raises(ValueError, match="VETTED"):
                mgr.approve(entry.skill_id, approver="bob")

    def test_approve_low_risk_policy_rejection_as_manual_exception(self, tmp_path, skill_dir):
        policy = CompanyPolicy({
            "auto_approve_max_risk": "MEDIUM",
            "allowed_tools_allowlist": ["Read"],
        })
        registry = Registry(data_dir=tmp_path / "reg-policy-override")
        mgr = AgentManager(policy=policy, registry=registry)

        entry = mgr.submit(skill_dir)
        assert entry.status == SkillStatus.REJECTED
        assert entry.risk_level == RiskLevel.BENIGN
        assert entry.declared_tools_valid is False

        approved = mgr.approve(entry.skill_id, approver="alice", note="只读检索工具例外批准")
        assert approved.status == SkillStatus.APPROVED
        assert approved.approved_by == "alice"
        assert approved.signature is not None

        event = next(item for item in mgr.audit() if item.event_type == "skill_approved")
        assert event.details["manual_policy_override"] is True

    def test_approve_failed_submission_as_manual_exception(self, mgr, skill_dir):
        entry = mgr.create_pending_submission(skill_dir)
        failed = mgr.mark_submission_failed(entry.skill_id, "后台分析失败: decode error")

        assert failed.status == SkillStatus.REJECTED
        assert failed.vetting.scan_report["vetting_failed"] is True

        approved = mgr.approve(entry.skill_id, approver="alice", note="人工确认内容可接受")

        assert approved.status == SkillStatus.APPROVED
        assert approved.signature is not None
        event = next(item for item in mgr.audit() if item.event_type == "skill_approved")
        assert event.details["manual_policy_override"] is True

    def test_approve_legacy_failed_submission_by_rejection_reason(self, mgr, skill_dir):
        entry = mgr.create_pending_submission(skill_dir)
        entry.status = SkillStatus.REJECTED
        entry.rejection_reason = "后台分析失败: Cannot vet skill: decode error"
        mgr.registry.update(entry)

        approved = mgr.approve(entry.skill_id, approver="alice", note="人工确认内容可接受")

        assert approved.status == SkillStatus.APPROVED
        assert approved.signature is not None

    def test_reject_skill(self, tmp_path, skill_dir):
        policy = CompanyPolicy({"auto_approve_max_risk": "LOW"})
        registry = Registry(data_dir=tmp_path / "reg2")
        mgr = AgentManager(policy=policy, registry=registry)
        entry = mgr.submit(skill_dir)
        # Force to VETTED
        entry.status = SkillStatus.VETTED
        registry.update(entry)

        entry = mgr.reject(entry.skill_id, reviewer="security-team", reason="Found XSS")
        assert entry.status == SkillStatus.REJECTED
        assert "XSS" in entry.rejection_reason


class TestDeployRetire:
    def test_deploy_approved_skill(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        assert entry.status == SkillStatus.APPROVED
        entry = mgr.deploy(entry.skill_id)
        assert entry.status == SkillStatus.DEPLOYED
        assert entry.deployed_at is not None

    def test_deploy_unapproved_raises(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        entry.status = SkillStatus.VETTED
        mgr.registry.update(entry)
        with pytest.raises(ValueError, match="APPROVED"):
            mgr.deploy(entry.skill_id)

    def test_retire_by_id(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        mgr.deploy(entry.skill_id)
        retired = mgr.retire(entry.skill_id, reason="CVE-2026-0001")
        assert retired.status == SkillStatus.RETIRED
        assert retired.retire_reason == "CVE-2026-0001"

    def test_retire_by_name(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        retired = mgr.retire("my-skill", reason="deprecated")
        assert retired.status == SkillStatus.RETIRED

    def test_retire_unknown_raises(self, mgr):
        with pytest.raises(KeyError):
            mgr.retire("ghost-skill", reason="whatever")

    def test_retired_skill_not_loadable(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        mgr.retire(entry.skill_id, reason="test")
        allowed, _, _ = mgr.runtime.can_load(entry.name, verify_sig=False)
        assert not allowed


class TestListAndAudit:
    def test_list_skills(self, mgr, skill_dir):
        mgr.submit(skill_dir)
        skills = mgr.list_skills()
        assert len(skills) >= 1

    def test_list_skills_by_status(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)
        approved = mgr.list_skills(SkillStatus.APPROVED)
        assert any(e.skill_id == entry.skill_id for e in approved)

    def test_audit_returns_events(self, mgr, skill_dir):
        mgr.submit(skill_dir)
        events = mgr.audit()
        assert len(events) > 0

    def test_delete_skill_removes_registry_entry(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)

        mgr.delete_skill(entry.skill_id)

        assert mgr.get_skill(entry.skill_id) is None

    def test_rescan_skill_preserves_effective_result_until_process_completes(self, mgr, skill_dir):
        entry = mgr.submit(skill_dir)

        pending = mgr.rescan_skill(entry.skill_id)

        assert pending.status == SkillStatus.APPROVED
        assert pending.vetting is not None
        assert mgr.list_scan_runs(entry.skill_id)[0].status == "PENDING"
        processed = mgr.process_pending_submission(entry.skill_id, force_scan=True)
        assert processed.status == SkillStatus.APPROVED
        assert mgr.list_scan_runs(entry.skill_id)[0].status == "COMPLETED"

    def test_completed_nonapproved_rescan_clears_previous_trust_evidence(self, mgr, skill_dir, monkeypatch):
        entry = mgr.submit(skill_dir)
        assert entry.status == SkillStatus.APPROVED
        assert entry.signature is not None

        def vet_for_review(*_args, **_kwargs):
            return VettingResult(
                risk_level=RiskLevel.SUSPICIOUS,
                findings_count=1,
                policy_notes=["[LLM] analysis skipped: invalid JSON"],
                scan_report={"pre_llm_risk_level": "suspicious", "findings": []},
            ), [], "my-skill", "needs review", ["Read"]

        monkeypatch.setattr(mgr.vetting, "vet", vet_for_review)
        monkeypatch.setattr(mgr.policy, "decide", lambda *_args, **_kwargs: SkillStatus.VETTED)
        mgr.rescan_skill(entry.skill_id)

        processed = mgr.process_pending_submission(entry.skill_id, force_scan=True)

        assert processed.status == SkillStatus.VETTED
        assert processed.signature is None
        assert processed.approved_at is None
        assert processed.approved_by is None
        assert processed.approval_note is None
        assert processed.deployed_at is None
        assert mgr.get_trusted_skill(entry.family_id) is None

    def test_processing_does_not_override_cancelled_pending_skill(self, mgr, skill_dir, monkeypatch):
        pending, _, _ = mgr.prepare_submission(skill_dir)

        def vet_after_cancel(*_args, **_kwargs):
            mgr.reject(pending.skill_id, reviewer="admin", reason="用户取消后台分析任务")
            return VettingResult(
                risk_level=RiskLevel.BENIGN,
                scan_report={"findings": []},
            ), [], "my-skill", "safe", ["Read"]

        monkeypatch.setattr(mgr.vetting, "vet", vet_after_cancel)

        processed = mgr.process_pending_submission(pending.skill_id, force_scan=True)

        assert processed.status == SkillStatus.REJECTED
        assert processed.rejection_reason == "用户取消后台分析任务"
        assert mgr.list_scan_runs(pending.skill_id)[0].status == "CANCELLED"
        assert mgr.list_skill_summaries(page=1, page_size=10)["items"][0]["scan_pending"] is False

    def test_cancelled_queued_task_does_not_start_scanning(self, mgr, skill_dir, monkeypatch):
        pending, _, _ = mgr.prepare_submission(skill_dir)
        mgr.reject(pending.skill_id, reviewer="admin", reason="用户取消后台分析任务")

        def unexpected_scan(*_args, **_kwargs):
            raise AssertionError("Cancelled task started scanning")

        monkeypatch.setattr(mgr.vetting, "vet", unexpected_scan)
        processed = mgr.process_pending_submission(pending.skill_id)
        assert processed.status == SkillStatus.REJECTED
        assert mgr.list_scan_runs(pending.skill_id)[0].status == "CANCELLED"
