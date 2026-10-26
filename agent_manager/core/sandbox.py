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
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import yaml
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

SANDBOX_URL_MAX_LENGTH = 2048
SANDBOX_DOCKER_ERRORS = {
    "sandbox.docker_command_unavailable": (
        "当前 Backend 运行环境未检测到 Docker 命令，无法使用“本地 Docker”运行方式，请改用“远程服务”。",
        "The current Backend environment has no Docker command. Local Docker is unavailable. Use Remote Service.",
    ),
    "sandbox.docker_daemon_unavailable": (
        "当前 Backend 无法连接 Docker 服务，请检查 Docker 服务及连接权限，或改用“远程服务”。",
        "The current Backend cannot connect to Docker. Check the Docker service and connection permissions, or use Remote Service.",
    ),
    "sandbox.image_unavailable": (
        "无法访问运行镜像 {image}，请确认镜像已安装且 Backend 可访问，或改用“远程服务”。",
        "Cannot access runtime image {image}. Check that the image is installed and accessible to the Backend, or use Remote Service.",
    ),
}
_http_url = TypeAdapter(HttpUrl)


def sandbox_url_error(value: str | None, runtime: str = "remote") -> str | None:
    """Return a stable validation code, or None for an accepted base URL."""
    # 本地运行不使用远程地址，保留的远程配置不影响保存。
    if runtime == "docker":
        return None
    if not value:
        return "sandbox.url_required"
    if len(value) > SANDBOX_URL_MAX_LENGTH:
        return "sandbox.url_too_long"
    try:
        # 服务会拼接 /run-code，查询参数和片段不能作为服务基础地址。
        if re.search(r"[\s\\?#]", value) or not re.match(r"^https?://", value, re.I):
            return "sandbox.url_invalid"
        _http_url.validate_python(value)
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.port == 0:
            return "sandbox.url_invalid"
    except (ValidationError, ValueError):
        return "sandbox.url_invalid"
    return None


_DEFAULT_SANDBOX_CONFIG_PATH = Path.home() / ".agent-manager" / "sandbox.yaml"

_NETWORK_PATTERNS = (
    re.compile(r"(attempting network access|network failure)", re.I),
    re.compile(r"(name or service not known|temporary failure in name resolution)", re.I),
    re.compile(r"(failed to establish a new connection|connection refused|network is unreachable)", re.I),
    re.compile(r"(handshake operation timed out|https?://[^\s]+.*timed out|timed out.*https?://[^\s]+)", re.I),
)
_PERMISSION_PATTERNS = (
    re.compile(r"permission denied", re.I),
    re.compile(r"read-only file system", re.I),
)
_MISSING_INPUT_PATTERNS = (
    re.compile(r"cannot open\s+[^:\n]+:\s+No such file", re.I),
    re.compile(r"No such file or directory", re.I),
)
_HELP_STYLE_PATTERNS = (
    re.compile(r"argparse\.ArgumentParser"),
    re.compile(r"@click\.(?:command|group)"),
    re.compile(r"\bimport\s+click\b"),
    re.compile(r"\bimport\s+typer\b"),
    re.compile(r"typer\.Typer\("),
)
_MARKDOWN_SHELL_BLOCK_RE = re.compile(
    r"```(?:bash|sh|shell|zsh|console|terminal)\s*\n(.*?)```",
    re.I | re.S,
)
_REMOTE_SANDBOX_EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
_REMOTE_SANDBOX_MAX_FILE_BYTES = 200_000
_REMOTE_SANDBOX_MAX_TOTAL_BYTES = 2_000_000


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
    reason_code: str | None = None
    reason_params: dict[str, str] = Field(default_factory=dict)
    max_severity: str = "SAFE"
    risk_level: str = "LOW"
    summary: str = "Sandbox 未发现明确风险信号。"
    recommendation: str = "可结合规则分析和深度分析结果继续评估。"
    signals: list[SandboxEvent] = Field(default_factory=list)


