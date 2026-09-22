"""Generate the Help Center PDF with a real PDF outline/bookmark tree."""

from __future__ import annotations

import html
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    ListFlowable,
    ListItem,
    LongTable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from .schemas import DocsPdfArticle, DocsPdfExportRequest, DocsPdfSection


PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 18 * mm
RIGHT_MARGIN = 18 * mm
TOP_MARGIN = 18 * mm
BOTTOM_MARGIN = 17 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN

BRAND_RED = colors.HexColor("#C9262D")
NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#244B70")
INK = colors.HexColor("#31495F")
MUTED = colors.HexColor("#6A7D8E")
LINE = colors.HexColor("#D7E1EA")
PANEL = colors.HexColor("#F2F6FA")
PALE_BLUE = colors.HexColor("#EAF2F9")
PALE_AMBER = colors.HexColor("#FFF7E8")
CODE_BG = colors.HexColor("#0B1F33")
CODE_FG = colors.HexColor("#DCE9F5")

FONT = "NotoSansSC"


COPY = {
    "zh-CN": {
        "product": "智能体生命周期管理系统",
        "title": "帮助文档",
        "subtitle": "产品说明、操作步骤与运维指南",
        "language": "文档语言",
        "language_value": "简体中文",
        "generated_at": "生成时间",
        "contents": "目录",
        "expected": "预期结果",
        "references": "官方参考",
        "diagram": "架构或流程图",
        "diagram_hint": "图示保留关键阶段，完整说明和边界见本节正文。",
        "page": "第 {page} 页",
        "diagrams": {
            "governance": ["提交", "检测", "策略判定", "审核签名", "运行校验", "审计追踪"],
            "skill-scan-logic": ["Skill 内容与扫描选项", "确定性分析器", "策略补跑 Sandbox", "发现项归类", "可选 LLM 研判", "准入决策"],
            "architecture": ["管理人员、Scanner、Agent 与客户端、模型应用、MCP Client", "统一入口", "治理控制面", "Skill、客户端、模型、MCP 四条数据面", "Registry、报告、Trace 与安全审计"],
            "docker": ["浏览器、Agent、客户端、Scanner、模型应用与 MCP Client", "Nginx 统一入口", "Frontend 与 Backend", "Sandbox 隔离执行", "持久化数据卷"],
        },
    },
    "en-US": {
        "product": "Agent Manager",
        "title": "Help Documentation",
        "subtitle": "Product guidance and operating instructions",
        "language": "Language",
        "language_value": "English",
        "generated_at": "Generated at",
        "contents": "Contents",
        "expected": "Expected result",
        "references": "Official references",
        "diagram": "Architecture or process diagram",
        "diagram_hint": "The diagram retains the key stages; see the surrounding text for complete details and boundaries.",
        "page": "Page {page}",
        "diagrams": {
            "governance": ["Submit", "Scan", "Policy decision", "Review and sign", "Runtime verification", "Audit trail"],
            "skill-scan-logic": ["Skill content and scan options", "Deterministic analyzers", "Policy-triggered Sandbox", "Finding classification", "Optional LLM judgement", "Admission decision"],
            "architecture": ["Administrators, Scanner, Agents and Clients, model applications, and MCP Clients", "Unified ingress", "Governance control plane", "Skill, Client, model, and MCP data planes", "Registry, reports, traces, and security audit"],
            "docker": ["Browsers, Agents, Clients, Scanner, model applications, and MCP Clients", "Nginx unified ingress", "Frontend and Backend", "Sandbox isolation", "Persistent volumes"],
        },
    },
}


def _asset_root() -> Path:
    return Path(__file__).resolve().parents[1] / "agent_manager" / "assets"


def _screenshot_root() -> Path:
    configured = os.getenv("DOCS_SCREENSHOT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "web" / "public" / "docs" / "screenshots"


def _register_font() -> None:
    path = _asset_root() / "fonts" / "NotoSansSC-Regular.ttf"
    if not path.exists():
        raise RuntimeError(f"Bundled PDF font is missing: {path}")
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, str(path)))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT, italic=FONT, boldItalic=FONT)


def _markup(value: Any) -> str:
    return html.escape(str(value or "")).replace("\n", "<br/>")


class BookmarkParagraph(Paragraph):
    def __init__(
        self,
        text: str,
        style: ParagraphStyle,
        *,
        key: str,
        title: str,
        level: int,
        include_in_toc: bool = False,
    ) -> None:
        super().__init__(_markup(text), style)
        self.bookmark_key = key
        self.bookmark_title = title
        self.bookmark_level = level
        self.include_in_toc = include_in_toc


