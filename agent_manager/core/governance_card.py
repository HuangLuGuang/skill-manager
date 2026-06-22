"""Deterministic governance skill card generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RegistryEntry
from .registry import Registry


_STATUS_LABELS = {
    "PENDING": "PENDING（分析中）",
    "VETTED": "VETTED（待审核）",
    "APPROVED": "APPROVED（已批准）",
    "DEPLOYED": "DEPLOYED（已部署）",
    "REJECTED": "REJECTED（已拒绝）",
    "RETIRED": "RETIRED（已退役）",
}
_RISK_LABELS = {
    "benign": "benign（安全）",
    "suspicious": "suspicious（可疑）",
    "malicious": "malicious（恶意）",
}
_ORIGIN_LABELS = {
    "local": "本地",
    "github": "GitHub",
    "clawhub": "ClawHub",
    "internal": "内部",
    "unknown": "未知",
}
_EVENT_LABELS = {
    "skill_submitted": "技能已提交",
    "skill_processing_completed": "后台分析完成",
    "skill_queued_for_review": "已进入人工审核",
    "skill_vetted": "安全检测完成",
    "skill_approved": "技能已批准",
    "skill_rejected": "技能已拒绝",
    "skill_deployed": "技能已部署",
    "skill_retired": "技能已退役",
    "skill_signature_verified": "签名校验通过",
    "skill_tamper_detected": "检测到内容篡改",
    "skill_load_allowed": "允许运行时加载",
    "skill_load_blocked": "阻止运行时加载",
    "tool_invoked": "工具已调用",
    "tool_blocked": "工具调用被阻止",
}


def governance_card_path(data_dir: str | Path, skill_id: str) -> Path:
    return Path(data_dir) / "skill_cards" / f"{skill_id}.md"


def write_governance_card(entry: RegistryEntry, registry: Registry) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    content = generate_governance_card(entry, registry, generated_at=generated_at)
    path = governance_card_path(registry.data_dir, entry.skill_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {
        "skill_id": entry.skill_id,
        "skill_name": entry.name,
        "generated_at": generated_at,
        "path": str(path),
        "content": content,
    }


def read_or_write_governance_card(entry: RegistryEntry, registry: Registry) -> dict[str, Any]:
    return write_governance_card(entry, registry)


def generate_governance_card(
    entry: RegistryEntry,
    registry: Registry,
    *,
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    vetting = entry.vetting
    scan_report = vetting.scan_report if vetting else {}
    findings = list(scan_report.get("findings") or [])
    top_findings = sorted(
        findings,
        key=lambda item: _severity_rank(str(item.get("severity") or "LOW")),
        reverse=True,
    )[:10]
    audit_events = registry.read_audit(skill_id=entry.skill_id, limit=20)

    lines = [
        f"# Governance Card（治理卡片）：{entry.name}",
        "",
        f"生成时间：{generated_at}",
        "",
        "## 基础信息",
        "",
        f"- Skill ID：`{entry.skill_id}`",
        f"- 名称：`{entry.name}`",
        f"- 描述：{entry.description or '-'}",
        f"- 状态：`{_status_label(entry.status.value)}`",
        f"- 风险等级：`{_risk_label(entry.risk_level.value if entry.risk_level else None)}`",
        f"- 来源：`{_ORIGIN_LABELS.get(entry.source.origin.value, entry.source.origin.value)}`",
        f"- 作者：{entry.source.author or '-'}",
        f"- 提交时间：{entry.submitted_at.isoformat()}",
        "",
        "## 内容身份",
        "",
        f"- 内容指纹：`{entry.content_fingerprint or '-'}`",
        f"- 扫描缓存 Key：`{entry.scan_cache_key or '-'}`",
        f"- 是否已签名：{'是' if entry.signature else '否'}",
        f"- 签名预览：`{entry.signature[:24] + '...' if entry.signature else '-'}`",
        "",
        "## 权限与策略",
        "",
        f"- 声明工具：{', '.join(entry.allowed_tools) if entry.allowed_tools else '无'}",
        f"- 声明工具是否有效：{'是' if entry.declared_tools_valid else '否'}",
        "",
        "## 检测摘要",
        "",
        f"- 命中项数量：{vetting.findings_count if vetting else 0}",
        f"- 使用的分析器：{', '.join(vetting.analyzers_used) if vetting and vetting.analyzers_used else '-'}",
        f"- 最高严重级别：`{_severity_label(scan_report.get('max_severity'))}`",
        f"- LLM 分析前风险：`{_risk_label(scan_report.get('pre_llm_risk_level'))}`",
        f"- 最终风险：`{_risk_label(scan_report.get('risk_level', entry.risk_level.value if entry.risk_level else None))}`",
        f"- 是否触发 Sandbox：{'是' if vetting and vetting.sandbox_triggered else '否'}",
        "",
        "## 判断依据",
        "",
    ]
    rationale_items = _rationale_items(top_findings, vetting.policy_notes if vetting else [])
    if rationale_items:
        lines.extend([f"- {item}" for item in rationale_items])
    else:
        lines.append("- 未记录到高风险判断依据。")

    lines.extend([
        "",
        "## 高风险命中项",
        "",
    ])
    if top_findings:
        for finding in top_findings:
            location = _format_location(finding)
            lines.extend([
                f"- `{_severity_label(finding.get('severity', 'LOW'))}` `{finding.get('source', 'rule')}` `{finding.get('rule') or finding.get('rule_id') or '-'}` {finding.get('title') or finding.get('message') or '-'}",
                f"  - 位置：{location}",
                f"  - 证据：{_inline(finding.get('evidence') or finding.get('code_snippet') or finding.get('finding') or '-')}",
                f"  - 修复建议：{finding.get('remediation') or '-'}",
            ])
    else:
        lines.append("- 未记录到命中项。")

    lines.extend([
        "",
        "## 人工审核",
        "",
        f"- 批准人：{entry.approved_by or '-'}",
        f"- 批准备注：{entry.approval_note or '-'}",
        f"- 拒绝原因：{entry.rejection_reason or '-'}",
        "",
        "## 审计记录",
        "",
    ])
    if audit_events:
        for event in audit_events:
            lines.append(
                f"- {event.timestamp.isoformat()} `{_EVENT_LABELS.get(event.event_type, event.event_type)}` "
                f"操作人：{event.actor or '-'}"
            )
    else:
        lines.append("- 暂无审计记录。")

    lines.extend([
        "",
        "## 能力边界",
        "",
        "- 静态分析可能无法发现仅在运行时分支或二进制载荷中出现的行为。",
        "- Sandbox 观察结果仅覆盖实际执行到的探测路径。",
        "- LLM 分析仅作为辅助信号，不能替代对高影响命中项的人工审核。",
        "",
    ])
    return "\n".join(lines)


def _severity_rank(value: str) -> int:
    return {"CRITICAL": 5, "EXTREME": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1, "SAFE": 0}.get(value.upper(), 0)


def _format_location(finding: dict[str, Any]) -> str:
    file = finding.get("file") or "-"
    line = finding.get("line") or finding.get("start_line")
    return f"{file}:{line}" if line else str(file)


def _inline(value: Any) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > 240:
        return text[:237] + "..."
    return text


def _extract_generated_at(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("生成时间："):
            return line.split("：", 1)[1].strip()
        if line.startswith("Generated at:"):
            return line.split(":", 1)[1].strip()
    return None


def _status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value or "-")


def _risk_label(value: Any) -> str:
    text = str(value or "-")
    return _RISK_LABELS.get(text.lower(), text)


def _rationale_items(findings: list[dict[str, Any]], policy_notes: list[str]) -> list[str]:
    items: list[str] = []
    for finding in findings[:3]:
        severity = _severity_label(finding.get("severity", "LOW"))
        source = finding.get("source", "rule")
        title = finding.get("title") or finding.get("message") or finding.get("rule") or "命中风险规则"
        items.append(f"`{severity}` `{source}` {title}")
    for note in policy_notes[:2]:
        if note and note not in items:
            items.append(note)
    return items[:5]


def _severity_label(value: Any) -> str:
    text = str(value or "-").upper()
    return {
        "SAFE": "安全",
        "INFO": "提示",
        "LOW": "低",
        "MEDIUM": "中",
        "HIGH": "高",
        "CRITICAL": "严重",
        "EXTREME": "极高",
    }.get(text, text)