_SANDBOX_REASON_CODES = {
    "executed by nsjail backend": "executed_nsjail",
    "executed by subprocess backend": "executed_subprocess",
    "execution timed out": "execution_timeout",
    "success": "remote_processed",
    "backend unavailable": "backend_unavailable",
    "probe_strategy=default": "probe_default",
    "probe_strategy=custom": "probe_custom",
    "Sandbox probe timed out": "probe_timeout",
    "Docker is not available on this host": "docker_unavailable",
    "Remote sandbox service URL is not configured": "remote_url_missing",
    "Remote sandbox returned an unsupported response shape": "remote_response_invalid",
    "Executed by remote isolated sandbox service": "executed_remote",
    "No supported executable script found. "
    "SKILL.md command examples are not executed as Sandbox probes.": "no_executable_script",
}
_SANDBOX_REASON_PREFIXES = (
    ("Unsupported sandbox runtime: ", "runtime_unsupported", "runtime"),
    ("Unsupported sandbox entrypoint type: ", "entrypoint_unsupported", "suffix"),
    ("Unsupported remote sandbox entrypoint type: ", "remote_entrypoint_unsupported", "suffix"),
    ("Remote sandbox request failed: ", "remote_request_failed", "detail"),
    ("Remote sandbox rejected execution: ", "remote_rejected", "detail"),
    ("Sandbox analysis skipped: ", "analysis_skipped", "detail"),
)


def _sandbox_http_error_params(detail: str) -> dict[str, str]:
    """Extract HTTPX's fixed template without translating upstream data."""
    match = re.fullmatch(
        r"(?P<kind>Informational response|Redirect response|Client error|Server error|Invalid status code) "
        r"'(?P<status>(?P<code>\d{3}) [^'\n]*)' for url '(?P<url>[^'\n]+)'\n"
        r"(?:Redirect location: '(?P<redirect>[^'\n]*)'\n)?"
        r"For more information check: (?P<info>https://developer\.mozilla\.org/en-US/docs/Web/HTTP/Status/(?P=code))",
        detail,
    )
    if not match:
        return {}
    kinds = {
        "Informational response": "informational", "Redirect response": "redirect",
        "Client error": "client", "Server error": "server", "Invalid status code": "invalid",
    }
    params = {
        "http_error_type": kinds[match["kind"]], "http_status": match["status"],
        "http_url": match["url"], "http_info_url": match["info"],
    }
    if match["redirect"] is not None:
        params["http_redirect_url"] = match["redirect"]
    return params


def sandbox_reason_metadata(reason: str | None) -> dict[str, Any]:
    """Identify platform messages while preserving upstream diagnostic text."""
    # 新报告与历史响应共用已知模板，动态错误只拆出平台前缀。
    if not isinstance(reason, str):
        return {}
    if code := _SANDBOX_REASON_CODES.get(reason):
        return {"reason_code": code, "reason_params": {}}
    unavailable = re.fullmatch(
        r"(Remote sandbox rejected execution: )?(nsjail|subprocess) backend is not available",
        reason,
    )
    if unavailable:
        return {
            "reason_code": "remote_backend_unavailable" if unavailable[1] else "named_backend_unavailable",
            "reason_params": {"backend": unavailable[2]},
        }
    for prefix, code, parameter in _SANDBOX_REASON_PREFIXES:
        if reason.startswith(prefix):
            detail = reason[len(prefix):]
            params = {parameter: detail}
            if code == "remote_request_failed":
                params.update(_sandbox_http_error_params(detail))
            return {"reason_code": code, "reason_params": params}
    return {}


# 新报告与历史响应共用固定文案编码，原始文本及上游证据保持不变。
_SANDBOX_DISPLAY_CODES = {
    "message": {
        "检测到网络访问尝试或网络相关错误输出。": "network_activity",
        "Sandbox 拦截了写入或特权文件访问行为。": "filesystem_access",
        "Sandbox probe 引用了不存在的示例输入文件，当前结果主要反映 probe 参数不完整。": "missing_probe_input",
        "执行超时，脚本可能存在阻塞、死循环或资源消耗异常。": "execution_timeout",
        "Sandbox probe exceeded the configured timeout.": "local_timeout",
        "Remote sandbox probe exceeded the configured timeout or was terminated.": "remote_timeout",
    },
    "summary": {
        "Sandbox 未执行。": "not_executed",
        "Sandbox 未发现明确风险信号。": "no_signals",
        "Sandbox 已执行，未提取到明确运行时风险信号。": "executed_clean",
        "Sandbox probe 未能完整执行：引用的示例输入文件不存在。": "missing_input",
    },
    "recommendation": {
        "先确认 Sandbox 后端可用性，再结合规则分析和深度分析结果继续评估。": "check_backend",
        "可结合规则分析、深度分析和 LLM 分析结果综合判断。": "combine_all",
        "可结合规则分析和深度分析结果继续评估。": "combine_static",
        "这通常不是 Skill 的安全行为，可补充真实测试输入后重新执行 Sandbox，或结合规则分析和深度分析结果继续判断。": "supply_input",
        "建议进入人工审核或直接拒绝，避免直接部署。": "manual_review",
        "建议结合其他扫描结果进一步确认后再决定是否批准。": "confirm_findings",
        "建议排查失败原因或依赖问题，再重新执行 sandbox 验证。": "retry_execution",
    },
}


