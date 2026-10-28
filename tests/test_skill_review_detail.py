"""当前版本拒绝记录的详情读取回归。"""
from datetime import datetime, timedelta, timezone

import pytest

from agent_manager.api.router import get_skill
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillStatus
from agent_manager.core.registry import make_event
from tests.test_scan_report_pdf import _entry


@pytest.fixture
def case(tmp_path):
    manager = AgentManager(data_dir=tmp_path)
    entry = _entry()
    entry.status = SkillStatus.REJECTED
    entry.rejection_reason = "保留原文 <script>\n拒绝原因"
    manager.registry.add(entry)
    return manager, entry


def event(manager, entry, kind, offset=0, actor=None):
    item = make_event(kind, entry, actor=actor)
    item.timestamp = datetime(2026, 10, 27, tzinfo=timezone.utc) + timedelta(seconds=offset)
    manager.registry.log_event(item)
    return item


def test_rejection_uses_version_event_without_audit_limit(case):
    manager, entry = case
    rejected = event(manager, entry, 'skill_rejected', actor='reviewer')
    for i in range(120):
        event(manager, entry, 'skill_signature_verified', i + 1, 'other')
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == 'reviewer'
    assert result['rejected_at'] == rejected.timestamp.isoformat()
    assert result['rejection_reason'] == entry.rejection_reason
    assert manager.registry.get_by_id(entry.skill_id).rejection_reason == entry.rejection_reason


def test_completed_rescan_does_not_reuse_previous_rejection(case):
    manager, entry = case
    rejected = event(manager, entry, 'skill_rejected', actor='old-reviewer')
    entry.vetting.vetted_at = rejected.timestamp + timedelta(seconds=1)
    manager.registry.update(entry)
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] is None
    assert result['rejected_at'] is None


def test_failed_rescan_preserves_effective_rejection(case):
    manager, entry = case
    rejected = event(manager, entry, 'skill_rejected', actor='reviewer')
    event(manager, entry, 'skill_processing_failed', 1)
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == 'reviewer'
    assert result['rejected_at'] == rejected.timestamp.isoformat()


def test_missing_history_and_other_version_remain_unrecorded(case):
    manager, entry = case
    other = entry.model_copy(update={'skill_id': 'other-version'})
    event(manager, other, 'skill_rejected', actor='other-reviewer')
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] is None
    assert result['rejected_at'] is None


def test_approved_detail_preserves_approval(case):
    manager, entry = case
    entry.status = SkillStatus.APPROVED
    entry.approved_by = 'approver'
    entry.approval_note = '批准原文\nsecond line'
    manager.registry.update(entry)
    result = get_skill(entry.skill_id, manager)
    assert result['approved_by'] == 'approver'
    assert result['approval_note'] == entry.approval_note


def test_reused_scan_does_not_reuse_previous_reviewer(case):
    manager, entry = case
    event(manager, entry, 'skill_rejected', actor='old-reviewer')
    event(manager, entry, 'skill_scan_reused', 1)
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] is None
    assert result['rejected_at'] is None


@pytest.mark.parametrize('kind,actor', [
    ('skill_processing_completed', 'auto-policy'),
    ('skill_scan_reused', 'auto-policy-cache'),
])
def test_automatic_rejection_uses_current_decision(case, kind, actor):
    manager, entry = case
    entry.rejection_reason = None
    manager.registry.update(entry)
    decision = make_event(kind, entry, details={'status': 'REJECTED'})
    manager.registry.log_event(decision)
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == actor
    assert result['rejected_at'] == decision.timestamp.isoformat()
    assert manager.registry.get_by_id(entry.skill_id).rejection_reason is None


def test_manual_rejection_after_automatic_decision_preserves_reason(case):
    manager, entry = case
    decision = event(manager, entry, 'skill_processing_completed')
    decision.details = {'status': 'REJECTED'}
    manager.registry.log_event(decision)
    event(manager, entry, 'skill_rejected', 1, 'reviewer')
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == 'reviewer'
    assert result['rejection_reason'] == entry.rejection_reason


def test_initial_scan_failure_exposes_actual_failure_time(case):
    manager, entry = case
    entry.status = SkillStatus.PENDING
    entry.vetting = None
    manager.registry.update(entry)
    manager.mark_submission_failed(entry.skill_id, '连接超时\nupstream timeout')
    failed = manager.registry.read_audit(skill_id=entry.skill_id, event_types=('skill_processing_failed',))[0]
    result = get_skill(entry.skill_id, manager)
    assert result['rejection_source'] == 'scan_failed'
    assert result['rejected_at'] == failed.timestamp.isoformat()
    assert result['rejected_by'] is None
    assert result['rejection_reason'] == '连接超时\nupstream timeout'

    # 已有失败结果的复扫失败也保留原先有效失败事件。
    manager.mark_submission_failed(entry.skill_id, 'second timeout')
    again = get_skill(entry.skill_id, manager)
    assert again['rejected_at'] == failed.timestamp.isoformat()
    assert again['rejection_reason'] == result['rejection_reason']


def test_failed_rescan_preserves_real_manual_rejection(case):
    manager, entry = case
    rejected = event(manager, entry, 'skill_rejected', actor='reviewer')
    manager.mark_submission_failed(entry.skill_id, 'rescan timeout')
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == 'reviewer'
    assert result['rejected_at'] == rejected.timestamp.isoformat()
    assert 'rejection_source' not in result


def test_failed_rescan_preserves_policy_rejection(case):
    manager, entry = case
    decision = make_event('skill_processing_completed', entry, details={'status': 'REJECTED'})
    manager.registry.log_event(decision)
    manager.mark_submission_failed(entry.skill_id, 'rescan timeout')
    result = get_skill(entry.skill_id, manager)
    assert result['rejected_by'] == 'auto-policy'
    assert result['rejected_at'] == decision.timestamp.isoformat()
    assert 'rejection_source' not in result
