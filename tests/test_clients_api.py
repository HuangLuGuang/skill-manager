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
from agent_manager.core.signer import compute_content_digest
from backend import auth, models, schemas
from backend.api_errors import ApiError, api_error_handler
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
    app.add_exception_handler(ApiError, api_error_handler)
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
    entry = type("Entry", (), {
        "skill_id": "skill-1",
        "version_no": 1,
        "name": "shared",
        "skill_path": "/skills/shared",
        "status": SkillStatus.APPROVED,
    })()
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


def test_compare_prefers_reported_approved_version_when_signatures_collide(monkeypatch):
    rejected = type("Entry", (), {
        "skill_id": "version-1",
        "version_no": 1,
        "name": "shared",
        "skill_path": "/skills/rejected",
        "status": SkillStatus.REJECTED,
    })()
    approved = type("Entry", (), {
        "skill_id": "version-2",
        "version_no": 2,
        "name": "shared",
        "skill_path": "/skills/approved",
        "status": SkillStatus.APPROVED,
    })()
    monkeypatch.setattr(clients, "compute_content_signature", lambda _path: "same-signature")
    manager = _Manager({"rejected": rejected, "approved": approved})
    entries = manager.list_skills()

    exact = clients._matching_skill_entry(
        manager,
        schemas.ClientSkillCompareItem(
            name="shared",
            signature="same-signature",
            version_id="version-2",
        ),
        registry_entries=entries,
    )
    legacy = clients._matching_skill_entry(
        manager,
        schemas.ClientSkillCompareItem(name="shared", signature="same-signature"),
        registry_entries=entries,
    )

    assert exact is approved
    assert legacy is approved


def test_compare_uses_newest_approved_version_even_if_scan_risk_was_malicious(monkeypatch):
    from types import SimpleNamespace
    safe = SimpleNamespace(skill_id="rescanned-v1", version_no=1, name="sample",
                           skill_path="/safe", status=SkillStatus.APPROVED, risk_level="benign")
    old = SimpleNamespace(skill_id="old-v2", version_no=2, name="sample",
                          skill_path="/old", status=SkillStatus.APPROVED, risk_level="malicious")
    monkeypatch.setattr(clients, "compute_content_signature", lambda path: "same-content")
    local = schemas.ClientSkillCompareItem(name="sample", signature="same-content")
    manager = _Manager({"safe": safe, "old": old})
    assert clients._matching_skill_entry(manager, local) is old


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


def test_client_observation_round_trip_requires_matching_content(tmp_path):
    client = _client(tmp_path)
    created = client.post(
        "/api/v1/access/tokens", json={"name": "observation", "token_type": "client"},
    )
    assert created.status_code == 200
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    observation = {
        "signature": "current",
        "trusted_signature": "baseline",
        "certification": "changed",
        "trigger": "trusted_content_changed",
        "action": "record",
        "policy_version": "1:2",
        "action_status": "completed",
        "count": 3,
        "scan": {"status": "PENDING", "skill_id": "family", "version_id": "scan-v1", "progress": {
            "stage": "analyzers", "analyzers": {"scanner": "completed", "llm": "running"},
            "version_id": "scan-v1", "updated_at": None,
        }},
    }
    skill = {
        "name": "local", "path": "/skills/local", "signature": "current",
        "governance": observation,
    }
    body = {
        "client_id": "observation-host", "name": "host", "hostname": "host",
        "os": "linux", "arch": "amd64", "client_version": "1.0", "governance_protocol": 1,
        "agents": [{"agent_type": "codex", "skills_path": "/skills", "skills": [skill]}],
    }
    assert client.post("/api/v1/clients/register", headers=headers, json=body).status_code == 200
    response = client.get("/api/v1/clients/observation-host")
    assert response.status_code == 200
    reported = response.json()["agents"][0]["skills"][0]["governance"]
    assert all(reported[key] == value for key, value in observation.items())
    assert response.json()["issue_count"] == 1
    # Shared paths count once, even when multiple Agents report the same content.
    body["agents"].append({"agent_type": "hermes", "skills_path": "/skills", "skills": [skill]})
    assert client.post("/api/v1/clients/observation-host/inventory", headers=headers, json=body).status_code == 200
    assert client.get("/api/v1/clients").json()[0]["issue_count"] == 1
    # Submitting a scan is not a resolution of the current content warning.
    assert client.post("/api/v1/clients/observation-host/events", headers=headers, json={
        "event_type": "skill_scan_submitted", "agent_type": "codex", "skill_name": "local",
    }).status_code == 200
    assert client.get("/api/v1/clients/observation-host").json()["issue_count"] == 1
    # A later inventory must not present an earlier content verdict as current.
    skill["signature"] = "edited-again"
    assert client.post("/api/v1/clients/observation-host/inventory", headers=headers, json=body).status_code == 200
    assert client.get("/api/v1/clients/observation-host").json()["agents"][0]["skills"][0]["governance"] is None
    assert client.get("/api/v1/clients/observation-host").json()["issue_count"] == 0
    observation.update(signature="edited-again", certification="certified", trigger="", action_status="completed")
    assert client.post("/api/v1/clients/observation-host/inventory", headers=headers, json=body).status_code == 200
    assert client.get("/api/v1/clients/observation-host").json()["issue_count"] == 0
    observation["action_status"] = "failed"
    assert client.post("/api/v1/clients/observation-host/inventory", headers=headers, json=body).status_code == 200
    assert client.get("/api/v1/clients/observation-host").json()["issue_count"] == 1


def test_governance_events_aggregate_retries_and_preserve_policy_changes(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "events", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "events-host", "name": "host", "hostname": "host",
        "os": "linux", "arch": "amd64", "client_version": "1.0", "governance_protocol": 1,
    }).status_code == 200
    body = {"event_type": "skill_governance_detected", "agent_type": "codex", "skill_name": "sample",
            "details": {"path": "/skills/sample", "signature": "content", "trigger": "unverified",
                        "action": "record", "policy_version": "1:0"}}
    ids = []
    for count, observed in [(1, "2026-09-11T08:00:00Z"), (3, "2026-09-11T08:10:00Z"), (1, "2026-09-11T08:00:00Z")]:
        response = client.post("/api/v1/clients/events-host/events", headers=headers,
                               json={**body, "observation_count": count, "observed_at": observed})
        assert response.status_code == 200, response.text
        ids.append(response.json()["event_id"])
    assert len(set(ids)) == 1
    events = client.get("/api/v1/clients/events-host").json()["events"]
    assert len(events) == 1
    assert events[0]["observation_count"] == 3
    assert events[0]["last_seen_at"].startswith("2026-09-11T08:10:00")
    body["details"]["policy_version"] = "2:0"
    response = client.post("/api/v1/clients/events-host/events", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["event_id"] != ids[0]
    body["details"]["signature"] = "changed-content"
    assert client.post("/api/v1/clients/events-host/events", headers=headers, json=body).status_code == 200
    assert len(client.get("/api/v1/clients/events-host").json()["events"]) == 3


def test_backup_restore_authorization_binds_both_backup_and_current_content(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "backup", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    registered = client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "backup-host", "name": "Backup", "hostname": "host", "os": "linux", "arch": "amd64", "client_version": "1.0", "governance_protocol": 1,
        "agents": [{"agent_type": "codex", "skills_path": "/skills", "skills": [{"name": "sample", "path": "/skills/sample", "signature": "current-content"}]}],
        "recovery": [{"id": "backup-copy", "agent_type": "codex", "skill_name": "sample", "original_path": "/skills/sample", "signature": "backup-content", "status": "backed_up", "reason": "backup"}],
    })
    assert registered.status_code == 200, registered.text
    action = {"request_id": "restore-backup", "action": "restore_backup", "agent_type": "codex", "path": "/skills/sample", "expected_signature": "backup-content", "quarantine_id": "backup-copy"}
    for target_signature in [None, "old-content"]:
        response = client.post("/api/v1/clients/backup-host/skill-actions", headers=headers, json={**action, "expected_target_signature": target_signature})
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "client.skill_content_changed"
    action["expected_target_signature"] = "current-content"
    created = client.post("/api/v1/clients/backup-host/skill-actions", headers=headers, json=action)
    assert created.status_code == 200, created.text
    assert created.json()["payload"]["expected_target_signature"] == "current-content"
    assert created.json()["payload"]["expected_signature"] == "backup-content"
    duplicate = client.post("/api/v1/clients/backup-host/skill-actions", headers=headers, json=action)
    assert duplicate.json()["id"] == created.json()["id"]


