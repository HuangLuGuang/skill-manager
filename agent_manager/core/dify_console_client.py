"""Bounded, secret-minimizing client for the self-hosted Dify Console API."""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

import yaml


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_FORBIDDEN_HOSTS = {"localhost", "metadata.google.internal", "instance-data.ec2.internal"}
_FORBIDDEN_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("100.100.100.200")}


class DifyConsoleError(RuntimeError):
    """Stable error without upstream response content or credentials."""

    def __init__(self, code: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class DifyConsoleClientConfig:
    base_url: str
    workspace_id: str
    app_id: str
    admin_api_key: str
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_retries: int = 2
    allow_insecure_transport: bool = False
    allowed_cidrs: tuple[str, ...] = ()
    allowed_redirect_hosts: tuple[str, ...] = ()
    expected_ips: tuple[str, ...] = ()


def _allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address, cidrs: tuple[str, ...]) -> bool:
    if address in _FORBIDDEN_IPS:
        return False
    if address.is_global:
        return True
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        return False
    return address.is_private and any(address in ipaddress.ip_network(value, strict=True) for value in cidrs)


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str, bool], tuple[str, ...]], pinner):  # noqa: ANN001
        super().__init__()
        self._validator = validator
        self._pinner = pinner

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        resolved = self._validator(newurl, True)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            self._pinner(redirected, resolved=resolved)
            redirected.add_unredirected_header("Authorization", req.get_header("Authorization"))
            redirected.add_unredirected_header("X-WORKSPACE-ID", req.get_header("X-workspace-id"))
        return redirected


def _connect_pinned(
    addresses: tuple[str, ...],
    port: int,
    timeout: float,
    source_address,
):
    last_error = None
    for address in addresses:
        sock = None
        try:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect((address, port))
            return sock
        except OSError as exc:
            last_error = exc
            if sock is not None:
                sock.close()
    raise last_error or OSError("no validated upstream address")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, *, validated_ips: tuple[str, ...], **kwargs):  # noqa: ANN001
        super().__init__(host, **kwargs)
        self._validated_ips = validated_ips

    def connect(self) -> None:
        self.sock = _connect_pinned(self._validated_ips, self.port, self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, validated_ips: tuple[str, ...], **kwargs):  # noqa: ANN001
        super().__init__(host, **kwargs)
        self._validated_ips = validated_ips

    def connect(self) -> None:
        self.sock = _connect_pinned(self._validated_ips, self.port, self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        except OSError:
            self.sock.close()
            raise


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # noqa: ANN001
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPConnection(
                host, validated_ips=req._dify_valid_ips, **kwargs,
            ), req,
        )


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # noqa: ANN001
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(
                host, validated_ips=req._dify_valid_ips, **kwargs,
            ), req, context=self._context,
        )


