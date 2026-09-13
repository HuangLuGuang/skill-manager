from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import auth, iam, models
from backend.api_errors import ApiError, api_error_handler
from backend.routers import config as config_router
from backend.sqlite_db import Base, get_db


def _test_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    iam.initialize(db)
    user = models.User(
        username="docs-admin",
        email="docs@example.com",
        hashed_password="unused",
        role="admin",
        is_active=True,
    )
    provider = models.ModelProvider(
        name="docs-provider",
        base_url="https://model.example.test/v1",
        enabled=True,
        timeout_seconds=10,
    )
    db.add_all([user, provider])
    db.flush()
    db.add(models.ModelEndpoint(
        provider_id=provider.id,
        name="docs-model",
        display_name="Docs Model",
        enabled=True,
        max_output_tokens=800,
    ))
    db.commit()

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    async def override_user():
        return SimpleNamespace(username="docs-admin", role="admin", is_active=True)

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_active_user] = override_user
    app.dependency_overrides[auth.get_current_admin_user] = override_user
    app.include_router(config_router.router, prefix="/api")
    return TestClient(app), session_factory


def _enabled_config():
    return {
        "enabled": True,
        "model": "docs-model",
        "welcome_zh": "你好",
        "welcome_en": "Hello",
        "instruction_zh": "只回答文档内容",
        "instruction_en": "Use the docs only",
        "max_context_sections": 4,
        "common_questions": [
            {
                "id": "submit",
                "question_zh": "如何提交 Skill？",
                "question_en": "How do I submit a Skill?",
            }
        ],
    }


@pytest.mark.parametrize("protocol,suffix", [
    ("openai", "chat/completions"), ("anthropic", "messages"), ("responses_api", "responses"),
])
def test_docs_and_skill_call_selected_provider_protocol(monkeypatch, protocol, suffix):
    import httpx
    from agent_manager.core import llm

    client, factory = _test_client()
    with factory() as db:
        db.query(models.ModelProvider).one().api_format = protocol
        db.query(models.ModelEndpoint).one().upstream_name = "shared-upstream"
        db.commit()
    assert client.post("/api/config/docs-assistant", json=_enabled_config()).status_code == 200
    calls = []

    class Upstream:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, *, json, headers):
            assert url == f"https://model.example.test/v1/{suffix}"
            assert json["model"] == "shared-upstream"
            calls.append(json)
            answer = '{"verdict":"safe"}'
            if protocol == "responses_api":
                assert "input" in json and "messages" not in json
                result = {"id": "resp-test", "status": "completed", "model": "shared-upstream", "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": answer}]}]}
            elif protocol == "anthropic":
                assert headers["anthropic-version"] == "2023-06-01" and json["system"]
                result = {"id": "msg-test", "model": "shared-upstream", "stop_reason": "end_turn",
                          "content": [{"type": "text", "text": answer}], "usage": {"input_tokens": 1, "output_tokens": 1}}
            else:
                result = {"model": "shared-upstream", "choices": [{"message": {"content": answer}}]}
            return httpx.Response(200, json=result)

    monkeypatch.setattr(httpx, "AsyncClient", Upstream)
    response = client.post("/api/config/docs-assistant/ask", json={
        "question": "How to submit?", "locale": "en-US",
        "contexts": [{"slug": "quick-start", "article_title": "Start", "section_title": "Submit", "content": "Upload ZIP."}],
    })
    assert response.status_code == 200, response.text
    assert response.json() == {"answer": '{"verdict":"safe"}', "model": "docs-model"}

    monkeypatch.setattr("backend.sqlite_db.SessionLocal", factory)
    monkeypatch.delenv("AGENT_MANAGER_LLM_GATEWAY_URL", raising=False)
    value, raw = llm._call_llm(llm.LLMConfig(provider="model-gateway", model="docs-model"), "Return JSON.", "Inspect this Skill.")
    assert value == {"verdict": "safe"}
    assert raw["model"] == "docs-model"
    assert len(calls) == 2


def test_docs_assistant_is_disabled_by_default():
    client, _ = _test_client()
    response = client.get("/api/config/docs-assistant")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["model"] is None
    assert response.json()["max_output_tokens"] == 12800
    assert len(response.json()["common_questions"]) == 4


def test_enabling_docs_assistant_requires_an_available_model():
    client, _ = _test_client()
    payload = _enabled_config()
    payload["model"] = None

    response = client.post("/api/config/docs-assistant", json=payload)

    assert response.status_code == 400
    assert response.json()["error_code"] == "docs_assistant.model_required"


def test_docs_assistant_config_is_persisted_with_operation_log():
    client, session_factory = _test_client()

    payload = {**_enabled_config(), "max_output_tokens": 16000}
    saved = client.post("/api/config/docs-assistant", json=payload)
    loaded = client.get("/api/config/docs-assistant")

    assert saved.status_code == 200
    assert loaded.json()["enabled"] is True
    assert loaded.json()["model"] == "docs-model"
    assert loaded.json()["max_output_tokens"] == 16000
    assert loaded.json()["common_questions"][0]["question_en"] == "How do I submit a Skill?"
    db = session_factory()
    try:
        log = db.query(models.OperationLog).filter(models.OperationLog.target == "文档助手配置").one()
        assert log.username == "docs-admin"
    finally:
        db.close()


def test_ask_rejects_when_docs_assistant_is_disabled():
    client, _ = _test_client()

    response = client.post("/api/config/docs-assistant/ask", json={
        "question": "如何提交？",
        "locale": "zh-CN",
        "contexts": [{
            "slug": "quick-start",
            "article_title": "快速上手",
            "section_title": "提交 Skill",
            "content": "打开提交页面并上传 ZIP。",
        }],
    })

    assert response.status_code == 403
    assert response.json()["error_code"] == "docs_assistant.disabled"


@pytest.mark.parametrize("configured_limit,model_limit,expected_limit", [
    (None, None, 12800),
    (None, 32000, 12800),
    (16000, 32000, 16000),
    (16000, 800, 800),
])
def test_ask_uses_configured_model_and_document_context(monkeypatch, configured_limit, model_limit, expected_limit):
    client, session_factory = _test_client()
    with session_factory() as db:
        db.query(models.ModelEndpoint).filter_by(name="docs-model").one().max_output_tokens = model_limit
        db.commit()
    config = _enabled_config()
    if configured_limit is not None:
        config["max_output_tokens"] = configured_limit
    assert client.post("/api/config/docs-assistant", json=config).status_code == 200
    captured = {}

    async def fake_call_upstream(db, model, payload):
        captured["model"] = model.name
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "请打开提交页面并上传 ZIP。"}}]}

    monkeypatch.setattr("backend.routers.llm_gateway._call_upstream", fake_call_upstream)
    response = client.post("/api/config/docs-assistant/ask", json={
        "question": "然后做什么？",
        "locale": "zh-CN",
        "history": [
            {"role": "user", "content": "如何提交 Skill？"},
            {"role": "assistant", "content": "先准备 ZIP。"},
        ],
        "contexts": [{
            "slug": "quick-start",
            "article_title": "快速上手",
            "section_title": "提交 Skill",
            "content": "打开提交页面并上传 ZIP。",
        }],
    })

    assert response.status_code == 200
    assert response.json() == {"answer": "请打开提交页面并上传 ZIP。", "model": "docs-model"}
    assert captured["model"] == "docs-model"
    assert "打开提交页面并上传 ZIP" in captured["payload"]["messages"][1]["content"]
    assert captured["payload"]["messages"][-1] == {"role": "user", "content": "然后做什么？"}
    assert captured["payload"]["max_tokens"] == expected_limit
