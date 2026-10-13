import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_manager.api.router import get_manager
from agent_manager.core.models import SkillStatus
from backend import auth, models
from backend.client_signing import compute_content_signature, private_key
from backend.config import settings
from backend.routers import access_tokens, clients
from backend.sqlite_db import Base, get_db
from tests.test_clients_api import _Manager


@pytest.mark.parametrize("unverified_action", ["record", "quarantine"])
def test_go_client_register_takeover_and_install_e2e(tmp_path, monkeypatch, unverified_action):
    server_skill = tmp_path / "server-skill"
    _write_skill(server_skill, "approved-skill")
    signature = compute_content_signature(server_skill)
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    private_key.cache_clear()
    entry = type(
        "Entry",
        (),
        {
            "skill_id": "skill-approved",
            "name": "approved-skill",
            "status": SkillStatus.APPROVED,
            "signature": signature,
            "skill_path": str(server_skill),
        },
    )()
    download_root = tmp_path / "download-skill"
    _write_skill(download_root, "download-skill")
    download_entry = SimpleNamespace(skill_id="skill-download", name="download-skill", status=SkillStatus.APPROVED,
                                     signature=compute_content_signature(download_root), skill_path=str(download_root))
    manager = _Manager({"approved-skill": entry, "skill-approved": entry,
                        "download-skill": download_entry, "skill-download": download_entry})
    manager.registry.get_by_id = manager.get_skill

    engine = create_engine(f"sqlite:///{tmp_path / 'e2e.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    database = session_factory()
    database.add(
        models.ManagedAgent(
            agent_id="codex-agent",
            name="Codex Agent",
            channel="Codex",
            status="active",
            created_by="admin",
            skill_names_json='["skill-approved"]',
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_manager] = lambda: manager
    app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=1,
        username="admin",
        hashed_password="x",
        role="super_admin",
    )
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(clients.router, prefix="/api")

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started

    binary = tmp_path / "agent-manager-client"
    subprocess.run(
        ["go", "build", "-o", str(binary), "./cmd/agent-manager-client"],
        cwd=Path(__file__).parents[1] / "scanner",
        env={**os.environ, "GOCACHE": "/tmp/skill-manager-go-cache"},
        check=True,
    )
    home = tmp_path / "home"
    approved_local = home / ".codex" / "skills" / "approved-skill"
    denied_local = home / ".codex" / "skills" / "unregistered-skill"
    shutil.copytree(server_skill, approved_local)
    _write_skill(denied_local, "unregistered-skill")
    base_url = f"http://127.0.0.1:{port}"

    try:
        with httpx.Client(base_url=base_url, timeout=10) as api:
            token_response = api.post(
                "/api/v1/access/tokens",
                json={"name": "E2E Client", "token_type": "client"},
            )
            assert token_response.status_code == 200
            token = token_response.json()["token"]

            common = [
                str(binary),
                "--home",
                str(home),
                "--server",
                base_url,
                "--token",
                token,
            ]
            subprocess.run([common[0], "register", *common[1:]], check=True, capture_output=True, text=True)
            detail = api.get("/api/v1/clients")
            assert detail.status_code == 200
            codex = next(agent for agent in detail.json()[0]["agents"] if agent["agent_type"] == "codex")
            managed_agent_id = codex["managed_agent_id"]
            assert managed_agent_id and managed_agent_id != "codex-agent"
            with session_factory() as db:
                discovered = db.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one()
                assert discovered.origin_type == "client_discovery"
                discovered.skill_names_json = '["skill-approved", "skill-download"]'
                db.commit()
            policy_path = f"/api/v1/clients/{detail.json()[0]['client_id']}/governance"
            policy = api.get(policy_path).json()
            change = {"expected_version": policy["version"], "rules": {"unverified": unverified_action}}
            preview = api.post(policy_path + "/preview", json=change)
            assert preview.status_code == 200, preview.text
            saved = api.put(policy_path, json={**change, "preview_id": preview.json()["preview_id"]})
            assert saved.status_code == 200, saved.text

            subprocess.run(
                [common[0], "takeover", *common[1:], "--agent", f"codex={managed_agent_id}", "--confirm"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert (approved_local / "SKILL.md").is_file()
            assert denied_local.exists() == (unverified_action == "record")
            copies = json.loads(subprocess.run([common[0], "quarantine", *common[1:]], check=True, capture_output=True, text=True).stdout)
            if unverified_action == "quarantine":
                assert len(copies) == 1
                assert (Path(copies[0]["quarantine_path"]) / "SKILL.md").is_file()
            else:
                assert copies == []
            after_takeover = api.get(f"/api/v1/clients/{detail.json()[0]['client_id']}").json()
            managed_skill = next(
                skill
                for agent in after_takeover["agents"]
                if agent["agent_type"] == "codex"
                for skill in agent["skills"]
                if skill["name"] == "approved-skill"
            )
            assert managed_skill["governance"]["trusted_skill_id"] == "skill-approved"
            assert managed_skill["governance"]["certification"] == "certified"

            task = api.post(
                f"/api/v1/clients/{detail.json()[0]['client_id']}/tasks",
                json={
                    "task_type": "install_skill",
                    "payload": {
                        "agent_type": "codex",
                        "managed_agent_id": managed_agent_id,
                        "skill_id": "skill-download",
                    },
                },
            )
            assert task.status_code == 200
            subprocess.run([common[0], "run-once", *common[1:]], check=True, capture_output=True, text=True)
            current = api.get(f"/api/v1/clients/{detail.json()[0]['client_id']}").json()
            current_agent = next(agent for agent in current["agents"] if agent["agent_type"] == "codex")
            assert current_agent["managed_agent_id"] == managed_agent_id
            assert current["tasks"][0]["status"] == "succeeded", current["tasks"][0]
            assert any(event["event_type"] == "skill_installed" for event in current["events"])
            assert any(event.event_type == "skill_installed" for event in manager.registry.events)
            assert (approved_local / "SKILL.md").is_file()
            assert (home / ".codex" / "skills" / "download-skill" / "SKILL.md").read_text() == (download_root / "SKILL.md").read_text()
            installed = next(skill for skill in current_agent["skills"] if skill["name"] == "download-skill")
            assert installed["skill_id"] == "skill-download"
            assert installed["status"] == "managed"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _write_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: e2e\n---\n", encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
