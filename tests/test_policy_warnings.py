"""Regression coverage for recorded admission notices."""

import time
import zipfile
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from agent_manager.api import router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import RiskLevel, SkillStatus
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.policy_warnings import format_policy_warning, get_policy_warnings
from agent_manager.core.scan_report_pdf import build_scan_report_pdf
from agent_manager.core.vetting import _check_manifest_policy
from tests.test_scan_report_pdf import _entry

NOTE = "[WARN] unaccepted_license: License 'GPL-3.0' is not in the accepted list: ['Apache-2.0', 'MIT']"


def test_manifest_records_actual_policy_parameters():
    items = _check_manifest_policy([], 'GPL-3.0', CompanyPolicy({'accepted_licenses': ['Apache-2.0', 'MIT']}))
    assert items[0].params == {'license': 'GPL-3.0', 'accepted_licenses': ['Apache-2.0', 'MIT']}
    assert items[0].blocking is False


def test_legacy_keeps_recorded_values():
    result = get_policy_warnings({}, [NOTE, '[BEHAVIORAL] scanned 1 files'])
    assert len(result) == 1
    assert result[0]['params'] == {'license': 'GPL-3.0', 'accepted_licenses': ['Apache-2.0', 'MIT']}


def test_empty_structured_list_takes_precedence():
    assert get_policy_warnings({'policy_warnings': []}, [NOTE]) == []


def test_unknown_preserves_original():
    item = get_policy_warnings({}, ['[WARN] custom: Original reason <sample>'])[0]
    assert format_policy_warning(item, 'zh-CN') == 'Original reason <sample>'


@pytest.mark.parametrize('language,expected', [('zh-CN', '许可证'), ('en-US', 'license')])
def test_missing_license_translated(language, expected):
    item = get_policy_warnings({}, ["[WARN] require_license: Skill manifest is missing a 'license' field (required by policy)"])[0]
    assert expected in format_policy_warning(item, language)


@pytest.mark.parametrize('language,label', [('zh-CN', '策略说明'), ('en-US', 'Policy Notes')])
def test_pdf_uses_recorded_values(language, label):
    entry = _entry()
    entry.vetting.policy_notes = [NOTE, '[BEHAVIORAL] scanned 1 files']
    raw = build_scan_report_pdf(entry, language=language)
    text = '\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(raw)).pages)
    assert text.count(label) == 1
    assert text.index(label) < text.index('GPL-3.0') < text.index('[BEHAVIORAL] scanned 1 files')
    assert '[BEHAVIORAL] scanned 1 files' in text
    assert 'GPL-3.0' in text and 'Apache-2.0' in text and 'MIT' in text
    assert 'BSD-3-Clause' not in text


def test_zip_queue_applies_saved_policy_to_real_scan(tmp_path, monkeypatch):
    initial = AgentManager(policy=CompanyPolicy({"require_sandbox_for_risk": []}), data_dir=tmp_path / "data")
    monkeypatch.setattr(router, "_manager", initial)
    monkeypatch.setattr(router, "_policy_path_for_write", lambda: tmp_path / "policy.yaml")
    monkeypatch.setattr(router, "AgentManager", lambda policy: AgentManager(policy=policy, data_dir=tmp_path / "data"))
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    app = FastAPI()
    app.include_router(router.router)
    client = TestClient(app)
    client.get("/policy")
    queue = router._get_upload_jobs(initial)
    worker = queue.thread
    try:
        for index, (license_value, expected_rule) in enumerate([
            ("GPL-3.0", "unaccepted_license"),
            (None, "require_license"),
            ("MIT", None),
        ]):
            policy = {**initial.policy.to_dict(), "accepted_licenses": ["Apache-2.0", "MIT"], "require_license": True}
            assert client.put("/policy", json=policy).status_code == 200
            assert router._get_upload_jobs(router.get_manager()) is queue
            assert queue.thread is worker
            archive = BytesIO()
            with zipfile.ZipFile(archive, "w") as output:
                manifest = f"---\nname: warning-{index}\ndescription: Policy notice test\n"
                if license_value:
                    manifest += f"license: {license_value}\n"
                output.writestr("SKILL.md", manifest + "---\n")
            prepared = client.post("/skills/prepare-upload-zip", files={"file": ("sample.zip", archive.getvalue(), "application/zip")})
            assert prepared.status_code == 200, prepared.text
            prepared = prepared.json()
            body = {"session_id": prepared["session_id"], "paths": [prepared["items"][0]["path"]]}
            submitted = client.post("/skills/submit-upload-selected", json=body)
            assert submitted.status_code == 202, submitted.text
            deadline = time.monotonic() + 5
            job = None
            while time.monotonic() < deadline:
                job = next(item for item in queue.list() if item["job_id"] == submitted.json()["job_id"])
                if job["status"] == "COMPLETED":
                    entry = router.get_manager().registry.get_by_id(job["results"][0]["version_id"])
                    if entry and entry.vetting:
                        break
                time.sleep(0.02)
            assert job["status"] == "COMPLETED", job
            assert entry.vetting is not None
            report = client.get(f"/skills/{entry.skill_id}/scan-report").json()["scan_report"]
            notices = report["policy_warnings"]
            assert [item["rule"] for item in notices] == ([expected_rule] if expected_rule else [])
            assert entry.status.value == "APPROVED"
            if expected_rule == "unaccepted_license":
                assert notices[0]["params"]["accepted_licenses"] == ["Apache-2.0", "MIT"]
                assert "BSD-3-Clause" not in notices[0]["message"]
    finally:
        queue.close()
        router._upload_jobs.pop(initial.registry.data_dir, None)


