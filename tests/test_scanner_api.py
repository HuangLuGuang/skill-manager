import hashlib
import io
import json
import os
import zipfile
import pytest
from pathlib import Path

from fastapi import HTTPException, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_manager.api.router as api_router
import agent_manager.api.scanner_router as scanner_api
from agent_manager.api.router import get_manager
from agent_manager.api.router import runtime_router as agent_runtime_router
from agent_manager.api.scanner_router import (
    ScannerAuthContext,
    _fingerprint_skill_dir,
    _scanner_release_dir,
    admin_router,
    get_scanner_import,
    router,
    runtime_router,
)
from agent_manager.core.llm import LLMConfig
from agent_manager.core.manager import AgentManager
from agent_manager.core.models import SkillOrigin, SkillStatus, SourceInfo
from agent_manager.core.policy import CompanyPolicy
from agent_manager.core.registry import make_event
from agent_manager.core.signer import compute_content_digest
from agent_manager.core.scanner_tokens import ScannerTokenStore
from backend import models
from backend.api_errors import ApiError, api_error_handler
from backend.routers.access_tokens import _hash_token
from backend.sqlite_db import Base, get_db


def _skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: api-skill\ndescription: API test\n---\n")
    return buffer.getvalue()


def test_scanner_requested_llm_disabled_is_consistent_in_reports(tmp_path, monkeypatch):
    class ImmediateExecutor:
        def submit(self, callback, *args):
            callback(*args)

    manager = AgentManager(
        policy=CompanyPolicy({"require_sandbox_for_risk": []}),
        data_dir=tmp_path / "data",
    )
    monkeypatch.setattr(api_router, "_scan_executor", ImmediateExecutor())
    monkeypatch.setattr(LLMConfig, "load", lambda: LLMConfig(enabled=False))
    monkeypatch.setattr(
        "agent_manager.core.vetting._run_scanner",
        lambda *_: {"findings": [], "max_severity": "SAFE"},
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_manager] = lambda: manager
    client = TestClient(app)
    _, token = ScannerTokenStore(manager.registry.data_dir).create(name="llm-disabled")
    response = client.post(
        "/api/v1/scanner/imports",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        data={"use_llm": "true"},
    )
    assert response.status_code == 200
    entry = manager.get_skill(response.json()["version_id"])
    assert entry.scan_options["use_llm"] is True
    assert entry.vetting.scan_report["analyzer_timings"]["llm"]["status"] == "disabled"
    summary = manager.list_skill_summaries(page=1, page_size=10)["items"][0]
    assert summary["analysis_results"]["llm"] == {"status": "disabled", "risk_level": None}
    assert api_router._version_summary(entry)["risk_chain"]["llm_status"] == "disabled"
    read_response = client.get(
        f"/api/v1/scanner/imports/{entry.skill_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert read_response.status_code == 200
    notes = read_response.json()["vetting"]["policy_notes"]
    assert not any("[LLM] analysis skipped:" in note for note in notes)
    # 摘要须优先使用本次状态，不能被旧版策略备注推断覆盖。
    entry.vetting.policy_notes = ["[LLM] analysis skipped: upstream unavailable"]
    for state in ("failed", "skipped", "disabled", "completed"):
        entry.vetting.scan_report["analyzer_timings"]["llm"]["status"] = state
        assert api_router._version_summary(entry)["risk_chain"]["llm_status"] == state


def test_scanner_fingerprint_orders_relative_paths_like_go(tmp_path):
    skill_dir = tmp_path / "skill"
    contents = {
        "SKILL.md": b"name: example\n",
        "scripts/pptx_to_svg/__init__.py": b"package",
        "scripts/pptx_to_svg.py": b"script",
        "templates/a/item.svg": b"svg",
        "templates/a-b.svg": b"sibling",
        "templates/中文.svg": b"unicode",
    }
    expected_hash = hashlib.sha256()
    for name in sorted(contents):
        content = contents[name]
        path = skill_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        expected_hash.update(f"{name}\0{len(content)}\0{digest}\0".encode())
    expected = "sha256:" + expected_hash.hexdigest()
    result = _fingerprint_skill_dir(skill_dir)
    assert result["fingerprint"] == expected
    assert [item["path"] for item in result["files"]] == sorted(contents)
    (skill_dir / "scripts/pptx_to_svg.py").write_bytes(b"changed")
    assert _fingerprint_skill_dir(skill_dir)["fingerprint"] != expected


def test_scanner_import_requires_token(tmp_path):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/scanner/imports",
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
    )

    assert response.status_code == 401


