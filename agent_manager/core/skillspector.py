"""Optional SkillSpector CLI integration.

SkillSpector currently requires a newer Python runtime than Agent Manager's
baseline, so this module treats it as an external optional scanner.
"""

from __future__ import annotations

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .deep_scan_display import with_deep_scan_display
from .llm import LLMConfig

_FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2"}
_RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"}
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

    with tempfile.TemporaryDirectory(prefix="agent-manager-skillspector-") as tmp_dir, contextlib.ExitStack() as stack:
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
        effective_use_llm = use_llm
        llm_note: str | None = None
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
            env, llm_note = _skillspector_llm_env(llm_config, stack)
            if env is None:
                effective_use_llm = False
        if not effective_use_llm:
            cmd.insert(3, "--no-llm")
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
            raw_findings = _normalize_raw_findings(raw_report)
            findings = [
                finding
                for finding in raw_findings
                if not _is_noisy_finding(finding)
            ]
            suppressed_findings = get_suppressed_findings(raw_report)
            risk_assessment = raw_report.get("risk_assessment")
            if not isinstance(risk_assessment, dict):
                risk_assessment = {}
            risk_score = raw_report.get("risk_score", risk_assessment.get("score"))
            raw_risk_severity = str(raw_report.get("risk_severity", risk_assessment.get("severity")) or "SAFE").upper()
            raw_risk_recommendation = raw_report.get(
                "risk_recommendation",
                risk_assessment.get("recommendation"),
            )
            # PDF 命中不参与汇总；其余噪声仍按原有规则处理。
            severity_for_summary = raw_risk_severity
            if any(item["suppression_reason"] == "pdf_file" for item in suppressed_findings):
                severity_for_summary = _max_severity(*(
                    item["severity"] for item in raw_findings
                    if _noise_reason(item) != "pdf_file"
                ))
            effective_severity = _effective_severity(
                severity_for_summary,
                findings,
                risk_score=risk_score,
                recommendation=raw_risk_recommendation,
                all_suppressed_as_binary_noise=(
                    bool(raw_findings)
                    and not findings
                    # PDF 与位图噪声共用汇总规则，避免过滤后仍残留上游风险。
                    and all(_noise_reason(item) in {"raster_image", "pdf_file"} for item in raw_findings)
                ),
            )
            return {
                "available": True,
                "version": version,
                "risk_score": risk_score,
                "raw_risk_severity": raw_risk_severity,
                "raw_risk_recommendation": raw_risk_recommendation,
                "risk_severity": effective_severity,
                "effective_risk_severity": effective_severity,
                "risk_recommendation": _recommendation_for_severity(effective_severity, raw_risk_recommendation),
                "effective_risk_recommendation": _recommendation_for_severity(effective_severity, raw_risk_recommendation),
                "max_severity": effective_severity,
                "findings": findings,
                "suppressed_findings_count": len(suppressed_findings),
                "suppressed_findings": suppressed_findings,
                "raw_report": raw_report,
                "llm_requested": use_llm,
                "llm_enabled": effective_use_llm,
                "llm_note": llm_note,
            }
        except Exception as exc:
            return {
                "available": True,
                "version": version,
                "max_severity": "SAFE",
                "findings": [],
                "raw_report": {},
                "error": str(exc),
                "llm_requested": use_llm,
                "llm_enabled": effective_use_llm,
                "llm_note": llm_note,
            }


def _normalize_raw_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
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
        findings.append(with_deep_scan_display(normalized))
    return findings


