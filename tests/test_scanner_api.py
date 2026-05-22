import io
import json
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

import agent_manager.api.router as api_router
from agent_manager.api.router import get_manager
from agent_manager.api.scanner_router import _scanner_release_dir, admin_router, router, runtime_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.registry import make_event
from agent_manager.core.signer import compute_signature


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
