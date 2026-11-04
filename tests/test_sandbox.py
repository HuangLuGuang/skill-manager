from pathlib import Path
import base64
from agent_manager.core.sandbox import (
    RemoteSandboxRunner,
    SandboxConfig,
    SandboxRunner,
    build_probe_plan,
    discover_probe_entrypoint,
    extract_markdown_command_probes,
    get_sandbox_runner,
    write_markdown_command_probe_scripts,
    _collect_remote_sandbox_files,
)


def test_remote_collection_preserves_binary_and_text(tmp_path):
    binary = b"\x80\x04\xff\x00\r\n"
    (tmp_path / "uploaded.pkl").write_bytes(binary)
    (tmp_path / "text.txt").write_bytes("中文\r\n".encode())
    files = {item.path: item for item in _collect_remote_sandbox_files(tmp_path)}
    assert files["uploaded.pkl"].encoding == "base64"
    assert base64.b64decode(files["uploaded.pkl"].content) == binary
    assert files["text.txt"].encoding == "utf-8"
    assert files["text.txt"].content.encode() == "中文\r\n".encode()


def test_remote_runner_checks_binary_support_and_waits_for_execution_timeout(tmp_path, monkeypatch):
    (tmp_path / "run.py").write_text("pass")
    (tmp_path / "uploaded.pkl").write_bytes(b"\x80\x04")
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"file_encodings": ["utf-8", "base64"], "timed_out": True, "exit_code": 137, "message": "stopped"}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", post)
    result = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local", timeout_seconds=3)).run_probe(tmp_path, "run.py")
    assert captured["json"]["timeout_seconds"] == 3
    assert captured["timeout"] > 5
    assert result.executed and result.timed_out and result.exit_code == 137


def test_remote_runner_does_not_send_binary_to_unsupported_service(tmp_path, monkeypatch):
    (tmp_path / "run.py").write_text("pass")
    (tmp_path / "uploaded.pkl").write_bytes(b"\x80\x04")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "ok"}

    def unexpected_post(*args, **kwargs):
        raise AssertionError("binary input sent to unsupported service")

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", unexpected_post)
    result = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local")).run_probe(tmp_path, "run.py")
    assert not result.executed
    assert "support base64" in result.reason


def test_discover_probe_entrypoint_prefers_scripts_directory(tmp_path):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")
    (skill_dir / "helper.py").write_text("print('helper')\n", encoding="utf-8")

    assert discover_probe_entrypoint(skill_dir) == "scripts/run.py"


