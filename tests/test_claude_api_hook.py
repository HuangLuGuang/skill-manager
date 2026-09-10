import importlib.util
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).resolve().parents[1] / "demo" / "claude-code-api-hook" / "agent_guard_hook.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("agent_guard_hook_for_test", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hook_allows_non_skill_without_configuration(monkeypatch):
    hook = _load_hook()
    monkeypatch.delenv("AGENT_MANAGER_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_MANAGER_API_TOKEN", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
    })))

    with pytest.raises(SystemExit) as exc:
        hook.main()

    assert exc.value.code == 0


def test_hook_blocks_skill_when_configuration_missing(monkeypatch, capsys):
    hook = _load_hook()
    monkeypatch.delenv("AGENT_MANAGER_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_MANAGER_API_TOKEN", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Skill",
        "tool_input": {"skill": "risk-skill"},
    })))

    with pytest.raises(SystemExit) as exc:
        hook.main()

    assert exc.value.code == 2
    assert "Missing Agent Manager URL" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("tool_input", "expected"),
    [
        ({"skill": "claude-skill"}, "claude-skill"),
        ({"name": "named-skill"}, "named-skill"),
    ],
)
def test_hook_extracts_skill_name_from_supported_argument_keys(tool_input, expected):
    hook = _load_hook()

    assert hook._extract_skill_name_from_event({
        "tool_name": "Skill",
        "tool_input": tool_input,
    }) == expected


def test_hook_signature_normalizes_legacy_zip_mojibake_paths(tmp_path):
    hook = _load_hook()
    normal = tmp_path / "normal"
    mojibake = tmp_path / "mojibake"
    (normal / "references").mkdir(parents=True)
    (mojibake / "references").mkdir(parents=True)
    (normal / "references" / "常用查询模板.md").write_text("select 1", encoding="utf-8")
    (mojibake / "references" / "σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md").write_text("select 1", encoding="utf-8")

    assert hook.compute_skill_signature(normal, hook.DEFAULT_IGNORES) == hook.compute_skill_signature(
        mojibake, hook.DEFAULT_IGNORES
    )


def test_hook_signature_sorts_by_canonical_relative_path(tmp_path):
    hook = _load_hook()
    files = {
        "SKILL.md": b"skill",
        "_meta.json": b"meta",
        "skill-card.md": b"card",
    }
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
    payload = "".join(
        f"{name}:{hashlib.sha256(files[name]).hexdigest()}\n"
        for name in sorted(files)
    ).encode()

    assert hook.compute_skill_signature(tmp_path, hook.DEFAULT_IGNORES) == hashlib.sha256(payload).hexdigest()


def test_hook_signature_ignores_macos_finder_metadata(tmp_path):
    hook = _load_hook()
    (tmp_path / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    before = hook.compute_skill_signature(tmp_path, hook.DEFAULT_IGNORES)
    (tmp_path / ".DS_Store").write_bytes(b"finder metadata")

    assert hook.compute_skill_signature(tmp_path, hook.DEFAULT_IGNORES) == before


def test_hook_scan_keeps_company_skill_when_project_has_same_name(tmp_path, monkeypatch):
    hook = _load_hook()
    company_root = tmp_path / "company-skills"
    project_root = tmp_path / "project"
    company_skill = company_root / "shared-skill"
    project_skill = project_root / ".claude" / "skills" / "shared-skill"
    company_skill.mkdir(parents=True)
    project_skill.mkdir(parents=True)
    manifest = "---\nname: shared-skill\n---\n"
    (company_skill / "SKILL.md").write_text(manifest, encoding="utf-8")
    (project_skill / "SKILL.md").write_text(manifest, encoding="utf-8")
    monkeypatch.setenv("AGENT_MANAGER_SKILLS_DIR", str(company_root))

    assert hook._scan_skill_dirs(str(project_root))["shared-skill"] == company_skill


def test_hook_reads_skill_id_from_managed_install_path(tmp_path, monkeypatch):
    hook = _load_hook()
    skill_id = "6f1fa149-5b0c-4eb2-b597-462bcedac5c9"
    skill_dir = tmp_path / "skills" / skill_id / "content-signature"
    skill_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_MANAGER_MANAGED_SKILLS_DIR", str(tmp_path / "skills"))

    assert hook.managed_skill_id(skill_dir) == skill_id
    assert hook.managed_skill_id(tmp_path / "other") is None


def test_hook_pre_tool_use_verifies_skill_from_name_payload(tmp_path, monkeypatch):
    hook = _load_hook()
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "named-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: named-skill\n---\n", encoding="utf-8")
    verified = {}

    def fake_verify_skill(client, server, token, path, agent_id, skill_name):
        verified.update({
            "server": server,
            "token": token,
            "path": path,
            "agent_id": agent_id,
            "skill_name": skill_name,
        })
        return True, skill_name

    monkeypatch.setenv("AGENT_MANAGER_SKILLS_DIR", str(skills_root))
    monkeypatch.setenv("AGENT_ID", "agent-a")
    monkeypatch.setattr(hook, "verify_skill", fake_verify_skill)

    hook.handle_pre_tool_use(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Skill",
            "tool_input": {"name": "named-skill"},
            "cwd": str(tmp_path),
            "session_id": "session-a",
        },
        client=object(),
        server="http://agent-manager",
        token="amat_test",
    )

    assert verified == {
        "server": "http://agent-manager",
        "token": "amat_test",
        "path": skill_dir,
        "agent_id": "agent-a",
        "skill_name": "named-skill",
    }


