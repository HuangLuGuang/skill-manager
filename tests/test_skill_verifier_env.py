import argparse
import importlib.util
from pathlib import Path

import pytest


def _load_verifier():
    path = (
        Path(__file__).resolve().parents[1]
        / "demo"
        / "agent-manager-skill-verifier"
        / "skills"
        / "agent-manager-skill-verifier"
        / "scripts"
        / "agent_manager_skill_verifier.py"
    )
    spec = importlib.util.spec_from_file_location("agent_manager_skill_verifier", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_verifier_prefers_specific_env(monkeypatch):
    verifier = _load_verifier()
    args = argparse.Namespace(server=None, token=None)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://verifier.example")
    monkeypatch.setenv("AGENT_MANAGER_BASE_URL", "http://legacy.example")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "verifier-token")

    assert verifier.resolve_server(args) == "http://verifier.example"
    assert verifier.resolve_token(args) == "verifier-token"


def test_verifier_sends_requested_language(monkeypatch):
    verifier = _load_verifier()
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_LANG", "en-US")

    request = verifier._json_request("GET", "http://agent-manager/api", "amat_test", None)

    assert request.get_header("Accept-language") == "en-US"


@pytest.mark.parametrize("language,expected", [("zh-CN", "SKILL.md 缺少 name 字段"), ("en-US", "SKILL.md is missing name metadata")])
def test_submit_rejects_missing_name_before_upload(tmp_path, monkeypatch, language, expected):
    verifier = _load_verifier()
    (tmp_path / "SKILL.md").write_text("---\ndescription: No name\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_LANG", language)
    with pytest.raises(verifier.VerifierError, match=expected):
        verifier.create_skill_zip(tmp_path, tmp_path)
    assert not list(tmp_path.glob("*.zip"))


def test_verifier_command_verify_checks_signature_then_can_load(tmp_path, monkeypatch, capsys):
    verifier = _load_verifier()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: safe-skill\n---\n", encoding="utf-8")
    calls = []

    def fake_api_request(method, url, token, *, json_body=None, fields=None, file_path=None):
        calls.append((method, url, token, json_body))
        if url.endswith("/verify-skill-signature"):
            return {"allowed": True, "skill_name": "safe-skill", "status": "APPROVED"}
        if "/can-load/safe-skill" in url:
            return {"allowed": True, "status": "APPROVED", "risk_level": "BENIGN"}
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "api_request", fake_api_request)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://agent-manager")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "amat_test")
    monkeypatch.setenv("AGENT_ID", "risk-agent")

    assert verifier.main(["verify", "--path", str(skill_dir)]) == 0

    out = capsys.readouterr().out
    assert "允许加载: safe-skill" in out
    assert calls[0][0] == "POST"
    assert calls[0][1] == "http://agent-manager/api/v1/access/runtime/verify-skill-signature"
    assert calls[0][2] == "amat_test"
    assert calls[0][3]["skill_name"] == "safe-skill"
    assert calls[0][3]["agent_id"] == "risk-agent"
    assert calls[1][0] == "GET"
    assert calls[1][1] == "http://agent-manager/api/v1/access/runtime/can-load/safe-skill?agent_id=risk-agent"


def test_verifier_command_verify_blocks_unapproved_skill(tmp_path, monkeypatch, capsys):
    verifier = _load_verifier()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: pending-skill\n---\n", encoding="utf-8")

    def fake_api_request(method, url, token, *, json_body=None, fields=None, file_path=None):
        return {"allowed": True, "skill_name": "pending-skill", "status": "PENDING"}

    monkeypatch.setattr(verifier, "api_request", fake_api_request)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://agent-manager")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "amat_test")
    monkeypatch.setenv("AGENT_ID", "risk-agent")

    assert verifier.main(["verify", "--path", str(skill_dir)]) == 1

    out = capsys.readouterr().out
    assert "阻断: Skill 尚未审批通过 status=PENDING" in out
    assert "请联系管理员" in out


def test_verifier_command_verify_explains_unbound_approved_skill(tmp_path, monkeypatch, capsys):
    verifier = _load_verifier()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: approved-but-unbound\n---\n", encoding="utf-8")

    def fake_api_request(method, url, token, *, json_body=None, fields=None, file_path=None):
        if url.endswith("/verify-skill-signature"):
            return {"allowed": True, "skill_name": "approved-but-unbound", "status": "APPROVED"}
        if "/can-load/approved-but-unbound" in url:
            return {"allowed": False, "reason": "智能体未授权使用该 Skill", "status": "APPROVED"}
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "api_request", fake_api_request)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://agent-manager")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "amat_test")
    monkeypatch.setenv("AGENT_ID", "risk-agent")

    assert verifier.main(["verify", "--path", str(skill_dir)]) == 1

    out = capsys.readouterr().out
    assert "阻断: 智能体未授权使用该 Skill status=APPROVED" in out
    assert "Skill 已批准" in out
    assert "绑定到当前智能体" in out
    assert "审批通过后再使用" not in out


