"""Owned native plugin profiles -> receiver -> real HTTP API, without model calls."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    parser.add_argument("--claude", required=True)
    parser.add_argument("--source-failure-probe", action="store_true", help="Test owned Codex config failure and temporarily missing Claude hook file, then restore")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-plugin-status-", dir="/private/tmp"))
    binary, platform = root/"client", root/"platform"
    subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"], cwd=repo/"scanner", check=True, capture_output=True, timeout=120)

    def cli(*parts):
        run = subprocess.run([str(binary), *map(str, parts)], capture_output=True, timeout=90)
        if run.returncode:
            raise RuntimeError("controlled_client_command_failed")
        return json.loads(run.stdout)

    cli("aidr-plugin-package", "--source-dir", repo/"client/aidr-plugins", "--destination", root/"market")
    for agent, host in (("codex", args.codex), ("claude", args.claude)):
        (root/agent).mkdir(mode=0o700)
        cli("aidr-plugin-install", "--agent", agent, "--host-bin", host, "--host-config-dir", root/agent, "--marketplace-path", root/"market")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    server = receiver = None
    token = None
    report = {"root": str(root), "runs": [], "model_calls": 0, "status": "incomplete"}
    backups = {}

    def request(path, form=None):
        headers = {"Authorization": "Bearer "+token} if token else {}
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        with urllib.request.urlopen(urllib.request.Request(base+path, data=data, headers=headers), timeout=5) as response:
            return json.load(response)

    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    try:
        with (root/"server.log").open("wb") as log:
            server = subprocess.Popen([str(repo/"backend/.venv/bin/python"), str(repo/"experiments/aidr-agentlog/p1_server.py"), "--state-dir", str(platform), "--port", str(port)], stdout=log, stderr=log)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            try:
                captcha = request("/api/auth/captcha")
                break
            except (OSError, ValueError):
                if server.poll() is not None:
                    raise RuntimeError("owned_server_exited")
                time.sleep(.2)
        else:
            raise RuntimeError("owned_server_not_ready")
        fixture = json.loads((platform/"fixture.json").read_text())
        token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"], "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"})["access_token"]
        env = {**os.environ, "AIDR_STATUS_TEST_TOKEN": (platform/"device-token").read_text().strip()}
        api = f"/api/v1/clients/{fixture['client_id']}/aidr/hook-policy"
        previous = {}
        phases = ["enabled", "disabled_after_restart"]
        if args.source_failure_probe:
            phases += ["source_unreadable", "source_restored"]
        baseline_before = None
        for phase in phases:
            if phase == "disabled_after_restart":
                codex_config = root/"codex/config.toml"
                raw = codex_config.read_text()
                assert raw.count("enabled = true") == 1
                codex_config.write_text(raw.replace("enabled = true", "enabled = false"))
                claude_config = root/"claude/settings.json"
                config = json.loads(claude_config.read_text())
                config["enabledPlugins"]["aidr-claude@aidr-local"] = False
                claude_config.write_text(json.dumps(config))
            if phase == "source_unreadable":
                codex_config = root/"codex/config.toml"
                backups[codex_config] = codex_config.read_bytes()
                codex_config.write_text("{ invalid native configuration\n")
                hook_files = list((root/"claude/plugins/cache/aidr-local/aidr-claude").glob("*/hooks/hooks.json"))
                if len(hook_files) != 1:
                    raise RuntimeError("owned_claude_hook_path_ambiguous")
                backups[hook_files[0]] = hook_files[0].read_bytes()
                hook_files[0].unlink()
                with sqlite3.connect((platform/"platform.db").resolve().as_uri()+"?mode=ro", uri=True) as db:
                    baseline_before = db.execute("SELECT scope_id,baseline FROM aidr_plugin_status ORDER BY scope_id").fetchall()
            if phase == "source_restored":
                for path, content in backups.items():
                    path.write_bytes(content)
            with (root/(phase+".stdout")).open("wb") as out, (root/(phase+".stderr")).open("wb") as err:
                receiver = subprocess.Popen([str(binary), "aidr-hook-serve", "--state-dir", str(root/"state"), "--socket", str(root/"h.sock"), "--server", base,
                    "--client-id", fixture["client_id"], "--token-env", "AIDR_STATUS_TEST_TOKEN", "--codex-host-bin", args.codex, "--codex-config-dir", str(root/"codex"),
                    "--claude-host-bin", args.claude, "--claude-config-dir", str(root/"claude")], env=env, stdout=out, stderr=err)
            deadline = time.monotonic()+40
            expected = phase == "enabled"
            while time.monotonic() < deadline:
                if receiver.poll() is not None:
                    raise RuntimeError("owned_receiver_exited")
                items = request(api)["plugins"]["items"]
                found = {i["report"]["status"]["agent"]: i for i in items}
                fresh = len(found) == 2 and all(not previous or int(i["report"]["report_sequence"]) > int(previous[a]["report"]["report_sequence"]) for a, i in found.items())
                if phase == "source_unreadable":
                    matches = len(found) == 2 and found["codex"]["report"]["status"]["source_code"] == "aidr_plugin_source_unreadable" and found["claude"]["report"]["status"]["files_code"] == "aidr_plugin_files_unreadable"
                else:
                    matches = all(i["report"]["status"]["enabled"] is expected and i["report"]["status"]["files_code"] == "aidr_plugin_files_observed" for i in found.values())
                if fresh and matches:
                    break
                time.sleep(.2)
            else:
                report["failed_phase"] = phase
                report["last_statuses"] = {a: {k: i["report"]["status"].get(k) for k in ("source_code", "enabled", "installed", "files_code")} for a, i in found.items()}
                raise RuntimeError("native_status_report_deadline")
            checks = []
            for agent, item in found.items():
                current = item["report"]
                assert not item["stale"] and current["status"]["hook_trust"] == "unknown"
                if previous:
                    before = previous[agent]["report"]
                    assert current["receiver_instance"] != before["receiver_instance"]
                    assert current["stream_id"] == before["stream_id"]
                    assert int(current["report_sequence"]) > int(before["report_sequence"])
                    assert item["change"]["fields"] == ["native_configuration"]
                if phase == "source_unreadable" and agent == "codex":
                    assert current["status"]["installed"] is None and current["status"]["enabled"] is None
                    assert not current["status"]["configuration_digest"]
                if phase == "source_unreadable" and agent == "claude":
                    assert current["status"]["installed"] is True and current["status"]["enabled"] is False
                checks.append({"agent": agent, "host_version": current["status"]["host_version"], "enabled": current["status"]["enabled"], "source_code": current["status"]["source_code"], "files_code": current["status"]["files_code"], "sequence": current["report_sequence"], "change": item["change"]["code"]})
            if phase == "source_unreadable":
                with sqlite3.connect((platform/"platform.db").resolve().as_uri()+"?mode=ro", uri=True) as db:
                    after = db.execute("SELECT scope_id,baseline FROM aidr_plugin_status ORDER BY scope_id").fetchall()
                keys = ("agent", "installed", "enabled", "configuration_digest", "files_digest", "files_code", "files_reported_at")
                def baseline_values(rows):
                    return {scope: {key: json.loads(raw).get(key) for key in keys} for scope, raw in rows}
                report["unreadable_baseline_preserved"] = baseline_values(after) == baseline_values(baseline_before)
                assert report["unreadable_baseline_preserved"]
            if phase == "source_restored":
                baselines = {json.loads(raw)["agent"]: json.loads(raw) for _, raw in baseline_before}
                report["restored_digests_match"] = all(all(item["report"]["status"][key] == baselines[agent][key]
                    for key in ("configuration_digest", "files_digest")) for agent, item in found.items())
                assert report["restored_digests_match"]
            previous = found
            stop(receiver)
            assert receiver.returncode == 0 and not (root/"h.sock").exists()
            report["runs"].append({"phase": phase, "checks": checks, "receiver_reclaimed": True})
        report["status"] = "native_plugin_status_passed"
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        for path, content in backups.items():
            path.write_bytes(content)
        report["owned_config_restored"] = all(path.read_bytes() == content for path, content in backups.items())
        stop(receiver)
        stop(server)
        report["receiver_reclaimed"] = receiver is None or receiver.poll() is not None
        report["server_reclaimed"] = server is None or server.poll() is not None
        (root/"report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root/"report.json"), "status": report["status"]}))


if __name__ == "__main__":
    main()
