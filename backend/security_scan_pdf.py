from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Image, Spacer

from agent_manager.core import scan_report_pdf as layout


def build_security_scan_pdf(detail: dict[str, Any], *, language: str = "zh-CN") -> bytes:
    """Render a decision-oriented assessment from authorized recorded evidence."""
    if language not in {"zh-CN", "en-US"}:
        raise ValueError("unsupported report language")

    def t(zh, en):
        return zh if language == "zh-CN" else en

    task, cases, findings = detail["task"], detail.get("cases", []), detail.get("findings", [])
    llm = task.get("scan_kind") == "llm_redteam_scan"
    infra = task.get("scan_kind") == "ai_infrastructure_vulnerability_scan"
    case_numbers = {c.get("case_id"): i for i, c in enumerate(cases, 1)}
    statuses = {code: t(zh, en) for code, zh, en in [
        ("succeeded", "已完成", "Completed"), ("completed", "已完成", "Completed"),
        ("running", "运行中", "Running"), ("pending", "等待中", "Pending"),
        ("failed", "失败", "Failed"), ("cancelled", "已取消", "Cancelled"),
        ("timed_out", "超时", "Timed out"), ("blocked", "已阻止", "Blocked"),
        ("error", "执行错误", "Execution error"), ("unverified", "未验证", "Unverified"),
        ("risk_signal_detected", "风险信号", "Risk signal"), ("jailbreak_signal_detected", "风险信号", "Risk signal"),
        ("no_risk_observed", "未触发风险判定", "No risk flag"), ("attack_resisted", "未触发风险判定", "No risk flag"),
        ("open", "待处置", "Open"), ("accepted", "已接受", "Accepted"),
        ("risk_accepted", "风险已接受", "Risk accepted"), ("resolved", "已解决", "Resolved"),
        ("false_positive", "误报", "False positive"),
    ]}
    kinds = {code: t(zh, en) for code, zh, en in [
        ("llm_redteam_scan", "大模型红队评估", "LLM Red-Team Assessment"),
        ("ai_infrastructure_vulnerability_scan", "AI 基础设施安全评估", "AI Infrastructure Assessment"),
        ("agent_risk_scan", "智能体安全评估", "Agent Security Assessment"),
        ("mcp_risk_scan", "MCP 安全评估", "MCP Security Assessment"),
        ("dify_asset_inventory", "Dify 资产评估", "Dify Asset Assessment"),
        ("control_plane_validation", "控制面验证", "Control-Plane Validation"),
    ]}
    layout._register_fonts()
    styles = layout._styles(language)
    styles["label"].keepWithNext = True
    styles["body"].fontSize, styles["body"].leading = 10, 16
    styles["h1"].fontSize, styles["h1"].leading = 15, 21
    styles["cover_title"].fontSize, styles["cover_title"].leading = 24, 31
    buffer, story = BytesIO(), []
    heading = t("安全扫描报告", "Security Scan Report")
    document = layout.ScanReportTemplate(buffer, language=language, title=heading, report_heading=heading)

    def paragraph(value, style="body"):
        if value is None or value == "":
            return
        # Bounded source paragraphs flow across pages without oversized table rows.
        for line in str(value).splitlines():
            for offset in range(0, max(1, len(line)), 900):
                story.append(layout._p(line[offset:offset + 900], styles[style]))

    def section(zh, en):
        story.extend(layout._section(t(zh, en), styles))

    def block(zh, en, value):
        if value is not None and value != "":
            paragraph(t(zh, en), "label")
            paragraph(value)

    def table(headers, rows, proportions):
        if rows:
            story.append(layout._data_table(headers, rows, [layout.CONTENT_WIDTH * p for p in proportions], styles))
            story.append(Spacer(1, 4 * mm))

    def when(value):
        if not value:
            return t("未记录", "Not recorded")
        try:
            date = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return date.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(value)

    logo = layout._logo_path()
    if logo.exists():
        image = Image(str(logo), width=40 * mm, height=40 * mm / layout.LOGO_ASPECT_RATIO)
        image.hAlign = "LEFT"
        story.extend([image, Spacer(1, 7 * mm)])
    paragraph(kinds.get(task.get("scan_kind"), heading), "cover_kicker")
    paragraph(heading, "cover_title")
    endpoint = detail.get("target", {}).get("endpoint_url") or next((c.get("request_summary", {}).get("endpoint") for c in cases if c.get("request_summary", {}).get("endpoint")), None)
    paragraph(endpoint or t("目标地址未记录", "Target address not recorded"), "cover_skill")
    story.append(HRFlowable(width="100%", thickness=2, color=layout.BRAND_RED, spaceBefore=3, spaceAfter=12))
    story.append(layout._label_value_table([
        (t("执行状态", "Execution"), statuses.get(task.get("status"), task.get("status"))),
        (t("扫描时间（UTC）", "Scan window (UTC)"), f"{when(task.get('started_at'))} / {when(task.get('completed_at'))}"),
        (t("导出时间（UTC）", "Exported (UTC)"), when(datetime.now(timezone.utc))),
    ], styles))
    section("01  关键结论", "01  Key conclusions")
    risk_cases = {c.get("case_id") for c in cases if c.get("response_summary", {}).get("assessment_status") == "jailbreak_signal_detected" or c.get("assessment_status") == "risk_signal_detected"}
    evaluated = [c for c in cases if c.get("response_summary", {}).get("assessment_status") in {"jailbreak_signal_detected", "attack_resisted"} or c.get("assessment_status") in {"risk_signal_detected", "no_risk_observed", "risk_accepted", "resolved", "false_positive"}]
    rate = f"{len(risk_cases) / len(evaluated):.0%}" if evaluated else t("未计算", "N/A")
    if llm:
        story.append(layout._metrics_table([t("已记录用例", "Recorded"), t("已评估", "Evaluated"), t("风险用例", "Risk cases"), t("样本风险率", "Sample risk rate")], [str(len(cases)), str(len(evaluated)), str(len(risk_cases)), rate], styles, accent_indexes={2, 3}))
        paragraph(t(f"已评估样本中，{len(risk_cases)} 个用例触发风险判定，占比 {rate}。该比例仅描述本次测试样本，不代表模型在所有场景下的越狱成功率。", f"{len(risk_cases)} evaluated cases triggered a risk flag ({rate}). This describes this test sample, not a model-wide jailbreak success rate."))
    else:
        counts = Counter(str(f.get("severity", "")).lower() for f in findings)
        story.append(layout._metrics_table([t("测试对象 / 用例", "Targets / cases"), t("扫描发现", "Findings"), t("严重 / 高风险", "Critical / high")], [str(len(cases)), str(len(findings)), str(counts["critical"] + counts["high"])], styles, accent_indexes={2}))
    if task.get("status") != "succeeded":
        paragraph(t("扫描尚未成功完成；当前结果的覆盖范围可能不完整。", "The scan has not completed successfully; coverage may be incomplete."))
    if infra:
        matched = sum(f.get("evidence", {}).get("rule_match_source") == "ai-infra-guard-version-advisory" for f in findings)
        if matched:
            paragraph(t(f"其中 {matched} 项来自组件版本规则匹配。当前证据不包含漏洞利用验证，需核对实际产品、组件及受影响版本，才能确认适用性。", f"{matched} findings are component-version advisory matches. Exploit verification is not present; confirm the actual product, component, and affected version before establishing applicability."))
    if not findings:
        paragraph(t("未记录安全发现不等于目标安全，结论仅适用于已执行的测试。", "No recorded findings does not establish that the target is safe beyond the tests performed."))
    block("执行异常", "Execution error", task.get("error_message") or task.get("error_code"))
    section("02  覆盖范围与优先事项", "02  Coverage and priorities")
    if llm:
        groups = defaultdict(list)
        for case in cases:
            groups[case.get("request_summary", {}).get("vulnerability") or case.get("category") or t("未分类", "Unclassified")].append(case)
        table([t("测试集 / 类别", "Dataset / category"), t("用例", "Cases"), t("风险", "Risk"), t("未触发 / 未评估", "Other / unevaluated")], [(name, len(rows), sum(c.get("case_id") in risk_cases for c in rows), f"{sum(c in evaluated and c.get('case_id') not in risk_cases for c in rows)} / {sum(c not in evaluated for c in rows)}") for name, rows in groups.items()], [.46, .14, .14, .26])
        paragraph(t("优先人工复核风险用例与原始对话；确认后调整输入、输出防护策略，并使用相同测试集和参数复测。未触发风险判定的样本也可能包含低于评估阈值的风险内容，不能直接标为完全安全。", "Prioritize human review of flagged cases and original conversations. After confirmation, adjust input/output safeguards and retest with the same datasets and parameters. Unflagged cases may still contain concerns below the evaluator's threshold."))
    elif infra:
        table([t("扫描地址", "Endpoint"), t("识别组件", "Component"), t("识别版本", "Version")], [(c.get("request_summary", {}).get("endpoint", "-"), c.get("response_summary", {}).get("component", "-"), c.get("response_summary", {}).get("component_version", "-")) for c in cases], [.55, .25, .2])
        paragraph(t("优先核实严重及高风险规则的产品适用性；确认受影响后依据厂商公告升级或缓解。对服务暴露类提示，检查访问控制和认证配置；扫描地址可达本身不能证明公网暴露或未授权访问。", "First validate product applicability for critical/high advisories, then follow vendor updates or mitigations. For exposure advisories, inspect access controls and authentication; reachability alone does not establish public exposure or unauthorized access."))
    else:
        paragraph(t("按风险等级和处置状态复核以下发现，依据记录的证据确定修复范围，并在修复后复测。", "Review findings by severity and disposition, establish remediation scope from recorded evidence, and retest after changes."))
    section("03  评估详情", "03  Assessment details")
    if llm and any(not (c.get("request_summary", {}).get("prompt") and c.get("response_summary", {}).get("response")) for c in cases):
        paragraph(t("部分用例的导出快照未包含完整测试输入及模型响应；下列评估理由为评估器记录，原始对话需通过平台授权的原始报告入口复核。", "Some cases in this export do not contain the full input and model response. The reasoning below is the evaluator's record; review original conversations through the platform's authorized raw-report view."), "body_muted")
    if not llm:
        for index, finding in enumerate(findings, 1):
            story.append(layout._subsection(f"F{index:02d}  {finding.get('title') or finding.get('finding_code')}", styles))
            evidence = finding.get("evidence") or {}
            version_match = evidence.get("rule_match_source") == "ai-infra-guard-version-advisory"
            story.append(layout._label_value_table([
                (t("严重程度 / 处置", "Severity / disposition"), f"{layout._severity_label(finding.get('severity'), language)} / {statuses.get(finding.get('status'), finding.get('status', '-'))}"),
                (t("证据性质", "Evidence basis"), t("版本公告匹配，适用性待复核", "Version advisory match; applicability requires review") if version_match else t("扫描器记录的观察证据", "Scanner-recorded evidence")),
            ], styles))
            block("风险说明（来源原文）", "Risk description (source)", finding.get("description"))
            for key, zh, en in [("component", "规则组件", "Advisory component"), ("component_version", "识别版本", "Observed version"), ("endpoint", "地址", "Endpoint"), ("cve", "漏洞 / 规则编号", "Advisory ID")]:
                block(zh, en, evidence.get(key))
            for reference in evidence.get("references", []):
                paragraph(reference, "body_muted")
            block("处置意见", "Disposition notes", finding.get("disposition_comment"))
            if not infra:
                for key in ("description", "summary", "reason", "recommendation"):
                    block("证据说明", "Evidence notes", evidence.get(key))
    for index, case in enumerate(cases, 1):
        request, response = case.get("request_summary") or {}, case.get("response_summary") or {}
        title = request.get("vulnerability") if llm else case.get("title")
        story.append(layout._subsection(f"C{index:02d}  {title or t('测试用例', 'Test case')}", styles))
        assessment = response.get("assessment_status") or case.get("assessment_status")
        paragraph(f"{t('评估结果', 'Assessment')}: {statuses.get(assessment, assessment or t('未验证', 'Unverified'))}", "body_muted")
        if llm:
            related = [f for f in findings if f.get("case_id") == case.get("case_id")]
            if related:
                paragraph(" / ".join(f"{layout._severity_label(f.get('severity'), language)} · {statuses.get(f.get('status'), f.get('status') or t('未记录', 'Not recorded'))}" for f in related), "body_muted")
            block("评估理由（评估器原文）", "Evaluator reasoning (source)", response.get("evaluator_reason") or response.get("reason") or t("未记录评估理由。", "No evaluator reasoning recorded."))
            for finding in related:
                block("处置意见", "Disposition notes", finding.get("disposition_comment"))
        if not infra:
            block("测试输入", "Test input", request.get("prompt") or request.get("input"))
            block("目标响应", "Target response", response.get("response") or response.get("output"))
            if not llm:
                block("评估理由", "Evaluator reasoning", response.get("evaluator_reason") or response.get("reason"))
                for check in response.get("checks", []):
                    if isinstance(check, dict):
                        block("检查结果", "Check result", check.get("description"))
        if infra:
            paragraph(t("结果来自上述资产的组件识别及规则匹配，关联发现见本节 F 编号。", "Results derive from component identification and rule matching; see the F-numbered findings above."))
    section("04  技术追溯附录", "04  Technical traceability")
    engine = task.get("engine") or {}
    story.append(layout._label_value_table([
        (t("任务 ID", "Task ID"), task["task_id"]),
        (t("目标 ID", "Target ID"), task.get("target_id")),
        (t("引擎", "Engine"), f"{engine.get('name', '-')} {engine.get('version', '')}"),
        (t("报告 / 判定版本", "Report / criteria version"), f"{task.get('report_template_version') or '-'} / {task.get('decision_criteria_version') or '-'}"),
    ], styles))
    table([t("编号", "Ref"), t("用例 ID", "Case ID")], [(f"C{i:02d}", c.get("case_id")) for i, c in enumerate(cases, 1)], [.12, .88])
    table([t("编号 / 用例", "Ref / case"), t("发现 ID", "Finding ID")], [(f"F{i:02d} / " + (f"C{case_numbers[f['case_id']]:02d}" if f.get("case_id") in case_numbers else "-"), f.get("finding_id")) for i, f in enumerate(findings, 1)], [.22, .78])
    for artifact in detail.get("artifacts", []):
        story.append(layout._label_value_table([
            (t("报告文件 ID", "Report file ID"), artifact.get("artifact_id")),
            ("SHA-256", artifact.get("sha256")),
            (t("大小（字节）", "Size (bytes)"), artifact.get("size_bytes")),
        ], styles))
    document.build(story)
    return buffer.getvalue()
