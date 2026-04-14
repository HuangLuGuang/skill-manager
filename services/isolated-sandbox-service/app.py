from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class ServiceConfig(BaseModel):
    backend: str = "nsjail"
    api_key: str | None = None
    work_root: str = "/tmp/isolated-sandbox-service"
    default_timeout_seconds: int = 15
    max_code_bytes: int = 200_000
    python_bin: str = sys.executable
    node_bin: str = "node"
    nsjail_bin: str = "nsjail"
    memory_limit_mb: int = 256
    cpu_limit_seconds: int = 10
    max_output_chars: int = 8_000

    @classmethod
    def load(cls) -> "ServiceConfig":
        return cls(
            backend=os.getenv("SANDBOX_SERVICE_BACKEND", "nsjail"),
            api_key=os.getenv("SANDBOX_SERVICE_API_KEY") or None,
            work_root=os.getenv("SANDBOX_SERVICE_WORK_ROOT", "/tmp/isolated-sandbox-service"),
            default_timeout_seconds=int(os.getenv("SANDBOX_SERVICE_DEFAULT_TIMEOUT_SECONDS", "15")),
            max_code_bytes=int(os.getenv("SANDBOX_SERVICE_MAX_CODE_BYTES", "200000")),
            python_bin=os.getenv("SANDBOX_SERVICE_PYTHON_BIN", sys.executable),
            node_bin=os.getenv("SANDBOX_SERVICE_NODE_BIN", "node"),
            nsjail_bin=os.getenv("SANDBOX_SERVICE_NSJAIL_BIN", "nsjail"),
            memory_limit_mb=int(os.getenv("SANDBOX_SERVICE_MEMORY_LIMIT_MB", "256")),
            cpu_limit_seconds=int(os.getenv("SANDBOX_SERVICE_CPU_LIMIT_SECONDS", "10")),
            max_output_chars=int(os.getenv("SANDBOX_SERVICE_MAX_OUTPUT_CHARS", "8000")),
        )


