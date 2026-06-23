from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_manager.api import scanner_router
from backend import auth, models
from backend.routers import access_tokens
from backend.sqlite_db import Base, get_db


class _Runtime:
    def can_load(self, skill_name, agent_id=None):
        entry = type("Entry", (), {"status": type("Status", (), {"value": "APPROVED"})(), "risk_level": None})()
        return True, entry, "allowed"


class _Manager:
    runtime = _Runtime()

    def get_prompt(self, prompt_name):
        if prompt_name != "risk-prompt":
            return None
        return type(
            "Prompt",
            (),
            {"status": type("Status", (), {"value": "APPROVED"})(), "is_loadable": lambda self: True},
        )()


def _client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'access.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    group = models.UserGroup(name="风控部")
    db.add(group)
    db.flush()
    db.add(
        models.ManagedAgent(
            agent_id="risk-agent",
            name="风险智能体",
            department_group_id=group.id,
            status="active",
            skill_names_json='["risk-skill"]',
            prompt_names_json='["risk-prompt"]',
        )
    )
    db.add(
        models.ManagedAgent(
            agent_id="disabled-agent",
            name="停用智能体",
            department_group_id=group.id,
            status="disabled",
            skill_names_json='["risk-skill"]',
            prompt_names_json="[]",
        )
    )
    db.commit()
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username="admin",
        hashed_password="x",
        role="super_admin",
    )
    app.dependency_overrides[scanner_router.get_manager] = lambda: _Manager()
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(scanner_router.runtime_router)
    return TestClient(app)


def test_create_access_token_returns_plaintext_once_and_lists_masked_record(tmp_path):
    client = _client(tmp_path)

    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "risk-agent-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "scopes": ["runtime:can-load"],
            "expires_at": (datetime.utcnow() + timedelta(days=1)).isoformat(),
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["token"].startswith("amat_")
    assert body["record"]["token_hash"] is None
    assert body["record"]["bound_agent_id"] == "risk-agent"
    assert body["record"]["scopes"] == ["runtime:can-load"]

    listed = client.get("/api/v1/access/tokens")
    assert listed.status_code == 200
    rows = listed.json()["items"]
    assert len(rows) == 1
    assert rows[0]["token"] is None
    assert rows[0]["token_hash"] is None
    assert rows[0]["token_prefix"] == body["record"]["token_prefix"]


def test_agent_runtime_token_enforces_bound_agent_and_allowed_skill(tmp_path):
    client = _client(tmp_path)
    token = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "risk-agent-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "scopes": ["runtime:can-load"],
        },
    ).json()["token"]

    allowed = client.get(
        "/api/v1/access/runtime/can-load/risk-skill",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "risk-agent"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True

    wrong_agent = client.get(
        "/api/v1/access/runtime/can-load/risk-skill",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "other-agent"},
    )
    assert wrong_agent.status_code == 403
    assert "绑定的智能体" in wrong_agent.json()["detail"]

    unbound_skill = client.get(
        "/api/v1/access/runtime/can-load/other-skill",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "risk-agent"},
    )
    assert unbound_skill.status_code == 403
    assert "未授权使用该 Skill" in unbound_skill.json()["detail"]

    disabled_token = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "disabled-agent-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": "disabled-agent",
            "scopes": ["runtime:can-load"],
        },
    ).json()["token"]
    disabled = client.get(
        "/api/v1/access/runtime/can-load/risk-skill",
        headers={"Authorization": f"Bearer {disabled_token}", "X-Agent-ID": "disabled-agent"},
    )
    assert disabled.status_code == 403
    assert "未启用" in disabled.json()["detail"]


def test_agent_runtime_token_enforces_bound_prompt(tmp_path):
    client = _client(tmp_path)
    token = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "risk-agent-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "scopes": ["runtime:can-load"],
        },
    ).json()["token"]

    allowed = client.get(
        "/api/v1/access/runtime/can-load-prompt/risk-prompt",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "risk-agent"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True

    unbound = client.get(
        "/api/v1/access/runtime/can-load-prompt/other-prompt",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "risk-agent"},
    )
    assert unbound.status_code == 403
    assert "未授权使用该 Prompt" in unbound.json()["detail"]
