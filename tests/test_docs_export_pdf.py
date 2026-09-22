from io import BytesIO

from pypdf import PdfReader

from backend import schemas
from backend.docs_export_pdf import build_docs_export_pdf
from tests.test_docs_assistant import _test_client


def _payload(locale: str = "zh-CN") -> dict:
    chinese = locale == "zh-CN"
    return {
        "locale": locale,
        "articles": [
            {
                "slug": "skill-governance",
                "group_title": "能力治理" if chinese else "Capability governance",
                "eyebrow": "能力治理" if chinese else "Capability governance",
                "title": "治理流程" if chinese else "Governance flow",
                "summary": "提交、检测、审核与运行校验。" if chinese else "Submission, scanning, review, and runtime verification.",
                "scenario": [{"label": "目标" if chinese else "Goal", "value": "安全准入" if chinese else "Safe admission"}],
                "roles": [],
                "sections": [
                    {
                        "id": "pipeline",
                        "title": "检测与决策" if chinese else "Scanning and decisions",
                        "paragraphs": ["策略汇总各分析器结果。" if chinese else "Policy reconciles analyzer results."],
                        "bullets": ["保留原始证据。" if chinese else "Retain original evidence."],
                        "flow": [],
                        "diagram": "governance",
                        "steps": [],
                        "references": [],
                        "image": {
                            "name": "dashboard",
                            "alt": "Dashboard",
                            "caption": "Dashboard screenshot",
                        },
                    }
                ],
            }
        ],
    }


def _outline_titles(items) -> list[str]:
    titles = []
    for item in items:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
        else:
            titles.append(item.title)
    return titles


def test_help_pdf_has_sidebar_outline_and_no_article_count_on_cover():
    request = schemas.DocsPdfExportRequest.model_validate(_payload())
    document = build_docs_export_pdf(request, generated_at="2026年09月22日 12:00")
    reader = PdfReader(BytesIO(document))

    assert len(reader.pages) >= 3
    assert reader.root_object["/PageMode"] == "/UseOutlines"
    assert _outline_titles(reader.outline) == ["帮助文档", "目录", "能力治理", "治理流程"]
    cover = reader.pages[0].extract_text()
    assert "文档语言" in cover
    assert "生成时间" in cover
    assert "导出范围" not in cover
    assert "篇文档" not in cover
    assert sum(len(page.images) for page in reader.pages) >= 2


def test_docs_export_endpoint_returns_pdf_with_outline_header():
    client, _ = _test_client()
    response = client.post("/api/config/docs-export.pdf", json=_payload("en-US"))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-pdf-outline"] == "module-article"
    reader = PdfReader(BytesIO(response.content))
    assert "Capability governance" in _outline_titles(reader.outline)
    assert "Governance flow" in _outline_titles(reader.outline)


def test_docs_export_rejects_unsafe_screenshot_names():
    client, _ = _test_client()
    payload = _payload()
    payload["articles"][0]["sections"][0]["image"] = {
        "name": "../../secret.png",
        "alt": "unsafe",
        "caption": "unsafe",
    }

    response = client.post("/api/config/docs-export.pdf", json=payload)

    assert response.status_code == 422
