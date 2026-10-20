"""
Vetting pipeline — wraps skill-scanner and applies company policy checks.

Produces a VettingResult with risk level, findings summary, and policy notes.
Falls back to a basic static check if skill-scanner is not installed.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from .llm import (
    LLMConfig,
    LLMAnalysisTimeout,
    llm_analysis_timeout,
    _build_skill_snapshot,  # noqa: F401 - used via llm module
    analyze_skill_with_llm_single_round,
)
from .local_analyzers import run_local_static_analysis
from .models import PolicyViolation, RiskLevel, SourceInfo, VettingResult
from .sandbox import (
    build_probe_plan,
    discover_probe_entrypoint,
    get_sandbox_runner,
)
from .skillspector import run_skillspector_scan
from .text_reader import read_text_fallback

if TYPE_CHECKING:
    from .policy import CompanyPolicy

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {
    "SAFE": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}
_BEHAVIORAL_TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
}
_BEHAVIORAL_PRIORITY_DIRS = ("scripts", "references", "prompts")
_BEHAVIORAL_RULES = (
    {
        "rule": "subprocess_shell_true",
        "severity": "HIGH",
        "title": "检测到 shell=True 子进程调用",
        "message": "脚本通过 subprocess 且 shell=True 执行命令，存在命令注入和权限放大风险。",
        "pattern": re.compile(r"subprocess\.(?:run|Popen|call|check_call|check_output)\s*\([^\\n]*shell\s*=\s*True"),
    },
    {
        "rule": "os_command_execution",
        "severity": "HIGH",
        "title": "检测到直接系统命令执行",
        "message": "脚本直接调用 os.system 或 os.popen，执行路径不透明，风险较高。",
        "pattern": re.compile(r"\bos\.(?:system|popen)\s*\("),
    },
    {
        "rule": "dynamic_code_execution",
        "severity": "HIGH",
        "title": "检测到动态代码执行",
        "message": "脚本出现 eval 或 exec，可能执行动态构造代码。",
        "pattern": re.compile(r"(?<![\w.])(?:eval|exec)\s*\("),
    },
    {
        "rule": "download_and_execute",
        "severity": "HIGH",
        "title": "检测到下载后执行模式",
        "message": "脚本中存在 curl/wget 与 shell 管道组合，可能下载后直接执行远程内容。",
        "pattern": re.compile(r"(?:curl|wget)[^\n|>]*(?:\||>)\s*(?:sh|bash|zsh)"),
    },
    {
        "rule": "credential_file_access",
        "severity": "MEDIUM",
        "title": "检测到敏感凭据文件访问",
        "message": "脚本中出现常见凭据文件路径，可能访问本地敏感配置。",
        "pattern": re.compile(r"(?:\.aws/credentials|id_rsa|id_dsa|\.ssh/config|\.env\b|/etc/shadow|/etc/passwd)"),
    },
    {
        "rule": "encoded_payload_execution",
        "severity": "MEDIUM",
        "title": "检测到编码载荷或反序列化执行风险",
        "message": "脚本中出现 base64 解码、pickle.loads 或 marshal.loads，需确认是否用于执行外部输入。",
        "pattern": re.compile(r"(?:base64\.(?:b64decode|urlsafe_b64decode)|pickle\.loads|marshal\.loads)"),
    },
)
_SANDBOX_ENTRYPOINT_EXTENSIONS = {".py", ".sh", ".js"}
_UNSAFE_LLM_PROBE_ARGS = {"&&", "||", "|", ";", "<", ">", ">>", "2>", "&"}
_BLOCKING_RULES = {
    "download_and_execute",
    "credential_exfiltration",
    "data_exfiltration",
    "agent_manager_bypass",
}
_NOISE_RULES = {"DEPENDENCY_MISSING", "MISSING_DEPENDENCY"}
_NOISE_CATEGORIES = {"dependency", "runtime"}


def _analyzer_worker_count() -> int:
    try:
        return max(1, int(os.environ.get("AGENT_MANAGER_ANALYZER_WORKERS", "8")))
    except ValueError:
        return 8


def _skillspector_concurrency() -> int:
    try:
        return max(1, int(os.environ.get("AGENT_MANAGER_SKILLSPECTOR_CONCURRENCY", "2")))
    except ValueError:
        return 2


_analyzer_executor = ThreadPoolExecutor(
    max_workers=_analyzer_worker_count(),
    thread_name_prefix="agent-manager-analyzer",
)
_skillspector_slots = threading.BoundedSemaphore(_skillspector_concurrency())


def _shutdown_analyzer_executor() -> None:
    _analyzer_executor.shutdown(wait=True, cancel_futures=False)


atexit.register(_shutdown_analyzer_executor)


@dataclass(frozen=True)
class AnalyzerExecution:
    """One analyzer result returned without mutating the shared scan report."""

    name: str
    result: dict[str, Any]
    duration_seconds: float


@dataclass
class SandboxExecution:
    result: dict[str, Any]
    findings: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    runtime: str | None = None
    max_severity: str = "SAFE"
    duration_seconds: float = 0.0


def _timed_analyzer(name: str, callback: Callable[[], dict[str, Any]]) -> AnalyzerExecution:
    started = time.monotonic()
    result = callback()
    return AnalyzerExecution(
        name=name,
        result=result,
        duration_seconds=time.monotonic() - started,
    )


def _normalize_llm_probe_entrypoint(
    skill_path: Path,
    candidate: str | None,
    default_entrypoint: str,
) -> str | None:
    raw = (candidate or default_entrypoint).strip()
    if not raw or raw.startswith("/") or ".." in Path(raw).parts:
        return None

    root = skill_path.resolve()
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file() or target.suffix.lower() not in _SANDBOX_ENTRYPOINT_EXTENSIONS:
        return None
    return target.relative_to(root).as_posix()


def _llm_probe_args_safe(args: list[str]) -> bool:
    return all(str(arg).strip() not in _UNSAFE_LLM_PROBE_ARGS for arg in args)


# --------------------------------------------------------------------------- #
# Scanner integration                                                           #
# --------------------------------------------------------------------------- #

def _try_import_scanner():
    try:
        from skill_scanner import SkillScanner
        from skill_scanner.core.scan_policy import ScanPolicy
        return SkillScanner, ScanPolicy
    except ImportError:
        return None, None


_scanner_instances: dict[tuple[type, str], tuple[Any, threading.Lock]] = {}
_scanner_instances_lock = threading.Lock()


def _scanner_instance(SkillScanner: type, ScanPolicy: type, scanner_policy_name: str) -> tuple[Any, threading.Lock]:
    key = (SkillScanner, scanner_policy_name)
    with _scanner_instances_lock:
        cached = _scanner_instances.get(key)
        if cached is not None:
            return cached
        try:
            policy = ScanPolicy.from_preset(scanner_policy_name)
        except Exception:
            policy = ScanPolicy.default()
        cached = (SkillScanner(policy=policy), threading.Lock())
        _scanner_instances[key] = cached
        return cached


def _run_scanner(skill_path: Path, scanner_policy_name: str) -> dict:
    """Run skill-scanner and return the serialized ScanResult dict."""
    SkillScanner, ScanPolicy = _try_import_scanner()
    if SkillScanner is None:
        logger.warning("skill-scanner not installed — using basic file check only")
        return {"scanner_unavailable": True, "findings": [], "max_severity": "SAFE"}

    scanner, scan_lock = _scanner_instance(SkillScanner, ScanPolicy, scanner_policy_name)
    try:
        # The upstream scanner does not document thread safety. Reuse removes
        # repeated model/analyzer initialization while serializing access to the
        # shared instance.
        with scan_lock:
            result = scanner.scan_skill(str(skill_path))
        return result.to_dict()
    except Exception as exc:
        logger.warning("skill-scanner failed for %s; continuing with local analyzers: %s", skill_path, exc)
        return {
            "max_severity": "SAFE",
            "findings": [],
            "analyzers_used": ["scanner:error"],
            "scanner_error": str(exc),
        }


def warmup_scanner(scanner_policy_name: str = "balanced") -> None:
    """Load and exercise the base scanner before the first user submission."""
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="agent-manager-scanner-warmup-") as tmp_dir:
            skill_path = Path(tmp_dir)
            (skill_path / "SKILL.md").write_text(
                "---\nname: agent-manager-scanner-warmup\ndescription: scanner warmup\n---\n",
                encoding="utf-8",
            )
            _run_scanner(skill_path, scanner_policy_name)
    except Exception:
        logger.exception("Base scanner warmup failed")
    else:
        logger.info("Base scanner warmup completed in %.3fs", time.monotonic() - started)


# --------------------------------------------------------------------------- #
# Manifest loading (no scanner dependency)                                      #
# --------------------------------------------------------------------------- #

def _load_manifest(skill_path: Path) -> tuple[str, str, list[str], str | None]:
    """
    Parse SKILL.md frontmatter.
    Returns (name, description, allowed_tools, license).
    Raises ValueError if SKILL.md is missing or unparseable.
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise ValueError(f"SKILL.md not found in {skill_path}")

    try:
        import frontmatter
    except ImportError:
        frontmatter = None

    if frontmatter is not None:
        try:
            post = frontmatter.load(str(skill_md))
        except Exception as exc:
            logger.warning("python-frontmatter failed to parse %s; falling back to tolerant parser: %s", skill_md, exc)
        else:
            name = post.get("name") or post.get("skill-name")
            if not name:
                raise ValueError("SKILL.md 缺少 name 字段（格式：name: your-skill-name）")
            description = post.get("description") or ""
            raw_tools = post.get("allowed-tools") or post.get("allowed_tools") or []
            if isinstance(raw_tools, str):
                raw_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
            return str(name), str(description), list(raw_tools), post.get("license")

    # Fallback: parse SKILL.md frontmatter without python-frontmatter.
    content, _encoding = read_text_fallback(skill_md)
    name = ""
    description = ""
    allowed_tools: list[str] = []
    license_val = None

    in_frontmatter = False
    fm_lines: list[str] = []
    for i, line in enumerate(content.splitlines()):
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == "---":
                break
            fm_lines.append(line)

    fm_text = "\n".join(fm_lines)
    try:
        import yaml

        payload = yaml.safe_load(fm_text) or {}
    except Exception:
        payload = None
    if isinstance(payload, dict):
        name = str(payload.get("name") or payload.get("skill-name") or "").strip()
        if not name:
            raise ValueError("SKILL.md 缺少 name 字段（格式：name: your-skill-name）")
        description = str(payload.get("description") or description)
        raw_tools = payload.get("allowed-tools") or payload.get("allowed_tools") or []
        if isinstance(raw_tools, str):
            allowed_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        elif isinstance(raw_tools, list):
            allowed_tools = [str(t).strip() for t in raw_tools if str(t).strip()]
        license_raw = payload.get("license")
        if license_raw is not None:
            license_val = str(license_raw)
        return name, description, allowed_tools, license_val

    for line in fm_lines:
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("license:"):
            license_val = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("allowed-tools:") or line.startswith("allowed_tools:"):
            raw = line.split(":", 1)[1].strip().strip('"\'')
            if raw:
                allowed_tools = [t.strip() for t in raw.split(",") if t.strip()]

    if not name:
        raise ValueError("SKILL.md 缺少 name 字段（格式：name: your-skill-name）")
    return name, description, allowed_tools, license_val


