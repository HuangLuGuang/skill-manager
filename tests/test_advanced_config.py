"""Advanced settings reject invalid writes without changing saved configuration."""

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from agent_manager.api import api_cli
from agent_manager.core.llm import LLMConfig
from agent_manager.core.sandbox import SandboxConfig


@pytest.fixture
def client(monkeypatch, tmp_path):
    apps = []
    monkeypatch.setattr(api_cli.uvicorn, "run", lambda app, **kwargs: apps.append(app))
    monkeypatch.setattr(LLMConfig, "load", classmethod(lambda cls: LLMConfig()))
    monkeypatch.setattr(SandboxConfig, "load", classmethod(lambda cls: SandboxConfig()))
    monkeypatch.setattr(LLMConfig, "save", lambda self: tmp_path / "llm.yaml")
    monkeypatch.setattr(SandboxConfig, "save", lambda self: tmp_path / "sandbox.yaml")
    result = CliRunner().invoke(api_cli.main, [])
    assert result.exit_code == 0, result.output
    return TestClient(apps[0])


@pytest.mark.parametrize("path", ["/llm-config", "/sandbox-config", "/sandbox-config/test", "/policy"])
@pytest.mark.parametrize("value", [True, 123, "config", [], [["enabled", True]]])
def test_non_object_configuration_is_rejected(client, monkeypatch, path, value):
    def unexpected(*args, **kwargs):
        pytest.fail("Non-object configuration must not be saved")

    monkeypatch.setattr(LLMConfig, "save", unexpected)
    monkeypatch.setattr(SandboxConfig, "save", unexpected)
    method = client.post if path.endswith("/test") else client.put
    for locale in ("zh-CN", "en-US"):
        response = method(path, json=value, headers={"Accept-Language": locale})
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "request.validation_failed"
        assert body["detail"].isascii() == (locale == "en-US")


@pytest.mark.parametrize("group,field,values", [
    ("llm", "timeout_seconds", [None, 0, -1, 30.6, 181, "30", True]),
    ("llm", "max_files", [None, 0, -1, 1.5, 21]),
    ("llm", "max_manifest_chars", [1999, 50001, 2000.5]),
    ("llm", "max_file_chars", [499, 20001, 500.5]),
    ("sandbox", "timeout_seconds", [None, 0, -1, 15.6, 301]),
    ("sandbox", "pids_limit", [None, 0, -1, 1.5, 1025]),
    ("sandbox", "cpu_limit", ["", "abc", "0", "-1", "NaN", "Infinity", "1e2", "64.01", "0.001"]),
    ("sandbox", "memory_limit", ["", "invalid", "0m", "-1m", "1.5g", "5m", "65g"]),
    ("sandbox", "runtime", ["invalid"]),
    ("sandbox", "network_mode", ["host"]),
    ("sandbox", "image", ["", "bad name", "x" * 256]),
    ("llm", "enabled", ["false", 1]),
    ("sandbox", "read_only_rootfs", ["false", 1]),
])
def test_invalid_values_have_localized_field_errors(client, group, field, values, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid configuration must not be written")

    monkeypatch.setattr(LLMConfig, "save", unexpected)
    monkeypatch.setattr(SandboxConfig, "save", unexpected)
    for value in values:
        for locale in ("zh-CN", "en-US"):
            payload = {field: value}
            if group == "sandbox" and field not in {"runtime"}:
                payload["runtime"] = "docker"
            response = client.put(f"/{group}-config", json=payload, headers={"Accept-Language": locale})
            assert response.status_code == 422, (field, value, response.text)
            body = response.json()
            assert body["error_code"]
            assert any(item["field"] == field for item in body["error_params"]["errors"])
            assert body["detail"].isascii() == (locale == "en-US")


@pytest.mark.parametrize("group,payload", [
    ("llm", {"timeout_seconds": 5, "max_files": 1, "max_manifest_chars": 2000, "max_file_chars": 500}),
    ("llm", {"timeout_seconds": 180, "max_files": 20, "max_manifest_chars": 50000, "max_file_chars": 20000}),
    ("sandbox", {"runtime": "docker", "timeout_seconds": 1, "pids_limit": 1, "memory_limit": "6m", "cpu_limit": "0.01"}),
    ("sandbox", {"runtime": "docker", "timeout_seconds": 300, "pids_limit": 1024, "memory_limit": "64G", "cpu_limit": "64"}),
    ("sandbox", {"runtime": "docker", "cpu_limit": "2.50", "image": "registry.local:5000/team/runtime:v1"}),
])
def test_boundaries_are_accepted(client, group, payload):
    assert client.put(f"/{group}-config", json=payload).status_code == 200


def test_conditional_fields_and_credentials(client):
    assert client.put("/sandbox-config", json={"runtime": "remote", "cpu_limit": "invalid", "pids_limit": "invalid", "read_only_rootfs": "invalid", "image": ""}).status_code == 200
    assert client.put("/sandbox-config", json={"runtime": "docker", "remote_url": "invalid", "remote_api_key": "a b"}).status_code == 200
    for value in ("a b", "x" * 4097, "a\nb"):
        result = client.put("/sandbox-config", json={"runtime": "remote", "remote_api_key": value})
        assert result.status_code == 422
        assert result.json()["error_params"]["errors"][0]["field"] == "remote_api_key"
    assert client.put("/sandbox-config", json={"remote_api_key": "new", "clear_remote_api_key": True}).status_code == 422
    assert client.put("/llm-config", json={"enabled": True, "model": ""}).status_code == 422
    assert client.put("/llm-config", json={"enabled": False, "model": ""}).status_code == 200


def test_remote_save_preserves_docker_settings_and_saved_key(client, monkeypatch):
    current = SandboxConfig(cpu_limit="2.5", memory_limit="1g", pids_limit=128, remote_api_key="test-only-key")
    monkeypatch.setattr(SandboxConfig, "load", classmethod(lambda cls: current))
    response = client.put("/sandbox-config", json={"runtime": "remote", "cpu_limit": "invalid"})
    assert response.status_code == 200
    assert response.json()["cpu_limit"] == "2.5"
    assert response.json()["memory_limit"] == "1g"
    assert response.json()["pids_limit"] == 128
    assert response.json()["remote_api_key_configured"] is True
    assert "test-only-key" not in response.text


def test_connection_rejects_invalid_timeout_before_calling_remote(client, monkeypatch):
    from agent_manager.api import router as routes

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid settings must not call remote execution")

    monkeypatch.setattr(routes, "test_sandbox_connection", unexpected)
    response = client.post("/sandbox-config/test", json={"timeout_seconds": 15.6})
    assert response.status_code == 422
    assert response.json()["error_params"]["errors"][0]["field"] == "timeout_seconds"
