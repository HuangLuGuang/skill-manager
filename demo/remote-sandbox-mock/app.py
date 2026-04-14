from __future__ import annotations

import time

from fastapi import FastAPI
from pydantic import BaseModel, Field


class RunCodeRequest(BaseModel):
    language: str
    code: str
    preload: str = ""
    enable_network: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class RunCodeData(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0


class RunCodeResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: RunCodeData


app = FastAPI(title="Remote Sandbox Mock", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "service": "remote-sandbox-mock"}


@app.post("/run-code", response_model=RunCodeResponse)
def run_code(body: RunCodeRequest):
    started = time.monotonic()
    args = body.metadata.get("args") if isinstance(body.metadata, dict) else []
    if not isinstance(args, list):
        args = []

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    exit_code = 0

    if "--help" in args:
        stdout_lines.append("usage: mock-script [--help]")
        stdout_lines.append("mock sandbox help output")
    else:
        stdout_lines.append(f"mock sandbox executed language={body.language}")

    code_text = body.code or ""
    if "requests.post" in code_text or "http://" in code_text or "https://" in code_text:
        stderr_lines.append("network access attempt detected by mock sandbox")
    if "eval(" in code_text or "exec(" in code_text:
        stderr_lines.append("dynamic execution pattern detected by mock sandbox")
    if body.enable_network:
        stdout_lines.append("network mode enabled for this probe")
    else:
        stdout_lines.append("network mode disabled for this probe")

    duration_ms = int((time.monotonic() - started) * 1000)
    return RunCodeResponse(
        data=RunCodeData(
            stdout="\n".join(stdout_lines).strip(),
            stderr="\n".join(stderr_lines).strip(),
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
    )
