from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import models
from backend import auth
from backend.routers import llm_gateway
from backend.sqlite_db import Base, get_db


def _client(tmp_path, monkeypatch, *, max_body_kb: int = 1024, max_concurrent_requests: int = 5):
    engine = create_engine(f"sqlite:///{tmp_path / 'gateway.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    token = "amk_test_token"
    provider = models.ModelProvider(name="mock", base_url="http://mock.local", api_key="provider-key")
    db.add(provider)
    db.flush()
    db.add(models.ModelEndpoint(provider_id=provider.id, name="mock-model", enabled=True, is_default=True))
    db.add(
        models.LlmApiKey(
            name="customer-key",
            key_hash=llm_gateway._hash_token(token),
            key_prefix=token[:8],
            allowed_models_json='["mock-model"]',
            expires_at=datetime.utcnow() + timedelta(days=1),
            max_body_kb=max_body_kb,
            max_concurrent_requests=max_concurrent_requests,
        )
    )
    db.add(
        models.PrivacyPolicy(
            name="default",
            entity_types_json='["PERSON","CN_PERSON","EMAIL_ADDRESS","PHONE_NUMBER"]',
            mapping_ttl_days=7,
        )
    )
    db.commit()
    db.close()

    async def fake_upstream(_db, _model, payload):
        joined = "\n".join(message["content"] for message in payload["messages"])
        assert "jane@example.com" not in joined
        assert "<EMAIL_ADDRESS:" in joined
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": joined}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(llm_gateway.runtime_router)
    app.include_router(llm_gateway.admin_router)
    return TestClient(app), token, TestingSessionLocal


def test_chat_completions_pseudonymizes_and_saves_trace(tmp_path, monkeypatch):
    client, token, session_factory = _client(tmp_path, monkeypatch)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "conversation_id": "conv-1",
            "metadata": {"tenant_id": "tenant-a", "user_id": "user-a"},
            "messages": [{"role": "user", "content": "Jane Doe email is jane@example.com"}],
        },
    )

    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "jane@example.com" in content
    assert "<EMAIL_ADDRESS:" not in content

    db = session_factory()
    try:
        assert db.query(models.PseudonymMapping).count() >= 1
        stages = {row.stage for row in db.query(models.LlmPipelineTrace).all()}
        assert {"meta", "original", "masked", "masked_response", "final_response"} <= stages
        audit = db.query(models.LlmRequestAudit).first()
        assert audit.total_tokens == 15
        meta = next(row for row in db.query(models.LlmPipelineTrace).all() if row.stage == "meta")
        meta_payload = llm_gateway._json_loads(meta.payload_json, {})
        assert meta_payload["api_key_id"] == audit.api_key_id
        assert meta_payload["api_key_name"] == "customer-key"
    finally:
        db.close()


def test_root_chat_completions_alias_supports_clients_without_v1_base(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)

    response = client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Jane email is jane@example.com"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"


def test_index_chat_completions_alias_supports_clients_using_base_as_endpoint(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)

    response = client.post(
        "/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Jane email is jane@example.com"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"


def test_openai_models_endpoint_lists_allowed_models(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)

    response = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {
                "id": "mock-model",
                "object": "model",
                "created": response.json()["data"][0]["created"],
                "owned_by": "agent-manager",
            }
        ],
    }


def test_api_key_cannot_use_unlisted_model(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "other-model",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 403


def test_unknown_chat_completion_fields_are_rejected(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "hello"}],
            "top_logprobs": 20,
        },
    )

    assert response.status_code == 422


