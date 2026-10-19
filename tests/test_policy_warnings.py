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
