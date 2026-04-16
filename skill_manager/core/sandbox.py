"""
Sandbox execution helpers for dynamic skill probing.

Supports multiple backends:
- docker: local container probe for development and single-host deployments
- remote: isolated execution service inspired by systems like dify-sandbox
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Protocol

import httpx
import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_SANDBOX_CONFIG_PATH = Path.home() / ".skill-manager" / "sandbox.yaml"

_NETWORK_PATTERNS = (
    re.compile(r"(name or service not known|temporary failure in name resolution)", re.I),
    re.compile(r"(failed to establish a new connection|connection refused|network is unreachable)", re.I),
    re.compile(r"(https?://[^\s]+)", re.I),
)
_DEPENDENCY_PATTERNS = (
    re.compile(r"No module named ['\"]?([A-Za-z0-9_.-]+)['\"]?", re.I),
    re.compile(r"ModuleNotFoundError", re.I),
)
_PERMISSION_PATTERNS = (
    re.compile(r"permission denied", re.I),
    re.compile(r"read-only file system", re.I),
)
_EXECUTION_PATTERNS = (
    re.compile(r"\b(subprocess|os\.system|os\.popen|eval|exec)\b", re.I),
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"\b(api[_-]?key|secret|token|password|authorization)\b", re.I),
)
_HELP_STYLE_PATTERNS = (
    re.compile(r"argparse\.ArgumentParser"),
    re.compile(r"@click\.(?:command|group)"),
    re.compile(r"\bimport\s+click\b"),
    re.compile(r"\bimport\s+typer\b"),
    re.compile(r"typer\.Typer\("),
)


class SandboxEvent(BaseModel):
    category: str
    severity: str
    message: str
    evidence: str | None = None


class SandboxResult(BaseModel):
    executed: bool
    runtime: str
    available: bool = True
    entrypoint: str | None = None
    image: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int | None = None
    stdout: str = ""
    stderr: str = ""
    suspicious_events: list[SandboxEvent] = Field(default_factory=list)
    network_attempts: int = 0
    processes_spawned: int = 0
    reason: str | None = None
    max_severity: str = "SAFE"
    risk_level: str = "LOW"
    summary: str = "Sandbox 未发现明确风险信号。"
    recommendation: str = "可结合静态扫描结果继续评估。"
    signals: list[SandboxEvent] = Field(default_factory=list)


class SandboxConfig(BaseModel):
    enabled: bool = False
    runtime: str = "docker"
    image: str = "skill-manager-sandbox-runtime:latest"
    timeout_seconds: int = 15
    network_mode: str = "none"
    memory_limit: str = "256m"
    cpu_limit: str = "1.0"
    pids_limit: int = 64
    read_only_rootfs: bool = True
    remote_url: str | None = None
    remote_api_key: str | None = None
    remote_language_map: dict[str, str] = Field(default_factory=lambda: {
        ".py": "python3",
        ".js": "nodejs",
    })

    @classmethod
    def config_path(cls) -> Path:
        raw = os.environ.get("SKILL_MANAGER_SANDBOX_CONFIG")
        if raw:
            return Path(raw).expanduser().resolve()
        data_dir = os.environ.get("SKILL_MANAGER_DATA_DIR")
        if data_dir:
            return Path(data_dir).expanduser().resolve() / "config" / "sandbox.yaml"
        return _DEFAULT_SANDBOX_CONFIG_PATH

    @classmethod
    def load(cls) -> "SandboxConfig":
        target = cls.config_path()
        data: dict[str, object] = {}
        if target.exists():
            with open(target, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

        env_defaults: dict[str, object] = {}
        if "SKILL_MANAGER_SANDBOX_ENABLED" in os.environ:
            env_defaults["enabled"] = os.environ["SKILL_MANAGER_SANDBOX_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
        if os.environ.get("SKILL_MANAGER_SANDBOX_RUNTIME"):
            env_defaults["runtime"] = os.environ["SKILL_MANAGER_SANDBOX_RUNTIME"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_IMAGE"):
            env_defaults["image"] = os.environ["SKILL_MANAGER_SANDBOX_IMAGE"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_TIMEOUT_SECONDS"):
            env_defaults["timeout_seconds"] = int(os.environ["SKILL_MANAGER_SANDBOX_TIMEOUT_SECONDS"])
        if os.environ.get("SKILL_MANAGER_SANDBOX_NETWORK_MODE"):
            env_defaults["network_mode"] = os.environ["SKILL_MANAGER_SANDBOX_NETWORK_MODE"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_MEMORY_LIMIT"):
            env_defaults["memory_limit"] = os.environ["SKILL_MANAGER_SANDBOX_MEMORY_LIMIT"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_CPU_LIMIT"):
            env_defaults["cpu_limit"] = os.environ["SKILL_MANAGER_SANDBOX_CPU_LIMIT"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_PIDS_LIMIT"):
            env_defaults["pids_limit"] = int(os.environ["SKILL_MANAGER_SANDBOX_PIDS_LIMIT"])
        if "SKILL_MANAGER_SANDBOX_READ_ONLY" in os.environ:
            env_defaults["read_only_rootfs"] = os.environ["SKILL_MANAGER_SANDBOX_READ_ONLY"].strip().lower() != "false"
        if os.environ.get("SKILL_MANAGER_SANDBOX_URL"):
            env_defaults["remote_url"] = os.environ["SKILL_MANAGER_SANDBOX_URL"].strip()
        if os.environ.get("SKILL_MANAGER_SANDBOX_API_KEY"):
            env_defaults["remote_api_key"] = os.environ["SKILL_MANAGER_SANDBOX_API_KEY"].strip()

        return cls.model_validate({
            **env_defaults,
            **data,
            "remote_language_map": data.get("remote_language_map") or env_defaults.get("remote_language_map") or {
                ".py": "python3",
                ".js": "nodejs",
            },
        })

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path or self.config_path()).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            yaml.safe_dump(self.model_dump(mode="json"), handle, sort_keys=False, allow_unicode=False)
        return target

    @property
    def api_key_masked(self) -> str | None:
        if not self.remote_api_key:
            return None
        if len(self.remote_api_key) <= 8:
            return "*" * len(self.remote_api_key)
        return f"{self.remote_api_key[:4]}{'*' * (len(self.remote_api_key) - 8)}{self.remote_api_key[-4:]}"

    def public_dict(self) -> dict[str, object]:
        data = self.model_dump(mode="json")
        data.pop("remote_api_key", None)
        data["remote_api_key_configured"] = bool(self.remote_api_key)
        data["remote_api_key_masked"] = self.api_key_masked
        data["config_path"] = str(self.config_path())
        return data


class SandboxProbePlan(BaseModel):
    entrypoint: str
    args: list[str] = Field(default_factory=list)
    strategy: str = "default"


class RemoteSandboxRequest(BaseModel):
    language: str
    code: str
    preload: str = ""
    enable_network: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


class RemoteSandboxExecutionData(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    code: int | None = None
    error: str | None = None
    message: str | None = None
    duration_ms: int | None = None


class RemoteSandboxEnvelope(BaseModel):
    code: int = 0
    message: str = "success"
    data: RemoteSandboxExecutionData | None = None


class SandboxBackend(Protocol):
    config: SandboxConfig

    def is_available(self) -> bool:
        ...

    def run_probe(
        self,
        skill_path: str | Path,
        entrypoint: str,
        args: list[str] | None = None,
        timeout_seconds: int | None = None,
        network_mode: str | None = None,
    ) -> SandboxResult:
        ...


def discover_probe_entrypoint(skill_path: str | Path) -> str | None:
    root = Path(skill_path)
    preferred_roots = [root / "scripts", root]
    patterns = ("*.py", "*.sh", "*.js")
    for base in preferred_roots:
        if not base.exists():
            continue
        for pattern in patterns:
            for candidate in sorted(base.rglob(pattern)):
                if candidate.is_file():
                    return candidate.relative_to(root).as_posix()
    return None


def build_probe_plan(skill_path: str | Path, entrypoint: str) -> SandboxProbePlan:
    skill_root = Path(skill_path)
    target = (skill_root / entrypoint).resolve()
    if not target.exists() or not target.is_file():
        raise ValueError(f"Sandbox entrypoint not found: {entrypoint}")

    args: list[str] = []
    strategy = "default"
    if target.suffix in {".py", ".sh", ".js"}:
        try:
            content = target.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        if any(pattern.search(content) for pattern in _HELP_STYLE_PATTERNS):
            args = ["--help"]
            strategy = "cli-help"

    return SandboxProbePlan(entrypoint=entrypoint, args=args, strategy=strategy)


def _build_events(stdout: str, stderr: str) -> list[SandboxEvent]:
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    if not combined:
        return []

    events: list[SandboxEvent] = []
    for pattern in _NETWORK_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="network",
                severity="HIGH",
                message="检测到网络访问尝试或网络相关错误输出。",
                evidence=match.group(0)[:200],
            ))
            break

    for pattern in _DEPENDENCY_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="dependency",
                severity="LOW",
                message="Sandbox 执行环境缺少脚本依赖，当前结果可能只反映运行环境问题。",
                evidence=match.group(0)[:200],
            ))
            break

    for pattern in _PERMISSION_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="filesystem",
                severity="MEDIUM",
                message="Sandbox 拦截了写入或特权文件访问行为。",
                evidence=match.group(0)[:200],
            ))
            break

    for pattern in _EXECUTION_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="execution",
                severity="HIGH",
                message="输出中出现动态代码执行或 shell 执行迹象。",
                evidence=match.group(0)[:200],
            ))
            break

    for pattern in _CREDENTIAL_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="credentials",
                severity="HIGH",
                message="输出中出现凭证相关字段，需检查是否存在敏感信息访问或外泄风险。",
                evidence=match.group(0)[:200],
            ))
            break

    return events


def _severity_rank(severity: str) -> int:
    return {
        "SAFE": 0,
        "INFO": 1,
        "LOW": 2,
        "MEDIUM": 3,
        "HIGH": 4,
        "CRITICAL": 5,
        "EXTREME": 6,
    }.get((severity or "SAFE").upper(), 0)


def _risk_from_severity(severity: str) -> str:
    value = (severity or "SAFE").upper()
    if value in {"CRITICAL", "EXTREME"}:
        return "EXTREME"
    if value == "HIGH":
        return "HIGH"
    if value == "MEDIUM":
        return "MEDIUM"
    return "LOW"


def _finalize_result(result: SandboxResult) -> SandboxResult:
    signals = list(result.suspicious_events)

    if result.timed_out and not any(event.category == "timeout" for event in signals):
        signals.append(SandboxEvent(
            category="timeout",
            severity="MEDIUM",
            message="执行超时，脚本可能存在阻塞、死循环或资源消耗异常。",
            evidence=f"duration_ms={result.duration_ms}" if result.duration_ms is not None else None,
        ))

    if result.executed and result.exit_code not in {None, 0}:
        signals.append(SandboxEvent(
            category="runtime",
            severity="LOW",
            message="脚本以非零退出码结束，建议结合 stderr 排查失败原因。",
            evidence=f"exit_code={result.exit_code}",
        ))

    max_severity = "SAFE"
    for event in signals:
        severity = (event.severity or "SAFE").upper()
        if _severity_rank(severity) > _severity_rank(max_severity):
            max_severity = severity

    if not result.executed:
        if max_severity == "SAFE":
            max_severity = "LOW"
        summary = result.reason or "Sandbox 未执行。"
        recommendation = "先确认 sandbox 后端可用性，再结合静态扫描结果继续评估。"
    elif not signals:
        summary = "Sandbox 已执行，未从输出中提取到明确风险信号。"
        recommendation = "可结合静态扫描、LLM 和规则分析结果综合判断。"
    else:
        categories: list[str] = []
        for event in signals:
            if event.category not in categories:
                categories.append(event.category)
        summary = f"Sandbox 执行中检测到 {len(signals)} 个风险信号，主要涉及 {'、'.join(categories[:3])}。"
        risk_level = _risk_from_severity(max_severity)
        if risk_level in {"HIGH", "EXTREME"}:
            recommendation = "建议进入人工审核或直接拒绝，避免直接部署。"
        elif risk_level == "MEDIUM":
            recommendation = "建议结合其他扫描结果进一步确认后再决定是否批准。"
        else:
            recommendation = "建议排查失败原因或依赖问题，再重新执行 sandbox 验证。"

    result.signals = signals
    result.max_severity = max_severity
    result.risk_level = _risk_from_severity(max_severity)
    result.summary = summary
    result.recommendation = recommendation
    return result


class DockerSandboxRunner:
    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig.load()

    def is_available(self) -> bool:
        return self.config.runtime == "docker" and shutil.which("docker") is not None

    def run_probe(
        self,
        skill_path: str | Path,
        entrypoint: str,
        args: list[str] | None = None,
        timeout_seconds: int | None = None,
        network_mode: str | None = None,
    ) -> SandboxResult:
        skill_root = Path(skill_path).resolve()
        if not skill_root.is_dir():
            raise ValueError(f"Skill path is not a directory: {skill_root}")

        if self.config.runtime != "docker":
            return _finalize_result(SandboxResult(
                executed=False,
                runtime=self.config.runtime,
                available=False,
                entrypoint=entrypoint,
                reason=f"Unsupported sandbox runtime: {self.config.runtime}",
            ))

        if not self.is_available():
            return _finalize_result(SandboxResult(
                executed=False,
                runtime=self.config.runtime,
                available=False,
                entrypoint=entrypoint,
                reason="Docker is not available on this host",
            ))

        relative_entrypoint = entrypoint
        target = (skill_root / relative_entrypoint).resolve()
        if skill_root not in target.parents and target != skill_root:
            raise ValueError("Sandbox entrypoint must stay within the skill directory")
        if not target.exists() or not target.is_file():
            raise ValueError(f"Sandbox entrypoint not found: {relative_entrypoint}")

        timeout_value = timeout_seconds or self.config.timeout_seconds
        network = network_mode or self.config.network_mode
        image = self.config.image

        probe_args = args or []
        if target.suffix == ".py":
            inner_cmd = ["python", f"/workspace/skill/{relative_entrypoint}", *probe_args]
        elif target.suffix == ".sh":
            inner_cmd = ["sh", f"/workspace/skill/{relative_entrypoint}", *probe_args]
        elif target.suffix == ".js":
            inner_cmd = ["node", f"/workspace/skill/{relative_entrypoint}", *probe_args]
        else:
            return _finalize_result(SandboxResult(
                executed=False,
                runtime=self.config.runtime,
                available=True,
                entrypoint=relative_entrypoint,
                image=image,
                reason=f"Unsupported sandbox entrypoint type: {target.suffix}",
            ))

        with tempfile.TemporaryDirectory(prefix="skill-sandbox-tmp-") as tmp_dir:
            docker_cmd = [
                "docker", "run", "--rm",
                "--network", network,
                "--memory", self.config.memory_limit,
                "--cpus", self.config.cpu_limit,
                "--pids-limit", str(self.config.pids_limit),
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--user", "65534:65534",
                "-v", f"{skill_root}:/workspace/skill:ro",
                "-v", f"{tmp_dir}:/tmp",
                "-w", "/workspace/skill",
            ]
            if self.config.read_only_rootfs:
                docker_cmd.append("--read-only")
            docker_cmd.extend([image, *inner_cmd])

            started = time.monotonic()
            try:
                completed = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_value,
                    check=False,
                )
                duration_ms = int((time.monotonic() - started) * 1000)
                stdout = completed.stdout.strip()
                stderr = completed.stderr.strip()
                events = _build_events(stdout, stderr)
                network_attempts = sum(1 for event in events if event.category == "network")
                return _finalize_result(SandboxResult(
                    executed=True,
                    runtime="docker",
                    available=True,
                    entrypoint=relative_entrypoint,
                    image=image,
                    exit_code=completed.returncode,
                    timed_out=False,
                    duration_ms=duration_ms,
                    stdout=stdout[:8000],
                    stderr=stderr[:8000],
                    suspicious_events=events,
                    network_attempts=network_attempts,
                    processes_spawned=1,
                    reason=f"probe_strategy={'default' if not probe_args else 'custom'}",
                ))
            except subprocess.TimeoutExpired as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                stdout = (exc.stdout or "").strip()
                stderr = (exc.stderr or "").strip()
                events = _build_events(stdout, stderr)
                events.append(SandboxEvent(
                    category="timeout",
                    severity="MEDIUM",
                    message="Sandbox probe exceeded the configured timeout.",
                    evidence=f"timeout={timeout_value}s",
                ))
                return _finalize_result(SandboxResult(
                    executed=True,
                    runtime="docker",
                    available=True,
                    entrypoint=relative_entrypoint,
                    image=image,
                    exit_code=None,
                    timed_out=True,
                    duration_ms=duration_ms,
                    stdout=stdout[:8000],
                    stderr=stderr[:8000],
                    suspicious_events=events,
                    network_attempts=sum(1 for event in events if event.category == "network"),
                    processes_spawned=1,
                    reason="Sandbox probe timed out",
                ))


class RemoteSandboxRunner:
    """
    Runner for a standalone isolated execution service.

    This backend is intentionally generic so the project can adopt services
    inspired by dify-sandbox without binding to a vendor-specific name.
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig.load()

    def is_available(self) -> bool:
        return self.config.runtime == "remote" and bool(self.config.remote_url)

    def run_probe(
        self,
        skill_path: str | Path,
        entrypoint: str,
        args: list[str] | None = None,
        timeout_seconds: int | None = None,
        network_mode: str | None = None,
    ) -> SandboxResult:
        skill_root = Path(skill_path).resolve()
        target = (skill_root / entrypoint).resolve()
        if not target.exists() or not target.is_file():
            raise ValueError(f"Sandbox entrypoint not found: {entrypoint}")

        if not self.is_available():
            return _finalize_result(SandboxResult(
                executed=False,
                runtime="remote",
                available=False,
                entrypoint=entrypoint,
                reason="Remote sandbox service URL is not configured",
            ))

        language = self.config.remote_language_map.get(target.suffix.lower())
        if not language:
            return _finalize_result(SandboxResult(
                executed=False,
                runtime="remote",
                available=True,
                entrypoint=entrypoint,
                reason=f"Unsupported remote sandbox entrypoint type: {target.suffix}",
            ))

        code = target.read_text(encoding="utf-8", errors="ignore")
        timeout_value = timeout_seconds or self.config.timeout_seconds
        network = network_mode or self.config.network_mode
        enable_network = network.lower() not in {"none", "off", "disabled", "false"}
        payload = RemoteSandboxRequest(
            language=language,
            code=code,
            preload="",
            enable_network=enable_network,
            metadata={
                "entrypoint": entrypoint,
                "args": args or [],
            },
        )
        headers = {}
        if self.config.remote_api_key:
            headers["Authorization"] = f"Bearer {self.config.remote_api_key}"

        started = time.monotonic()
        try:
            response = httpx.post(
                self.config.remote_url.rstrip("/") + "/run-code",
                json=payload.model_dump(mode="json"),
                headers=headers,
                timeout=timeout_value,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            response.raise_for_status()
            raw = response.json()
        except Exception as exc:
            return _finalize_result(SandboxResult(
                executed=False,
                runtime="remote",
                available=True,
                entrypoint=entrypoint,
                duration_ms=int((time.monotonic() - started) * 1000),
                reason=f"Remote sandbox request failed: {exc}",
            ))

        if isinstance(raw, dict) and "data" in raw and {"code", "message"}.issubset(raw.keys()):
            envelope = RemoteSandboxEnvelope.model_validate(raw)
            if envelope.code != 0:
                return _finalize_result(SandboxResult(
                    executed=False,
                    runtime="remote",
                    available=True,
                    entrypoint=entrypoint,
                    image=self.config.remote_url,
                    duration_ms=duration_ms,
                    reason=f"Remote sandbox rejected execution: {envelope.message}",
                ))
            output = envelope.data or RemoteSandboxExecutionData()
        elif isinstance(raw, dict):
            output = RemoteSandboxExecutionData.model_validate(raw)
        else:
            return _finalize_result(SandboxResult(
                executed=False,
                runtime="remote",
                available=True,
                entrypoint=entrypoint,
                image=self.config.remote_url,
                duration_ms=duration_ms,
                reason="Remote sandbox returned an unsupported response shape",
            ))

        stdout = str(output.stdout or "")
        stderr = str(output.stderr or "")
        events = _build_events(stdout, stderr)
        exit_code = output.exit_code
        if exit_code is None and isinstance(output.code, int):
            exit_code = output.code
        timed_out = "timeout" in ((output.error or "") + " " + (output.message or "")).lower()
        if timed_out:
            events.append(SandboxEvent(
                category="timeout",
                severity="MEDIUM",
                message="Remote sandbox probe exceeded the configured timeout or was terminated.",
                evidence=output.error or output.message,
            ))
        return _finalize_result(SandboxResult(
            executed=True,
            runtime="remote",
            available=True,
            entrypoint=entrypoint,
            image=self.config.remote_url,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=output.duration_ms if output.duration_ms is not None else duration_ms,
            stdout=stdout[:8000],
            stderr=stderr[:8000],
            suspicious_events=events,
            network_attempts=sum(1 for event in events if event.category == "network"),
            processes_spawned=1,
            reason=output.message or output.error or "Executed by remote isolated sandbox service",
        ))


def get_sandbox_runner(config: SandboxConfig | None = None) -> SandboxBackend:
    resolved = config or SandboxConfig.load()
    if resolved.runtime == "remote":
        return RemoteSandboxRunner(resolved)
    return DockerSandboxRunner(resolved)


# Backward-compatible alias for existing imports/tests.
SandboxRunner = DockerSandboxRunner