def test_cherry_studio_stream_options_and_undefined_fields_are_accepted(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)
    captured = {}

    async def fake_stream(_db, _model, payload, **kwargs):
        captured["payload"] = payload

        async def event_generator():
            yield "data: [DONE]\n\n"

        return event_generator()

    monkeypatch.setattr(llm_gateway, "_stream_upstream", fake_stream)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "user": "[undefined]",
            "max_tokens": "[undefined]",
            "temperature": "[undefined]",
            "top_p": "[undefined]",
            "frequency_penalty": "[undefined]",
            "presence_penalty": "[undefined]",
            "response_format": "[undefined]",
            "stop": "[undefined]",
            "seed": "[undefined]",
            "serviceTier": "[undefined]",
            "reasoning_effort": "[undefined]",
            "verbosity": "[undefined]",
            "messages": [{"role": "user", "content": "hello jane@example.com"}],
            "tools": "[undefined]",
            "tool_choice": "[undefined]",
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )

    assert response.status_code == 200
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert "max_tokens" not in captured["payload"]
    assert "tools" not in captured["payload"]
    assert "service_tier" not in captured["payload"]


def test_multimodal_text_content_is_pseudonymized(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)
    captured = {}

    async def fake_upstream(_db, _model, payload):
        captured["messages"] = payload["messages"]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "记住这个文档里的信息"},
                        {"type": "text", "text": "用户信息.csv\n姓名,手机号\n张三,13312344321\n李四,13298766789"},
                    ],
                }
            ],
        },
    )

    assert response.status_code == 200
    content = captured["messages"][1]["content"]
    assert isinstance(content, list)
    joined = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
    assert "13312344321" not in joined
    assert "<PHONE_NUMBER:" in joined


def test_message_level_undefined_fields_are_stripped_before_upstream(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)
    captured = {}

    async def fake_upstream(_db, _model, payload):
        captured["messages"] = payload["messages"]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [
                {
                    "role": "assistant",
                    "content": "ok",
                    "tool_calls": "[undefined]",
                    "reasoning_content": "internal trace",
                },
                {"role": "user", "content": "hello"},
            ],
        },
    )

    assert response.status_code == 200
    assistant = captured["messages"][1]
    assert "tool_calls" not in assistant
    assert assistant["reasoning_content"] == "internal trace"


def test_reasoning_content_is_pseudonymized_and_restored(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)
    captured = {}

    async def fake_upstream(_db, _model, payload):
        captured["messages"] = payload["messages"]
        reasoning = payload["messages"][1]["reasoning_content"]
        assert "黄润泽" not in reasoning
        assert "<CN_PERSON:" in reasoning
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "ok",
                        "reasoning_content": reasoning,
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [
                {
                    "role": "assistant",
                    "content": "ok",
                    "reasoning_content": "用户的孩子叫黄润泽。",
                },
                {"role": "user", "content": "hello"},
            ],
        },
    )

    assert response.status_code == 200
    message = response.json()["choices"][0]["message"]
    assert "黄润泽" in message["reasoning_content"]
    assert "<CN_PERSON:" not in message["reasoning_content"]


def test_api_key_body_size_limit_is_enforced(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch, max_body_kb=1)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "messages": [{"role": "user", "content": "x" * 2000}],
        },
    )

    assert response.status_code == 413


def test_api_key_concurrency_counter_is_enforced():
    key = models.LlmApiKey(id=99, name="k", key_hash="h", key_prefix="amk", max_concurrent_requests=1)
    llm_gateway.ACTIVE_KEY_REQUESTS.pop(key.id, None)

    try:
        llm_gateway._acquire_key_slot(key)
        try:
            llm_gateway._acquire_key_slot(key)
            raised = False
        except Exception as exc:
            raised = getattr(exc, "status_code", None) == 429
        assert raised is True
    finally:
        llm_gateway._release_key_slot(key)
        llm_gateway.ACTIVE_KEY_REQUESTS.pop(key.id, None)


def test_existing_mappings_do_not_rewrite_system_examples(tmp_path, monkeypatch):
    client, token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        db.add(
            models.PseudonymMapping(
                tenant_id="tenant-a",
                conversation_id="conv-1",
                token="<EMAIL_ADDRESS:em_known>",
                entity_type="EMAIL_ADDRESS",
                original_value="jane@example.com",
                normalized_value="jane@example.com",
                request_id="seed",
                created_by="tester",
                expires_at=datetime.utcnow() + timedelta(days=1),
            )
        )
        db.commit()
    finally:
        db.close()

    captured = {}

    async def fake_upstream(_db, _model, payload):
        captured["messages"] = payload["messages"]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)

    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "conversation_id": "conv-1",
            "metadata": {"tenant_id": "tenant-a"},
            "messages": [
                {"role": "system", "content": "Use jane@example.com only as a formatting example."},
                {"role": "user", "content": "hello"},
            ],
        },
    )

    assert response.status_code == 200
    assert captured["messages"][1]["content"] == "Use jane@example.com only as a formatting example."


