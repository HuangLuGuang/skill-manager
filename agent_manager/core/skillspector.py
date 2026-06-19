"""Optional SkillSpector CLI integration.

SkillSpector currently requires a newer Python runtime than Agent Manager's
baseline, so this module treats it as an external optional scanner.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .llm import LLMConfig

_FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}
_LICENSE_FILENAMES = {"license", "license.txt", "notice", "notice.txt", "copying"}
_CACHE_TTL_SECONDS = 60
_availability_cache: tuple[float, str | None] | None = None
_version_cache: tuple[float, str | None, str | None] | None = None


def _skillspector_executable() -> str | None:
    configured = os.environ.get("SKILLSPECTOR_BIN")
    if configured:
        return configured if Path(configured).exists() else None
    return shutil.which("skillspector")


def is_skillspector_available() -> bool:
    global _availability_cache
    now = time.monotonic()
    if _availability_cache and now - _availability_cache[0] < _CACHE_TTL_SECONDS:
        return _availability_cache[1] is not None
    executable = _skillspector_executable()
    _availability_cache = (now, executable)
    return executable is not None


def get_skillspector_version() -> str | None:
    global _version_cache
    executable = _skillspector_executable()
    if not executable:
        return None
    now = time.monotonic()
    if _version_cache and _version_cache[1] == executable and now - _version_cache[0] < _CACHE_TTL_SECONDS:
        return _version_cache[2]
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return None
    value = (completed.stdout or completed.stderr or "").strip()
    version = value or None
    _version_cache = (now, executable, version)
    return version


def run_skillspector_scan(
    skill_path: Path,
    timeout_seconds: int = 120,
    use_llm: bool = False,
) -> dict[str, Any]:
    executable = _skillspector_executable()
    version = get_skillspector_version()
    if not executable:
        return {
            "available": False,
            "version": version,
            "max_severity": "SAFE",
            "findings": [],
            "raw_report": {},
            "error": "SkillSpector CLI is not installed or not on PATH",
        }

    with tempfile.TemporaryDirectory(prefix="agent-manager-skillspector-") as tmp_dir:
        output_path = Path(tmp_dir) / "skillspector-report.json"
        cmd = [
            executable,
            "scan",
            str(skill_path),
            "--format",
            "json",
            "--output",
            str(output_path),
        ]
        if not use_llm:
            cmd.insert(3, "--no-llm")
        env = None
        if use_llm:
            llm_config = LLMConfig.load()
            if not llm_config.is_ready:
                return {
                    "available": True,
                    "version": version,
                    "max_severity": "SAFE",
                    "findings": [],
                    "raw_report": {},
                    "error": "SkillSpector LLM is enabled but system LLM config is not ready",
                }
            env = _skillspector_llm_env(llm_config)
        try:
            run_kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": timeout_seconds,
                "check": False,
            }
            if env is not None:
                run_kwargs["env"] = env
            completed = subprocess.run(
                cmd,
                **run_kwargs,
            )
            if completed.returncode not in (0, 1):
                raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip())
            raw_report = json.loads(output_path.read_text(encoding="utf-8"))
            findings = _normalize_findings(raw_report)
            risk_assessment = raw_report.get("risk_assessment")
            if not isinstance(risk_assessment, dict):
                risk_assessment = {}
            risk_score = raw_report.get("risk_score", risk_assessment.get("score"))
            risk_severity = raw_report.get("risk_severity", risk_assessment.get("severity"))
            risk_recommendation = raw_report.get(
                "risk_recommendation",
                risk_assessment.get("recommendation"),
            )
            effective_severity = _max_severity(*(str(item.get("severity") or "SAFE") for item in findings))
            return {
                "available": True,
                "version": version,
                "risk_score": risk_score,
                "risk_severity": effective_severity,
                "risk_recommendation": _recommendation_for_severity(effective_severity, risk_recommendation),
                "max_severity": effective_severity,
                "findings": findings,
                "raw_report": raw_report,
            }
        except Exception as exc:
            return {
                "available": True,
                "version": version,
                "max_severity": "SAFE",
                "findings": [],
                "raw_report": {},
                "error": str(exc),
            }


def _normalize_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    raw_findings = report.get("filtered_findings")
    if raw_findings is None:
        raw_findings = report.get("findings")
    if raw_findings is None:
        raw_findings = report.get("issues", [])
    if not isinstance(raw_findings, list):
        return []

    findings: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        location = item.get("location")
        if not isinstance(location, dict):
            location = {}
        rule_id = str(item.get("rule_id") or item.get("rule") or item.get("id") or "skillspector")
        message = str(item.get("message") or item.get("finding") or item.get("pattern") or rule_id)
        line = item.get("start_line") or item.get("line") or location.get("start_line")
        normalized = {
            "severity": str(item.get("severity") or "LOW").upper(),
            "title": str(item.get("pattern") or item.get("message") or rule_id),
            "message": message,
            "file": str(item.get("file") or location.get("file") or ""),
            "source": "skillspector",
            "rule": rule_id,
            "rule_id": rule_id,
            "category": str(item.get("category") or ""),
            "confidence": item.get("confidence"),
            "finding": item.get("finding"),
            "explanation": item.get("explanation"),
            "remediation": item.get("remediation"),
            "code_snippet": item.get("code_snippet"),
        }
        if line is not None:
            normalized["line"] = line
        if not _is_noisy_finding(normalized):
            findings.append(normalized)
    return findings


def _is_noisy_finding(finding: dict[str, Any]) -> bool:
    file = str(finding.get("file") or "")
    rule = str(finding.get("rule") or finding.get("rule_id") or "").upper()
    message = str(finding.get("message") or finding.get("evidence") or "").lower()
    suffix = Path(file).suffix.lower()
    if suffix in _FONT_EXTENSIONS:
        return True
    if rule == "EA3" and _is_license_file(file) and "limited to" in message:
        return True
    return False


def _is_license_file(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return name in _LICENSE_FILENAMES or name.endswith("-ofl.txt")


def _recommendation_for_severity(severity: str, fallback: Any) -> str:
    return {
        "SAFE": "SAFE",
        "INFO": "SAFE",
        "LOW": "SAFE",
        "MEDIUM": "CAUTION",
        "HIGH": "DO_NOT_INSTALL",
        "CRITICAL": "DO_NOT_INSTALL",
    }.get(str(severity or "").upper(), str(fallback or "SAFE"))


def _skillspector_llm_env(config: LLMConfig) -> dict[str, str]:
    env = os.environ.copy()
    provider = config.provider.lower()
    if provider == "anthropic":
        env["SKILLSPECTOR_PROVIDER"] = "anthropic"
        env["ANTHROPIC_API_KEY"] = config.api_key or ""
    else:
        env["SKILLSPECTOR_PROVIDER"] = "openai"
        env["OPENAI_API_KEY"] = config.api_key or ""
        env["OPENAI_BASE_URL"] = config.api_base
    env["SKILLSPECTOR_MODEL"] = config.model
    return env


def _max_severity(*values: str) -> str:
    order = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4, "EXTREME": 5}
    normalized = (str(value or "SAFE").upper() for value in values)
    return max(normalized, key=lambda value: order.get(value, 0), default="SAFE")
