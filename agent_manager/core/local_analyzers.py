"""Local static analyzers for agent skill safety signals."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
}

TEXT_RULES = (
    ("P1", "HIGH", "Prompt Injection", "Instruction Override", re.compile(r"ignore (?:all )?(?:previous|prior|above|system) instructions?", re.I), "Skill content asks the agent to ignore higher-priority instructions."),
    ("P6", "HIGH", "System Prompt Leakage", "System Prompt Disclosure", re.compile(r"(?:reveal|print|show|dump|exfiltrate).{0,40}system prompt", re.I), "Skill content attempts to disclose the system prompt."),
    ("TP1", "HIGH", "Tool Poisoning", "Hidden Instructions", re.compile(r"<!--[\s\S]{0,300}(?:ignore|send|exfiltrate|system prompt)[\s\S]{0,300}-->", re.I), "Hidden metadata contains agent-facing instructions."),
    ("E1", "MEDIUM", "Data Exfiltration", "External Transmission", re.compile(r"\b(?:requests\.(?:post|put)|httpx\.(?:post|put)|fetch)\s*\(|https?://", re.I), "Code or instructions reference external transmission."),
    ("E2", "HIGH", "Data Exfiltration", "Environment Variable Harvesting", re.compile(r"\b(?:os\.environ|process\.env|env\s*\|)", re.I), "Code accesses environment variables that may contain secrets."),
    ("E3", "MEDIUM", "Data Exfiltration", "Credential File Access", re.compile(r"(?:\.aws/credentials|id_rsa|id_dsa|\.ssh/config|\.env\b|/etc/shadow|/etc/passwd)", re.I), "Code or instructions reference sensitive credential files."),
    ("SC2", "HIGH", "Supply Chain", "External Script Fetching", re.compile(r"(?:curl|wget)[^\n|>]*(?:\||>)\s*(?:sh|bash|zsh)", re.I), "Installer downloads remote content and executes it directly."),
    ("SC3", "HIGH", "Supply Chain", "Obfuscated Code", re.compile(r"(?:base64\.(?:b64decode|urlsafe_b64decode)|pickle\.loads|marshal\.loads)", re.I), "Code decodes or deserializes potentially executable payloads."),
    ("TP2", "HIGH", "Tool Poisoning", "Unicode Deception", re.compile(r"[\u202a-\u202e\u2066-\u2069\u200b\u200c\u200d\ufeff]|\\u(?:202a|202b|202c|202d|202e|2066|2067|2068|2069|200b|200c|200d|feff)", re.I), "Metadata contains direction override or zero-width characters."),
    ("LP2", "MEDIUM", "MCP Least Privilege", "Wildcard Permission", re.compile(r'["\'](?:\*|all|full|any)["\']', re.I), "Permission metadata contains wildcard-like access."),
)

_SEVERITY_ORDER = {
    "SAFE": 0,
    "INFO": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4,
    "CRITICAL": 5,
}


def run_local_static_analysis(skill_path: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned_files: list[str] = []
    root = Path(skill_path).resolve()

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts) or "__pycache__" in rel_parts:
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        rel_path = path.relative_to(root).as_posix()
        scanned_files.append(rel_path)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        if path.suffix.lower() == ".py":
            findings.extend(_analyze_python_ast(content, rel_path))
        findings.extend(_analyze_text_rules(content, rel_path))

    max_severity = "SAFE"
    for finding in findings:
        max_severity = _max_severity(max_severity, str(finding["severity"]))
    return {
        "max_severity": max_severity,
        "findings": findings,
        "scanned_files": scanned_files,
        "scanned_file_count": len(scanned_files),
    }


def _max_severity(*values: str) -> str:
    resolved = "SAFE"
    resolved_rank = -1
    for value in values:
        rank = _SEVERITY_ORDER.get((value or "SAFE").upper(), 0)
        if rank > resolved_rank:
            resolved_rank = rank
            resolved = (value or "SAFE").upper()
    return resolved


def _finding(
    *,
    rule: str,
    severity: str,
    category: str,
    title: str,
    message: str,
    file: str,
    line: int,
    evidence: str,
    remediation: str,
) -> dict[str, Any]:
    return {
        "source": "agent-manager-local",
        "rule": rule,
        "rule_id": rule,
        "severity": severity,
        "category": category,
        "title": title,
        "message": message,
        "file": file,
        "line": line,
        "evidence": evidence[:500],
        "remediation": remediation,
    }


def _analyze_text_rules(content: str, rel_path: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for rule, severity, category, title, pattern, message in TEXT_RULES:
        match = pattern.search(content)
        if not match:
            continue
        line = content[: match.start()].count("\n") + 1
        findings.append(_finding(
            rule=rule,
            severity=severity,
            category=category,
            title=title,
            message=f"{message} 文件: {rel_path}:{line}",
            file=rel_path,
            line=line,
            evidence=match.group(0),
            remediation="Review the matched content and remove or constrain unsafe behavior.",
        ))
    return findings


def _analyze_python_ast(content: str, rel_path: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name == "exec":
            findings.append(_ast_finding("AST1", "CRITICAL", "exec() Call", name, rel_path, node))
        elif name == "eval":
            findings.append(_ast_finding("AST2", "HIGH", "eval() Call", name, rel_path, node))
        elif name == "__import__":
            findings.append(_ast_finding("AST3", "HIGH", "Dynamic Import", name, rel_path, node))
        elif name and name.startswith("subprocess."):
            findings.append(_ast_finding("AST4", "HIGH", "subprocess Call", name, rel_path, node))
        elif name in {"os.system", "os.popen", "os.execv", "os.execve", "os.spawnv"}:
            findings.append(_ast_finding("AST5", "HIGH", "os command execution", name, rel_path, node))
        elif name == "compile":
            findings.append(_ast_finding("AST6", "MEDIUM", "compile() Call", name, rel_path, node))
        elif name == "getattr" and len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):
            findings.append(_ast_finding("AST7", "MEDIUM", "Dynamic getattr()", name, rel_path, node))
    return findings


def _ast_finding(rule: str, severity: str, title: str, name: str, rel_path: str, node: ast.AST) -> dict[str, Any]:
    return _finding(
        rule=rule,
        severity=severity,
        category="Behavioral AST",
        title=title,
        message=f"Python AST detected dangerous call {name!r}. 文件: {rel_path}:{getattr(node, 'lineno', 1)}",
        file=rel_path,
        line=int(getattr(node, "lineno", 1)),
        evidence=name,
        remediation="Avoid dynamic code or shell execution unless it is tightly scoped and reviewed.",
    )


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _call_name(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return None
