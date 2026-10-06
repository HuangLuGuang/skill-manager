"""Measure shipped hook bridge processes with controlled input, never run tools.

Includes shell/client startup, IPC, durable admission and cached signed policy.
Excludes host dispatch/model time and human approval. Uses an owned platform.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import platform as system_platform
import resource
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def run(samples, client_bin=None, burst_size=0, capacity=10000):
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-precheck-", dir="/private/tmp"))
    state, platform = root/"state", root/"platform"
    platform.mkdir(mode=0o700)
    binary = Path(client_bin).resolve() if client_bin else root/"client"
    if client_bin:
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("acceptance_client_binary_unavailable")
    else:
        subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"], cwd=repo/"scanner", check=True, capture_output=True, timeout=120)
    key = ec.generate_private_key(ec.SECP256R1())
    private, public = root/"key.pem", root/"public.x963"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    token = None
    server = receiver = None
    report = {"scope": "shipped_bridge_process_with_synthetic_input", "samples_per_case": samples,
              "machine": system_platform.platform(), "cases": [], "status": "incomplete",
              "client_binary_source": "provided_package" if client_bin else "source_build",
              "pending_capacity": capacity}

    def request(path, body=None, method=None, form=False):
        headers = {"Authorization": "Bearer "+token} if token else {}
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        with urllib.request.urlopen(urllib.request.Request(base+path, data=data, headers=headers, method=method), timeout=5) as response:
            return json.load(response)

    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def health():
        p = subprocess.run([str(binary), "aidr-hook", "--socket", str(root/"h.sock"), "--health"], capture_output=True, timeout=5)
        return json.loads(p.stdout)["state"] if p.returncode == 0 else {}

    def frame(connection):
        def read(size):
            value = bytearray()
            while len(value) < size:
                part = connection.recv(size-len(value))
                if not part:
                    raise RuntimeError("acceptance_ipc_incomplete")
                value.extend(part)
            return value
        size = struct.unpack("!I", read(4))[0]
        if not 0 < size <= 65536:
            raise RuntimeError("acceptance_ipc_response_budget")
        return json.loads(read(size))

    def exchange(event):
        payload = json.dumps(event).encode()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(root/"h.sock"))
            connection.sendall(struct.pack("!I", len(payload))+payload)
            return frame(connection)

    def frozen():
        with sqlite3.connect((state/"hooks.db").as_uri()+"?mode=ro", uri=True) as database:
            return database.execute("SELECT digest,payload FROM hook_frozen").fetchall()

    try:
        with (root/"server.log").open("wb") as log:
            server = subprocess.Popen([sys.executable, str(repo/"experiments/aidr-agentlog/p1_server.py"), "--state-dir", str(platform), "--port", str(port)],
                env={**os.environ, "AIDR_POLICY_SIGNING_KEY_FILE": str(private)}, stdout=log, stderr=log)
        deadline = time.monotonic()+25
        while time.monotonic()<deadline:
            try:
                if request("/_test/ready")["ready"]:
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("owned_platform_not_ready")
        fixture = json.loads((platform/"fixture.json").read_text())
        captcha = request("/api/auth/captcha")
        token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"], "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"}, form=True)["access_token"]
        api = f"/api/v1/clients/{fixture['client_id']}/aidr"
        request(api+"/hook-policy", {"expected_revision": "0", "lifetime_seconds": 3600, "default_action": "allow", "rules": []}, method="PUT")
        env = {**os.environ, "AIDR_PRECHECK_TOKEN": (platform/"device-token").read_text().strip()}
        with (root/"receiver.stdout").open("wb") as out, (root/"receiver.stderr").open("wb") as err:
            receiver = subprocess.Popen([str(binary), "aidr-hook-serve", "--state-dir", str(state), "--socket", str(root/"h.sock"), "--server", base,
                "--capacity", str(capacity),
                "--client-id", fixture["client_id"], "--token-env", "AIDR_PRECHECK_TOKEN", "--public-key", str(public),
                "--codex-host-bin", "/usr/bin/false", "--claude-host-bin", "/usr/bin/false", "--codex-config-dir", str(root/"codex"), "--claude-config-dir", str(root/"claude")], env=env, stdout=out, stderr=err)
        bridge_env = {**os.environ, "AIDR_CLIENT_BIN": str(binary), "AIDR_HOOK_SOCKET": str(root/"h.sock")}
        count = 0
        for phase, revision, expected in (("online_allow", "1", "allow"), ("online_deny", "2", "deny"), ("offline_cached_deny", "2", "deny")):
            if phase == "online_deny":
                request(api+"/hook-policy", {"expected_revision": "1", "lifetime_seconds": 3600, "default_action": "deny", "rules": []}, method="PUT")
            if phase == "offline_cached_deny":
                stop(server)
            deadline = time.monotonic()+40
            while time.monotonic()<deadline:
                actual = health()
                if actual.get("control_revision") == revision and actual.get("control_code") == "aidr_hook_policy_ready":
                    break
                if receiver.poll() is not None:
                    raise RuntimeError("owned_receiver_exited")
                time.sleep(.1)
            else:
                raise RuntimeError("signed_policy_not_applied")
            for agent in ("claude", "codex"):
                durations = []
                cpu_start = resource.getrusage(resource.RUSAGE_CHILDREN)
                for index in range(samples):
                    count += 1
                    event = {"hook_event_name": "PreToolUse", "session_id": "latency-controlled-"+agent, "turn_id": "turn-1",
                             "prompt_id": "prompt-1", "tool_use_id": f"call-{count}", "tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "/usr/bin/true"}}
                    started = time.perf_counter_ns()
                    result = subprocess.run(["/bin/sh", str(repo/f"client/aidr-plugins/aidr-{agent}/scripts/bridge.sh"), "PreToolUse"],
                        input=json.dumps(event).encode(), env=bridge_env, capture_output=True, timeout=5)
                    durations.append((time.perf_counter_ns()-started)/1e6)
                    answer = json.loads(result.stdout)
                    assert result.returncode == 0
                    if expected == "allow":
                        assert answer == {}
                    else:
                        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
                        assert answer["hookSpecificOutput"]["permissionDecisionReason"] == "aidr_hook_rule_deny"
                cpu_end = resource.getrusage(resource.RUSAGE_CHILDREN)
                values = sorted(durations)
                rss = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(receiver.pid)]).strip())
                report["cases"].append({"phase": phase, "agent": agent, "count": len(values), "p50_ms": values[math.ceil(len(values)*.5)-1],
                    "p95_ms": values[math.ceil(len(values)*.95)-1], "p99_ms": values[math.ceil(len(values)*.99)-1], "max_ms": max(values), "first_ms": durations[0],
                    "bridge_cpu_seconds": cpu_end.ru_utime+cpu_end.ru_stime-cpu_start.ru_utime-cpu_start.ru_stime, "receiver_rss_kib": rss, "samples_ms": durations})
        report["final_health"] = health()
        assert int(report["final_health"]["last_sequence"]) == count
        assert report["final_health"]["queued_records"] >= 2*samples
        report["total_prechecks"] = count
        if burst_size:
            # Synthetic IPC load, separate from the shell-process latency and
            # native-host evidence. Saturate the real 16-request admission cap.
            held = []
            try:
                for _ in range(16):
                    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    connection.settimeout(3)
                    connection.connect(str(root/"h.sock"))
                    held.append(connection)
                time.sleep(.2)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as overflow:
                    overflow.settimeout(3)
                    overflow.connect(str(root/"h.sock"))
                    busy = frame(overflow)
                assert busy["code"] == "aidr_hook_receiver_busy"
            finally:
                for connection in held:
                    connection.close()
            time.sleep(.2)
            before, original_frozen = health(), frozen()
            requests = [{"version": 1, "method": "SubmitEvent",
                "event_id": f"{time.time_ns()//1000000:016x}"+uuid.uuid4().hex[:16],
                "agent": "codex", "hook": "PreToolUse", "event": {
                    "hook_event_name": "PreToolUse", "session_id": "controlled-burst",
                    "turn_id": "turn-1", "tool_use_id": f"burst-{index}", "tool_name": "Bash",
                    "cwd": str(root), "tool_input": {"command": "/usr/bin/true"}}}
                for index in range(burst_size)]
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=8) as pool:
                responses = list(pool.map(exchange, requests))
            elapsed = time.monotonic()-started
            codes = Counter(answer["code"] for answer in responses)
            report["burst"] = {"scope": "synthetic_ipc_offline_input", "requests": burst_size,
                "workers": 8, "elapsed_seconds": elapsed, "codes": dict(codes),
                "busy_probe_code": busy["code"], "before_pending": before["queued_records"]}
            assert set(codes) <= {"aidr_hook_recorded", "aidr_hook_outbox_full", "aidr_hook_receiver_busy"}
            after = health()
            report["burst"]["after_pending"] = after["queued_records"]
            report["final_health"] = after
            recorded = codes["aidr_hook_recorded"]
            assert int(after["last_sequence"])-int(before["last_sequence"]) == recorded
            assert after["queued_records"] == before["queued_records"]+recorded <= capacity
            if before["queued_records"]+burst_size > capacity:
                assert codes["aidr_hook_outbox_full"] > 0
            replayed = 0
            for event, answer in zip(requests, responses):
                if answer["code"] == "aidr_hook_recorded" and replayed < 3:
                    replay = exchange(event)
                    assert replay["code"] == "aidr_hook_recorded"
                    assert replay["source_seq"] == answer["source_seq"]
                    replayed += 1
            final = health()
            assert final["last_sequence"] == after["last_sequence"]
            assert final["queued_records"] == after["queued_records"]
            assert frozen() == original_frozen
            report["burst"] = {"scope": "synthetic_ipc_offline_input", "requests": burst_size,
                "workers": 8, "elapsed_seconds": elapsed, "codes": dict(codes),
                "busy_probe_code": busy["code"], "before_pending": before["queued_records"],
                "after_pending": final["queued_records"], "replayed_without_new_sequence": replayed,
                "frozen_bytes_unchanged": True,
                "receiver_rss_kib_after": int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(receiver.pid)]).strip())}
            report["final_health"] = final
        report["status"] = "passed" if all(c["p95_ms"] <= 50 for c in report["cases"]) else "latency_gate_failed"
    finally:
        stop(receiver)
        stop(server)
        report["receiver_reclaimed"] = receiver is None or receiver.poll() is not None
        report["server_reclaimed"] = server is None or server.poll() is not None
        (root/"report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root/"report.json"), "status": report["status"], "cases": [{k:v for k,v in case.items() if k!="samples_ms"} for case in report["cases"]]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--client-bin", help="Existing package binary to measure instead of a source build")
    parser.add_argument("--burst-size", type=int, default=0, help="Optional bounded concurrent synthetic IPC input after offline cases")
    parser.add_argument("--capacity", type=int, default=10000, help="Pending-record capacity of this separate acceptance receiver")
    args = parser.parse_args()
    if not 100 <= args.samples <= 1000:
        parser.error("samples must be between 100 and 1000")
    if not 0 <= args.burst_size <= 1000 or not 2*args.samples <= args.capacity <= 100000:
        parser.error("burst-size must be 0..1000; capacity must be 2*samples..100000")
    run(args.samples, args.client_bin, args.burst_size, args.capacity)
