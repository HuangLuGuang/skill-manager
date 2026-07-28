import base64
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agent_manager.api.router import get_manager
from agent_manager.core.models import SkillStatus
from backend import auth, models, schemas
from backend.config import settings
from backend.client_signing import compute_content_signature, private_key
from backend.routers import access_tokens, clients
from backend.sqlite_db import Base, get_db


class _Registry:
    def __init__(self):
        self.events = []

    def log_event(self, event):
        self.events.append(event)


class _Manager:
    def __init__(self, entries=None):
        self.entries = entries or {}
        self.list_calls = 0
        self.registry = _Registry()

    def get_skill(self, value):
        return self.entries.get(value)

    def list_skills(self):
        self.list_calls += 1
        result = []
        seen = set()
        for entry in self.entries.values():
            if id(entry) not in seen:
                result.append(entry)
                seen.add(id(entry))
        return result

    def list_skills_by_names(self, names):
        wanted = {name.lower() for name in names}
        return [entry for entry in self.list_skills() if entry.name.lower() in wanted]


def _client(tmp_path, manager=None):
    engine = create_engine(f"sqlite:///{tmp_path / 'clients.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        session = session_factory()
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
    app.dependency_overrides[get_manager] = lambda: manager or _Manager()
    app.include_router(access_tokens.router, prefix="/api/v1")
    app.include_router(clients.router, prefix="/api")
    return TestClient(app)


def test_compare_reuses_platform_skill_signature(monkeypatch):
    entry = type("Entry", (), {"skill_id": "skill-1", "name": "shared", "skill_path": "/skills/shared"})()
    calls = 0

    def signature(_path):
        nonlocal calls
        calls += 1
        return "same-signature"

    monkeypatch.setattr(clients, "compute_content_signature", signature)
    cache = {}
    local = schemas.ClientSkillCompareItem(name="shared", signature="same-signature")
    manager = _Manager({"shared": entry})
    entries = manager.list_skills()
    assert clients._matching_skill_entry(manager, local, signature_cache=cache, registry_entries=entries) is entry
    assert clients._matching_skill_entry(manager, local, signature_cache=cache, registry_entries=entries) is entry
    assert calls == 1
    assert manager.list_calls == 1


def test_generated_registry_name_uses_skill_metadata(tmp_path):
    root = tmp_path / "uploaded_skills" / "063abf7c7194468c8c6c69b160acebe9"
    root.mkdir(parents=True)
    (root / "_meta.json").write_text('{"slug":"cninfo-announcement-scraper"}', encoding="utf-8")
    (root / "SKILL.md").write_text(
        "# cninfo-announcement-scraper\n\nFetches official CNINFO disclosures.\n",
        encoding="utf-8",
    )

    assert clients._skill_display_metadata(root.name, root=root) == (
        "cninfo-announcement-scraper",
        "Fetches official CNINFO disclosures.",
    )


def test_client_register_inventory_and_task_round_trip(tmp_path):
    manager = _Manager()
    client = _client(tmp_path, manager)
    created = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    )
    assert created.status_code == 200
    token = created.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "host-001",
            "name": "研发客户端",
            "hostname": "dev-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [
                {
                    "agent_type": "codex",
                    "skills_path": "/tmp/home/.codex/skills",
                    "skill_management_supported": True,
                    "skills": [
                        {
                            "name": "code-review",
                            "path": "/tmp/home/.codex/skills/code-review",
                            "signature": "sha256:abc",
                        }
                    ],
                },
                {
                    "agent_type": "legacy-client",
                    "skill_management_supported": False,
                    "capabilities": {"skill_management": False},
                },
            ],
        },
    )
    assert registered.status_code == 200
    assert registered.json()["client_id"] == "host-001"
    assert len(registered.json()["agents"]) == 2

    repeated = client.post("/api/v1/clients/register", headers=headers, json=json.loads(registered.request.content))
    assert repeated.status_code == 200
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.ClientEvent).filter_by(client_id="host-001", event_type="client_registered").count() == 1
    database.close()

    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedAgent(
            agent_id="bound-codex",
            name="Bound Codex",
            channel="Codex",
            status="active",
            skill_names_json="[]",
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()
    bound = client.put(
        "/api/v1/clients/host-001/agents/codex",
        json={"managed_agent_id": "bound-codex"},
    )
    assert bound.status_code == 200
    runtime_policy = client.get("/api/v1/clients/host-001/policy", headers=headers)
    assert runtime_policy.status_code == 200
    assert runtime_policy.json()["agent_bindings"] == {"codex": "bound-codex"}
    heartbeat = client.post(
        "/api/v1/clients/host-001/heartbeat",
        headers=headers,
        json={"client_id": "host-001", "client_version": "0.1.0"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["policy"] == runtime_policy.json()
    refreshed = client.post(
        "/api/v1/clients/host-001/inventory",
        headers=headers,
        json={
            "agents": [
                {
                    "agent_type": "codex",
                    "skills_path": "/tmp/home/.codex/skills",
                    "skill_management_supported": True,
                }
            ]
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["agents"][0]["managed_agent_id"] == "bound-codex"

    database = next(client.app.dependency_overrides[get_db]())
    stored_client = database.query(models.ManagedClient).filter(models.ManagedClient.client_id == "host-001").first()
    stored_client.last_seen_at = datetime.utcnow() - timedelta(minutes=10)
    database.commit()
    database.close()

    runtime_status = client.get("/api/v1/clients/host-001/status", headers=headers)
    assert runtime_status.status_code == 200
    assert runtime_status.json()["client_id"] == "host-001"
    assert runtime_status.json()["status"] == "online"
    assert runtime_status.json()["detection_capabilities"]["rules"]["enabled"] is True
    assert runtime_status.json()["agents"][0]["managed_agent_id"] == "bound-codex"
    assert all(event["event_type"] != "client_registered" for event in runtime_status.json()["events"])

    policy_update = client.put(
        "/api/v1/clients/host-001/policy",
        json={"mode": "repair"},
    )
    assert policy_update.status_code == 200
    sync_task_id = policy_update.json()["sync_task_id"]
    governance_update = client.put(
        "/api/v1/clients/host-001/policy",
        json={"governance_mode": "strict"},
    )
    assert governance_update.status_code == 200
    assert governance_update.json()["sync_task_id"] == sync_task_id
    sync_tasks = client.get("/api/v1/clients/host-001/tasks", headers=headers).json()
    assert sync_tasks == [
        {
            "id": sync_task_id,
            "task_type": "rescan",
            "payload": {"reason": "policy_changed", "mode": "repair", "governance_mode": "strict"},
        }
    ]
    synced = client.post(
        f"/api/v1/clients/host-001/tasks/{sync_task_id}/result",
        headers=headers,
        json={"status": "succeeded"},
    )
    assert synced.status_code == 200

    other_client = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "host-002",
            "name": "其他客户端",
            "hostname": "other",
            "os": "linux",
            "arch": "amd64",
            "client_version": "0.1.0",
        },
    )
    assert other_client.status_code == 403
    assert "已绑定其他客户端" in other_client.json()["detail"]

    task = client.post(
        "/api/v1/clients/host-001/tasks",
        json={"task_type": "rescan", "payload": {}},
    )
    assert task.status_code == 200
    runtime_task = client.get("/api/v1/clients/host-001/status", headers=headers).json()["tasks"][0]
    assert runtime_task["task_type"] == "rescan"
    assert runtime_task["status"] == "pending"
    duplicate = client.post(
        "/api/v1/clients/host-001/tasks",
        json={"task_type": "rescan", "payload": {}},
    )
    assert duplicate.json() == task.json()

    polled = client.get("/api/v1/clients/host-001/tasks", headers=headers)
    assert polled.status_code == 200
    assert polled.json() == [{"id": task.json()["id"], "task_type": "rescan", "payload": {}}]

    completed = client.post(
        f"/api/v1/clients/host-001/tasks/{task.json()['id']}/result",
        headers=headers,
        json={"status": "succeeded"},
    )
    assert completed.status_code == 200
    cancellable = client.post(
        "/api/v1/clients/host-001/tasks",
        json={"task_type": "rescan", "payload": {"generation": 2}},
    )
    cancelled = client.post(f"/api/v1/clients/host-001/tasks/{cancellable.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    retried = client.post(f"/api/v1/clients/host-001/tasks/{cancellable.json()['id']}/retry")
    assert retried.json()["status"] == "pending"
    unsafe_remove = client.post(
        "/api/v1/clients/host-001/tasks",
        json={
            "task_type": "remove_skill",
            "payload": {
                "agent_type": "legacy-client",
                "skill_id": "missing",
                "skill_name": "../../unsafe",
            },
        },
    )
    assert unsafe_remove.status_code == 400
    assert unsafe_remove.json()["detail"] == "客户端中不存在可移除的受管 Skill"
    takeover = client.post(
        "/api/v1/clients/host-001/takeover-report",
        headers=headers,
        json={"backup": "/tmp/backup", "managed_count": 1, "pending_count": 2},
    )
    assert takeover.status_code == 200
    assert takeover.json()["recorded"] is True
    no_change_takeover = client.post(
        "/api/v1/clients/host-001/takeover-report",
        headers=headers,
        json={"backup": "", "managed_count": 0, "pending_count": 0},
    )
    assert no_change_takeover.status_code == 200
    assert no_change_takeover.json()["recorded"] is False
    reported = client.post(
        "/api/v1/clients/host-001/events",
        headers=headers,
        json={
            "event_type": "skill_quarantined",
            "agent_type": "codex",
            "skill_name": "unsafe",
            "details": {"skill_id": "skill-unsafe", "reason": "signature_mismatch"},
        },
    )
    assert reported.status_code == 200
    audit_event = manager.registry.events[-1]
    assert audit_event.event_type == "skill_quarantined"
    assert audit_event.skill_id == "skill-unsafe"
    assert audit_event.actor == "host-001"
    assert audit_event.details["agent_id"] == "codex"
    assert audit_event.details["source"] == "managed_client"
    assert client.get("/api/v1/clients").json()[0]["issue_count"] == 1
    class LockedRegistry:
        def log_event(self, _event):
            raise sqlite3.OperationalError("database is locked")

    manager.registry = LockedRegistry()
    restored = client.post(
        "/api/v1/clients/host-001/events",
        headers=headers,
        json={"event_type": "skill_quarantine_restored", "agent_type": "codex", "skill_name": "unsafe"},
    )
    assert restored.status_code == 200
    assert client.get("/api/v1/clients").json()[0]["issue_count"] == 0

    detail = client.get("/api/v1/clients/host-001")
    assert detail.status_code == 200
    assert detail.json()["agents"][0]["managed_agent_id"] == "bound-codex"
    assert detail.json()["agents"][0]["skills"] == []
    assert any(item["status"] == "succeeded" for item in detail.json()["tasks"])
    assert all(item["event_type"] != "takeover_completed" for item in detail.json()["events"])
    inventory = client.get("/api/v1/clients/host-001/inventory")
    assert inventory.status_code == 200
    assert inventory.json()["agents"][0]["agent_type"] == "codex"
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.ClientEvent).filter_by(client_id="host-001", event_type="takeover_completed").count() == 1
    assert database.query(models.OperationLog).count() >= 2
    database.close()


def test_client_update_manifest_and_download_require_client_token(tmp_path, monkeypatch):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    artifact = release_dir / "agent-manager-client.app.tar.gz"
    artifact.write_bytes(b"signed-update")
    (release_dir / "latest.json").write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "notes": "test release",
                "pub_date": "2026-07-16T00:00:00Z",
                "platforms": {
                    "darwin-aarch64": {
                        "file": artifact.name,
                        "signature": "test-signature",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(clients, "_CLIENT_RELEASE_DIR", release_dir)
    client = _client(tmp_path)
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    denied = client.get("/api/v1/clients/updates/darwin/arm64/0.1.0")
    assert denied.status_code == 401
    checked = client.get("/api/v1/clients/updates/darwin/arm64/0.1.0", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["version"] == "0.2.0"
    assert checked.json()["signature"] == "test-signature"
    downloaded = client.get(checked.json()["url"], headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == b"signed-update"


def test_only_latest_client_installers_are_listed_and_downloadable(tmp_path, monkeypatch):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    older = release_dir / "agent-manager-client-26.03.14-windows-x86_64.exe"
    newer = release_dir / "agent-manager-client-26.03.15-darwin-aarch64.dmg"
    newer_windows = release_dir / "agent-manager-client-26.03.15-windows-x86_64.exe"
    ignored = release_dir / "agent-manager-client-26.03.15-darwin-aarch64.app.tar.gz"
    older.write_bytes(b"windows")
    newer.write_bytes(b"macos")
    newer_windows.write_bytes(b"new-windows")
    ignored.write_bytes(b"updater")
    monkeypatch.setattr(clients, "_CLIENT_RELEASE_DIR", release_dir)
    client = _client(tmp_path)

    response = client.get("/api/v1/clients/downloads/available")
    assert response.status_code == 200
    assert {item["version"] for item in response.json()["items"]} == {"26.03.15"}
    assert {item["platform"] for item in response.json()["items"]} == {
        "darwin-aarch64",
        "windows-x86_64",
    }
    assert all(item["size"] > 0 for item in response.json()["items"])
    key = response.json()["items"][0]["key"]
    denied = client.get("/api/v1/clients/downloads/file", params={"platform": key})
    assert denied.status_code == 401
    ticket = client.post("/api/v1/clients/downloads/ticket", params={"platform": key})
    assert ticket.status_code == 200
    assert ticket.json()["expires_in"] == 300
    assert ticket.json()["filename"].startswith("agent-manager-client-")
    ticket_payload = auth.jwt.decode(
        client.cookies.get("agent_manager_client_download"),
        settings.SECRET_KEY,
        algorithms=[auth.ALGORITHM],
    )
    assert "sub" not in ticket_payload
    assert ticket_payload["purpose"] == "client_installer_download"
    downloaded = client.get(ticket.json()["url"])
    assert downloaded.status_code == 200
    assert downloaded.content in {b"macos", b"new-windows"}
    partial = client.get(
        ticket.json()["url"],
        headers={"Range": "bytes=0-2"},
    )
    assert partial.status_code == 206
    assert partial.content in {b"mac", b"new"}

    other_key = next(item["key"] for item in response.json()["items"] if item["key"] != key)
    mismatch = client.get("/api/v1/clients/downloads/file", params={"platform": other_key})
    assert mismatch.status_code == 403


def test_client_installer_list_is_empty_when_release_directory_has_no_installers(tmp_path, monkeypatch):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    (release_dir / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(clients, "_CLIENT_RELEASE_DIR", release_dir)
    client = _client(tmp_path)

    response = client.get("/api/v1/clients/downloads/available")

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_disabled_client_token_is_rejected_immediately(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()
    disabled = client.put(
        f"/api/v1/access/tokens/{created['record']['id']}",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200
    response = client.post(
        "/api/v1/clients/register",
        headers={"Authorization": f"Bearer {created['token']}"},
        json={
            "client_id": "disabled-host",
            "name": "Disabled Host",
            "hostname": "disabled-host",
            "os": "linux",
            "arch": "amd64",
            "client_version": "0.1.0",
        },
    )
    assert response.status_code == 403
    assert "已禁用" in response.json()["detail"]


def test_client_list_marks_stale_heartbeat_offline(tmp_path):
    client = _client(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedClient(
            client_id="stale-host",
            name="Stale Host",
            hostname="stale-host",
            os="linux",
            arch="amd64",
            client_version="0.1.0",
            last_seen_at=datetime.utcnow() - timedelta(minutes=11),
        )
    )
    database.commit()
    database.close()

    response = client.get("/api/v1/clients")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "offline"


def test_client_content_signature_cache_invalidates_after_file_change(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    path = root / "SKILL.md"
    path.write_text("first", encoding="utf-8")
    first = compute_content_signature(root)
    assert compute_content_signature(root) == first
    path.write_text("second", encoding="utf-8")
    assert compute_content_signature(root) != first


def test_compare_same_name_skills_uses_authorized_signature(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "SKILL.md").write_text("---\nname: same\n---\nfirst\n", encoding="utf-8")
    (second_root / "SKILL.md").write_text("---\nname: same\n---\nsecond\n", encoding="utf-8")
    first = type(
        "Entry",
        (),
        {"skill_id": "skill-1", "name": "same", "status": SkillStatus.APPROVED, "skill_path": str(first_root)},
    )()
    second = type(
        "Entry",
        (),
        {"skill_id": "skill-2", "name": "same", "status": SkillStatus.APPROVED, "skill_path": str(second_root)},
    )()
    client = _client(tmp_path, _Manager({"same": first, "skill-1": first, "skill-2": second}))
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "same-name-host",
            "name": "Same Name Host",
            "hostname": "same-name-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [{"agent_type": "codex", "skill_management_supported": True}],
        },
    )
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedAgent(
            agent_id="codex-agent",
            name="Codex Agent",
            channel="Codex",
            status="active",
            skill_names_json='["skill-2"]',
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()
    client.put(
        "/api/v1/clients/same-name-host/agents/codex",
        json={"managed_agent_id": "codex-agent"},
    )
    client.put(
        "/api/v1/clients/same-name-host/policy",
        json={"governance_mode": "strict"},
    )

    response = client.post(
        "/api/v1/clients/same-name-host/compare",
        headers=headers,
        json={
            "agents": [
                {
                    "agent_type": "codex",
                    "managed_agent_id": "codex-agent",
                    "skills": [
                        {
                            "name": "same",
                            "path": "/skills/first",
                            "signature": compute_content_signature(first_root),
                        },
                        {
                            "name": "same",
                            "path": "/skills/second",
                            "signature": compute_content_signature(second_root),
                        },
                    ],
                }
            ]
        },
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["local_path"] == "/skills/first"
    assert items[0]["allowed"] is False
    assert items[0]["reason"] == "signature_mismatch"
    assert items[1]["local_path"] == "/skills/second"
    assert items[1]["skill_id"] == "skill-2"
    assert items[1]["allowed"] is True


def test_compare_and_download_signed_approved_skill(tmp_path, monkeypatch):
    skill_root = tmp_path / "approved-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("---\nname: approved-skill\n---\n", encoding="utf-8")
    entry = type(
        "Entry",
        (),
        {
            "skill_id": "skill-1",
            "name": "approved-skill",
            "description": "用于安全地审查代码变更",
            "status": SkillStatus.APPROVED,
            "risk_level": None,
            "signature": "local-signature",
            "skill_path": str(skill_root),
        },
    )()
    rejected = type(
        "Entry",
        (),
        {
            "skill_id": "skill-2",
            "name": "rejected-skill",
            "status": SkillStatus.REJECTED,
            "signature": None,
            "skill_path": str(skill_root),
        },
    )()
    manager = _Manager({"approved-skill": entry, "skill-1": entry, "skill-2": rejected})
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    private_key.cache_clear()
    client = _client(tmp_path, manager)
    content_signature = compute_content_signature(skill_root)

    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "host-001",
            "name": "研发客户端",
            "hostname": "dev-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [
                {
                    "agent_type": "codex",
                    "skills_path": "/tmp/.codex/skills",
                    "skill_management_supported": True,
                }
            ],
        },
    )

    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedAgent(
            agent_id="codex-agent",
            name="Codex Agent",
            channel="Codex",
            status="active",
            created_by="admin",
            skill_names_json='["skill-1"]',
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()
    client.put(
        "/api/v1/clients/host-001/policy",
        json={"governance_mode": "strict"},
    )

    compared = client.post(
        "/api/v1/clients/host-001/compare",
        headers=headers,
        json={
            "agents": [
                {
                    "agent_type": "codex",
                    "managed_agent_id": "codex-agent",
                    "skills": [{"name": "approved-skill", "signature": content_signature}],
                }
            ]
        },
    )
    assert compared.status_code == 200
    assert compared.json()["items"][0]["allowed"] is True
    assert client.get("/api/v1/clients/host-001").json()["agents"][0]["managed_agent_id"] == "codex-agent"

    rejected_task = client.post(
        "/api/v1/clients/host-001/tasks",
        json={
            "task_type": "install_skill",
            "payload": {
                "agent_type": "codex",
                "managed_agent_id": "codex-agent",
                "skill_id": "skill-2",
            },
        },
    )
    assert rejected_task.status_code == 400
    assert rejected_task.json()["detail"] == "只能安装已批准的 Skill"

    install_task = client.post(
        "/api/v1/clients/host-001/tasks",
        json={
            "task_type": "install_skill",
            "payload": {
                "agent_type": "codex",
                "managed_agent_id": "codex-agent",
                "skill_id": "skill-1",
            },
        },
    )
    assert install_task.status_code == 200
    task = client.get("/api/v1/clients/host-001").json()["tasks"][0]
    assert task["payload"]["skill_name"] == "approved-skill"

    policy = client.get("/api/v1/clients/host-001/policy", headers=headers).json()
    available = client.get(
        "/api/v1/clients/host-001/skills/available",
        params={"agent_type": "codex", "managed_agent_id": "codex-agent"},
        headers=headers,
    )
    assert available.status_code == 200
    assert available.json()["items"] == [{"skill_id": "skill-1", "name": "approved-skill", "status": "APPROVED"}]
    preview = client.get(
        "/api/v1/clients/host-001/skills/skill-1/preview",
        params={"managed_agent_id": "codex-agent"},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["description"] == "用于安全地审查代码变更"
    package = client.get(
        "/api/v1/clients/host-001/skills/skill-1/package",
        params={"managed_agent_id": "codex-agent"},
        headers=headers,
    )
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        signature = base64.b64decode(archive.read("manifest.sig"))
        assert archive.read("skill/SKILL.md") == (skill_root / "SKILL.md").read_bytes()
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(policy["release_public_key"]))
    public_key.verify(signature, manifest_bytes)
    assert manifest["content_signature"] == content_signature


def test_client_cannot_download_skill_for_unbound_agent(tmp_path, monkeypatch):
    skill_root = tmp_path / "approved-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("---\nname: approved-skill\n---\n", encoding="utf-8")
    entry = type(
        "Entry",
        (),
        {
            "skill_id": "skill-1",
            "name": "approved-skill",
            "status": SkillStatus.APPROVED,
            "signature": "local-signature",
            "skill_path": str(skill_root),
        },
    )()
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    private_key.cache_clear()
    client = _client(tmp_path, _Manager({"skill-1": entry}))
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "host-001",
            "name": "研发客户端",
            "hostname": "dev-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [{"agent_type": "codex", "skill_management_supported": True}],
        },
    )
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedAgent(
            agent_id="other-agent",
            name="Other Agent",
            channel="Codex",
            status="active",
            created_by="admin",
            skill_names_json='["skill-1"]',
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()
    client.put(
        "/api/v1/clients/host-001/policy",
        json={"governance_mode": "strict"},
    )

    response = client.get(
        "/api/v1/clients/host-001/skills/skill-1/package",
        params={"managed_agent_id": "other-agent"},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "客户端未绑定该智能体"


def test_registry_mode_does_not_require_managed_agent_binding(tmp_path, monkeypatch):
    skill_root = tmp_path / "approved-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("---\nname: approved-skill\n---\n", encoding="utf-8")
    entry = type(
        "Entry",
        (),
        {
            "skill_id": "skill-1",
            "name": "approved-skill",
            "status": SkillStatus.APPROVED,
            "skill_path": str(skill_root),
        },
    )()
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    private_key.cache_clear()
    client = _client(tmp_path, _Manager({"skill-1": entry, "approved-skill": entry}))
    token = client.post("/api/v1/access/tokens", json={"name": "客户端接入", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "registry-host",
            "name": "Registry Host",
            "hostname": "registry-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [{"agent_type": "codex", "skill_management_supported": True}],
        },
    )
    signature = compute_content_signature(skill_root)
    compared = client.post(
        "/api/v1/clients/registry-host/compare",
        headers=headers,
        json={"agents": [{"agent_type": "codex", "skills": [{"name": "approved-skill", "signature": signature}]}]},
    )
    assert compared.status_code == 200
    assert compared.json()["items"][0]["allowed"] is True
    task = client.post(
        "/api/v1/clients/registry-host/tasks",
        json={"task_type": "install_skill", "payload": {"agent_type": "codex", "skill_id": "skill-1"}},
    )
    assert task.status_code == 200
    package = client.get(
        "/api/v1/clients/registry-host/skills/skill-1/package",
        params={"agent_type": "codex"},
        headers=headers,
    )
    assert package.status_code == 200


def test_register_auto_matches_only_unique_agent_type(tmp_path):
    client = _client(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedAgent(
            agent_id="codex-agent",
            name="Codex Agent",
            channel="Codex",
            status="active",
            created_by="admin",
            skill_names_json="[]",
            prompt_names_json="[]",
        )
    )
    database.commit()
    database.close()
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    response = client.post(
        "/api/v1/clients/register",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "client_id": "auto-host",
            "name": "Auto Host",
            "hostname": "auto-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [{"agent_type": "codex", "skill_management_supported": True}],
        },
    )
    assert response.status_code == 200
    assert response.json()["agents"][0]["managed_agent_id"] == "codex-agent"


def test_admin_cannot_read_another_owners_client(tmp_path):
    client = _client(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    database.add(
        models.ManagedClient(
            client_id="alice-host",
            name="Alice Host",
            hostname="alice",
            os="linux",
            arch="amd64",
            client_version="0.1.0",
            registered_by="alice",
        )
    )
    database.commit()
    database.close()
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(
        id=2,
        username="bob",
        hashed_password="x",
        role="admin",
    )
    assert client.get("/api/v1/clients/alice-host").status_code == 404
    assert client.get("/api/v1/clients").json() == []