def test_api_legacy_notice_read_preserves_stored_report(tmp_path):
    entry = _entry()
    entry.vetting.policy_notes = [NOTE]
    original = entry.vetting.scan_report.copy()
    manager = AgentManager(data_dir=tmp_path)
    manager.registry.add(entry)
    response = router.get_scan_report(entry.skill_id, manager)
    assert response["scan_report"]["policy_warnings"][0]["params"]["license"] == "GPL-3.0"
    assert manager.get_skill(entry.skill_id).vetting.scan_report == original


@pytest.mark.parametrize("license_value,required,accepted", [
    (None, False, ["MIT"]),
    ("GPL-3.0", True, []),
    ("mit", True, ["MIT"]),
])
def test_manifest_without_admission_notices(license_value, required, accepted):
    policy = CompanyPolicy({"require_license": required, "accepted_licenses": accepted})
    assert _check_manifest_policy([], license_value, policy) == []


@pytest.mark.parametrize("risk,expected", [
    (RiskLevel.BENIGN, SkillStatus.APPROVED),
    (RiskLevel.SUSPICIOUS, SkillStatus.VETTED),
    (RiskLevel.MALICIOUS, SkillStatus.REJECTED),
])
def test_tool_notice_follows_risk_admission(risk, expected):
    # Jira 附件的自定义工具只产生声明提示，最终动作仍由风险规则决定。
    policy = CompanyPolicy({"allowed_tools_allowlist": ["Read", "Bash"]})
    items = _check_manifest_policy(["harmless_custom_tool"], "MIT", policy)
    assert len(items) == 1
    assert items[0].blocking is False
    assert items[0].params == {
        "tool": "harmless_custom_tool", "allowed_tools_allowlist": ["Read", "Bash"],
    }
    assert policy.decide(risk, items) == expected


def test_tool_notice_preserves_explicit_permission_block():
    policy = CompanyPolicy({"allowed_tools_allowlist": ["Read"]})
    items = _check_manifest_policy(["read_credentials"], "MIT", policy)
    assert next(item for item in items if item.rule == "tool_not_in_allowlist").blocking is False
    assert next(item for item in items if item.rule == "blocked_permission").blocking is True
    assert policy.decide(RiskLevel.BENIGN, items) == SkillStatus.REJECTED


@pytest.mark.parametrize("allowed,expected_zh,expected_en", [
    (["Read", "Bash"], "Read, Bash", "Read, Bash"),
    ([], "无", "None"),
    (None, "未记录", "Not recorded"),
])
def test_tool_notice_uses_recorded_allowlist(allowed, expected_zh, expected_en):
    params = {"tool": "harmless_custom_tool"}
    if allowed is not None:
        params["allowed_tools_allowlist"] = allowed
    notice = {"rule": "tool_not_in_allowlist", "params": params, "message": "Original"}
    assert format_policy_warning(notice, "zh-CN") == (
        f"声明的工具 harmless_custom_tool 不在允许列表中：{expected_zh}。"
    )
    assert format_policy_warning(notice, "en-US") == (
        f"The declared tool harmless_custom_tool is not in the allowlist: {expected_en}."
    )


