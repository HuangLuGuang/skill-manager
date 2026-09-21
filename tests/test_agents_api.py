import json
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.routers import access_tokens, agents, clients
from backend.sqlite_db import Base, get_db


def _client(tmp_path, *, username: str = "admin", role: str = "admin"):
    engine = create_engine(f"sqlite:///{tmp_path / 'agents.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    group = models.UserGroup(name="风控部", description="风险运营团队")
    db.add(group)
    db.commit()
    db.refresh(group)
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username=username,
        hashed_password="x",
        role=role,
    )
    app.include_router(agents.router)
    app.include_router(access_tokens.router, prefix="/api/v1")
    return TestClient(app), group.id


def test_create_list_and_update_department_agent(tmp_path):
    client, group_id = _client(tmp_path)

    response = client.post(
        "/agents",
        json={
            "agent_id": "risk-screening-agent",
            "name": "风险筛查智能体",
            "department_group_id": group_id,
            "owner": "风控部",
            "description": "用于客户风险初筛",
            "channel": "OpenClaw",
            "default_model": "deepseek-chat",
            "skill_names": ["risk-screening-deep-trace"],
            "prompt_names": ["risk-screening-system-v1"],
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["agent_id"] == "risk-screening-agent"
    assert created["department_name"] == "风控部"
    assert created["skill_names"] == ["risk-screening-deep-trace"]
    assert created["origin_type"] == "platform"

    list_response = client.get("/agents", params={"department_group_id": group_id})
    assert list_response.status_code == 200
    rows = list_response.json()
    assert [row["agent_id"] for row in rows] == ["risk-screening-agent"]

    update_response = client.put(
        f"/agents/{created['id']}",
        json={
            "status": "disabled",
            "skill_names": ["risk-screening-deep-trace", "raw-log-threat-hunting"],
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "disabled"
    assert updated["skill_names"] == ["risk-screening-deep-trace", "raw-log-threat-hunting"]


def test_agents_are_scoped_to_creator(tmp_path):
    client, group_id = _client(tmp_path, username="alice")
    response = client.post(
        "/agents",
        json={"agent_id": "alice-agent", "name": "Alice Agent", "department_group_id": group_id},
    )
    assert response.status_code == 200
    assert response.json()["created_by"] == "alice"

    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=2,
        username="bob",
        hashed_password="x",
        role="admin",
    )
    other_response = client.post(
        "/agents",
        json={"agent_id": "bob-agent", "name": "Bob Agent", "department_group_id": group_id},
    )
    assert other_response.status_code == 200

    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username="alice",
        hashed_password="x",
        role="admin",
    )
    alice_rows = client.get("/agents").json()
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=2,
        username="bob",
        hashed_password="x",
        role="admin",
    )
    bob_rows = client.get("/agents").json()

    assert [row["agent_id"] for row in alice_rows] == ["alice-agent"]
    assert [row["agent_id"] for row in bob_rows] == ["bob-agent"]


def test_create_agent_rejects_unknown_department(tmp_path):
    client, _group_id = _client(tmp_path)

    response = client.post(
        "/agents",
        json={"agent_id": "unknown-dept-agent", "name": "未知部门智能体", "department_group_id": 999},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "部门不存在"


def test_agent_identity_is_immutable_while_credentials_are_bound(tmp_path):
    client, group_id = _client(tmp_path)
    agent = client.post(
        "/agents",
        json={"agent_id": "bound-agent", "name": "Bound Agent", "department_group_id": group_id},
    ).json()
    credential = client.post(
        "/api/v1/access/tokens",
        json={"name": "bound-runtime", "token_type": "agent_runtime", "bound_agent_id": "bound-agent"},
    )
    assert credential.status_code == 200

    fetched = client.get("/agents").json()[0]
    assert fetched["runtime_token_id"] == credential.json()["record"]["id"]
    assert fetched["runtime_token_name"] == "bound-runtime"

    renamed = client.put(f"/agents/{agent['id']}", json={"agent_id": "renamed-agent"})
    assert renamed.status_code == 409
    assert renamed.json()["error_code"] == "agent.id_bound_to_credentials"

    deleted = client.delete(f"/agents/{agent['id']}")
    assert deleted.status_code == 409
    assert deleted.json()["error_code"] == "agent.credentials_still_bound"


def test_asset_list_merges_existing_instances_and_auto_registered_client_agents(tmp_path):
    client, group_id = _client(tmp_path)
    platform_agent = client.post(
        "/agents",
        json={
            "agent_id": "contract-review-agent",
            "name": "合同审查助手",
            "department_group_id": group_id,
            "channel": "Claude Code",
        },
    ).json()
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedClient(
            client_id="huanglg-4",
            name="huanglg-4.local",
            hostname="huanglg-4.local",
            os="darwin",
            arch="arm64",
            client_version="1.0.0",
            registered_by="admin",
            last_seen_at=datetime.utcnow(),
        )
    )
    database.add_all(
        [
            models.ClientAgent(
                client_id="huanglg-4",
                local_agent_id="claude-code",
                agent_type="Claude Code",
                managed_agent_id="contract-review-agent",
                agent_version="1.2.3",
                install_path="/Applications/Claude.app",
                skills_path="/Users/admin/.claude/skills",
                takeover_status="managed",
            ),
            models.ClientAgent(
                client_id="huanglg-4",
                local_agent_id="codex",
                agent_type="Codex",
                agent_version="0.49.0",
                install_path="/Applications/Codex.app",
                skills_path="/Users/admin/.codex/skills",
            ),
            models.ClientSkillInstall(
                client_id="huanglg-4",
                agent_type="Claude Code",
                skill_name="contract-reader",
                skill_path="/Users/admin/.claude/skills/contract-reader",
                status="verified",
            ),
            models.ClientSkillInstall(
                client_id="huanglg-4",
                agent_type="Codex",
                skill_name="ppt-master",
                skill_path="/Users/admin/.codex/skills/ppt-master",
                status="verified",
            ),
        ]
    )
    database.commit()
    host = database.query(models.ManagedClient).filter_by(client_id="huanglg-4").one()
    assert clients.ensure_client_inventory_identities(database, host, owner="admin") == 1
    database.commit()

    response = client.get("/agents/assets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stats"] == {"total": 2, "platform": 1, "client_discovery": 1}
    assert len(payload["items"]) == 2
    managed = next(item for item in payload["items"] if item["agent_id"] == "contract-review-agent")
    discovered = next(item for item in payload["items"] if item["origin_type"] == "client_discovery")
    assert managed["managed_agent_pk"] == platform_agent["id"]
    assert managed["origin_type"] == "platform"
    assert managed["instance_count"] == 1
    assert managed["instances"][0]["local_agent_id"] == "claude-code"
    assert managed["instances"][0]["skills"][0]["name"] == "contract-reader"
    assert discovered["agent_id"].startswith("client-huanglg-4-codex-")
    assert discovered["discovered_skill_count"] == 1
    stored = database.query(models.ClientAgent).filter_by(client_id="huanglg-4", local_agent_id="codex").one()
    assert stored.managed_agent_id == discovered["agent_id"]
    assert stored.takeover_status == "managed"
    managed_identity = database.query(models.ManagedAgent).filter_by(agent_id=discovered["agent_id"]).one()
    assert managed_identity.origin_type == "client_discovery"

    external_gateway = models.ExternalAIGateway(
        name="北京联通 AI 网关",
        management_base_url="http://gateway.example.test:4005",
        model_base_url="http://gateway.example.test:8080/",
        token_id="test-token-id",
        token_value_encrypted="encrypted-test-token",
        created_by="admin",
    )
    database.add(external_gateway)
    database.flush()
    database.add(
        models.ExternalGatewayAgentBinding(
            gateway_id=external_gateway.id,
            client_id="huanglg-4",
            managed_agent_id=discovered["agent_id"],
            external_agent_id="client-huanglg-4-codex",
            key_id="key-codex",
            api_key_encrypted="encrypted-test-key",
        )
    )
    stored.capabilities_json = json.dumps(
        {
            "model_config_auto_apply": True,
            "model_config_state": {
                "model": "deepseek-v4-flash",
                "gateway_url": "http://gateway.example.test:8080/v1",
                "gateway_source": "external",
                "credential_source": "external_gateway",
            },
        }
    )
    database.commit()

    refreshed = client.get("/agents/assets").json()
    refreshed_discovered = next(item for item in refreshed["items"] if item["origin_type"] == "client_discovery")
    assert refreshed_discovered["external_gateway_id"] == external_gateway.id
    assert refreshed_discovered["external_gateway_name"] == "北京联通 AI 网关"

    identity_update = client.put(
        f"/agents/{discovered['managed_agent_pk']}",
        json={"agent_id": "manual-replacement"},
    )
    assert identity_update.status_code == 409
    assert identity_update.json()["error_code"] == "agent.client_identity_immutable"
    identity_delete = client.delete(f"/agents/{discovered['managed_agent_pk']}")
    assert identity_delete.status_code == 409
    assert identity_delete.json()["error_code"] == "agent.client_managed"
    database.close()