def test_verifier_command_verify_allows_deployed_skill(tmp_path, monkeypatch, capsys):
    verifier = _load_verifier()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: deployed-skill\n---\n", encoding="utf-8")

    def fake_api_request(method, url, token, *, json_body=None, fields=None, file_path=None):
        if url.endswith("/verify-skill-signature"):
            return {"allowed": True, "skill_name": "deployed-skill", "status": "DEPLOYED"}
        if "/can-load/deployed-skill" in url:
            return {"allowed": True, "status": "DEPLOYED", "risk_level": "BENIGN"}
        raise AssertionError(url)

    monkeypatch.setattr(verifier, "api_request", fake_api_request)
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://agent-manager")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "amat_test")
    monkeypatch.setenv("AGENT_ID", "risk-agent")

    assert verifier.main(["verify", "--path", str(skill_dir)]) == 0

    out = capsys.readouterr().out
    assert "允许加载: deployed-skill status=DEPLOYED" in out
    assert "尚未审批" not in out


def test_verifier_main_explains_api_permission_error(monkeypatch, capsys):
    verifier = _load_verifier()

    def fail_with_api_error(args):
        raise verifier.ApiError(403, "接入凭证缺少权限: runtime:verify-signature")

    monkeypatch.setattr(verifier, "command_status", fail_with_api_error)

    assert verifier.main(["status", "--skill-id", "skill-1"]) == 1

    out = capsys.readouterr().out
    assert "阻断: Agent Manager API 返回 403" in out
    assert "统一凭证中心" in out
    assert "runtime 权限" in out


def test_verifier_main_uses_api_skill_status_for_guidance(monkeypatch, capsys):
    verifier = _load_verifier()

    def fail_with_api_error(args):
        raise verifier.ApiError(403, "状态不允许加载", "PENDING")

    monkeypatch.setattr(verifier, "command_status", fail_with_api_error)

    assert verifier.main(["status", "--skill-id", "skill-1"]) == 1

    out = capsys.readouterr().out
    assert "审批通过该 Skill" in out


def test_verifier_uses_error_code_for_english_guidance(monkeypatch, capsys):
    verifier = _load_verifier()
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_LANG", "en-US")

    def fail_with_api_error(args):
        raise verifier.ApiError(
            403,
            "The Agent is not authorized to use this Skill",
            "APPROVED",
            "agent.skill_not_allowed",
        )

    monkeypatch.setattr(verifier, "command_status", fail_with_api_error)

    assert verifier.main(["status", "--skill-id", "skill-1"]) == 1
    out = capsys.readouterr().out
    assert "Blocked: Agent Manager API returned 403" in out
    assert "must also be assigned to this Agent" in out


def test_verifier_local_block_reason_is_english(monkeypatch, tmp_path, capsys):
    verifier = _load_verifier()
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: pending-skill\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_LANG", "en-US")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_BASE_URL", "http://agent-manager")
    monkeypatch.setenv("AGENT_MANAGER_VERIFIER_TOKEN", "amat_test")
    monkeypatch.setenv("AGENT_ID", "risk-agent")
    monkeypatch.setattr(
        verifier,
        "api_request",
        lambda *args, **kwargs: {
            "allowed": True,
            "skill_name": "pending-skill",
            "status": "PENDING",
        },
    )

    assert verifier.main(["verify", "--path", str(skill_dir)]) == 1
    out = capsys.readouterr().out
    assert "Blocked: The Skill has not been approved status=PENDING" in out
    assert "尚未审批" not in out


def test_api_request_rejects_non_object_json_response(monkeypatch):
    verifier = _load_verifier()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'["not", "an", "object"]'

    monkeypatch.setattr(verifier.urllib.request, "urlopen", lambda request, timeout: FakeResponse())

    try:
        verifier.api_request("GET", "http://agent-manager/api", "amat_test")
    except verifier.VerifierError as exc:
        assert "非预期的响应格式" in str(exc)
    else:
        raise AssertionError("expected VerifierError")