def test_sandbox_runner_reports_unavailable_without_docker(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    monkeypatch.setattr("agent_manager.core.sandbox.shutil.which", lambda _: None)

    runner = SandboxRunner(SandboxConfig(runtime="docker"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is False
    assert result.available is False
    assert "Docker" in (result.reason or "")


def test_build_probe_plan_prefers_help_for_argparse_scripts(tmp_path):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text(
        "import argparse\nparser = argparse.ArgumentParser()\nparser.parse_args()\n",
        encoding="utf-8",
    )

    plan = build_probe_plan(skill_dir, "scripts/run.py")

    assert plan.entrypoint == "scripts/run.py"
    assert plan.args == ["--help"]
    assert plan.strategy == "cli-help"


def test_markdown_command_blocks_can_be_written_as_probe_scripts(tmp_path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: markdown-command
description: d
---

```bash
$ clawdhub update --all --dry-run
clawdbot --version
```
""",
        encoding="utf-8",
    )

    probes = extract_markdown_command_probes(skill_dir)
    plans = write_markdown_command_probe_scripts(skill_dir, probes)

    assert len(probes) == 1
    assert len(plans) == 1
    assert plans[0].entrypoint.endswith(".sh")
    script = (skill_dir / plans[0].entrypoint).read_text(encoding="utf-8")
    assert "clawdhub update --all --dry-run" in script
    assert "clawdbot --version" in script
    assert 'cd "$(dirname "$0")/.."' in script
    assert "cd /tmp" not in script


def test_get_sandbox_runner_returns_remote_runner_when_configured():
    runner = get_sandbox_runner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))

    assert isinstance(runner, RemoteSandboxRunner)
    assert runner.is_available() is True


def test_sandbox_config_public_dict_masks_remote_api_key():
    config = SandboxConfig(runtime="remote", remote_url="http://sandbox.local", remote_api_key="secret-key-value")

    data = config.public_dict()

    assert "remote_api_key" not in data
    assert data["remote_api_key_configured"] is True
    assert isinstance(data["remote_api_key_masked"], str)


def test_remote_runner_parses_enveloped_response(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "stdout": "ok",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 12,
                },
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.runtime == "remote"
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.duration_ms == 12
    assert result.risk_level == "LOW"
    assert result.max_severity == "SAFE"
    assert "未提取到明确运行时风险信号" in result.summary


def test_remote_runner_sends_skill_files_for_local_package_imports(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "__init__.py").write_text("", encoding="utf-8")
    (scripts_dir / "helper.py").write_text("VALUE = 'ok'\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("from scripts.helper import VALUE\nprint(VALUE)\n", encoding="utf-8")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "stdout": "ok",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 12,
                },
            }

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", fake_post)

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    sent_files = {item["path"]: item["content"] for item in captured["json"]["files"]}
    assert result.executed is True
    assert captured["json"]["metadata"]["execute_entrypoint"] is True
    assert captured["json"]["metadata"]["entrypoint"] == "scripts/run.py"
    assert "scripts/helper.py" in sent_files
    assert "scripts/__init__.py" in sent_files


def test_remote_runner_parses_flat_response(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "stdout": "",
                "stderr": "timeout while running",
                "code": 124,
                "message": "timeout",
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.timed_out is True
    assert result.exit_code == 124
    assert any(event.category == "timeout" for event in result.suspicious_events)
    assert result.risk_level == "MEDIUM"
    assert result.max_severity == "MEDIUM"
    assert result.recommendation


def test_remote_runner_extracts_network_signal_without_dependency_noise(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "stdout": "",
                "stderr": "ModuleNotFoundError: No module named 'requests'\nnetwork failure for https://evil.example.com",
                "exit_code": 1,
                "duration_ms": 20,
                "message": "failed",
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.risk_level == "HIGH"
    assert result.max_severity == "HIGH"
    assert not any(event.category == "dependency" for event in result.signals)
    assert any(event.category == "network" for event in result.signals)


def test_missing_module_output_is_not_runtime_risk(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "stdout": "",
                "stderr": "ModuleNotFoundError: No module named 'scripts'",
                "exit_code": 1,
                "duration_ms": 20,
                "message": "failed",
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.risk_level == "LOW"
    assert result.max_severity == "SAFE"
    assert not result.signals
    assert "未提取到明确运行时风险信号" in result.summary


def test_stdout_keyword_does_not_create_sandbox_risk_signal(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "stdout": "eval",
                "stderr": "",
                "exit_code": 0,
                "duration_ms": 20,
                "message": "ok",
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.risk_level == "LOW"
    assert result.max_severity == "SAFE"
    assert not result.signals
    assert "未提取到明确运行时风险信号" in result.summary


def test_remote_runner_treats_missing_probe_input_as_info(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n", encoding="utf-8")
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "stdout": "",
                "stderr": "/tmp/sandbox/main.sh: 5: cannot open path-to-trigger-eval.json: No such file",
                "exit_code": 2,
                "duration_ms": 20,
                "message": "failed",
            }

    monkeypatch.setattr("agent_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.risk_level == "LOW"
    assert result.max_severity == "INFO"
    assert any(event.category == "probe_input" for event in result.signals)
    assert not any(event.category == "runtime" for event in result.signals)
    assert "示例输入文件不存在" in result.summary
