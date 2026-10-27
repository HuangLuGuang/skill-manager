"""Local Docker settings must be usable before an enabled configuration is saved."""

import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as routes
from agent_manager.core import sandbox
from backend.api_errors import ApiError, api_error_handler


@pytest.fixture
def client(monkeypatch, tmp_path):
    path = tmp_path / "sandbox.yaml"
    monkeypatch.setattr(sandbox.SandboxConfig, "config_path", classmethod(lambda cls: path))
    current = sandbox.SandboxConfig(enabled=False)
    current.save()
    monkeypatch.setattr(sandbox.SandboxConfig, "load", classmethod(lambda cls: current))
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.put("/sandbox-config")(routes.update_sandbox_config)
    app.post("/sandbox-config/test")(routes.test_sandbox_config)
    return TestClient(app), path


@pytest.mark.parametrize("failure,code", [
    ("command", "sandbox.docker_command_unavailable"),
    ("daemon", "sandbox.docker_daemon_unavailable"),
    ("permission", "sandbox.docker_daemon_unavailable"),
    ("timeout", "sandbox.docker_daemon_unavailable"),
    ("image", "sandbox.image_unavailable"),
    ("image_timeout", "sandbox.image_unavailable"),
])
@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_unavailable_docker_rejects_save_without_changing_config(client, monkeypatch, failure, code, locale):
    http, path = client
    before = path.read_bytes()
    calls = []
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None if failure == "command" else "/usr/bin/docker")

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] <= 3
        assert kwargs["capture_output"] and kwargs["text"]
        stage = "image" if args[1] == "image" else "daemon"
        if failure == "permission":
            raise PermissionError("test-only Docker access denied")
        if failure == "timeout" or (failure == "image_timeout" and stage == "image"):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, int(failure == stage), "", "test-only failure")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    response = http.put(
        "/sandbox-config", json={"enabled": True, "runtime": "docker"},
        headers={"Accept-Language": locale},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == code
    if code == "sandbox.image_unavailable":
        assert response.json()["error_params"]["image"] == "agent-manager-sandbox-runtime:latest"
    assert response.json()["detail"].isascii() == (locale == "en-US")
    assert path.read_bytes() == before
    assert len(calls) == (0 if failure == "command" else 2 if failure.startswith("image") else 1)


def test_available_docker_checks_daemon_then_selected_image_and_saves(client, monkeypatch):
    http, path = client
    calls = []
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "available", "")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    image = "registry.example/team/sandbox:release"
    response = http.put("/sandbox-config", json={"enabled": True, "runtime": "docker", "image": image})
    assert response.status_code == 200
    assert calls[0][:2] == ["docker", "info"]
    assert calls[1] == ["docker", "image", "inspect", image]
    assert image in path.read_text()


@pytest.mark.parametrize("payload", [
    {"enabled": False, "runtime": "docker"},
    {"enabled": True, "runtime": "remote", "remote_url": "http://sandbox:8194"},
])
def test_disabled_or_remote_settings_do_not_require_local_docker(client, monkeypatch, payload):
    http, _ = client

    def unexpected(*args, **kwargs):
        pytest.fail("Disabled or remote saves must not run Docker checks")

    monkeypatch.setattr(sandbox.shutil, "which", unexpected)
    monkeypatch.setattr(sandbox.subprocess, "run", unexpected)
    assert http.put("/sandbox-config", json=payload).status_code == 200


def test_local_connection_test_uses_same_daemon_check(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        sandbox.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "connection refused"),
    )
    result = http.post("/sandbox-config/test", json={"enabled": True, "runtime": "docker"}).json()
    assert result["available"] is False
    assert "Docker 服务" in result["message"]


def test_docker_checks_share_total_timeout_budget(monkeypatch):
    calls = []
    clock = iter([0, 1, 2])
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")

    def run(args, **kwargs):
        calls.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, "available", "")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    assert sandbox.sandbox_docker_error(sandbox.SandboxConfig(runtime="docker")) is None
    assert calls == [2, 1]


def test_docker_command_disappearing_before_execution_has_command_error(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")

    def run(*args, **kwargs):
        raise FileNotFoundError("test-only Docker command removed")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    assert sandbox.sandbox_docker_error(sandbox.SandboxConfig()) == "sandbox.docker_command_unavailable"


def test_image_check_stops_when_shared_budget_is_exhausted(monkeypatch):
    clock = iter([0, 1, 3])
    calls = []
    monkeypatch.setattr(sandbox.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: "/usr/bin/docker")

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "available", "")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    assert sandbox.sandbox_docker_error(sandbox.SandboxConfig()) == "sandbox.image_unavailable"
    assert len(calls) == 1


def test_standalone_api_rejects_unavailable_docker_with_same_error_envelope(client, monkeypatch):
    from click.testing import CliRunner
    from agent_manager.api import api_cli

    _, path = client
    before = path.read_bytes()
    apps = []
    monkeypatch.setattr(api_cli.uvicorn, "run", lambda app, **kwargs: apps.append(app))
    monkeypatch.setattr(sandbox.shutil, "which", lambda _: None)
    result = CliRunner().invoke(api_cli.main, [])
    assert result.exit_code == 0, result.output
    response = TestClient(apps[0]).put(
        "/sandbox-config", json={"enabled": True, "runtime": "docker"},
        headers={"Accept-Language": "en-US"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "sandbox.docker_command_unavailable"
    assert response.json()["detail"].isascii()
    assert path.read_bytes() == before
