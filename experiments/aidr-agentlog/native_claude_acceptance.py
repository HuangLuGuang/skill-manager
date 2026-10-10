#!/usr/bin/env python3
"""Bounded real Claude audit test; fresh profile, workspace and receiver state.

Provider environment is read privately from existing settings. No user hooks,
plugins, MCP configuration or sessions are copied. Reports contain only IDs,
event counts and explicit result metadata, never provider secrets or raw bodies.
"""
import argparse
import json
import os
import re
from pathlib import Path
import signal
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid


def auto_permission_command(work):
    """Exercise native classification with an owned, harmless script and rule."""
    marker = work / "approval-probe"
    script = work / "aidr-classifier-probe.sh"
    script.write_text("#!/bin/sh\nexec /usr/bin/touch " + shlex.quote(str(marker)) + "\n")
    script.chmod(0o600)
    command = "/bin/sh " + shlex.quote(str(script))
    settings = {"autoMode": {"hard_deny": ["$defaults",
        "AIDR Canary Denial: Always block the exact shell command " + command +
        ". This owned test script only creates a synthetic marker. Block it even when explicitly requested; "
        "the test is observing the native classifier's refusal, not granting an exception."]}}
    return command, settings


def subagent_result_evidence(row):
    value = row.get("tool_use_result")
    if not isinstance(value, dict) or "agentId" not in value:
        return None
    blocks = row.get("message", {}).get("content", [])
    results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
    if len(results) != 1:
        return None
    result = results[0]
    return {"call_id": result.get("tool_use_id"), "agent_id": value.get("agentId"),
        "status": value.get("status"), "agent_type": value.get("agentType"),
        "tool_count": value.get("totalToolUseCount"), "is_error": result.get("is_error"),
        "expected_marker": any(isinstance(b, dict) and b.get("type") == "text"
            and b.get("text", "").strip() == "AIDR-CHILD-DONE" for b in value.get("content", []))}


def subagent_result_matches(calls, results, completions):
    if len(calls) != 1 or len(results) != 1 or len(completions) != 1:
        return False
    c = completions[0]
    return (calls[0]["id"] == results[0]["id"] == c["call_id"] and c["status"] == "completed"
        and bool(c["agent_id"]) and c["agent_type"] == "aidr-probe" and c["tool_count"] == 0
        and c["expected_marker"] and c["is_error"] is not True)


def receiver_evidence(root):
    """Keep queue evidence even when a failed receiver emitted no summary."""
    evidence = {}
    try:
        summary_path = root / "receiver.json"
        if summary_path.stat().st_size > 65536:
            raise ValueError("receiver_summary_oversized")
        summary = json.loads(summary_path.read_text())
        if not isinstance(summary, dict):
            raise ValueError("receiver_summary_invalid")
        evidence["receiver_diagnostics"] = {
            key: value if isinstance(value, str) and re.fullmatch(r"(?:aidr_[a-z0-9_]{1,100})?", value) else "unknown"
            for key in ("policy_code", "upload_code", "control_code", "plugin_code")
            for value in [summary.get(key)]}
    except (OSError, ValueError):
        evidence["receiver_diagnostics_code"] = "acceptance_receiver_summary_unavailable"
    database = root / "state/hooks.db"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        evidence["acked_hooks"] = db.execute("SELECT count(*) FROM hook_receipts").fetchone()[0]
        evidence["pending_hooks"] = db.execute("SELECT count(*) FROM hook_events").fetchone()[0]
        evidence["received_hooks"] = evidence["acked_hooks"] + evidence["pending_hooks"]
        evidence["terminal_reports_acked"] = db.execute("SELECT count(*) FROM hook_attempt_reports WHERE acked=1").fetchone()[0]
    return evidence


