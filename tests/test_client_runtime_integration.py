"""Exercise the compiled Go client against the actual client API over HTTP."""

import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from agent_manager.core.manager import AgentManager
from tests.test_clients_api import _client


def test_go_client_records_changes_and_executes_content_bound_recovery(tmp_path):
    if not shutil.which("go"):
        pytest.skip("Go compiler is required for client runtime integration")
    repository = Path(__file__).resolve().parents[1]
    binary = tmp_path / "agent-manager-client"
    subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"], cwd=repository / "scanner", check=True, capture_output=True, timeout=120)
    manager = AgentManager(data_dir=tmp_path / "registry")
    admin = _client(tmp_path, manager)
    token_response = admin.post("/api/v1/access/tokens", json={"name": "runtime-integration", "token_type": "client"})
    assert token_response.status_code == 200
    token = token_response.json()["token"]
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    fail_reports = threading.Event()
    hold_claim = threading.Event()
    claim_entered = threading.Event()
    release_claim = threading.Event()
    requests = {"heartbeats": 0, "polls": 0, "failed_reports": 0}

    async def transport(scope, receive, send):
        # Faults affect transport only; authentication and task transitions remain real.
        if scope["type"] == "http":
            if scope["path"].endswith("/heartbeat"):
                requests["heartbeats"] += 1
            if scope["path"].endswith("/tasks") and scope["method"] == "GET":
                requests["polls"] += 1
            if hold_claim.is_set() and scope["path"].endswith("/result"):
                claim_entered.set()
                while not release_claim.is_set():
                    await asyncio.sleep(0.02)
        if scope["type"] == "http" and fail_reports.is_set() and (
            scope["path"].endswith("/events") or scope["path"].endswith("/result")
        ):
            messages = []
            while True:
                message = await receive()
                messages.append(message)
                if not message.get("more_body", False):
                    break
            body = json.loads(b"".join(item.get("body", b"") for item in messages) or b"{}")
            if body.get("status") != "running":
                if scope["path"].endswith("/result") and body.get("status") == "failed":
                    requests["failed_reports"] += 1
                await send({"type": "http.response.start", "status": 503, "headers": []})
                await send({"type": "http.response.body", "body": b"delivery unavailable"})
                return

            async def replay():
                return messages.pop(0) if messages else await receive()

            await admin.app(scope, replay, send)
            return
        await admin.app(scope, receive, send)

    server = uvicorn.Server(uvicorn.Config(transport, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    home = tmp_path / "device"
    skill = home / ".codex" / "skills" / "local-example"
    skill.mkdir(parents=True)
    original = "---\nname: local-example\ndescription: Local integration example\n---\nHello\n"
    (skill / "SKILL.md").write_text(original)
    shared_alias = home / ".claude" / "skills" / "local-example"
    shared_alias.parent.mkdir(parents=True)
    shared_alias.symlink_to(skill, target_is_directory=True)
    env = {**os.environ, "AGENT_MANAGER_CLIENT_HOME": str(home), "AGENT_MANAGER_CLIENT_SERVER": server_url, "AGENT_MANAGER_CLIENT_TOKEN": token}

    def cli(command, *arguments, succeeds=True):
        result = subprocess.run([str(binary), command, *arguments], env=env, text=True, capture_output=True, timeout=45)
        assert (result.returncode == 0) == succeeds, f"{command}: {result.stderr.replace(token, '[redacted]')}"
        return result.stdout

    daemon = None

    def await_value(read, predicate, description):
        deadline = time.monotonic() + 45
        value = None
        while time.monotonic() < deadline:
            assert daemon.poll() is None, "client daemon exited unexpectedly"
            value = read()
            if predicate(value):
                return value
            time.sleep(0.1)
        pytest.fail(f"Timed out waiting for {description}: {value}")

    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        daemon = subprocess.Popen([str(binary), "run", "--interval", "200ms"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        listing = await_value(lambda: admin.get("/api/v1/clients").json(),
                              lambda rows: bool(rows) and any(s.get("governance") for a in rows[0]["agents"] for s in a["skills"]),
                              "automatic registration and classification")
        assert len(listing) == 1
        client_id = listing[0]["client_id"]
        path = f"/api/v1/clients/{client_id}"

        def detail():
            response = admin.get(path)
            assert response.status_code == 200
            return response.json()

        def current_skill():
            return next(s for a in detail()["agents"] for s in a["skills"] if s["path"] == str(skill))

        observed = current_skill()
        assert observed["governance"]["trigger"] == "unverified"
        assert observed["governance"]["action"] == "record"
        alias_observation = next(s for a in detail()["agents"] for s in a["skills"] if s["path"] == str(shared_alias))
        assert alias_observation["governance"]["trigger"] == "unverified"
        assert alias_observation["governance"]["signature"] == observed["signature"]
        assert (skill / "SKILL.md").read_text() == original
        assert detail()["issue_count"] >= 1
        # A live Go long poll receives the committed policy task and acknowledges
        # the exact version only after persisting it and requesting inspection.
        governance_path = path + "/governance"
        current = admin.get(governance_path).json()
        update = {"expected_version": current["version"], "rules": {"malicious": "record_only"}}
        preview = admin.post(governance_path + "/preview", json=update)
        assert preview.status_code == 200, preview.text
        saved = admin.put(governance_path, json={**update, "preview_id": preview.json()["preview_id"]})
        assert saved.status_code == 200, saved.text
        target = saved.json()["version"]
        synchronized = await_value(lambda: detail()["tasks"],
                                   lambda tasks: any(t["task_type"] == "sync_policy" and t["payload"].get("target_version") == target and t["status"] == "succeeded" for t in tasks),
                                   "exact policy version acknowledgment through long polling")
        assert any(t["payload"].get("target_version") == target for t in synchronized)
        (skill / "SKILL.md").write_text(original + "User edit\n")
        changed = await_value(current_skill,
                              lambda s: s.get("governance", {}) and s["governance"].get("trigger") == "unverified_content_changed",
                              "file watcher classification")
        assert changed["signature"] != observed["signature"]
        assert changed["governance"]["trigger"] == "unverified_content_changed"
        # Hold the real task claim across a long-poll renewal interval. Other loops
        # must continue, and a shared-path edit must invalidate the queued action.
        hold_claim.set()
        slow = admin.post(path + "/tasks", json={"task_type": "skill_action", "payload": {
            "action": "quarantine", "agent_type": "codex", "path": str(skill),
            "expected_signature": changed["signature"], "request_id": "slow-conflicting-task",
        }})
        assert slow.status_code == 200, slow.text
        slow_id = slow.json()["id"]
        await_value(claim_entered.is_set, bool, "held task claim")
        heartbeat_before, polls_before = requests["heartbeats"], requests["polls"]
        await_value(lambda: dict(requests),
                    lambda value: value["heartbeats"] >= heartbeat_before + 3 and value["polls"] > polls_before,
                    "heartbeat and repeated task polling during held claim")
        changed_content = original + "User edit\nConcurrent shared edit\n"
        (shared_alias / "SKILL.md").write_text(changed_content)
        fail_reports.set()
        hold_claim.clear()
        release_claim.set()
        await_value(lambda: requests["failed_reports"], lambda count: count >= 2, "failed terminal delivery retries")
        assert (skill / "SKILL.md").read_text() == changed_content
        assert json.loads(cli("quarantine")) == []
        fail_reports.clear()
        completed = await_value(lambda: next(item for item in detail()["tasks"] if item["id"] == slow_id),
                                lambda task: task["status"] == "failed", "persistent failure receipt delivery")
        assert "skill_content_changed" in completed["error"], completed
        changed = await_value(current_skill, lambda item: item["signature"] != changed["signature"], "edited inventory")
        assert (shared_alias / "SKILL.md").read_text() == changed_content
        daemon.terminate()
        assert daemon.wait(timeout=10) == 0
        daemon = None
        # Drain events from the completed fault scenario before injecting the next outage.
        cli("run-once")
        task_body = {"task_type": "skill_action", "payload": {
            "action": "quarantine", "agent_type": "codex", "path": str(skill),
            "expected_signature": changed["signature"], "request_id": "integration-quarantine",
        }}
        created = admin.post(path + "/tasks", json=task_body)
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]
        assert admin.post(path + "/tasks", json=task_body).json()["id"] == task_id
        fail_reports.set()
        cli("run-once", succeeds=False)
        assert not skill.exists()
        assert next(item for item in detail()["tasks"] if item["id"] == task_id)["status"] == "running"
        copies = json.loads(cli("quarantine"))
        assert len(copies) == 1
        # A repeated remote task after lost acknowledgements must not remove new content.
        skill.mkdir()
        (skill / "SKILL.md").write_text("New content after interrupted delivery\n")
        fail_reports.clear()
        cli("run-once")
        assert (skill / "SKILL.md").read_text() == "New content after interrupted delivery\n"
        assert shared_alias.readlink() == skill
        assert len(json.loads(cli("quarantine"))) == 1
        shutil.rmtree(skill)
        cli("run-once")
        after = detail()
        task = next(item for item in after["tasks"] if item["id"] == task_id)
        assert task["status"] == "succeeded", task
        recovery = next(item for item in after["recovery"] if item["original_path"] == str(skill))
        assert recovery["signature"] == changed["signature"]
        recovered = admin.post(path + "/tasks", json={"task_type": "skill_action", "payload": {
            "action": "restore_quarantine", "agent_type": "codex", "path": str(skill),
            "expected_signature": recovery["signature"], "quarantine_id": recovery["id"], "request_id": "integration-restore",
        }})
        assert recovered.status_code == 200, recovered.text
        cli("run-once")
        assert (skill / "SKILL.md").read_text() == changed_content
        assert next(item for item in detail()["tasks"] if item["id"] == recovered.json()["id"])["status"] == "succeeded"
        backup_skill = home / ".agent-manager" / "backups" / "integration-backup" / "codex" / "local-example"
        backup_skill.mkdir(parents=True)
        backup_content = original + "Backup payload\n"
        (backup_skill / "SKILL.md").write_text(backup_content)
        arguments = ["--backup", "integration-backup", "--request-id", "integration-backup-request", "--confirm"]
        requested = json.loads(cli("restore", *arguments))
        assert requested["errors"] == [], requested
        assert len(requested["tasks"]) == 1
        assert (skill / "SKILL.md").read_text() == changed_content
        repeated = json.loads(cli("restore", *arguments))
        assert repeated["tasks"][0]["id"] == requested["tasks"][0]["id"]
        cli("run-once")
        assert (skill / "SKILL.md").read_text() == backup_content
        assert next(item for item in detail()["tasks"] if item["id"] == requested["tasks"][0]["id"])["status"] == "succeeded"
        changed = current_skill()
        # A previewed administrator rule must reach the runtime and apply to
        # the current content, without a separate local takeover operation.
        policy_path = path + "/governance"
        policy = admin.get(policy_path).json()
        change = {"expected_version": policy["version"], "rules": {
            "unverified": "quarantine", "unverified_content_changed": "quarantine",
        }}
        preview = admin.post(policy_path + "/preview", json=change)
        assert preview.status_code == 200, preview.text
        assert any(item["path"] == str(skill) for item in preview.json()["items"])
        saved = admin.put(policy_path, json={**change, "preview_id": preview.json()["preview_id"]})
        assert saved.status_code == 200, saved.text
        cli("run-once")
        assert not skill.exists()
        after_policy = detail()
        assert not shared_alias.exists()
        assert shared_alias.is_symlink()
        action = next(event for event in after_policy["events"] if event["event_type"] == "skill_governance_action" and event["details"].get("action") == "quarantine"
                   and event["details"].get("status") == "completed" and event["details"].get("policy_version") == saved.json()["version"]
                   and event["details"].get("path") == str(skill))
        retained = next(item for item in after_policy["recovery"] if item["id"] == action["details"]["quarantine_id"])
        assert retained["original_path"] == str(skill)
        assert retained["signature"] == changed["signature"]
        local_copy = next(item for item in json.loads(cli("quarantine")) if item["id"] == retained["id"])
        assert (Path(local_copy["quarantine_path"]) / "SKILL.md").read_text() == backup_content
        # All discovered entries may be links to a source outside Agent roots.
        # Reintroducing the same content must still enforce the current policy.
        external = home / "external-shared-skill"
        shutil.copytree(local_copy["quarantine_path"], external)
        shared_alias.unlink()
        skill.symlink_to(external, target_is_directory=True)
        shared_alias.symlink_to(external, target_is_directory=True)
        old_recovery_ids = {item["id"] for item in after_policy["recovery"]}
        cli("run-once")
        assert not skill.is_symlink() and not skill.exists()
        assert not shared_alias.is_symlink() and not shared_alias.exists()
        assert (external / "SKILL.md").read_text() == backup_content
        link_recoveries = [item for item in detail()["recovery"] if item["id"] not in old_recovery_ids]
        assert {item["original_path"] for item in link_recoveries} == {str(skill), str(shared_alias)}
        local_link_copies = [item for item in json.loads(cli("quarantine")) if item["id"] in {row["id"] for row in link_recoveries}]
        assert len({item["quarantine_path"] for item in local_link_copies}) == 1
        assert all(item["signature"] == changed["signature"] for item in link_recoveries)
    finally:
        release_claim.set()
        if daemon is not None and daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=5)
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive()


def test_real_scan_rejection_is_polled_and_quarantined_without_desktop(tmp_path, monkeypatch):
    """Real upload, manifest validation, scan pipeline and policy decision over HTTP.

    External LLM/sandbox/deep-scan services are disabled in this isolated test;
    the built-in scanning and admission pipeline are not replaced.
    """
    pytest.importorskip("skill_scanner", reason="Real scanner integration requires the project backend runtime")
    from agent_manager.api.scanner_router import router as scanner_router
    from agent_manager.core.policy import CompanyPolicy
    from agent_manager.core.models import SkillStatus

    monkeypatch.setenv("AGENT_MANAGER_DATA_DIR", str(tmp_path / "registry"))
    monkeypatch.setenv("AGENT_MANAGER_LLM_CONFIG", str(tmp_path / "llm.yaml"))
    monkeypatch.setenv("AGENT_MANAGER_SANDBOX_CONFIG", str(tmp_path / "sandbox.yaml"))
    monkeypatch.setenv("AGENT_MANAGER_LLM_ENABLED", "false")
    monkeypatch.setenv("AGENT_MANAGER_SANDBOX_ENABLED", "false")
    monkeypatch.setenv("SKILLSPECTOR_BIN", str(tmp_path / "not-installed"))
    manager = AgentManager(data_dir=tmp_path / "registry", policy=CompanyPolicy({
        "auto_reject_risk": ["benign", "suspicious", "malicious"], "scan_result_reuse_enabled": False,
    }))
    admin = _client(tmp_path, manager)
    admin.app.include_router(scanner_router)
    response = admin.post("/api/v1/access/tokens", json={"name": "scan-chain", "token_type": "client"})
    assert response.status_code == 200
    token = response.json()["token"]
    binary = tmp_path / "agent-manager-client"
    subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"],
                   cwd=Path(__file__).resolve().parents[1] / "scanner", check=True, capture_output=True, timeout=120)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(admin.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    gate = threading.Event()
    vet = manager.vetting.vet

    def wait_then_vet(*args, **kwargs):
        assert gate.wait(45), "test did not release real scan"
        return vet(*args, **kwargs)

    monkeypatch.setattr(manager.vetting, "vet", wait_then_vet)
    home = tmp_path / "device"
    skill = home / ".codex" / "skills" / "scan-chain"
    skill.mkdir(parents=True)
    original = "---\nname: scan-chain\ndescription: Simple greeting\n---\nSay hello.\n"
    (skill / "SKILL.md").write_text(original)
    env = {**os.environ, "AGENT_MANAGER_CLIENT_HOME": str(home), "AGENT_MANAGER_CLIENT_SERVER": url, "AGENT_MANAGER_CLIENT_TOKEN": token}
    daemon = None

    def wait(read, predicate, description, timeout=40):
        deadline = time.monotonic() + timeout
        value = None
        while time.monotonic() < deadline:
            if daemon:
                assert daemon.poll() is None, "headless daemon exited"
            value = read()
            if predicate(value):
                return value
            time.sleep(0.1)
        pytest.fail(f"Timed out: {description}: {value}")

    def save(scope, rules):
        current = admin.get(scope).json()
        body = {"rules": rules, "expected_version": current["version"]}
        preview = admin.post(scope + "/preview", json=body)
        assert preview.status_code == 200, preview.text
        body["preview_id"] = preview.json()["preview_id"]
        result = admin.put(scope, json=body)
        assert result.status_code == 200, result.text
        return result.json()

    try:
        save("/api/v1/clients/governance/default", {"unverified": "record_only", "unverified_content_changed": "submit_scan", "unverified_scan_rejected": "quarantine"})
        thread.start()
        wait(lambda: server.started, bool, "HTTP server")
        daemon = subprocess.Popen([str(binary), "run", "--interval", "200ms"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rows = wait(lambda: admin.get("/api/v1/clients").json(), lambda rows: bool(rows), "registration")
        root = f"/api/v1/clients/{rows[0]['client_id']}"

        def detail():
            result = admin.get(root)
            assert result.status_code == 200, result.text
            return result.json()

        def observed():
            return next((s for a in detail()["agents"] for s in a["skills"] if s["path"] == str(skill)), {})

        first = wait(observed, lambda s: (s.get("governance") or {}).get("action") == "record_only", "record-only classification")
        assert detail()["classification"]["advanced_supported"]
        assert detail()["issue_count"] == 0
        (skill / "SKILL.md").write_text(original + "A local edit.\n")
        progress = wait(observed, lambda s: ((s.get("governance") or {}).get("scan") or {}).get("progress", {}).get("stage") == "preparing", "headless scan progress")
        assert progress["signature"] != first["signature"]
        assert (skill / "SKILL.md").exists()
        version = progress["governance"]["scan"]["version_id"]
        gate.set()
        wait(lambda: manager.get_skill(version), lambda e: e.status == SkillStatus.REJECTED, "real scan rejection")
        entry = manager.get_skill(version)
        assert entry.vetting and not entry.vetting.scan_report.get("vetting_failed")
        assert not entry.vetting.scan_report.get("scanner_error")
        assert entry.risk_level.value != "malicious", "this test targets rejection, not the malicious rule"
        events = wait(lambda: detail()["events"], lambda events: any(e["event_type"] == "skill_governance_action" and e["details"].get("trigger") == "unverified_scan_rejected" and e["details"].get("status") == "completed" for e in events), "automatic rejection quarantine")
        assert not (skill / "SKILL.md").exists()
        assert any(e["details"].get("quarantine_id") for e in events)
        def pending_items():
            result = subprocess.run([str(binary), "pending"], env=env, capture_output=True, text=True, check=True, timeout=10)
            return json.loads(result.stdout)
        wait(pending_items, lambda items: any(item["version_id"] == version and item["status"] == "REJECTED" for item in items), "terminal progress persisted by daemon")
        assert len(manager.list_skills()) == 1, "the same snapshot was submitted twice"
    finally:
        gate.set()
        if daemon and daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=10)
        server.should_exit = True
        if thread.is_alive():
            thread.join(timeout=10)
        listener.close()
