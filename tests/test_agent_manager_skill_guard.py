from __future__ import annotations

import importlib.util
import json
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_manager.api.router as api_router
from agent_manager.api.router import get_manager
from agent_manager.api.scanner_router import admin_router, router, runtime_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.signer import compute_signature


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "demo"
    / "agent-manager-skill-guard"
    / "skills"
    / "agent-manager-skill-guard"
    / "scripts"
    / "agent_manager_skill_guard.py"
)


@pytest.fixture
def guard_module():
    spec = importlib.util.spec_from_file_location("agent_manager_skill_guard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def skill_dir(tmp_path):
    root = tmp_path / "third-party-skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: third-party\ndescription: Demo\n---\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("ignored\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg.js").write_text("ignored\n", encoding="utf-8")
    return root


def test_compute_signature_matches_agent_manager_signer(guard_module, skill_dir):
    assert guard_module.compute_skill_signature(skill_dir) == compute_signature(skill_dir)


def test_create_skill_zip_ignores_dependency_and_vcs_directories(guard_module, skill_dir, tmp_path):
    zip_path, manifest = guard_module.create_skill_zip(skill_dir, tmp_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())

    assert names == ["SKILL.md", "scripts/run.py"]
    assert manifest["fingerprint"].startswith("sha256:")
    assert [item["path"] for item in manifest["files"]] == ["SKILL.md", "scripts/run.py"]


def test_submit_posts_zip_manifest_and_scan_flags(guard_module, skill_dir, tmp_path, monkeypatch, capsys):
    calls = []

    def fake_request(method, url, token, **kwargs):
        calls.append((method, url, token, kwargs))
        return {
            "skill_id": "skill-1",
            "name": "third-party",
            "status": "PENDING",
            "detail_url": "/skills/skill-1",
        }

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    exit_code = guard_module.main([
        "submit",
        "--path",
        str(skill_dir),
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
        "--behavioral",
        "--sandbox",
        "--llm",
    ])

    assert exit_code == 0
    method, url, token, kwargs = calls[0]
    assert method == "POST"
    assert url == "http://manager.example/api/v1/scanner/imports"
    assert token == "smsc_live_test"
    assert kwargs["fields"]["use_behavioral"] == "true"
    assert kwargs["fields"]["use_sandbox"] == "true"
    assert kwargs["fields"]["use_llm"] == "true"
    assert json.loads(kwargs["fields"]["manifest"])["fingerprint"].startswith("sha256:")
    assert "已提交扫描" in capsys.readouterr().out


def test_submit_enables_llm_by_default(guard_module, skill_dir, monkeypatch):
    captured = {}

    def fake_request(method, url, token, **kwargs):
        captured.update(kwargs["fields"])
        return {"skill_id": "skill-1", "name": "third-party", "status": "PENDING"}

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    assert guard_module.main([
        "submit",
        "--path",
        str(skill_dir),
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
    ]) == 0
    assert captured["use_llm"] == "true"


def test_submit_can_disable_llm_explicitly(guard_module, skill_dir, monkeypatch):
    captured = {}

    def fake_request(method, url, token, **kwargs):
        captured.update(kwargs["fields"])
        return {"skill_id": "skill-1", "name": "third-party", "status": "PENDING"}

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    assert guard_module.main([
        "submit",
        "--path",
        str(skill_dir),
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
        "--no-llm",
    ]) == 0
    assert captured["use_llm"] == "false"


def test_verify_allows_only_when_signature_and_can_load_pass(guard_module, skill_dir, monkeypatch, capsys):
    calls = []

    def fake_request(method, url, token, **kwargs):
        calls.append((method, url, token, kwargs))
        if url.endswith("/verify-skill-signature"):
            body = kwargs["json_body"]
            assert body["local_signature"] == guard_module.compute_skill_signature(
                skill_dir,
                ignores=guard_module.DEFAULT_IGNORES,
            )
            return {
                "allowed": True,
                "reason": "signature verified",
                "skill_name": "third-party",
                "status": "APPROVED",
                "risk_level": "benign",
                "signature_match": True,
            }
        return {"allowed": True, "reason": "skill is approved", "status": "APPROVED", "risk_level": "benign"}

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    exit_code = guard_module.main([
        "verify",
        "--name",
        "third-party",
        "--path",
        str(skill_dir),
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
    ])

    assert exit_code == 0
    assert [call[0] for call in calls] == ["POST", "GET"]
    assert "允许加载" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        {"allowed": False, "reason": "Skill not in the registry", "status": None, "signature_match": False},
        {"allowed": False, "reason": "Skill is VETTED", "status": "VETTED", "signature_match": False},
        {"allowed": False, "reason": "Skill has no stored signature", "status": "APPROVED", "signature_match": False},
        {"allowed": False, "reason": "signature mismatch", "status": "APPROVED", "signature_match": False},
    ],
)
def test_verify_blocks_unapproved_unsigned_or_mismatched_skills(guard_module, skill_dir, monkeypatch, capsys, payload):
    def fake_request(method, url, token, **kwargs):
        return payload

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    exit_code = guard_module.main([
        "verify",
        "--name",
        "third-party",
        "--path",
        str(skill_dir),
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
    ])

    assert exit_code == 1
    assert "阻断" in capsys.readouterr().out


