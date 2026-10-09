"""Validate remote service addresses before configuration or connection requests."""

import pytest

from agent_manager.core.sandbox import sandbox_url_error


@pytest.mark.parametrize("value", [
    "http://127.0.0.1:8194", "http://sandbox:8194", "https://example.com/base",
    "http://[::1]:8194", "http://localhost:8194/", "http://a/" + "x" * 2039,
])
def test_accepts_supported_base_urls(value):
    assert sandbox_url_error(value) is None


@pytest.mark.parametrize("value", [
    "example.com", "ftp://example.com", "http://", "http:///path",
    "http://127.0.0.1:8194http://127.0.0.1:8194",
    "http://localhost:65536", "http://localhost:0", "http://host/with space",
    "http://host/?q=1", "http://host/#section", "http://host\\path",
])
def test_rejects_invalid_base_urls(value):
    assert sandbox_url_error(value) == "sandbox.url_invalid"


def test_limit_and_optional_local_runtime_address():
    assert sandbox_url_error("http://a/" + "x" * 2040) == "sandbox.url_too_long"
    assert sandbox_url_error(None) == "sandbox.url_required"
    assert sandbox_url_error("", runtime="docker") is None


@pytest.mark.parametrize("value", [None, "", "invalid", "http://a/" + "x" * 2040])
def test_docker_does_not_validate_unused_remote_address(value):
    assert sandbox_url_error(value, runtime="docker") is None
    assert sandbox_url_error(value, runtime="remote") is not None


@pytest.mark.parametrize("method,path", [("put", "/sandbox-config"), ("post", "/sandbox-config/test")])
@pytest.mark.parametrize("value,code", [
    (None, "sandbox.url_required"),
    ("http://a/" + "x" * 2040, "sandbox.url_too_long"),
    ("not-a-url", "sandbox.url_invalid"),
])
def test_api_validation_preserves_error_envelope(method, path, value, code, monkeypatch):
    """Exercise both API entry points through the production error handler."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from agent_manager.api import router as routes
    from agent_manager.core.sandbox import SandboxConfig
    from backend.api_errors import ApiError, api_error_handler, http_error_handler

    monkeypatch.setattr(SandboxConfig, "load", classmethod(lambda cls: SandboxConfig()))

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid addresses must not be saved or sent to the service")

    monkeypatch.setattr(SandboxConfig, "save", unexpected)
    monkeypatch.setattr(routes, "test_sandbox_connection", unexpected)
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.put("/sandbox-config")(routes.update_sandbox_config)
    app.post("/sandbox-config/test")(routes.test_sandbox_config)
    client = TestClient(app)
    for locale in ("zh-CN", "en-US"):
        response = client.request(method, path, json={"runtime": "remote", "remote_url": value}, headers={"Accept-Language": locale})
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == code
        assert body["error_params"] == {}
        assert isinstance(body["detail"], str)
        assert "[object Object]" not in body["detail"]
        if locale == "en-US":
            assert body["detail"].isascii()
        else:
            assert any("\u4e00" <= char <= "\u9fff" for char in body["detail"])


@pytest.mark.parametrize("method,path", [("put", "/sandbox-config"), ("post", "/sandbox-config/test")])
@pytest.mark.parametrize("value,code", [
    (None, "sandbox.url_required"),
    ("http://a/" + "x" * 2040, "sandbox.url_too_long"),
    ("not-a-url", "sandbox.url_invalid"),
])
def test_standalone_api_error_envelope(method, path, value, code, monkeypatch):
    """Check the app built by the actual standalone CLI entry point."""
    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from agent_manager.api import api_cli
    from agent_manager.core.sandbox import SandboxConfig

    # 截获真实入口创建的应用，不启动监听端口或扫描器预热。
    apps = []
    monkeypatch.setattr(api_cli.uvicorn, "run", lambda app, **kwargs: apps.append(app))
    monkeypatch.setattr(SandboxConfig, "load", classmethod(lambda cls: SandboxConfig()))
    result = CliRunner().invoke(api_cli.main, ["--host", "127.0.0.1", "--port", "8081"])
    assert result.exit_code == 0, result.output
    assert len(apps) == 1
    client = TestClient(apps[0])
    for locale in ("zh-CN", "en-US"):
        response = client.request(
            method, path, json={"runtime": "remote", "remote_url": value},
            headers={"Accept-Language": locale},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == code
        assert body["error_params"] == {}
        assert body["detail"].isascii() == (locale == "en-US")
