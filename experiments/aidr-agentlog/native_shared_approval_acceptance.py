"""Two real Claude sessions, one shared MCP/shell, opposite exact approvals."""
import argparse
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
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from shared_mcp_acceptance import server as shared_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--mode", choices=("approval", "concurrent-audit"), default="approval")
    args = parser.parse_args()
    os.umask(0o077)
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-shared-approval-", dir="/private/tmp"))
    platform = root / "platform"
    private, public = root / "signing.pem", root / "public.x963"
    key = ec.generate_private_key(ec.SECP256R1())
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0)); port = port_socket.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    token = None
    children, handles, jobs, decisions = [], [], {}, {}
    audit = args.mode == "concurrent-audit"
    report = {"root": str(root), "status": "incomplete", "mode": args.mode, "native_sessions": 2, "checks": {}}
    http, shared = shared_server(root, barrier_size=20 if audit else 0)
    thread = threading.Thread(target=http.serve_forever); thread.start()
    def output(name):
        handle = (root / name).open("wb"); handles.append(handle); return handle
    def request(path, body=None, method=None, form=False):
        headers = {"Authorization": "Bearer " + token} if token else {}
        raw = None
        if body is not None:
            raw = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        with urllib.request.urlopen(urllib.request.Request(base + path, data=raw, headers=headers, method=method), timeout=5) as response:
            return json.load(response)
    try:
        backend = subprocess.Popen([sys.executable, str(repo / "experiments/aidr-agentlog/p1_server.py"),
            "--state-dir", str(platform), "--port", str(port)],
            env={**os.environ, "AIDR_POLICY_SIGNING_KEY_FILE": str(private)}, stdout=output("server.log"), stderr=subprocess.STDOUT)
        children.append(backend)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                if request("/_test/ready")["ready"]:
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("owned_platform_timeout")
        fixture = json.loads((platform / "fixture.json").read_text())
        cap = request("/api/auth/captcha")
        token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"],
            "captcha_id": cap["captcha_id"], "captcha_code": "aidr"}, form=True)["access_token"]
        api = f"/api/v1/clients/{fixture['client_id']}/aidr"
        request(api + "/hook-policy", {"expected_revision": "0", "lifetime_seconds": 600,
            "default_action": "allow" if audit else "deny", "rules": [] if audit else [{"id": "shared-probe-review", "agent": "claude",
            "tool": "mcp__shared__probe", "decision": "ask"}]}, method="PUT")
        for decision, slot in (("allow", 0), ("deny", 10)):
            ready = root / (decision + "-ready.json")
            command = [sys.executable, str(repo / "experiments/aidr-agentlog/native_claude_acceptance.py"),
                "--claude", args.claude, "--settings", args.settings, "--client-bin", args.client,
                "--server", base, "--client-id", fixture["client_id"], "--token-file", str(platform / "device-token"),
                "--public-key", str(public), "--ready-file", str(ready),
                "--mcp-url", f"http://127.0.0.1:{http.server_port}/mcp", "--probe-offset", str(slot)]
            if not audit:
                command += ["--expected-decision", decision]
            process = subprocess.Popen(command, stdout=output(decision + ".stdout"), stderr=output(decision + ".stderr"))
            children.append(process); jobs[decision] = (process, ready)
        print(json.dumps({"evidence_directory": str(root)}), flush=True)
        deadline = time.monotonic() + 155
        while time.monotonic() < deadline and any(p.poll() is None for p, _ in jobs.values()):
            instances = {json.loads(path.read_text())["receiver_instance"]: name for name, (_, path) in jobs.items() if path.exists()}
            for row in ([] if audit else request(api + "/hook-approvals")["items"]):
                if row["state"] != "pending":
                    continue
                decision = instances.get(row["scope"]["receiver_instance"])
                if decision is None or decision in decisions or row["scope"]["tool"] != "mcp__shared__probe":
                    raise RuntimeError("unexpected_shared_approval_scope")
                request(api + f"/hook-approvals/{row['id']}/decision", {"request_id": uuid.uuid4().hex,
                    "expected_revision": row["revision"], "decision": decision})
                decisions[decision] = row["id"]
            time.sleep(.1)
        if any(p.poll() is None for p, _ in jobs.values()):
            raise RuntimeError("native_shared_deadline")
        native_reports = []
        for decision in jobs:
            summary = json.loads((root / (decision + ".stdout")).read_text().splitlines()[-1])
            native = json.loads(Path(summary["report"]).read_text())
            if audit:
                report["checks"][decision] = native["status"] == "native_shared_mcp_audit_passed"
                native_reports.append({"report": summary["report"], "scope": "audit"})
                continue
            detail = request(api + "/hook-approvals/" + decisions[decision])
            report["checks"][decision] = (native["status"] == "native_shared_mcp_control_passed"
                and detail["approval"]["recorded_state"] == ("approved" if decision == "allow" else "denied")
                and detail["client_report"]["record"]["state"] == ("consumed" if decision == "allow" else "denied"))
            native_reports.append({"decision": decision, "report": summary["report"], "approval_id": decisions[decision]})
        report["native_reports"] = native_reports
        if audit:
            report["checks"]["20_inflight_native_requests"] = shared.peak_active == 20
            report["checks"]["20_exact_shell_probes"] = len(shared.records) == 20 and {r["slot"] for r in shared.records} == set(range(20))
            report["checks"]["two_native_sessions"] = len(shared.sessions) == 2
            assert all(report["checks"].values())
            report["status"] = "native_shared_20_inflight_passed"
            return
        report["checks"]["only_allowed_call_reached_shell"] = len(shared.records) == 1 and shared.records[0]["slot"] == 0
        report["checks"]["two_sessions_share_one_shell"] = len(shared.sessions) == 2 and shared.records[0]["shell_pid"] == shared.shell.pid
        report["checks"]["two_distinct_approvals"] = len(set(decisions.values())) == 2
        assert all(report["checks"].values())
        report["status"] = "native_shared_approval_isolation_passed"
    except Exception as error:
        report["error_type"] = type(error).__name__
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        http.shutdown(); http.server_close(); thread.join(timeout=5); shared.close()
        report["owned_processes_reclaimed"] = all(p.poll() is not None for p in children) and not thread.is_alive() and shared.shell.poll() is not None
        for handle in handles:
            handle.close()
        (root / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"report": str(root / "report.json"), "status": report["status"]}))


if __name__ == "__main__":
    main()