def _sandbox_display_metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field, codes in _SANDBOX_DISPLAY_CODES.items():
        value = record.get(field)
        if not record.get(f"{field}_code") and isinstance(value, str) and value in codes:
            metadata[f"{field}_code"] = codes[value]
    if not record.get("summary_code") and isinstance(record.get("summary"), str):
        match = re.fullmatch(r"Sandbox 执行中检测到 (\d+) 个风险信号，主要涉及 (.+)。", record["summary"])
        if match:
            metadata.update(summary_code="risk_signals", summary_params={
                "count": int(match[1]), "categories": match[2].split("、"),
            })
    if not record.get("probe_description_code") and isinstance(record.get("probe_description"), str):
        match = re.fullmatch(r"default sandbox probe strategy=(default|cli-help)", record["probe_description"])
        if match:
            metadata.update(probe_description_code="default_probe", probe_description_params={"strategy": match[1]})
    return metadata


def _with_sandbox_record_reason(analysis: dict[str, Any]) -> dict[str, Any]:
    enriched = {**analysis, **_sandbox_display_metadata(analysis)}
    if not analysis.get("reason_code"):
        enriched.update(sandbox_reason_metadata(analysis.get("reason")))
    elif analysis.get("reason_code") == "remote_request_failed":
        # 已编码历史报告同样补齐 HTTP 固定模板参数，原编码和原始详情保留。
        params = analysis.get("reason_params") or {}
        if isinstance(params.get("detail"), str):
            enriched["reason_params"] = {**_sandbox_http_error_params(params["detail"]), **params}
    return enriched


def with_sandbox_reason_metadata(analysis: dict[str, Any]) -> dict[str, Any]:
    """Enrich one report response without modifying its stored values."""
    enriched = _with_sandbox_record_reason(analysis)
    if isinstance(analysis.get("probe_results"), list):
        enriched["probe_results"] = [
            with_sandbox_reason_metadata(probe) if isinstance(probe, dict) else probe
            for probe in analysis["probe_results"]
        ]
    for field in ("signals", "suspicious_events"):
        if isinstance(analysis.get(field), list):
            enriched[field] = [
                {**event, **_sandbox_display_metadata(event)} if isinstance(event, dict) else event
                for event in analysis[field]
            ]
    return enriched