# --------------------------------------------------------------------------- #
# Policy checks (independent of scanner)                                        #
# --------------------------------------------------------------------------- #

def _check_manifest_policy(
    allowed_tools: list[str],
    license_val: str | None,
    policy: "CompanyPolicy",
) -> list[PolicyViolation]:
    violations: list[PolicyViolation] = []

    if policy._data.get("require_license") and not license_val:
        violations.append(PolicyViolation(
            rule="require_license",
            message="Skill manifest is missing a 'license' field (required by policy)",
            blocking=False,
        ))

    accepted = [l.lower() for l in policy._data.get("accepted_licenses", [])]
    if license_val and accepted and license_val.lower() not in accepted:
        violations.append(PolicyViolation(
            rule="unaccepted_license",
            message=f"License {license_val!r} is not in the accepted list: {policy._data['accepted_licenses']}",
            params={"license": license_val, "accepted_licenses": list(policy._data["accepted_licenses"])},
            blocking=False,
        ))

    tool_violations = policy.check_tool_declarations(allowed_tools)
    violations.extend(tool_violations)

    return violations


def _max_severity(*values: str) -> str:
    resolved = "SAFE"
    resolved_rank = -1
    for value in values:
        rank = _SEVERITY_ORDER.get((value or "SAFE").upper(), 0)
        if rank > resolved_rank:
            resolved_rank = rank
            resolved = (value or "SAFE").upper()
    return resolved


