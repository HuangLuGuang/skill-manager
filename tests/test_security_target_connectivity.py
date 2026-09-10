from unittest.mock import MagicMock

import pytest

from backend.api_errors import ApiError
from backend.routers import security_scans
from backend.security_scan_schemas import SecurityTargetConnectivityRequest


def test_connectivity_uses_validated_ip(monkeypatch):
    monkeypatch.setattr(security_scans, "resolve_target_endpoint", lambda *a, **kw: ["93.184.216.34"])
    connect = MagicMock()
    monkeypatch.setattr(security_scans.socket, "create_connection", connect)
    result = security_scans.test_target_connectivity(SecurityTargetConnectivityRequest(endpoint_url="https://example.com:8443/api"))
    assert result["reachable"] is True
    assert connect.call_args.args[0] == ("93.184.216.34", 8443)
    assert 0 < connect.call_args.kwargs["timeout"] <= 5
    connect.return_value.__exit__.assert_called_once()


def test_connectivity_failure(monkeypatch):
    monkeypatch.setattr(security_scans, "resolve_target_endpoint", lambda *a, **kw: ["93.184.216.34"])
    monkeypatch.setattr(security_scans.socket, "create_connection", MagicMock(side_effect=TimeoutError))
    result = security_scans.test_target_connectivity(SecurityTargetConnectivityRequest(endpoint_url="https://example.com"))
    assert result == {"reachable": False, "error_code": "agent_security.target_connection_failed"}


@pytest.mark.parametrize("url", ["https://localhost", "https://169.254.169.254", "https://example.com:bad", "https://example.com:0"])
def test_connectivity_rejects_unsafe_or_invalid_target(monkeypatch, url):
    connect = MagicMock()
    monkeypatch.setattr(security_scans.socket, "create_connection", connect)
    with pytest.raises(ApiError):
        security_scans.test_target_connectivity(SecurityTargetConnectivityRequest(endpoint_url=url))
    connect.assert_not_called()
