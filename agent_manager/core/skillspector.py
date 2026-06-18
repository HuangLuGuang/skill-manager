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
from pathlib import Path
from typing import Any

from .llm import LLMConfig


def _skillspector_executable() -> str | None:
    configured = os.environ.get("SKILLSPECTOR_BIN")
    if configured:
        return configured if Path(configured).exists() else None
    return shutil.which("skillspector")


def is_skillspector_available() -> bool:
    return _skillspector_executable() is not None


def get_skillspector_version() -> str | None:
    executable = _skillspector_executable()
    if not executable:
        return None
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
    return value or None


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
            return {
                "available": True,
                "version": version,
                "risk_score": risk_score,
                "risk_severity": risk_severity,
                "risk_recommendation": risk_recommendation,
                "max_severity": _max_severity(
                    str(risk_severity or "SAFE"),
                    *(str(item.get("severity") or "SAFE") for item in findings),
                ),
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
        findings.append(normalized)
    return findings


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
