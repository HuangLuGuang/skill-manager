#!/usr/bin/env python3
"""Real Claude/Codex allow/deny probes against an owned disposable platform.

Run with the backend Python environment for cryptography. No production state,
signing key, policy or user session is reused. Private test artifacts are retained.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def run(args):
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-native-approval-", dir="/private/tmp"))
    platform = root / "platform"
    platform.mkdir(mode=0o700)
    key = ec.generate_private_key(ec.SECP256R1())
    private, public = root / "signing.pem", root / "public.x963"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = probe = None
    report = {"root": str(root), "scope": f"real_{args.agent}_signed_approval", "runs": [], "status": "incomplete"}
    token = None

    def request(path, body=None, method=None, form=False):
        headers = {"Authorization": "Bearer " + token} if token else {}
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=10) as response:
            return json.load(response)

    try:
        with (root / "server.log").open("wb") as log:
            server = subprocess.Popen([sys.executable, str(repo / "experiments/aidr-agentlog/p1_server.py"),
                "--state-dir", str(platform), "--port", str(port)], cwd=repo,
                env={**os.environ, "AIDR_POLICY_SIGNING_KEY_FILE": str(private)}, stdout=log, stderr=log)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("owned_platform_start_failed")
            try:
                if request("/_test/ready")["ready"]:
                    break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError("owned_platform_not_ready")
        fixture = json.loads((platform / "fixture.json").read_text())
        captcha = request("/api/auth/captcha")
        token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"],
            "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"}, form=True)["access_token"]
        api = f"/api/v1/clients/{fixture['client_id']}/aidr"
        request(api + "/hook-policy", {"expected_revision": "0", "lifetime_seconds": 3600,
            "default_action": "deny", "rules": [{"id": "controlled-review", "agent": args.agent, "tool": "Bash", "decision": "ask"}]}, method="PUT")
        seen = set()
        for decision in ("deny", "allow"):
            stdout_path = root / (decision + ".json")
            with stdout_path.open("wb") as out, (root / (decision + ".stderr")).open("wb") as err:
                script="native_claude_acceptance.py" if args.agent=="claude" else "native_plugin_acceptance.py"
                host_args=["--claude",args.claude,"--settings",args.settings] if args.agent=="claude" else ["--codex",args.codex,"--model",args.model]
                probe = subprocess.Popen([sys.executable, str(repo / "experiments/aidr-agentlog" / script), *host_args, "--server", base,
                    "--client-id", fixture["client_id"], "--token-file", str(platform / "device-token"),
                    "--public-key", str(public), "--expected-decision", decision], stdout=out, stderr=err)
            deadline = time.monotonic() + 155
            approved = None
            while time.monotonic() < deadline and probe.poll() is None:
                pending = [row for row in request(api + "/hook-approvals")["items"] if row["id"] not in seen and row["state"] == "pending"]
                if pending:
                    if len(pending) != 1 or approved is not None:
                        raise RuntimeError("unexpected_native_approval_count")
                    row = pending[0]
                    seen.add(row["id"])
                    detail = request(api + "/hook-approvals/" + row["id"])
                    evidence = detail["evidence"]["event"]
                    commands = [a.get("command") for a in (evidence.get("behavior") or {}).get("actions", [])]
                    if len(commands) != 1 or not commands[0].startswith(f"/usr/bin/touch /private/tmp/aidr-p3-native-{args.agent}-") or not commands[0].endswith("/work/approval-probe"):
                        raise RuntimeError("unexpected_approval_command")
                    request(api + f"/hook-approvals/{row['id']}/decision", {"request_id": uuid.uuid4().hex,
                        "expected_revision": row["revision"], "decision": decision})
                    approved = row["id"]
                time.sleep(.2)
            if probe.poll() is None:
                raise RuntimeError("native_probe_deadline")
            result = json.loads(stdout_path.read_text())
            native_report = json.loads(Path(result["report"]).read_text())
            detail = request(api + "/hook-approvals/" + approved) if approved else {}
            receipt = (detail.get("client_report") or {}).get("record", {})
            checks = {"native_probe": native_report["status"] == "native_control_probe_passed",
                      "platform_decision": detail.get("approval", {}).get("recorded_state") == ("approved" if decision == "allow" else "denied"),
                      "client_terminal": receipt.get("state") == ("consumed" if decision == "allow" else "denied")}
            report["runs"].append({"decision": decision, "native_report": result["report"], "approval_id": approved, "checks": checks})
            if not all(checks.values()):
                raise RuntimeError("native_control_verification_failed")
        report["status"] = f"native_{args.agent}_approval_passed"
    except Exception as exc:
        report.update(status="incomplete", error_type=type(exc).__name__)
    finally:
        for process in (probe, server):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=35 if process is probe else 15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        report["owned_server_exit"] = server.poll() if server is not None else None
        report["probe_exit"] = probe.poll() if probe is not None else None
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root / "report.json"), "status": report["status"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", choices=("claude","codex"), default="claude")
    parser.add_argument("--claude")
    parser.add_argument("--settings")
    parser.add_argument("--codex")
    parser.add_argument("--model")
    args=parser.parse_args()
    if (args.agent=="claude" and not (args.claude and args.settings)) or (args.agent=="codex" and not (args.codex and args.model)):
        parser.error("selected host binary and existing model configuration are required")
    run(args)
