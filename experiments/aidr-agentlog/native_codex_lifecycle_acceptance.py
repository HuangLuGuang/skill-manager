"""Bounded native compaction/interrupt probe in an owned Codex profile.

Requires native persisted hook trust before spending any model calls. App
Server support for the CLI invocation trust override is not assumed.
Never changes persisted trust or resumes user threads. The optional permission
probe requests one owned marker command and declines its native approval.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time


def run(args):
    os.umask(0o077)
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-codex-lifecycle-", dir="/private/tmp"))
    home, work, market = root / "home", root / "work", root / "market"
    if args.profile:
        home = owned_profile(args.profile)
    else:
        home.mkdir()
    work.mkdir()
    sock = root / "hook.sock"
    report = {"scope": "native_codex_lifecycle_audit", "root": str(root), "status": "incomplete",
              "profile": str(home), "persisted_hook_trust": "not_verified", "trust_mode": "native_persisted_trust_required", "started_model_turns": 0}
    receiver = native = reader = None
    handles = []
    copied_auth = False
    inbox = queue.Queue(maxsize=256)
    overflow = threading.Event()
    notifications = []
    permission_probe = getattr(args, "permission_probe", False)
    subagent_probe = getattr(args, "subagent_probe", False)
    marker = work / "denied-marker"
    report["native_approval_requests"] = []
    env = {**os.environ, "CODEX_HOME": str(home), "AIDR_CLIENT_BIN": args.client,
           "AIDR_HOOK_SOCKET": str(sock)}

    def output(name):
        handle = (root / name).open("xb"); handles.append(handle); return handle

    def health():
        result = subprocess.run([args.client, "aidr-hook", "--socket", str(sock), "--health"],
                                capture_output=True, timeout=5)
        return json.loads(result.stdout)["state"] if result.returncode == 0 else None

    def send(value):
        native.stdin.write(json.dumps(value) + "\n"); native.stdin.flush()

    def next_message(deadline):
        while time.monotonic() < deadline:
            if overflow.is_set():
                raise RuntimeError("native_protocol_budget")
            try:
                message = inbox.get(timeout=.2)
            except queue.Empty:
                if native.poll() is not None:
                    raise RuntimeError("native_server_exited")
                continue
            if "method" in message:
                if "id" in message:
                    params = message.get("params", {})
                    if permission_probe and message["method"] == "item/commandExecution/requestApproval":
                        # Deny first, including malformed or unrelated requests. Never
                        # grant permissions based on model-generated command text.
                        send({"id": message["id"], "result": {"decision": "decline"}})
                        valid = approval_matches(params, report, work, marker)
                        report["native_approval_requests"].append({"method": message["method"],
                            "thread_id": params.get("threadId"), "turn_id": params.get("turnId"),
                            "item_id": params.get("itemId"), "owned_command": valid, "decision": "decline"})
                        if not valid or len(report["native_approval_requests"]) > 1:
                            raise RuntimeError("native_unexpected_approval")
                        continue
                    report["unexpected_request_method"] = message["method"]
                    send({"id": message["id"], "error": {"code": -32000, "message": "Tool and approval requests are outside this text-only probe"}})
                    raise RuntimeError("native_unexpected_server_request")
                params = message.get("params", {})
                item, turn = params.get("item", {}), params.get("turn", {})
                notifications.append({"method": message["method"], "thread_id": params.get("threadId"),
                    "turn_id": params.get("turnId", turn.get("id")), "status": turn.get("status"),
                    "item_type": item.get("type"), "item_id": item.get("id"), "item_status": item.get("status"),
                    "collab_tool": item.get("tool"), "receiver_thread_ids": item.get("receiverThreadIds")})
                if len(notifications) > 512:
                    raise RuntimeError("native_notification_budget")
            return message
        raise TimeoutError("native_protocol_timeout")

    def request(index, method, params):
        send({"id": index, "method": method, "params": params})
        deadline = time.monotonic() + 20
        while True:
            message = next_message(deadline)
            if message.get("id") == index:
                if "error" in message:
                    error = message["error"]
                    report["rpc_failure"] = {"method": method, "code": error.get("code"),
                        "categories": [word for word in ("thread", "turn", "progress", "compaction", "input", "busy", "not found", "rate", "context") if word in str(error.get("message", "")).lower()]}
                    raise RuntimeError("native_request_rejected")
                return message["result"]

    def completed(thread_id, turn_id=None, start=0):
        deadline = time.monotonic() + 90
        while True:
            for row in notifications[start:]:
                if row["method"] == "turn/completed" and row["thread_id"] == thread_id and (turn_id is None or row["turn_id"] == turn_id):
                    return row
            next_message(deadline)

    try:
        if not args.profile:
            subprocess.run([args.client, "aidr-plugin-package", "--source-dir", str(repo / "client/aidr-plugins"),
                            "--destination", str(market)], check=True, capture_output=True, timeout=30)
            subprocess.run([args.client, "aidr-plugin-install", "--agent", "codex", "--host-bin", args.codex,
                            "--host-config-dir", str(home), "--marketplace-path", str(market)],
                           check=True, capture_output=True, timeout=60)
        report["native_version"] = subprocess.check_output([args.codex, "--version"], text=True, timeout=10).strip()
        if not (home / "auth.json").exists():
            shutil.copyfile(Path.home() / ".codex/auth.json", home / "auth.json")
            (home / "auth.json").chmod(0o600)
            copied_auth = True
        receiver = subprocess.Popen([args.client, "aidr-hook-serve", "--state-dir", str(root / "state"),
            "--socket", str(sock), "--server", args.server, "--client-id", args.client_id,
            "--token-env", "AIDR_TEST_TOKEN"], env={**env, "AIDR_TEST_TOKEN": Path(args.token_file).read_text().strip()},
            stdout=output("receiver.json"), stderr=output("receiver.stderr"))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = health()
            if state:
                report["initial_health"] = state; break
            if receiver.poll() is not None:
                raise RuntimeError("receiver_start_failed")
            time.sleep(.1)
        else:
            raise TimeoutError("receiver_readiness_timeout")
        auth_flags = ["-c", 'cli_auth_credentials_store="file"'] if getattr(args, "file_auth", False) else []
        if subagent_probe:
            auth_flags += ["-c", "agents.enabled=true", "-c", "agents.max_concurrent_threads_per_session=1"]
        native = subprocess.Popen([args.codex, *auth_flags, "app-server", "--stdio"],
            cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=output("native.stderr"), text=True)

        def read():
            while True:
                line = native.stdout.readline(1048577)
                if not line:
                    return
                if len(line) > 1048576:
                    overflow.set(); return
                try:
                    message = json.loads(line)
                    if message.get("method", "").endswith("/delta"):
                        continue
                    inbox.put_nowait(message)
                except (ValueError, queue.Full):
                    overflow.set()
        reader = threading.Thread(target=read, daemon=True); reader.start()
        request(1, "initialize", {"clientInfo": {"name": "aidr-owned-lifecycle", "version": "1"},
                                   "capabilities": {"experimentalApi": True}})
        send({"method": "initialized"})
        inventory = request(9, "hooks/list", {"cwds": [str(work)]})
        report["hook_inventory"] = [{key: hook.get(key) for key in ("eventName", "enabled", "trustStatus", "pluginId")}
            for group in inventory["data"] for hook in group["hooks"]]
        if not inventory_trusted(inventory):
            raise RuntimeError("native_hook_trust_required")
        report["persisted_hook_trust"] = "native_inventory_trusted"
        instructions = ("This is an isolated permission probe. Only request the single command specified by the user. "
            "Never read files or environment, use other tools or spawn agents. After denial stop without retrying."
            if permission_probe else "This is a text-only lifecycle probe. Never call tools, read files, inspect environment or spawn agents. Reply briefly.")
        if subagent_probe:
            instructions = "This is an isolated native subagent lifecycle test. Use only native subagent orchestration tools. Spawn exactly one child with a text-only task, wait until it finishes and close it if a close tool exists. Never read files, execute commands, inspect environment or create further descendants."
        thread = request(2, "thread/start", {"cwd": str(work), "approvalPolicy": "untrusted" if permission_probe else "on-request", "sandbox": "read-only",
            "baseInstructions": instructions})["thread"]["id"]
        report["session_id"] = thread
        if permission_probe:
            report["started_model_turns"] += 1
            turn = request(10, "turn/start", {"threadId": thread,
                "input": [{"type": "text", "text": f"Request exactly one shell command: /usr/bin/touch {marker}. Use the current working directory. This is an intentional native approval denial test. Do not retry after denial or execute any other command. Reply briefly afterward."}]})["turn"]["id"]
            report["permission_turn_id"] = turn
            report["permission_turn"] = completed(thread, turn)
        elif subagent_probe:
            report["started_model_turns"] += 1
            turn = request(10, "turn/start", {"threadId": thread, "input": [{"type": "text", "text":
                "For this native lifecycle acceptance test, spawn exactly one new subagent. Its sole task is to reply exactly AIDR-CHILD-DONE, without using tools, reading files or spawning agents. Wait for its completion and close that child if supported. Do not interact with any other agent. Report its result briefly."}]})["turn"]["id"]
            report["subagent_turn"] = completed(thread, turn)
        else:
            compact_and_interrupt(request, completed, next_message, notifications, report, thread)
        request(8, "thread/archive", {"threadId": thread})
        native.stdin.close()
        try:
            report["native_exit"] = native.wait(timeout=10)
        except subprocess.TimeoutExpired:
            native.terminate(); report["native_exit"] = native.wait(timeout=10)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = health()
            if state:
                report["final_health"] = state
                if state["queued_records"] == 0:
                    break
            time.sleep(.2)
        receiver.send_signal(signal.SIGTERM); report["receiver_exit"] = receiver.wait(timeout=10)
        with sqlite3.connect((root / "state/hooks.db").as_uri() + "?mode=ro", uri=True) as db:
            report["received_hooks"] = db.execute("SELECT count(*) FROM hook_receipts").fetchone()[0]
            report["pending_hooks"] = db.execute("SELECT count(*) FROM hook_events").fetchone()[0]
        with sqlite3.connect(Path(args.database).resolve().as_uri() + "?mode=ro", uri=True) as db:
            values = db.execute("SELECT payload_json FROM aidr_hook_events WHERE client_id=? AND stream_id=? LIMIT 101",
                               (args.client_id, report["final_health"]["stream_id"])).fetchall()
        events = [json.loads(value[0])["event"] for value in values]
        counts = Counter(e["hook_event"] for e in events)
        report["native_hook_counts"] = dict(counts)
        report["checks"] = {
            "native_exited": report["native_exit"] == 0,
            "same_session": bool(events) and {e["session_id"] for e in events} == {thread},
            "uploaded_exactly": len(events) == report["received_hooks"] and report["pending_hooks"] == 0,
            "receiver_reclaimed": report["receiver_exit"] == 0 and not sock.exists(),
        }
        if permission_probe:
            approvals = report["native_approval_requests"]
            report["checks"].update({
                "one_owned_declined_request": len(approvals) == 1 and approvals[0]["owned_command"],
                "marker_absent": not marker.exists(),
                "permission_hook": counts["PermissionRequest"] == 1,
                "turn_completed": report["permission_turn"]["status"] == "completed",
                "declined_item": len(approvals) == 1 and any(n["method"] == "item/completed"
                    and n["item_id"] == approvals[0]["item_id"] and n["thread_id"] == thread
                    and n["turn_id"] == report["permission_turn_id"] and n["item_status"] == "declined" for n in notifications),
            })
        elif subagent_probe:
            starts = [e.get("native_agent_id") for e in events if e["hook_event"] == "SubagentStart"]
            stops = [e.get("native_agent_id") for e in events if e["hook_event"] == "SubagentStop"]
            report["subagent_ids"] = {"starts": starts, "stops": stops}
            report["checks"].pop("same_session")
            report["checks"].update({
                "one_matched_child_lifecycle": len(starts) == len(stops) == 1 and bool(starts[0]) and starts == stops,
                "turn_completed": report["subagent_turn"]["status"] == "completed",
                "native_collaboration_observed": any(n["method"] == "item/completed" and n["item_type"] == "collabAgentToolCall" for n in notifications),
                "owned_sessions_only": bool(events) and bool(starts) and {e["session_id"] for e in events}.issubset({thread, *starts}),
            })
        else:
            report["checks"].update({
                "compact_completed": report["compact_turn"]["status"] == "completed" and report["compact_item_completed"],
                "turn_interrupted": report["interrupted_turn"]["status"] == "interrupted",
                "compact_hooks": counts["PreCompact"] == counts["PostCompact"] == 1,
                "interrupt_hook": counts["Interrupt"] == 1,
                "no_tool_events": not any(e["kind"].startswith("tool.") for e in events),
            })
        report["status"] = "native_lifecycle_passed" if all(report["checks"].values()) else "native_lifecycle_incomplete"
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        if str(exc).startswith(("native_", "receiver_")) and str(exc).replace("_", "").isalpha():
            report["error_code"] = str(exc)
    finally:
        for process in (native, receiver):
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        if reader:
            reader.join(timeout=3)
        for handle in handles:
            handle.close()
        if copied_auth:
            (home / "auth.json").unlink(missing_ok=True)
        report["owned_processes_reclaimed"] = all(p is None or p.poll() is not None for p in (native, receiver))
        report["notifications"] = notifications
        (root / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(root / "report.json"), "status": report["status"], "checks": report.get("checks")}))


def compact_and_interrupt(request, completed, next_message, notifications, report, thread):
    report["seed_turns"] = []
    for index in range(2):
        report["started_model_turns"] += 1
        turn = request(3 + index, "turn/start", {"threadId": thread,
            "input": [{"type": "text", "text": f"Remember synthetic marker COMPACT-{index}. Acknowledge in one short sentence without tools."}]})["turn"]["id"]
        result = completed(thread, turn)
        report["seed_turns"].append(result)
        if result["status"] != "completed":
            raise RuntimeError("native_seed_failed")
    start = len(notifications)
    request(5, "thread/compact/start", {"threadId": thread})
    report["compact_turn"] = completed(thread, start=start)
    report["compact_item_completed"] = any(n["method"] == "item/completed" and n["item_type"] == "contextCompaction" for n in notifications[start:])
    report["started_model_turns"] += 1
    turn = request(6, "turn/start", {"threadId": thread,
        "input": [{"type": "text", "text": "Text-only cancellation test. Explain the synthetic markers in a paragraph without tools."}]})["turn"]["id"]
    report["interrupt_requested_turn_id"] = turn
    deadline = time.monotonic() + 20
    while not any(n["method"] == "turn/started" and n["thread_id"] == thread and n["turn_id"] == turn for n in notifications):
        next_message(deadline)
    request(7, "turn/interrupt", {"threadId": thread, "turnId": turn})
    report["interrupted_turn"] = completed(thread, turn)


def approval_matches(params, report, work, marker):
    import shlex
    if not isinstance(params.get("command"), str):
        return False
    try:
        command = shlex.split(params.get("command", ""))
        if len(command) == 3 and command[0] in ("/bin/zsh", "/bin/bash", "/bin/sh") and command[1] in ("-c", "-lc"):
            command = shlex.split(command[2])
    except ValueError:
        return False
    return (params.get("threadId") == report.get("session_id")
        and bool(report.get("permission_turn_id")) and params.get("turnId") == report["permission_turn_id"]
        and bool(params.get("itemId")) and params.get("cwd") == str(work)
        and command == ["/usr/bin/touch", str(marker)])


def owned_profile(value):
    """Only resume configuration created by these isolated acceptance probes."""
    home = Path(value).resolve(strict=True)
    parent = home.parent
    if parent.parent != Path("/private/tmp") or home.name != "home":
        raise ValueError("native_profile_not_owned")
    report = json.loads((parent / "report.json").read_text())
    lifecycle = parent.name.startswith("aidr-p3-codex-lifecycle-") and report.get("scope") == "native_codex_lifecycle_audit"
    inventory = parent.name.startswith("aidr-p3-hook-inventory-") and report.get("status") == "native_enabled_but_untrusted_verified"
    if not (lifecycle or inventory):
        raise ValueError("native_profile_not_owned")
    return home


def inventory_trusted(inventory):
    groups = inventory.get("data", [])
    if len(groups) != 1 or groups[0].get("errors") or groups[0].get("warnings"):
        return False
    hooks = groups[0].get("hooks", [])
    return len(hooks) == 12 and all(h.get("enabled") is True and h.get("trustStatus") == "trusted"
        and h.get("pluginId") == "aidr-codex@aidr-local" for h in hooks)


if __name__ == "__main__":
    def cancelled(_signum, _frame):
        raise InterruptedError("acceptance_cancelled")
    signal.signal(signal.SIGTERM, cancelled)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("codex", "client", "server", "client-id", "token-file", "database"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile", help="Existing private profile from this probe or native_codex_hook_inventory.py, after user trust review")
    parser.add_argument("--file-auth", action="store_true", help="Use the owned profile's file credential store, matching its user login")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--permission-probe", action="store_true", help="Request one owned marker command and decline its native approval")
    mode.add_argument("--subagent-probe", action="store_true", help="Run one text-only native child and verify its lifecycle pair")
    run(parser.parse_args())
