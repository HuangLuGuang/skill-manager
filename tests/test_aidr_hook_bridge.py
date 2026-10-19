"""Real bridge/receiver/HTTP integration with synthetic host input, not Agent acceptance."""
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import uvicorn

from tests.test_aidr_api import service


def test_go_bridge_to_platform_with_owned_processes(service, tmp_path):
    from backend import auth, iam, models
    client, factory = service
    client.app.dependency_overrides[auth.get_current_active_user] = lambda: models.User(
        id=1, username='owner', role='admin', is_active=True)
    with factory() as db:
        iam.initialize(db)
    repository = Path(__file__).resolve().parents[1]
    binary = tmp_path / "agent-manager-client"
    subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"], cwd=repository / "scanner", check=True, capture_output=True, timeout=120)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="critical", access_log=False, lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    process = None
    with tempfile.TemporaryDirectory(prefix="aidr-p3-bridge-") as directory:
        root = Path(directory).resolve()
        state = root / "state"
        sock = root / "h.sock"
        env = {**os.environ, "AIDR_SYNTHETIC_TEST_TOKEN": "test-one"}
        try:
            process = subprocess.Popen([str(binary), "aidr-hook-serve", "--state-dir", str(state), "--socket", str(sock), "--server", f"http://127.0.0.1:{listener.getsockname()[1]}", "--client-id", "one", "--token-env", "AIDR_SYNTHETIC_TEST_TOKEN"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic()+15
            health = None
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise AssertionError("owned hook receiver exited before readiness")
                reply = subprocess.run([str(binary), "aidr-hook", "--socket", str(sock), "--health"], capture_output=True, timeout=5)
                if reply.returncode == 0:
                    health = json.loads(reply.stdout)
                    if health["state"]["policy"]["version"] != "0":
                        break
                time.sleep(.1)
            assert health and health["state"]["policy"]["enabled"] is True
            assert health["state"]["policy"]["version"] != "0"
            events = [
                {"hook_event_name": "SessionStart", "session_id": "isolated-synthetic-session", "prompt": "SYNTHETIC-OMITTED-PROMPT"},
                {"hook_event_name": "PreToolUse", "session_id": "isolated-synthetic-session", "turn_id": "t", "tool_use_id": "c", "tool_name": "Bash", "tool_input": {"command": "echo --password='synthetic-bridge-secret' && pwd"}},
                {"hook_event_name": "PostToolUse", "session_id": "isolated-synthetic-session", "turn_id": "t", "tool_use_id": "c", "tool_name": "Bash", "tool_response": {"exit_code": 7, "stdout": "SYNTHETIC-OMITTED-OUTPUT"}},
            ]
            bridge_pids = {}
            for event in events:
                with subprocess.Popen([str(binary), "aidr-hook", "--socket", str(sock), "--agent", "codex", "--event", event["hook_event_name"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as bridge:
                    bridge_pids[event["hook_event_name"]] = str(bridge.pid)
                    try:
                        output, _ = bridge.communicate(json.dumps(event).encode(), timeout=6)
                    except subprocess.TimeoutExpired:
                        bridge.kill()
                        bridge.communicate(timeout=3)
                        raise
                    assert bridge.returncode == 0 and json.loads(output) == {}
            deadline = time.monotonic()+15
            items = []
            while time.monotonic()<deadline:
                response = client.get("/api/v1/clients/one/aidr/hooks")
                assert response.status_code == 200
                items = response.json()["items"]
                if len(items)==3:
                    break
                time.sleep(.2)
            assert len(items)==3
            if sys.platform == "darwin":
                for item in items:
                    record = item["record"]
                    peer = record["bridge_process"]
                    assert peer["pid"] == bridge_pids[record["event"]["hook_event"]]
                    assert peer["pid"] != str(process.pid)
                    assert peer["role"] == "ipc_bridge"
                    assert int(peer["pidversion"]) > 0 and int(peer["start_us"]) > 0
                    assert record["event"]["process_relation"] == "unknown"
            runtime = client.get("/api/v1/clients/one/aidr/hook-policy").json()["runtime"]
            assert runtime["evidence_type"] == "receiver_self_report"
            assert len(runtime["items"]) == 1
            actual = runtime["items"][0]
            assert actual["receiver_instance"] == health["state"]["receiver_instance"]
            assert actual["stream_id"] == health["state"]["stream_id"]
            assert actual["control_mode"] == "audit" and actual["control_code"] == "aidr_hook_audit_only"
            assert actual["code"] == "aidr_hook_runtime_recent"
            assert not actual["matches_published_revision"]
            by_hook = {item["record"]["event"]["hook_event"]: item["record"]["event"] for item in items}
            assert by_hook["PostToolUse"]["behavior"]["exit_code"] == 7
            assert by_hook["PostToolUse"]["behavior"]["status"] == "reported_error"
            assert 'command' not in by_hook["PreToolUse"]["behavior"]["actions"][0]
            call = next(item for item in items if item['record']['event']['hook_event']=='PreToolUse')
            content = client.get('/api/v1/clients/one/aidr/content', params={'source':'hook','record_id':call['id']})
            assert content.status_code == 200, content.text
            command = next(item for item in content.json()['contents'] if item['kind']=='command_body')
            assert command['text'] == "echo --password='[REDACTED]' && pwd"
            assert all(item["record"]["user_scope"] == str(os.geteuid()) for item in items)
            for forbidden in ("synthetic-bridge-secret", "SYNTHETIC-OMITTED-PROMPT", "SYNTHETIC-OMITTED-OUTPUT"):
                assert forbidden not in json.dumps(items)
                for file in state.iterdir():
                    assert forbidden.encode() not in file.read_bytes()
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=6)
            assert process.returncode == 0 and not stderr
            summary = json.loads(stdout)
            assert summary["state"]["queued_records"] == 0
            assert summary["upload_code"] == ""
            assert not sock.exists()
            with sqlite3.connect(state / "hooks.db") as db:
                assert db.execute("SELECT count(*) FROM hook_receipts").fetchone()[0] == 3
            # Execute the actual exported scripts in a clean environment, with
            # the receiver stopped. These are synthetic hook payloads, not
            # claims that Claude/Codex executed a tool.
            connection = root / "bridge connection.json"
            gap = state / "bridge-gap.json"
            connection.write_text(json.dumps({"socket": str(sock), "active": True, "control_mode": "audit", "gap_file": str(gap)}))
            connection.chmod(0o600)
            marketplace = root / "marketplace with spaces"
            subprocess.run([str(binary), "aidr-plugin-package", "--source-dir", str(repository / "client/aidr-plugins"), "--destination", str(marketplace), "--runtime-bin", str(binary), "--connection-file", str(connection)], check=True, capture_output=True, timeout=6)
            for host in ("claude", "codex"):
                for event in ("PreToolUse", "UserPromptSubmit"):
                    script = marketplace / f"plugins/aidr-{host}/scripts/bridge.sh"
                    result = subprocess.run(["/bin/sh", str(script), event], input=json.dumps(events[1]).encode(), env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=6)
                    assert result.returncode == 0 and json.loads(result.stdout) == {}
                    assert b"aidr_hook_audit_gap aidr_hook_receiver_unavailable" in result.stderr
                    diagnostic = json.loads(gap.read_text())
                    assert diagnostic["agent"] == host and diagnostic["hook"] == event
                    assert "synthetic-bridge-secret" not in gap.read_text()
            connection.write_text(json.dumps({"socket": str(sock), "active": True, "control_mode": "plugin_pre_tool", "gap_file": str(gap)}))
            result = subprocess.run(["/bin/sh", str(script), "PreToolUse"], input=json.dumps(events[1]).encode(), env={"PATH": "/usr/bin:/bin"}, capture_output=True, timeout=6)
            assert result.returncode == 0
            assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
            assert b"aidr_hook_audit_gap" not in result.stderr
            assert len(client.get("/api/v1/clients/one/aidr/hooks").json()["items"]) == 3
            with sqlite3.connect(state / "hooks.db") as db:
                assert db.execute("SELECT count(*) FROM hook_receipts").fetchone()[0] == 3
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=6)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3)
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
            assert not thread.is_alive()
