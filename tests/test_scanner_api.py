import io
import json
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_manager.api.router as api_router
from agent_manager.api.router import get_manager
from agent_manager.api.scanner_router import _scanner_release_dir, admin_router, router, runtime_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.registry import make_event
from agent_manager.core.signer import compute_signature
from backend import models
from backend.routers.access_tokens import _hash_token
from backend.sqlite_db import Base, get_db


def _skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: api-skill\ndescription: API test\n---\n")
    return buffer.getvalue()


def test_scanner_import_requires_token(tmp_path):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/scanner/imports",
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
    )

    assert response.status_code == 401


def test_scanner_release_dir_points_to_project_scanner_releases():
    assert (_scanner_release_dir().parent / "go.mod").exists()
    assert _scanner_release_dir().name == "releases"


def _assert_skill_verifier_zip(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
    assert "agent-manager-skill-verifier/SKILL.md" in names
    assert "agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py" in names
    assert "agent-manager-skill-verifier/scripts/agent_manager_skill_guard.py" in names


def test_skill_verifier_download_returns_zip():
    app = FastAPI()
    app.include_router(admin_router)
    client = TestClient(app)

    response = client.get("/api/v1/scanner/skill-verifier/download")

    assert response.status_code == 200
    _assert_skill_verifier_zip(response.content)


def test_skill_guard_download_legacy_alias_returns_zip():
    app = FastAPI()
    app.include_router(admin_router)
    client = TestClient(app)

    response = client.get("/api/v1/scanner/skill-guard/download")

    assert response.status_code == 200
    _assert_skill_verifier_zip(response.content)


def test_scanner_import_accepts_scanner_token(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.include_router(admin_router)
        app.include_router(router)
        client = TestClient(app)

        token_response = client.post("/api/v1/scanner/tokens", json={"name": "customer-a"})
        assert token_response.status_code == 200
        token = token_response.json()["token"]

        response = client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
            data={
                "manifest": json.dumps({"fingerprint": None}),
                "use_behavioral": "false",
                "use_llm": "false",
                "use_sandbox": "false",
            },
        )

        assert response.status_code == 400
        assert "fingerprint mismatch" in response.json()["detail"].lower()

        response = client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["name"] == "api-skill"
        assert payload["status"] == "PENDING"
    finally:
        api_router._manager = previous_manager


def test_access_runtime_routes_accept_runtime_token(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: runtime-skill\ndescription: Runtime test\n---\n", encoding="utf-8")
    entry = manager.submit(skill_dir)

    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.include_router(admin_router)
        app.include_router(runtime_router)
        client = TestClient(app)

        token_response = client.post(
            "/api/v1/scanner/tokens",
            json={
                "name": "agent-runtime",
                "scopes": ["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"],
            },
        )
        assert token_response.status_code == 200
        token = token_response.json()["token"]

        verify_response = client.post(
            "/api/v1/access/runtime/verify-skill-signature",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "skill_name": "runtime-skill",
                "skill_id": entry.skill_id,
                "local_signature": compute_signature(skill_dir),
                "agent_id": "agno-demo",
            },
        )
        assert verify_response.status_code == 200
        assert verify_response.json()["allowed"] is True

        can_load_response = client.get(
            "/api/v1/access/runtime/can-load/runtime-skill",
            headers={"Authorization": f"Bearer {token}"},
            params={"agent_id": "agno-demo"},
        )
        assert can_load_response.status_code == 200
        assert can_load_response.json()["allowed"] is True

        path_response = client.get(
            "/api/v1/access/runtime/can-load/runtime-skill",
            headers={"Authorization": f"Bearer {token}"},
            params={"skill_path": str(skill_dir)},
        )
        assert path_response.status_code == 400
    finally:
        api_router._manager = previous_manager


def test_runtime_unauthorized_skill_is_audited(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'access.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    token = "amat_runtime_test"
    db = TestingSessionLocal()
    db.add(
        models.ManagedAgent(
            agent_id="risk-agent",
            name="风险智能体",
            status="active",
            skill_names_json="[]",
            prompt_names_json="[]",
        )
    )
    db.add(
        models.AccessToken(
            name="risk-runtime",
            token_type="agent_runtime",
            token_hash=_hash_token(token),
            token_prefix=token[:8],
            bound_agent_id="risk-agent",
            scopes_json='["runtime:verify-signature"]',
            allowed_models_json="[]",
            allowed_ips_json="[]",
            status="active",
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
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: blocked-skill\ndescription: Runtime test\n---\n", encoding="utf-8")
    entry = manager.submit(skill_dir)

    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.dependency_overrides[get_db] = override_get_db
        app.include_router(runtime_router)
        client = TestClient(app)

        response = client.post(
            "/api/v1/access/runtime/verify-skill-signature",
            headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "10.1.2.3"},
            json={
                "skill_name": "blocked-skill",
                "skill_id": entry.skill_id,
                "local_signature": compute_signature(skill_dir),
                "agent_id": "risk-agent",
            },
        )

        assert response.status_code == 403
        events = manager.audit(skill_id=entry.skill_id, limit=20)
        blocked = [event for event in events if event.event_type == "skill_load_blocked"]
        assert blocked
        assert blocked[0].actor == "risk-agent"
        assert blocked[0].details["reason"] == "智能体未授权使用该 Skill"
        assert blocked[0].details["client_ip"] == "10.1.2.3"
        assert blocked[0].details["token_name"] == "risk-runtime"
    finally:
        api_router._manager = previous_manager


def test_audit_accepts_comma_separated_event_types(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: audit-skill\ndescription: Audit test\n---\n", encoding="utf-8")
    entry = manager.create_pending_submission(skill_dir, source=SourceInfo(origin=SkillOrigin.LOCAL))
    manager.registry.log_event(make_event("skill_load_allowed", entry))
    manager.registry.log_event(make_event("tool_blocked", entry))
    manager.registry.log_event(make_event("skill_processing_completed", entry))

    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.include_router(api_router.router)
        client = TestClient(app)

        response = client.get(
            "/api/v1/audit",
            params={
                "event_types": "skill_load_allowed,tool_blocked",
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert {item["event_type"] for item in payload["items"]} == {"skill_load_allowed", "tool_blocked"}
    finally:
        api_router._manager = previous_manager