def get_suppressed_findings(
    report: dict[str, Any],
    *,
    effective_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return noise details while preserving recorded effective findings."""
    # 历史报告的有效发现以原记录为准，避免新过滤规则将其重复列为噪声。
    effective_keys = {
        (item["rule_id"], item["file"], item.get("line"))
        for item in _normalize_raw_findings({"findings": effective_findings})
    }
    details = []
    for finding in _normalize_raw_findings(report):
        if (finding["rule_id"], finding["file"], finding.get("line")) in effective_keys:
            continue
        reason = _noise_reason(finding)
        if reason:
            details.append({
                "severity": finding["severity"],
                "title": finding["title"],
                "rule_id": finding["rule_id"],
                "file": finding["file"],
                "line": finding.get("line"),
                "suppression_reason": reason,
            })
    return details


def _effective_severity(
    raw_severity: str,
    findings: list[dict[str, Any]],
    *,
    risk_score: Any = None,
    recommendation: Any = None,
    all_suppressed_as_binary_noise: bool = False,
) -> str:
    findings_severity = _max_severity(*(str(item.get("severity") or "SAFE") for item in findings))
    if findings_severity != "SAFE":
        return findings_severity
    if all_suppressed_as_binary_noise:
        return "SAFE"
    if _is_empty_safe_low(raw_severity, risk_score, recommendation):
        return "SAFE"
    if _severity_rank(raw_severity) >= _severity_rank("HIGH"):
        return "MEDIUM"
    return raw_severity.upper() if raw_severity else "SAFE"


def _is_empty_safe_low(raw_severity: str, risk_score: Any, recommendation: Any) -> bool:
    try:
        score = float(risk_score)
    except (TypeError, ValueError):
        return False
    return (
        str(raw_severity or "").upper() == "LOW"
        and score == 0
        and str(recommendation or "").upper() == "SAFE"
    )


def _is_noisy_finding(finding: dict[str, Any]) -> bool:
    return _noise_reason(finding) is not None


def _noise_reason(finding: dict[str, Any]) -> str | None:
    file = str(finding.get("file") or "")
    rule = str(finding.get("rule") or finding.get("rule_id") or "").upper()
    message = str(finding.get("message") or finding.get("evidence") or "").lower()
    suffix = Path(file).suffix.lower()
    if suffix in _FONT_EXTENSIONS:
        return "font_file"
    if _is_raster_image_noise_finding(finding):
        return "raster_image"
    if suffix == ".pdf":
        return "pdf_file"
    if rule == "EA3" and _is_license_file(file) and "limited to" in message:
        return "license_scope_wording"
    return None


def _is_raster_image_noise_finding(finding: dict[str, Any]) -> bool:
    file = str(finding.get("file") or "")
    return Path(file).suffix.lower() in _RASTER_IMAGE_EXTENSIONS


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


def _severity_rank(value: str) -> int:
    return {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4, "EXTREME": 5}.get(
        str(value or "SAFE").upper(),
        0,
    )


def _skillspector_llm_env(
    config: LLMConfig,
    stack: contextlib.ExitStack | None = None,
) -> tuple[dict[str, str] | None, str | None]:
    env = os.environ.copy()
    provider = config.provider.lower()
    if provider in {"model-gateway", "model_gateway"}:
        gateway_url = os.environ.get("AGENT_MANAGER_LLM_GATEWAY_URL", "").strip()
        gateway_api_key = os.environ.get("AGENT_MANAGER_LLM_GATEWAY_API_KEY", "").strip()
        if not gateway_url or not gateway_api_key:
            if stack is None:
                return None, "深度扫描 LLM 已按静态模式运行：缺少内部代理上下文。"
            try:
                proxy_env = stack.enter_context(_internal_model_gateway_proxy(config))
            except Exception as exc:
                return None, f"深度扫描 LLM 已按静态模式运行：内置模型网关代理启动失败：{exc}"
            env.update(proxy_env)
            return env, "深度扫描 LLM 已通过 Agent Manager 内置模型网关代理运行。"
        env["SKILLSPECTOR_PROVIDER"] = "openai"
        env["OPENAI_API_KEY"] = gateway_api_key
        env["OPENAI_BASE_URL"] = _openai_base_url(gateway_url)
        env["SKILLSPECTOR_MODEL"] = config.model
        return env, None
    if provider == "anthropic":
        env["SKILLSPECTOR_PROVIDER"] = "anthropic"
        env["ANTHROPIC_API_KEY"] = config.api_key or ""
    else:
        env["SKILLSPECTOR_PROVIDER"] = "openai"
        env["OPENAI_API_KEY"] = config.api_key or ""
        env["OPENAI_BASE_URL"] = config.api_base
    env["SKILLSPECTOR_MODEL"] = config.model
    return env, None


def _adapt_deepseek_structured_output(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate OpenAI JSON Schema output into DeepSeek JSON mode.

    DeepSeek supports ``response_format.type=json_object`` but not the
    ``json_schema`` variant emitted by ChatOpenAI structured output. Preserve
    the schema as a system instruction so SkillSpector can still validate the
    returned object locally.
    """
    model = str(payload.get("model") or "").lower()
    response_format = payload.get("response_format")
    if not model.startswith("deepseek-") or not isinstance(response_format, dict):
        return payload
    if response_format.get("type") != "json_schema":
        return payload

    adapted = dict(payload)
    adapted["response_format"] = {"type": "json_object"}
    json_schema = response_format.get("json_schema")
    schema = json_schema.get("schema") if isinstance(json_schema, dict) else None
    if not isinstance(schema, dict):
        return adapted

    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    schema_name = str(json_schema.get("name") or "response")
    instruction = (
        "Return only one valid JSON object matching the JSON Schema named "
        f"{schema_name!r}. Do not include markdown or explanatory text. "
        f"JSON Schema: {schema_text}"
    )
    messages = adapted.get("messages")
    if isinstance(messages, list):
        adapted["messages"] = [
            {"role": "system", "content": instruction},
            *[dict(item) if isinstance(item, dict) else item for item in messages],
        ]
    return adapted


@contextlib.contextmanager
def _internal_model_gateway_proxy(config: LLMConfig):
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return self.headers.get("Authorization", "").strip() == f"Bearer {token}"

        def do_GET(self) -> None:
            if self.path not in {"/models", "/v1/models"}:
                self._send_json(404, {"error": {"message": "not found"}})
                return
            if not self._authorized():
                self._send_json(401, {"error": {"message": "unauthorized"}})
                return
            self._send_json(200, {
                "object": "list",
                "data": [{
                    "id": config.model,
                    "object": "model",
                    "owned_by": "agent-manager",
                }],
            })

        def do_POST(self) -> None:
            if self.path not in {"/", "/chat/completions", "/v1/chat/completions"}:
                self._send_json(404, {"error": {"message": "not found"}})
                return
            if not self._authorized():
                self._send_json(401, {"error": {"message": "unauthorized"}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8") or "{}")
                if not payload.get("model"):
                    payload["model"] = config.model
                payload = _adapt_deepseek_structured_output(payload)
                from .llm import _call_model_gateway_sync

                response = _call_model_gateway_sync(payload)
                self._send_json(200, response)
            except Exception as exc:
                self._send_json(500, {
                    "error": {
                        "message": str(exc),
                        "type": "agent_manager_model_gateway_error",
                    },
                })

        def log_message(self, _format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "SKILLSPECTOR_PROVIDER": "openai",
            "OPENAI_API_KEY": token,
            "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "SKILLSPECTOR_MODEL": config.model,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _openai_base_url(value: str) -> str:
    base = value.rstrip("/")
    suffixes = (
        "/api/v1/llm/chat/completions",
        "/v1/chat/completions",
        "/chat/completions",
    )
    for suffix in suffixes:
        if base.endswith(suffix):
            return base[: -len(suffix)] or base
    return base


def _max_severity(*values: str) -> str:
    order = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4, "EXTREME": 5}
    normalized = (str(value or "SAFE").upper() for value in values)
    return max(normalized, key=lambda value: order.get(value, 0), default="SAFE")
