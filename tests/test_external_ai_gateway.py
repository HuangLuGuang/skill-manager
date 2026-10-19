import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, client_governance, models
from backend.api_errors import ApiError, api_error_handler
from backend.external_ai_gateway import (
    SignedClient,
    binding_models,
    canonical_path,
    canonical_query,
    ensure_binding,
    string_to_sign,
)
from backend.iam_routes import route_permission
from backend.routers import agents, clients, external_ai_gateways
from backend.routers.access_tokens import _hash_token
from backend.security_scan_controls import protect_secret, unprotect_secret
from backend.sqlite_db import Base, get_db


def _permission_for(path: str, method: str) -> str | None:
    request = SimpleNamespace(
        method=method,
        scope={"route": SimpleNamespace(path=path)},
        url=SimpleNamespace(path=path),
    )
    return route_permission(request)


def test_external_gateway_routes_use_dedicated_iam_permissions():
    assert _permission_for("/api/v1/external-ai-gateways", "GET") == "external_gateways:view"
    assert _permission_for("/api/v1/external-ai-gateways", "POST") == "external_gateways:create"
    assert _permission_for("/api/v1/external-ai-gateways/{gateway_id}", "PUT") == "external_gateways:update"
    assert _permission_for("/api/v1/external-ai-gateways/{gateway_id}", "DELETE") == "external_gateways:delete"
    assert _permission_for("/api/v1/external-ai-gateways/{gateway_id}/test", "POST") == "external_gateways:test"
    assert _permission_for("/api/v1/external-ai-gateways/{gateway_id}/agent-keys", "GET") == "external_gateways:view"
    assert _permission_for("/api/v1/external-ai-gateways/{gateway_id}/agent-keys/{binding_id}/reveal", "POST") == "external_gateways:reveal"


def _database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'external.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)
    return factory


@pytest.mark.parametrize("base_url", ["http://gateway.test:4005", "http://gateway.test:4005/management"])
def test_signed_client_matches_seven_line_contract(monkeypatch, base_url):
    captured = {}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr("backend.external_ai_gateway.httpx.request", request)
    client = SignedClient(base_url, "token-id", "token-secret")
    result = client.request("POST", "/api/v1/agents/中文", {"name": "测试"}, "b=2&a=1")
    assert result.data == {"ok": True}
    parsed = urlsplit(captured["url"])
    assert parsed.path == urlsplit(base_url).path + "/api/v1/agents/%E4%B8%AD%E6%96%87"
    query = parse_qs(parsed.query)
    body = captured["kwargs"]["content"]
    expected = string_to_sign(
        "POST", parsed.path, "b=2&a=1", body, query["timestamp"][0], query["nonce"][0], "token-id"
    )
    assert query["signature"] == [hmac.new(b"token-secret", expected.encode(), hashlib.sha256).hexdigest()]
    assert canonical_path("/api/%E4%B8%AD") == "/api/%25E4%25B8%25AD"
    assert canonical_query("b=2&signature=x&a=1&tokenid=t") == "a=1&b=2"


def test_signed_client_delete_is_idempotent_for_missing_remote_agent(monkeypatch):
    monkeypatch.setattr(
        "backend.external_ai_gateway.httpx.request",
        lambda *args, **kwargs: httpx.Response(404, text="agent not found"),
    )
    result = SignedClient("http://gateway.test:4005", "token-id", "token-secret").delete_agent("agent-1")
    assert result == {"deleted": "agent-1", "already_missing": True}


