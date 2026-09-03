from __future__ import annotations

import io
import json
import socket
import urllib.error

import pytest

from agent_manager.core.dify_console_client import (
    DifyConsoleClient,
    DifyConsoleClientConfig,
    DifyConsoleError,
)


class _Response:
    def __init__(self, payload: object, *, declared_length: int | None = None):
        self._stream = io.BytesIO(json.dumps(payload).encode())
        self.headers = {}
        if declared_length is not None:
            self.headers["Content-Length"] = str(declared_length)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _client(monkeypatch, responses, **overrides):
    monkeypatch.setattr(DifyConsoleClient, "_validate_url", lambda *_args, **_kwargs: None)
    config = DifyConsoleClientConfig(
        base_url="https://dify.example.test",
        workspace_id="workspace-test",
        app_id="app-test",
        admin_api_key="admin-test-secret",
        max_retries=overrides.pop("max_retries", 0),
        **overrides,
    )
    client = DifyConsoleClient(config)
    client._opener = _Opener(responses)
    return client


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://dify.example.test", status, "upstream", {}, None)


def test_export_uses_fixed_secret_exclusion_and_unwraps_real_envelope(monkeypatch):
    client = _client(monkeypatch, [_Response({"data": {"data": "app:\n  name: Demo\nworkflow:\n  graph:\n    nodes: []"}})])

    result = client.export_dsl(workflow_id="workflow-1")

    request = client._opener.requests[0][0]
    assert "include_secret=false" in request.full_url
    assert "workflow_id=workflow-1" in request.full_url
    assert result["app"]["name"] == "Demo"
    assert request.get_header("Authorization") == "Bearer admin-test-secret"
    assert request.get_header("X-workspace-id") == "workspace-test"


def test_draft_workflow_uses_console_draft_endpoint(monkeypatch):
    client = _client(monkeypatch, [_Response({"data": {"graph": {"nodes": []}, "version": "draft"}})])
    result = client.get_draft_workflow()
    assert result["graph"]["nodes"] == []
    assert "/console/api/apps/app-test/workflows/draft" in client._opener.requests[0][0].full_url


@pytest.mark.parametrize("status", [404, 405])
def test_draft_workflow_unavailable_has_dedicated_error(monkeypatch, status):
    client = _client(monkeypatch, [_http_error(status)])
    with pytest.raises(DifyConsoleError, match="draft_workflow_unavailable"):
        client.get_draft_workflow()


def test_draft_workflow_upstream_failure_has_dedicated_retryable_error(monkeypatch):
    client = _client(monkeypatch, [_http_error(503)])
    with pytest.raises(DifyConsoleError, match="draft_workflow_unavailable") as exc_info:
        client.get_draft_workflow()
    assert exc_info.value.retryable is True


@pytest.mark.parametrize("payload", [{"data": {}}, {"data": {"graph": {"nodes": {}}}}])
def test_invalid_draft_workflow_has_dedicated_error(monkeypatch, payload):
    client = _client(monkeypatch, [_Response(payload)])
    with pytest.raises(DifyConsoleError, match="draft_workflow_invalid"):
        client.get_draft_workflow()


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "dify_inventory.console_auth_failed"), (403, "dify_inventory.console_forbidden")],
)
def test_non_retryable_auth_statuses_use_stable_codes(monkeypatch, status, code):
    client = _client(monkeypatch, [_http_error(status)], max_retries=2)

    with pytest.raises(DifyConsoleError) as exc_info:
        client.get_app_detail()

    assert exc_info.value.code == code
    assert len(client._opener.requests) == 1
    assert "admin-test-secret" not in str(exc_info.value)


def test_app_and_export_404_have_distinct_meaning(monkeypatch):
    app_client = _client(monkeypatch, [_http_error(404)])
    with pytest.raises(DifyConsoleError, match="app_not_found"):
        app_client.get_app_detail()

    export_client = _client(monkeypatch, [_http_error(404)])
    with pytest.raises(DifyConsoleError, match="export_not_supported"):
        export_client.export_dsl()

    dataset_client = _client(monkeypatch, [_http_error(404)])
    with pytest.raises(DifyConsoleError, match="dataset_not_found"):
        dataset_client.get_dataset_detail("11111111-1111-4111-8111-111111111111")


