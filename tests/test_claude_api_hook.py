import importlib.util
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
        ({"name": "trae-skill"}, "trae-skill"),
    ],
)
def test_hook_extracts_skill_name_from_claude_and_trae_payloads(tool_input, expected):
    hook = _load_hook()

    assert hook._extract_skill_name_from_event({
        "tool_name": "Skill",
        "tool_input": tool_input,
    }) == expected


def test_hook_pre_tool_use_verifies_skill_from_name_payload(tmp_path, monkeypatch):
    hook = _load_hook()
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "trae-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: trae-skill\n---\n", encoding="utf-8")
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
            "tool_input": {"name": "trae-skill"},
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
        "skill_name": "trae-skill",
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