def test_gateway_crud_encrypts_and_masks_secret(tmp_path):
    factory = _database(tmp_path)

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1, username="root", hashed_password="x", role="super_admin"
    )
    app.include_router(external_ai_gateways.router, prefix="/api")
    client = TestClient(app)
    created = client.post("/api/v1/external-ai-gateways", json={
        "name": "联通网关",
        "management_base_url": "http://10.10.121.17:4005/",
        "model_base_url": "http://10.10.121.17:8080/",
        "token_id": "token-id",
        "token_value": "plain-token-value",
        "enabled": True,
    })
    assert created.status_code == 200
    assert created.json()["token_value_masked"] == "********"
    assert "plain-token-value" not in created.text
    gateway_id = created.json()["id"]
    updated = client.put(f"/api/v1/external-ai-gateways/{gateway_id}", json={"name": "联通网关 v2", "token_value": ""})
    assert updated.status_code == 200
    with factory() as db:
        row = db.get(models.ExternalAIGateway, gateway_id)
        assert row.management_base_url == "http://10.10.121.17:4005"
        assert row.model_base_url == "http://10.10.121.17:8080"
        assert "plain-token-value" not in row.token_value_encrypted
        assert unprotect_secret(row.token_value_encrypted) == "plain-token-value"


def test_model_routing_default_is_inherited_and_client_cannot_expand_it(tmp_path):
    factory = _database(tmp_path)
    with factory() as db:
        db.add(models.ClientGovernancePolicy(
            scope=client_governance.DEFAULT_SCOPE,
            enabled=True,
            protocol=2,
            model_routing_json=json.dumps({
                "external_gateway_enabled": True,
                "external_gateway_id": 7,
                "auto_register_agent": True,
                "client_select_model": True,
            }),
        ))
        db.add(models.ClientGovernancePolicy(
            scope="host-1",
            enabled=True,
            protocol=2,
            model_routing_json=json.dumps({
                "external_gateway_enabled": True,
                "external_gateway_id": 8,
                "auto_register_agent": True,
                "client_select_model": True,
            }),
        ))
        db.commit()
        view = client_governance.policy_view(db, "host-1")
        assert view["model_routing_source"] == "client"
        assert view["model_routing"]["external_gateway_enabled"] is False
        assert view["model_routing"]["external_gateway_id"] == 7


def test_model_routing_change_creates_a_dedicated_policy_sync_task(tmp_path):
    factory = _database(tmp_path)
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway", management_base_url="http://mgmt.test:4005", model_base_url="http://model.test:8080",
            token_id="id", token_value_encrypted=protect_secret("management-secret"), enabled=True,
        )
        db.add_all([
            gateway,
            models.ManagedClient(
                client_id="host-1", name="Host", hostname="host", os="darwin", arch="arm64", client_version="1.0"
            ),
            models.ClientGovernancePolicy(scope="host-1", enabled=True, protocol=2, revision=0),
        ])
        db.commit()
        requested = client_governance.PolicyChange(
            rules={},
            expected_version="0:0",
            model_routing=client_governance.ModelRoutingConfig(
                external_gateway_enabled=True,
                external_gateway_id=gateway.id,
                auto_register_agent=True,
                client_select_model=True,
            ),
        )
        preview = client_governance.preview(db, client_governance.DEFAULT_SCOPE, requested)
        requested.preview_id = preview["preview_id"]
        client_governance.save_policy(
            db,
            client_governance.DEFAULT_SCOPE,
            requested,
            SimpleNamespace(username="root"),
        )
        task = db.query(models.ClientTask).filter_by(client_id="host-1", task_type="sync_policy").one()
        assert json.loads(task.payload_json)["reason"] == "model_routing_policy_changed"


