"""Real HTTP + downloaded CLI acceptance; isolated storage, no mocked decisions."""

import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_manager.api import router as skill_api, scanner_router
from agent_manager.core.manager import AgentManager
from agent_manager.core.policy import CompanyPolicy
from backend import auth, models
from backend.api_errors import ApiError, api_error_handler
from backend.config import settings
from backend.routers import access_tokens, agents
from backend.sqlite_db import Base, get_db


@pytest.fixture
def verifier_server(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", secrets.token_hex(32))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    manager = AgentManager(CompanyPolicy({"require_human_review": ["benign", "suspicious"]}), data_dir=tmp_path / "registry")
    monkeypatch.setattr(skill_api, "_manager", manager)
    engine = create_engine(f"sqlite:///{tmp_path / 'platform.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with sessions() as db:
        db.add(models.User(username="verifier-acceptance-admin", hashed_password="unused", role="super_admin", is_active=True))
        db.commit()

    def database():
        with sessions() as db:
            yield db

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[skill_api.get_manager] = lambda: manager
    app.include_router(agents.router, prefix="/api")
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(skill_api.router, prefix="/api/v1", dependencies=[Depends(auth.get_current_admin_user)])
    app.include_router(scanner_router.admin_router, dependencies=[Depends(auth.get_current_admin_user)])
    app.include_router(scanner_router.router)
    app.include_router(scanner_router.runtime_router)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        admin_jwt = auth.create_access_token({"sub": "verifier-acceptance-admin"})
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {admin_jwt}"}, timeout=20) as api:
            yield api, sessions
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        engine.dispose()


@pytest.mark.parametrize("language,host", [("zh-CN", ".codex"), ("en-US", ".claude")])
def test_downloaded_verifier_full_onboarding(verifier_server, tmp_path, language, host):
    api, sessions = verifier_server
    evidence = []

    def request(method, path, **kwargs):
        response = api.request(method, path, **kwargs)
        assert response.status_code == 200, (path, response.status_code, response.text)
        return response.json()

    agent_id = "verifier-acceptance-agent"
    agent = request("POST", "/api/agents", json={"agent_id": agent_id, "name": "Verifier acceptance", "status": "active"})
    assert agent["origin_type"] == "platform"
    assert request("GET", "/api/agents")[0]["agent_id"] == agent_id
    evidence.append({"stage": "create_agent", "agent_id": agent_id, "origin": agent["origin_type"]})
    runtime = request("POST", "/api/v1/access/tokens", json={
        "name": "Verifier acceptance runtime", "token_type": "agent_runtime", "bound_agent_id": agent_id,
        "scopes": ["runtime:verify-signature", "runtime:can-load"],
    })
    scanner = request("POST", "/api/v1/access/tokens", json={
        "name": "Verifier acceptance scanner", "token_type": "scanner",
        "scopes": ["scanner:submit", "scanner:read-own-results"],
    })
    listing = request("GET", "/api/v1/access/tokens")
    assert runtime["token"] not in json.dumps(listing)
    with sessions() as db:
        stored = db.query(models.AccessToken).filter_by(name="Verifier acceptance runtime").one()
        token_id = stored.id
        assert stored.token_hash == hashlib.sha256(runtime["token"].encode()).hexdigest()
    evidence.append({"stage": "issue_credentials", "runtime_scopes": ["runtime:verify-signature", "runtime:can-load"], "plaintext_not_listed": True, "hash_verified": True})

    download = api.get("/api/v1/scanner/skill-verifier/download")
    assert download.status_code == 200
    package = tmp_path / "agent-manager-skill-verifier.zip"
    package.write_bytes(download.content)
    install_root = tmp_path / "runtime home" / host / "skills"
    install_root.mkdir(parents=True)
    subprocess.run(["unzip", "-q", str(package), "-d", str(install_root)], check=True, capture_output=True)
    installed = install_root / "agent-manager-skill-verifier"
    assert (installed / "SKILL.md").exists()
    script = installed / "scripts" / "agent_manager_skill_verifier.py"
    skill = install_root / "team's 测试 skill"
    skill.mkdir()
    original = "---\nname: verifier-acceptance-skill\ndescription: Return a friendly greeting.\n---\n\nReturn hello.\n"
    (skill / "SKILL.md").write_text(original, encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith(("AGENT_MANAGER_", "AGENT_ID", "SKILL_SCANNER_"))}
    env.update({"AGENT_MANAGER_VERIFIER_BASE_URL": str(api.base_url), "AGENT_MANAGER_AGENT_RUNTIME_TOKEN": runtime["token"],
                "AGENT_MANAGER_SCANNER_TOKEN": scanner["token"], "AGENT_ID": agent_id, "AGENT_MANAGER_VERIFIER_LANG": language})
    evidence.append({"stage": "install_downloaded_package", "sha256": hashlib.sha256(download.content).hexdigest(), "host": host, "language": language})

    def cli(*args, overrides=None):
        return subprocess.run(["python3", str(script), *args], env={**env, **(overrides or {})}, capture_output=True, text=True, timeout=30)

    submitted = cli("submit", "--path", str(skill))
    assert submitted.returncode == 0, submitted.stdout + submitted.stderr
    skill_id = re.search(r"skill_id=([^,\s]+)", submitted.stdout).group(1)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = cli("status", "--skill-id", skill_id)
        if "VETTED" in status.stdout:
            break
        time.sleep(0.05)
    assert status.returncode == 0 and "VETTED" in status.stdout, status.stdout + status.stderr
    request("PUT", f"/api/agents/{agent['id']}", json={"skill_names": [skill_id]})
    evidence.append({"stage": "submit_and_status", "skill_id": skill_id, "status": "VETTED"})

    # A real process gate models a Loader consuming the exit status. It does not
    # assert that any third-party desktop Agent automatically invokes Verifier.
    marker = tmp_path / "loaded.marker"
    gate = 'python3 "$VERIFIER_SCRIPT" verify --path "$TARGET_SKILL" && printf loaded > "$LOAD_MARKER"'

    def verify(case, allowed, overrides=None, audit_event=None):
        marker.unlink(missing_ok=True)
        before = request("GET", "/api/v1/audit", params={"q": agent_id, "limit": 1000})
        result = subprocess.run(["bash", "-c", gate], env={**env, "VERIFIER_SCRIPT": str(script), "TARGET_SKILL": str(skill),
                                  "LOAD_MARKER": str(marker), **(overrides or {})}, capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == allowed, result.stdout + result.stderr
        assert marker.exists() == allowed
        after = request("GET", "/api/v1/audit", params={"q": agent_id, "limit": 1000})
        ids = {row["event_id"] for row in before}
        events = [row for row in after if row["event_id"] not in ids]
        if audit_event:
            assert audit_event in {row["event_type"] for row in events}, events
        if allowed:
            assert {row["event_type"] for row in events} == {"skill_signature_verified", "skill_load_allowed"}
        else:
            assert "skill_load_allowed" not in {row["event_type"] for row in events}
        for row in events:
            assert row["agent_id"] == agent_id
            assert row["details"]["bound_agent_id"] == agent_id
            assert row["details"]["token_id"] == token_id
            assert runtime["token"] not in json.dumps(row)
        evidence.append({"stage": case, "exit_code": result.returncode, "load_marker": marker.exists(),
                         "output": (result.stdout + result.stderr).strip(), "audit_events": events})
        return result

    verify("pending_approval", False, audit_event="skill_load_blocked")
    version_id = request("GET", f"/api/v1/skills/{skill_id}")["version_id"]
    approved = request("POST", f"/api/v1/skills/{version_id}/approve", json={"approver": "verifier-acceptance-admin", "note": "Isolated acceptance fixture"})
    assert approved["status"] == "APPROVED"
    verify("approved_success", True, overrides={"AGENT_MANAGER_SCANNER_TOKEN": ""}, audit_event="skill_load_allowed")
    (skill / "SKILL.md").write_text(original + "\nChanged local content.\n", encoding="utf-8")
    verify("tampered_content", False, audit_event="skill_tamper_detected")
    (skill / "SKILL.md").write_text(original, encoding="utf-8")
    request("PUT", f"/api/agents/{agent['id']}", json={"skill_names": []})
    verify("skill_not_authorized", False, audit_event="skill_load_blocked")
    request("PUT", f"/api/agents/{agent['id']}", json={"skill_names": [skill_id]})
    verify("identity_mismatch", False, overrides={"AGENT_ID": "different-agent"})
    verify("scanner_credential_as_runtime", False, overrides={"AGENT_MANAGER_AGENT_RUNTIME_TOKEN": scanner["token"]})
    verify("missing_runtime_credential", False, overrides={"AGENT_MANAGER_AGENT_RUNTIME_TOKEN": ""})
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        verify("unreachable_platform", False, overrides={"AGENT_MANAGER_VERIFIER_BASE_URL": f"http://127.0.0.1:{unavailable.getsockname()[1]}"})
    request("PUT", f"/api/v1/access/tokens/{token_id}", json={"scopes": ["runtime:verify-signature"]})
    verify("missing_can_load_scope", False, audit_event="skill_signature_verified")
    request("PUT", f"/api/v1/access/tokens/{token_id}", json={"scopes": ["runtime:verify-signature", "runtime:can-load"]})
    request("PUT", f"/api/agents/{agent['id']}", json={"status": "disabled"})
    verify("disabled_agent", False)
    request("PUT", f"/api/agents/{agent['id']}", json={"status": "active"})
    request("PUT", f"/api/v1/access/tokens/{token_id}", json={"status": "disabled"})
    verify("disabled_credential", False)
    request("PUT", f"/api/v1/access/tokens/{token_id}", json={"status": "active", "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    verify("expired_credential", False)
    request("PUT", f"/api/v1/access/tokens/{token_id}", json={"expires_at": None})
    verify("restored_success", True, audit_event="skill_load_allowed")
    rescan = cli("submit", "--path", str(skill), "--no-cache")
    assert rescan.returncode == 0, rescan.stdout + rescan.stderr
    scan_path = f"/api/v1/skills/{skill_id}/versions/{version_id}/scan-runs"
    runs = request("GET", scan_path)["items"]
    assert len(runs) == 2, "--no-cache must create a new scan run for the existing version"
    deadline = time.monotonic() + 30
    while any(run["status"] == "PENDING" for run in runs) and time.monotonic() < deadline:
        time.sleep(0.05)
        runs = request("GET", scan_path)["items"]
    assert all(run["status"] == "COMPLETED" for run in runs), [run["status"] for run in runs]
    evidence.append({"stage": "force_rescan", "scan_runs": len(runs), "statuses": [run["status"] for run in runs]})
    request("POST", f"/api/v1/access/tokens/{token_id}/revoke")
    verify("revoked_credential", False)
    report = tmp_path / "acceptance-evidence.json"
    report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verifier HTTP acceptance evidence ({language}): {report}")
