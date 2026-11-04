"""Local static analyzers for agent skill safety signals."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .text_reader import read_text_fallback

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".zsh",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
}
_LICENSE_FILENAMES = {"license", "license.txt", "notice", "notice.txt", "copying"}

TEXT_RULES = (
    ("P1", "HIGH", "提示词注入", "覆盖上级指令", re.compile(r"ignore (?:all )?(?:previous|prior|above|system) instructions?", re.I), "Skill 内容要求忽略上级或系统指令。"),
    ("P6", "HIGH", "系统提示词泄露", "披露系统提示词", re.compile(r"(?:reveal|print|show|dump|exfiltrate).{0,40}system prompt", re.I), "Skill 内容尝试泄露系统提示词。"),
    ("MP1", "MEDIUM", "记忆投毒", "持久化记忆指令", re.compile(r"^(?:store|save|persist|retain|keep)\s+(?:this|the\s+following)(?:\s+(?:instruction|rule))?\s+(?:in|to)\s+(?:your\s+)?(?:long[- ]term\s+)?memory\b|^(?:请)?(?:将|把)[^\n。]{0,40}(?:写入|存入|保存到)[^\n。]{0,10}(?:长期记忆|持久记忆)", re.I | re.M), "Skill 内容要求将指令写入持久化记忆，需复核其对后续任务的影响。"),
    ("TP1", "HIGH", "工具投毒", "隐藏指令", re.compile(r"<!--[\s\S]{0,300}(?:ignore|send|exfiltrate|system prompt)[\s\S]{0,300}-->", re.I), "隐藏元数据中包含面向 Agent 的可疑指令。"),
    ("E1", "MEDIUM", "数据外传", "外部传输", re.compile(r"\b(?:requests\.(?:post|put)|httpx\.(?:post|put)|fetch)\s*\(", re.I), "代码或指令引用了可能向外部发送数据的调用。"),
    ("E2", "HIGH", "数据外传", "环境变量读取", re.compile(r"\b(?:os\.environ|process\.env|env\s*\|)", re.I), "代码读取环境变量，可能接触密钥或敏感配置。"),
    ("E3", "MEDIUM", "数据外传", "凭据文件访问", re.compile(r"(?:\.aws/credentials|id_rsa|id_dsa|\.ssh/config|\.env\b|/etc/shadow|/etc/passwd)", re.I), "代码或指令引用了常见敏感凭据文件。"),
    ("SC2", "HIGH", "供应链风险", "下载后执行", re.compile(r"(?:curl|wget)[^\n|>]*(?:\||>)\s*(?:sh|bash|zsh)", re.I), "安装脚本下载远程内容后直接交给 shell 执行。"),
    ("SC3", "HIGH", "供应链风险", "混淆或反序列化载荷", re.compile(r"(?:base64\.(?:b64decode|urlsafe_b64decode)|pickle\.loads|marshal\.loads)", re.I), "代码解码或反序列化可能执行的载荷。"),
    ("TP2", "HIGH", "工具投毒", "Unicode 欺骗字符", re.compile(r"[\u202a-\u202e\u2066-\u2069\u200b\u200c\u200d\ufeff]|\\u(?:202a|202b|202c|202d|202e|2066|2067|2068|2069|200b|200c|200d|feff)", re.I), "元数据中包含方向覆盖或零宽字符，可能隐藏真实内容。"),
    ("LP2", "MEDIUM", "最小权限", "通配权限", re.compile(r'["\'](?:\*|all|full|any)["\']', re.I), "权限声明包含通配或过宽权限。"),
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
            content, _encoding = read_text_fallback(path)
        except Exception:
            continue

        if path.suffix.lower() == ".py":
            findings.extend(_analyze_python_ast(content, rel_path))
        if not _is_license_file(rel_path):
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
            remediation="请复核命中内容，删除或收紧不必要的高风险行为。",
        ))
    return findings


def _is_license_file(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    return name in _LICENSE_FILENAMES or name.endswith("-ofl.txt")


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
        message=f"Python AST 检测到危险调用 {name!r}。文件: {rel_path}:{getattr(node, 'lineno', 1)}",
        file=rel_path,
        line=int(getattr(node, "lineno", 1)),
        evidence=name,
        remediation="除非范围明确且经过审核，否则避免动态代码或 shell 执行。",
    )


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _call_name(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return None
