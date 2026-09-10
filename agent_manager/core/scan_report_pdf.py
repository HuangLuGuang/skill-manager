"""Generate branded PDF documents for one concrete Skill scan result."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from agent_manager.core.models import AuditEvent, RegistryEntry, ScanRun

BRAND_RED = colors.HexColor("#DC0012")
BRAND_DARK = colors.HexColor("#303946")
INK = colors.HexColor("#202020")
MUTED = colors.HexColor("#62666D")
WEAK = colors.HexColor("#92969C")
PANEL = colors.HexColor("#F5F6F7")
LIGHT_RED = colors.HexColor("#FDEDEE")
LINE = colors.HexColor("#D9DCE0")
WHITE = colors.white
GREEN = colors.HexColor("#257942")
LIGHT_GREEN = colors.HexColor("#EAF6EE")
AMBER = colors.HexColor("#B45F06")
LIGHT_AMBER = colors.HexColor("#FFF4E5")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 18 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 29 * mm
BOTTOM_MARGIN = 18 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
LOGO_ASPECT_RATIO = 268 / 71

MAX_FINDINGS = 100
MAX_AUDIT_EVENTS = 30
MAX_LOG_CHARS = 3000

_REDACTION_PATTERNS = (
    (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret)\b\s*[:=]\s*([^\s,;&]+)"),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)\b(authorization)\b\s*[:=]\s*(?!Bearer\b)([^\s,;&]+)"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)([?&](?:access_token|token|api_key|key|secret)=)[^&#\s]+"), r"\1[REDACTED]"),
)
_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")

_ENGLISH_FINDING_COPY: dict[str, tuple[str, str, str]] = {
    "P1": (
        "Prompt injection",
        "The Skill content attempts to override higher-priority or system instructions.",
        "Remove the instruction override and keep the Skill aligned with higher-priority controls.",
    ),
    "P6": (
        "System prompt disclosure",
        "The Skill content attempts to reveal or exfiltrate the system prompt.",
        "Remove prompt-disclosure instructions and prevent access to hidden system context.",
    ),
    "TP1": (
        "Hidden instruction in metadata",
        "Hidden metadata contains suspicious instructions directed at the Agent.",
        "Remove hidden instructions and keep security-relevant behavior explicit and reviewable.",
    ),
    "E1": (
        "Potential outbound data transfer",
        "The code or instructions reference an operation that may send data externally.",
        "Verify the destination and data scope, and restrict outbound transfer to approved use cases.",
    ),
    "E2": (
        "Environment variable access",
        "The code reads environment variables and may access credentials or sensitive configuration.",
        "Limit environment access to required values and prevent secrets from being logged or transmitted.",
    ),
    "E3": (
        "Credential file access",
        "The code or instructions reference a common credential or sensitive system file.",
        "Remove unnecessary credential access and apply least-privilege file permissions.",
    ),
    "SC2": (
        "Download-and-execute pattern",
        "An installation command downloads remote content and passes it directly to a shell.",
        "Pin and verify downloaded artifacts before execution; do not pipe remote content directly to a shell.",
    ),
    "SC3": (
        "Encoded or deserialized payload",
        "The code decodes or deserializes a payload that may be executed.",
        "Validate the payload source and format, and avoid executing untrusted decoded content.",
    ),
    "TP2": (
        "Deceptive Unicode characters",
        "Metadata contains direction-control or zero-width characters that may conceal its true content.",
        "Remove deceptive Unicode characters and review the normalized text.",
    ),
    "LP2": (
        "Overly broad permission",
        "The permission declaration contains a wildcard or unnecessarily broad access.",
        "Replace broad permissions with the minimum explicit permissions required.",
    ),
    "SUBPROCESS_SHELL_TRUE": (
        "shell=True subprocess call",
        "The script executes a subprocess with shell=True, which can enable command injection or privilege abuse.",
        "Avoid shell=True and pass validated arguments as an explicit argument list.",
    ),
    "OS_COMMAND_EXECUTION": (
        "Direct operating-system command execution",
        "The script calls os.system or os.popen, making command execution harder to constrain and audit.",
        "Use a constrained subprocess call with validated arguments and no shell expansion.",
    ),
    "DYNAMIC_CODE_EXECUTION": (
        "Dynamic code execution",
        "The script uses eval or exec and may execute dynamically constructed code.",
        "Remove dynamic execution or strictly validate and isolate every possible input.",
    ),
    "DOWNLOAD_AND_EXECUTE": (
        "Download-and-execute pattern",
        "The script combines curl or wget with a shell pipeline and may execute remote content directly.",
        "Download to a controlled location, verify integrity and provenance, then execute only approved content.",
    ),
    "CREDENTIAL_FILE_ACCESS": (
        "Sensitive credential file access",
        "The script references a common credential path and may access sensitive local configuration.",
        "Remove unnecessary access and apply least privilege to required credential files.",
    ),
    "ENCODED_PAYLOAD_EXECUTION": (
        "Encoded payload or deserialization risk",
        "The script decodes or deserializes content that may lead to code execution.",
        "Do not execute untrusted decoded or deserialized input; validate provenance and structure first.",
    ),
}


def _font_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansSC-Regular.ttf"


def _register_fonts() -> None:
    """Register the bundled OFL font so generated PDFs are self-contained."""
    font_path = _font_path()
    if not font_path.exists():
        raise RuntimeError(f"Bundled PDF font is missing: {font_path}")
    if "NotoSansSC" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NotoSansSC", str(font_path)))
    pdfmetrics.registerFontFamily(
        "NotoSansSC",
        normal="NotoSansSC",
        bold="NotoSansSC",
        italic="NotoSansSC",
        boldItalic="NotoSansSC",
    )


FONT = "NotoSansSC"


def _logo_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "ruishu_logo_dark.png"


def _safe_text(value: Any, *, limit: int | None = None) -> str:
    if value is None or value == "":
        text = "-"
    elif isinstance(value, bool):
        text = "True" if value else "False"
    elif isinstance(value, (list, tuple, set)):
        text = ", ".join(_safe_text(item) for item in value) or "-"
    elif isinstance(value, dict):
        text = ", ".join(f"{key}: {_safe_text(item)}" for key, item in value.items()) or "-"
    else:
        text = str(value)
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    if limit is not None and len(text) > limit:
        text = f"{text[:limit]}... [TRUNCATED]"
    return text


def _contains_cjk(value: Any) -> bool:
    return bool(_CJK_PATTERN.search(_safe_text(value)))


def _localized_system_text(value: Any, language: str, english_fallback: str) -> Any:
    """Localize generated prose while preserving already-English values and raw evidence."""
    if language == "zh-CN" or not _contains_cjk(value):
        return value
    return english_fallback


def _localized_finding_copy(finding: dict[str, Any], field: str, language: str) -> Any:
    if field == "title":
        original = finding.get("title") or finding.get("message") or finding.get("rule") or "Finding"
        copy_index = 0
    elif field == "description":
        original = finding.get("explanation") or finding.get("description") or finding.get("message")
        copy_index = 1
    else:
        original = finding.get("remediation") or finding.get("recommendation") or finding.get("suggestion")
        copy_index = 2
    if language == "zh-CN" or not _contains_cjk(original):
        return original

    rule = str(finding.get("rule") or finding.get("rule_id") or "unknown").upper()
    translated = _ENGLISH_FINDING_COPY.get(rule)
    if translated:
        return translated[copy_index]
    generic = (
        f"Security finding ({rule})",
        f"The analyzer reported a security-relevant condition for rule {rule}. Review the evidence and source location.",
        "Review the matched content and remove or constrain unnecessary high-risk behavior.",
    )
    return generic[copy_index]


def _localized_policy_note(note: Any, language: str) -> Any:
    if language == "zh-CN" or not _contains_cjk(note):
        return note
    text = str(note)
    prefix_match = re.match(r"\s*(\[[A-Z_]+\])", text)
    prefix = f"{prefix_match.group(1)} " if prefix_match else ""
    if "DEEP_SCAN" in text:
        message = "Deep scan was unavailable, skipped, or failed. Review the analyzer status for details."
    elif "SANDBOX" in text:
        message = "Sandbox execution produced a system note. Review the Sandbox details in this report."
    elif "LLM" in text:
        message = "LLM analysis produced an original-language note. Review the structured LLM decision in this report."
    elif "BEHAVIORAL" in text:
        message = "Behavioral analysis produced a system note. Review the related findings in this report."
    else:
        message = "A system-generated policy note is available in the original scan record."
    return f"{prefix}{message}"


def _localized_sandbox_summary(sandbox: dict[str, Any], language: str) -> Any:
    summary = sandbox.get("summary")
    if language == "zh-CN" or not _contains_cjk(summary):
        return summary
    if not sandbox.get("executed", True):
        return "Sandbox was not executed. Review runtime availability and the recorded status."
    signals = sandbox.get("signals") or sandbox.get("suspicious_events") or []
    if not isinstance(signals, list) or not signals:
        return "Sandbox executed without explicit runtime risk signals."
    categories: list[str] = []
    for signal in signals:
        category = str(signal.get("category") or "runtime") if isinstance(signal, dict) else "runtime"
        if _contains_cjk(category):
            category = "runtime"
        if category not in categories:
            categories.append(category)
    return f"Sandbox detected {len(signals)} runtime risk signal(s), primarily involving {', '.join(categories[:3])}."


def _localized_sandbox_signal(signal: dict[str, Any], language: str) -> Any:
    message = signal.get("message") or "-"
    if language == "zh-CN" or not _contains_cjk(message):
        return message
    category = str(signal.get("category") or "runtime").lower()
    fallbacks = {
        "timeout": "Execution timed out; the process may be blocked, looping, or consuming excessive resources.",
        "probe_input": "The referenced sample input was unavailable, so the probe could not complete.",
        "network": "The runtime attempted network activity that requires review.",
        "filesystem": "The runtime performed filesystem activity that requires review.",
        "process": "The runtime created or invoked a process that requires review.",
        "dependency": "A runtime dependency issue affected execution coverage.",
    }
    return fallbacks.get(category, "The Sandbox recorded a runtime signal that requires review.")


def _xml(value: Any, *, limit: int | None = None) -> str:
    return html.escape(_safe_text(value, limit=limit)).replace("\n", "<br/>")


def _iso(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _risk_label(value: Any, language: str) -> str:
    normalized = str(_enum_value(value) or "pending").lower()
    zh = {"benign": "安全", "suspicious": "可疑", "malicious": "恶意", "pending": "待判定"}
    en = {"benign": "Benign", "suspicious": "Suspicious", "malicious": "Malicious", "pending": "Pending"}
    return (zh if language == "zh-CN" else en).get(normalized, normalized)


def _status_label(value: Any, language: str) -> str:
    normalized = str(_enum_value(value) or "-").upper()
    zh = {
        "PENDING": "扫描中",
        "VETTED": "待人工审核",
        "APPROVED": "已批准",
        "REJECTED": "已拒绝",
        "DEPRECATED": "已弃用",
    }
    en = {
        "PENDING": "Scanning",
        "VETTED": "Pending Review",
        "APPROVED": "Approved",
        "REJECTED": "Rejected",
        "DEPRECATED": "Deprecated",
    }
    return (zh if language == "zh-CN" else en).get(normalized, normalized)


def _severity_label(value: Any, language: str) -> str:
    normalized = str(value or "INFO").upper()
    zh = {"CRITICAL": "严重", "HIGH": "高", "MEDIUM": "中", "LOW": "低", "INFO": "提示"}
    return zh.get(normalized, normalized) if language == "zh-CN" else normalized.title()


def _severity_color(value: Any) -> colors.Color:
    normalized = str(value or "INFO").upper()
    if normalized in {"CRITICAL", "HIGH"}:
        return BRAND_RED
    if normalized == "MEDIUM":
        return AMBER
    if normalized == "LOW":
        return colors.HexColor("#2F6F9F")
    return MUTED


def _finding_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for finding in findings:
        severity = str(finding.get("severity") or "INFO").upper()
        counts[severity if severity in counts else "INFO"] += 1
    return counts


def _finding_location(finding: dict[str, Any], entry: RegistryEntry) -> str:
    path = finding.get("file") or finding.get("path") or entry.source.url or "-"
    line = finding.get("line") or finding.get("line_number")
    return f"{path}:{line}" if line else str(path)


def _finding_source(finding: dict[str, Any]) -> str:
    source = str(finding.get("source") or "rule")
    if source.lower() in {"behavioral", "agent-manager-local"}:
        return "Local Static"
    if "skillspector" in source.lower():
        return "Deep Scan"
    if "sandbox" in source.lower():
        return "Sandbox"
    return source


def _styles(language: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_kicker": ParagraphStyle(
            "CoverKicker",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=11,
            leading=15,
            textColor=BRAND_RED,
            spaceAfter=14,
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName=FONT,
            fontSize=29,
            leading=38,
            textColor=BRAND_DARK,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_skill": ParagraphStyle(
            "CoverSkill",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=18,
            leading=24,
            textColor=INK,
            spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading1"],
            fontName=FONT,
            fontSize=18,
            leading=24,
            textColor=BRAND_DARK,
            spaceBefore=10,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "SubsectionHeading",
            parent=base["Heading2"],
            fontName=FONT,
            fontSize=13,
            leading=18,
            textColor=BRAND_RED,
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "MinorHeading",
            parent=base["Heading3"],
            fontName=FONT,
            fontSize=10.5,
            leading=14,
            textColor=BRAND_DARK,
            spaceBefore=5,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.5,
            leading=14,
            textColor=INK,
            spaceAfter=5,
        ),
        "body_muted": ParagraphStyle(
            "ReportBodyMuted",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=13,
            textColor=MUTED,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=MUTED,
        ),
        "label": ParagraphStyle(
            "TableLabel",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.8,
            leading=12,
            textColor=BRAND_DARK,
        ),
        "value": ParagraphStyle(
            "TableValue",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.8,
            leading=12,
            textColor=INK,
        ),
        "metric_header": ParagraphStyle(
            "MetricHeader",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
            textColor=WHITE,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=15,
            leading=18,
            alignment=TA_CENTER,
            textColor=INK,
        ),
        "finding_title": ParagraphStyle(
            "FindingTitle",
            parent=base["Heading3"],
            fontName=FONT,
            fontSize=12,
            leading=16,
            textColor=BRAND_DARK,
            spaceAfter=1,
        ),
        "finding_meta": ParagraphStyle(
            "FindingMeta",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=MUTED,
        ),
        "finding_label": ParagraphStyle(
            "FindingLabel",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=8.5,
            leading=11,
            textColor=BRAND_RED,
            spaceAfter=2,
        ),
        "finding_body": ParagraphStyle(
            "FindingBody",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=13,
            textColor=INK,
        ),
        "bullet": ParagraphStyle(
            "ReportBullet",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9.3,
            leading=13.5,
            leftIndent=12,
            firstLineIndent=-8,
            bulletIndent=2,
            textColor=INK,
            spaceAfter=3,
        ),
        "center": ParagraphStyle(
            "Center",
            parent=base["BodyText"],
            fontName=FONT,
            fontSize=9,
            leading=13,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
    }


class ScanReportTemplate(BaseDocTemplate):
    def __init__(self, buffer: BytesIO, *, language: str, title: str, report_heading: str | None = None):
        super().__init__(
            buffer,
            pagesize=A4,
            leftMargin=LEFT_MARGIN,
            rightMargin=RIGHT_MARGIN,
            topMargin=TOP_MARGIN,
            bottomMargin=BOTTOM_MARGIN,
            title=title,
            author="River Security",
            subject=report_heading or "Skill security scan report",
        )
        self.language = language
        self.report_heading = report_heading
        frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="report-body",
        )
        self.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=self._draw_page))

    def _draw_page(self, canvas, doc) -> None:
        page_number = canvas.getPageNumber()
        canvas.saveState()
        if page_number > 1:
            logo = _logo_path()
            if logo.exists():
                logo_width = 36 * mm
                canvas.drawImage(
                    str(logo),
                    LEFT_MARGIN,
                    PAGE_HEIGHT - 20.5 * mm,
                    width=logo_width,
                    height=logo_width / LOGO_ASPECT_RATIO,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="w",
                )
            canvas.setFont(FONT, 8.5)
            canvas.setFillColor(MUTED)
            header = self.report_heading or ("Skill 安全扫描报告" if self.language == "zh-CN" else "Skill Security Scan Report")
            canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 14 * mm, header)
            canvas.setStrokeColor(LINE)
            canvas.setLineWidth(0.6)
            canvas.line(LEFT_MARGIN, PAGE_HEIGHT - 24 * mm, PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 24 * mm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(WEAK)
        classification = "内部使用" if self.language == "zh-CN" else "Internal Use"
        canvas.drawString(LEFT_MARGIN, 10 * mm, classification)
        page_text = f"第 {page_number} 页" if self.language == "zh-CN" else f"Page {page_number}"
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 10 * mm, page_text)
        canvas.restoreState()


def _p(value: Any, style: ParagraphStyle, *, limit: int | None = None) -> Paragraph:
    return Paragraph(_xml(value, limit=limit), style)


def _rich(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(value, style)


def _section(title: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    return [
        Paragraph(_xml(title), styles["h1"]),
        HRFlowable(width="100%", thickness=1.3, color=BRAND_RED, spaceAfter=8),
    ]


def _subsection(title: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_xml(title), styles["h2"])


def _bullet(value: Any, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"•&nbsp;&nbsp;{_xml(value)}", styles["bullet"])


def _label_value_table(
    rows: Iterable[tuple[str, Any]], styles: dict[str, ParagraphStyle], *, label_width: float = 43 * mm
) -> Table:
    data = [[_p(label, styles["label"]), _p(value, styles["value"], limit=3000)] for label, value in rows]
    table = Table(data, colWidths=[label_width, CONTENT_WIDTH - label_width], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PANEL),
                ("GRID", (0, 0), (-1, -1), 0.45, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _data_table(
    headers: list[str], rows: Iterable[Iterable[Any]], widths: list[float], styles: dict[str, ParagraphStyle]
) -> Table:
    data = [[_p(header, styles["metric_header"]) for header in headers]]
    data.extend([[_p(value, styles["value"], limit=1200) for value in row] for row in rows])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row_index in range(2, len(data), 2):
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), PANEL))
    table.setStyle(TableStyle(commands))
    return table


def _metrics_table(
    headers: list[str], values: list[Any], styles: dict[str, ParagraphStyle], *, accent_indexes: set[int] | None = None
) -> Table:
    accent_indexes = accent_indexes or set()
    data = [
        [_p(header, styles["metric_header"]) for header in headers],
        [_p(value, styles["metric_value"]) for value in values],
    ]
    width = CONTENT_WIDTH / len(headers)
    table = Table(data, colWidths=[width] * len(headers), hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
        ("BACKGROUND", (0, 1), (-1, 1), PANEL),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    for index in accent_indexes:
        commands.extend(
            [
                ("BACKGROUND", (index, 1), (index, 1), LIGHT_RED),
                ("TEXTCOLOR", (index, 1), (index, 1), BRAND_RED),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def _cover(
    entry: RegistryEntry, language: str, generated_at: datetime, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    logo = _logo_path()
    story: list[Flowable] = [Spacer(1, 14 * mm)]
    if logo.exists():
        logo_width = 54 * mm
        story.extend(
            [Image(str(logo), width=logo_width, height=logo_width / LOGO_ASPECT_RATIO), Spacer(1, 18 * mm)]
        )
    story.append(
        _p("SECURITY ASSESSMENT  /  安全评估" if language == "zh-CN" else "SECURITY ASSESSMENT", styles["cover_kicker"])
    )
    story.append(_p("Skill 安全扫描报告" if language == "zh-CN" else "Skill Security Scan Report", styles["cover_title"]))
    story.append(_p(entry.name, styles["cover_skill"]))
    story.append(HRFlowable(width="100%", thickness=3.2, color=BRAND_RED, spaceBefore=10, spaceAfter=18))
    risk = _risk_label(entry.risk_level, language)
    report_id = f"AM-SR-{generated_at:%Y%m%d}-{entry.skill_id[:8].upper()}"
    rows = (
        [
            ("报告编号", report_id),
            ("Skill 版本", f"v{entry.version_no}  /  {entry.skill_id}"),
            ("风险等级", risk),
            ("准入状态", _status_label(entry.status, language)),
            ("导出时间", _iso(generated_at)),
            ("密级", "内部使用"),
        ]
        if language == "zh-CN"
        else [
            ("Report ID", report_id),
            ("Skill Version", f"v{entry.version_no}  /  {entry.skill_id}"),
            ("Risk", risk),
            ("Admission Status", _status_label(entry.status, language)),
            ("Exported", _iso(generated_at)),
            ("Classification", "Internal Use"),
        ]
    )
    story.extend([_label_value_table(rows, styles), Spacer(1, 16 * mm)])
    notice = (
        "本报告仅对应上述版本、内容指纹与扫描上下文；Skill 内容变化后应重新扫描。"
        if language == "zh-CN"
        else "This report applies only to the identified version, content fingerprint, and scan context. Rescan after any content change."
    )
    story.extend([_p(notice, styles["body_muted"]), PageBreak()])
    return story


def _executive_conclusion(entry: RegistryEntry, language: str) -> str:
    risk = str(_enum_value(entry.risk_level) or "pending").lower()
    status = str(_enum_value(entry.status) or "pending").upper()
    if language == "zh-CN":
        if status == "REJECTED":
            return "当前版本未通过准入。应先处理策略阻断项或高风险发现，再重新扫描和审核。"
        if status == "APPROVED":
            return "当前版本已通过准入审批。部署前仍应核对内容指纹、签名和目标环境策略。"
        if risk == "malicious":
            return "扫描发现恶意或阻断级信号，当前版本不应批准或部署。"
        if risk == "suspicious":
            return "扫描发现需要复核的风险信号，建议由安全审核人员结合代码证据和运行时结果进行人工判断。"
        return "未发现达到阻断阈值的风险信号，但该结论不替代准入策略、签名校验和持续监控。"
    if status == "REJECTED":
        return "Admission is rejected. Resolve policy blockers or high-risk findings before rescanning and review."
    if status == "APPROVED":
        return "Admission is approved. Verify the fingerprint, signature, and target-environment policy before deployment."
    if risk == "malicious":
        return "Malicious or blocking signals were found. Do not approve or deploy this version."
    if risk == "suspicious":
        return "Risk signals require human review against code evidence and runtime observations."
    return "No blocking signal was found, but policy enforcement, signature verification, and monitoring still apply."


def _summary(
    entry: RegistryEntry, report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    classification = report.get("risk_classification") if isinstance(report.get("risk_classification"), dict) else {}
    blocking_count = classification.get("blocking_count", 0)
    headers = ["最终风险", "准入状态", "发现项", "阻断项"] if language == "zh-CN" else ["Final Risk", "Admission", "Findings", "Blocking"]
    values = [_risk_label(entry.risk_level, language), _status_label(entry.status, language), len(findings), blocking_count]
    story = _section("1. 管理摘要" if language == "zh-CN" else "1. Executive Summary", styles)
    story.extend(
        [
            _metrics_table(headers, values, styles, accent_indexes={0, 3}),
            Spacer(1, 9),
            _p(_executive_conclusion(entry, language), styles["body"]),
        ]
    )
    counts = _finding_counts(findings)
    severity_text = (
        f"严重度分布：Critical {counts['CRITICAL']}  /  High {counts['HIGH']}  /  Medium {counts['MEDIUM']}  /  Low {counts['LOW']}"
        if language == "zh-CN"
        else f"Severity: Critical {counts['CRITICAL']}  /  High {counts['HIGH']}  /  Medium {counts['MEDIUM']}  /  Low {counts['LOW']}"
    )
    story.append(_p(severity_text, styles["body_muted"]))
    top_findings = findings[:3]
    if top_findings:
        story.append(_subsection("重点关注" if language == "zh-CN" else "Priority Review", styles))
        for finding in top_findings:
            title = _localized_finding_copy(finding, "title", language)
            story.append(
                _bullet(
                    f"[{_severity_label(finding.get('severity'), language)}] {title} ({_finding_location(finding, entry)})",
                    styles,
                )
            )
    return story


def _identity(
    entry: RegistryEntry, report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    if language == "zh-CN":
        rows = [
            ("Skill 名称", entry.name),
            ("描述", entry.description),
            ("Family ID", entry.family_id),
            ("Version ID", entry.skill_id),
            ("版本", f"v{entry.version_no}"),
            ("来源", _enum_value(entry.source.origin)),
            ("作者 / 渠道", f"{entry.source.author or '-'} / {entry.source.channel or '-'}"),
            ("来源地址", entry.source.url),
            ("Commit SHA", entry.source.commit_sha),
            ("声明工具", entry.allowed_tools),
            ("内容指纹", entry.content_fingerprint),
            ("扫描上下文指纹", entry.scan_context_fingerprint),
            ("扫描结果复用", report.get("scan_result_reused", False)),
        ]
        title = "2. Skill 信息与来源"
    else:
        rows = [
            ("Skill Name", entry.name),
            ("Description", entry.description),
            ("Family ID", entry.family_id),
            ("Version ID", entry.skill_id),
            ("Version", f"v{entry.version_no}"),
            ("Origin", _enum_value(entry.source.origin)),
            ("Author / Channel", f"{entry.source.author or '-'} / {entry.source.channel or '-'}"),
            ("Source URL", entry.source.url),
            ("Commit SHA", entry.source.commit_sha),
            ("Declared Tools", entry.allowed_tools),
            ("Content Fingerprint", entry.content_fingerprint),
            ("Scan Context Fingerprint", entry.scan_context_fingerprint),
            ("Scan Result Reused", report.get("scan_result_reused", False)),
        ]
        title = "2. Skill Identity and Provenance"
    story = _section(title, styles)
    story.append(_label_value_table(rows, styles))
    return story


def _canonical_analyzer_key(analyzer: Any) -> str:
    """Map analyzer implementation/display identifiers to timing keys."""
    name = str(analyzer or "").strip().lower()
    if name == "basic" or name == "scanner" or name.startswith("scanner:"):
        return "scanner"
    if name == "skillspector" or name.startswith("skillspector:"):
        return "skillspector"
    if name == "agent-manager-local" or name == "behavioral" or name.startswith("behavioral:"):
        return "behavioral"
    if name == "sandbox" or name.startswith("sandbox:"):
        return "sandbox"
    if name == "llm" or name.startswith("llm:"):
        return "llm"
    return name


def _format_analyzer_duration(value: Any, language: str) -> str:
    missing = "未记录" if language == "zh-CN" else "Not recorded"
    if isinstance(value, bool):
        return missing
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return missing
    if seconds < 0:
        return missing
    if seconds < 0.01:
        milliseconds = seconds * 1000
        return "< 0.1 ms" if milliseconds < 0.1 else f"{milliseconds:.1f} ms"
    return f"{seconds:.2f}s"


def _analyzer_rows(entry: RegistryEntry, report: dict[str, Any], language: str) -> list[tuple[str, str, str]]:
    """Build de-duplicated analyzer rows backed by canonical timing records."""
    raw_timings = report.get("analyzer_timings")
    raw_timings = raw_timings if isinstance(raw_timings, dict) else {}
    timings: dict[str, dict[str, Any]] = {}
    for timing_name, timing in raw_timings.items():
        canonical_name = _canonical_analyzer_key(timing_name)
        if canonical_name and canonical_name not in timings and isinstance(timing, dict):
            timings[canonical_name] = timing

    display_names: dict[str, str] = {}
    analyzers = list(entry.vetting.analyzers_used) if entry.vetting else []
    for analyzer in analyzers:
        canonical_name = _canonical_analyzer_key(analyzer)
        if canonical_name and canonical_name not in display_names:
            display_names[canonical_name] = str(analyzer)
    for canonical_name in timings:
        display_names.setdefault(canonical_name, canonical_name)

    missing = "未记录" if language == "zh-CN" else "Not recorded"
    rows: list[tuple[str, str, str]] = []
    for canonical_name, display_name in display_names.items():
        timing = timings.get(canonical_name)
        status_value = timing.get("status") if timing else None
        status = _safe_text(status_value) if status_value is not None and status_value != "" else missing
        duration = _format_analyzer_duration(timing.get("duration_seconds") if timing else None, language)
        rows.append((display_name, status, duration))
    return rows


def _scope(
    entry: RegistryEntry, report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    analyzer_rows = _analyzer_rows(entry, report, language)
    story = _section("3. 扫描范围与执行状态" if language == "zh-CN" else "3. Scan Scope and Execution", styles)
    if analyzer_rows:
        headers = ["分析器", "状态", "耗时"] if language == "zh-CN" else ["Analyzer", "Status", "Duration"]
        story.extend([_data_table(headers, analyzer_rows, [92 * mm, 45 * mm, 38 * mm], styles), Spacer(1, 8)])
    rows = (
        [
            ("判定模式", report.get("judgement_mode")),
            ("执行策略", report.get("execution_strategy")),
            ("总耗时", f"{float(report.get('scan_duration_seconds') or (entry.vetting.scan_duration_seconds if entry.vetting else 0)):.2f}s"),
            ("Sandbox 已触发", bool(entry.vetting and entry.vetting.sandbox_triggered)),
            ("由策略要求 Sandbox", bool(entry.vetting and entry.vetting.sandbox_required_by_policy)),
            ("Sandbox Runtime", entry.vetting.sandbox_runtime if entry.vetting else None),
        ]
        if language == "zh-CN"
        else [
            ("Judgement Mode", report.get("judgement_mode")),
            ("Execution Strategy", report.get("execution_strategy")),
            ("Total Duration", f"{float(report.get('scan_duration_seconds') or (entry.vetting.scan_duration_seconds if entry.vetting else 0)):.2f}s"),
            ("Sandbox Triggered", bool(entry.vetting and entry.vetting.sandbox_triggered)),
            ("Sandbox Required by Policy", bool(entry.vetting and entry.vetting.sandbox_required_by_policy)),
            ("Sandbox Runtime", entry.vetting.sandbox_runtime if entry.vetting else None),
        ]
    )
    story.append(_label_value_table(rows, styles))
    return story


def _reconciliation(report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    reconciliation = report.get("risk_reconciliation") if isinstance(report.get("risk_reconciliation"), dict) else {}
    classification = report.get("risk_classification") if isinstance(report.get("risk_classification"), dict) else {}
    rows = (
        [
            ("前置风险", _risk_label(reconciliation.get("pre_llm_risk_level") or report.get("pre_llm_risk_level"), language)),
            ("LLM 风险", _risk_label(reconciliation.get("llm_risk_level"), language)),
            ("最终风险", _risk_label(reconciliation.get("final_risk_level") or report.get("risk_level"), language)),
            ("最高严重级别", report.get("max_severity")),
            ("阻断项", classification.get("blocking_count", 0)),
            ("合并策略", reconciliation.get("strategy")),
            ("LLM 风险降级", reconciliation.get("llm_downgraded")),
            ("降级被阻止", reconciliation.get("downgrade_blocked")),
            ("判定理由", reconciliation.get("reason")),
            ("降级理由", reconciliation.get("downgrade_reason")),
        ]
        if language == "zh-CN"
        else [
            ("Pre-LLM Risk", _risk_label(reconciliation.get("pre_llm_risk_level") or report.get("pre_llm_risk_level"), language)),
            ("LLM Risk", _risk_label(reconciliation.get("llm_risk_level"), language)),
            ("Final Risk", _risk_label(reconciliation.get("final_risk_level") or report.get("risk_level"), language)),
            ("Max Severity", report.get("max_severity")),
            ("Blocking Findings", classification.get("blocking_count", 0)),
            ("Reconciliation", reconciliation.get("strategy")),
            ("LLM Downgrade", reconciliation.get("llm_downgraded")),
            ("Downgrade Blocked", reconciliation.get("downgrade_blocked")),
            (
                "Reason",
                _localized_system_text(
                    reconciliation.get("reason"), language, "See the structured risk decision and accepted findings."
                ),
            ),
            (
                "Downgrade Reason",
                _localized_system_text(
                    reconciliation.get("downgrade_reason"),
                    language,
                    "The original-language downgrade rationale is available in the controlled console.",
                ),
            ),
        ]
    )
    story = _section("4. 综合风险研判" if language == "zh-CN" else "4. Risk Reconciliation", styles)
    story.append(_label_value_table(rows, styles))
    accepted = reconciliation.get("accepted_findings") if isinstance(reconciliation.get("accepted_findings"), list) else []
    dismissed = reconciliation.get("dismissed_findings") if isinstance(reconciliation.get("dismissed_findings"), list) else []
    if accepted:
        story.append(_subsection("采纳的发现项" if language == "zh-CN" else "Accepted Findings", styles))
        story.extend(
            _bullet(
                _localized_system_text(
                    item,
                    language,
                    f"Accepted finding {index}; original-language detail is available in the controlled console.",
                ),
                styles,
            )
            for index, item in enumerate(accepted, start=1)
        )
    if dismissed:
        story.append(_subsection("排除的发现项" if language == "zh-CN" else "Dismissed Findings", styles))
        story.extend(
            _bullet(
                _localized_system_text(
                    item,
                    language,
                    f"Dismissed finding {index}; original-language detail is available in the controlled console.",
                ),
                styles,
            )
            for index, item in enumerate(dismissed, start=1)
        )
    return story


def _finding_detail_block(
    label: str,
    value: Any,
    styles: dict[str, ParagraphStyle],
    *, background: colors.Color = PANEL,
    limit: int = 1600,
) -> Table:
    content = [_p(label, styles["finding_label"]), _p(value, styles["finding_body"], limit=limit)]
    table = Table([[content]], colWidths=[CONTENT_WIDTH - 13 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _finding_card(
    finding: dict[str, Any], index: int, entry: RegistryEntry, language: str, styles: dict[str, ParagraphStyle]
) -> Table:
    severity = finding.get("severity") or "INFO"
    severity_color = _severity_color(severity)
    title = _localized_finding_copy(finding, "title", language)
    source = _finding_source(finding)
    location = _finding_location(finding, entry)
    rule = finding.get("rule") or finding.get("rule_id") or "-"
    severity_chip = Table(
        [[_rich(f"<font color='#FFFFFF'>{_xml(_severity_label(severity, language))}</font>", styles["finding_meta"])]],
        colWidths=[18 * mm],
    )
    severity_chip.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), severity_color),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    title_block = [
        _p(f"F-{index:03d}  {title}", styles["finding_title"], limit=500),
        _p(f"{source}  |  {location}", styles["finding_meta"], limit=900),
    ]
    rule_label = "规则" if language == "zh-CN" else "Rule"
    header = Table(
        [[severity_chip, title_block, _rich(f"{rule_label}<br/>{_xml(rule, limit=300)}", styles["finding_meta"])]],
        colWidths=[22 * mm, 115 * mm, 25 * mm],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    details: list[Flowable] = [header]
    explanation = _localized_finding_copy(finding, "description", language)
    evidence = finding.get("evidence") or finding.get("code") or finding.get("snippet")
    remediation = _localized_finding_copy(finding, "remediation", language)
    if explanation:
        details.append(
            _finding_detail_block(
                "问题说明" if language == "zh-CN" else "Description", explanation, styles, background=colors.white, limit=1200
            )
        )
        details.append(Spacer(1, 4))
    if evidence:
        details.append(
            _finding_detail_block(
                "证据（已脱敏）" if language == "zh-CN" else "Evidence (redacted)", evidence, styles, background=PANEL, limit=1600
            )
        )
        details.append(Spacer(1, 4))
    if remediation:
        details.append(
            _finding_detail_block(
                "修复建议" if language == "zh-CN" else "Recommendation", remediation, styles, background=LIGHT_GREEN, limit=1200
            )
        )
    card = Table([[details]], colWidths=[CONTENT_WIDTH])
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.65, LINE),
                ("LINEBEFORE", (0, 0), (0, -1), 3, severity_color),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return card


def _findings(
    entry: RegistryEntry, report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    counts = _finding_counts(findings)
    story: list[Flowable] = [PageBreak()]
    story.extend(_section("5. 风险发现项" if language == "zh-CN" else "5. Risk Findings", styles))
    headers = ["总数", "严重", "高", "中", "低"] if language == "zh-CN" else ["Total", "Critical", "High", "Medium", "Low"]
    values = [len(findings), counts["CRITICAL"], counts["HIGH"], counts["MEDIUM"], counts["LOW"]]
    story.extend([_metrics_table(headers, values, styles, accent_indexes={1, 2}), Spacer(1, 10)])
    if not findings:
        message = "当前报告没有记录风险发现项。" if language == "zh-CN" else "No risk findings are recorded in this report."
        empty = Table([[_p(message, styles["body"]) ]], colWidths=[CONTENT_WIDTH])
        empty.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREEN), ("BOX", (0, 0), (-1, -1), 0.6, GREEN), ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        story.append(empty)
        return story
    intro = (
        "以下发现项按报告原始顺序展示。风险等级、证据和修复建议分层呈现，便于逐项复核。"
        if language == "zh-CN"
        else "Findings are shown in report order with severity, evidence, and remediation separated for review."
    )
    story.append(_p(intro, styles["body_muted"]))
    for index, finding in enumerate(findings[:MAX_FINDINGS], start=1):
        if isinstance(finding, dict):
            story.extend([KeepTogether([_finding_card(finding, index, entry, language, styles)]), Spacer(1, 9)])
    if len(findings) > MAX_FINDINGS:
        message = (
            f"报告仅展示前 {MAX_FINDINGS} 项；完整结果请在受控管理台查看。"
            if language == "zh-CN"
            else f"Only the first {MAX_FINDINGS} findings are shown. View the full result in the controlled console."
        )
        story.append(_p(message, styles["body_muted"]))
    return story


def _markdown_like(value: Any, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    story: list[Flowable] = []
    for raw_line in _safe_text(value, limit=12000).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            story.append(_p(line[4:], styles["h3"]))
        elif line.startswith("## "):
            story.append(_p(line[3:], styles["h2"]))
        elif line.startswith("# "):
            story.append(_p(line[2:], styles["h2"]))
        elif line.startswith(("- ", "* ")):
            story.append(_bullet(line[2:], styles))
        else:
            story.append(_p(line, styles["body"]))
    return story


def _analyzer_details(report: dict[str, Any], language: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    story: list[Flowable] = [PageBreak()]
    story.extend(_section("6. 分析器详细结果" if language == "zh-CN" else "6. Analyzer Details", styles))
    local = report.get("local_static_analysis") if isinstance(report.get("local_static_analysis"), dict) else {}
    deep = report.get("skillspector_analysis") if isinstance(report.get("skillspector_analysis"), dict) else {}
    sandbox = report.get("sandbox_analysis") if isinstance(report.get("sandbox_analysis"), dict) else {}
    llm = report.get("llm_analysis") if isinstance(report.get("llm_analysis"), dict) else {}
    story.append(_subsection("6.1 本地静态分析" if language == "zh-CN" else "6.1 Local Static Analysis", styles))
    if local:
        rows = [
            (("扫描文件" if language == "zh-CN" else "Files Scanned"), local.get("scanned_file_count")),
            (("发现项" if language == "zh-CN" else "Findings"), len(local.get("findings") or [])),
            (("最高严重级别" if language == "zh-CN" else "Max Severity"), local.get("max_severity")),
        ]
        story.append(_label_value_table(rows, styles))
    else:
        story.append(_p("未执行或没有结果。" if language == "zh-CN" else "Not run or no result available.", styles["body_muted"]))
    story.append(_subsection("6.2 深度扫描" if language == "zh-CN" else "6.2 Deep Scan", styles))
    if deep:
        rows = [
            (("可用" if language == "zh-CN" else "Available"), deep.get("available")),
            (("风险评分" if language == "zh-CN" else "Risk Score"), deep.get("risk_score")),
            (("风险级别" if language == "zh-CN" else "Risk Severity"), _severity_label(deep.get("risk_severity"), language)),
            (("抑制噪声" if language == "zh-CN" else "Suppressed Noise"), deep.get("suppressed_findings_count")),
            (
                ("建议" if language == "zh-CN" else "Recommendation"),
                _localized_system_text(
                    deep.get("risk_recommendation"),
                    language,
                    "Review the deep-scan result before approval.",
                ),
            ),
            (
                ("错误" if language == "zh-CN" else "Error"),
                _localized_system_text(
                    deep.get("error"),
                    language,
                    "The analyzer returned an error; see the controlled console for the original detail.",
                ),
            ),
        ]
        story.append(_label_value_table(rows, styles))
    else:
        story.append(_p("未执行或没有结果。" if language == "zh-CN" else "Not run or no result available.", styles["body_muted"]))
    story.append(_subsection("6.3 Sandbox 动态分析" if language == "zh-CN" else "6.3 Sandbox Dynamic Analysis", styles))
    if sandbox:
        rows = [
            (("已执行" if language == "zh-CN" else "Executed"), sandbox.get("executed", True)),
            (("Runtime / 镜像" if language == "zh-CN" else "Runtime / Image"), f"{sandbox.get('runtime', '-')} / {sandbox.get('image', '-')}"),
            (("入口" if language == "zh-CN" else "Entrypoint"), sandbox.get("entrypoint")),
            (("Probe 策略" if language == "zh-CN" else "Probe Strategy"), sandbox.get("probe_strategy")),
            (("退出码 / 超时" if language == "zh-CN" else "Exit / Timeout"), f"{sandbox.get('exit_code', '-')} / {sandbox.get('timed_out', False)}"),
            (("耗时" if language == "zh-CN" else "Duration"), f"{sandbox.get('duration_ms', '-')} ms"),
            (("网络尝试" if language == "zh-CN" else "Network Attempts"), sandbox.get("network_attempts")),
            (("风险 / 严重级别" if language == "zh-CN" else "Risk / Severity"), f"{sandbox.get('risk_level', '-')} / {sandbox.get('max_severity', '-')}"),
            (("摘要" if language == "zh-CN" else "Summary"), _localized_sandbox_summary(sandbox, language)),
        ]
        story.append(_label_value_table(rows, styles))
        signals = sandbox.get("signals") or sandbox.get("suspicious_events") or []
        if isinstance(signals, list) and signals:
            story.append(_p("运行时信号" if language == "zh-CN" else "Runtime Signals", styles["h3"]))
            for signal in signals[:30]:
                if isinstance(signal, dict):
                    category = _localized_system_text(signal.get("category", "-"), language, "runtime")
                    message = _localized_sandbox_signal(signal, language)
                    story.append(_bullet(f"[{signal.get('severity', 'INFO')}] {category} - {message}", styles))
                else:
                    story.append(
                        _bullet(
                            _localized_system_text(
                                signal,
                                language,
                                "The Sandbox recorded a runtime signal that requires review.",
                            ),
                            styles,
                        )
                    )
        for stream in ("stdout", "stderr"):
            if sandbox.get(stream):
                label = f"{stream} ({'已脱敏并截断' if language == 'zh-CN' else 'redacted and truncated'})"
                story.extend([_p(label, styles["h3"]), _finding_detail_block(label, _safe_text(sandbox.get(stream), limit=MAX_LOG_CHARS), styles)])
    else:
        story.append(_p("未执行或没有结果。" if language == "zh-CN" else "Not run or no result available.", styles["body_muted"]))
    story.append(_subsection("6.4 LLM 综合研判" if language == "zh-CN" else "6.4 LLM Review", styles))
    if llm:
        story.append(
            _label_value_table(
                [
                    (("供应商" if language == "zh-CN" else "Provider"), llm.get("provider")),
                    (("模型" if language == "zh-CN" else "Model"), llm.get("model")),
                    (("风险" if language == "zh-CN" else "Risk"), _risk_label(llm.get("risk_level"), language)),
                ],
                styles,
            )
        )
        if llm.get("report"):
            if language == "en-US" and _contains_cjk(llm.get("report")):
                story.append(
                    _p(
                        "The stored LLM narrative was generated in the original scan language. "
                        "The structured risk decision is shown above; view the controlled console for the original narrative.",
                        styles["body_muted"],
                    )
                )
            else:
                story.extend(_markdown_like(llm.get("report"), styles))
    else:
        story.append(_p("未执行或没有结果。" if language == "zh-CN" else "Not run or no result available.", styles["body_muted"]))
    return story


def _policy_and_integrity(
    entry: RegistryEntry, language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    story = _section("7. 准入策略与审批" if language == "zh-CN" else "7. Admission Policy and Review", styles)
    rows = (
        [
            ("安全风险", _risk_label(entry.risk_level, language)),
            ("准入状态", _status_label(entry.status, language)),
            ("声明工具合规", "是" if entry.declared_tools_valid else "否"),
            ("审批人", entry.approved_by),
            ("审批时间", _iso(entry.approved_at)),
            ("审批意见", entry.approval_note),
            ("拒绝原因", entry.rejection_reason),
        ]
        if language == "zh-CN"
        else [
            ("Security Risk", _risk_label(entry.risk_level, language)),
            ("Admission Status", _status_label(entry.status, language)),
            ("Declared Tools Compliant", "Yes" if entry.declared_tools_valid else "No"),
            ("Approved By", entry.approved_by),
            ("Approved At", _iso(entry.approved_at)),
            ("Approval Note", entry.approval_note),
            ("Rejection Reason", entry.rejection_reason),
        ]
    )
    story.append(_label_value_table(rows, styles))
    notes = entry.vetting.policy_notes if entry.vetting else []
    if notes:
        story.append(_subsection("策略说明" if language == "zh-CN" else "Policy Notes", styles))
        story.extend(_bullet(_localized_policy_note(note, language), styles) for note in notes)
    story.extend(_section("8. 完整性与可信校验" if language == "zh-CN" else "8. Integrity and Trust", styles))
    integrity = (
        [
            ("内容指纹", entry.content_fingerprint),
            ("扫描上下文指纹", entry.scan_context_fingerprint),
            ("签名状态", "已签名" if entry.signature else "未签名"),
            ("签名摘要", f"{entry.signature[:32]}..." if entry.signature else None),
            ("最新版本", "是" if entry.latest_version else "否"),
            ("最新可信版本", "是" if entry.latest_trusted_version else "否"),
        ]
        if language == "zh-CN"
        else [
            ("Content Fingerprint", entry.content_fingerprint),
            ("Scan Context Fingerprint", entry.scan_context_fingerprint),
            ("Signature", "Present" if entry.signature else "Not present"),
            ("Signature Digest", f"{entry.signature[:32]}..." if entry.signature else None),
            ("Latest Version", "Yes" if entry.latest_version else "No"),
            ("Latest Trusted Version", "Yes" if entry.latest_trusted_version else "No"),
        ]
    )
    story.append(_label_value_table(integrity, styles))
    return story


def _history(
    scan_runs: list[ScanRun], audit_events: list[AuditEvent], language: str, styles: dict[str, ParagraphStyle]
) -> list[Flowable]:
    story = _section("9. 扫描历史与审计轨迹" if language == "zh-CN" else "9. Scan History and Audit Trail", styles)
    if scan_runs:
        headers = ["扫描任务", "状态", "开始", "结束"] if language == "zh-CN" else ["Scan Run", "Status", "Started", "Finished"]
        rows = [(run.scan_run_id, _enum_value(run.status), _iso(run.started_at), _iso(run.finished_at)) for run in scan_runs[:20]]
        story.extend([_data_table(headers, rows, [48 * mm, 30 * mm, 48 * mm, 49 * mm], styles), Spacer(1, 8)])
    else:
        story.append(_p("没有可用的扫描执行记录。" if language == "zh-CN" else "No scan run records are available.", styles["body_muted"]))
    if audit_events:
        headers = ["时间", "事件", "操作人", "详情"] if language == "zh-CN" else ["Time", "Event", "Actor", "Details"]
        rows = [
            (
                _iso(event.timestamp),
                event.event_type,
                event.actor,
                _localized_system_text(
                    event.details,
                    language,
                    "Original-language audit details are available in the controlled console.",
                ),
            )
            for event in audit_events[:MAX_AUDIT_EVENTS]
        ]
        story.append(_data_table(headers, rows, [43 * mm, 42 * mm, 35 * mm, 55 * mm], styles))
    return story


def _limitations(language: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    story = _section("10. 评估局限" if language == "zh-CN" else "10. Assessment Limitations", styles)
    items = (
        [
            "本报告仅对应报告中记录的 Version ID、内容指纹和扫描上下文。",
            "静态分析不能覆盖所有运行时行为；Sandbox 结果受入口、参数、依赖和执行环境影响。",
            "Sandbox 未观察到风险不等于 Skill 完全安全；非零退出码也不必然代表恶意行为。",
            "未启用、跳过或执行失败的分析器会降低扫描覆盖范围，应结合执行状态判断报告置信度。",
            "LLM 分析是辅助信号，不能替代代码证据、公司策略和人工审核。",
            "报告中的日志和证据经过敏感信息遮盖与长度限制，完整原始数据应在受控平台内查看。",
        ]
        if language == "zh-CN"
        else [
            "This report applies only to the recorded Version ID, content fingerprint, and scan context.",
            "Static analysis cannot cover every runtime behavior; Sandbox observations depend on entrypoint, arguments, dependencies, and environment.",
            "No Sandbox finding does not prove the Skill is safe, and a non-zero exit code does not necessarily imply malicious behavior.",
            "Disabled, skipped, or failed analyzers reduce coverage; interpret confidence against execution status.",
            "LLM analysis is an auxiliary signal and does not replace code evidence, company policy, or human review.",
            "Logs and evidence are redacted and truncated. View complete raw data only in the controlled platform.",
        ]
    )
    story.extend(_bullet(item, styles) for item in items)
    return story


def build_scan_report_pdf(
    entry: RegistryEntry,
    *,
    scan_runs: Iterable[ScanRun] = (),
    audit_events: Iterable[AuditEvent] = (),
    language: str = "zh-CN",
    generated_at: datetime | None = None,
) -> bytes:
    """Return a branded, redacted PDF report for one concrete Skill version."""
    if language not in {"zh-CN", "en-US"}:
        raise ValueError("language must be zh-CN or en-US")
    if entry.vetting is None:
        raise ValueError("scan result is required")
    _register_fonts()
    generated_at = generated_at or datetime.now(timezone.utc)
    report = entry.vetting.scan_report if isinstance(entry.vetting.scan_report, dict) else {}
    styles = _styles(language)
    buffer = BytesIO()
    title = f"{entry.name} - {'Skill 安全扫描报告' if language == 'zh-CN' else 'Skill Security Scan Report'}"
    document = ScanReportTemplate(buffer, language=language, title=title)
    story: list[Flowable] = []
    story.extend(_cover(entry, language, generated_at, styles))
    story.extend(_summary(entry, report, language, styles))
    story.extend(_identity(entry, report, language, styles))
    story.extend(_scope(entry, report, language, styles))
    story.extend(_reconciliation(report, language, styles))
    story.extend(_findings(entry, report, language, styles))
    story.extend(_analyzer_details(report, language, styles))
    story.extend(_policy_and_integrity(entry, language, styles))
    story.extend(_history(list(scan_runs), list(audit_events), language, styles))
    story.extend(_limitations(language, styles))
    document.build(story)
    return buffer.getvalue()