def test_dataset_forbidden_has_dataset_specific_error(monkeypatch):
    client = _client(monkeypatch, [_http_error(403)])
    with pytest.raises(DifyConsoleError, match="dataset_forbidden"):
        client.get_dataset_detail("11111111-1111-4111-8111-111111111111")


def test_retryable_status_is_bounded(monkeypatch):
    monkeypatch.setattr("agent_manager.core.dify_console_client.time.sleep", lambda _delay: None)
    client = _client(monkeypatch, [_http_error(429), _Response({"data": {"name": "Demo"}})], max_retries=1)

    assert client.get_app_detail()["name"] == "Demo"
    assert len(client._opener.requests) == 2


def test_retryable_5xx_and_timeout_are_bounded(monkeypatch):
    monkeypatch.setattr("agent_manager.core.dify_console_client.time.sleep", lambda _delay: None)
    server_error = _client(monkeypatch, [_http_error(503), _http_error(503)], max_retries=1)
    with pytest.raises(DifyConsoleError) as server_exc:
        server_error.get_app_detail()
    assert server_exc.value.code == "dify_inventory.upstream_unavailable"
    assert len(server_error._opener.requests) == 2

    timed_out = _client(monkeypatch, [socket.timeout(), socket.timeout()], max_retries=1)
    with pytest.raises(DifyConsoleError) as timeout_exc:
        timed_out.get_app_detail()
    assert timeout_exc.value.code == "dify_inventory.upstream_unavailable"
    assert timeout_exc.value.retryable is True
    assert len(timed_out._opener.requests) == 2


def test_declared_and_streamed_response_limits_are_enforced(monkeypatch):
    declared = _client(monkeypatch, [_Response({}, declared_length=101)], max_response_bytes=100)
    with pytest.raises(DifyConsoleError, match="response_too_large"):
        declared.get_app_detail()

    streamed = _client(monkeypatch, [_Response({"data": "x" * 200})], max_response_bytes=100)
    with pytest.raises(DifyConsoleError, match="response_too_large"):
        streamed.get_app_detail()


def test_invalid_json_and_invalid_export_dsl_use_stable_codes(monkeypatch):
    invalid_json = _client(monkeypatch, [_Response({})])
    invalid_json._opener.responses = [type("Raw", (_Response,), {
        "__init__": lambda self: (setattr(self, "_stream", io.BytesIO(b"not-json")), setattr(self, "headers", {}))[-1],
    })()]
    with pytest.raises(DifyConsoleError, match="response_invalid"):
        invalid_json.get_app_detail()

    invalid_dsl = _client(monkeypatch, [_Response({"data": {"data": "- not-a-mapping"}})])
    with pytest.raises(DifyConsoleError, match="dsl_invalid"):
        invalid_dsl.export_dsl()


def test_document_and_segment_pagination_respects_limits(monkeypatch):
    client = _client(
        monkeypatch,
        [
            _Response({"data": {"data": [{"id": "d1"}], "has_more": True}}),
            _Response({"data": {"data": [{"id": "d2"}], "has_more": False}}),
            _Response({"data": {"data": [{"id": "s1"}], "has_more": True}}),
            _Response({"data": {"data": [{"id": "s2"}], "has_more": False}}),
        ],
    )

    assert [item["id"] for item in client.list_dataset_documents("dataset", limit=2)] == ["d1", "d2"]
    assert [item["id"] for item in client.list_document_segments("dataset", "document", limit=2)] == ["s1", "s2"]
    assert "/v1/datasets/dataset/documents?" in client._opener.requests[0][0].full_url
    assert "/segments?" in client._opener.requests[-1][0].full_url