def test_legacy_tool_notice_keeps_missing_allowlist():
    notes = ["[WARN] tool_not_in_allowlist: Tool 'harmless_custom_tool' is not in the company allowlist"]
    item = get_policy_warnings({}, notes)[0]
    assert item["params"] == {"tool": "harmless_custom_tool"}
    assert "未记录" in format_policy_warning(item, "zh-CN")


@pytest.mark.parametrize("language", ["zh-CN", "en-US"])
def test_tool_notice_pdf_uses_recorded_allowlist(language):
    entry = _entry()
    entry.vetting.policy_notes = []
    entry.vetting.scan_report["policy_warnings"] = [{
        "rule": "tool_not_in_allowlist", "message": "Original",
        "params": {"tool": "harmless_custom_tool", "allowed_tools_allowlist": ["Read", "Bash"]},
    }]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(
        BytesIO(build_scan_report_pdf(entry, language=language)),
    ).pages)
    assert "harmless_custom_tool" in text
    assert "Read, Bash" in text
    assert "Original" not in text


def test_tool_allowlist_snapshot_survives_policy_changes(tmp_path, monkeypatch):
    skill = tmp_path / "allowlist-warning-only-test"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: allowlist-warning-only-test\ndescription: Jira RENA-1485 harmless metadata sample\n"
        "license: MIT\nallowed-tools: [harmless_custom_tool]\n---\n# Metadata only\n",
    )
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    policy = CompanyPolicy({"allowed_tools_allowlist": ["Read"], "require_sandbox_for_risk": []})
    manager = AgentManager(policy=policy, data_dir=tmp_path / "data")
    entry = manager.submit(skill, use_llm=False, use_sandbox=False, use_skillspector=False)
    assert entry.status == SkillStatus.APPROVED
    assert entry.signature
    assert entry.declared_tools_valid is False
    assert any(note.startswith("[WARN] tool_not_in_allowlist:") for note in entry.vetting.policy_notes)
    policy.allowed_tools_allowlist.append("harmless_custom_tool")
    response = router.get_scan_report(entry.skill_id, manager)
    assert response["scan_report"]["policy_warnings"][0]["params"]["allowed_tools_allowlist"] == ["Read"]


@pytest.mark.parametrize("actions,expected", [
    ({"require_human_review": ["benign"]}, SkillStatus.VETTED),
    ({"auto_reject_risk": ["benign"]}, SkillStatus.REJECTED),
])
def test_tool_notice_preserves_configured_benign_action(actions, expected):
    policy = CompanyPolicy({**actions, "allowed_tools_allowlist": ["Read"]})
    notices = _check_manifest_policy(["harmless_custom_tool"], "MIT", policy)
    assert policy.decide(RiskLevel.BENIGN, notices) == expected


def test_blocked_permission_snapshot_survives_policy_changes(tmp_path, monkeypatch):
    # 红框清单使用扫描快照，策略变更不会改写历史拒绝依据。
    skill = tmp_path / "blocked-permission"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: blocked-permission\ndescription: Metadata test\nlicense: MIT\n"
        "allowed-tools: [read_credentials]\n---\n# Metadata only\n",
    )
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    policy = CompanyPolicy({"blocked_permissions": ["read_credentials", "write_memory"], "require_sandbox_for_risk": []})
    manager = AgentManager(policy=policy, data_dir=tmp_path / "data")
    entry = manager.submit(skill)
    assert entry.status == SkillStatus.REJECTED
    assert any(note.startswith("[BLOCK] blocked_permission:") for note in entry.vetting.policy_notes)
    snapshot = entry.vetting.scan_report["risk_reconciliation"]["policy_snapshot"]
    assert snapshot["blocked_permissions"] == ["read_credentials", "write_memory"]
    policy.blocked_permissions.append("read_identity")
    response = router.get_scan_report(entry.skill_id, manager)
    assert response["scan_report"]["risk_reconciliation"]["policy_snapshot"]["blocked_permissions"] == [
        "read_credentials", "write_memory",
    ]


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_tool_count_notice_boundary(count):
    policy = CompanyPolicy({"max_allowed_tools": 2, "allowed_tools_allowlist": ["Read", "Write", "Edit"]})
    tools = ["Read", "Write", "Edit"][:count]
    notices = policy.check_tool_declarations(tools)
    assert len(notices) == (1 if count > 2 else 0)
    if notices:
        assert notices[0].blocking is False
        assert notices[0].params == {"count": count, "limit": 2}
    assert policy.decide(RiskLevel.BENIGN, notices) == SkillStatus.APPROVED


