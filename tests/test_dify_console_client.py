from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

import pytest

from agent_manager.core.dify_console_client import (
    DifyConsoleClient,
    DifyConsoleClientConfig,
    DifyConsoleError,
    _PinnedHTTPSConnection,
    _connect_pinned,
    _ValidatedRedirectHandler,
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
    monkeypatch.setattr(DifyConsoleClient, "_validate_url", lambda *_args, **_kwargs: ("8.8.8.8",))
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


@pytest.mark.parametrize("kind", ["datasets", "documents", "segments"])
def test_top_level_pagination_envelope_preserves_has_more(monkeypatch, kind):
    client = _client(monkeypatch, [
        _Response({"data": [{"id": "one"}], "has_more": True}),
        _Response({"data": [{"id": "two"}], "has_more": False}),
    ])
    if kind == "datasets":
        rows = client.list_datasets(limit=2)
    elif kind == "documents":
        rows = client.list_dataset_documents("dataset", limit=2)
    else:
        rows = client.list_document_segments("dataset", "document", limit=2)
    assert [row["id"] for row in rows] == ["one", "two"]
    assert len(client._opener.requests) == 2


@pytest.mark.parametrize("kind", ["datasets", "documents", "segments"])
@pytest.mark.parametrize("requested_limit", [101, 150])
def test_pagination_uses_fixed_page_size_for_offset_apis(monkeypatch, kind, requested_limit):
    client = _client(monkeypatch, [])
    source = [{"id": str(index)} for index in range(150)]

    class PagingOpener:
        def __init__(self):
            self.requests = []

        def open(self, request, timeout):
            self.requests.append((request, timeout))
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
            page = int(query["page"][0])
            page_size = int(query["limit"][0])
            start = (page - 1) * page_size
            end = min(start + page_size, len(source))
            return _Response({"data": source[start:end], "has_more": end < len(source)})

    client._opener = PagingOpener()
    if kind == "datasets":
        rows = client.list_datasets(limit=requested_limit)
    elif kind == "documents":
        rows = client.list_dataset_documents("dataset", limit=requested_limit)
    else:
        rows = client.list_document_segments("dataset", "document", limit=requested_limit)

    assert [row["id"] for row in rows] == [str(index) for index in range(requested_limit)]
    assert {urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)["limit"][0]
            for request, _timeout in client._opener.requests} == {str(min(100, requested_limit))}


def test_pinned_https_keeps_hostname_for_sni_and_connects_to_ip(monkeypatch):
    connected = []

    class FakeSocket:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            connected.append(address)

    class FakeContext:
        def wrap_socket(self, sock, *, server_hostname):
            assert server_hostname == "dify.example.test"
            return sock

    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    connection = _PinnedHTTPSConnection(
        "dify.example.test", port=443, validated_ips=("203.0.113.7",), context=FakeContext(),
    )
    connection.connect()

    assert connected == [("203.0.113.7", 443)]


def test_pinned_connect_tries_all_validated_ips_and_closes_failed_socket(monkeypatch):
    sockets = []

    class FakeSocket:
        def __init__(self, should_fail):
            self.should_fail = should_fail
            self.closed = False

        def settimeout(self, timeout):
            pass

        def connect(self, address):
            if self.should_fail:
                raise OSError("unreachable")

        def close(self):
            self.closed = True

    def make_socket(*_args):
        sock = FakeSocket(not sockets)
        sockets.append(sock)
        return sock

    monkeypatch.setattr(socket, "socket", make_socket)
    result = _connect_pinned(("203.0.113.7", "203.0.113.8"), 443, 1.0, None)

    assert result is sockets[1]
    assert sockets[0].closed is True


def test_dns_rebinding_after_validation_cannot_change_connect_target(monkeypatch):
    resolutions = []
    connections = []

    def resolve(host, port, **_kwargs):
        resolutions.append(host)
        address = "8.8.8.8" if len(resolutions) <= 2 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 80))]

    class FakeSocket:
        def settimeout(self, timeout):
            pass

        def connect(self, address):
            connections.append(address)
            raise OSError("network disabled")

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    client = DifyConsoleClient(DifyConsoleClientConfig(
        base_url="http://dify.example.test", workspace_id="workspace", app_id="app",
        admin_api_key="secret", allow_insecure_transport=True,
        expected_ips=("8.8.8.8",), max_retries=0,
    ))

    with pytest.raises(DifyConsoleError):
        client.get_app_detail()
    assert connections == [("8.8.8.8", 80)]
    assert len(resolutions) == 2


def test_redirect_validation_pins_each_new_request():
    validated = []
    pinned = []

    def validate(url, redirect):
        validated.append((url, redirect))
        return ("203.0.113.8",)

    def pin(request, *, resolved):
        pinned.append((request.full_url, resolved))

    handler = _ValidatedRedirectHandler(validate, pin)
    request = urllib.request.Request("http://dify.example.test/start")
    redirected = handler.redirect_request(
        request, None, 302, "Found", {"Location": "http://dify.example.test/next"},
        "http://dify.example.test/next",
    )

    assert redirected is not None
    assert validated == [("http://dify.example.test/next", True)]
    assert pinned == [("http://dify.example.test/next", ("203.0.113.8",))]