def _risk_max_severity(findings: list[dict], reported_max: str = "SAFE") -> str:
    finding_max = _max_severity(*(
        str(finding.get("severity", "SAFE"))
        for finding in findings
        if not _is_low_analyzability_signal(finding)
    ))
    if finding_max != "SAFE" or not findings:
        return _max_severity(finding_max, reported_max)
    return "SAFE"


def _is_low_analyzability_signal(finding: dict) -> bool:
    rule = str(finding.get("rule") or finding.get("rule_id") or "").upper()
    severity = str(finding.get("severity", "SAFE")).upper()
    return rule == "LOW_ANALYZABILITY" and _SEVERITY_ORDER.get(severity, 0) <= _SEVERITY_ORDER["MEDIUM"]


def _classify_finding_detail(finding: dict, policy: "CompanyPolicy") -> tuple[str, str | None]:
    policy_key = policy.finding_policy_key(finding)
    configured = policy.risk_classification.get(policy_key) if policy_key else None
    if configured:
        return configured, policy_key

    rule = str(finding.get("rule") or finding.get("rule_id") or "").strip()
    rule_upper = rule.upper()
    category = str(finding.get("category") or "").strip().lower()
    severity = str(finding.get("severity", "SAFE")).upper()
    text = " ".join(
        str(finding.get(key) or "")
        for key in ("title", "message", "evidence", "category", "pattern", "finding", "explanation", "code_snippet")
    ).lower()

    if rule in _BLOCKING_RULES or any(token in text for token in ("exfiltrat", "数据外传", "窃取凭据", "steal credential")):
        return "blocking", None
    if rule_upper in _NOISE_RULES or category in _NOISE_CATEGORIES or _is_low_analyzability_signal(finding):
        return "noise", None
    if _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER["MEDIUM"]:
        return "risk", None
    return "noise", None


def _classify_finding(finding: dict, policy: "CompanyPolicy") -> str:
    return _classify_finding_detail(finding, policy)[0]


