from __future__ import annotations

import io
import json
import urllib.error

import pytest

import sys
from pathlib import Path


WORKER_DIR = Path("services/agent-security-worker").resolve()
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from aig_service_client import AigServiceClient, AigServiceError  # noqa: E402


class _Response:
    def __init__(self, body: dict | list | str, *, content_length: int | None = None):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self._stream = io.BytesIO(raw)
        self.headers = {"Content-Length": str(content_length if content_length is not None else len(raw))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_aig_service_client_creates_once_and_never_exposes_token(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response({"session_id": "aig-session-1", "created": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AigServiceClient("http://aig-scan-service:8091", "wrapper-secret")
    session_id = client.create_task(
        task_type="model_redteam_report",
        content={"model": [{"token": "target-secret"}]},
        idempotency_key="platform-task-attempt-stable",
    )

    assert session_id == "aig-session-1"
    request, timeout = requests[0]
    assert request.get_header("Authorization") == "Bearer wrapper-secret"
    assert request.get_header("Idempotency-key") == "platform-task-attempt-stable"
    assert timeout == 30.0
    assert "wrapper-secret" not in str(client)
    assert "target-secret" not in str(client)


def test_aig_service_client_validates_status_result_and_true_cancellation(monkeypatch):
    responses = iter(
        [
            _Response({"session_id": "session-2", "status": "running"}),
            _Response({"session_id": "session-2", "result": {"results": []}}),
            _Response({"session_id": "session-2", "status": "cancelled", "execution_stopped": True}),
        ]
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: next(responses))
    client = AigServiceClient("http://aig-scan-service:8091", "secret")

    assert client.get_status("session-2")["status"] == "running"
    assert client.get_result("session-2") == {"results": []}
    client.cancel_task("session-2")


def test_aig_service_client_rejects_invalid_json_and_oversized_responses(monkeypatch):
    client = AigServiceClient("http://aig-scan-service:8091", "secret", max_response_bytes=1024)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response("not-json"))
    with pytest.raises(AigServiceError, match="aig_result_invalid"):
        client.get_status("session-3")

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({}, content_length=2048),
    )
    with pytest.raises(AigServiceError, match="aig_result_invalid"):
        client.get_result("session-3")


def test_aig_service_client_maps_network_and_cancel_contract_failures(monkeypatch):
    client = AigServiceClient("http://aig-scan-service:8091", "secret")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(AigServiceError) as network:
        client.health()
    assert network.value.code == "agent_security.aig_service_unavailable"
    assert network.value.retryable is True
    assert "offline" not in str(network.value)

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"session_id": "session-4", "status": "cancelled", "execution_stopped": False}
        ),
    )
    with pytest.raises(AigServiceError, match="aig_task_cancel_failed"):
        client.cancel_task("session-4")
