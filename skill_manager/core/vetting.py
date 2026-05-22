"""
Vetting pipeline — wraps skill-scanner and applies company policy checks.

Produces a VettingResult with risk level, findings summary, and policy notes.
Falls back to a basic static check if skill-scanner is not installed.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .llm import LLMConfig, analyze_skill_with_llm, generate_sandbox_probes_with_llm
from .models import PolicyViolation, RiskLevel, SourceInfo, VettingResult
from .sandbox import (
    build_probe_plan,
    discover_probe_entrypoint,
    extract_markdown_command_probes,
    get_sandbox_runner,
    write_markdown_command_probe_scripts,
)

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
        "pattern": re.compile(r"\b(?:eval|exec)\s*\("),
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


def _run_scanner(skill_path: Path, scanner_policy_name: str) -> dict:
    """Run skill-scanner and return the serialized ScanResult dict."""
    SkillScanner, ScanPolicy = _try_import_scanner()
    if SkillScanner is None:
        logger.warning("skill-scanner not installed — using basic file check only")
        return {}

    try:
        policy = ScanPolicy.from_preset(scanner_policy_name)
    except Exception:
        policy = ScanPolicy.default()

    scanner = SkillScanner(policy=policy)
    result = scanner.scan_skill(str(skill_path))
    return result.to_dict()


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
        post = frontmatter.load(str(skill_md))
        name = post.get("name") or post.get("skill-name") or skill_path.name
        description = post.get("description") or ""
        raw_tools = post.get("allowed-tools") or post.get("allowed_tools") or []
        if isinstance(raw_tools, str):
            raw_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        license_val = post.get("license")
        return str(name), str(description), list(raw_tools), license_val
    except ImportError:
        # Fallback: parse SKILL.md frontmatter without python-frontmatter.
        content = skill_md.read_text(encoding="utf-8")
        name = skill_path.name
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
            if isinstance(payload, dict):
                name = str(payload.get("name") or payload.get("skill-name") or name)
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
        except Exception:
            pass

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
            content = path.read_text(encoding="utf-8")
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


# --------------------------------------------------------------------------- #
# Main vetting entry point                                                      #
# --------------------------------------------------------------------------- #

class VettingPipeline:
    """Orchestrates scanning and policy checks to produce a VettingResult."""

    def __init__(self, policy: "CompanyPolicy"):
        self.policy = policy

    def vet(
        self,
        skill_path: Path,
        source: SourceInfo,
        use_behavioral: bool = False,
        use_llm: bool = False,
        use_sandbox: bool = False,
    ) -> tuple[VettingResult, list[PolicyViolation], str, str, list[str]]:
        """
        Run the full vetting pipeline.

        Returns:
            (VettingResult, violations, name, description, allowed_tools)
        """
        skill_path = Path(skill_path).resolve()

        # 1. Parse manifest
        try:
            name, description, allowed_tools, license_val = _load_manifest(skill_path)
        except ValueError as e:
            raise ValueError(f"Cannot vet skill: {e}") from e

        # 2. Run scanner
        scan_report = _run_scanner(skill_path, self.policy.scanner_policy)
        behavioral_notes: list[str] = []
        if use_behavioral:
            behavioral_result = _run_behavioral_analysis(skill_path)
            scan_report = {
                **scan_report,
                "max_severity": _max_severity(
                    scan_report.get("max_severity", "SAFE"),
                    str(behavioral_result.get("max_severity", "SAFE")),
                ),
                "findings": [
                    *scan_report.get("findings", []),
                    *behavioral_result.get("findings", []),
                ],
                "analyzers_used": [
                    *scan_report.get("analyzers_used", ["basic"]),
                    "behavioral:local",
                ],
                "behavioral_analysis": behavioral_result,
            }
            behavioral_notes.append(
                "[BEHAVIORAL] "
                f"scanned {behavioral_result.get('scanned_file_count', 0)} files"
            )
            if behavioral_result.get("findings"):
                behavioral_notes.append(
                    "[BEHAVIORAL] "
                    f"found {len(behavioral_result['findings'])} suspicious patterns"
                )
        llm_notes: list[str] = []
        if use_llm:
            try:
                llm_config = LLMConfig.load()
                llm_result = analyze_skill_with_llm(skill_path, llm_config)
                llm_findings = [
                    {
                        "severity": finding.severity.upper(),
                        "title": finding.title,
                        "message": finding.message,
                        "file": finding.file,
                        "source": "llm",
                    }
                    for finding in llm_result.findings
                ]
                scan_report = {
                    **scan_report,
                    "max_severity": _max_severity(
                        scan_report.get("max_severity", "SAFE"),
                        llm_result.max_severity,
                    ),
                    "findings": [*scan_report.get("findings", []), *llm_findings],
                    "analyzers_used": [
                        *scan_report.get("analyzers_used", ["basic"]),
                        f"llm:{llm_result.provider}",
                    ],
                    "llm_analysis": llm_result.model_dump(mode="json"),
                }
                if llm_result.summary:
                    llm_notes.append(f"[LLM] {llm_result.summary}")
                llm_notes.extend(f"[LLM] {note}" for note in llm_result.policy_notes)
            except Exception as exc:
                logger.warning("LLM analysis skipped for %s: %s", skill_path, exc)
                llm_notes.append(f"[LLM] analysis skipped: {exc}")

        initial_risk_level = RiskLevel.from_severity(scan_report.get("max_severity", "SAFE"))
        sandbox_required_by_policy = self.policy.requires_sandbox(initial_risk_level)
        effective_use_sandbox = use_sandbox or sandbox_required_by_policy
        sandbox_notes: list[str] = []
        sandbox_runtime: str | None = None
        if sandbox_required_by_policy:
            sandbox_notes.append(
                f"[SANDBOX] required by policy for risk level {initial_risk_level.value}"
            )
        if effective_use_sandbox:
            sandbox_runtime = get_sandbox_runner().config.runtime
            sandbox_skill_path = skill_path
            temp_probe_context: tempfile.TemporaryDirectory[str] | None = None
            markdown_probe_plans = []
            markdown_command_probes = extract_markdown_command_probes(skill_path)
            if markdown_command_probes:
                temp_probe_context = tempfile.TemporaryDirectory(prefix="skill-md-sandbox-")
                sandbox_skill_path = Path(temp_probe_context.name) / "skill"
                shutil.copytree(skill_path, sandbox_skill_path)
                markdown_probe_plans = write_markdown_command_probe_scripts(sandbox_skill_path, markdown_command_probes)
                sandbox_notes.append(f"[SANDBOX] generated {len(markdown_probe_plans)} probes from SKILL.md command blocks")

            entrypoint = discover_probe_entrypoint(sandbox_skill_path)
            if not entrypoint and not markdown_probe_plans:
                sandbox_result = {
                    "executed": False,
                    "runtime": sandbox_runtime,
                    "available": True,
                    "reason": "No supported probe entrypoint or SKILL.md command block found",
                }
                scan_report = {
                    **scan_report,
                    "sandbox_analysis": sandbox_result,
                    "analyzers_used": [
                        *scan_report.get("analyzers_used", ["basic"]),
                        "sandbox:docker",
                    ],
                }
                sandbox_notes.append("[SANDBOX] no supported entrypoint or SKILL.md command block found")
            else:
                try:
                    runner = get_sandbox_runner()
                    sandbox_runtime = runner.config.runtime
                    probe_plan = build_probe_plan(sandbox_skill_path, entrypoint) if entrypoint else markdown_probe_plans[0]
                    probe_cases = []
                    if entrypoint:
                        probe_cases.append({
                            "name": "default",
                            "description": f"default sandbox probe strategy={probe_plan.strategy}",
                            "entrypoint": probe_plan.entrypoint,
                            "args": probe_plan.args,
                            "generated_by": "default",
                        })
                    for index, markdown_plan in enumerate(markdown_probe_plans, start=1):
                        if not any(existing["entrypoint"] == markdown_plan.entrypoint for existing in probe_cases):
                            probe_cases.append({
                                "name": f"skill-md-command-{index}",
                                "description": markdown_plan.description or "SKILL.md command block",
                                "entrypoint": markdown_plan.entrypoint,
                                "args": markdown_plan.args,
                                "generated_by": "skill-md",
                            })
                    llm_probe_plan = None
                    if use_llm:
                        try:
                            llm_probe_plan = generate_sandbox_probes_with_llm(skill_path, probe_plan.entrypoint, LLMConfig.load())
                            for case in llm_probe_plan.probes:
                                case_entrypoint = _normalize_llm_probe_entrypoint(
                                    sandbox_skill_path,
                                    case.entrypoint,
                                    probe_plan.entrypoint,
                                )
                                if not case_entrypoint:
                                    sandbox_notes.append(
                                        f"[SANDBOX] skipped LLM probe {case.name}: invalid entrypoint {case.entrypoint!r}"
                                    )
                                    continue
                                if not any(
                                    existing["entrypoint"] == case_entrypoint and existing["args"] == case.args
                                    for existing in probe_cases
                                ):
                                    probe_cases.append({
                                        "name": case.name,
                                        "description": case.description,
                                        "entrypoint": case_entrypoint,
                                        "args": case.args,
                                        "generated_by": f"llm:{llm_probe_plan.provider}",
                                    })
                            if llm_probe_plan.probes:
                                sandbox_notes.append(f"[SANDBOX] LLM generated {len(llm_probe_plan.probes)} probe cases")
                        except Exception as exc:
                            sandbox_notes.append(f"[SANDBOX] LLM probe generation skipped: {exc}")

                    sandbox_exec_results = []
                    all_sandbox_events = []
                    max_sandbox_severity = "SAFE"
                    representative_exec = None
                    for case in probe_cases:
                        sandbox_exec = runner.run_probe(
                            sandbox_skill_path,
                            entrypoint=case.get("entrypoint") or probe_plan.entrypoint,
                            args=case["args"],
                        )
                        result_payload = sandbox_exec.model_dump(mode="json")
                        result_payload["probe_name"] = case["name"]
                        result_payload["probe_description"] = case["description"]
                        result_payload["probe_entrypoint"] = case.get("entrypoint") or probe_plan.entrypoint
                        result_payload["probe_args"] = case["args"]
                        result_payload["probe_generated_by"] = case["generated_by"]
                        sandbox_exec_results.append(result_payload)
                        for event in sandbox_exec.signals or sandbox_exec.suspicious_events:
                            all_sandbox_events.append((case, event))
                            max_sandbox_severity = _max_severity(max_sandbox_severity, event.severity)
                        if representative_exec is None:
                            representative_exec = sandbox_exec
                        elif _SEVERITY_ORDER.get(sandbox_exec.max_severity.upper(), 0) > _SEVERITY_ORDER.get(representative_exec.max_severity.upper(), 0):
                            representative_exec = sandbox_exec

                    sandbox_exec = representative_exec
                    sandbox_result = sandbox_exec.model_dump(mode="json") if sandbox_exec else {
                        "executed": False,
                        "runtime": sandbox_runtime,
                        "reason": "No sandbox probe executed",
                    }
                    sandbox_result["probe_strategy"] = "multi-case" if len(probe_cases) > 1 else probe_plan.strategy
                    sandbox_result["probe_args"] = probe_cases[0]["args"]
                    sandbox_result["probe_cases"] = probe_cases
                    sandbox_result["probe_results"] = sandbox_exec_results
                    sandbox_result["llm_probe_plan"] = llm_probe_plan.model_dump(mode="json") if llm_probe_plan else None
                    sandbox_events = [
                        {
                            "severity": event.severity,
                            "title": event.message,
                            "message": event.message,
                            "file": case.get("entrypoint") or probe_plan.entrypoint,
                            "source": "sandbox",
                            "probe": case["name"],
                            "probe_entrypoint": case.get("entrypoint") or probe_plan.entrypoint,
                            "category": event.category,
                            "evidence": event.evidence,
                        }
                        for case, event in all_sandbox_events
                    ]

                    scan_report = {
                        **scan_report,
                        "max_severity": _max_severity(
                            scan_report.get("max_severity", "SAFE"),
                            max_sandbox_severity,
                        ),
                        "findings": [
                            *scan_report.get("findings", []),
                            *sandbox_events,
                        ],
                        "analyzers_used": [
                            *scan_report.get("analyzers_used", ["basic"]),
                            "sandbox:docker",
                        ],
                        "sandbox_analysis": sandbox_result,
                    }
                    if sandbox_exec.executed:
                        sandbox_notes.append(
                            f"[SANDBOX] executed {entrypoint} strategy={sandbox_result['probe_strategy']} "
                            f"cases={len(probe_cases)} "
                            f"exit_code={sandbox_exec.exit_code} timeout={sandbox_exec.timed_out} "
                            f"duration_ms={sandbox_exec.duration_ms}"
                        )
                    else:
                        sandbox_notes.append(f"[SANDBOX] skipped: {sandbox_exec.reason or 'not executed'}")
                    for case, event in all_sandbox_events:
                        sandbox_notes.append(f"[SANDBOX] {case['name']} {event.category}: {event.message}")
                except Exception as exc:
                    logger.warning("Sandbox analysis skipped for %s: %s", skill_path, exc)
                    sandbox_result = {
                        "executed": False,
                        "runtime": sandbox_runtime or "unknown",
                        "available": False,
                        "entrypoint": entrypoint,
                        "reason": f"Sandbox analysis skipped: {exc}",
                    }
                    scan_report = {
                        **scan_report,
                        "sandbox_analysis": sandbox_result,
                        "analyzers_used": [
                            *scan_report.get("analyzers_used", ["basic"]),
                            "sandbox:docker",
                        ],
                    }
                    sandbox_notes.append(f"[SANDBOX] analysis skipped: {exc}")
                finally:
                    if temp_probe_context:
                        temp_probe_context.cleanup()

        # 3. Derive risk level
        max_severity = scan_report.get("max_severity", "SAFE")
        risk_level = RiskLevel.from_severity(max_severity)

        findings = scan_report.get("findings", [])
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev = f.get("severity", "INFO").lower()
            if sev in counts:
                counts[sev] += 1

        # 4. Policy checks
        violations = _check_manifest_policy(allowed_tools, license_val, self.policy)

        policy_notes: list[str] = []
        for v in violations:
            prefix = "[BLOCK]" if v.blocking else "[WARN]"
            policy_notes.append(f"{prefix} {v.rule}: {v.message}")
        policy_notes.extend(behavioral_notes)
        policy_notes.extend(llm_notes)
        policy_notes.extend(sandbox_notes)

        # 5. Build result
        result = VettingResult(
            risk_level=risk_level,
            max_severity=max_severity,
            findings_count=len(findings),
            critical_count=counts["critical"],
            high_count=counts["high"],
            medium_count=counts["medium"],
            low_count=counts["low"],
            analyzers_used=scan_report.get("analyzers_used", ["basic"]),
            sandbox_triggered=effective_use_sandbox,
            sandbox_required_by_policy=sandbox_required_by_policy,
            sandbox_runtime=sandbox_runtime,
            scan_duration_seconds=scan_report.get("scan_duration_seconds", 0.0),
            scan_report=scan_report,
            policy_notes=policy_notes,
        )

        return result, violations, name, description, allowed_tools