class DifyConsoleClient:
    def __init__(self, config: DifyConsoleClientConfig):
        self.config = config
        self._base = config.base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(self._base)
        self._base_host = (parsed.hostname or "").lower()
        self._allowed_hosts = {self._base_host, *(value.lower() for value in config.allowed_redirect_hosts)}
        self._validate_url(self._base, False)
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _PinnedHTTPHandler(),
            _PinnedHTTPSHandler(context=ssl.create_default_context()),
            _ValidatedRedirectHandler(self._validate_url, self._pin_request),
        )

    def _resolve(self, hostname: str, port: int | None) -> tuple[str, ...]:
        try:
            literal = ipaddress.ip_address(hostname.strip("[]"))
            values = (str(literal),)
        except ValueError:
            try:
                records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise DifyConsoleError("dify_inventory.upstream_unavailable", retryable=True) from exc
            values = tuple(sorted({record[4][0] for record in records}))
        if not values:
            raise DifyConsoleError("dify_inventory.upstream_unavailable", retryable=True)
        for value in values:
            if not _allowed_address(ipaddress.ip_address(value), self.config.allowed_cidrs):
                raise DifyConsoleError("dify_inventory.upstream_unavailable")
        return values

    def _validate_url(self, url: str, redirect: bool) -> tuple[str, ...]:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme != "https" and not (scheme == "http" and self.config.allow_insecure_transport):
            raise DifyConsoleError("dify_inventory.upstream_unavailable")
        if parsed.username or parsed.password or parsed.fragment:
            raise DifyConsoleError("dify_inventory.upstream_unavailable")
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname in _FORBIDDEN_HOSTS or hostname not in self._allowed_hosts:
            raise DifyConsoleError("dify_inventory.upstream_unavailable")
        resolved = self._resolve(hostname, parsed.port)
        if not redirect and self.config.expected_ips and set(resolved) != set(self.config.expected_ips):
            raise DifyConsoleError("dify_inventory.upstream_unavailable")
        return resolved

    def _pin_request(
        self,
        request: urllib.request.Request,
        *,
        resolved: tuple[str, ...],
        enforce_expected: bool = False,
    ) -> None:
        if enforce_expected and self.config.expected_ips and set(resolved) != set(self.config.expected_ips):
            raise DifyConsoleError("dify_inventory.upstream_unavailable")
        request._dify_valid_ips = resolved

    @staticmethod
    def _error_for_status(status: int) -> DifyConsoleError:
        if status == 401:
            return DifyConsoleError("dify_inventory.console_auth_failed", status=status)
        if status == 403:
            return DifyConsoleError("dify_inventory.console_forbidden", status=status)
        if status == 404:
            return DifyConsoleError("dify_inventory.app_not_found", status=status)
        return DifyConsoleError(
            "dify_inventory.upstream_unavailable",
            status=status,
            retryable=status in _RETRYABLE_STATUSES,
        )

    def _read_bounded(self, response) -> bytes:  # noqa: ANN001
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > self.config.max_response_bytes:
                    raise DifyConsoleError("dify_inventory.response_too_large")
            except ValueError:
                pass
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(min(64 * 1024, self.config.max_response_bytes + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > self.config.max_response_bytes:
                raise DifyConsoleError("dify_inventory.response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _request_json(self, path: str, *, query: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or ".." in path:
            raise DifyConsoleError("dify_inventory.response_invalid")
        url = f"{self._base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        resolved = self._validate_url(url, False)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.config.admin_api_key}",
                "X-WORKSPACE-ID": self.config.workspace_id,
                "Accept": "application/json",
            },
            method="GET",
        )
        self._pin_request(request, resolved=resolved, enforce_expected=True)
        for attempt in range(self.config.max_retries + 1):
            try:
                with self._opener.open(
                    request,
                    timeout=max(self.config.connect_timeout_seconds, self.config.read_timeout_seconds),
                ) as response:
                    raw = self._read_bounded(response)
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DifyConsoleError("dify_inventory.response_invalid") from exc
            except urllib.error.HTTPError as exc:
                error = self._error_for_status(exc.code)
                if not error.retryable or attempt >= self.config.max_retries:
                    raise error from exc
                retry_after = exc.headers.get("Retry-After")
                try:
                    delay = min(2.0, max(0.0, float(retry_after))) if retry_after else 0.25 * (2**attempt)
                except ValueError:
                    delay = 0.25 * (2**attempt)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt >= self.config.max_retries:
                    raise DifyConsoleError("dify_inventory.upstream_unavailable", retryable=True) from exc
                time.sleep(0.25 * (2**attempt))
        raise DifyConsoleError("dify_inventory.upstream_unavailable", retryable=True)

    @staticmethod
    def _data(payload: Any) -> Any:
        if not isinstance(payload, dict):
            raise DifyConsoleError("dify_inventory.response_invalid")
        return payload.get("data", payload)

    @classmethod
    def _paged_items(cls, payload: Any) -> tuple[Any, bool]:
        envelope = payload if isinstance(payload, dict) else None
        data = cls._data(payload)
        if isinstance(data, dict):
            envelope = data
            items = data.get("data") or data.get("items") or []
        else:
            items = data
        return items, bool(envelope and envelope.get("has_more"))

    def get_app_detail(self, app_id: str | None = None) -> dict[str, Any]:
        selected = urllib.parse.quote(app_id or self.config.app_id, safe="")
        data = self._data(self._request_json(f"/console/api/apps/{selected}"))
        if not isinstance(data, dict):
            raise DifyConsoleError("dify_inventory.response_invalid")
        return data

    def export_dsl(self, app_id: str | None = None, workflow_id: str | None = None) -> dict[str, Any]:
        selected = urllib.parse.quote(app_id or self.config.app_id, safe="")
        query: dict[str, Any] = {"include_secret": "false"}
        if workflow_id:
            query["workflow_id"] = workflow_id
        try:
            payload = self._request_json(f"/console/api/apps/{selected}/export", query=query)
        except DifyConsoleError as exc:
            if exc.code == "dify_inventory.app_not_found":
                raise DifyConsoleError("dify_inventory.export_not_supported", status=exc.status) from exc
            raise
        data = self._data(payload)
        if isinstance(data, dict) and "data" in data and len(data) <= 3:
            data = data.get("data")
        if isinstance(data, str):
            try:
                data = yaml.safe_load(data)
            except yaml.YAMLError as exc:
                raise DifyConsoleError("dify_inventory.dsl_invalid") from exc
        if not isinstance(data, dict):
            raise DifyConsoleError("dify_inventory.dsl_invalid")
        return data

    def get_draft_workflow(self, app_id: str | None = None) -> dict[str, Any]:
        """Read the current draft workflow; callers must minimize it before persistence."""
        selected = urllib.parse.quote(app_id or self.config.app_id, safe="")
        try:
            payload = self._request_json(f"/console/api/apps/{selected}/workflows/draft")
        except DifyConsoleError as exc:
            if exc.status in {404, 405}:
                raise DifyConsoleError(
                    "dify_inventory.draft_workflow_unavailable", status=exc.status,
                ) from exc
            if exc.code == "dify_inventory.response_invalid":
                raise DifyConsoleError("dify_inventory.draft_workflow_invalid") from exc
            if exc.code == "dify_inventory.upstream_unavailable":
                raise DifyConsoleError(
                    "dify_inventory.draft_workflow_unavailable",
                    status=exc.status,
                    retryable=exc.retryable,
                ) from exc
            raise
        data = self._data(payload)
        graph = data.get("graph") if isinstance(data, dict) else None
        if not isinstance(data, dict) or not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
            raise DifyConsoleError("dify_inventory.draft_workflow_invalid")
        return data

    def get_workflow_detail(self, app_id: str | None = None) -> dict[str, Any]:
        """Backward-compatible alias for callers using the former method name."""
        return self.get_draft_workflow(app_id)

    def get_dataset_detail(self, dataset_id: str) -> dict[str, Any]:
        selected = urllib.parse.quote(dataset_id, safe="")
        try:
            data = self._data(self._request_json(f"/v1/datasets/{selected}"))
        except DifyConsoleError as exc:
            if exc.code == "dify_inventory.app_not_found":
                raise DifyConsoleError("dify_inventory.dataset_not_found", status=exc.status) from exc
            if exc.code == "dify_inventory.console_forbidden":
                raise DifyConsoleError("dify_inventory.dataset_forbidden", status=exc.status) from exc
            raise
        if not isinstance(data, dict):
            raise DifyConsoleError("dify_inventory.response_invalid")
        return data

    def list_datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        page = 1
        page_size = min(100, limit)
        rows: list[dict[str, Any]] = []
        while len(rows) < limit:
            try:
                payload = self._request_json(
                    "/v1/datasets", query={"page": page, "limit": page_size},
                )
            except DifyConsoleError as exc:
                if exc.code == "dify_inventory.console_forbidden":
                    raise DifyConsoleError("dify_inventory.dataset_forbidden", status=exc.status) from exc
                raise
            items, has_more = self._paged_items(payload)
            if not isinstance(items, list):
                raise DifyConsoleError("dify_inventory.response_invalid")
            rows.extend(item for item in items if isinstance(item, dict))
            if not has_more or not items:
                break
            page += 1
        return rows[:limit]

    def list_dataset_documents(self, dataset_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        selected = urllib.parse.quote(dataset_id, safe="")
        page = 1
        page_size = min(100, limit)
        rows: list[dict[str, Any]] = []
        while len(rows) < limit:
            try:
                payload = self._request_json(
                    f"/v1/datasets/{selected}/documents",
                    query={"page": page, "limit": page_size},
                )
            except DifyConsoleError as exc:
                if exc.code == "dify_inventory.app_not_found":
                    raise DifyConsoleError("dify_inventory.dataset_not_found", status=exc.status) from exc
                if exc.code == "dify_inventory.console_forbidden":
                    raise DifyConsoleError("dify_inventory.dataset_forbidden", status=exc.status) from exc
                raise
            items, has_more = self._paged_items(payload)
            if not isinstance(items, list):
                raise DifyConsoleError("dify_inventory.response_invalid")
            rows.extend(item for item in items if isinstance(item, dict))
            if not has_more or not items:
                break
            page += 1
        return rows[:limit]

    def list_document_segments(
        self,
        dataset_id: str,
        document_id: str,
        *,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        selected_dataset = urllib.parse.quote(dataset_id, safe="")
        selected_document = urllib.parse.quote(document_id, safe="")
        page = 1
        page_size = min(100, limit)
        rows: list[dict[str, Any]] = []
        while len(rows) < limit:
            try:
                payload = self._request_json(
                    f"/v1/datasets/{selected_dataset}/documents/{selected_document}/segments",
                    query={"page": page, "limit": page_size},
                )
            except DifyConsoleError as exc:
                if exc.code == "dify_inventory.app_not_found":
                    raise DifyConsoleError("dify_inventory.dataset_not_found", status=exc.status) from exc
                if exc.code == "dify_inventory.console_forbidden":
                    raise DifyConsoleError("dify_inventory.dataset_forbidden", status=exc.status) from exc
                raise
            items, has_more = self._paged_items(payload)
            if not isinstance(items, list):
                raise DifyConsoleError("dify_inventory.response_invalid")
            rows.extend(item for item in items if isinstance(item, dict))
            if not has_more or not items:
                break
            page += 1
        return rows[:limit]