def _classify_findings(findings: list[dict], policy: "CompanyPolicy") -> dict[str, object]:
    items = []
    for finding in findings:
        classification, policy_key = _classify_finding_detail(finding, policy)
        item = {**finding, "classification": classification}
        if policy_key:
            item["classification_key"] = policy_key
        items.append(item)
    return {
        "items": items,
        "blocking_count": sum(1 for item in items if item["classification"] == "blocking"),
        "risk_count": sum(1 for item in items if item["classification"] == "risk"),
        "noise_count": sum(1 for item in items if item["classification"] == "noise"),
    }


def _risk_from_classification(classification: dict[str, object], mode: str) -> tuple[RiskLevel, str]:
    items = classification.get("items", [])
    if not isinstance(items, list):
        items = []
    if any(item.get("classification") == "blocking" for item in items):
        return RiskLevel.MALICIOUS, "blocking"

    max_risk_severity = _max_severity(*(
        str(item.get("severity", "SAFE"))
        for item in items
        if item.get("classification") == "risk"
    ))
    rank = _SEVERITY_ORDER.get(max_risk_severity, 0)
    if rank >= _SEVERITY_ORDER["HIGH"]:
        return (RiskLevel.MALICIOUS if mode == "strict" else RiskLevel.SUSPICIOUS), "risk"
    if rank >= _SEVERITY_ORDER["MEDIUM"]:
        return (RiskLevel.BENIGN if mode == "permissive" else RiskLevel.SUSPICIOUS), "risk"
    return RiskLevel.BENIGN, "noise"


def reconcile_llm_risk(
    pre_llm_risk: RiskLevel,
    llm_risk: RiskLevel | None,
    has_blocking_findings: bool,
    mode: str,
) -> tuple[RiskLevel, bool, bool]:
    """Reconcile an LLM assessment with deterministic risk and policy constraints."""
    lowered = bool(
        llm_risk
        and not has_blocking_findings
        and mode in {"balanced", "permissive"}
        and not llm_risk.is_at_least(pre_llm_risk)
    )
    downgrade_blocked = bool(
        llm_risk and not llm_risk.is_at_least(pre_llm_risk) and not lowered
    )
    final_risk = (
        llm_risk if llm_risk and (llm_risk.is_at_least(pre_llm_risk) or lowered)
        else pre_llm_risk
    )
    return final_risk, lowered, downgrade_blocked


