"""Owned IPC peers plus ES evidence, optionally with a real Claude session.

Run with sudo and an explicitly built --client binary. The temporary sensor uses
an empty file-rule set and never installs a service. Synthetic mode has no model
calls and a 90-second sensor limit; --claude/--settings use one isolated native
session and a 240-second sensor limit. Existing user sessions are untouched.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--claude", help="Run a real isolated Claude task instead of synthetic hooks")
    parser.add_argument("--settings", help="Existing Claude settings; only provider env is copied privately")
    args = parser.parse_args()
    if bool(args.claude) != bool(args.settings):
        parser.error("--claude and --settings must be supplied together")
    if os.geteuid() != 0 or sys.platform != "darwin":
        raise SystemExit("Requires a macOS root test process")
    os.umask(0o077)
    repo = Path(__file__).resolve().parents[2]
    binary = Path(args.client).resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-native-bridge-", dir="/private/tmp"))
    platform, sensor_state = root/"platform", root/"sensor"
    sensor_state.mkdir()
    key = ec.generate_private_key(ec.SECP256R1())
    public = root/"public.x963"
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = receiver = sensor = reader = native_runner = None
    token = device_token = None
    events, lock = [], threading.Condition()
    collection = {"records": 0, "over_budget": 0, "invalid_records": 0, "health_gaps": 0}
    report = {"scope": "real_ES_and_IPC_bridge_with_synthetic_hooks", "model_calls": 0,
              "status": "incomplete", "root": str(root), "checks": []}
    print(json.dumps({"evidence_directory": str(root)}), flush=True)

    def request(path, body=None, *, form=False, device=False):
        credential = device_token if device else token
        headers = {"Authorization": "Bearer " + credential} if credential else {}
        raw = None
        if body is not None:
            raw = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        with urllib.request.urlopen(urllib.request.Request(base+path, data=raw, headers=headers), timeout=5) as response:
            return json.load(response)

    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def wait(predicate, seconds=12):
        until = time.monotonic()+seconds
        with lock:
            while time.monotonic() < until:
                found = predicate(events)
                if found:
                    return found
                if sensor.poll() is not None:
                    raise RuntimeError("owned_ES_sensor_exited")
                lock.wait(.1)
        raise RuntimeError("owned_ES_evidence_timeout")

    def collect():
        for line in sensor.stdout:
            try:
                value = json.loads(line)
            except ValueError:
                with lock:
                    collection["invalid_records"] += 1
                continue
            with lock:
                collection["records"] += 1
                if value.get("kind") == "health":
                    collection["health_gaps"] = max(collection["health_gaps"], int(value.get("gaps", "0")))
                # The native sensor only emits known catalog process records.
                # Retain bounded metadata for this isolated experiment.
                if len(events) >= 512:
                    collection["over_budget"] += 1
                    continue
                events.append(value)
                lock.notify_all()

    try:
        with (root/"server.log").open("wb") as log:
            server = subprocess.Popen([sys.executable, str(repo/"experiments/aidr-agentlog/p1_server.py"), "--state-dir", str(platform), "--port", str(port)], stdout=log, stderr=log)
        until = time.monotonic()+25
        while time.monotonic() < until:
            try:
                captcha = request("/api/auth/captcha")
                break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("owned_platform_exited")
                time.sleep(.2)
        else:
            raise RuntimeError("owned_platform_not_ready")
        fixture = json.loads((platform/"fixture.json").read_text())
        token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"], "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"}, form=True)["access_token"]
        device_token = (platform/"device-token").read_text().strip()
        api = f"/api/v1/clients/{fixture['client_id']}/aidr"
        with (root/"sensor.stderr").open("w") as err:
            sensor = subprocess.Popen([str(repo/"client/macos-enforcer/build/aidr-enforcer"), str(public), fixture["client_id"], str(sensor_state), "240" if args.claude else "90"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True)
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        wait(lambda rows: any(r["kind"] == "health" for r in rows))
        now = int(time.time())
        policy = {"schema": 1, "device": fixture["client_id"], "revision": "1", "issued_at": str(now), "expires_at": str(now+300),
            "unknown_actor_action": "allow", "expired_action": "allow", "agent_executables": [str(Path(args.claude).resolve()) if args.claude else str(binary)], "rules": []}
        raw = json.dumps(policy, separators=(",", ":"), sort_keys=True).encode()
        envelope = {"payload": base64.b64encode(raw).decode(), "signature": base64.b64encode(key.sign(raw, ec.ECDSA(hashes.SHA256()))).decode()}
        sensor.stdin.write(json.dumps({"type": "policy", "envelope": envelope})+"\n")
        sensor.stdin.flush()
        wait(lambda rows: any(r["kind"] == "policy" and r["revision"] == "1" for r in rows))
        if args.claude:
            report["scope"] = "real_Claude_log_hook_ES_three_sources"
            report.pop("model_calls", None)
            command = [sys.executable, str(repo/"experiments/aidr-agentlog/native_claude_acceptance.py"), "--client-bin", str(binary),
                "--claude", args.claude, "--settings", args.settings, "--server", base, "--client-id", fixture["client_id"],
                "--token-file", str(platform/"device-token"), "--platform-fixture", str(platform/"fixture.json")]
            native_runner = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                native_output, _ = native_runner.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                native_runner.terminate()
                native_runner.communicate(timeout=20)
                raise RuntimeError("native_Claude_task_timeout")
            summary = json.loads(native_output.strip().splitlines()[-1])
            report["native_report"] = summary["report"]
            native_report = json.loads(Path(summary["report"]).read_text())
            assert native_report["status"] == "native_audit_smoke_passed"
            # The child verifies its own API evidence by logging into this test
            # account. Respect the platform's single-session login semantics.
            captcha = request("/api/auth/captcha")
            token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"],
                "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"}, form=True)["access_token"]
            items = request(api+"/hooks")["items"]
            tool_records = [item["record"] for item in items if item["record"]["event"]["kind"].startswith("tool.")]
            assert len(tool_records) == 4
            upload_rows = {}
            for record in tool_records:
                peer = record["bridge_process"]
                native = wait(lambda rows: next((r for r in rows if r["kind"] == "process" and r["transition"] == "exec"
                    and r["boot_id"] == peer["boot_id"] and all(r["process"][k] == peer[k] for k in ("pid", "pidversion", "start_us"))), None))
                exited = wait(lambda rows: next((r for r in rows if r["kind"] == "process" and r["transition"] == "exit" and r["process"] == native["process"]), None))
                assert native["relation"] == "inherited" and native.get("root")
                for value in (native, exited):
                    upload_rows[value["sequence"]] = value
            request(api+"/enforcement/records", {"records": list(upload_rows.values())}, device=True)
            session = tool_records[0]["event"]["session_id"]
            profile = Path(native_report["root"])/"profile"
            logs = list(profile.rglob(session+".jsonl"))
            assert len(logs) == 1
            empty = root/"empty-codex"
            empty.mkdir()
            sync_command = [str(binary), "aidr-sync", "--state-dir", str(root/"logs"), "--server", base, "--client-id", fixture["client_id"],
                "--claude-root", str(logs[0].parent), "--claude-file", str(logs[0]), "--codex-root", str(empty),
                "--token-env", "AIDR_BRIDGE_TEST_TOKEN", "--duration", "6s"]
            for _ in range(2):
                synced = subprocess.run(sync_command, env={**os.environ, "AIDR_BRIDGE_TEST_TOKEN": device_token}, capture_output=True, timeout=15)
                assert synced.returncode == 0
            operations = request(api+"/operations?session="+urllib.parse.quote(session, safe=""))["items"]
            assert len(operations) == 2
            for operation in operations:
                link = operation["hook_evidence"]
                assert link["relation"] == "inferred" and operation["process_relation"] == "unknown"
                assert len(link["items"]) == 2
                assert all(h["bridge_evidence"]["relation"] == "matched" and len(h["bridge_evidence"]["items"]) == 2 for h in link["items"])
                report["checks"].append({"call_id": operation["call"]["native_call_id"], "hook_count": len(link["items"]),
                    "bridge_evidence": [h["bridge_evidence"] for h in link["items"]], "tool_process_relation": "unknown"})
            report.update(status="native_Claude_three_source_evidence_passed", native_sessions=1, session_id=session,
                operation_count=2, tool_hooks=4, matched_os_records=len(upload_rows), log_mode="explicit_owned_file")
            return
        env = {**os.environ, "AIDR_BRIDGE_TEST_TOKEN": device_token}
        with (root/"receiver.stdout").open("wb") as out, (root/"receiver.stderr").open("wb") as err:
            receiver = subprocess.Popen([str(binary), "aidr-hook-serve", "--state-dir", str(root/"hooks"), "--socket", str(root/"h.sock"), "--server", base,
                "--client-id", fixture["client_id"], "--token-env", "AIDR_BRIDGE_TEST_TOKEN", "--codex-host-bin", "/usr/bin/false", "--claude-host-bin", "/usr/bin/false"], env=env, stdout=out, stderr=err)
        until = time.monotonic()+15
        while not (root/"h.sock").exists() and time.monotonic() < until:
            if receiver.poll() is not None:
                raise RuntimeError("owned_receiver_exited")
            time.sleep(.1)
        for index in range(3):
            hook = {"hook_event_name": "PreToolUse", "session_id": "synthetic-native-bridge", "turn_id": f"t-{index}",
                "tool_use_id": "shared-call", "tool_name": "Bash", "tool_input": {"command": "/usr/bin/true"}}
            # This only sends a hook; it does not execute the requested command.
            with subprocess.Popen([str(binary), "aidr-hook", "--socket", str(root/"h.sock"), "--agent", "codex", "--event", "PreToolUse"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as bridge:
                try:
                    output, _ = bridge.communicate(json.dumps(hook).encode(), timeout=6)
                except subprocess.TimeoutExpired:
                    bridge.kill(); bridge.communicate(timeout=3)
                    raise
                assert bridge.returncode == 0 and json.loads(output) == {}
                pid = str(bridge.pid)
            native = wait(lambda rows: next((r for r in rows if r["kind"] == "process" and r["transition"] == "exec" and r["process"]["pid"] == pid), None))
            exited = wait(lambda rows: next((r for r in rows if r["kind"] == "process" and r["transition"] == "exit" and r["process"] == native["process"]), None))
            until = time.monotonic()+15
            while time.monotonic() < until:
                items = request(api+"/hooks")["items"]
                record = next((r["record"] for r in items if r["record"]["event"].get("turn_id") == f"t-{index}"), None)
                if record:
                    break
                time.sleep(.2)
            else:
                raise RuntimeError("owned_hook_upload_timeout")
            peer = record["bridge_process"]
            assert peer["boot_id"] == native["boot_id"]
            assert all(peer[k] == native["process"][k] for k in ("pid", "pidversion", "start_us"))
            assert record["event"]["process_relation"] == "unknown"
            request(api+"/enforcement/records", {"records": [native, exited]}, device=True)
            report["checks"].append({"turn": f"t-{index}", "bridge": peer, "monitor_id": native["monitor_id"],
                "exec_sequence": native["sequence"], "exit_sequence": exited["sequence"], "event_id": record["event_id"], "tool_process_relation": "unknown"})
        with lock:
            assert not any(r["kind"] == "health" and int(r.get("gaps", "0")) for r in events)
        report["status"] = "native_bridge_ES_identity_passed"
    finally:
        stop(native_runner); stop(receiver); stop(sensor); stop(server)
        if reader:
            reader.join(timeout=5)
        report["owned_processes_reclaimed"] = all(p is None or p.poll() is not None for p in (native_runner, receiver, sensor, server))
        report["reader_reclaimed"] = reader is None or not reader.is_alive()
        report["sensor_collection"] = dict(collection)
        coverage_ok = not any(collection[k] for k in ("over_budget", "invalid_records", "health_gaps"))
        if not coverage_ok:
            report["status"] = "incomplete"
            report["error_code"] = "aidr_acceptance_sensor_coverage_gap"
        report["socket_reclaimed"] = not (root/"h.sock").exists()
        (root/"report.json").write_text(json.dumps(report, indent=2))
        # Return only this owned experiment's artifacts to the invoking user,
        # after every privileged process is stopped. Private modes are retained.
        uid, gid = int(os.environ.get("SUDO_UID", "0")), int(os.environ.get("SUDO_GID", "0"))
        if uid:
            for directory, folders, files in os.walk(root, followlinks=False):
                for name in files + folders:
                    os.chown(Path(directory)/name, uid, gid, follow_symlinks=False)
            os.chown(root, uid, gid, follow_symlinks=False)
        assert report["owned_processes_reclaimed"] and report["reader_reclaimed"] and report["socket_reclaimed"]
        assert coverage_ok, "aidr_acceptance_sensor_coverage_gap"
        print(json.dumps({"report": str(root/"report.json"), "status": report["status"]}))


if __name__ == "__main__":
    main()