def test_hook_subprocess_verifies_skill_against_runtime_api(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "runtime-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: runtime-skill\n---\n", encoding="utf-8")
    captured = {"post": None, "get_path": None, "authorization": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            captured["post"] = json.loads(self.rfile.read(length).decode("utf-8"))
            captured["authorization"] = self.headers.get("authorization")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "allowed": True,
                "skill_name": "runtime-skill",
                "status": "APPROVED",
            }).encode("utf-8"))

        def do_GET(self):
            captured["get_path"] = self.path
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "allowed": True,
                "status": "APPROVED",
                "risk_level": "BENIGN",
            }).encode("utf-8"))

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "AGENT_MANAGER_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "AGENT_MANAGER_API_TOKEN": "amat_test",
            "AGENT_ID": "agent-a",
            "AGENT_MANAGER_SKILLS_DIR": str(skills_root),
            "AGENT_MANAGER_HOOK_LOG_FILE": str(tmp_path / "hook.log"),
            "AGENT_MANAGER_SESSION_STATE_DIR": str(tmp_path / "session-state"),
        }
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Skill",
            "tool_input": {"name": "runtime-skill"},
            "cwd": str(tmp_path),
            "session_id": "session-a",
        }

        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert captured["authorization"] == "Bearer amat_test"
    assert captured["post"]["skill_name"] == "runtime-skill"
    assert captured["post"]["agent_id"] == "agent-a"
    assert captured["post"]["local_signature"]
    assert captured["get_path"] == "/api/v1/access/runtime/can-load/runtime-skill?agent_id=agent-a"


def test_hook_submits_managed_skill_id_and_uses_it_for_can_load(tmp_path, monkeypatch):
    hook = _load_hook()
    skill_id = "6f1fa149-5b0c-4eb2-b597-462bcedac5c9"
    skill_dir = tmp_path / "skills" / skill_id / "content-signature"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: shared-skill\n---\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_MANAGER_MANAGED_SKILLS_DIR", str(tmp_path / "skills"))
    captured = {}

    def fake_verify(*_args, **kwargs):
        captured["skill_id"] = kwargs.get("skill_id")
        return {
            "allowed": True,
            "skill_id": skill_id,
            "skill_name": "shared-skill",
            "status": "APPROVED",
        }

    def fake_can_load(_client, _server, _token, skill_ref, _agent_id):
        captured["skill_ref"] = skill_ref
        return {"allowed": True, "status": "APPROVED"}

    monkeypatch.setattr(hook, "verify_skill_signature", fake_verify)
    monkeypatch.setattr(hook, "can_load_skill", fake_can_load)

    allowed, _ = hook.verify_skill(object(), "http://agent-manager", "token", skill_dir, "agent-a")

    assert allowed
    assert captured == {"skill_id": skill_id, "skill_ref": skill_id}