class HelpPdfTemplate(BaseDocTemplate):
    def __init__(self, *args, footer_text: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.footer_text = footer_text
        frame = Frame(
            LEFT_MARGIN,
            BOTTOM_MARGIN,
            CONTENT_WIDTH,
            PAGE_HEIGHT - TOP_MARGIN - BOTTOM_MARGIN,
            id="help-content",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="help", frames=[frame], onPage=self._draw_page))

    def _draw_page(self, canvas, doc) -> None:
        canvas.showOutline()
        if doc.page <= 2:
            return
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(LEFT_MARGIN, 11 * mm, PAGE_WIDTH - RIGHT_MARGIN, 11 * mm)
        canvas.setFont(FONT, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(LEFT_MARGIN, 7 * mm, "Agent Manager")
        canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 7 * mm, self.footer_text.format(page=doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, BookmarkParagraph):
            return
        self.canv.bookmarkPage(flowable.bookmark_key)
        self.canv.addOutlineEntry(
            flowable.bookmark_title,
            flowable.bookmark_key,
            level=flowable.bookmark_level,
            closed=False,
        )
        if flowable.include_in_toc:
            self.notify(
                "TOCEntry",
                (flowable.bookmark_level, flowable.bookmark_title, self.page, flowable.bookmark_key),
            )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_product": ParagraphStyle("cover-product", parent=base["Normal"], fontName=FONT, fontSize=11, leading=15, textColor=MUTED, spaceAfter=7, alignment=TA_LEFT),
        "cover_title": ParagraphStyle("cover-title", parent=base["Normal"], fontName=FONT, fontSize=32, leading=39, textColor=NAVY, spaceAfter=8, alignment=TA_LEFT),
        "cover_subtitle": ParagraphStyle("cover-subtitle", parent=base["Normal"], fontName=FONT, fontSize=13, leading=19, textColor=MUTED, alignment=TA_LEFT),
        "cover_meta_label": ParagraphStyle("cover-meta-label", parent=base["Normal"], fontName=FONT, fontSize=8, leading=12, textColor=MUTED, spaceAfter=2, alignment=TA_LEFT),
        "cover_meta_value": ParagraphStyle("cover-meta-value", parent=base["Normal"], fontName=FONT, fontSize=9.5, leading=15, textColor=INK, alignment=TA_LEFT),
        "toc_title": ParagraphStyle("toc-title", parent=base["Title"], fontName=FONT, fontSize=27, leading=34, textColor=NAVY, spaceAfter=16),
        "group": ParagraphStyle("group", parent=base["Normal"], fontName=FONT, fontSize=9, leading=13, textColor=MUTED, spaceAfter=8),
        "article": ParagraphStyle("article", parent=base["Title"], fontName=FONT, fontSize=25, leading=32, textColor=NAVY, spaceAfter=10),
        "summary": ParagraphStyle("summary", parent=base["Normal"], fontName=FONT, fontSize=10.5, leading=18, textColor=INK, spaceAfter=14),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=FONT, fontSize=16, leading=21, textColor=BLUE, spaceBefore=12, spaceAfter=8, keepWithNext=True),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName=FONT, fontSize=11, leading=16, textColor=BLUE, spaceBefore=7, spaceAfter=4, keepWithNext=True),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=FONT, fontSize=9.2, leading=16, textColor=INK, spaceAfter=7),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=FONT, fontSize=7.5, leading=12, textColor=MUTED),
        "table": ParagraphStyle("table", parent=base["BodyText"], fontName=FONT, fontSize=7, leading=10, textColor=INK),
        "table_header": ParagraphStyle("table-header", parent=base["BodyText"], fontName=FONT, fontSize=7, leading=10, textColor=BLUE, alignment=TA_LEFT),
        "code": ParagraphStyle("code", parent=base["Code"], fontName=FONT, fontSize=7.2, leading=10, textColor=CODE_FG, backColor=CODE_BG, borderPadding=8, spaceBefore=5, spaceAfter=8),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontName=FONT, fontSize=8, leading=13, textColor=BLUE),
        "toc_group": ParagraphStyle("toc-group", fontName=FONT, fontSize=11, leading=16, leftIndent=0, firstLineIndent=0, textColor=BLUE, spaceBefore=6),
        "toc_article": ParagraphStyle("toc-article", fontName=FONT, fontSize=8.5, leading=13, leftIndent=14, firstLineIndent=0, textColor=MUTED),
    }