def test_recovery_tasks_bind_client_copy_and_inventory(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "recovery", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    agent = {"agent_type": "codex", "local_agent_id": "codex", "skills_path": "/skills", "skills": []}
    copy = {"id": "retained-copy", "agent_type": "codex", "skill_name": "sample", "original_path": "/skills/sample", "signature": "retained-content", "status": "quarantined", "reason": "unverified"}
    registered = client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "recovery-host", "name": "Recovery", "hostname": "host", "os": "linux", "arch": "amd64", "client_version": "1.0",
        "governance_protocol": 1, "agents": [agent], "recovery": [copy],
    })
    assert registered.status_code == 200, registered.text
    assert registered.json()["recovery"][0]["signature"] == copy["signature"]
    action = {"request_id": "restore-1", "action": "restore_quarantine", "agent_type": "codex", "path": copy["original_path"], "expected_signature": copy["signature"], "quarantine_id": copy["id"]}
    denied = client.post("/api/v1/clients/recovery-host/skill-actions", headers=headers, json=action)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error_code"] == "client.manual_uninstall_restore_only"
    updated = client.post("/api/v1/clients/recovery-host/inventory", headers=headers, json={"agents": [agent], "recovery": []})
    assert updated.status_code == 200, updated.text
    assert client.get("/api/v1/clients/recovery-host").json()["recovery"] == []


def test_manual_skill_actions_require_scope_bind_content_and_deduplicate(tmp_path):
    client = _client(tmp_path)
    def connect(name, scopes=None):
        token = client.post("/api/v1/access/tokens", json={"name": name, "token_type": "client", **({"scopes": scopes} if scopes else {})}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post("/api/v1/clients/register", headers=headers, json={
            "client_id": name, "name": name, "hostname": name, "os": "linux", "arch": "amd64", "client_version": "1.0",
            "governance_protocol": 1,
            "agents": [{"agent_type": "codex", "local_agent_id": "codex", "skills_path": "/skills",
                        "skills": [{"name": "sample", "path": "/skills/sample", "signature": "selected-content"}]}],
        })
        assert response.status_code == 200, response.text
        return headers
    headers = connect("actions-host")
    restricted = connect("restricted-host", ["client:register", "client:read-policy"])
    action = {"request_id": "click-1", "action": "quarantine", "agent_type": "codex",
              "path": "/skills/sample", "expected_signature": "selected-content"}
    denied = client.post("/api/v1/clients/restricted-host/skill-actions", headers=restricted, json=action)
    assert denied.status_code == 403
    ids = []
    for _ in range(2):
        response = client.post("/api/v1/clients/actions-host/skill-actions", headers=headers, json=action)
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
        assert response.json()["payload"]["expected_signature"] == "selected-content"
        assert response.json()["task_type"] == "skill_action"
    assert ids[0] == ids[1]
    scan_request = {**action, "request_id": "admin-scan", "action": "submit_scan"}
    scan = client.post("/api/v1/clients/actions-host/tasks", json={"task_type": "skill_action", "payload": scan_request})
    assert scan.status_code == 200, scan.text
    repeated_scan = client.post("/api/v1/clients/actions-host/tasks", json={"task_type": "skill_action", "payload": scan_request})
    assert repeated_scan.json()["id"] == scan.json()["id"]
    conflict = client.post("/api/v1/clients/actions-host/skill-actions", headers=headers, json={**action, "action": "uninstall"})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "client.action_request_conflict"
    stale = client.post("/api/v1/clients/actions-host/skill-actions", headers=headers, json={**action, "request_id": "click-2", "expected_signature": "old-content"})
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "client.skill_content_changed"
    cross_client = client.post("/api/v1/clients/restricted-host/skill-actions", headers=headers, json=action)
    assert cross_client.status_code == 403
    malformed = client.post("/api/v1/clients/actions-host/tasks", json={"task_type": "skill_action", "payload": {}})
    assert malformed.status_code == 422
    assert malformed.json()["error_code"] == "client.action_payload_invalid"
    task_id = ids[0]
    root = "/api/v1/clients/actions-host/tasks"
    assert client.post(f"{root}/{task_id}/cancel").status_code == 200
    late_start = client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "running"})
    assert late_start.json() == {"ok": True, "ignored": True, "status": "cancelled"}
    retried = client.post(f"{root}/{task_id}/retry")
    assert retried.status_code == 200, retried.text
    retry_id = retried.json()["id"]
    assert retry_id != task_id
    assert client.post(f"{root}/{task_id}/retry").json()["id"] == retry_id
    started = client.post(f"{root}/{retry_id}/result", headers=headers, json={"status": "running"})
    assert started.json()["ignored"] is False
    mid_action_cancel = client.post(f"{root}/{retry_id}/cancel")
    assert mid_action_cancel.status_code == 409
    assert mid_action_cancel.json()["error_code"] == "client.action_already_started"
    assert client.post(f"{root}/{retry_id}/result", headers=headers, json={"status": "failed", "error": "skill_content_changed"}).status_code == 200
    inventory = {"agents": [{"agent_type": "codex", "local_agent_id": "codex", "skills_path": "/skills", "skills": [{"name": "sample", "path": "/skills/sample", "signature": "new-content"}]}]}
    assert client.post("/api/v1/clients/actions-host/inventory", headers=headers, json=inventory).status_code == 200
    stale_retry = client.post(f"{root}/{retry_id}/retry")
    assert stale_retry.status_code == 409
    assert stale_retry.json()["error_code"] == "client.skill_content_changed"
    terminal_start = client.post(f"{root}/{retry_id}/result", headers=headers, json={"status": "running"})
    assert terminal_start.json()["ignored"] is True
    assert terminal_start.json()["status"] == "failed"


def test_legacy_removal_requests_pin_inventory_and_retry_as_content_bound_actions(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "removal", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    registered = client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "remove-host", "name": "Remove", "hostname": "host", "os": "linux", "arch": "amd64", "client_version": "new", "governance_protocol": 1,
        "agents": [{"agent_type": "codex", "skills_path": "/skills", "skills": [{"skill_id": "family", "name": "sample", "path": "/skills/actual-folder", "signature": "selected-content"}]}],
    })
    assert registered.status_code == 200, registered.text
    root = "/api/v1/clients/remove-host/tasks"
    created = client.post(root, json={"task_type": "remove_skill", "payload": {"agent_type": "codex", "skill_id": "family", "skill_name": "other-folder", "path": "/wrong", "expected_signature": "wrong"}})
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]
    task = client.get(root, headers=headers).json()[0]
    assert task["payload"]["path"] == "/skills/actual-folder"
    assert task["payload"]["expected_signature"] == "selected-content"
    assert task["payload"]["actor"] == "admin"
    assert client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "running"}).json()["ignored"] is False
    assert client.post(f"{root}/{task_id}/cancel").status_code == 409
    assert client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "failed"}).status_code == 200
    retry = client.post(f"{root}/{task_id}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] != task_id
    retried = next(task for task in client.get(root, headers=headers).json() if task["id"] == retry.json()["id"])
    assert retried["task_type"] == "skill_action"
    assert retried["payload"]["action"] == "uninstall"
    assert retried["payload"]["expected_signature"] == "selected-content"


def test_install_and_repair_retries_use_new_ids_and_keep_content_preconditions(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "retry", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "retry-host", "name": "Retry", "hostname": "host", "os": "linux", "arch": "amd64", "client_version": "new", "agents": [],
    }).status_code == 200
    root = "/api/v1/clients/retry-host/tasks"
    for task_type in ("install_skill", "repair_skill"):
        payload = {"agent_type": "codex", "skill_id": "family", "expected_root": "/skills", "expected_targets": {"/skills/sample": "selected-content"}}
        database = next(client.app.dependency_overrides[get_db]())
        row = models.ClientTask(client_id="retry-host", task_type=task_type, payload_json=json.dumps(payload))
        database.add(row)
        database.commit()
        task_id = row.id
        database.close()
        assert client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "running"}).json()["ignored"] is False
        assert client.post(f"{root}/{task_id}/cancel").status_code == 409
        assert client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "failed"}).status_code == 200
        assert client.post(f"{root}/{task_id}/result", headers=headers, json={"status": "running"}).json()["ignored"] is True
        retry = client.post(f"{root}/{task_id}/retry")
        assert retry.status_code == 200, retry.text
        retry_id = retry.json()["id"]
        assert retry_id != task_id
        assert client.post(f"{root}/{task_id}/retry").json()["id"] == retry_id
        polled = next(item for item in client.get(root, headers=headers).json() if item["id"] == retry_id)
        assert polled["payload"] == payload
        assert client.post(f"{root}/{retry_id}/cancel").status_code == 200
        assert client.post(f"{root}/{retry_id}/result", headers=headers, json={"status": "running"}).json()["status"] == "cancelled"