def _iter_behavioral_candidate_files(skill_path: Path) -> list[Path]:
    priority_files: list[Path] = []
    fallback_files: list[Path] = []

    for path in sorted(skill_path.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(skill_path).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if "__pycache__" in rel_parts:
            continue
        if path.suffix.lower() not in _BEHAVIORAL_TEXT_EXTENSIONS:
            continue
        if rel_parts and rel_parts[0] in _BEHAVIORAL_PRIORITY_DIRS:
            priority_files.append(path)
        else:
            fallback_files.append(path)

    return [*priority_files, *fallback_files]


def _run_behavioral_analysis(skill_path: Path) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    scanned_files: list[str] = []

    for path in _iter_behavioral_candidate_files(skill_path):
        try:
            content, _encoding = read_text_fallback(path)
        except Exception:
            continue

        rel_path = path.relative_to(skill_path).as_posix()
        scanned_files.append(rel_path)
        for rule in _BEHAVIORAL_RULES:
            match = rule["pattern"].search(content)
            if not match:
                continue

            line_no = content[: match.start()].count("\n") + 1
            findings.append({
                "severity": str(rule["severity"]),
                "title": str(rule["title"]),
                "message": f"{rule['message']} 文件: {rel_path}:{line_no}",
                "file": rel_path,
                "source": "behavioral",
                "rule": str(rule["rule"]),
            })

    max_severity = "SAFE"
    for finding in findings:
        max_severity = _max_severity(max_severity, finding["severity"])

    return {
        "max_severity": max_severity,
        "findings": findings,
        "scanned_files": scanned_files,
        "scanned_file_count": len(scanned_files),
    }


def _run_behavioral_bundle(skill_path: Path) -> dict[str, Any]:
    local_static_result = run_local_static_analysis(skill_path)
    behavioral_result = _run_behavioral_analysis(skill_path)
    findings = [
        *behavioral_result.get("findings", []),
        *local_static_result.get("findings", []),
    ]
    return {
        "behavioral_analysis": behavioral_result,
        "local_static_analysis": local_static_result,
        "findings": findings,
        "max_severity": _max_severity(
            str(behavioral_result.get("max_severity", "SAFE")),
            str(local_static_result.get("max_severity", "SAFE")),
        ),
    }


def _run_skillspector_without_llm(skill_path: Path, timeout_seconds: int) -> dict[str, Any]:
    # SkillSpector is an expensive subprocess. Limit concurrent processes and
    # keep all model use in the final Agent Manager judgement.
    with _skillspector_slots:
        return run_skillspector_scan(
            skill_path,
            timeout_seconds=timeout_seconds,
            use_llm=False,
        )


def _run_sandbox_analysis(skill_path: Path) -> SandboxExecution:
    runtime: str | None = None
    entrypoint: str | None = None
    try:
        runner = get_sandbox_runner()
        runtime = runner.config.runtime
        entrypoint = discover_probe_entrypoint(skill_path)
        if not entrypoint:
            return SandboxExecution(
                runtime=runtime,
                result={
                    "executed": False,
                    "runtime": runtime,
                    "available": True,
                    "reason_code": "no_executable_script",
                    "reason": (
                        "No supported executable script found. "
                        "SKILL.md command examples are not executed as Sandbox probes."
                    ),
                },
                notes=["[SANDBOX] no supported executable script found; skipped SKILL.md command examples"],
            )

        probe_plan = build_probe_plan(skill_path, entrypoint)
        probe_case = {
            "name": "default",
            "description": f"default sandbox probe strategy={probe_plan.strategy}",
            "entrypoint": probe_plan.entrypoint,
            "args": probe_plan.args,
            "generated_by": "default",
        }
        sandbox_exec = runner.run_probe(
            skill_path,
            entrypoint=probe_plan.entrypoint,
            args=probe_plan.args,
        )
        result_payload = sandbox_exec.model_dump(mode="json")
        result_payload.update({
            "probe_name": probe_case["name"],
            "probe_description": probe_case["description"],
            "probe_entrypoint": probe_plan.entrypoint,
            "probe_args": probe_plan.args,
            "probe_generated_by": "default",
        })
        events = list(sandbox_exec.signals or sandbox_exec.suspicious_events)
        max_severity = _max_severity(*(event.severity for event in events))
        findings = [
            {
                "severity": event.severity,
                "title": event.message,
                "message": event.message,
                "file": probe_plan.entrypoint,
                "source": "sandbox",
                "probe": "default",
                "probe_entrypoint": probe_plan.entrypoint,
                "category": event.category,
                "evidence": event.evidence,
            }
            for event in events
        ]
        sandbox_result = sandbox_exec.model_dump(mode="json")
        sandbox_result.update({
            "probe_strategy": probe_plan.strategy,
            "probe_args": probe_plan.args,
            "probe_cases": [probe_case],
            "probe_results": [result_payload],
            "llm_probe_plan": None,
        })
        notes = []
        if sandbox_exec.executed:
            notes.append(
                f"[SANDBOX] executed {entrypoint} strategy={probe_plan.strategy} "
                f"cases=1 exit_code={sandbox_exec.exit_code} timeout={sandbox_exec.timed_out} "
                f"duration_ms={sandbox_exec.duration_ms}"
            )
        else:
            notes.append(f"[SANDBOX] skipped: {sandbox_exec.reason or 'not executed'}")
        notes.extend(f"[SANDBOX] default {event.category}: {event.message}" for event in events)
        return SandboxExecution(
            result=sandbox_result,
            findings=findings,
            notes=notes,
            runtime=runtime,
            max_severity=max_severity,
        )
    except Exception as exc:
        logger.warning("Sandbox analysis skipped for %s: %s", skill_path, exc)
        return SandboxExecution(
            runtime=runtime,
            result={
                "executed": False,
                "runtime": runtime or "unknown",
                "available": False,
                "entrypoint": entrypoint,
                "reason": f"Sandbox analysis skipped: {exc}",
            },
            notes=[f"[SANDBOX] analysis skipped: {exc}"],
        )


def _timed_sandbox(skill_path: Path) -> SandboxExecution:
    started = time.monotonic()
    result = _run_sandbox_analysis(skill_path)
    result.duration_seconds = time.monotonic() - started
    return result


# --------------------------------------------------------------------------- #
# Main vetting entry point                                                      #
# --------------------------------------------------------------------------- #

class VettingPipeline:
    """Run independent analyzers concurrently, then reconcile once."""

    def __init__(self, policy: "CompanyPolicy"):
        self.policy = policy

    def vet(
        self,
        skill_path: Path,
        source: SourceInfo,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
        use_skillspector: bool | None = None,
        judgement_mode: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
        analyzer_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[VettingResult, list[PolicyViolation], str, str, list[str]]:
        """Run selected analyzers and return the final policy-ready result."""
        from .licensing import require_license
        require_license("security_scanning")
        started = time.monotonic()
        skill_path = Path(skill_path).resolve()
        effective_judgement_mode = (
            judgement_mode
            if judgement_mode in {"strict", "balanced", "permissive"}
            else self.policy.judgement_mode
        )

        try:
            name, description, allowed_tools, license_val = _load_manifest(skill_path)
        except ValueError as exc:
            raise ValueError(f"Cannot vet skill: {exc}") from exc

        should_run_skillspector = (
            self.policy.skillspector_enabled
            if use_skillspector is None
            else use_skillspector
        )

        def report_analyzer(name: str, status: str) -> None:
            if status == "running":
                require_license("security_scanning")
            if analyzer_callback:
                analyzer_callback(name, status)

        def run_analyzer(name: str, callback: Callable[[], Any]) -> Any:
            report_analyzer(name, "running")
            try:
                execution = callback()
            except Exception:
                report_analyzer(name, "failed")
                raise
            result = execution.result
            status = "completed"
            if name == "scanner":
                status = "skipped" if result.get("scanner_unavailable") else "failed" if result.get("scanner_error") else "completed"
            elif name == "skillspector":
                status = "skipped" if not result.get("available") else "failed" if result.get("error") else "completed"
            elif name == "sandbox":
                status = "failed" if result.get("available") is False else "completed" if result.get("executed") else "skipped"
            report_analyzer(name, status)
            return execution

        report_analyzer("scanner", "pending")
        report_analyzer("behavioral", "pending" if use_behavioral else "disabled")
        report_analyzer("skillspector", "pending" if should_run_skillspector else "disabled")
        report_analyzer("sandbox", "pending")
        report_analyzer("llm", "pending" if use_llm else "disabled")
        if progress_callback:
            progress_callback("analyzers")
        futures: dict[str, Future[Any]] = {
            "scanner": _analyzer_executor.submit(
                run_analyzer,
                "scanner",
                lambda: _timed_analyzer("scanner", lambda: _run_scanner(skill_path, self.policy.scanner_policy)),
            ),
        }
        if use_behavioral:
            futures["behavioral"] = _analyzer_executor.submit(
                run_analyzer,
                "behavioral",
                lambda: _timed_analyzer("behavioral", lambda: _run_behavioral_bundle(skill_path)),
            )
        if should_run_skillspector:
            futures["skillspector"] = _analyzer_executor.submit(
                run_analyzer,
                "skillspector",
                lambda: _timed_analyzer("skillspector", lambda: _run_skillspector_without_llm(
                    skill_path,
                    self.policy.skillspector_timeout_seconds,
                )),
            )
        if use_sandbox:
            futures["sandbox"] = _analyzer_executor.submit(run_analyzer, "sandbox", lambda: _timed_sandbox(skill_path))

        analyzer_timings: dict[str, dict[str, Any]] = {}
        scanner_execution: AnalyzerExecution = futures["scanner"].result()
        scan_report = dict(scanner_execution.result or {})
        scan_report.setdefault("max_severity", "SAFE")
        scan_report.setdefault("findings", [])
        scan_report.setdefault("analyzers_used", ["basic"])
        analyzer_timings["scanner"] = {
            "status": "skipped" if scan_report.get("scanner_unavailable") else "failed" if scan_report.get("scanner_error") else "completed",
            "duration_seconds": scanner_execution.duration_seconds,
        }
        if scan_report.get("scanner_unavailable"):
            analyzer_timings["scanner"]["reason"] = "scanner_unavailable"

        skillspector_notes: list[str] = []
        if should_run_skillspector:
            execution: AnalyzerExecution = futures["skillspector"].result()
            skillspector_result = execution.result
            analyzer_name = "skillspector:cli"
            analyzer_status = "completed"
            if not skillspector_result.get("available"):
                analyzer_name = "skillspector:unavailable"
                analyzer_status = "skipped"
                skillspector_notes.append("[DEEP_SCAN] 深度扫描不可用，已跳过")
            elif skillspector_result.get("error"):
                analyzer_name = "skillspector:error"
                analyzer_status = "failed"
                skillspector_notes.append(f"[DEEP_SCAN] 深度扫描失败: {skillspector_result['error']}")
            else:
                skillspector_notes.append(
                    "[DEEP_SCAN] "
                    f"risk={skillspector_result.get('risk_severity', 'SAFE')} "
                    f"score={skillspector_result.get('risk_score', '-')}"
                )
            analyzer_timings["skillspector"] = {
                "status": analyzer_status,
                "duration_seconds": execution.duration_seconds,
            }
            scan_report.update({
                "max_severity": _max_severity(
                    str(scan_report.get("max_severity", "SAFE")),
                    str(skillspector_result.get("max_severity", "SAFE")),
                ),
                "findings": [
                    *scan_report.get("findings", []),
                    *skillspector_result.get("findings", []),
                ],
                "analyzers_used": [
                    *scan_report.get("analyzers_used", ["basic"]),
                    analyzer_name,
                ],
                "skillspector_analysis": skillspector_result,
            })

        behavioral_notes: list[str] = []
        behavioral_result: dict[str, Any] | None = None
        behavioral_for_llm: dict[str, Any] | None = None
        if use_behavioral:
            execution = futures["behavioral"].result()
            bundle = execution.result
            behavioral_result = bundle["behavioral_analysis"]
            combined_findings = bundle.get("findings", [])
            behavioral_for_llm = {
                **behavioral_result,
                "findings": combined_findings,
            }
            analyzer_timings["behavioral"] = {
                "status": "completed",
                "duration_seconds": execution.duration_seconds,
            }
            scan_report.update({
                "max_severity": _max_severity(
                    str(scan_report.get("max_severity", "SAFE")),
                    str(bundle.get("max_severity", "SAFE")),
                ),
                "findings": [*scan_report.get("findings", []), *combined_findings],
                "analyzers_used": [
                    *scan_report.get("analyzers_used", ["basic"]),
                    "behavioral:local",
                    "agent-manager-local",
                ],
                "behavioral_analysis": behavioral_result,
                "local_static_analysis": bundle["local_static_analysis"],
            })
            behavioral_notes.append(
                "[BEHAVIORAL] "
                f"scanned {behavioral_result.get('scanned_file_count', 0)} files"
            )
            if combined_findings:
                behavioral_notes.append(
                    f"[BEHAVIORAL] found {len(combined_findings)} suspicious patterns"
                )

        # First deterministic merge decides whether policy adds Sandbox when
        # the user did not explicitly request it.
        scan_report["risk_max_severity"] = _risk_max_severity(
            scan_report.get("findings", []),
            str(scan_report.get("max_severity", "SAFE")),
        )
        interim_risk_level = RiskLevel.from_severity(scan_report["risk_max_severity"])
        scan_report["interim_risk_level"] = interim_risk_level.value
        sandbox_required_by_policy = self.policy.requires_sandbox(interim_risk_level)
        effective_use_sandbox = use_sandbox or sandbox_required_by_policy
        sandbox_notes: list[str] = []
        sandbox_result: dict[str, Any] | None = None
        sandbox_runtime: str | None = None
        if sandbox_required_by_policy:
            sandbox_notes.append(
                f"[SANDBOX] required by policy for risk level {interim_risk_level.value}"
            )
        if not effective_use_sandbox:
            report_analyzer("sandbox", "skipped")
        if effective_use_sandbox:
            if progress_callback:
                progress_callback("sandbox")
            if "sandbox" not in futures:
                futures["sandbox"] = _analyzer_executor.submit(run_analyzer, "sandbox", lambda: _timed_sandbox(skill_path))
            sandbox_execution: SandboxExecution = futures["sandbox"].result()
            sandbox_result = sandbox_execution.result
            sandbox_runtime = sandbox_execution.runtime
            sandbox_notes.extend(sandbox_execution.notes)
            analyzer_timings["sandbox"] = {
                "status": (
                    "failed"
                    if sandbox_result.get("available") is False
                    else "completed" if sandbox_result.get("executed") else "skipped"
                ),
                "duration_seconds": sandbox_execution.duration_seconds,
            }
            scan_report.update({
                "max_severity": _max_severity(
                    str(scan_report.get("max_severity", "SAFE")),
                    sandbox_execution.max_severity,
                ),
                "findings": [
                    *scan_report.get("findings", []),
                    *sandbox_execution.findings,
                ],
                "analyzers_used": [
                    *scan_report.get("analyzers_used", ["basic"]),
                    # 按本次运行方式记录，远程服务和无脚本跳过也保持一致。
                    f"sandbox:{sandbox_runtime or 'unknown'}",
                ],
                "sandbox_analysis": sandbox_result,
            })

        scan_report["risk_max_severity"] = _risk_max_severity(
            scan_report.get("findings", []),
            str(scan_report.get("max_severity", "SAFE")),
        )
        risk_classification = _classify_findings(scan_report.get("findings", []), self.policy)
        pre_llm_risk_level, pre_llm_reason = _risk_from_classification(
            risk_classification,
            effective_judgement_mode,
        )
        scan_report.update({
            "pre_llm_risk_level": pre_llm_risk_level.value,
            "judgement_mode": effective_judgement_mode,
            "risk_classification": risk_classification,
        })

        # Exactly one model call, after every selected deterministic analyzer.
        llm_notes: list[str] = []
        llm_result = None
        if use_llm:
            llm_started = time.monotonic()
            llm_provider_timeout = False
            llm_timeout_seconds = None
            try:
                llm_config = LLMConfig.load()
                # CLI 只请求分析；服务端关闭 AI 时记录未启用，不进入模型调用。
                if not llm_config.enabled:
                    llm_status = "disabled"
                else:
                    if progress_callback:
                        progress_callback("llm")
                    report_analyzer("llm", "running")
                    from .llm import _build_skill_snapshot as _build_snapshot

                    # 实际启用的分析器在调用前记录，失败时仍保留名称。
                    scan_report["analyzers_used"] = [
                        *scan_report.get("analyzers_used", ["basic"]),
                        f"llm:{llm_config.provider}",
                    ]
                    with llm_analysis_timeout(llm_config):
                        analysis_result = analyze_skill_with_llm_single_round(
                            skill_snapshot=_build_snapshot(skill_path, llm_config),
                            rule_results={
                                "max_severity": scan_report.get("max_severity", "SAFE"),
                                "findings": [
                                    finding
                                    for finding in scan_report.get("findings", [])
                                    if finding.get("source") not in {"behavioral", "sandbox"}
                                ],
                            },
                            behavioural_result=behavioral_for_llm,
                            sandbox_result=sandbox_result,
                            config=llm_config,
                        )
                    llm_result = analysis_result
                    scan_report["llm_analysis"] = llm_result.model_dump(mode="json")
                    if llm_result.report:
                        llm_notes.append(f"[LLM] {llm_result.report}")
                    llm_status = "completed"
            except Exception as exc:
                logger.warning("LLM analysis skipped for %s: %s", skill_path, exc)
                llm_notes.append(f"[LLM] analysis skipped: {exc}")
                llm_status = "failed"
                llm_provider_timeout = isinstance(exc, httpx.TimeoutException)
                if isinstance(exc, LLMAnalysisTimeout):
                    llm_timeout_seconds = exc.seconds
            report_analyzer("llm", llm_status)
            analyzer_timings["llm"] = {
                "status": llm_status,
                "duration_seconds": time.monotonic() - llm_started,
            }
            if llm_timeout_seconds is not None:
                analyzer_timings["llm"].update({
                    "reason": "llm_analysis_timeout",
                    "timeout_seconds": llm_timeout_seconds,
                })
            if llm_provider_timeout:
                analyzer_timings["llm"]["reason"] = "llm_provider_timeout"
            if llm_status == "disabled":
                analyzer_timings["llm"]["reason"] = "llm_analysis_disabled"

        llm_risk_level = RiskLevel(llm_result.risk_level) if llm_result else None
        has_blocking_findings = bool(risk_classification.get("blocking_count"))
        final_risk_level, llm_downgraded, llm_downgrade_blocked = reconcile_llm_risk(
            pre_llm_risk_level, llm_risk_level, has_blocking_findings, effective_judgement_mode,
        )
        if llm_downgraded and llm_result:
            downgrade_reason = (
                llm_result.downgrade_reason
                or llm_result.report
                or "LLM judged the risk signal non-exploitable"
            )
            llm_notes.append(
                "[LLM] non-blocking risk downgraded: "
                f"tool risk={pre_llm_risk_level.value}, "
                f"LLM risk={llm_risk_level.value}; reason={downgrade_reason}"
            )
        elif llm_downgrade_blocked:
            llm_notes.append(
                "[LLM] downgrade blocked: "
                f"tool risk={pre_llm_risk_level.value}, "
                f"LLM risk={llm_risk_level.value}; "
                f"reason={'blocking finding present' if has_blocking_findings else 'strict mode'}"
            )

        reconciliation_strategy = (
            "mode_aware_llm_judgement"
            if llm_result
            else "llm_unavailable_deterministic_fallback"
            if use_llm and llm_status != "disabled"
            else "deterministic_policy_merge"
        )
        scan_report["risk_reconciliation"] = {
            "policy_snapshot": {
                "judgement_mode": effective_judgement_mode,
                "risk_classification": dict(self.policy.risk_classification),
                # 拒绝提示保留本次禁止权限清单，避免后续策略变更影响历史说明。
                "blocked_permissions": list(self.policy.blocked_permissions),
            },
            "strategy": reconciliation_strategy,
            "judgement_mode": effective_judgement_mode,
            "pre_llm_reason": pre_llm_reason,
            "pre_llm_risk_level": pre_llm_risk_level.value,
            "llm_risk_level": llm_risk_level.value if llm_risk_level else None,
            "final_risk_level": final_risk_level.value,
            "llm_downgraded": llm_downgraded,
            "llm_downgrade_blocked": llm_downgrade_blocked,
            "downgrade_reason": (
                (llm_result.downgrade_reason or llm_result.report)
                if llm_downgraded and llm_result
                else None
            ),
            "dismissed_findings": llm_result.dismissed_findings if llm_result else [],
            "accepted_findings": llm_result.accepted_findings if llm_result else [],
        }

        if progress_callback:
            progress_callback("finalizing")
        violations = _check_manifest_policy(allowed_tools, license_val, self.policy)
        # 本次准入提示保存编码与参数，供页面及 PDF 按语言展示。
        scan_report["policy_warnings"] = [
            violation.model_dump(mode="json") for violation in violations if not violation.blocking
        ]
        policy_notes = [
            f"{'[BLOCK]' if violation.blocking else '[WARN]'} {violation.rule}: {violation.message}"
            for violation in violations
        ]
        policy_notes.extend(skillspector_notes)
        policy_notes.extend(behavioral_notes)
        policy_notes.extend(llm_notes)
        policy_notes.extend(sandbox_notes)

        findings = scan_report.get("findings", [])
        total_duration = time.monotonic() - started
        scan_report.update({
            "risk_level": final_risk_level.value,
            "analyzer_timings": analyzer_timings,
            "scan_duration_seconds": total_duration,
            "execution_strategy": "parallel_analyzers_single_reconciliation",
        })
        result = VettingResult(
            risk_level=final_risk_level,
            findings_count=len(findings),
            analyzers_used=scan_report.get("analyzers_used", ["basic"]),
            sandbox_triggered=effective_use_sandbox,
            sandbox_required_by_policy=sandbox_required_by_policy,
            sandbox_runtime=sandbox_runtime,
            scan_duration_seconds=total_duration,
            scan_report=scan_report,
            policy_notes=policy_notes,
        )
        return result, violations, name, description, allowed_tools
