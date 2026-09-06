from __future__ import annotations

import json
import ipaddress
import os
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field


ENGINE_TAG = "v4.6.0"
ENGINE_COMMIT = "e8931cc68001b66ad024fd87ef07394e9e96524a"
SUPPORTED_TASK_TYPES = {"model_redteam_report", "ai_infra_scan"}
TERMINAL_STATUSES = {"completed", "done", "failed", "error", "cancelled", "terminated"}
ACTIVE_STATUSES = {"pending", "todo", "running", "doing"}
MAX_REQUEST_BYTES = 1024 * 1024
MAX_UPSTREAM_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TARGETS = 32
MAX_PROMPTS = 100
DATASET_DIRECTORY = Path(
    os.environ.get("AIG_RUNTIME_DIR", str(Path(__file__).parent / "vendor" / "ai-infra-guard"))
) / "data" / "eval"
ALLOWED_DATASETS = {path.stem for path in DATASET_DIRECTORY.glob("*.json") if path.is_file()}
ALLOWED_TECHNIQUES = {
    "Raw",
    "BaseEncoding",
    "Leetspeak",
    "PromptInjection",
    "Roleplay",
    "ROTEncoding",
    "SystemOverride",
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def _failure_code(message: str) -> str:
    # Upstream errors may contain request bodies or credentials; return only classifications.
    text = message[:65536].lower()
    if "404" in text:
        return "agent_security.aig_model_not_found"
    if "401" in text or "403" in text:
        return "agent_security.aig_model_auth_failed"
    if "429" in text:
        return "agent_security.aig_model_rate_limited"
    if "timeout" in text or "timed out" in text:
        return "agent_security.aig_model_timeout"
    if "connection" in text or "connecterror" in text:
        return "agent_security.aig_model_connection_failed"
    if "加载模型" in text:
        return "agent_security.aig_model_initialization_failed"
    return "agent_security.aig_task_failed"


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(min_length=1, max_length=64)
    content: dict[str, Any]


def _bounded_string(value: Any, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise ServiceError(422, "agent_security.aig_task_failed")
    normalized = value.strip()
    if len(normalized) < minimum or len(normalized) > maximum or any(char in normalized for char in "\r\n\x00"):
        raise ServiceError(422, "agent_security.aig_task_failed")
    return normalized


def _bounded_int(value: Any, *, minimum: int, maximum: int, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise ServiceError(422, "agent_security.aig_task_failed")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceError(422, "agent_security.aig_task_failed") from exc
    if normalized < minimum or normalized > maximum:
        raise ServiceError(422, "agent_security.aig_task_failed")
    return normalized


def _validate_model(value: Any, *, require_token: bool = True) -> None:
    if not isinstance(value, dict) or set(value) - {"model", "token", "base_url", "limit"}:
        raise ServiceError(422, "agent_security.aig_task_failed")
    _bounded_string(value.get("model"), maximum=256)
    if isinstance(value.get("token"), str) and any(char in value["token"] for char in "\r\n\x00"):
        raise ServiceError(422, "agent_security.aig_task_failed")
    _bounded_string(value.get("token"), minimum=1 if require_token else 0, maximum=8192)
    base_url = _bounded_string(value.get("base_url"), maximum=2048)
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ServiceError(422, "agent_security.aig_task_failed")
    _bounded_int(value.get("limit"), minimum=1, maximum=8, default=1)


def _validate_headers(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or len(value) > 32:
        raise ServiceError(422, "agent_security.aig_task_failed")
    for key, item in value.items():
        _bounded_string(key, maximum=128)
        _bounded_string(item, minimum=0, maximum=8192)


def _address_allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address, cidrs: list[str]) -> bool:
    if not address.is_private:
        return True
    try:
        return any(address in ipaddress.ip_network(value, strict=False) for value in cidrs)
    except ValueError as exc:
        raise ServiceError(422, "agent_security.infra_target_forbidden") from exc


def _validate_infrastructure_network_policy(targets: list[str], value: Any) -> None:
    if not isinstance(value, dict) or set(value) - {
        "expected_ips",
        "allowed_cidrs",
        "policy_allowed_cidrs",
        "allow_http",
    }:
        raise ServiceError(422, "agent_security.infra_target_forbidden")
    expected = value.get("expected_ips")
    target_cidrs = value.get("allowed_cidrs") or []
    policy_cidrs = value.get("policy_allowed_cidrs") or []
    if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
        raise ServiceError(422, "agent_security.infra_target_forbidden")
    if not isinstance(target_cidrs, list) or not isinstance(policy_cidrs, list):
        raise ServiceError(422, "agent_security.infra_target_forbidden")

    current: set[str] = set()
    for target in targets:
        parsed = urlsplit(target)
        if parsed.scheme == "http" and value.get("allow_http") is not True:
            raise ServiceError(422, "agent_security.infra_target_forbidden")
        try:
            answers = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise ServiceError(422, "agent_security.infra_target_forbidden") from exc
        for answer in answers:
            address = ipaddress.ip_address(answer[4][0])
            if (
                address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
                or str(address) in {"169.254.169.254", "100.100.100.200"}
            ):
                raise ServiceError(422, "agent_security.infra_target_forbidden")
            if not _address_allowed(address, target_cidrs) or not _address_allowed(address, policy_cidrs):
                raise ServiceError(422, "agent_security.infra_private_address_forbidden")
            current.add(str(address))
    if current != set(expected):
        raise ServiceError(409, "agent_security.infra_target_forbidden")


def _validate_task_content(task_type: str, content: dict[str, Any]) -> None:
    if task_type == "ai_infra_scan":
        if set(content) - {"target", "headers", "timeout", "model", "network_policy"}:
            raise ServiceError(422, "agent_security.aig_task_failed")
        targets = content.get("target")
        if not isinstance(targets, list) or not 1 <= len(targets) <= MAX_TARGETS:
            raise ServiceError(422, "agent_security.aig_task_failed")
        for target in targets:
            endpoint = _bounded_string(target, maximum=2048)
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ServiceError(422, "agent_security.aig_task_failed")
        _validate_headers(content.get("headers"))
        _validate_infrastructure_network_policy(targets, content.get("network_policy"))
        _bounded_int(content.get("timeout"), minimum=1, maximum=120, default=30)
        _validate_model(content.get("model"))
        return

    if set(content) - {"model", "eval_model", "dataset", "prompt", "techniques"}:
        raise ServiceError(422, "agent_security.aig_task_failed")
    models = content.get("model")
    if not isinstance(models, list) or not 1 <= len(models) <= 4:
        raise ServiceError(422, "agent_security.aig_task_failed")
    for model in models:
        _validate_model(model, require_token=False)
    _validate_model(content.get("eval_model"))
    dataset = content.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) - {"dataFile", "numPrompts", "randomSeed", "promptColumn"}:
        raise ServiceError(422, "agent_security.aig_task_failed")
    data_files = dataset.get("dataFile") or []
    if not isinstance(data_files, list) or any(item not in ALLOWED_DATASETS for item in data_files):
        raise ServiceError(422, "agent_security.aig_task_failed")
    _bounded_int(dataset.get("numPrompts"), minimum=1, maximum=MAX_PROMPTS)
    _bounded_int(dataset.get("randomSeed"), minimum=0, maximum=2_147_483_647, default=42)
    if dataset.get("promptColumn") not in {None, "prompt"}:
        raise ServiceError(422, "agent_security.aig_task_failed")
    prompt = content.get("prompt") or ""
    if not isinstance(prompt, str) or len(prompt) > 8192:
        raise ServiceError(422, "agent_security.aig_task_failed")
    if bool(data_files) == bool(prompt.strip()):
        raise ServiceError(422, "agent_security.aig_task_failed")
    techniques = content.get("techniques") or ["Raw"]
    if not isinstance(techniques, list) or not 1 <= len(techniques) <= 8 or any(
        item not in ALLOWED_TECHNIQUES for item in techniques
    ):
        raise ServiceError(422, "agent_security.aig_task_failed")


class UpstreamClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("AIG upstream must be loopback-only HTTP")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json", "username": "agent-manager-worker"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                length = response.headers.get("Content-Length")
                if length and int(length) > MAX_UPSTREAM_RESPONSE_BYTES:
                    raise ServiceError(502, "agent_security.aig_result_invalid")
                raw = response.read(MAX_UPSTREAM_RESPONSE_BYTES + 1)
        except ServiceError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ServiceError(503, "agent_security.aig_service_unavailable") from exc
        if len(raw) > MAX_UPSTREAM_RESPONSE_BYTES:
            raise ServiceError(502, "agent_security.aig_result_invalid")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceError(502, "agent_security.aig_result_invalid") from exc
        if not isinstance(body, dict):
            raise ServiceError(502, "agent_security.aig_result_invalid")
        return body

    @staticmethod
    def _data(body: dict[str, Any], *, error_code: str) -> dict[str, Any]:
        if body.get("status") != 0 or not isinstance(body.get("data"), dict):
            raise ServiceError(502, error_code)
        return body["data"]

    def health(self) -> None:
        self._request("GET", "/api/v1/version")

    def create_task(self, task_type: str, content: dict[str, Any]) -> str:
        data = self._data(
            self._request("POST", "/api/v1/app/taskapi/tasks", {"type": task_type, "content": content}),
            error_code="agent_security.aig_task_failed",
        )
        session_id = str(data.get("session_id") or "").strip()
        if not session_id or len(session_id) > 128:
            raise ServiceError(502, "agent_security.aig_result_invalid")
        return session_id

    def status(self, session_id: str) -> dict[str, Any]:
        return self._data(
            self._request("GET", f"/api/v1/app/taskapi/status/{quote(session_id, safe='')}") ,
            error_code="agent_security.aig_task_failed",
        )

    def result(self, session_id: str) -> dict[str, Any]:
        data = self._data(
            self._request("GET", f"/api/v1/app/taskapi/result/{quote(session_id, safe='')}") ,
            error_code="agent_security.aig_task_failed",
        )
        result = data.get("result")
        if not isinstance(result, dict):
            raise ServiceError(502, "agent_security.aig_result_invalid")
        return result

    def request_termination(self, session_id: str) -> bool:
        try:
            body = self._request(
                "POST",
                f"/api/v1/app/tasks/{quote(session_id, safe='')}/terminate",
                {},
            )
        except ServiceError:
            return False
        return body.get("status") == 0


class AgentProcessSupervisor:
    def __init__(
        self,
        command: list[str],
        *,
        ready_seconds: float = 2.0,
        cwd: str | None = None,
    ) -> None:
        if not command or any(not part for part in command):
            raise RuntimeError("AIG agent command is required")
        self.command = command
        self.ready_seconds = max(0.0, min(float(ready_seconds), 30.0))
        self.cwd = cwd
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def ensure_running(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
                cwd=self.cwd,
            )
        if self.ready_seconds:
            time.sleep(self.ready_seconds)
        if not self.is_running():
            raise ServiceError(503, "agent_security.aig_service_unavailable")

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def stop_execution(self) -> bool:
        with self._lock:
            process = self._process
            self._process = None
        if process is None or process.poll() is not None:
            return True
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        except (OSError, ProcessLookupError):
            return process.poll() is not None
        return process.poll() is not None

    def restart_after_cancel(self) -> bool:
        if not self.stop_execution():
            return False
        self.ensure_running()
        return True


class TaskRegistry:
    def __init__(self, path: Path, *, max_jobs: int = 100) -> None:
        self.path = path
        self.max_jobs = max(1, min(int(max_jobs), 10_000))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "idempotency_key TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, "
                "task_type TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def by_idempotency(self, key: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT idempotency_key, session_id, task_type, status FROM jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return dict(zip(("idempotency_key", "session_id", "task_type", "status"), row, strict=True))

    def by_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT idempotency_key, session_id, task_type, status FROM jobs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return dict(zip(("idempotency_key", "session_id", "task_type", "status"), row, strict=True))

    def active(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._connect() as db:
            rows = db.execute(
                f"SELECT idempotency_key, session_id, task_type, status FROM jobs WHERE status IN ({placeholders})",
                tuple(ACTIVE_STATUSES),
            ).fetchall()
        keys = ("idempotency_key", "session_id", "task_type", "status")
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def add(self, key: str, session_id: str, task_type: str) -> None:
        now = time.time()
        with self._lock, self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if count >= self.max_jobs:
                db.execute(
                    "DELETE FROM jobs WHERE session_id IN ("
                    "SELECT session_id FROM jobs WHERE status IN ('completed','done','failed','error','cancelled','terminated') "
                    "ORDER BY updated_at ASC LIMIT ?)",
                    (max(1, count - self.max_jobs + 1),),
                )
            db.execute(
                "INSERT INTO jobs (idempotency_key, session_id, task_type, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?)",
                (key, session_id, task_type, now, now),
            )

    def update_status(self, session_id: str, status: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, time.time(), session_id),
            )


class Runtime:
    def __init__(
        self,
        upstream: UpstreamClient,
        supervisor: AgentProcessSupervisor,
        registry: TaskRegistry,
        *,
        server_supervisor: AgentProcessSupervisor | None = None,
    ) -> None:
        self.upstream = upstream
        self.supervisor = supervisor
        self.registry = registry
        self.server_supervisor = server_supervisor
        self._create_lock = threading.Lock()

    def start(self) -> None:
        if self.server_supervisor is not None:
            self.server_supervisor.ensure_running()
            deadline = time.monotonic() + 30
            while True:
                try:
                    self.upstream.health()
                    break
                except ServiceError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.25)
        self.supervisor.ensure_running()
        self._reconcile_active()

    def stop(self) -> None:
        self.supervisor.stop_execution()
        if self.server_supervisor is not None:
            self.server_supervisor.stop_execution()

    def create(self, task_type: str, content: dict[str, Any], idempotency_key: str) -> tuple[str, bool]:
        if task_type not in SUPPORTED_TASK_TYPES:
            raise ServiceError(422, "agent_security.aig_task_failed")
        if not _SAFE_IDENTIFIER.fullmatch(idempotency_key):
            raise ServiceError(422, "agent_security.aig_task_failed")
        _validate_task_content(task_type, content)
        encoded = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ServiceError(413, "agent_security.aig_task_failed")
        with self._create_lock:
            existing = self.registry.by_idempotency(idempotency_key)
            if existing:
                if existing["task_type"] != task_type:
                    raise ServiceError(409, "agent_security.aig_task_failed")
                return existing["session_id"], False
            self._reconcile_active()
            if self.registry.active():
                raise ServiceError(429, "agent_security.aig_service_unavailable")
            self.supervisor.ensure_running()
            session_id = self.upstream.create_task(task_type, content)
            self.registry.add(idempotency_key, session_id, task_type)
            return session_id, True

    def _reconcile_active(self) -> None:
        for job in self.registry.active():
            try:
                data = self.upstream.status(job["session_id"])
            except ServiceError as exc:
                if exc.code == "agent_security.aig_task_failed":
                    self.registry.update_status(job["session_id"], "error")
                    continue
                raise
            status = str(data.get("status") or "unverified").lower()
            if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
                raise ServiceError(502, "agent_security.aig_result_invalid")
            self.registry.update_status(job["session_id"], status)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ServiceError(404, "agent_security.aig_task_failed")

    def status(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        if not self.registry.by_session(session_id):
            raise ServiceError(404, "agent_security.aig_task_failed")
        data = self.upstream.status(session_id)
        status = str(data.get("status") or "unverified").lower()
        if status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            raise ServiceError(502, "agent_security.aig_result_invalid")
        self.registry.update_status(session_id, status)
        result = {key: data[key] for key in ("session_id", "status", "created_at", "updated_at") if key in data}
        if status in {"error", "failed"}:
            result["error_code"] = _failure_code(str(data.get("error_message") or ""))
        return result

    def result(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        if not self.registry.by_session(session_id):
            raise ServiceError(404, "agent_security.aig_task_failed")
        return self.upstream.result(session_id)

    def cancel(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        if not self.registry.by_session(session_id):
            raise ServiceError(404, "agent_security.aig_task_failed")
        upstream_acknowledged = self.upstream.request_termination(session_id)
        try:
            execution_stopped = self.supervisor.restart_after_cancel()
        except ServiceError:
            execution_stopped = False
        if not execution_stopped:
            raise ServiceError(500, "agent_security.aig_task_cancel_failed")
        self.registry.update_status(session_id, "cancelled")
        return {
            "session_id": session_id,
            "status": "cancelled",
            "execution_stopped": True,
            "upstream_acknowledged": upstream_acknowledged,
        }


def _default_runtime() -> Runtime:
    upstream_url = os.environ.get("AIG_UPSTREAM_URL", "http://127.0.0.1:18088")
    server_host = urlsplit(upstream_url).netloc
    agent_bin = os.environ.get("AIG_AGENT_BIN", "/opt/aig/bin/agent")
    server_bin = os.environ.get("AIG_SERVER_BIN", "/opt/aig/bin/ai-infra-guard")
    runtime_dir = os.environ.get("AIG_RUNTIME_DIR", "/opt/aig")
    registry_path = Path(os.environ.get("AIG_WRAPPER_DB", "/tmp/aig-wrapper/jobs.db"))
    return Runtime(
        UpstreamClient(upstream_url),
        AgentProcessSupervisor(
            [agent_bin, "-server", server_host],
            ready_seconds=float(os.environ.get("AIG_AGENT_READY_SECONDS", "2")),
            cwd=runtime_dir,
        ),
        TaskRegistry(registry_path, max_jobs=int(os.environ.get("AIG_WRAPPER_MAX_JOBS", "100"))),
        server_supervisor=AgentProcessSupervisor(
            [server_bin, "webserver", "--server", "127.0.0.1:18088"],
            ready_seconds=0,
            cwd=runtime_dir,
        ),
    )


def create_app(runtime: Runtime | None = None, *, manage_runtime: bool = True) -> FastAPI:
    service_runtime = runtime or _default_runtime()
    service_token = os.environ.get("AIG_WRAPPER_TOKEN", "").strip()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if manage_runtime:
            if not service_token:
                raise RuntimeError("AIG wrapper service token is required")
            for writable_path in ("/tmp/aig-home", "/tmp/uv-cache", "/tmp/aig-redteam/logs"):
                Path(writable_path).mkdir(parents=True, exist_ok=True)
            service_runtime.start()
        try:
            yield
        finally:
            if manage_runtime:
                service_runtime.stop()

    app = FastAPI(title="Agent Manager AIG Scan Service", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": "AI scanning service request failed", "error_code": exc.code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid AI scanning service request", "error_code": "agent_security.aig_task_failed"},
        )

    async def authenticate(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {service_token}"
        if not service_token or not authorization or not secrets.compare_digest(authorization, expected):
            raise ServiceError(401, "agent_security.aig_service_unavailable")

    @app.middleware("http")
    async def request_size_limit(request: Request, call_next):
        length = request.headers.get("content-length")
        if request.method in {"POST", "PUT", "PATCH"} and length is None:
            return JSONResponse(
                status_code=411,
                content={"detail": "Content-Length required", "error_code": "agent_security.aig_task_failed"},
            )
        if length is not None:
            try:
                if int(length) > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large", "error_code": "agent_security.aig_task_failed"},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid request", "error_code": "agent_security.aig_task_failed"},
                )
        return await call_next(request)

    @app.get("/healthz")
    async def health(_auth: None = Depends(authenticate)):
        service_runtime.upstream.health()
        if not service_runtime.supervisor.is_running():
            raise ServiceError(503, "agent_security.aig_service_unavailable")
        return {
            "status": "ok",
            "engine": {"name": "AI-Infra-Guard", "tag": ENGINE_TAG, "commit": ENGINE_COMMIT},
            "cancellation_mode": "agent_process_group_termination",
            "max_concurrency": 1,
        }

    @app.post("/v1/tasks")
    async def create_task(
        body: TaskCreate,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _auth: None = Depends(authenticate),
    ):
        key = (idempotency_key or "").strip()
        if not _SAFE_IDENTIFIER.fullmatch(key):
            raise ServiceError(422, "agent_security.aig_task_failed")
        session_id, created = service_runtime.create(body.task_type, body.content, key)
        return {"session_id": session_id, "created": created}

    @app.get("/v1/tasks/{session_id}/status")
    async def get_status(session_id: str, _auth: None = Depends(authenticate)):
        data = service_runtime.status(session_id)
        return {"session_id": session_id, "status": str(data.get("status") or "unverified"), "progress": data}

    @app.get("/v1/tasks/{session_id}/result")
    async def get_result(session_id: str, _auth: None = Depends(authenticate)):
        return {"session_id": session_id, "result": service_runtime.result(session_id)}

    @app.post("/v1/tasks/{session_id}/cancel")
    async def cancel_task(session_id: str, _auth: None = Depends(authenticate)):
        return service_runtime.cancel(session_id)

    return app


app = create_app()