def test_status_reports_scanner_import_status(guard_module, monkeypatch, capsys):
    def fake_request(method, url, token, **kwargs):
        assert method == "GET"
        assert url == "http://manager.example/api/v1/scanner/imports/skill-1"
        return {"skill_id": "skill-1", "name": "third-party", "status": "PENDING", "risk_level": None}

    monkeypatch.setattr(guard_module, "api_request", fake_request)

    exit_code = guard_module.main([
        "status",
        "--skill-id",
        "skill-1",
        "--server",
        "http://manager.example",
        "--token",
        "smsc_live_test",
    ])

    assert exit_code == 0
    assert "PENDING" in capsys.readouterr().out


def test_token_can_come_from_agent_manager_api_token(guard_module, monkeypatch):
    args = type("Args", (), {"token": None})()
    monkeypatch.delenv("AGENT_MANAGER_TOKEN", raising=False)
    monkeypatch.setenv("AGENT_MANAGER_API_TOKEN", "api-token")

    assert guard_module.resolve_token(args) == "api-token"


def test_submit_approve_verify_and_tamper_flow_against_api(guard_module, skill_dir, tmp_path, monkeypatch, capsys):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.include_router(admin_router)
        app.include_router(router)
        app.include_router(runtime_router)
        client = TestClient(app)

        token_response = client.post(
            "/api/v1/scanner/tokens",
            json={
                "name": "agent-manager-skill-guard-test",
                "scopes": [
                    "scanner:submit",
                    "scanner:read-own-results",
                    "runtime:verify-signature",
                    "runtime:can-load",
                    "runtime:check-tool",
                ],
            },
        )
        assert token_response.status_code == 200
        token = token_response.json()["token"]

        def local_request(method, url, request_token, **kwargs):
            assert request_token == token
            path = url.removeprefix("http://testserver")
            headers = {"Authorization": f"Bearer {request_token}"}
            if kwargs.get("fields") is not None:
                fields = kwargs["fields"]
                file_path = kwargs["file_path"]
                with open(file_path, "rb") as handle:
                    response = client.post(
                        path,
                        headers=headers,
                        data=fields,
                        files={"file": (file_path.name, handle, "application/zip")},
                    )
            elif method == "POST":
                response = client.post(path, headers=headers, json=kwargs.get("json_body"))
            else:
                response = client.get(path, headers=headers)
            if response.status_code >= 400:
                raise guard_module.GuardError(response.text)
            return response.json()

        monkeypatch.setattr(guard_module, "api_request", local_request)

        assert guard_module.main([
            "submit",
            "--path",
            str(skill_dir),
            "--server",
            "http://testserver",
            "--token",
            token,
        ]) == 0
        skill_id = next(item.skill_id for item in manager.list_skills() if item.name == "third-party")
        deadline = time.time() + 5
        while time.time() < deadline:
            entry = manager.get_skill(skill_id)
            if entry and entry.status.value != "PENDING":
                break
            time.sleep(0.05)
        assert manager.get_skill(skill_id).status.value == "APPROVED"
        assert guard_module.main([
            "verify",
            "--name",
            "third-party",
            "--path",
            str(skill_dir),
            "--server",
            "http://testserver",
            "--token",
            token,
        ]) == 0
        assert "允许加载" in capsys.readouterr().out

        (skill_dir / "SKILL.md").write_text("---\nname: third-party\ndescription: Tampered\n---\n", encoding="utf-8")
        assert guard_module.main([
            "verify",
            "--name",
            "third-party",
            "--path",
            str(skill_dir),
            "--server",
            "http://testserver",
            "--token",
            token,
        ]) == 1
        assert "阻断" in capsys.readouterr().out
    finally:
        api_router._manager = previous_manager