class RunCodeRequest(BaseModel):
    language: str
    code: str
    preload: str = ""
    enable_network: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class RunCodeData(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    message: str | None = None
    backend: str


class RunCodeResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: RunCodeData


class SandboxExecutor(Protocol):
    config: ServiceConfig

    def is_available(self) -> bool:
        ...

    def execute(self, request: RunCodeRequest) -> RunCodeData:
        ...


class Workspace:
    def __init__(self, config: ServiceConfig, request: RunCodeRequest):
        self.config = config
        self.request = request
        self.root_context = tempfile.TemporaryDirectory(prefix="sandbox-work-", dir=config.work_root)
        self.root = Path(self.root_context.name)
        self.source_path = self.root / self._filename_for_language(request.language)

    @staticmethod
    def _filename_for_language(language: str) -> str:
        mapping = {
            "python3": "main.py",
            "nodejs": "main.js",
        }
        if language not in mapping:
            raise ValueError(f"Unsupported language: {language}")
        return mapping[language]

    def prepare(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self.request.code
        if self.request.preload.strip():
            payload = f"{self.request.preload.rstrip()}\n\n{payload}"
        self.source_path.write_text(payload, encoding="utf-8")
        return self.source_path

    def cleanup(self) -> None:
        self.root_context.cleanup()


class SubprocessExecutor:
    def __init__(self, config: ServiceConfig):
        self.config = config

    def is_available(self) -> bool:
        if self.config.backend != "subprocess":
            return False
        if shutil.which(self.config.python_bin) is None and shutil.which(self.config.node_bin) is None:
            return False
        return True

    def execute(self, request: RunCodeRequest) -> RunCodeData:
        workspace = Workspace(self.config, request)
        source_path = workspace.prepare()
        command = self._command_for_request(request.language, source_path)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(workspace.root),
                capture_output=True,
                text=True,
                timeout=self.config.default_timeout_seconds,
                env={},
                check=False,
                start_new_session=True,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            return RunCodeData(
                stdout=(completed.stdout or "")[: self.config.max_output_chars],
                stderr=(completed.stderr or "")[: self.config.max_output_chars],
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                message="executed by subprocess backend",
                backend="subprocess",
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return RunCodeData(
                stdout=(exc.stdout or "")[: self.config.max_output_chars],
                stderr=(exc.stderr or "")[: self.config.max_output_chars],
                exit_code=None,
                duration_ms=duration_ms,
                message="execution timed out",
                backend="subprocess",
            )
        finally:
            workspace.cleanup()

    def _command_for_request(self, language: str, source_path: Path) -> list[str]:
        if language == "python3":
            return [self._resolve_binary(self.config.python_bin), str(source_path)]
        if language == "nodejs":
            return [self._resolve_binary(self.config.node_bin), str(source_path)]
        raise ValueError(f"Unsupported language: {language}")

    @staticmethod
    def _resolve_binary(binary: str) -> str:
        resolved = shutil.which(binary)
        if resolved:
            return resolved
        return binary


class NsjailExecutor:
    """
    Linux-first production executor.

    This backend assumes `nsjail` is installed on the host and that the service
    runs on Linux. It is intentionally conservative and returns stderr from the
    jail process so Skill Manager can surface failures in `sandbox_analysis`.
    """

    def __init__(self, config: ServiceConfig):
        self.config = config

    def is_available(self) -> bool:
        return self.config.backend == "nsjail" and shutil.which(self.config.nsjail_bin) is not None

    def execute(self, request: RunCodeRequest) -> RunCodeData:
        workspace = Workspace(self.config, request)
        source_path = workspace.prepare()
        command = self._command_for_request(request.language, source_path)
        nsjail_command = self._build_nsjail_command(workspace.root, command, request.enable_network)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                nsjail_command,
                capture_output=True,
                text=True,
                timeout=self.config.default_timeout_seconds + 2,
                env={},
                check=False,
                start_new_session=True,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            return RunCodeData(
                stdout=(completed.stdout or "")[: self.config.max_output_chars],
                stderr=(completed.stderr or "")[: self.config.max_output_chars],
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                message="executed by nsjail backend",
                backend="nsjail",
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return RunCodeData(
                stdout=(exc.stdout or "")[: self.config.max_output_chars],
                stderr=(exc.stderr or "")[: self.config.max_output_chars],
                exit_code=None,
                duration_ms=duration_ms,
                message="execution timed out",
                backend="nsjail",
            )
        finally:
            workspace.cleanup()

    def _command_for_request(self, language: str, source_path: Path) -> list[str]:
        if language == "python3":
            return [self._resolve_binary(self.config.python_bin), f"/workspace/{source_path.name}"]
        if language == "nodejs":
            return [self._resolve_binary(self.config.node_bin), f"/workspace/{source_path.name}"]
        raise ValueError(f"Unsupported language: {language}")

    def _build_nsjail_command(self, workspace_root: Path, command: list[str], enable_network: bool) -> list[str]:
        cmd = [
            self._resolve_binary(self.config.nsjail_bin),
            "--mode", "o",
            "--cwd", "/workspace",
            "--time_limit", str(self.config.default_timeout_seconds),
            "--hostname", "sandbox",
            "--user", "65534",
            "--group", "65534",
            "--rlimit_as", str(self.config.memory_limit_mb),
            "--rlimit_cpu", str(self.config.cpu_limit_seconds),
            "--rlimit_nofile", "64",
            "--bindmount_ro", f"{workspace_root}:/workspace",
            "--tmpfsmount", "/tmp",
            "--env", "LANG=C.UTF-8",
        ]
        if not enable_network:
            cmd.extend(["--iface_no_lo"])
        cmd.extend(["--"])
        cmd.extend(command)
        return cmd

    @staticmethod
    def _resolve_binary(binary: str) -> str:
        resolved = shutil.which(binary)
        if resolved:
            return resolved
        return binary


def get_executor(config: ServiceConfig) -> SandboxExecutor:
    if config.backend == "nsjail":
        return NsjailExecutor(config)
    return SubprocessExecutor(config)


def require_api_key(
    authorization: str | None = Header(default=None),
    config: ServiceConfig = Depends(ServiceConfig.load),
):
    if not config.api_key:
        return
    token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if token != config.api_key:
        raise HTTPException(status_code=401, detail="invalid sandbox api key")


app = FastAPI(title="Isolated Sandbox Service", version="0.1.0")


@app.get("/health")
def health(config: ServiceConfig = Depends(ServiceConfig.load)):
    executor = get_executor(config)
    return {
        "status": "ok",
        "service": "isolated-sandbox-service",
        "backend": config.backend,
        "available": executor.is_available(),
    }


@app.post("/run-code", response_model=RunCodeResponse, dependencies=[Depends(require_api_key)])
def run_code(body: RunCodeRequest, config: ServiceConfig = Depends(ServiceConfig.load)):
    body_bytes = len(body.code.encode("utf-8", errors="ignore"))
    if body_bytes > config.max_code_bytes:
        raise HTTPException(status_code=413, detail="code payload too large")

    if body.language not in {"python3", "nodejs"}:
        raise HTTPException(status_code=400, detail=f"unsupported language: {body.language}")

    work_root = Path(config.work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    executor = get_executor(config)
    if not executor.is_available():
        return RunCodeResponse(
            code=1,
            message=f"{config.backend} backend is not available",
            data=RunCodeData(
                stdout="",
                stderr="backend unavailable",
                exit_code=None,
                duration_ms=0,
                message="backend unavailable",
                backend=config.backend,
            ),
        )

    try:
        result = executor.execute(body)
        return RunCodeResponse(
            code=0,
            message=result.message or "success",
            data=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"execution failed: {exc}") from exc
