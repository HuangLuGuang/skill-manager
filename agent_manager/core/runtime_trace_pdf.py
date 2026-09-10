"""Generate a redacted, auditable runtime-trace PDF report."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#657086")
BLUE = colors.HexColor("#3156A3")
PALE_BLUE = colors.HexColor("#EEF3FC")
LINE = colors.HexColor("#D9E0EA")
PANEL = colors.HexColor("#F7F9FC")
RED = colors.HexColor("#9F3441")
WHITE = colors.white
FONT = "NotoSansSC"


def _register_font() -> None:
    font_path = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansSC-Regular.ttf"
    if not font_path.exists():
        raise RuntimeError(f"Bundled PDF font is missing: {font_path}")
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(font_path)))


def _text(value: Any, limit: int = 240) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    normalized = " ".join(str(value).split())
    if len(normalized) > limit:
        normalized = f"{normalized[:limit]}…"
    return html.escape(normalized)


def build_runtime_trace_pdf(
    trace: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    language: str = "zh-CN",
    generated_at: datetime | None = None,
) -> bytes:
    """Build a PDF from redacted API projections only."""
    _register_font()
    generated_at = generated_at or datetime.now(timezone.utc)
    english = language == "en-US"
    labels = {
        "title": "Runtime Trace Evidence Report" if english else "统一调用轨迹证据报告",
        "classification": "REDACTED PROJECTION" if english else "脱敏投影",
        "boundary": (
            "This report contains server-redacted projections only. Raw prompts, responses, and tool arguments are excluded."
            if english
            else "本报告仅包含服务端脱敏投影，不包含原始 Prompt、响应和工具参数。"
        ),
        "overview": "Trace overview" if english else "轨迹概览",
        "events": "Ordered events" if english else "顺序事件",
        "generated": "Generated" if english else "生成时间",
        "event_count": "Events" if english else "事件数",
        "risk": "Risk" if english else "风险",
        "completeness": "Completeness" if english else "完整度",
        "trace_id": "Trace ID" if english else "轨迹 ID",
        "session_id": "Session ID" if english else "会话 ID",
        "agent": "Agent" if english else "智能体",
        "status": "Status" if english else "状态",
        "headers": (
            ["SEQ", "TYPE", "STATUS", "TURN / STEP", "TOOL", "DURATION", "RISK / REDACTED PAYLOAD"]
            if english
            else ["序号", "事件类型", "状态", "TURN / STEP", "工具", "耗时", "风险 / 脱敏负载"]
        ),
        "footer": "Agent Manager · Redacted runtime trace evidence" if english else "智能体生命周期管理系统 · 脱敏调用轨迹证据",
    }
    buffer = BytesIO()
    page_width, _ = landscape(A4)
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title=labels["title"],
        author="Agent Manager",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TraceTitle", parent=styles["Title"], fontName=FONT, fontSize=20, leading=25, textColor=INK, alignment=TA_LEFT)
    section_style = ParagraphStyle("TraceSection", parent=styles["Heading2"], fontName=FONT, fontSize=12, leading=16, textColor=INK, spaceBefore=8, spaceAfter=7)
    body_style = ParagraphStyle("TraceBody", parent=styles["BodyText"], fontName=FONT, fontSize=7.5, leading=10, textColor=INK)
    small_style = ParagraphStyle("TraceSmall", parent=body_style, fontSize=6.5, leading=8.5, textColor=MUTED)
    badge_style = ParagraphStyle("TraceBadge", parent=body_style, fontSize=7, leading=9, textColor=RED, alignment=TA_RIGHT)
    story = [
        Table(
            [[Paragraph(labels["title"], title_style), Paragraph(labels["classification"], badge_style)]],
            colWidths=[page_width - 70 * mm, 42 * mm],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LINEBELOW", (0, 0), (-1, -1), 1.2, BLUE)]),
        ),
        Spacer(1, 5 * mm),
        Paragraph(labels["boundary"], ParagraphStyle("Boundary", parent=body_style, backColor=PALE_BLUE, borderColor=BLUE, borderWidth=.5, borderPadding=7, leading=11)),
        Spacer(1, 4 * mm),
        Paragraph(labels["overview"], section_style),
    ]
    overview = [
        [labels["trace_id"], _text(trace.get("trace_id"), 80), labels["session_id"], _text(trace.get("session_id"), 80)],
        [labels["agent"], _text(trace.get("agent_id"), 80), labels["status"], _text(trace.get("status"), 40)],
        [labels["event_count"], _text(trace.get("event_count"), 20), labels["risk"], _text(trace.get("risk_level"), 30)],
        [labels["completeness"], _text(trace.get("completeness"), 40), labels["generated"], _text(generated_at.isoformat(), 50)],
    ]
    overview_table = Table(overview, colWidths=[28 * mm, 72 * mm, 30 * mm, 85 * mm])
    overview_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED), ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
        ("GRID", (0, 0), (-1, -1), .35, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([overview_table, Spacer(1, 5 * mm), Paragraph(labels["events"], section_style)])
    rows: list[list[Any]] = [[Paragraph(value, small_style) for value in labels["headers"]]]
    for event in events:
        turn_step = " / ".join(value for value in [event.get("turn_id"), event.get("step_id")] if value) or "-"
        duration = f"{event['duration_ms']:.1f} ms" if isinstance(event.get("duration_ms"), (int, float)) else "-"
        evidence = {"risk_codes": event.get("risk_codes") or [], "payload": event.get("payload")}
        rows.append([
            Paragraph(_text(event.get("seq"), 12), small_style),
            Paragraph(_text(event.get("type"), 50), small_style),
            Paragraph(_text(event.get("status"), 30), small_style),
            Paragraph(_text(turn_step, 60), small_style),
            Paragraph(_text(event.get("tool_name"), 50), small_style),
            Paragraph(_text(duration, 20), small_style),
            Paragraph(_text(evidence, 320), small_style),
        ])
    event_table = Table(rows, repeatRows=1, colWidths=[12 * mm, 32 * mm, 21 * mm, 38 * mm, 30 * mm, 22 * mm, 82 * mm])
    event_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE), ("GRID", (0, 0), (-1, -1), .3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PANEL]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(event_table)

    def footer(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 8 * mm, labels["footer"])
        canvas.drawRightString(page_width - 14 * mm, 8 * mm, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