def test_default_classification_policy_saves_auditable_dates_and_requires_super_admin(tmp_path):
    client = _client(tmp_path)
    root = "/api/v1/clients/governance/default"
    policy = client.get(root).json()
    assert policy["editable"] is True
    change = {"rules": {"malicious": "quarantine"}, "expected_version": policy["version"]}
    preview = client.post(root + "/preview", json=change)
    assert preview.status_code == 200, preview.text
    saved = client.put(root, json={**change, "preview_id": preview.json()["preview_id"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["rules"]["malicious"] == "quarantine"
    assert saved.json()["updated_at"]
    assert client.get(root).json()["version"] == saved.json()["version"]
    client.app.dependency_overrides[auth.get_current_admin_user] = lambda: models.User(id=2, username="limited", hashed_password="x", role="admin")
    readonly = client.get(root)
    assert readonly.status_code == 200 and readonly.json()["editable"] is False
    denied = client.put(root, json={**change, "preview_id": preview.json()["preview_id"]})
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "client.default_policy_forbidden"


def test_existing_client_upgrade_automatically_enables_preserved_policy(tmp_path):
    client = _client(tmp_path)
    token = client.post("/api/v1/access/tokens", json={"name": "upgrade", "token_type": "client"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    registered = client.post("/api/v1/clients/register", headers=headers, json={
        "client_id": "upgrade-host", "name": "Upgrade", "hostname": "old-host", "os": "linux", "arch": "amd64", "client_version": "old",
        "agents": [{"agent_type": "codex", "skills_path": "/skills", "skills": []}],
    })
    assert registered.status_code == 200, registered.text
    root = "/api/v1/clients/upgrade-host"
    assert client.put(root + "/policy", json={"mode": "repair"}).status_code == 200
    original = client.get(root + "/governance").json()
    assert original["supported"] is False
    assert original["enabled"] is False
    upgrade = client.post(root + "/heartbeat", headers=headers, json={"client_id": "upgrade-host", "client_version": "new", "governance_protocol": 1})
    assert upgrade.status_code == 200, upgrade.text
    assert upgrade.json()["policy"]["mode"] == "repair"
    migrated = upgrade.json()["policy"]["classification"]
    assert migrated["enabled"] is True
    assert migrated["rules"]["trusted_content_changed"] == "restore_trusted"
    assert migrated["rules"]["unverified"] == "record"
    repeated = client.post(root + "/heartbeat", headers=headers, json={"client_id": "upgrade-host", "governance_protocol": 1})
    assert repeated.json()["policy"]["classification"]["version"] == migrated["version"]
    protected = client.put(root + "/policy", json={"mode": "block"})
    assert protected.status_code == 409
    assert protected.json()["error_code"] == "client.classification_policy_active"
    downgraded = client.post(root + "/heartbeat", headers=headers, json={"client_id": "upgrade-host", "client_version": "old", "governance_protocol": 0})
    assert downgraded.status_code == 200
    assert downgraded.json()["policy"]["classification"]["enabled"] is False
    assert downgraded.json()["policy"]["mode"] == "repair"
    restored = client.post(root + "/heartbeat", headers=headers, json={"client_id": "upgrade-host", "client_version": "new", "governance_protocol": 1})
    assert restored.json()["policy"]["classification"]["enabled"] is True
    assert restored.json()["policy"]["classification"]["rules"] == migrated["rules"]


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
    registered_ids = {
        item["agent_type"]: item["managed_agent_id"]
        for item in registered.json()["agents"]
    }
    assert registered_ids["codex"].startswith("client-host-001-codex-")
    assert registered_ids["legacy-client"].startswith("client-host-001-legacy-client-")

    repeated = client.post("/api/v1/clients/register", headers=headers, json=json.loads(registered.request.content))
    assert repeated.status_code == 200
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.ClientEvent).filter_by(client_id="host-001", event_type="client_registered").count() == 1
    database.close()

    runtime_policy = client.get("/api/v1/clients/host-001/policy", headers=headers)
    assert runtime_policy.status_code == 200
    assert runtime_policy.json()["agent_bindings"] == registered_ids
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
    assert refreshed.json()["agents"][0]["managed_agent_id"] == registered_ids["codex"]

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
    assert runtime_status.json()["agents"][0]["managed_agent_id"] == registered_ids["codex"]
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
    assert detail.json()["agents"][0]["managed_agent_id"] == registered_ids["codex"]
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


def test_client_applies_agent_scoped_model_config_without_secret_in_task(tmp_path):
    client = _client(tmp_path)
    client_credential = client.post(
        "/api/v1/access/tokens",
        json={"name": "model-host", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {client_credential}"}

    database = next(client.app.dependency_overrides[get_db]())
    provider = models.ModelProvider(
        name="platform-gateway",
        base_url="https://models.example.com/v1",
        api_format="anthropic",
        enabled=True,
    )
    database.add(provider)
    database.flush()
    database.add(
        models.ModelEndpoint(
            provider_id=provider.id,
            name="claude-sonnet",
            display_name="Claude Sonnet",
            enabled=True,
        )
    )
    database.add(models.McpGateway(slug="readonly", name="Readonly", status="active"))
    database.commit()
    database.close()

    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "host-model",
            "name": "Model Host",
            "hostname": "model-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.2.0",
            "agents": [
                {
                    "local_agent_id": "claude-main",
                    "agent_type": "claude-code",
                    "skills_path": "/tmp/home/.claude/skills",
                    "capabilities": {"model_config_auto_apply": True},
                }
            ],
        },
    )
    assert registered.status_code == 200
    assert registered.json()["agents"][0]["local_agent_id"] == "claude-main"
    managed_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    assert managed_agent_id.startswith("client-host-model-claude-main-")
    database = next(client.app.dependency_overrides[get_db]())
    database.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one().allowed_mcp_gateways_json = '["readonly"]'
    database.commit()
    database.close()
    runtime_credential = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "claude-composite-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": managed_agent_id,
            "scopes": [
                "runtime:verify-signature",
                "runtime:can-load",
                "runtime:check-tool",
                "model:chat",
                "mcp:connect",
                "mcp:list-tools",
                "mcp:call-tools",
            ],
            "allowed_models": ["claude-sonnet"],
            "allowed_mcp_gateways": ["readonly"],
        },
    )
    assert runtime_credential.status_code == 200

    policy = client.get("/api/v1/clients/host-model/policy", headers=headers)
    assert policy.status_code == 200
    assert policy.json()["agent_profiles"] == [
        {
            "local_agent_id": "claude-main",
            "agent_type": "claude-code",
            "managed_agent_id": managed_agent_id,
            "default_model": None,
            "allowed_models": ["claude-sonnet"],
            "allowed_mcp_gateways": ["readonly"],
            "auto_apply_supported": True,
        }
    ]

    rejected = client.post(
        "/api/v1/clients/host-model/tasks",
        json={"task_type": "apply_model_config", "payload": {
            "local_agent_id": "claude-main", "agent_type": "claude-code",
            "model": "claude-sonnet", "parameters": {"timeout_ms": 1000},
        }},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "client.model_parameter_version_unverified"
    current = client.get("/api/v1/clients/host-model").json()["agents"][0]
    assert current["capabilities"]["model_config_contract"]["parameters"] == {}

    task = client.post(
        "/api/v1/clients/host-model/tasks",
        json={
            "task_type": "apply_model_config",
            "payload": {
                "local_agent_id": "claude-main",
                "agent_type": "claude-code",
                "managed_agent_id": "ignored-by-server",
                "model": "claude-sonnet",
                "token": "must-not-be-forwarded",
            },
        },
    )
    assert task.status_code == 200
    preflight_url = f"/api/v1/clients/host-model/tasks/{task.json()['id']}/model-preflight"
    preflight_body = {"revision": "0" * 64, "current_parameters": {"max_output_tokens": 1024}}
    assert client.post(preflight_url, headers=headers, json=preflight_body).status_code == 200
    database = next(client.app.dependency_overrides[get_db]())
    target = database.query(models.ModelEndpoint).filter_by(name="claude-sonnet").one()
    target.max_output_tokens = 512
    database.commit()
    too_large = client.post(preflight_url, headers=headers, json=preflight_body)
    assert too_large.status_code == 422
    assert too_large.json()["error_code"] == "client.model_output_limit"
    target.enabled = False
    database.commit()
    assert client.post(preflight_url, headers=headers, json=preflight_body).json()["error_code"] == "model.not_found"
    target.enabled = True
    target.max_output_tokens = None
    database.commit()
    database.close()
    polled = client.get("/api/v1/clients/host-model/tasks", headers=headers).json()
    assert polled == [
        {
            "id": task.json()["id"],
            "task_type": "apply_model_config",
            "payload": {
                "local_agent_id": "claude-main",
                "agent_type": "claude-code",
                "managed_agent_id": managed_agent_id,
                "model": "claude-sonnet",
                "parameters": {},
            },
        }
    ]
    assert runtime_credential.json()["token"] not in json.dumps(polled)
    completed = client.post(
        f"/api/v1/clients/host-model/tasks/{task.json()['id']}/result",
        headers=headers,
        json={"status": "succeeded"},
    )
    assert completed.status_code == 200

    repeated = client.post(
        "/api/v1/clients/host-model/tasks",
        json={
            "task_type": "apply_model_config",
            "payload": {
                "local_agent_id": "claude-main",
                "agent_type": "claude-code",
                "model": "claude-sonnet",
            },
        },
    )
    cancelled = client.post(f"/api/v1/clients/host-model/tasks/{repeated.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert client.get("/api/v1/clients/host-model").json()["agents"][0]["model_config_status"] == "cancelled"
    retried = client.post(f"/api/v1/clients/host-model/tasks/{repeated.json()['id']}/retry")
    assert retried.json()["status"] == "pending"
    assert retried.json()["id"] != repeated.json()["id"]
    assert client.get("/api/v1/clients/host-model").json()["agents"][0]["model_config_status"] == "pending"
    assert client.post(
        f"/api/v1/clients/host-model/tasks/{retried.json()['id']}/result",
        headers=headers,
        json={"status": "succeeded"},
    ).status_code == 200

    detail = client.get("/api/v1/clients/host-model").json()
    local_agent = detail["agents"][0]
    assert local_agent["desired_model"] == "claude-sonnet"
    assert local_agent["applied_model"] == "claude-sonnet"
    assert local_agent["model_config_status"] == "pending_restart"
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one().default_model == "claude-sonnet"
    database.close()


def test_client_can_issue_task_bound_agent_runtime_credential_when_explicitly_allowed(tmp_path):
    client = _client(tmp_path)
    created_client_credential = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "auto-model-host",
            "token_type": "client",
            "allow_agent_credential_issuance": True,
        },
    )
    assert created_client_credential.status_code == 200
    client_token = created_client_credential.json()["token"]
    client_token_id = created_client_credential.json()["record"]["id"]
    headers = {"Authorization": f"Bearer {client_token}"}

    database = next(client.app.dependency_overrides[get_db]())
    provider = models.ModelProvider(
        name="auto-provider",
        base_url="https://models.example.com/v1",
        api_format="anthropic",
        enabled=True,
    )
    database.add(provider)
    database.flush()
    database.add(models.ModelEndpoint(provider_id=provider.id, name="claude-auto", enabled=True))
    database.commit()
    database.close()

    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "auto-model-host",
            "name": "Auto Model Host",
            "hostname": "auto-model-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.2.0",
            "agents": [
                {
                    "local_agent_id": "claude-main",
                    "agent_type": "claude-code",
                    "skills_path": "/tmp/home/.claude/skills",
                    "capabilities": {"model_config_auto_apply": True},
                }
            ],
        },
    )
    assert registered.status_code == 200
    managed_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    assert managed_agent_id.startswith("client-auto-model-host-claude-main-")

    task = client.post(
        "/api/v1/clients/auto-model-host/tasks",
        json={
            "task_type": "apply_model_config",
            "payload": {
                "local_agent_id": "claude-main",
                "agent_type": "claude-code",
                "model": "claude-auto",
            },
        },
    )
    assert task.status_code == 200
    polled = client.get("/api/v1/clients/auto-model-host/tasks", headers=headers).json()
    assert polled[0]["payload"]["auto_issue_credential"] is True
    assert "token" not in polled[0]["payload"]
    assert client.post(
        f"/api/v1/clients/auto-model-host/tasks/{task.json()['id']}/result",
        headers=headers,
        json={"status": "running"},
    ).status_code == 200

    issued = client.post(
        f"/api/v1/clients/auto-model-host/tasks/{task.json()['id']}/agent-credential",
        headers=headers,
        json={},
    )
    assert issued.status_code == 200
    assert issued.json()["token"].startswith("amat_")
    assert issued.json()["bound_agent_id"] == managed_agent_id
    assert issued.json()["allowed_models"] == ["claude-auto"]

    database = next(client.app.dependency_overrides[get_db]())
    runtime = database.query(models.AccessToken).filter(
        models.AccessToken.issued_by_client_token_id == client_token_id,
        models.AccessToken.status == "active",
    ).one()
    assert runtime.bound_agent_id == managed_agent_id
    assert json.loads(runtime.scopes_json) == [
        "runtime:verify-signature",
        "runtime:can-load",
        "runtime:check-tool",
        "model:chat",
    ]
    assert json.loads(runtime.allowed_models_json) == ["claude-auto"]
    database.close()

    revoked = client.post(f"/api/v1/access/tokens/{client_token_id}/revoke")
    assert revoked.status_code == 200
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.AccessToken).filter(
        models.AccessToken.issued_by_client_token_id == client_token_id,
        models.AccessToken.status == "active",
    ).count() == 0
    database.close()