class SandboxConfig(BaseModel):
    enabled: bool = False
    runtime: str = "remote"
    image: str = "agent-manager-sandbox-runtime:latest"
    timeout_seconds: int = 15
    network_mode: str = "none"
    memory_limit: str = "256m"
    cpu_limit: str = "1.0"
    pids_limit: int = 64
    read_only_rootfs: bool = True
    remote_url: str | None = "http://sandbox:8194"
    remote_api_key: str | None = None
    remote_language_map: dict[str, str] = Field(default_factory=lambda: {
        ".py": "python3",
        ".js": "nodejs",
        ".sh": "shell",
    })

    @classmethod
    def config_path(cls) -> Path:
        raw = os.environ.get("AGENT_MANAGER_SANDBOX_CONFIG")
        if raw:
            return Path(raw).expanduser().resolve()
        data_dir = os.environ.get("AGENT_MANAGER_DATA_DIR")
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
        if "AGENT_MANAGER_SANDBOX_ENABLED" in os.environ:
            env_defaults["enabled"] = os.environ["AGENT_MANAGER_SANDBOX_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
        if os.environ.get("AGENT_MANAGER_SANDBOX_RUNTIME"):
            env_defaults["runtime"] = os.environ["AGENT_MANAGER_SANDBOX_RUNTIME"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_IMAGE"):
            env_defaults["image"] = os.environ["AGENT_MANAGER_SANDBOX_IMAGE"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_TIMEOUT_SECONDS"):
            env_defaults["timeout_seconds"] = int(os.environ["AGENT_MANAGER_SANDBOX_TIMEOUT_SECONDS"])
        if os.environ.get("AGENT_MANAGER_SANDBOX_NETWORK_MODE"):
            env_defaults["network_mode"] = os.environ["AGENT_MANAGER_SANDBOX_NETWORK_MODE"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_MEMORY_LIMIT"):
            env_defaults["memory_limit"] = os.environ["AGENT_MANAGER_SANDBOX_MEMORY_LIMIT"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_CPU_LIMIT"):
            env_defaults["cpu_limit"] = os.environ["AGENT_MANAGER_SANDBOX_CPU_LIMIT"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_PIDS_LIMIT"):
            env_defaults["pids_limit"] = int(os.environ["AGENT_MANAGER_SANDBOX_PIDS_LIMIT"])
        if "AGENT_MANAGER_SANDBOX_READ_ONLY" in os.environ:
            env_defaults["read_only_rootfs"] = os.environ["AGENT_MANAGER_SANDBOX_READ_ONLY"].strip().lower() != "false"
        if os.environ.get("AGENT_MANAGER_SANDBOX_URL"):
            env_defaults["remote_url"] = os.environ["AGENT_MANAGER_SANDBOX_URL"].strip()
        if os.environ.get("AGENT_MANAGER_SANDBOX_API_KEY"):
            env_defaults["remote_api_key"] = os.environ["AGENT_MANAGER_SANDBOX_API_KEY"].strip()

        default_language_map = {
            ".py": "python3",
            ".js": "nodejs",
            ".sh": "shell",
        }
        configured_language_map = data.get("remote_language_map") or env_defaults.get("remote_language_map") or {}

        return cls.model_validate({
            **env_defaults,
            **data,
            "remote_language_map": {**default_language_map, **configured_language_map},
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
    description: str = ""


class MarkdownCommandProbe(BaseModel):
    name: str
    description: str
    script: str


class RemoteSandboxFile(BaseModel):
    path: str
    content: str


class RemoteSandboxRequest(BaseModel):
    language: str
    code: str
    preload: str = ""
    enable_network: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
    files: list[RemoteSandboxFile] = Field(default_factory=list)


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


class SandboxConnectionTest(BaseModel):
    available: bool
    runtime: str
    target: str | None = None
    message: str
    error_code: str | None = None
    error_params: dict[str, str] = Field(default_factory=dict)
    duration_ms: int | None = None


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
                rel_parts = candidate.relative_to(root).parts
                if candidate.is_file() and not any(part.startswith(".") for part in rel_parts):
                    return candidate.relative_to(root).as_posix()
    return None


def extract_markdown_command_probes(
    skill_path: str | Path,
    max_cases: int = 4,
    max_chars_per_case: int = 4000,
) -> list[MarkdownCommandProbe]:
    manifest_path = Path(skill_path) / "SKILL.md"
    if not manifest_path.exists():
        return []
    try:
        manifest = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    probes: list[MarkdownCommandProbe] = []
    for index, match in enumerate(_MARKDOWN_SHELL_BLOCK_RE.finditer(manifest), start=1):
        script = _normalize_markdown_shell_block(match.group(1), max_chars_per_case)
        if not script:
            continue
        probes.append(MarkdownCommandProbe(
            name=f"skill-md-command-{len(probes) + 1}",
            description=f"SKILL.md shell command block #{index}",
            script=script,
        ))
        if len(probes) >= max_cases:
            break
    return probes


def write_markdown_command_probe_scripts(
    skill_path: str | Path,
    probes: list[MarkdownCommandProbe],
) -> list[SandboxProbePlan]:
    root = Path(skill_path)
    probe_dir = root / ".agent-manager-sandbox-probes"
    probe_dir.mkdir(parents=True, exist_ok=True)
    plans: list[SandboxProbePlan] = []
    for probe in probes:
        script_path = probe_dir / f"{probe.name}.sh"
        script_path.write_text(
            "\n".join([
                "#!/bin/sh",
                "set +e",
                "export HOME=/tmp",
                'cd "$(dirname "$0")/.."',
                probe.script,
                "",
            ]),
            encoding="utf-8",
        )
        plans.append(SandboxProbePlan(
            entrypoint=script_path.relative_to(root).as_posix(),
            args=[],
            strategy="skill-md-command",
            description=probe.description,
        ))
    return plans


def _normalize_markdown_shell_block(raw: str, max_chars: int) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("$ "):
            line = line[line.find("$ ") + 2 :]
        elif stripped.startswith("> "):
            line = line[line.find("> ") + 2 :]
        lines.append(line.rstrip())
    return "\n".join(lines).strip()[:max_chars]


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


def _collect_remote_sandbox_files(skill_root: Path) -> list[RemoteSandboxFile]:
    files: list[RemoteSandboxFile] = []
    total_bytes = 0
    for path in sorted(skill_root.rglob("*")):
        if not path.is_file():
            continue
        rel_path = path.relative_to(skill_root)
        if any(part in _REMOTE_SANDBOX_EXCLUDED_DIRS for part in rel_path.parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > _REMOTE_SANDBOX_MAX_FILE_BYTES:
            continue
        if total_bytes + size > _REMOTE_SANDBOX_MAX_TOTAL_BYTES:
            break
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        total_bytes += len(content.encode("utf-8", errors="ignore"))
        files.append(RemoteSandboxFile(path=rel_path.as_posix(), content=content))
    return files


def _remote_fallback_code(language: str, target: Path, entrypoint: str, args: list[str]) -> str:
    if language == "python3":
        argv = repr([entrypoint, *args])
        return "\n".join([
            "import os, runpy, sys",
            "os.chdir('/workspace')",
            "sys.path.insert(0, '/workspace')",
            f"sys.argv = {argv}",
            f"runpy.run_path('/workspace/{entrypoint}', run_name='__main__')",
            "",
        ])
    if language == "shell":
        command = " ".join(shlex.quote(part) for part in [entrypoint, *args])
        return f"cd /workspace\nexec sh {command}\n"
    if language == "nodejs":
        argv = repr(["node", entrypoint, *args])
        return "\n".join([
            "process.chdir('/workspace');",
            f"process.argv = {argv};",
            f"require('/workspace/{entrypoint}');",
            "",
        ])
    return target.read_text(encoding="utf-8", errors="ignore")


def _build_events(stdout: Any, stderr: Any) -> list[SandboxEvent]:
    # Ensure we have strings to avoid join errors
    s_out = stdout.decode("utf-8", "ignore") if isinstance(stdout, bytes) else str(stdout or "")
    s_err = stderr.decode("utf-8", "ignore") if isinstance(stderr, bytes) else str(stderr or "")
    combined = "\n".join(part for part in (s_out, s_err) if part).strip()
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
                evidence=f"规则：输出匹配网络访问/网络错误特征；命中片段：{match.group(0)[:200]}",
            ))
            break

    for pattern in _PERMISSION_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="filesystem",
                severity="MEDIUM",
                message="Sandbox 拦截了写入或特权文件访问行为。",
                evidence=f"规则：输出匹配权限拒绝或只读文件系统特征；命中片段：{match.group(0)[:200]}",
            ))
            break

    for pattern in _MISSING_INPUT_PATTERNS:
        match = pattern.search(combined)
        if match:
            events.append(SandboxEvent(
                category="probe_input",
                severity="INFO",
                message="Sandbox probe 引用了不存在的示例输入文件，当前结果主要反映 probe 参数不完整。",
                evidence=f"规则：输出匹配 probe 输入文件缺失特征；命中片段：{match.group(0)[:200]}",
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
    if not result.reason_code:
        metadata = sandbox_reason_metadata(result.reason)
        result.reason_code = metadata.get("reason_code")
        result.reason_params = metadata.get("reason_params", {})
    signals = list(result.suspicious_events)

    if result.timed_out and not any(event.category == "timeout" for event in signals):
        signals.append(SandboxEvent(
            category="timeout",
            severity="MEDIUM",
            message="执行超时，脚本可能存在阻塞、死循环或资源消耗异常。",
            evidence=f"规则：Sandbox 执行超过超时阈值；耗时：duration_ms={result.duration_ms}" if result.duration_ms is not None else "规则：Sandbox 执行超过超时阈值",
        ))

    probe_input_only = bool(signals) and all(event.category == "probe_input" for event in signals)

    max_severity = "SAFE"
    for event in signals:
        severity = (event.severity or "SAFE").upper()
        if _severity_rank(severity) > _severity_rank(max_severity):
            max_severity = severity

    if not result.executed:
        if max_severity == "SAFE":
            max_severity = "LOW"
        summary = result.reason or "Sandbox 未执行。"
        recommendation = "先确认 Sandbox 后端可用性，再结合规则分析和深度分析结果继续评估。"
    elif not signals:
        summary = "Sandbox 已执行，未提取到明确运行时风险信号。"
        recommendation = "可结合规则分析、深度分析和 LLM 分析结果综合判断。"
    elif probe_input_only:
        summary = "Sandbox probe 未能完整执行：引用的示例输入文件不存在。"
        recommendation = "这通常不是 Skill 的安全行为，可补充真实测试输入后重新执行 Sandbox，或结合规则分析和深度分析结果继续判断。"
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

        probe_args = args or []
        files = _collect_remote_sandbox_files(skill_root)
        code = _remote_fallback_code(language, target, entrypoint, probe_args)
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
                "args": probe_args,
                "execute_entrypoint": True,
            },
            files=files,
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
        # 兼容内置服务的 timed out 消息与上游常见 timeout 错误。
        execution_message = ((output.error or "") + " " + (output.message or "")).lower()
        timed_out = "timeout" in execution_message or "timed out" in execution_message
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


def _sandbox_test_target(config: SandboxConfig) -> str | None:
    if config.runtime == "remote":
        return config.remote_url.rstrip("/") + "/run-code" if config.remote_url else None
    if config.runtime == "docker":
        return config.image
    return None


def sandbox_docker_error(config: SandboxConfig, timeout_seconds: int = 3) -> str | None:
    """Check the Backend's Docker service and selected image within one budget."""
    if shutil.which("docker") is None:
        return "sandbox.docker_command_unavailable"
    # 保存和连接测试共用检查；先确认服务可达，避免将连接故障误报为镜像缺失。
    deadline = time.monotonic() + max(1, min(timeout_seconds, 10))
    checks = (
        (["docker", "info", "--format", "{{.ServerVersion}}"], "sandbox.docker_daemon_unavailable"),
        (["docker", "image", "inspect", config.image], "sandbox.image_unavailable"),
    )
    for command, code in checks:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return code
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=remaining, check=False,
            )
        except FileNotFoundError:
            return "sandbox.docker_command_unavailable"
        except (OSError, subprocess.SubprocessError):
            return code
        if completed.returncode != 0:
            return code
    return None


def test_sandbox_connection(
    config: SandboxConfig | None = None,
    timeout_seconds: int = 3,
) -> SandboxConnectionTest:
    resolved = config or SandboxConfig.load()
    started = time.monotonic()

    def finish(
        available: bool, message: str, target: str | None = None,
        *, error_code: str | None = None, error_params: dict[str, str] | None = None,
    ) -> SandboxConnectionTest:
        return SandboxConnectionTest(
            available=available,
            runtime=resolved.runtime,
            target=target if target is not None else _sandbox_test_target(resolved),
            message=message,
            error_code=error_code,
            error_params=error_params or {},
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if not resolved.enabled:
        return finish(False, "Sandbox 未启用")

    if resolved.runtime == "docker":
        code = sandbox_docker_error(resolved, timeout_seconds)
        if code:
            # 保留原消息兼容旧客户端，错误编码供界面按语言展示。
            return finish(
                False, SANDBOX_DOCKER_ERRORS[code][0].format(image=resolved.image),
                error_code=code,
                error_params={"image": resolved.image} if code == "sandbox.image_unavailable" else {},
            )
        return finish(True, "Docker Sandbox 镜像可用")

    if resolved.runtime != "remote":
        return finish(False, f"不支持的 Sandbox 后端：{resolved.runtime}")

    target = _sandbox_test_target(resolved)
    if not target:
        return finish(False, "远程 Sandbox URL 未配置")

    payload = RemoteSandboxRequest(
        language="shell",
        code="echo sandbox-ok",
        preload="",
        enable_network=False,
        metadata={"probe": "connection-test"},
    )
    headers = {}
    if resolved.remote_api_key:
        headers["Authorization"] = f"Bearer {resolved.remote_api_key}"

    try:
        response = httpx.post(
            target,
            json=payload.model_dump(mode="json"),
            headers=headers,
            timeout=max(1, min(timeout_seconds, 10)),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return finish(False, f"远程 Sandbox 返回 HTTP {exc.response.status_code}", target)
    except Exception as exc:
        return finish(False, f"远程 Sandbox 连接失败：{exc}", target)

    return finish(True, "远程 Sandbox 连接可用", target)


# Backward-compatible alias for existing imports/tests.
SandboxRunner = DockerSandboxRunner
