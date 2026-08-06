from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from agent_manager.api import scanner_router
from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.routers import access_tokens, agents
from backend.sqlite_db import Base, get_db


class _Runtime:
    def can_load(self, skill_name, agent_id=None, **_kwargs):
        entry = type("Entry", (), {"status": type("Status", (), {"value": "APPROVED"})(), "risk_level": None})()
        return True, entry, "allowed"


class _Registry:
    def log_event(self, _event):
        return None


class _Manager:
    runtime = _Runtime()
    registry = _Registry()

    def get_skill(self, skill_name):
        if skill_name != "risk-skill":
            return None
        return type(
            "Skill",
            (),
            {"skill_id": "risk-skill-id", "name": "risk-skill"},
        )()

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
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username="admin",
        hashed_password="x",
        role="super_admin",
    )
    app.dependency_overrides[scanner_router.get_manager] = lambda: _Manager()
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(agents.router)
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
    assert body["record"]["prompt_guard_mode"] == "block"

    listed = client.get("/api/v1/access/tokens")
    assert listed.status_code == 200
    rows = listed.json()["items"]
    assert len(rows) == 1
    assert rows[0]["token"] is None
    assert rows[0]["token_hash"] is None
    assert rows[0]["token_prefix"] == body["record"]["token_prefix"]


def test_agent_runtime_can_explicitly_select_non_blocking_prompt_guard(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "temporary-audit-only",
            "token_type": "agent_runtime",
            "prompt_guard_mode": "warn",
        },
    )

    assert created.status_code == 200
    assert created.json()["record"]["prompt_guard_mode"] == "warn"


def test_last_used_lock_does_not_block_token_authentication():
    row = models.AccessToken(id=1, name="client", token_hash="hash", token_prefix="amat_test")

    class LockedSession:
        rolled_back = False

        def commit(self):
            raise OperationalError("UPDATE access_tokens", {}, Exception("database is locked"))

        def refresh(self, _row):
            raise AssertionError("locked writes must not refresh")

        def rollback(self):
            self.rolled_back = True

    db = LockedSession()
    assert access_tokens._touch_last_used(db, row) is row
    assert db.rolled_back is True


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


def test_agent_runtime_token_allows_skill_id_binding(tmp_path):
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

    response = client.put(
        "/agents/1",
        json={"skill_names": ["risk-skill-id"]},
    )
    assert response.status_code == 200

    allowed = client.get(
        "/api/v1/access/runtime/can-load/risk-skill",
        headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "risk-agent"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True


def test_runtime_missing_scope_error_identifies_token(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "scanner-only",
            "token_type": "scanner",
            "scopes": ["scanner:submit"],
        },
    ).json()

    response = client.post(
        "/api/v1/access/runtime/verify-skill-signature",
        headers={"Authorization": f"Bearer {created['token']}"},
        json={
            "skill_name": "risk-skill",
            "agent_id": "risk-agent",
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail == "接入凭证缺少权限: runtime:verify-signature"
    assert "scanner-only" not in detail
    assert created["record"]["token_prefix"] not in detail


def test_create_rejects_scope_for_wrong_token_type(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "scanner-with-runtime-scope",
            "token_type": "scanner",
            "scopes": ["runtime:can-load"],
        },
    )

    assert created.status_code == 400
    assert created.json()["error_code"] == "credential.scope_type_mismatch"


def test_allowed_models_require_model_capable_type_and_scope(tmp_path):
    client = _client(tmp_path)

    scanner = client.post(
        "/api/v1/access/tokens",
        json={"name": "scanner", "token_type": "scanner", "allowed_models": ["gpt-test"]},
    )
    assert scanner.status_code == 400
    assert scanner.json()["error_code"] == "credential.models_not_applicable"

    runtime_without_chat = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "runtime-no-chat",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "allowed_models": ["gpt-test"],
        },
    )
    assert runtime_without_chat.status_code == 400
    assert runtime_without_chat.json()["error_code"] == "credential.models_not_applicable"

    runtime_with_chat = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "runtime-chat",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "scopes": ["runtime:can-load", "model:chat"],
            "allowed_models": ["gpt-test"],
        },
    )
    assert runtime_with_chat.status_code == 200
    assert runtime_with_chat.json()["record"]["allowed_models"] == ["gpt-test"]


def test_removing_model_scope_clears_allowed_models(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "runtime-chat",
            "token_type": "agent_runtime",
            "bound_agent_id": "risk-agent",
            "scopes": ["runtime:can-load", "model:chat"],
            "allowed_models": ["gpt-test"],
        },
    ).json()

    updated = client.put(
        f"/api/v1/access/tokens/{created['record']['id']}",
        json={"scopes": ["runtime:can-load"]},
    )

    assert updated.status_code == 200
    assert updated.json()["allowed_models"] == []


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
