from io import BytesIO
import base64
import json
from copy import deepcopy

import pytest
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


def test_docs_export_accepts_more_than_forty_articles():
    payload = _payload("en-US")
    payload["articles"] = [deepcopy(payload["articles"][0]) for _ in range(41)]
    assert len(schemas.DocsPdfExportRequest.model_validate(payload).articles) == 41


def test_streamed_pdf_reports_layout_and_contains_updated_content():
    client, _ = _test_client()
    payload = _payload("en-US")
    payload["articles"][0]["summary"] = "Updated documentation revision for this export."
    response = client.post("/api/config/docs-export.pdf?stream=true", json=payload)
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-store"
    events = [json.loads(line) for line in response.text.splitlines() if line]
    progress = [event for event in events if event["type"] == "progress"]
    assert progress[0]["stage"] == "queued"
    assert any(event["stage"] == "preparing" and event["completed"] == 1 for event in progress)
    assert any(event["stage"] == "layout" and event["pass"] >= 2 for event in progress)
    assert events[-1]["type"] == "complete"
    document = b"".join(base64.b64decode(event["data"]) for event in events if event["type"] == "chunk")
    reader = PdfReader(BytesIO(document))
    layout = [event for event in progress if event["stage"] == "layout"]
    passes = sorted({event["pass"] for event in layout})
    for pass_number in passes:
        pages = [event for event in layout if event["pass"] == pass_number]
        assert pages[0]["page"] == 0
        assert [event["page"] for event in pages] == list(range(pages[-1]["page"] + 1))
        estimate = None if pass_number == 1 else max(event["page"] for event in layout if event["pass"] == pass_number - 1)
        assert all(event["estimated_pages"] == estimate for event in pages)
    ready = next(event for event in progress if event["stage"] == "downloading")
    assert ready["total_passes"] == max(passes)
    assert ready["total_pages"] == len(reader.pages)
    assert ready["total_bytes"] == len(document)
    assert ready["completed_bytes"] == 0
    assert "Updated documentation revision for this export." in "".join(page.extract_text() for page in reader.pages)
    assert "Governance flow" in _outline_titles(reader.outline)


def test_streamed_pdf_failure_has_stable_error_without_complete(monkeypatch):
    from backend import docs_export_stream

    def fail(*args, **kwargs):
        raise RuntimeError("Internal render error")

    monkeypatch.setattr(docs_export_stream, "build_docs_export_pdf", fail)
    client, _ = _test_client()
    response = client.post("/api/config/docs-export.pdf?stream=true", json=_payload())
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert events[-1] == {"type": "error", "error_code": "docs_export.generation_failed"}
    assert not any(event["type"] in {"chunk", "complete"} for event in events)


def test_streamed_pdf_checks_permission_before_generation(monkeypatch):
    from backend import iam
    from backend.api_errors import ApiError

    def deny(*args, **kwargs):
        raise ApiError(403, "auth.permission_denied", "权限不足", "Permission denied")

    client, _ = _test_client()
    monkeypatch.setattr(iam, "check", deny)
    response = client.post("/api/config/docs-export.pdf?stream=true", json=_payload())
    assert response.status_code == 403
    assert response.json()["error_code"] == "auth.permission_denied"


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


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_docs_export_accepts_aidr_architecture_and_retains_control_boundary(locale):
    payload = _payload(locale)
    article = payload["articles"][0]
    article["slug"] = "aidr-overview"
    boundary = "平台 ACK 只确认接收；阻断由执行点完成。" if locale == "zh-CN" else "Platform ACK confirms receipt; blocking requires an enforcement point."
    article["sections"] = [{"id": "architecture", "title": "AIDR", "diagram": "aidr", "paragraphs": [boundary]}]

    request = schemas.DocsPdfExportRequest.model_validate(payload)
    reader = PdfReader(BytesIO(build_docs_export_pdf(request, generated_at="2026-10-13")))
    text = "".join(page.extract_text() for page in reader.pages)
    compact = "".join(text.split())
    assert "".join(boundary.split()) in compact
    for label in (["Agent 日志", "持久化队列", "批次上报", "关联与审计"] if locale == "zh-CN" else ["Agent logs", "durable outbox", "batch upload", "correlation and audit"]):
        assert "".join(label.split()) in compact


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_docs_export_accepts_integration_choice_diagram(locale):
    payload = _payload(locale)
    payload["articles"][0]["sections"] = [{"id": "integration-flow", "title": "Integration", "diagram": "integration-choice"}]
    request = schemas.DocsPdfExportRequest.model_validate(payload)
    reader = PdfReader(BytesIO(build_docs_export_pdf(request, generated_at="2026-10-13")))
    compact = "".join("".join(page.extract_text() for page in reader.pages).split())
    for label in ("Runtime", "Dify", "Scanner", "Hook", "Verifier", "AIDR"):
        assert label in compact