def verify_platform(server, fixture_path, report, *, include_logs=False):
    """Read back real API evidence; authentication and bodies stay out of reports."""
    if urllib.parse.urlsplit(server).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("acceptance_server_must_be_loopback")
    fixture = json.loads(Path(fixture_path).read_text())
    token = None

    def request(path, data=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        with urllib.request.urlopen(urllib.request.Request(server + path, data=body, headers=headers), timeout=10) as response:
            return json.load(response)

    captcha = request("/api/auth/captcha")
    token = request("/api/auth/token", {"username": fixture["username"], "password": fixture["password"],
        "captcha_id": captcha["captcha_id"], "captcha_code": "aidr"})["access_token"]
    stream = report["final_health"]["stream_id"]
    client = report["final_health"]["client_id"]
    events, after = [], 0
    for _ in range(100):
        page = request(f"/api/v1/clients/{urllib.parse.quote(client, safe='')}/aidr/hooks?after={after}&limit=100")
        items = page["items"]
        events.extend(i["record"]["event"] for i in items if i["stream_id"] == stream)
        if not page["has_more"]:
            break
        next_after = int(page["next_after"])
        if next_after <= after:
            raise RuntimeError("nonprogressing_api_cursor")
        after = next_after
    else:
        raise RuntimeError("api_scan_budget_exhausted")
    pre = [e for e in events if e["hook_event"] == "PreToolUse"]
    if report.get("scope") == "native_claude_permission_audit":
        names = [e["hook_event"] for e in events]
        report["native_hook_counts"] = {name: names.count(name) for name in sorted(set(names))}
        denied = [e for e in events if e["hook_event"] == "PermissionDenied"]
        call_ids = [c["id"] for c in report.get("calls", [])]
        return {
            "one_native_permission_denied": len(denied) == 1,
            "same_owned_session": bool(report.get("session_id"))
                and {e["session_id"] for e in events} == {report["session_id"]},
            "exact_denied_call": len(call_ids) == len(pre) == len(denied) == 1
                and pre[0]["native_call_id"] == denied[0]["native_call_id"] == call_ids[0],
            "no_success_or_failure_post": not any(name in {"PostToolUse", "PostToolUseFailure"} for name in names),
            "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
        }
    if report.get("scope") == "native_claude_subagent_audit":
        names = [e["hook_event"] for e in events]
        starts = [e.get("native_agent_id") for e in events if e["hook_event"] == "SubagentStart"]
        stops = [e.get("native_agent_id") for e in events if e["hook_event"] == "SubagentStop"]
        report["native_hook_counts"] = {name: names.count(name) for name in sorted(set(names))}
        report["subagent_ids"] = {"starts": starts, "stops": stops}
        return {
            "matched_child_lifecycle": len(starts) == len(stops) == 1 and bool(starts[0]) and starts == stops,
            "child_matches_native_result": bool(starts) and starts == [c["agent_id"] for c in report.get("subagent_completions", [])],
            "same_owned_session": {e["session_id"] for e in events} == {report["session_id"]},
            "one_exact_agent_call": len(pre) == 1 and len(report["calls"]) == 1 and pre[0]["native_call_id"] == report["calls"][0]["id"],
            "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
        }
    if report.get("scope") == "native_claude_idle_notification_audit":
        names = [e["hook_event"] for e in events]
        report["native_hook_counts"] = {name: names.count(name) for name in sorted(set(names))}
        return {
            "native_notification_observed": "Notification" in names,
            "same_owned_session": {e["session_id"] for e in events} == {report["session_id"]},
            "no_tool_pre_events": not pre,
            "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
        }
    if report.get("scope") == "native_claude_task_completion_audit":
        names = [e["hook_event"] for e in events]
        report["native_hook_counts"] = {name: names.count(name) for name in sorted(set(names))}
        return {
            "native_task_completed": names.count("TaskCompleted") == 1,
            "same_owned_session": {e["session_id"] for e in events} == {report["session_id"]},
            "two_exact_tool_pre_events": len(pre) == 2 and {e["native_call_id"] for e in pre} == {c["id"] for c in report["calls"]},
            "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
        }
    if report.get("scope") == "native_claude_compaction_audit":
        names = [e["hook_event"] for e in events]
        report["native_hook_counts"] = {name: names.count(name) for name in sorted(set(names))}
        return {
            "native_compact_pair": names.count("PreCompact") == names.count("PostCompact") == 1,
            "same_owned_session": {e["session_id"] for e in events} == {report["session_id"]},
            "no_tool_events": not any(e["kind"].startswith("tool.") for e in events),
            "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
        }
    post = [e for e in events if e["hook_event"] == "PostToolUse"]
    failed = [e for e in events if e["hook_event"] == "PostToolUseFailure"]
    checks = {
        "eight_platform_events": len(events) == 8,
        "same_native_call_ids": {e["native_call_id"] for e in pre} == {c["id"] for c in report["calls"]} and len(pre) == 2,
        "failure_exit_7": len(failed) == 1 and failed[0]["behavior"].get("exit_code") == 7,
        "success_hook_exit_unknown": len(post) == 1 and post[0]["behavior"].get("exit_code") is None,
        "system_relation_unknown": bool(events) and all(e["process_relation"] == "unknown" for e in events),
    }
    if include_logs:
        sessions = {e["session_id"] for e in events}
        if len(sessions) != 1:
            raise RuntimeError("native_session_ambiguous")
        session = urllib.parse.quote(next(iter(sessions)), safe="")
        operations = request(f"/api/v1/clients/{urllib.parse.quote(client, safe='')}/aidr/operations?session={session}")
        rows = operations["items"]
        checks.update(
            two_log_operations=len(rows) == 2 and not operations["has_more"],
            exact_log_call_ids={r["call"]["native_call_id"] for r in rows} == {c["id"] for c in report["calls"]},
            two_hooks_per_operation=bool(rows) and all(len(r["hook_evidence"]["items"]) == 2 for r in rows),
            inferred_only=bool(rows) and all(r["hook_evidence"]["relation"] == "inferred" and r["process_relation"] == "unknown" for r in rows),
        )
    return checks


def run(args):
    idle_probe = getattr(args, "idle_notification_probe", False)
    compact_probe = getattr(args, "compact_probe", False)
    task_probe = getattr(args, "task_completion_probe", False)
    subagent_probe = getattr(args, "subagent_probe", False)
    auto_permission_probe = getattr(args, "auto_permission_probe", False)
    permission_probe = getattr(args, "native_permission_deny", False) or auto_permission_probe
    permission_host = getattr(args, "permission_host", False)
    if auto_permission_probe and permission_host:
        raise ValueError("auto_permission_probe_requires_native_classifier")
    if subagent_probe and (compact_probe or task_probe or idle_probe or permission_probe or args.expected_decision or args.public_key or args.mcp_url or not args.platform_fixture):
        raise ValueError("subagent_probe_requires_independent_audit_and_platform_verification")
    if idle_probe and (compact_probe or task_probe or permission_probe or args.expected_decision or args.public_key or args.mcp_url or not args.platform_fixture):
        raise ValueError("idle_probe_requires_independent_audit_and_platform_verification")
    if permission_host and not permission_probe:
        raise ValueError("permission_host_requires_native_permission_probe")
    if permission_probe and (args.expected_decision or args.public_key or args.mcp_url or args.platform_fixture):
        raise ValueError("native_permission_probe_requires_independent_audit_mode")
    if compact_probe and (permission_probe or args.expected_decision or args.public_key or args.mcp_url or not args.platform_fixture):
        raise ValueError("compact_probe_requires_audit_mode_and_platform_verification")
    if task_probe and (compact_probe or permission_probe or args.expected_decision or args.public_key or args.mcp_url or not args.platform_fixture):
        raise ValueError("task_probe_requires_independent_audit_and_platform_verification")
    mcp_url = getattr(args, "mcp_url", None)
    offset = getattr(args, "probe_offset", 0)
    if mcp_url and (urllib.parse.urlsplit(mcp_url).hostname != "127.0.0.1" or args.platform_fixture):
        raise ValueError("shared_probe_requires_loopback_and_independent_verification")
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-native-claude-", dir="/private/tmp"))
    home, work = root / "profile", root / "work"
    home.mkdir(mode=0o700)
    work.mkdir(mode=0o700)
    binary, sock = root / "client", root / "hook.sock"
    report = {"root": str(root), "scope": "native_claude_audit", "status": "incomplete"}
    receiver = native = None
    handles = []

    def output(name):
        fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        handle = os.fdopen(fd, "wb")
        handles.append(handle)
        return handle

    try:
        if getattr(args, "client_bin", None):
            binary = Path(args.client_bin).resolve(strict=True)
        else:
            subprocess.run(["go", "build", "-o", str(binary), "./cmd/agent-manager-client"],
                           cwd=repo / "scanner", check=True, capture_output=True, timeout=120)
        report["host_version"] = subprocess.check_output([args.claude, "--version"], timeout=10, text=True).strip()
        configured = json.loads(Path(args.settings).read_text()).get("env", {})
        keys = {"ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"}
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE", "ANTHROPIC", "AIDR_", "AGENT_MANAGER_AIDR"))
               and k not in {"ENV", "BASH_ENV", "ZDOTDIR"}}
        env.update({k: v for k, v in configured.items() if k in keys and isinstance(v, str)})
        if subagent_probe:
            model = configured.get("ANTHROPIC_MODEL")
            if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}", model):
                raise ValueError("subagent_probe_requires_explicit_configured_model")
            env.update(CLAUDE_CODE_SUBAGENT_MODEL=model, ANTHROPIC_DEFAULT_SONNET_MODEL=model)
            report.update(requested_subagent_model=model, requested_subagent_model_alias="sonnet")
        env.update(CLAUDE_CONFIG_DIR=str(home), AIDR_CLIENT_BIN=str(binary), AIDR_HOOK_SOCKET=str(sock),
                   HOME=str(home), SHELL="/bin/bash", ZDOTDIR=str(home),
                   DISABLE_AUTOUPDATER="1", CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        # Device authentication belongs to the receiver, never the model host.
        receiver_env = {k: v for k, v in env.items() if not k.startswith("ANTHROPIC")}
        receiver_env["AIDR_TEST_TOKEN"] = Path(args.token_file).read_text().strip()
        receiver_command = [str(binary), "aidr-hook-serve", "--state-dir", str(root / "state"),
            "--socket", str(sock), "--server", args.server, "--client-id", args.client_id,
            "--token-env", "AIDR_TEST_TOKEN"]
        if args.public_key:
            receiver_command += ["--public-key", args.public_key]
        receiver = subprocess.Popen(receiver_command, env=receiver_env,
            stdout=output("receiver.json"), stderr=output("receiver.stderr"))

        def health():
            p = subprocess.run([str(binary), "aidr-hook", "--socket", str(sock), "--health"],
                               capture_output=True, timeout=5)
            return json.loads(p.stdout)["state"] if p.returncode == 0 else None

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if receiver.poll() is not None:
                raise RuntimeError("receiver_start_failed")
            initial = health()
            if initial is not None and (not args.public_key or initial.get("control_code") == "aidr_hook_policy_ready"):
                report["initial_health"] = initial
                break
            time.sleep(.1)
        else:
            raise RuntimeError("receiver_readiness_timeout")
        if getattr(args, "ready_file", None):
            fd = os.open(args.ready_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as ready:
                json.dump({"receiver_instance": report["initial_health"]["receiver_instance"], "root": str(root)}, ready)
        prompt = ("Isolated AIDR acceptance: use Bash exactly twice, as separate calls. First run "
                  "/usr/bin/printf 'aidr-native-hook-check\\n'. Second run exit 7. "
                  "Do not read files or environment, modify files, retry commands or spawn agents. "
                  "Finally report the two observed outcomes.")
        marker = work / "approval-probe"
        probe_command = "/usr/bin/touch " + str(marker)
        auto_settings = None
        if auto_permission_probe:
            probe_command, auto_settings = auto_permission_command(work)
        allowed = ["Bash(/usr/bin/printf *)", "Bash(exit 7)"]
        mcp_config, builtins = '{"mcpServers":{}}', "Bash"
        if mcp_url:
            report["scope"] = "native_claude_shared_mcp_audit"
            report["expected_slots"] = [offset] if args.expected_decision else list(range(offset, offset + 10))
            prompt = ("Isolated acceptance: call mcp__shared__probe exactly once for each slot in "
                      + json.dumps(report["expected_slots"]) + ". Issue the independent calls concurrently if supported. "
                      "Use only this MCP tool. Do not retry, use shell tools, read files/environment or spawn agents. "
                      "Then briefly report whether each call returned its requested slot.")
            allowed, builtins = ["mcp__shared__probe"], ""
            mcp_config = json.dumps({"mcpServers": {"shared": {"type": "http", "url": mcp_url}}})
        if args.expected_decision:
            if not args.public_key:
                raise ValueError("control_probe_requires_public_key")
            if not mcp_url:
                prompt = ("Isolated AIDR approval test. Use Bash exactly once to run: " + probe_command +
                          ". Do not retry if denied. Do not use another tool, inspect files or environment, "
                          "or spawn agents. Report only the observed tool outcome.")
                allowed = ["Bash(" + probe_command + ")"]
        if permission_probe:
            report["scope"] = "native_claude_permission_audit"
            prompt = ("Isolated native permission acceptance. Request Bash exactly once with command: " + probe_command +
                      ". The host may deny permission; do not retry, change commands, use another tool, "
                      "inspect files/environment or spawn agents. Report only the tool outcome.")
            allowed = ["Bash(/usr/bin/true)"]
        host_flags = []
        if auto_permission_probe:
            host_flags = ["--permission-mode", "auto", "--settings", json.dumps(auto_settings)]
            report["requested_permission_mode"] = "auto"
            report["native_classifier_rule"] = "aidr_canary_denial"
            config = subprocess.run([args.claude, "--setting-sources", "", "--settings",
                json.dumps(auto_settings), "auto-mode", "config"], cwd=work, env=env,
                capture_output=True, timeout=15, check=True)
            effective = json.loads(config.stdout)
            rule = auto_settings["autoMode"]["hard_deny"][-1]
            report["native_classifier_rule_loaded"] = rule in effective.get("hard_deny", [])
            if not report["native_classifier_rule_loaded"]:
                raise RuntimeError("native_classifier_rule_not_loaded")
        if permission_host:
            mcp_config = json.dumps({"mcpServers": {"permission": {"command": sys.executable,
                "args": [str(repo / "experiments/aidr-agentlog/permission_host_fixture.py"), str(root / "permission-host.json")]}}})
            host_flags = ["--permission-prompt-tool", "mcp__permission__deny"]
        if compact_probe:
            report.update(scope="native_claude_compaction_audit", session_id=str(uuid.uuid4()))
            builtins, allowed = "", []
        if idle_probe:
            report.update(scope="native_claude_idle_notification_audit", session_id=str(uuid.uuid4()))
            builtins, allowed = "", []
            prompt = "Isolated lifecycle test. Reply only IDLE-PROBE. Do not use tools or access files."
        if task_probe:
            report.update(scope="native_claude_task_completion_audit", session_id=str(uuid.uuid4()))
            builtins, allowed = "TaskCreate,TaskUpdate", ["TaskCreate", "TaskUpdate"]
            prompt = ("Isolated AIDR lifecycle acceptance. Call TaskCreate exactly once with subject AIDR-TASK-PROBE "
                      "and description Synthetic task for lifecycle testing. Then call TaskUpdate exactly once "
                      "with the returned taskId and status completed. Use no other tools, do not read files "
                      "or environment, and do not spawn agents. Finally state whether the two calls succeeded.")
        if subagent_probe:
            report.update(scope="native_claude_subagent_audit", session_id=str(uuid.uuid4()))
            builtins, allowed = "Agent,Read", ["Agent(aidr-probe)"]
            host_flags += ["--agents", json.dumps({"aidr-probe": {
                "description": "Text-only synthetic lifecycle acceptance child",
                "prompt": "Reply exactly AIDR-CHILD-DONE. Do not call tools, access files or environment, or spawn agents.",
                "tools": ["Read"], "maxTurns": 1}})]
            prompt = ("Use the aidr-probe subagent exactly once, in the foreground. Its sole task is to reply "
                      "AIDR-CHILD-DONE. Set the Agent model parameter explicitly to sonnet, which this "
                      "isolated environment maps to the configured provider model. Reply "
                      "AIDR-CHILD-DONE without using tools or accessing files/environment. Wait for its result. "
                      "Do not call other tools, resume it or spawn another child. Report completion briefly.")
        command = [args.claude, "--print", "--verbose", "--output-format", "stream-json", *host_flags,
            "--setting-sources", "", "--strict-mcp-config", "--mcp-config", mcp_config,
            "--plugin-dir", str(repo / "client/aidr-plugins/aidr-claude"),
            "--tools", builtins]
        if allowed:
            command += ["--allowedTools", *allowed]
        command += ["--max-turns", "2" if compact_probe else "4"]
        if task_probe or subagent_probe:
            command += ["--session-id", report["session_id"]]
        if compact_probe:
            seeds = (
                "Isolated lifecycle acceptance. Reply in one short sentence that the synthetic marker COMPACT-PROBE is noted. Do not use tools or access files.",
                "Add the second synthetic marker COMPACT-SECOND to the notes. Reply in one short sentence only. Do not use tools or access files.",
            )
            report["seed_exits"] = []
            for index, seed in enumerate(seeds):
                flag = "--session-id" if index == 0 else "--resume"
                native = subprocess.Popen([*command, flag, report["session_id"], "--", seed],
                    cwd=work, env=env, stdout=output(f"native-seed-{index}.jsonl"), stderr=output(f"native-seed-{index}.stderr"))
                report["seed_exits"].append(native.wait(timeout=90))
                if report["seed_exits"][-1] != 0:
                    raise RuntimeError("native_compact_seed_failed")
            command += ["--resume", report["session_id"]]
            prompt = "/compact Preserve only the synthetic marker and that no tools were used."
        if idle_probe:
            native = subprocess.Popen([*command, "--input-format", "stream-json", "--session-id", report["session_id"]],
                cwd=work, env=env, stdin=subprocess.PIPE,
                stdout=output("native.jsonl"), stderr=output("native.stderr"))
            native.stdin.write((json.dumps({"type": "user", "session_id": report["session_id"],
                "parent_tool_use_id": None, "message": {"role": "user", "content": prompt}}) + "\n").encode())
            native.stdin.flush()
            deadline = time.monotonic() + 90
            completed_at = None
            while time.monotonic() < deadline and native.poll() is None:
                path = root / "native.jsonl"
                if path.stat().st_size > 1024 * 1024:
                    raise RuntimeError("native_output_budget_exceeded")
                for line in path.read_bytes().splitlines():
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if value.get("type") == "result" and value.get("is_error") is False and value.get("session_id") == report["session_id"]:
                        completed_at = time.monotonic()
                        break
                if completed_at is not None:
                    break
                time.sleep(.2)
            if completed_at is None:
                raise RuntimeError("native_idle_seed_incomplete")
            while native.poll() is None and time.monotonic() - completed_at < 75:
                if (root / "native.jsonl").stat().st_size > 1024 * 1024:
                    raise RuntimeError("native_output_budget_exceeded")
                time.sleep(.2)
            report["idle_seconds"] = round(time.monotonic() - completed_at, 3)
            report["alive_after_idle"] = native.poll() is None
            native.stdin.close()
        else:
            native = subprocess.Popen([*command, "--", prompt], cwd=work, env=env,
                stdout=output("native.jsonl"), stderr=output("native.stderr"))
        try:
            report["native_exit"] = native.wait(timeout=120)
        except subprocess.TimeoutExpired:
            report["native_exit"] = 124
            native.terminate()
            try:
                native.wait(timeout=10)
            except subprocess.TimeoutExpired:
                native.kill()
                native.wait(timeout=5)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = health()
            if state is not None:
                report["final_health"] = state
                receipts_ready = True
                if args.expected_decision:
                    with sqlite3.connect(root / "state/hooks.db") as db:
                        receipts_ready = db.execute("SELECT count(*) FROM hook_attempt_reports WHERE acked=1").fetchone()[0] == 1
                if state["queued_records"] == 0 and receipts_ready:
                    break
            time.sleep(.2)
        receiver.send_signal(signal.SIGTERM)
        receiver.wait(timeout=10)
        report["receiver_exit"] = receiver.returncode
        report.update(receiver_evidence(root))
        calls, results, terminal, completions = [], [], [], []
        for line in (root / "native.jsonl").read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if permission_probe and row.get("type") == "system" and row.get("subtype") == "init":
                report["session_id"] = row.get("session_id")
                report["native_permission_mode"] = row.get("permissionMode")
            if subagent_probe:
                evidence = subagent_result_evidence(row)
                if evidence is not None:
                    completions.append(evidence)
            if row.get("type") == "result":
                terminal.append({k: row.get(k) for k in ("subtype", "is_error", "num_turns")})
            message = row.get("message", {})
            for block in message.get("content", []) if isinstance(message, dict) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    calls.append({"id": block.get("id"), "name": block.get("name"),
                                  "expected_command": (block.get("input") or {}).get("command") in
                                  ((probe_command,) if args.expected_decision or permission_probe else ("/usr/bin/printf 'aidr-native-hook-check\\n'", "exit 7"))})
                    if subagent_probe:
                        calls[-1]["model_alias"] = (block.get("input") or {}).get("model")
                    if mcp_url:
                        calls[-1]["slot"] = (block.get("input") or {}).get("slot")
                    if task_probe:
                        value = block.get("input") or {}
                        calls[-1]["synthetic_subject"] = value.get("subject") == "AIDR-TASK-PROBE"
                        calls[-1]["completed_requested"] = value.get("status") == "completed"
                        ident = value.get("taskId")
                        calls[-1]["numeric_task_id"] = ident if isinstance(ident, str) and re.fullmatch(r"[0-9]{1,20}", ident) else None
                if block.get("type") == "tool_result":
                    results.append({"id": block.get("tool_use_id"), "is_error": block.get("is_error")})
        report.update(calls=calls, results=results, terminal=terminal)
        if subagent_probe:
            report["subagent_completions"] = completions
        report["checks"] = {
            "native_exited": report["native_exit"] == 0,
            "two_expected_calls": len(calls) == 2 and all(c["name"] == "Bash" and c["expected_command"] for c in calls),
            "matching_results": [c["id"] for c in calls] == [r["id"] for r in results] and len(results) == 2,
            "reported_success_then_error": [r["is_error"] for r in results] == [False, True],
            "eight_receipts": report["received_hooks"] == 8,
            "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
            "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
        }
        if args.platform_fixture:
            report["platform_checks"] = verify_platform(args.server, args.platform_fixture, report)
        report["status"] = "native_audit_smoke_passed" if all(report["checks"].values()) and all(report.get("platform_checks", {}).values()) else "native_audit_smoke_incomplete"
        if idle_probe:
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "no_tool_calls": not calls and not results,
                "one_successful_turn": len(terminal) == 1 and terminal[0].get("is_error") is False,
                "alive_for_idle_window": report["alive_after_idle"] and report["idle_seconds"] >= 75,
                "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_idle_notification_passed" if all(report["checks"].values()) and all(report.get("platform_checks", {}).values()) else "native_idle_notification_incomplete"
        if subagent_probe:
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "one_agent_call": len(calls) == 1 and calls[0]["name"] == "Agent",
                "explicit_supported_model_alias": len(calls) == 1 and calls[0].get("model_alias") == "sonnet",
                "matching_success_result": subagent_result_matches(calls, results, completions),
                "one_successful_turn": len(terminal) == 1 and terminal[0].get("is_error") is False,
                "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_subagent_passed" if all(report["checks"].values()) and all(report.get("platform_checks", {}).values()) else "native_subagent_incomplete"
        if compact_probe:
            report["checks"] = {
                "seed_exited": report["seed_exits"] == [0, 0],
                "native_exited": report["native_exit"] == 0,
                "no_tool_calls": not calls and not results,
                "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_compaction_passed" if all(report["checks"].values()) and all(report.get("platform_checks", {}).values()) else "native_compaction_incomplete"
        if task_probe:
            completed_tasks = []
            for path in (home / "tasks").glob("*/*.json"):
                if path.stat().st_size > 65536:
                    raise RuntimeError("native_task_record_oversized")
                value = json.loads(path.read_text())
                if value.get("subject") == "AIDR-TASK-PROBE" and value.get("status") == "completed":
                    completed_tasks.append(str(value.get("id")))
            report["completed_task_ids"] = completed_tasks
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "exact_task_calls": len(calls) == 2 and [c["name"] for c in calls] == ["TaskCreate", "TaskUpdate"]
                    and calls[0]["synthetic_subject"] and calls[1]["completed_requested"],
                "matching_success_results": len(results) == len(calls) == 2
                    and [c["id"] for c in calls] == [r["id"] for r in results] and all(not r["is_error"] for r in results),
                "completed_task_persisted": len(calls) == 2 and completed_tasks == [calls[1]["numeric_task_id"]],
                "outbox_drained": report.get("final_health", {}).get("queued_records") == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_task_completion_passed" if all(report["checks"].values()) and all(report.get("platform_checks", {}).values()) else "native_task_completion_incomplete"
        if mcp_url and not args.expected_decision:
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "ten_exact_probes": len(calls) == 10 and all(c["name"] == "mcp__shared__probe" for c in calls)
                    and sorted(c["slot"] for c in calls) == report["expected_slots"],
                "matching_results": len(results) == 10 and {c["id"] for c in calls} == {r["id"] for r in results},
                "no_reported_tool_errors": all(not r["is_error"] for r in results),
                "24_receipts": report["received_hooks"] == 24,
                "outbox_drained": report["final_health"]["queued_records"] == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_shared_mcp_audit_passed" if all(report["checks"].values()) else "native_shared_mcp_audit_incomplete"
        if permission_probe:
            report["marker_exists"] = marker.exists()
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "one_exact_probe": len(calls) == 1 and calls[0]["expected_command"] and calls[0]["name"] == "Bash",
                "matching_error_result": len(results) == len(calls) == 1 and results[0]["id"] == calls[0]["id"] and bool(results[0]["is_error"]),
                "marker_absent": not marker.exists(),
                "audit_mode": report["initial_health"].get("control_mode") == "audit"
                    and report["initial_health"].get("control_code") == "aidr_hook_audit_only",
                "outbox_drained": report["final_health"]["queued_records"] == 0,
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
            }
            report["status"] = "native_permission_probe_passed" if all(report["checks"].values()) else "native_permission_probe_incomplete"
            if auto_permission_probe:
                report["checks"]["native_auto_mode"] = report.get("native_permission_mode") == "auto"
                report["status"] = "native_permission_probe_passed" if all(report["checks"].values()) else "native_permission_probe_incomplete"
            if permission_host:
                host_report = root / "permission-host.json"
                report["permission_host"] = json.loads(host_report.read_text()) if host_report.exists() else {"calls": 0}
                report["checks"]["permission_host_called"] = report["permission_host"].get("calls") == 1 and report["permission_host"].get("requested_bash") is True
                report["status"] = "native_permission_probe_passed" if all(report["checks"].values()) else "native_permission_probe_incomplete"
        elif args.expected_decision and mcp_url:
            report["expected_decision"] = args.expected_decision
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "one_exact_probe": len(calls) == 1 and calls[0]["name"] == "mcp__shared__probe" and calls[0]["slot"] == offset,
                "matching_result": len(calls) == len(results) == 1 and calls[0]["id"] == results[0]["id"],
                "host_result_matches": len(results) == 1 and bool(results[0]["is_error"]) == (args.expected_decision == "deny"),
                "control_enabled": report["initial_health"].get("control_mode") == "plugin_pre_tool",
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
                "outbox_drained": report["final_health"]["queued_records"] == 0,
                "terminal_report_acked": report["terminal_reports_acked"] == 1,
            }
            report["status"] = "native_shared_mcp_control_passed" if all(report["checks"].values()) else "native_shared_mcp_control_incomplete"
        elif args.expected_decision:
            report["marker_exists"] = marker.exists()
            report["expected_decision"] = args.expected_decision
            report["checks"] = {
                "native_exited": report["native_exit"] == 0,
                "one_exact_probe": len(calls) == 1 and calls[0]["expected_command"] and calls[0]["name"] == "Bash",
                "matching_result": len(results) == 1 and len(calls) == 1 and results[0]["id"] == calls[0]["id"],
                "marker_matches_decision": marker.exists() == (args.expected_decision == "allow"),
                "host_result_matches": len(results) == 1 and results[0]["is_error"] == (args.expected_decision == "deny"),
                "control_enabled": report["initial_health"].get("control_mode") == "plugin_pre_tool",
                "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
                "outbox_drained": report["final_health"]["queued_records"] == 0,
                "terminal_report_acked": report["terminal_reports_acked"] == 1,
            }
            report["status"] = "native_control_probe_passed" if all(report["checks"].values()) else "native_control_probe_incomplete"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
    finally:
        for process in (native, receiver):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if native is not None and native.stdin is not None and not native.stdin.closed:
            native.stdin.close()
        for handle in handles:
            handle.close()
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root / "report.json"), "status": report["status"],
                      "native_exit": report.get("native_exit"), "received_hooks": report.get("received_hooks")}))