def test_scanner_nested_zip_verifies_transport_before_expanding_analysis(tmp_path, monkeypatch):
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_manager] = lambda: manager
    _, token = ScannerTokenStore(manager.registry.data_dir).create(name="nested-zip")
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: api-skill\ndescription: nested archive test\n---\n")
    with zipfile.ZipFile(source / "templates.zip", "w") as nested:
        nested.writestr("template.txt", "nested evidence")
    manifest = _fingerprint_skill_dir(source)
    manifest["name"] = "api-skill"
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for file in source.iterdir():
            archive.writestr(file.name, file.read_bytes())
    # Exercise the real import route and persistence, without starting analyzers.
    class IdleExecutor:
        def submit(self, *args, **kwargs):
            return None
    monkeypatch.setattr(api_router, "_scan_executor", IdleExecutor())
    monkeypatch.setattr(scanner_api, "_scan_executor", IdleExecutor())
    monkeypatch.setattr(api_router, "_manager", manager)
    client = TestClient(app)
    def submit(fingerprint):
        return client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", payload.getvalue(), "application/zip")},
            data={"manifest": json.dumps({**manifest, "fingerprint": fingerprint}), "use_llm": "false", "use_sandbox": "false"},
        )
    rejected = submit("sha256:" + "0" * 64)
    assert rejected.status_code == 400
    assert "fingerprint mismatch" in rejected.json()["detail"].lower()
    accepted = submit(manifest["fingerprint"])
    assert accepted.status_code == 200, accepted.text
    entry = manager.get_skill(accepted.json()["version_id"])
    expanded = list(Path(entry.skill_path).rglob("template.txt"))
    assert expanded == []
    assert _fingerprint_skill_dir(Path(entry.skill_path)) == _fingerprint_skill_dir(source)
    files = api_router.list_skill_files(entry.skill_id, mgr=manager)
    assert {file.path for file in files.files} == {"SKILL.md", "templates.zip"}
    preview = api_router.get_skill_file_content(entry.skill_id, path="SKILL.md", mgr=manager)
    assert preview.content == (source / "SKILL.md").read_text()
    with pytest.raises(HTTPException) as missing:
        api_router.get_skill_file_content(entry.skill_id, path="templates/template.txt", mgr=manager)
    assert missing.value.status_code == 404
    retried = submit(manifest["fingerprint"])
    assert retried.status_code == 200
    assert retried.json()["version_id"] == accepted.json()["version_id"]


def test_scanner_release_dir_points_to_project_scanner_releases():
    assert (_scanner_release_dir().parent / "go.mod").exists()
    assert _scanner_release_dir().name == "releases"


