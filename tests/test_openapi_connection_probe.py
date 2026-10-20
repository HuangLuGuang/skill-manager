import importlib
from pathlib import Path
import ssl

import httpx
import pytest


@pytest.fixture
def probe_module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path("services/agent-security-worker").resolve()))
    return importlib.import_module("connection_probe")


@pytest.mark.parametrize("status,payload,code", [
    (200, {"choices": [{"message": {"content": "OK"}}]}, None),
    (401, {"detail": "private error"}, "CONNECTION_AUTH_FAILED"),
    (403, {}, "CONNECTION_AUTH_FAILED"),
    (302, {}, "CONNECTION_PROTOCOL_INVALID"),
    (500, {}, "CONNECTION_PROTOCOL_INVALID"),
    (200, {"choices": []}, "CONNECTION_PROTOCOL_INVALID"),
    (200, {"choices": [{"message": {"content": " "}}]}, "CONNECTION_PROTOCOL_INVALID"),
])
def test_connection_response_checks(probe_module, monkeypatch, status, payload, code):
    original = httpx.Client
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status, json=payload, headers={"Location": "http://127.0.0.1/private"})
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    checks, error, _ = probe_module.probe({"endpoint_url": "https://10.1.1.1/v1", "resolved_ips": ["10.1.1.1"], "config": {"model": "test"}}, "test-key")
    assert error == code and len(calls) == 1
    assert checks["network"] == checks["tls"] == "passed"
    if code is None:
        assert checks["authentication"] == checks["protocol"] == "passed"


@pytest.mark.parametrize("failure,code", [("tls", "CONNECTION_TLS_FAILED"), ("timeout", "CONNECTION_TIMED_OUT"),
                                         ("network", "CONNECTION_NETWORK_FAILED"), ("large", "CONNECTION_PROTOCOL_INVALID")])
def test_connection_transport_failures(probe_module, monkeypatch, failure, code):
    original = httpx.Client
    def transport(request):
        if failure == "tls":
            raise httpx.ConnectError("certificate failed") from ssl.SSLCertVerificationError("test")
        if failure == "timeout":
            raise httpx.ReadTimeout("test")
        if failure == "network":
            raise httpx.ConnectError("test")
        return httpx.Response(200, content=b"x" * 101)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    checks, error, _ = probe_module.probe({"endpoint_url": "https://10.1.1.1/v1", "resolved_ips": ["10.1.1.1"], "config": {"model": "test"}}, "test-key", max_bytes=100)
    assert error == code
    if failure == "tls":
        assert checks["tls"] == "failed"


def test_changed_dns_prevents_request(probe_module, monkeypatch):
    def no_request(**kwargs):
        raise AssertionError("request must not be sent")
    monkeypatch.setattr(httpx, "Client", no_request)
    _, error, _ = probe_module.probe({"endpoint_url": "http://10.1.1.1/v1", "resolved_ips": ["10.1.1.2"], "config": {"model": "test"}}, "test-key")
    assert error == "CONNECTION_NETWORK_FAILED"


def test_worker_image_includes_connection_probe():
    source = Path("services/agent-security-worker/Dockerfile").read_text()
    assert "COPY services/agent-security-worker/connection_probe.py /app/connection_probe.py" in source
