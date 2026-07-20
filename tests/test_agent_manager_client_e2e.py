import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
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


class _Manager:
    def __init__(self, entries):
        self.entries = entries

    def get_skill(self, value):
        return self.entries.get(value)

    def list_skills(self):
        return list({id(entry): entry for entry in self.entries.values()}.values())


def test_go_client_register_takeover_and_install_e2e(tmp_path, monkeypatch):
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
    manager = _Manager({"approved-skill": entry, "skill-approved": entry})

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
            assert codex["managed_agent_id"] == "codex-agent"

            subprocess.run(
                [common[0], "takeover", *common[1:], "--agent", "codex=codex-agent", "--confirm"],
                check=True,
                capture_output=True,
                text=True,
            )
            assert (approved_local / "SKILL.md").is_file()
            assert not denied_local.exists()
            assert (home / ".agent-manager" / "pending" / "codex" / "unregistered-skill" / "SKILL.md").is_file()
            after_takeover = api.get(f"/api/v1/clients/{detail.json()[0]['client_id']}").json()
            managed_skill = next(
                skill
                for agent in after_takeover["agents"]
                if agent["agent_type"] == "codex"
                for skill in agent["skills"]
            )
            assert managed_skill["skill_id"] == "skill-approved"
            assert managed_skill["status"] == "managed"

            task = api.post(
                f"/api/v1/clients/{detail.json()[0]['client_id']}/tasks",
                json={
                    "task_type": "install_skill",
                    "payload": {
                        "agent_type": "codex",
                        "managed_agent_id": "codex-agent",
                        "skill_id": "skill-approved",
                    },
                },
            )
            assert task.status_code == 200
            subprocess.run([common[0], "run-once", *common[1:]], check=True, capture_output=True, text=True)
            current = api.get(f"/api/v1/clients/{detail.json()[0]['client_id']}").json()
            assert current["tasks"][0]["status"] == "succeeded"
            assert any(event["event_type"] == "skill_installed" for event in current["events"])
            assert (approved_local / "SKILL.md").is_file()
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
