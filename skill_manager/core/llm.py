"""
LLM-assisted vetting support.

Provides a small, file-backed configuration layer and a DeepSeek-compatible
chat-completions client used by the vetting pipeline when `use_llm=True`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_LLM_CONFIG_PATH = Path.home() / ".skill-manager" / "llm.yaml"
_TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
    ".yaml", ".yml", ".sh", ".toml", ".cfg", ".ini",
}


class LLMFinding(BaseModel):
    severity: str
    title: str
    message: str
    file: str | None = None


class LLMAnalysisResult(BaseModel):
    provider: str
    model: str
    max_severity: str = "SAFE"
    risk_level: str = "LOW"
    skill_function_summary: str = ""
    summary: str = ""
    findings: list[LLMFinding] = Field(default_factory=list)
    policy_notes: list[str] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class LLMSandboxProbeCase(BaseModel):
    name: str
    description: str = ""
    args: list[str] = Field(default_factory=list)


class LLMSandboxProbePlan(BaseModel):
    provider: str
    model: str
    probes: list[LLMSandboxProbeCase] = Field(default_factory=list)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    enabled: bool = False
    provider: str = "deepseek"
    api_base: str = "https://api.deepseek.com"
    api_key: str | None = None
    model: str = "deepseek-chat"
    timeout_seconds: float = 30.0
    max_files: int = 6
    max_file_chars: int = 3000
    max_manifest_chars: int = 12000

    @classmethod
    def config_path(cls) -> Path:
        raw = os.environ.get("SKILL_MANAGER_LLM_CONFIG")
        if raw:
            return Path(raw).expanduser().resolve()
        data_dir = os.environ.get("SKILL_MANAGER_DATA_DIR")
        if data_dir:
            return Path(data_dir).expanduser().resolve() / "config" / "llm.yaml"
        return _DEFAULT_LLM_CONFIG_PATH

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LLMConfig":
        target = Path(path or cls.config_path()).expanduser()
        data: dict[str, Any] = {}
        if target.exists():
            with open(target, encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

        env_defaults: dict[str, Any] = {}
        if "SKILL_MANAGER_LLM_ENABLED" in os.environ:
            env_defaults["enabled"] = os.environ["SKILL_MANAGER_LLM_ENABLED"].strip().lower() in {
                "1", "true", "yes", "on",
            }
        if os.environ.get("SKILL_MANAGER_LLM_PROVIDER"):
            env_defaults["provider"] = os.environ["SKILL_MANAGER_LLM_PROVIDER"].strip()
        if os.environ.get("SKILL_MANAGER_LLM_API_BASE"):
            env_defaults["api_base"] = os.environ["SKILL_MANAGER_LLM_API_BASE"].strip()
        if os.environ.get("SKILL_MANAGER_LLM_API_KEY"):
            env_defaults["api_key"] = os.environ["SKILL_MANAGER_LLM_API_KEY"].strip()
        if os.environ.get("SKILL_MANAGER_LLM_MODEL"):
            env_defaults["model"] = os.environ["SKILL_MANAGER_LLM_MODEL"].strip()
        if os.environ.get("SKILL_MANAGER_LLM_TIMEOUT_SECONDS"):
            env_defaults["timeout_seconds"] = float(os.environ["SKILL_MANAGER_LLM_TIMEOUT_SECONDS"])

        return cls.model_validate({**env_defaults, **data})

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path or self.config_path()).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            yaml.safe_dump(self.model_dump(mode="json"), handle, sort_keys=False, allow_unicode=False)
        return target

    @property
    def is_ready(self) -> bool:
        return bool(self.enabled and self.api_key and self.api_base and self.model)

    @property
    def api_key_masked(self) -> str | None:
        if not self.api_key:
            return None
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}{'*' * (len(self.api_key) - 8)}{self.api_key[-4:]}"

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data.pop("api_key", None)
        data["api_key_configured"] = bool(self.api_key)
        data["api_key_masked"] = self.api_key_masked
        data["config_path"] = str(self.config_path())
        return data


def _iter_text_files(skill_path: Path, max_files: int) -> list[Path]:
    files: list[Path] = []
    for path in sorted(skill_path.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "SKILL.md":
            continue
        if any(part.startswith(".") for part in path.relative_to(skill_path).parts):
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue
        files.append(path)
        if len(files) >= max_files:
            break
    return files


def _build_skill_snapshot(skill_path: Path, config: LLMConfig) -> str:
    manifest_path = skill_path / "SKILL.md"
    manifest = manifest_path.read_text(encoding="utf-8")[: config.max_manifest_chars]
    all_files = [
        str(path.relative_to(skill_path))
        for path in sorted(skill_path.rglob("*"))
        if path.is_file()
    ]

    sections = [
        "# Skill Manifest",
        manifest,
        "",
        "# File Inventory",
        "\n".join(all_files[:200]),
        "",
        "# Sample File Contents",
    ]

    for file_path in _iter_text_files(skill_path, config.max_files):
        try:
            content = file_path.read_text(encoding="utf-8")[: config.max_file_chars]
        except Exception:
            continue
        sections.extend([
            f"## {file_path.relative_to(skill_path)}",
            content,
            "",
        ])

    return "\n".join(sections)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    candidate = raw_text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(candidate[start : end + 1])


def analyze_skill_with_llm(skill_path: Path, config: LLMConfig | None = None) -> LLMAnalysisResult:
    resolved_config = config or LLMConfig.load()
    if not resolved_config.enabled:
        raise ValueError("LLM analysis is disabled")
    if not resolved_config.api_key:
        raise ValueError("LLM API key is not configured")
    if resolved_config.provider.lower() != "deepseek":
        raise ValueError(f"Unsupported LLM provider: {resolved_config.provider}")

    snapshot = _build_skill_snapshot(skill_path, resolved_config)
    system_prompt = (
        "You are a security reviewer for AI agent skills. "
        "Review the provided skill manifest and file excerpts for risky behavior, "
        "over-broad permissions, sensitive data handling, remote execution, credential access, "
        "shell injection risk, and suspicious obfuscation. "
        "All natural-language output values must be written in Simplified Chinese. "
        "This includes summary, findings.title, findings.message, and policy_notes. "
        "Respond with exactly one JSON object and no markdown. "
        "Schema: "
        "{"
        "\"skill_function_summary\": string, "
        "\"summary\": string, "
        "\"risk_level\": \"LOW\"|\"MEDIUM\"|\"HIGH\"|\"EXTREME\", "
        "\"max_severity\": \"SAFE\"|\"LOW\"|\"MEDIUM\"|\"HIGH\"|\"CRITICAL\", "
        "\"policy_notes\": string[], "
        "\"findings\": ["
        "{\"severity\": \"LOW\"|\"MEDIUM\"|\"HIGH\"|\"CRITICAL\", "
        "\"title\": string, "
        "\"message\": string, "
        "\"file\": string|null}"
        "]"
        "}"
    )
    user_prompt = (
        "请分析这个 skill 快照，重点给出基于证据的具体风险点。"
        "同时请先用一小段简体中文概括这个 skill 的主要功能，不要太长。"
        "所有说明文字必须使用简体中文。"
        "如果没有明显问题，请返回空 findings，"
        "\"risk_level\": \"LOW\"，\"max_severity\": \"SAFE\"，并给出简短功能概述。\n\n"
        f"{snapshot}"
    )

    base = resolved_config.api_base.rstrip("/")
    endpoint = f"{base}/chat/completions"
    payload = {
        "model": resolved_config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "stream": False,
    }

    with httpx.Client(timeout=resolved_config.timeout_seconds) as client:
        response = client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {resolved_config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Unexpected LLM response shape") from exc

    parsed = _extract_json_object(content)
    result = LLMAnalysisResult.model_validate({
        "provider": resolved_config.provider,
        "model": resolved_config.model,
        "raw_response": body,
        **parsed,
    })
    logger.info(
        "Completed LLM vetting for %s via %s/%s with %s findings",
        skill_path,
        result.provider,
        result.model,
        len(result.findings),
    )
    return result


def generate_sandbox_probes_with_llm(
    skill_path: Path,
    entrypoint: str,
    config: LLMConfig | None = None,
    max_cases: int = 4,
) -> LLMSandboxProbePlan:
    resolved_config = config or LLMConfig.load()
    if not resolved_config.enabled:
        raise ValueError("LLM analysis is disabled")
    if not resolved_config.api_key:
        raise ValueError("LLM API key is not configured")
    if resolved_config.provider.lower() != "deepseek":
        raise ValueError(f"Unsupported LLM provider: {resolved_config.provider}")

    snapshot = _build_skill_snapshot(skill_path, resolved_config)
    system_prompt = (
        "You generate safe sandbox probe arguments for AI agent skill testing. "
        "Only generate command-line argument lists for the existing entrypoint. "
        "Do not generate code, shell pipelines, destructive commands, credential values, or real external targets. "
        "Prefer harmless placeholder paths under /tmp and example URLs/domains. "
        "Respond with exactly one JSON object and no markdown. "
        "Schema: {\"probes\": [{\"name\": string, \"description\": string, \"args\": string[]}]} "
        f"Return at most {max_cases} probes."
    )
    user_prompt = (
        f"Skill entrypoint: {entrypoint}\n\n"
        "请基于这个 skill 快照生成 sandbox 动态测试用例参数。"
        "目标是尽可能触发真实执行路径，但不能要求访问真实凭证、真实内网或破坏性文件。"
        "如果无法判断参数，返回空 probes。\n\n"
        f"{snapshot}"
    )

    endpoint = f"{resolved_config.api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": resolved_config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    with httpx.Client(timeout=resolved_config.timeout_seconds) as client:
        response = client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {resolved_config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        body = response.json()

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Unexpected LLM response shape") from exc

    parsed = _extract_json_object(content)
    raw_probes = parsed.get("probes") or []
    probes: list[dict[str, Any]] = []
    for item in raw_probes[:max_cases]:
        args = item.get("args") or []
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            continue
        probes.append({
            "name": str(item.get("name") or f"probe-{len(probes) + 1}"),
            "description": str(item.get("description") or ""),
            "args": args[:12],
        })

    return LLMSandboxProbePlan.model_validate({
        "provider": resolved_config.provider,
        "model": resolved_config.model,
        "probes": probes,
        "raw_response": body,
    })