def test_runtime_exposes_ed25519_public_key():
    app = FastAPI()
    app.include_router(agent_runtime_router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/runtime/signing-public-key")

    assert response.status_code == 200
    payload = response.json()
    assert payload["algorithm"] == "Ed25519"
    assert payload["key_id"]
    assert payload["public_key"]


def test_runtime_public_key_endpoint_does_not_create_private_key():
    private_key_path = Path(os.environ["AGENT_MANAGER_SIGNING_PRIVATE_KEY_PATH"])
    private_key_path.unlink()
    app = FastAPI()
    app.include_router(agent_runtime_router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/runtime/signing-public-key")

    assert response.status_code == 503
    assert response.json()["detail"] == "signing public key is not initialized"
    assert not private_key_path.exists()


def _assert_skill_verifier_zip(content: bytes):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = set(archive.namelist())
    assert "agent-manager-skill-verifier/SKILL.md" in names
    assert "agent-manager-skill-verifier/scripts/agent_manager_skill_verifier.py" in names
    assert "agent-manager-skill-verifier/scripts/agent_manager_skill_guard.py" not in names


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

        _record, token = ScannerTokenStore(manager.registry.data_dir).create(name="customer-a")

        response = client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
            data={"manifest": json.dumps({"root": "/opt/skills/claw-and-order", "name": ""})},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "SKILL.md 缺少 name 字段（格式：name: your-skill-name）"

        response = client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
            data={
                "manifest": json.dumps({"name": "api-skill", "fingerprint": None}),
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


def test_scanner_import_force_rescan_starts_new_run_for_owned_version(tmp_path, monkeypatch):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app.dependency_overrides[get_manager] = lambda: manager
    app.include_router(router)
    client = TestClient(app)
    _record, token = ScannerTokenStore(manager.registry.data_dir).create(name="customer-a")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: api-skill\ndescription: API test\n---\n", encoding="utf-8")
    entry = manager.submit(skill, source=SourceInfo(origin=SkillOrigin.LOCAL, author="customer-a"))
    assert entry.status == SkillStatus.APPROVED
    scheduled = []
    monkeypatch.setattr(scanner_api._scan_executor, "submit", lambda *args: scheduled.append(args))

    response = client.post(
        "/api/v1/scanner/imports",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        data={"force_rescan": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version_id"] == entry.skill_id
    assert payload["status"] == "PENDING"
    assert payload["scan_reused"] is False
    assert payload["scan_run_id"]
    assert len(scheduled) == 1
    assert len(manager.list_scan_runs(entry.skill_id)) == 2


def test_scanner_import_cannot_force_rescan_another_tokens_version(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app.dependency_overrides[get_manager] = lambda: manager
    app.include_router(router)
    client = TestClient(app)
    _record, token = ScannerTokenStore(manager.registry.data_dir).create(name="customer-b")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: api-skill\ndescription: API test\n---\n", encoding="utf-8")
    entry = manager.submit(skill, source=SourceInfo(origin=SkillOrigin.LOCAL, author="customer-a"))

    response = client.post(
        "/api/v1/scanner/imports",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("skill.zip", _skill_zip(), "application/zip")},
        data={"force_rescan": "true"},
    )

    assert response.status_code == 403
    assert len(manager.list_scan_runs(entry.skill_id)) == 1


def test_legacy_scanner_token_issuance_is_removed(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_manager] = lambda: manager
    app.include_router(admin_router)
    client = TestClient(app)

    response = client.post("/api/v1/scanner/tokens", json={"name": "customer-a"})

    assert response.status_code == 410
    assert response.json()["error_code"] == "credential.legacy_scanner_token_issuance_removed"


def test_legacy_runtime_governance_routes_are_removed(tmp_path):
    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    app.dependency_overrides[get_manager] = lambda: manager
    app.include_router(agent_runtime_router, prefix="/api/v1")
    client = TestClient(app)

    response = client.get("/api/v1/runtime/can-load/example")

    assert response.status_code == 410
    assert "/api/v1/access/runtime/" in response.json()["detail"]


@pytest.mark.parametrize('assigned_user', ['张三', None])
def test_scanner_import_accepts_bound_client_token(tmp_path, assigned_user):
    engine = create_engine(f"sqlite:///{tmp_path / 'client-access.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    token = "amat_client_submit"
    rotated_token = "amat_client_submit_rotated"
    other_client_token = "amat_other_client"
    db = session_factory()
    db.add(models.ManagedClient(client_id='host-001', name='PC', hostname='PC-001', os='linux',
                                arch='amd64', client_version='test', device_user=assigned_user))
    for raw_token, name, client_id in (
        (token, "desktop-client", "host-001"),
        (rotated_token, "desktop-client-rotated", "host-001"),
        (other_client_token, "other-client", "host-002"),
    ):
        db.add(models.AccessToken(
            name=name,
            token_type="client",
            device_user='张三',
            token_hash=_hash_token(raw_token),
            token_prefix=raw_token[:8],
            bound_client_id=client_id,
            scopes_json='["client:submit-skill"]',
            allowed_models_json="[]",
            allowed_ips_json="[]",
            status="active",
        ))
    db.commit()
    db.close()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    legacy_skill = tmp_path / "legacy-client-skill"
    legacy_skill.mkdir()
    (legacy_skill / "SKILL.md").write_text(
        "---\nname: api-skill\ndescription: API test\n---\n",
        encoding="utf-8",
    )
    legacy_entry = manager.submit(
        legacy_skill,
        source=SourceInfo(origin=SkillOrigin.LOCAL, author="old-client-token", token_name="old-client-token"),
    )
    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.dependency_overrides[get_db] = override_get_db
        app.include_router(router)
        client = TestClient(app)

        response = client.post(
            "/api/v1/scanner/imports",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("skill.zip", _skill_zip(), "application/zip")},
            data={"host_id": "host-001", "use_behavioral": "true"},
        )

        assert response.status_code == 200
        entry = manager.get_skill(response.json()["skill_id"])
        assert entry.skill_id == legacy_entry.skill_id
        assert entry.source.author == "old-client-token"
        submissions = manager.registry.client_submissions(entry.skill_id, 1, 10)
        assert submissions['total'] == 1
        assert submissions['items'][0]['details']['device_user'] == '张三'
        assert submissions['items'][0]['details']['hostname'] == 'PC-001'
        with session_factory() as db:
            db.query(models.ManagedClient).filter_by(client_id='host-001').update({'device_user': '李四'})
            db.commit()
        repeated = client.post('/api/v1/scanner/imports', headers={'Authorization': f'Bearer {rotated_token}'},
                               files={'file': ('skill.zip', _skill_zip(), 'application/zip')}, data={'host_id': 'host-001'})
        assert repeated.status_code == 200, repeated.text
        submissions = manager.registry.client_submissions(entry.skill_id, 1, 1)
        assert submissions['total'] == 2
        assert submissions['items'][0]['details']['device_user'] == '李四'
        assert manager.registry.client_submissions(entry.skill_id, 2, 1)['items'][0]['details']['device_user'] == '张三'
        summary = manager.list_skill_summaries(page=1, page_size=10)['items'][0]
        assert summary['latest_client_submission']['device_user'] == '李四'
        assert entry.source.author == 'old-client-token'
        app.include_router(api_router.router, prefix='/api/v1')
        history = client.get(f'/api/v1/skills/{entry.skill_id}/client-submissions', params={'page': 2, 'page_size': 1})
        assert history.status_code == 200
        assert history.json()['total'] == 2
        assert history.json()['items'][0]['details']['device_user'] == '张三'
        spoofed = client.post('/api/v1/scanner/imports', headers={'Authorization': f'Bearer {token}'},
                              files={'file': ('skill.zip', _skill_zip(), 'application/zip')}, data={'host_id': 'host-002'})
        assert spoofed.status_code == 403
        assert manager.registry.client_submissions(entry.skill_id, 1, 10)['total'] == 2
        assert "client:host-001" in entry.submission_principals
        result = client.get(
            f"/api/v1/scanner/imports/{entry.skill_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert result.status_code == 200
        assert result.json()["skill_id"] == (entry.family_id or entry.skill_id)
        assert result.json()["version_id"] == entry.skill_id
        assert "submission_principals" not in result.json()

        rotated_result = client.get(
            f"/api/v1/scanner/imports/{entry.skill_id}",
            headers={"Authorization": f"Bearer {rotated_token}"},
        )
        assert rotated_result.status_code == 200

        other_client_result = client.get(
            f"/api/v1/scanner/imports/{entry.skill_id}",
            headers={"Authorization": f"Bearer {other_client_token}"},
        )
        assert other_client_result.status_code == 403
    finally:
        api_router._manager = previous_manager


def test_scanner_result_reports_pending_while_approved_version_is_being_rescanned(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: rescan-approved\ndescription: test\n---\n",
        encoding="utf-8",
    )
    manager = AgentManager(policy=CompanyPolicy.default(), data_dir=tmp_path / "data")
    entry = manager.submit(
        skill,
        source=SourceInfo(origin=SkillOrigin.LOCAL, author="desktop-client", token_name="desktop-token"),
    )
    assert entry.status == SkillStatus.APPROVED
    pending, started = manager.request_rescan(entry.skill_id)
    assert started is True
    assert pending.status == SkillStatus.APPROVED
    run = next(run for run in manager.list_scan_runs(entry.skill_id) if run.status == "PENDING")
    manager.registry.update_scan_progress(run.scan_run_id, "analyzers")
    manager.registry.update_scan_analyzer(run.scan_run_id, "scanner", "completed")
    manager.registry.update_scan_analyzer(run.scan_run_id, "sandbox", "running")

    payload = get_scanner_import(
        entry.skill_id,
        scanner_auth=ScannerAuthContext(
            name="desktop-client",
            author="desktop-client",
            token_name="desktop-token",
            max_upload_mb=50,
        ),
        mgr=manager,
    )

    assert payload["status"] == "PENDING"
    assert payload["scan_pending"] is True
    assert payload["effective_status"] == "APPROVED"
    assert payload["scan_progress_stage"] == "analyzers"
    assert payload["scan_progress_analyzers"] == {"scanner": "completed", "sandbox": "running"}
    assert manager.get_skill(entry.skill_id).status == SkillStatus.APPROVED


def test_access_runtime_routes_accept_runtime_token(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'access.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    token = "amat_runtime_test"
    db = TestingSessionLocal()
    db.add(
        models.ManagedAgent(
            agent_id="agno-demo",
            name="Agno Demo",
            status="active",
            skill_names_json='["runtime-skill"]',
            prompt_names_json="[]",
        )
    )
    db.add(
        models.AccessToken(
            name="agent-runtime",
            token_type="agent_runtime",
            token_hash=_hash_token(token),
            token_prefix=token[:8],
            bound_agent_id="agno-demo",
            scopes_json='["runtime:verify-signature", "runtime:can-load", "runtime:check-tool"]',
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
    (skill_dir / "SKILL.md").write_text("---\nname: runtime-skill\ndescription: Runtime test\n---\n", encoding="utf-8")
    entry = manager.submit(skill_dir)
    assert entry.family_id

    db = TestingSessionLocal()
    agent = db.query(models.ManagedAgent).filter(models.ManagedAgent.agent_id == "agno-demo").one()
    agent.skill_names_json = json.dumps([entry.family_id])
    db.commit()
    db.close()

    previous_manager = api_router._manager
    api_router._manager = manager
    try:
        app.dependency_overrides[get_manager] = lambda: manager
        app.dependency_overrides[get_db] = override_get_db
        app.include_router(admin_router)
        app.include_router(runtime_router)
        app.include_router(api_router.router)
        client = TestClient(app)

        verify_response = client.post(
            "/api/v1/access/runtime/verify-skill-signature",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "skill_name": "runtime-skill",
                "skill_id": entry.skill_id,
                "local_signature": compute_content_digest(skill_dir),
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

        audit_response = client.get(
            "/audit",
            params={
                "skill_id": entry.skill_id,
                "event_types": "skill_signature_verified,skill_load_allowed",
                "page": 1,
                "page_size": 20,
            },
        )
        assert audit_response.status_code == 200
        assert {item["event_type"] for item in audit_response.json()["items"]} == {
            "skill_signature_verified",
            "skill_load_allowed",
        }

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
                "local_signature": compute_content_digest(skill_dir),
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
            "/audit",
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