def test_client_model_switch_catalog_binding_and_task_credential_are_self_service(tmp_path):
    client = _client(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    provider = models.ModelProvider(
        name="gateway-provider",
        base_url="https://models.example.com/v1",
        api_format="openai",
        enabled=True,
    )
    database.add(provider)
    other_provider = models.ModelProvider(name="other-provider", base_url="https://other.example.com/v1", enabled=True)
    database.add(other_provider)
    database.flush()
    database.add_all([
        models.ModelEndpoint(provider_id=provider.id, name="codex-allowed", upstream_name="shared-model", display_name="Codex Allowed", enabled=True),
        models.ModelEndpoint(provider_id=other_provider.id, name="codex-hidden", upstream_name="shared-model", display_name="Codex Hidden", enabled=True),
        models.ManagedAgent(agent_id="codex-primary", name="Primary Codex", channel="Codex", status="active", created_by="admin"),
        models.ManagedAgent(agent_id="codex-secondary", name="Secondary Codex", channel="Codex", status="active", created_by="admin"),
        models.McpGateway(slug="developer-tools", name="Developer Tools", status="active"),
    ])
    database.commit()
    database.close()

    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "codex-model-switcher",
            "token_type": "client",
            "allow_agent_credential_issuance": True,
            "allowed_models": ["codex-allowed"],
        },
    )
    assert created.status_code == 200
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "codex-switch-host",
            "name": "Codex Switch Host",
            "hostname": "codex-switch-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.3.0",
            "agents": [{
                "local_agent_id": "codex",
                "agent_type": "codex",
                "skills_path": "/tmp/home/.codex/skills",
                "capabilities": {"model_config_auto_apply": True},
            }],
        },
    )
    assert registered.status_code == 200
    managed_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    assert managed_agent_id.startswith("client-codex-switch-host-codex-")
    database = next(client.app.dependency_overrides[get_db]())
    database.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one().allowed_mcp_gateways_json = '["developer-tools"]'
    database.commit()
    database.close()
    mcp_runtime = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "codex-existing-runtime",
            "token_type": "agent_runtime",
            "bound_agent_id": managed_agent_id,
            "scopes": ["runtime:can-load", "mcp:connect", "mcp:list-tools", "mcp:call-tools"],
            "allowed_mcp_gateways": ["developer-tools"],
        },
    )
    assert mcp_runtime.status_code == 200

    status = client.get("/api/v1/clients/codex-switch-host/status", headers=headers)
    assert status.status_code == 200
    assert [item["name"] for item in status.json()["model_configuration"]["models"]] == ["codex-allowed"]
    assert status.json()["model_configuration"]["models"][0]["upstream_name"] == "shared-model"
    assert status.json()["model_configuration"]["models"][0]["provider_name"] == "gateway-provider"
    assert "available_managed_agents" not in status.json()

    task = client.post(
        "/api/v1/clients/codex-switch-host/model-configurations",
        headers=headers,
        json={
            "local_agent_id": "codex",
            "agent_type": "codex",
            "managed_agent_id": managed_agent_id,
            "model": "codex-allowed",
        },
    )
    assert task.status_code == 200
    assert task.json()["task_type"] == "apply_model_config"
    assert task.json()["payload"]["auto_issue_credential"] is True
    assert "token" not in task.json()["payload"]

    denied = client.post(
        "/api/v1/clients/codex-switch-host/model-configurations",
        headers=headers,
        json={"local_agent_id": "codex", "agent_type": "codex", "model": "codex-hidden"},
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "client.model_not_delegated"

    issued = client.post(
        f"/api/v1/clients/codex-switch-host/tasks/{task.json()['id']}/agent-credential",
        headers=headers,
        json={},
    )
    assert issued.status_code == 200
    assert issued.json()["bound_agent_id"] == managed_agent_id
    assert issued.json()["allowed_models"] == ["codex-allowed"]
    assert issued.json()["allowed_mcp_gateways"] == ["developer-tools"]
    database = next(client.app.dependency_overrides[get_db]())
    runtime = database.query(models.AccessToken).filter(
        models.AccessToken.issued_by_client_token_id == created.json()["record"]["id"],
        models.AccessToken.status == "active",
    ).one()
    assert set(json.loads(runtime.scopes_json)) == {
        "runtime:verify-signature",
        "runtime:can-load",
        "runtime:check-tool",
        "model:chat",
        "mcp:connect",
        "mcp:list-tools",
        "mcp:call-tools",
    }
    stale_task = database.query(models.ClientTask).filter(models.ClientTask.id == task.json()["id"]).one()
    stale_task.started_at = datetime.utcnow() - timedelta(minutes=11)
    database.commit()
    database.close()

    retried = client.post(
        "/api/v1/clients/codex-switch-host/model-configurations",
        headers=headers,
        json={"local_agent_id": "codex", "agent_type": "codex", "model": "codex-allowed"},
    )
    assert retried.status_code == 200
    assert retried.json()["id"] != task.json()["id"]
    database = next(client.app.dependency_overrides[get_db]())
    stale_task = database.query(models.ClientTask).filter(models.ClientTask.id == task.json()["id"]).one()
    assert stale_task.status == "failed"
    assert stale_task.error == "model_config.task_timeout"
    database.close()


def test_client_registration_auto_creates_runtime_identity_for_model_switch(tmp_path):
    client = _client(tmp_path)
    database = next(client.app.dependency_overrides[get_db]())
    provider = models.ModelProvider(
        name="auto-identity-provider",
        base_url="https://models.example.com/v1",
        api_format="openai",
        enabled=True,
    )
    database.add(provider)
    database.flush()
    database.add(models.ModelEndpoint(provider_id=provider.id, name="claude-auto", enabled=True))
    database.commit()
    database.close()

    created = client.post(
        "/api/v1/access/tokens",
        json={
            "name": "auto-identity-client",
            "token_type": "client",
            "allow_agent_credential_issuance": True,
            "allowed_models": ["claude-auto"],
        },
    )
    headers = {"Authorization": f"Bearer {created.json()['token']}"}
    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "designer-mac",
            "name": "Designer Mac",
            "hostname": "designer-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.3.0",
            "agents": [{
                "local_agent_id": "claude-code",
                "agent_type": "claude-code",
                "skills_path": "/tmp/home/.claude/skills",
                "capabilities": {"model_config_auto_apply": True},
            }],
        },
    )
    assert registered.status_code == 200
    registered_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    assert registered_agent_id.startswith("client-designer-mac-claude-code-")

    switched = client.post(
        "/api/v1/clients/designer-mac/model-configurations",
        headers=headers,
        json={"local_agent_id": "claude-code", "agent_type": "claude-code", "model": "claude-auto"},
    )
    assert switched.status_code == 200
    managed_agent_id = switched.json()["payload"]["managed_agent_id"]
    assert managed_agent_id == registered_agent_id
    assert "token" not in switched.json()["payload"]

    refreshed = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "designer-mac",
            "name": "Designer Mac",
            "hostname": "designer-mac",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.3.0",
            "agents": [{
                "local_agent_id": "claude-code",
                "agent_type": "claude-code",
                "skills_path": "/tmp/home/.claude/skills",
                "capabilities": {"model_config_auto_apply": True},
            }],
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["agents"][0]["managed_agent_id"] == managed_agent_id

    database = next(client.app.dependency_overrides[get_db]())
    local_agent = database.query(models.ClientAgent).filter(
        models.ClientAgent.client_id == "designer-mac",
        models.ClientAgent.local_agent_id == "claude-code",
    ).one()
    runtime_identity = database.query(models.ManagedAgent).filter(
        models.ManagedAgent.agent_id == managed_agent_id,
    ).one()
    assert local_agent.managed_agent_id == managed_agent_id
    assert local_agent.takeover_status == "managed"
    assert runtime_identity.origin_type == "client_discovery"
    assert runtime_identity.name == "Designer Mac · Claude Code"
    assert runtime_identity.channel == "Claude Code"
    assert runtime_identity.created_by == "admin"
    assert database.query(models.ClientEvent).filter(
        models.ClientEvent.client_id == "designer-mac",
        models.ClientEvent.event_type == "managed_agent_auto_created",
    ).count() == 1
    database.close()

    issued = client.post(
        f"/api/v1/clients/designer-mac/tasks/{switched.json()['id']}/agent-credential",
        headers=headers,
        json={},
    )
    assert issued.status_code == 200
    assert issued.json()["bound_agent_id"] == managed_agent_id
    assert issued.json()["allowed_models"] == ["claude-auto"]