def test_cn_person_detection_uses_name_like_pattern():
    entities = llm_gateway._detect_entities("张三 联系邮箱 zhang@example.com，普通中文词语不应全中", {"CN_PERSON", "EMAIL_ADDRESS"})
    types = [item["entity_type"] for item in entities]

    assert "CN_PERSON" in types
    assert "EMAIL_ADDRESS" in types


def test_cn_person_detection_handles_context_and_suffix():
    text = "我叫黄路光，以后记得叫我黄路光。张三这个名字怎么样。我的孩子叫黄润泽"
    entities = llm_gateway._detect_entities(text, {"CN_PERSON"})
    names = [text[item["start"] : item["end"]] for item in entities]

    assert "黄路光" in names
    assert "张三" in names
    assert "黄润泽" in names


def test_custom_entity_rules_are_used():
    entities = llm_gateway._detect_entities(
        "内部工号为 STAFF-778899",
        {"EMPLOYEE_ID"},
        {"EMPLOYEE_ID": r"\bSTAFF-\d{6}\b"},
    )

    assert entities[0]["entity_type"] == "EMPLOYEE_ID"


def test_user_membership_policy_applies_when_key_has_no_group(tmp_path, monkeypatch):
    client, token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        user = models.User(username="policy-user", email="policy@example.com", hashed_password="x", role="admin")
        group = models.UserGroup(name="policy-group")
        db.add_all([user, group])
        db.flush()
        db.add(models.UserGroupMember(user_id=user.id, group_id=group.id))
        key = db.query(models.LlmApiKey).filter(models.LlmApiKey.key_hash == llm_gateway._hash_token(token)).first()
        key.user_id = user.id
        key.group_id = None
        db.add(
            models.PrivacyPolicy(
                name="group-policy",
                group_id=group.id,
                entity_types_json='["EMPLOYEE_ID"]',
                entity_rules_json='{"EMPLOYEE_ID":"\\\\bSTAFF-\\\\d{6}\\\\b"}',
                mapping_ttl_days=7,
            )
        )
        db.commit()
    finally:
        db.close()

    captured = {}

    async def fake_upstream(_db, _model, payload):
        captured["messages"] = payload["messages"]
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(llm_gateway, "_call_upstream", fake_upstream)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={"model": "mock-model", "messages": [{"role": "user", "content": "我的工号 STAFF-778899"}]},
    )

    assert response.status_code == 200
    assert "<EMPLOYEE_ID:" in captured["messages"][1]["content"]


def test_group_response_includes_bound_policy(tmp_path, monkeypatch):
    _client_obj, _token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        group = models.UserGroup(name="bound-group")
        db.add(group)
        db.flush()
        policy = models.PrivacyPolicy(
            name="bound-policy",
            group_id=group.id,
            entity_types_json='["EMAIL_ADDRESS"]',
            mapping_ttl_days=7,
        )
        db.add(policy)
        db.commit()
        db.refresh(group)
        response = llm_gateway._group_response(db, group)
        assert response.privacy_policy_id == policy.id
        assert response.privacy_policy_name == "bound-policy"
    finally:
        db.close()