def _summary_table(items, styles: dict[str, ParagraphStyle]) -> Table | None:
    if not items:
        return None
    rows = []
    for offset in range(0, len(items), 3):
        row = []
        for item in items[offset:offset + 3]:
            row.append(Paragraph(f"<font color='#71869A' size='7'>{_markup(item.label)}</font><br/><b>{_markup(item.value)}</b>", styles["body"]))
        while len(row) < 3:
            row.append("")
        rows.append(row)
    table = Table(rows, colWidths=[CONTENT_WIDTH / 3] * 3, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _data_table(section: DocsPdfSection, styles: dict[str, ParagraphStyle]) -> LongTable | None:
    if not section.table:
        return None
    columns = section.table.columns
    rows = [[Paragraph(_markup(value), styles["table_header"]) for value in columns]]
    for source_row in section.table.rows:
        normalized = [*source_row[:len(columns)], *([""] * max(0, len(columns) - len(source_row)))]
        rows.append([Paragraph(_markup(value), styles["table"]) for value in normalized])
    table = LongTable(rows, colWidths=[CONTENT_WIDTH / len(columns)] * len(columns), repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _diagram(section: DocsPdfSection, labels: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list:
    nodes = labels["diagrams"].get(section.diagram or "", [])
    if not nodes:
        return []
    cells = []
    widths = []
    node_width = (CONTENT_WIDTH - (len(nodes) - 1) * 7 * mm) / len(nodes)
    for index, node in enumerate(nodes):
        cells.append(Paragraph(f"<b>{_markup(node)}</b>", styles["table_header"]))
        widths.append(node_width)
        if index < len(nodes) - 1:
            cells.append(Paragraph("→", styles["table_header"]))
            widths.append(7 * mm)
    table = Table([cells], colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return [
        Paragraph(f"<b>{_markup(labels['diagram'])}</b>", styles["h3"]),
        table,
        Spacer(1, 3),
        Paragraph(_markup(labels["diagram_hint"]), styles["small"]),
        Spacer(1, 7),
    ]


def _code_block(value: str | None, styles: dict[str, ParagraphStyle]) -> Paragraph | None:
    if not value:
        return None
    escaped = html.escape(value).replace(" ", "&#160;").replace("\n", "<br/>")
    return Paragraph(escaped, styles["code"])


def _section_flowables(
    section: DocsPdfSection,
    *,
    locale: str,
    labels: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list:
    story: list = [Paragraph(_markup(section.title), styles["h2"])]
    story.extend(Paragraph(_markup(text), styles["body"]) for text in section.paragraphs)

    if section.bullets:
        story.append(ListFlowable(
            [ListItem(Paragraph(_markup(item), styles["body"]), leftIndent=10) for item in section.bullets],
            bulletType="bullet",
            start="circle",
            leftIndent=14,
            bulletFontName=FONT,
            bulletFontSize=7,
        ))
        story.append(Spacer(1, 5))

    flow_table = _summary_table(section.flow, styles)
    if flow_table:
        story.extend([flow_table, Spacer(1, 7)])
    story.extend(_diagram(section, labels, styles))

    if section.steps:
        for index, step in enumerate(section.steps, 1):
            story.append(Paragraph(f"{index}. {_markup(step.title)}", styles["h3"]))
            if step.body:
                story.append(Paragraph(_markup(step.body), styles["body"]))
            code = _code_block(step.code, styles)
            if code:
                story.append(code)
            if step.expected:
                expected = Paragraph(
                    f"<b>{_markup(labels['expected'])}</b><br/>{_markup(step.expected)}",
                    styles["callout"],
                )
                table = Table([[expected]], colWidths=[CONTENT_WIDTH])
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF8F1")),
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#C8E5D1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]))
                story.extend([table, Spacer(1, 5)])

    data_table = _data_table(section, styles)
    if data_table:
        story.extend([data_table, Spacer(1, 8)])
    code = _code_block(section.code, styles)
    if code:
        story.append(code)

    if section.callout:
        callout = Paragraph(
            f"<b>{_markup(section.callout.title)}</b><br/>{_markup(section.callout.body)}",
            styles["callout"],
        )
        table = Table([[callout]], colWidths=[CONTENT_WIDTH])
        background = PALE_AMBER if section.callout.type == "warning" else colors.HexColor("#EEF5FF")
        border = colors.HexColor("#D8B777") if section.callout.type == "warning" else colors.HexColor("#B9D1E7")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), background),
            ("BOX", (0, 0), (-1, -1), 0.5, border),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.extend([table, Spacer(1, 7)])

    if section.references:
        story.append(Paragraph(f"<b>{_markup(labels['references'])}</b>", styles["h3"]))
        for reference in section.references:
            story.append(Paragraph(f"<b>{_markup(reference.label)}</b><br/><font size='7' color='#728496'>{_markup(reference.url)}</font>", styles["body"]))

    if section.image:
        image_name = section.image.name if Path(section.image.name).suffix else f"{section.image.name}.png"
        image_path = (_screenshot_root() / locale / image_name).resolve()
        locale_root = (_screenshot_root() / locale).resolve()
        if image_path.is_relative_to(locale_root) and image_path.is_file():
            image = Image(str(image_path))
            image._restrictSize(CONTENT_WIDTH, 145 * mm)
            story.extend([image, Spacer(1, 3)])
            if section.image.caption:
                story.extend([Paragraph(_markup(section.image.caption), styles["small"]), Spacer(1, 7)])

    for resource in (section.link, section.download):
        if resource:
            story.append(Paragraph(f"<b>{_markup(resource.label)}</b>  <font color='#6B7E90'>{_markup(resource.value)}</font>", styles["body"]))
    return story


def _article_flowables(
    article: DocsPdfArticle,
    *,
    index: int,
    first_in_group: bool,
    locale: str,
    labels: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list:
    story: list = []
    group_label = article.eyebrow or article.group_title
    if first_in_group:
        story.append(BookmarkParagraph(
            group_label,
            styles["group"],
            key=f"group-{index}",
            title=article.group_title,
            level=0,
            include_in_toc=True,
        ))
    else:
        story.append(Paragraph(_markup(group_label), styles["group"]))
    story.append(BookmarkParagraph(
        article.title,
        styles["article"],
        key=f"article-{index}",
        title=article.title,
        level=1,
        include_in_toc=True,
    ))
    if article.summary:
        story.append(Paragraph(_markup(article.summary), styles["summary"]))
    story.append(HRFlowable(width="100%", thickness=1, color=NAVY, spaceBefore=2, spaceAfter=14))
    for items in (article.scenario, article.roles):
        table = _summary_table(items, styles)
        if table:
            story.extend([table, Spacer(1, 10)])
    for section in article.sections:
        story.extend(_section_flowables(section, locale=locale, labels=labels, styles=styles))
    return story


def build_docs_export_pdf(payload: DocsPdfExportRequest, *, generated_at: str) -> bytes:
    """Return a self-contained A4 PDF whose module/article tree appears as PDF bookmarks."""
    _register_font()
    labels = COPY[payload.locale]
    styles = _styles()
    output = BytesIO()
    doc = HelpPdfTemplate(
        output,
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=labels["title"],
        author="Agent Manager",
        subject=labels["subtitle"],
        footer_text=labels["page"],
    )

    story: list = [Spacer(1, 12 * mm)]
    logo = _asset_root() / "ruishu_logo_dark.png"
    if logo.is_file():
        image = Image(str(logo))
        image._restrictSize(55 * mm, 15 * mm)
        image.hAlign = "LEFT"
        story.extend([image, Spacer(1, 39 * mm)])
    story.extend([
        HRFlowable(width=24 * mm, thickness=4, color=BRAND_RED, hAlign="LEFT", spaceAfter=9 * mm),
        Paragraph(_markup(labels["product"]), styles["cover_product"]),
        BookmarkParagraph(labels["title"], styles["cover_title"], key="cover", title=labels["title"], level=0),
        Paragraph(_markup(labels["subtitle"]), styles["cover_subtitle"]),
        Spacer(1, 70 * mm),
        HRFlowable(width="100%", thickness=0.6, color=LINE, hAlign="LEFT", spaceAfter=7 * mm),
        Table(
            [
                [
                    Paragraph(_markup(labels["language"]), styles["cover_meta_label"]),
                    Paragraph(_markup(labels["generated_at"]), styles["cover_meta_label"]),
                ],
                [
                    Paragraph(_markup(labels["language_value"]), styles["cover_meta_value"]),
                    Paragraph(_markup(generated_at), styles["cover_meta_value"]),
                ],
            ],
            colWidths=[55 * mm, CONTENT_WIDTH - 55 * mm],
            hAlign="LEFT",
            style=TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 10 * mm),
                ("RIGHTPADDING", (1, 0), (1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]),
        ),
        PageBreak(),
        BookmarkParagraph(labels["contents"], styles["toc_title"], key="contents", title=labels["contents"], level=0),
    ])
    toc = TableOfContents()
    toc.levelStyles = [styles["toc_group"], styles["toc_article"]]
    toc.dotsMinLevel = 0
    story.extend([toc, PageBreak()])

    previous_group = None
    for index, article in enumerate(payload.articles, 1):
        if index > 1:
            story.append(PageBreak())
        first_in_group = article.group_title != previous_group
        story.extend(_article_flowables(
            article,
            index=index,
            first_in_group=first_in_group,
            locale=payload.locale,
            labels=labels,
            styles=styles,
        ))
        previous_group = article.group_title

    doc.multiBuild(story)
    return output.getvalue()