def test_client_without_permission_cannot_issue_agent_runtime_credential(tmp_path):
    client = _client(tmp_path)
    client_token = client.post(
        "/api/v1/access/tokens",
        json={"name": "restricted-host", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {client_token}"}
    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "restricted-host",
            "name": "Restricted Host",
            "hostname": "restricted-host",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.2.0",
            "agents": [],
        },
    )
    assert registered.status_code == 200
    denied = client.post(
        "/api/v1/clients/restricted-host/tasks/999/agent-credential",
        headers=headers,
        json={},
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "client.agent_credential_issuance_disabled"


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
    (release_dir / "preview.json").write_text(
        json.dumps(
            {
                "version": "0.3.0",
                "notes": "preview release",
                "pub_date": "2026-07-17T00:00:00Z",
                "platforms": {
                    "darwin-aarch64": {
                        "file": artifact.name,
                        "signature": "preview-signature",
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

    registered = client.post(
        "/api/v1/clients/register",
        headers=headers,
        json={
            "client_id": "update-signal-client",
            "name": "Update Signal Client",
            "hostname": "update-signal-client",
            "os": "darwin",
            "arch": "arm64",
            "client_version": "0.1.0",
            "agents": [],
        },
    )
    assert registered.status_code == 200
    task_poll = client.get("/api/v1/clients/update-signal-client/tasks", headers=headers)
    assert task_poll.status_code == 200
    assert task_poll.headers["x-agent-manager-client-stable-version"] == "0.2.0"
    assert task_poll.headers["x-agent-manager-client-preview-version"] == "0.3.0"

    denied = client.get("/api/v1/clients/updates/darwin/arm64/0.1.0")
    assert denied.status_code == 401
    checked = client.get("/api/v1/clients/updates/darwin/arm64/0.1.0", headers=headers)
    assert checked.status_code == 200
    assert checked.json()["version"] == "0.2.0"
    assert checked.json()["signature"] == "test-signature"
    preview = client.get(
        "/api/v1/clients/updates/darwin/arm64/0.1.0",
        params={"channel": "preview"},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["version"] == "0.3.0"
    assert preview.json()["signature"] == "preview-signature"
    invalid_channel = client.get(
        "/api/v1/clients/updates/darwin/arm64/0.1.0",
        params={"channel": "nightly"},
        headers=headers,
    )
    assert invalid_channel.status_code == 400
    downloaded = client.get(checked.json()["url"], headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == b"signed-update"


def test_preview_update_channel_without_manifest_returns_no_content(tmp_path, monkeypatch):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    monkeypatch.setattr(clients, "_CLIENT_RELEASE_DIR", release_dir)
    client = _client(tmp_path)
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]

    response = client.get(
        "/api/v1/clients/updates/darwin/arm64/0.1.0",
        params={"channel": "preview"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert response.content == b""


def test_only_latest_client_installers_are_listed_and_downloadable(tmp_path, monkeypatch):
    release_dir = tmp_path / "releases"
    release_dir.mkdir()
    older = release_dir / "agent-manager-client-26.03.14-windows-x86_64.exe"
    newer = release_dir / "agent-manager-client-26.03.15-darwin-aarch64.dmg"
    newer_windows = release_dir / "agent-manager-client-26.03.15-windows-x86_64.exe"
    same_day_newer = release_dir / "agent-manager-client-26.03.15.2-darwin-aarch64.dmg"
    same_day_newer_windows = release_dir / "agent-manager-client-26.03.15.2-windows-x86_64.exe"
    ignored = release_dir / "agent-manager-client-26.03.15-darwin-aarch64.app.tar.gz"
    older.write_bytes(b"windows")
    newer.write_bytes(b"macos")
    newer_windows.write_bytes(b"new-windows")
    same_day_newer.write_bytes(b"macos-revision-2")
    same_day_newer_windows.write_bytes(b"windows-revision-2")
    ignored.write_bytes(b"updater")
    monkeypatch.setattr(clients, "_CLIENT_RELEASE_DIR", release_dir)
    client = _client(tmp_path)

    response = client.get("/api/v1/clients/downloads/available")
    assert response.status_code == 200
    assert {item["version"] for item in response.json()["items"]} == {"26.03.15.2"}
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
    assert downloaded.content in {b"macos-revision-2", b"windows-revision-2"}
    partial = client.get(
        ticket.json()["url"],
        headers={"Range": "bytes=0-2"},
    )
    assert partial.status_code == 206
    assert partial.content in {b"mac", b"win"}

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


def test_client_content_signature_normalizes_legacy_zip_mojibake_paths(tmp_path):
    normal = tmp_path / "normal"
    mojibake = tmp_path / "mojibake"
    (normal / "references").mkdir(parents=True)
    (mojibake / "references").mkdir(parents=True)
    (normal / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (mojibake / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (normal / "references" / "常用查询模板.md").write_text("select 1", encoding="utf-8")
    mojibake_name = "σ╕╕τö¿µƒÑΦ»óµ¿íµ¥┐.md"
    (mojibake / "references" / mojibake_name).write_text("select 1", encoding="utf-8")

    assert compute_content_signature(normal) == compute_content_signature(mojibake)
    assert compute_content_signature(mojibake) == compute_content_digest(mojibake)
    manifest = clients.build_manifest("skill-1", "demo", mojibake, None)
    assert f"references/{mojibake_name}" in {item["path"] for item in manifest["files"]}


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
        {
            "skill_id": "skill-2",
            "family_id": "family-2",
            "name": "same",
            "status": SkillStatus.APPROVED,
            "skill_path": str(second_root),
        },
    )()
    client = _client(tmp_path, _Manager({"same": first, "skill-1": first, "skill-2": second, "family-2": second}))
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    registered = client.post(
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
    managed_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    database = next(client.app.dependency_overrides[get_db]())
    auto_identity = database.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one()
    auto_identity.skill_names_json = '["family-2"]'
    database.commit()
    database.close()
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
                    "managed_agent_id": managed_agent_id,
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
    assert items[1]["skill_id"] == "family-2"
    assert items[1]["version_id"] == "skill-2"
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
            "source": type("Source", (), {"author": "alice"})(),
            "submitted_at": datetime(2026, 7, 30, 3, 0, 0),
            "approved_at": datetime(2026, 7, 30, 3, 5, 0),
            "approved_by": "reviewer",
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
                    "skills_path": "/tmp/.codex/skills",
                    "skill_management_supported": True,
                }
            ],
        },
    )
    managed_agent_id = registered.json()["agents"][0]["managed_agent_id"]
    database = next(client.app.dependency_overrides[get_db]())
    auto_identity = database.query(models.ManagedAgent).filter_by(agent_id=managed_agent_id).one()
    auto_identity.skill_names_json = '["skill-1"]'
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
                    "managed_agent_id": managed_agent_id,
                    "skills": [{"name": "approved-skill", "signature": content_signature}],
                }
            ]
        },
    )
    assert compared.status_code == 200
    assert compared.json()["items"][0]["allowed"] is True
    assert client.get("/api/v1/clients/host-001").json()["agents"][0]["managed_agent_id"] == managed_agent_id

    rejected_task = client.post(
        "/api/v1/clients/host-001/tasks",
        json={
            "task_type": "install_skill",
            "payload": {
                "agent_type": "codex",
                "managed_agent_id": managed_agent_id,
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
                "managed_agent_id": managed_agent_id,
                "skill_id": "skill-1",
            },
        },
    )
    assert install_task.status_code == 200
    task = client.get("/api/v1/clients/host-001").json()["tasks"][0]
    assert task["payload"]["skill_name"] == "approved-skill"
    assert task["payload"]["version_id"] == "skill-1"
    assert task["payload"]["expected_root"] == "/tmp/.codex/skills"
    assert task["payload"]["expected_targets"] == {}

    current_path = "/tmp/.codex/skills/approved-skill"
    updated = client.post(
        "/api/v1/clients/host-001/inventory", headers=headers,
        json={"agents": [{"agent_type": "codex", "skills_path": "/tmp/.codex/skills",
                          "skill_management_supported": True, "managed_agent_id": managed_agent_id,
                          "skills": [{"name": "approved-skill", "path": current_path, "signature": "edited-content"}]}]},
    )
    assert updated.status_code == 200
    repair = client.post(
        "/api/v1/clients/host-001/tasks",
        json={"task_type": "repair_skill", "payload": {"agent_type": "codex", "managed_agent_id": managed_agent_id, "skill_id": "skill-1",
                                                       "expected_targets": {current_path: "caller-supplied"}}},
    )
    assert repair.status_code == 200
    repair_task = next(item for item in client.get("/api/v1/clients/host-001").json()["tasks"] if item["id"] == repair.json()["id"])
    assert repair_task["payload"]["expected_targets"] == {current_path: "edited-content"}

    policy = client.get("/api/v1/clients/host-001/policy", headers=headers).json()
    available = client.get(
        "/api/v1/clients/host-001/skills/available",
        params={"agent_type": "codex", "managed_agent_id": managed_agent_id},
        headers=headers,
    )
    assert available.status_code == 200
    assert available.json()["items"] == [{
        "skill_id": "skill-1",
        "version_id": "skill-1",
        "version_no": 1,
        "source_version": None,
        "name": "approved-skill",
        "status": "APPROVED",
        "submitted_by": "alice",
        "submitted_at": "2026-07-30T03:00:00",
    }]
    exact_available = client.get(
        "/api/v1/clients/host-001/skills/available",
        params={
            "agent_type": "codex",
            "managed_agent_id": managed_agent_id,
            "skill_id": "skill-1",
        },
        headers=headers,
    )
    assert exact_available.status_code == 200
    assert exact_available.json() == available.json()
    preview = client.get(
        "/api/v1/clients/host-001/skills/skill-1/preview",
        params={"managed_agent_id": managed_agent_id},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["description"] == "用于安全地审查代码变更"
    assert preview.json()["submitted_by"] == "alice"
    assert preview.json()["submitted_at"] == "2026-07-30T03:00:00"
    versions = client.get(
        "/api/v1/clients/host-001/skills/skill-1/versions",
        params={"agent_type": "codex", "managed_agent_id": managed_agent_id},
        headers=headers,
    )
    assert versions.status_code == 200
    assert versions.json()["items"][0]["version_no"] == 1
    assert versions.json()["items"][0]["submitted_by"] == "alice"
    assert versions.json()["items"][0]["submitted_at"] == "2026-07-30T03:00:00"
    package = client.get(
        "/api/v1/clients/host-001/skills/skill-1/package",
        params={"managed_agent_id": managed_agent_id},
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

    exact_available = client.get(
        "/api/v1/clients/host-001/skills/available",
        params={
            "agent_type": "codex",
            "managed_agent_id": "other-agent",
            "skill_id": "skill-1",
        },
        headers=headers,
    )
    assert exact_available.status_code == 403
    assert exact_available.json()["detail"] == "客户端未绑定该智能体"


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
            "risk_level": "malicious",
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
    verdict = compared.json()["items"][0]
    assert verdict["allowed"] is True
    assert verdict["certified"] is True
    assert verdict["malicious"] is False
    assert verdict["reason"] == "allowed"

    entry.status = SkillStatus.VETTED
    pending_review = client.post(
        "/api/v1/clients/registry-host/compare",
        headers=headers,
        json={"agents": [{"agent_type": "codex", "skills": [{"name": "approved-skill", "signature": signature}]}]},
    ).json()["items"][0]
    assert pending_review["allowed"] is False
    assert pending_review["certified"] is False
    assert pending_review["malicious"] is True
    assert pending_review["reason"] == "malicious"
    entry.status = SkillStatus.APPROVED

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


def test_registry_available_skills_use_display_names_and_latest_submission_order(tmp_path):
    class SummaryManager(_Manager):
        def list_skill_summaries(self, **kwargs):
            assert kwargs["sort_by"] == "submitted_at"
            assert kwargs["sort_order"] == "desc"
            assert kwargs["trusted_only"] is True
            ordered = sorted(
                self.list_skills(),
                key=lambda entry: entry.submitted_at,
                reverse=True,
            )
            return {
                "items": [
                    {
                        "skill_id": entry.family_id,
                        "version_id": entry.skill_id,
                        "version_no": entry.version_no,
                        "source_version": None,
                        "name": entry.name,
                        "status": entry.status.value,
                        "submitted_by": entry.source.author,
                        "submitted_at": entry.submitted_at,
                    }
                    for entry in ordered
                ]
            }

        def get_trusted_skill(self, value):
            return self.entries.get(value)

    def make_entry(version_id, family_id, generated_name, heading, submitted_at):
        skill_root = tmp_path / generated_name
        skill_root.mkdir()
        (skill_root / "SKILL.md").write_text(f"# {heading}\n", encoding="utf-8")
        return type(
            "Entry",
            (),
            {
                "skill_id": version_id,
                "family_id": family_id,
                "version_no": 1,
                "name": generated_name,
                "description": "",
                "status": SkillStatus.APPROVED,
                "skill_path": str(skill_root),
                "submitted_at": submitted_at,
                "source": type("Source", (), {"author": "admin"})(),
            },
        )()

    older = make_entry(
        "version-old",
        "family-old",
        "063abf7c7194468c8c6c69b160acebe9",
        "older-friendly-name",
        "2026-07-01T03:00:00",
    )
    newer = make_entry(
        "version-new",
        "family-new",
        "f48649032a594c019e09b74c741c68cc",
        "newer-friendly-name",
        "2026-07-30T03:00:00",
    )
    manager = SummaryManager({
        older.skill_id: older,
        older.family_id: older,
        newer.skill_id: newer,
        newer.family_id: newer,
    })
    client = _client(tmp_path, manager)
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
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

    response = client.get(
        "/api/v1/clients/registry-host/skills/available",
        params={"agent_type": "codex"},
        headers=headers,
    )

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == [
        "newer-friendly-name",
        "older-friendly-name",
    ]
    assert [item["submitted_at"] for item in response.json()["items"]] == [
        "2026-07-30T03:00:00",
        "2026-07-01T03:00:00",
    ]


def test_registry_available_skills_exact_query_bypasses_catalog_page(tmp_path):
    skill_root = tmp_path / "older-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Older Skill\n", encoding="utf-8")
    entry = type(
        "Entry",
        (),
        {
            "skill_id": "version-old",
            "family_id": "family-old",
            "version_no": 3,
            "source_version": "3.0.0",
            "name": "older-skill",
            "description": "",
            "status": SkillStatus.APPROVED,
            "skill_path": str(skill_root),
            "submitted_at": "2026-06-01T03:00:00",
            "source": type("Source", (), {"author": "admin"})(),
        },
    )()

    class ExactManager(_Manager):
        def list_skill_summaries(self, **_kwargs):
            raise AssertionError("exact lookup must not read the paginated catalog")

    manager = ExactManager({entry.skill_id: entry, entry.family_id: entry})
    client = _client(tmp_path, manager)
    token = client.post(
        "/api/v1/access/tokens",
        json={"name": "客户端接入", "token_type": "client"},
    ).json()["token"]
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

    response = client.get(
        "/api/v1/clients/registry-host/skills/available",
        params={"agent_type": "codex", "skill_id": "family-old"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["items"] == [{
        "skill_id": "family-old",
        "version_id": "version-old",
        "version_no": 3,
        "source_version": "3.0.0",
        "name": "older-skill",
        "status": "APPROVED",
        "submitted_by": "admin",
        "submitted_at": "2026-06-01T03:00:00",
    }]


def test_register_creates_client_owned_identity_instead_of_matching_platform_agent(tmp_path):
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
    managed_agent_id = response.json()["agents"][0]["managed_agent_id"]
    assert managed_agent_id.startswith("client-auto-host-codex-")
    assert managed_agent_id != "codex-agent"
    database = next(client.app.dependency_overrides[get_db]())
    assert database.query(models.ManagedAgent).filter_by(
        agent_id=managed_agent_id,
        origin_type="client_discovery",
    ).one()
    database.close()


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


def test_policy_delivery_checks_reported_action_capabilities(tmp_path):
    client = _client(tmp_path)
    response = client.post('/api/v1/access/tokens', json={'name': 'capabilities', 'token_type': 'client'})
    headers = {'Authorization': 'Bearer ' + response.json()['token']}
    root = '/api/v1/clients/capability-host'
    registration = client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'capability-host', 'name': 'Capability', 'hostname': 'host',
        'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'governance_protocol': 2,
    })
    assert registration.status_code == 200, registration.text
    policy = client.get(root + '/governance').json()
    body = {'rules': {'unverified': 'record_only'}, 'expected_version': policy['version']}
    preview = client.post(root + '/governance/preview', json=body)
    assert preview.status_code == 200, preview.text
    body['preview_id'] = preview.json()['preview_id']
    assert client.put(root + '/governance', json=body).status_code == 200
    heartbeat = client.post(root + '/heartbeat', headers=headers, json={'client_id': 'capability-host', 'governance_protocol': 1})
    assert heartbeat.status_code == 409
    assert heartbeat.json()['error_code'] == 'client.policy_capability_required'
    assert client.get(root + '/policy', headers=headers).status_code == 409
    restored = client.post(root + '/heartbeat', headers=headers, json={'client_id': 'capability-host', 'governance_protocol': 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()['policy']['classification']['rules']['unverified'] == 'record_only'


def test_discovery_catalog_save_validation_and_client_sync(tmp_path):
    client = _client(tmp_path)
    url = '/api/v1/clients/discovery-config'
    initial = client.get(url)
    assert initial.status_code == 200, initial.text
    catalog = initial.json()
    seeds = {a['agent_type']: a for a in catalog['agents']}
    assert seeds['qoder']['skill_roots'] == ['.qoder/skills']
    assert seeds['qoder-cn']['skill_roots'] == ['.qoder-cn/skills']
    assert seeds['teleagent']['skill_roots'] == ['.config/TeleAgent/users/*/skills']
    assert not seeds['claude-desktop']['enabled']
    agent = dict(agent_type='company', name='Company', enabled=True, systems=['linux'], skill_roots=['~/company/users/*/skills'])
    body = {'expected_version': catalog['version'], 'agents': [agent]}
    saved = client.put(url, json=body)
    assert saved.status_code == 200, saved.text
    saved_by_type = {item['agent_type']: item for item in saved.json()['agents']}
    assert saved_by_type['company'] == agent
    assert saved_by_type['teleagent']['skill_roots'] == ['.config/TeleAgent/users/*/skills']
    assert client.get(url).json() == saved.json()
    assert client.put(url, json=body).status_code == 409
    current = saved.json()['version']
    for invalid in [dict(agent, skill_roots=[]), dict(agent, skill_roots=['../skills']), dict(agent, skill_roots=['~/company/user*/skills']), dict(agent, systems=[]), dict(agent, agent_type='../../bad')]:
        assert client.put(url, json={'expected_version': current, 'agents': [invalid]}).status_code == 422
    assert client.put(url, json={'expected_version': current, 'agents': [agent, agent]}).status_code == 422
    token = client.post('/api/v1/access/tokens', json={'name': 'discovery', 'token_type': 'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    registered = client.post('/api/v1/clients/register', headers=headers, json={
        'client_id': 'discovery-host', 'name': 'host', 'hostname': 'host', 'os': 'linux', 'arch': 'amd64', 'client_version': 'dev', 'agents': [],
    })
    assert registered.status_code == 200, registered.text
    policy = client.get('/api/v1/clients/discovery-host/policy', headers=headers)
    assert policy.json()['agent_discovery'] == saved.json()
    heartbeat = client.post('/api/v1/clients/discovery-host/heartbeat', headers=headers, json={'client_id': 'discovery-host'})
    assert heartbeat.json()['policy']['agent_discovery'] == saved.json()
    empty = client.put(url, json={'expected_version': current, 'agents': []})
    assert empty.status_code == 200, empty.text
    assert [item['agent_type'] for item in empty.json()['agents']] == ['teleagent']
    tasks = client.get('/api/v1/clients/discovery-host/tasks', headers=headers).json()
    discovery_tasks = [task for task in tasks if task['payload'].get('agent_discovery_version')]
    assert len(discovery_tasks) == 1
    assert discovery_tasks[0]['task_type'] == 'sync_policy'
    assert discovery_tasks[0]['payload']['agent_discovery_version'] == empty.json()['version']
    assert client.get('/api/v1/clients/discovery-host/policy', headers=headers).json()['agent_discovery'] == empty.json()
    unchanged = client.put(url, json={'expected_version': empty.json()['version'], 'agents': empty.json()['agents']})
    assert unchanged.status_code == 200
    assert client.get('/api/v1/clients/discovery-host/tasks', headers=headers).json() == tasks


def test_admin_client_events_pagination_beyond_one_hundred(tmp_path):
    client = _client(tmp_path)
    db = next(client.app.dependency_overrides[get_db]())
    try:
        db.add(models.ManagedClient(client_id='paged', name='Paged', hostname='host', os='linux', arch='amd64', client_version='dev'))
        db.flush()
        for index in range(105):
            db.add(models.ClientEvent(client_id='paged', event_type='skill_action', skill_name=str(index), created_at=datetime(2026, 1, 1)))
        db.add(models.ClientEvent(client_id='paged', event_type='client_registered'))
        db.commit()
    finally:
        db.close()
    first = client.get('/api/v1/clients/paged').json()
    assert first['events_total'] == 105
    assert len(first['events']) == 10
    assert first['events'][0]['skill_name'] == '104'
    last = client.get('/api/v1/clients/paged', params={'event_page': 11}).json()
    assert len(last['events']) == 5
    assert last['events'][-1]['skill_name'] == '0'
    assert not set(e['id'] for e in first['events']) & set(e['id'] for e in last['events'])
    assert client.get('/api/v1/clients/paged', params={'event_page': 99}).json()['event_page'] == 11
    assert client.get('/api/v1/clients/paged', params={'event_page': 0}).status_code == 422


def test_model_operations_share_revision_checks_claim_and_evidence_gate(tmp_path):
    client = _client(tmp_path)
    token = client.post('/api/v1/access/tokens', json={'name':'probe-client','token_type':'client'}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    state = {'change_id':'change-1','revision':'a'*64,'model':'model-a','can_restore':True}
    assert client.post('/api/v1/clients/register', headers=headers, json={
        'client_id':'probe-host','name':'Probe','hostname':'test','os':'darwin','arch':'arm64','client_version':'test',
        'agents':[{'agent_type':'hermes','local_agent_id':'hermes','capabilities':{'model_config_auto_apply':True,'model_config_verification':True,'model_config_state':state}}],
    }).status_code == 200
    payload = {'agent_type':'hermes','local_agent_id':'hermes','change_id':'change-1','expected_revision':'a'*64}
    endpoint = '/api/v1/clients/probe-host/model-operations'
    first = client.post(endpoint, headers=headers, json={'task_type':'verify_model_config','payload':payload})
    assert first.status_code == 200, first.text
    repeated = client.post(endpoint, headers=headers, json={'task_type':'verify_model_config','payload':payload})
    assert repeated.json()['id'] == first.json()['id']
    result_url = f"/api/v1/clients/probe-host/tasks/{first.json()['id']}/result"
    assert client.post(result_url, headers=headers, json={'status':'running'}).json()['ignored'] is False
    assert client.post(result_url, headers=headers, json={'status':'running'}).json()['ignored'] is True
    cancelled = client.post(f"/api/v1/clients/probe-host/tasks/{first.json()['id']}/cancel")
    assert cancelled.status_code == 409
    denied = client.post(result_url, headers=headers, json={'status':'succeeded','verification_request_ids':[]})
    assert denied.status_code == 409
    assert denied.json()['error_code'] == 'client.model_evidence_required'
    detail = client.get('/api/v1/clients/probe-host').json()
    assert detail['agents'][0]['model_config_status'] == 'failed'
    stale = client.post(endpoint, headers=headers, json={'task_type':'restore_model_config','payload':{**payload,'expected_revision':'b'*64}})
    assert stale.status_code == 409
    remote = client.post('/api/v1/clients/probe-host/tasks', json={'task_type':'restore_model_config','payload':payload})
    assert remote.status_code == 200, remote.text
    duplicate = client.post(endpoint, headers=headers, json={'task_type':'restore_model_config','payload':payload})
    assert duplicate.json()['id'] == remote.json()['id']