def test_create_api_key_binds_current_user_not_group(tmp_path, monkeypatch):
    client, _token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        user = models.User(username="creator", email="creator@example.com", hashed_password="x", role="admin")
        group = models.UserGroup(name="creator-group")
        db.add_all([user, group])
        db.flush()
        db.add(models.UserGroupMember(user_id=user.id, group_id=group.id))
        db.commit()
        user_id = user.id
    finally:
        db.close()

    async def override_current_user():
        db_session = session_factory()
        try:
            return db_session.query(models.User).filter(models.User.id == user_id).first()
        finally:
            db_session.close()

    client.app.dependency_overrides[auth.get_current_admin_user] = override_current_user
    response = client.post(
        "/v1/llm-api-keys",
        json={
            "name": "auto-bound",
            "allowed_models": ["mock-model"],
            "max_body_kb": 1024,
            "max_concurrent_requests": 5,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == user_id
    assert data["group_id"] is None


def test_api_key_list_and_mutations_are_owner_scoped(tmp_path, monkeypatch):
    client, _token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        owner = models.User(username="owner", email="owner@example.com", hashed_password="x", role="admin")
        other = models.User(username="other", email="other@example.com", hashed_password="x", role="admin")
        db.add_all([owner, other])
        db.flush()
        owner_key = models.LlmApiKey(
            name="owner-key",
            key_hash=llm_gateway._hash_token("owner-token"),
            key_prefix="owner",
            user_id=owner.id,
            allowed_models_json='["mock-model"]',
        )
        other_key = models.LlmApiKey(
            name="other-key",
            key_hash=llm_gateway._hash_token("other-token"),
            key_prefix="other",
            user_id=other.id,
            allowed_models_json='["mock-model"]',
        )
        db.add_all([owner_key, other_key])
        db.commit()
        owner_id = owner.id
        other_key_id = other_key.id
    finally:
        db.close()

    async def override_current_user():
        db_session = session_factory()
        try:
            return db_session.query(models.User).filter(models.User.id == owner_id).first()
        finally:
            db_session.close()

    client.app.dependency_overrides[auth.get_current_admin_user] = override_current_user

    response = client.get("/v1/llm-api-keys")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["owner-key"]

    response = client.post(f"/v1/llm-api-keys/{other_key_id}/revoke")
    assert response.status_code == 404


def test_super_admin_api_key_list_is_also_owner_scoped(tmp_path, monkeypatch):
    client, _token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        super_admin = models.User(username="root", email="root@example.com", hashed_password="x", role="super_admin")
        other = models.User(username="other-root", email="other-root@example.com", hashed_password="x", role="admin")
        db.add_all([super_admin, other])
        db.flush()
        db.add_all(
            [
                models.LlmApiKey(
                    name="root-key",
                    key_hash=llm_gateway._hash_token("root-token"),
                    key_prefix="root",
                    user_id=super_admin.id,
                    allowed_models_json='["mock-model"]',
                ),
                models.LlmApiKey(
                    name="other-root-key",
                    key_hash=llm_gateway._hash_token("other-root-token"),
                    key_prefix="other",
                    user_id=other.id,
                    allowed_models_json='["mock-model"]',
                ),
            ]
        )
        db.commit()
        super_admin_id = super_admin.id
    finally:
        db.close()

    async def override_current_user():
        db_session = session_factory()
        try:
            return db_session.query(models.User).filter(models.User.id == super_admin_id).first()
        finally:
            db_session.close()

    client.app.dependency_overrides[auth.get_current_admin_user] = override_current_user

    response = client.get("/v1/llm-api-keys")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["root-key"]


def test_privacy_stats_are_owner_scoped(tmp_path, monkeypatch):
    client, _token, session_factory = _client(tmp_path, monkeypatch)
    db = session_factory()
    try:
        owner = models.User(username="stats-owner", email="stats-owner@example.com", hashed_password="x", role="admin")
        other = models.User(username="stats-other", email="stats-other@example.com", hashed_password="x", role="admin")
        db.add_all([owner, other])
        db.flush()
        owner_key = models.LlmApiKey(
            name="stats-owner-key",
            key_hash=llm_gateway._hash_token("stats-owner-token"),
            key_prefix="owner",
            user_id=owner.id,
            allowed_models_json='["mock-model"]',
        )
        other_key = models.LlmApiKey(
            name="stats-other-key",
            key_hash=llm_gateway._hash_token("stats-other-token"),
            key_prefix="other",
            user_id=other.id,
            allowed_models_json='["mock-model"]',
        )
        db.add_all([owner_key, other_key])
        db.flush()
        policy = db.query(models.PrivacyPolicy).first()
        policy.dp_enabled = False
        db.add_all(
            [
                models.LlmRequestAudit(
                    request_id="owner-req",
                    tenant_id="t",
                    conversation_id="c",
                    user_ref="owner",
                    api_key_id=owner_key.id,
                    model="mock-model",
                    traffic_type="pii_checked",
                    created_tokens=2,
                    reused_tokens=1,
                ),
                models.LlmRequestAudit(
                    request_id="other-req",
                    tenant_id="t",
                    conversation_id="c",
                    user_ref="other",
                    api_key_id=other_key.id,
                    model="mock-model",
                    traffic_type="pii_checked",
                    created_tokens=10,
                    reused_tokens=10,
                ),
                models.LlmUsageMetric(
                    request_id="owner-req",
                    tenant_id="t",
                    conversation_id="c",
                    api_key_id=owner_key.id,
                    model="mock-model",
                    pii_hits_json='{"EMAIL_ADDRESS": 2}',
                    created_tokens=2,
                    reused_tokens=1,
                ),
                models.LlmUsageMetric(
                    request_id="other-req",
                    tenant_id="t",
                    conversation_id="c",
                    api_key_id=other_key.id,
                    model="mock-model",
                    pii_hits_json='{"PHONE_NUMBER": 5}',
                    created_tokens=10,
                    reused_tokens=10,
                ),
                models.PseudonymMapping(
                    tenant_id="t",
                    conversation_id="c",
                    token="<EMAIL_ADDRESS:e_1>",
                    entity_type="EMAIL_ADDRESS",
                    original_value="a@example.com",
                    normalized_value="a@example.com",
                    request_id="owner-req",
                    created_by="owner",
                    expires_at=datetime.utcnow() + timedelta(days=1),
                ),
                models.PseudonymMapping(
                    tenant_id="t",
                    conversation_id="c",
                    token="<PHONE_NUMBER:p_1>",
                    entity_type="PHONE_NUMBER",
                    original_value="13800138000",
                    normalized_value="13800138000",
                    request_id="other-req",
                    created_by="other",
                    expires_at=datetime.utcnow() + timedelta(days=1),
                ),
            ]
        )
        db.commit()
        owner_id = owner.id
    finally:
        db.close()

    async def override_current_user():
        db_session = session_factory()
        try:
            return db_session.query(models.User).filter(models.User.id == owner_id).first()
        finally:
            db_session.close()

    client.app.dependency_overrides[auth.get_current_admin_user] = override_current_user

    response = client.get("/v1/privacy/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_requests"] == 1
    assert data["pii_checked_requests"] == 1
    assert data["active_mappings"] == 1
    assert data["created_tokens"] == 2
    assert data["reused_tokens"] == 1
    assert data["pii_hits"] == {"EMAIL_ADDRESS": 2}


def test_stream_chat_completions_returns_sse(tmp_path, monkeypatch):
    client, token, _session_factory = _client(tmp_path, monkeypatch)
    captured = {}

    async def fake_stream(_db, _model, payload, **kwargs):
        captured["stream"] = payload["stream"]
        captured["messages"] = payload["messages"]

        async def gen():
            try:
                yield 'data: {"choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n'
                yield "data: [DONE]\n\n"
            finally:
                llm_gateway._release_key_slot(kwargs["key"])

        return gen()

    monkeypatch.setattr(llm_gateway, "_stream_upstream", fake_stream)

    with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "mock-model",
            "stream": True,
            "messages": [{"role": "user", "content": "Jane email is jane@example.com"}],
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert captured["stream"] is True
    assert "jane@example.com" not in "\n".join(message["content"] for message in captured["messages"])
    assert "data: [DONE]" in body


def test_stream_safe_split_buffers_partial_tokens():
    token = "<EMAIL_ADDRESS:em_abc123>"
    emit, pending = llm_gateway._split_stream_safe_text("hello <EMAIL", [token])

    assert emit == "hello "
    assert pending == "<EMAIL"