def test_client_external_model_selection_obeys_platform_policy(tmp_path):
    factory = _database(tmp_path)
    token = "client-runtime-token"
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway", management_base_url="http://mgmt.test:4005", model_base_url="http://model.test:8080",
            token_id="id", token_value_encrypted=protect_secret("management-secret"), enabled=True,
        )
        client = models.ManagedClient(
            client_id="host-1", name="Host", hostname="host", os="darwin", arch="arm64", client_version="1.0"
        )
        agent = models.ManagedAgent(
            agent_id="managed-1", name="Managed", channel="codex", status="active", created_by="owner",
            skill_names_json="[]", prompt_names_json="[]",
        )
        db.add_all([gateway, client, agent])
        db.flush()
        gateway_id = gateway.id
        db.add_all([
            models.ClientGovernancePolicy(
                scope=client_governance.DEFAULT_SCOPE,
                enabled=True,
                protocol=2,
                model_routing_json=json.dumps({
                    "external_gateway_enabled": True,
                    "external_gateway_id": gateway_id,
                    "auto_register_agent": True,
                    "client_select_model": False,
                }),
            ),
            models.ClientAgent(
                client_id=client.client_id,
                local_agent_id="codex",
                agent_type="codex",
                managed_agent_id=agent.agent_id,
                capabilities_json='{"model_config_auto_apply":true}',
            ),
            models.AccessToken(
                name="client", token_type="client", token_hash=_hash_token(token), token_prefix=token[:8],
                scopes_json='["client:read-tasks"]', bound_client_id=client.client_id,
                allow_agent_credential_issuance=True, created_by="owner", status="active",
            ),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.include_router(clients.router, prefix="/api")
    response = TestClient(app).post(
        "/api/v1/clients/host-1/model-configurations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "local_agent_id": "codex",
            "agent_type": "codex",
            "managed_agent_id": "managed-1",
            "model": "model-1",
            "source": "external_gateway",
            "gateway_id": gateway_id,
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "client.external_model_selection_disabled"


def test_client_status_exposes_external_gateway_readiness_without_secret(tmp_path):
    factory = _database(tmp_path)
    token = "client-runtime-token"
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway", management_base_url="http://mgmt.test:4005", model_base_url="http://model.test:8080",
            token_id="id", token_value_encrypted=protect_secret("management-secret"), enabled=True,
        )
        client = models.ManagedClient(
            client_id="host-1", name="Host", hostname="host", os="darwin", arch="arm64", client_version="1.0"
        )
        agent = models.ManagedAgent(
            agent_id="managed-1", name="Managed", channel="codex", status="active", created_by="owner",
            skill_names_json="[]", prompt_names_json="[]",
        )
        db.add_all([gateway, client, agent])
        db.flush()
        db.add_all([
            models.ClientGovernancePolicy(
                scope=client_governance.DEFAULT_SCOPE,
                enabled=True,
                protocol=2,
                model_routing_json=json.dumps({
                    "external_gateway_enabled": True,
                    "external_gateway_id": gateway.id,
                    "auto_register_agent": True,
                    "client_select_model": True,
                }),
            ),
            models.ClientAgent(
                client_id=client.client_id,
                local_agent_id="codex",
                agent_type="codex",
                managed_agent_id=agent.agent_id,
                capabilities_json='{"model_config_auto_apply":true}',
            ),
            models.ExternalGatewayAgentBinding(
                gateway_id=gateway.id,
                client_id=client.client_id,
                managed_agent_id=agent.agent_id,
                external_agent_id="external-agent-1",
                key_id="key-1",
                api_key_encrypted=protect_secret("external-api-secret"),
                available_models_json='[{"id":"model-1","name":"model-1"}]',
                status="active",
            ),
            models.AccessToken(
                name="client", token_type="client", token_hash=_hash_token(token), token_prefix=token[:8],
                scopes_json='["client:read-policy"]', bound_client_id=client.client_id,
                allow_agent_credential_issuance=True, created_by="owner", status="active",
            ),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.include_router(clients.router, prefix="/api")
    response = TestClient(app).get(
        "/api/v1/clients/host-1/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    configuration = response.json()["model_configuration"]
    assert configuration["external_gateway"] == {
        "id": configuration["model_routing"]["external_gateway_id"],
        "name": "gateway",
        "model_base_url": "http://model.test:8080",
    }
    assert configuration["external_catalogs"][0]["external_agent_id"] == "external-agent-1"
    assert configuration["external_catalogs"][0]["key_id"] == "key-1"
    assert "external-api-secret" not in response.text


def test_binding_encrypts_one_time_key_and_catalog_uses_bearer(tmp_path, monkeypatch):
    factory = _database(tmp_path)
    calls = []

    class FakeManagement:
        def register_agent(self, payload):
            calls.append(payload)
            return {"success": True, "id": payload["id"], "key": "external-api-secret", "keyId": "key-1"}

    def get(url, headers=None, timeout=None):
        assert url == "http://model.test:8080/v1/models"
        assert headers == {"Authorization": "Bearer external-api-secret"}
        return httpx.Response(200, json={"data": [{"id": "m-1"}, {"id": "m-2"}, {"id": "m-1"}]})

    monkeypatch.setattr("backend.external_ai_gateway.gateway_client", lambda _row: FakeManagement())
    monkeypatch.setattr("backend.external_ai_gateway.httpx.get", get)
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="test", management_base_url="http://mgmt.test:4005", model_base_url="http://model.test:8080",
            token_id="id", token_value_encrypted=protect_secret("management-secret"), enabled=True,
        )
        agent = models.ManagedAgent(agent_id="agent-1", name="Agent", status="active", skill_names_json="[]", prompt_names_json="[]")
        db.add_all([gateway, agent])
        db.flush()
        binding = ensure_binding(db, gateway, agent, client_id=None)
        assert "external-api-secret" not in binding.api_key_encrypted
        assert unprotect_secret(binding.api_key_encrypted) == "external-api-secret"
        assert binding.key_id == "key-1"
        assert binding_models(db, gateway, binding) == [{"id": "m-1", "name": "m-1"}, {"id": "m-2", "name": "m-2"}]
        assert json.loads(binding.available_models_json)[0]["id"] == "m-1"
        assert calls[0]["permissions"] == {"tools": []}


def test_external_task_payload_has_no_key_and_credential_endpoint_delivers_it(tmp_path):
    factory = _database(tmp_path)
    token = "client-runtime-token"
    with factory() as db:
        client = models.ManagedClient(
            client_id="host-1", name="Host", hostname="host", os="darwin", arch="arm64", client_version="1.0"
        )
        agent = models.ManagedAgent(
            agent_id="managed-1", name="Managed", status="active", skill_names_json="[]", prompt_names_json="[]"
        )
        gateway = models.ExternalAIGateway(
            name="gateway", management_base_url="http://mgmt.test:4005", model_base_url="http://model.test:8080",
            token_id="id", token_value_encrypted=protect_secret("management-secret"), enabled=True,
        )
        db.add_all([client, agent, gateway])
        db.flush()
        binding = models.ExternalGatewayAgentBinding(
            gateway_id=gateway.id, client_id=client.client_id, managed_agent_id=agent.agent_id,
            external_agent_id="external-1", key_id="key-1", api_key_encrypted=protect_secret("external-api-key"), status="active",
        )
        db.add(binding)
        db.flush()
        db.add(models.ClientAgent(
            client_id=client.client_id, local_agent_id="claude-code", agent_type="claude-code",
            managed_agent_id=agent.agent_id, capabilities_json='{"model_config_auto_apply":true}',
        ))
        task_payload = {
            "local_agent_id": "claude-code", "agent_type": "claude-code", "managed_agent_id": agent.agent_id,
            "model": "model-1", "source": "external_gateway", "gateway_id": gateway.id,
            "external_binding_id": binding.id, "model_base_url": gateway.model_base_url,
            "gateway_source": "external", "credential_source": "external_gateway",
            "credential_type": "external_gateway_api_key", "verification_mode": "client_call",
        }
        task = models.ClientTask(client_id=client.client_id, task_type="apply_model_config", payload_json=json.dumps(task_payload), status="running")
        db.add(task)
        db.add(models.AccessToken(
            name="client", token_type="client", token_hash=_hash_token(token), token_prefix=token[:8],
            scopes_json='["client:read-tasks"]', bound_client_id=client.client_id,
            allow_agent_credential_issuance=True, status="active",
        ))
        db.commit()
        task_id = task.id

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.include_router(clients.router, prefix="/api")
    response = TestClient(app).post(
        f"/api/v1/clients/host-1/tasks/{task_id}/agent-credential",
        headers={"Authorization": f"Bearer {token}"},
        json={"credential_source": "external_gateway"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["token"] == "external-api-key"
    assert response.json()["credential_type"] == "external_gateway_api_key"
    with factory() as db:
        stored = json.loads(db.get(models.ClientTask, task_id).payload_json)
        assert "external-api-key" not in json.dumps(stored)


def test_external_verification_failure_reports_restored_state(tmp_path):
    factory = _database(tmp_path)
    token = "client-runtime-token"
    with factory() as db:
        db.add(models.ManagedClient(
            client_id="host-1", name="Host", hostname="host", os="darwin", arch="arm64", client_version="1.0"
        ))
        db.add(models.ClientAgent(
            client_id="host-1", local_agent_id="claude-code", agent_type="claude-code",
            model_config_status="verifying", capabilities_json="{}",
        ))
        task = models.ClientTask(
            client_id="host-1", task_type="verify_model_config", status="running",
            payload_json=json.dumps({
                "local_agent_id": "claude-code", "agent_type": "claude-code", "model": "model-1",
                "gateway_source": "external", "credential_source": "external_gateway", "verification_mode": "client_call",
            }),
        )
        db.add(task)
        db.add(models.AccessToken(
            name="client", token_type="client", token_hash=_hash_token(token), token_prefix=token[:8],
            scopes_json='["client:read-tasks"]', bound_client_id="host-1", status="active",
        ))
        db.commit()
        task_id = task.id

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.include_router(clients.router, prefix="/api")
    response = TestClient(app).post(
        f"/api/v1/clients/host-1/tasks/{task_id}/result",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "failed", "error": "model_config.agent_response_missing", "restored_after_failure": True},
    )
    assert response.status_code == 200, response.text
    with factory() as db:
        assert db.get(models.ClientTask, task_id).status == "failed"
        assert db.query(models.ClientAgent).filter_by(client_id="host-1").one().model_config_status == "restored"


def test_gateway_key_inventory_is_masked_and_reveal_requires_password(tmp_path):
    factory = _database(tmp_path)
    password = "strong-password"
    user = models.User(
        id=1,
        username="root",
        hashed_password=auth.get_password_hash(password),
        role="super_admin",
        is_active=True,
    )
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway",
            management_base_url="http://mgmt.test:4005",
            model_base_url="http://model.test:8080",
            token_id="id",
            token_value_encrypted=protect_secret("management-secret"),
            enabled=True,
        )
        agent = models.ManagedAgent(
            agent_id="managed-1",
            name="Managed Agent",
            channel="Codex",
            status="active",
            skill_names_json="[]",
            prompt_names_json="[]",
        )
        db.add_all([gateway, agent])
        db.flush()
        binding = models.ExternalGatewayAgentBinding(
            gateway_id=gateway.id,
            managed_agent_id=agent.agent_id,
            external_agent_id="external-1",
            key_id="key-1",
            api_key_encrypted=protect_secret("rsgw_sk_plain-secret-value"),
            available_models_json='[{"id":"model-1"}]',
            status="active",
        )
        db.add(binding)
        db.commit()
        gateway_id = gateway.id
        binding_id = binding.id

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: user
    app.include_router(external_ai_gateways.router, prefix="/api")
    api = TestClient(app)

    listed = api.get(f"/api/v1/external-ai-gateways/{gateway_id}/agent-keys")
    assert listed.status_code == 200
    assert listed.json()[0]["managed_agent_name"] == "Managed Agent"
    assert listed.json()[0]["model_count"] == 1
    assert "plain-secret-value" not in listed.text

    denied = api.post(
        f"/api/v1/external-ai-gateways/{gateway_id}/agent-keys/{binding_id}/reveal",
        json={"password": "wrong-password"},
    )
    assert denied.status_code == 403
    revealed = api.post(
        f"/api/v1/external-ai-gateways/{gateway_id}/agent-keys/{binding_id}/reveal",
        json={"password": password},
    )
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["api_key"] == "rsgw_sk_plain-secret-value"
    assert revealed.headers["cache-control"] == "no-store"


def test_platform_agent_prepares_external_catalog_without_client(tmp_path, monkeypatch):
    factory = _database(tmp_path)
    user = models.User(id=1, username="root", hashed_password="x", role="super_admin", is_active=True)
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway",
            management_base_url="http://mgmt.test:4005",
            model_base_url="http://model.test:8080",
            token_id="id",
            token_value_encrypted=protect_secret("management-secret"),
            enabled=True,
        )
        db.add(gateway)
        db.commit()
        gateway_id = gateway.id

    def fake_ensure(db, gateway, agent, *, client_id):
        assert client_id is None
        binding = models.ExternalGatewayAgentBinding(
            gateway_id=gateway.id,
            client_id=None,
            managed_agent_id=agent.agent_id,
            external_agent_id="external-platform-agent",
            key_id="key-platform",
            api_key_encrypted=protect_secret("external-api-key"),
            status="active",
        )
        db.add(binding)
        db.flush()
        return binding

    def fake_models(db, gateway, binding):
        catalog = [{"id": "external-model-1", "name": "external-model-1"}]
        binding.available_models_json = json.dumps(catalog)
        db.flush()
        return catalog

    monkeypatch.setattr("backend.routers.agents.ensure_binding", fake_ensure)
    monkeypatch.setattr("backend.routers.agents.binding_models", fake_models)

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: user
    app.include_router(agents.router, prefix="/api")
    api = TestClient(app)
    draft = api.post("/api/agents", json={
        "agent_id": "platform-agent",
        "name": "Platform Agent",
        "channel": "Codex",
        "status": "draft",
        "default_model_source": "external_gateway",
        "external_gateway_id": gateway_id,
    })
    assert draft.status_code == 200, draft.text
    catalog = api.post(
        f"/api/agents/{draft.json()['id']}/external-model-catalog",
        json={"gateway_id": gateway_id},
    )
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["models"][0]["id"] == "external-model-1"
    saved = api.put(f"/api/agents/{draft.json()['id']}", json={
        "status": "active",
        "default_model": "external-model-1",
        "default_model_source": "external_gateway",
        "external_gateway_id": gateway_id,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["external_gateway_name"] == "gateway"


def test_agent_runtime_credential_resolves_external_gateway_key(tmp_path):
    factory = _database(tmp_path)
    runtime_token = "amat_runtime-token"
    with factory() as db:
        gateway = models.ExternalAIGateway(
            name="gateway",
            management_base_url="http://mgmt.test:4005",
            model_base_url="http://model.test:8080",
            token_id="id",
            token_value_encrypted=protect_secret("management-secret"),
            enabled=True,
        )
        db.add(gateway)
        db.flush()
        agent = models.ManagedAgent(
            agent_id="platform-agent",
            name="Platform Agent",
            channel="Codex",
            status="active",
            default_model="external-model-1",
            default_model_source="external_gateway",
            external_gateway_id=gateway.id,
            skill_names_json="[]",
            prompt_names_json="[]",
        )
        db.add(agent)
        db.flush()
        db.add_all([
            models.ExternalGatewayAgentBinding(
                gateway_id=gateway.id,
                managed_agent_id=agent.agent_id,
                external_agent_id="external-platform-agent",
                key_id="key-platform",
                api_key_encrypted=protect_secret("external-api-key"),
                status="active",
            ),
            models.AccessToken(
                name="runtime",
                token_type="agent_runtime",
                token_hash=_hash_token(runtime_token),
                token_prefix=runtime_token[:8],
                scopes_json='["model:chat"]',
                bound_agent_id=agent.agent_id,
                allowed_models_json='["external-model-1"]',
                allowed_ips_json="[]",
                status="active",
            ),
        ])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_db
    app.include_router(external_ai_gateways.runtime_router, prefix="/api")
    response = TestClient(app).get(
        "/api/v1/runtime/external-model/credential",
        headers={"Authorization": f"Bearer {runtime_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["api_key"] == "external-api-key"
    assert response.json()["model"] == "external-model-1"
    assert response.headers["cache-control"] == "no-store"