if __name__ == "__main__":
    def cancelled(_signum, _frame):
        raise InterruptedError("acceptance_cancelled")

    signal.signal(signal.SIGTERM, cancelled)
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude", required=True)
    parser.add_argument("--client-bin", help="Existing owned test client, for a shared native ES catalog")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--platform-fixture", help="Private login fixture for the isolated acceptance server only")
    parser.add_argument("--public-key", help="Pinned platform X9.63 key for isolated control verification")
    parser.add_argument("--expected-decision", choices=("allow", "deny"), help="One controlled touch probe, evaluated against this platform decision")
    parser.add_argument("--mcp-url", help="Owned shared MCP printf fixture on 127.0.0.1")
    parser.add_argument("--probe-offset", type=int, choices=(0, 10), default=0)
    parser.add_argument("--ready-file", help="New private metadata file for the owned acceptance coordinator")
    parser.add_argument("--native-permission-deny", action="store_true", help="One isolated non-allowlisted touch request; audit native host denial without AIDR control")
    parser.add_argument("--auto-permission-probe", action="store_true", help="Request one harmless owned script under a verified temporary native auto hard-deny rule; denial and hook coverage require independent verification")
    parser.add_argument("--permission-host", action="store_true", help="Use the owned deny-only stdio MCP permission host with the native permission probe")
    parser.add_argument("--compact-probe", action="store_true", help="Create one tool-free private session, then resume only that session for manual compaction")
    parser.add_argument("--task-completion-probe", action="store_true", help="Create and complete one synthetic native task using only TaskCreate/TaskUpdate")
    parser.add_argument("--idle-notification-probe", action="store_true", help="Keep one tool-free native stream input open for 75 seconds after its result")
    parser.add_argument("--subagent-probe", action="store_true", help="Run exactly one synthetic foreground child and verify its native lifecycle pair")
    run(parser.parse_args())
