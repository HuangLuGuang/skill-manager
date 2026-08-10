from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.routers import access_tokens, agents
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