@pytest.mark.parametrize("tool,risk,expected", [
    ("harmless_custom_tool", RiskLevel.BENIGN, SkillStatus.APPROVED),
    ("harmless_custom_tool", RiskLevel.SUSPICIOUS, SkillStatus.VETTED),
    ("harmless_custom_tool", RiskLevel.MALICIOUS, SkillStatus.REJECTED),
    ("read_credentials", RiskLevel.BENIGN, SkillStatus.REJECTED),
])
def test_tool_count_notice_preserves_risk_and_permission_actions(tool, risk, expected):
    policy = CompanyPolicy({"max_allowed_tools": 1, "allowed_tools_allowlist": ["Read"]})
    notices = policy.check_tool_declarations(["Read", tool])
    assert next(item for item in notices if item.rule == "max_allowed_tools").blocking is False
    assert policy.decide(risk, notices) == expected


def test_tool_count_notice_records_scan_values(tmp_path, monkeypatch):
    # 数量与上限属于本次扫描依据，后续修改策略不会改变既有说明。
    skill = tmp_path / "tool-count-notice"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: tool-count-notice\ndescription: Metadata test\nlicense: MIT\n"
        "allowed-tools: [Read, Write]\n---\n# Metadata only\n",
    )
    monkeypatch.setattr("agent_manager.core.vetting._run_scanner", lambda *_: {"findings": [], "max_severity": "SAFE"})
    policy = CompanyPolicy({"max_allowed_tools": 1, "require_sandbox_for_risk": []})
    manager = AgentManager(policy=policy, data_dir=tmp_path / "data")
    entry = manager.submit(skill, use_llm=False, use_sandbox=False, use_skillspector=False)
    assert entry.status == SkillStatus.APPROVED
    policy._data["max_allowed_tools"] = 5
    report = router.get_scan_report(entry.skill_id, manager)["scan_report"]
    notice = next(item for item in report["policy_warnings"] if item["rule"] == "max_allowed_tools")
    assert notice["params"] == {"count": 2, "limit": 1}
    assert format_policy_warning(notice, "zh-CN") == "声明的工具数量为 2，超过公司允许的上限 1。"
    assert format_policy_warning(notice, "en-US") == "The Skill declares 2 tools, exceeding the company limit of 1."


def test_legacy_tool_count_notice_uses_recorded_values():
    notices = get_policy_warnings({}, ["[WARN] max_allowed_tools: Skill declares 2 tools; policy allows at most 1"])
    assert notices[0]["params"] == {"count": 2, "limit": 1}
    assert format_policy_warning(notices[0], "zh-CN") == "声明的工具数量为 2，超过公司允许的上限 1。"


@pytest.mark.parametrize("language,expected", [
    ("zh-CN", "声明的工具数量为 2，超过公司允许的上限 1。"),
    ("en-US", "The Skill declares 2 tools, exceeding the company limit of 1."),
])
def test_tool_count_pdf_uses_recorded_values(language, expected):
    entry = _entry()
    entry.vetting.policy_notes = []
    entry.vetting.scan_report["policy_warnings"] = [{
        "rule": "max_allowed_tools", "message": "Original", "params": {"count": 2, "limit": 1},
    }]
    text = "\n".join(page.extract_text() or "" for page in PdfReader(
        BytesIO(build_scan_report_pdf(entry, language=language)),
    ).pages)
    assert expected in text
