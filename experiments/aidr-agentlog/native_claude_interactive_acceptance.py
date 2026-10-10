#!/usr/bin/env python3
"""User-operated native terminal probe; no synthetic terminal or trust override.

Each invocation owns its profile, workspace, receiver and bounded lifetime.
The report records collection, not acceptance: match its stream against the
platform and native session evidence before marking a lifecycle event passed.
"""
import argparse
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from native_claude_acceptance import receiver_evidence


def resolve_team_model(configured, override=None):
    model = override or configured.get("ANTHROPIC_MODEL")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}", model):
        raise ValueError("interactive_team_requires_explicit_configured_model")
    return model


def prompt_for(mode, work, team_model=None):
    if mode == "permission":
        return ("Isolated lifecycle acceptance. Request Bash exactly once to execute /usr/bin/touch "
                + str(work / "permission-marker") + ". If permission is denied, stop without retrying. "
                "Do not read files or environment, use other tools, or spawn agents.")
    if mode == "idle":
        return "Reply exactly AIDR-IDLE-DONE. Do not use tools, access files or spawn agents."
    model = resolve_team_model({}, team_model)
    return ("Isolated team lifecycle acceptance. Create one team with exactly one teammate named aidr-probe. "
            "Set the Agent spawn model parameter explicitly to sonnet. "
            "This isolated profile maps sonnet to " + json.dumps(model) + ". "
            "Its only task is to reply AIDR-TEAM-DONE without tools, files or environment access. "
            "Wait until that teammate becomes idle, then shut it down and clean up the team. "
            "Do not poll TaskOutput, schedule wakeups, create any other teammate or execute shell commands. "
            "If the spawn or model call fails, stop and report that failure without a replacement.")


def run(args):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("interactive_acceptance_requires_user_terminal")
    if urlsplit(args.server).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("interactive_acceptance_requires_loopback")
    os.umask(0o077)
    repo = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="aidr-p3-claude-interactive-", dir="/private/tmp"))
    home, work = root / "profile", root / "work"
    home.mkdir(); work.mkdir()
    sock = root / "hook.sock"
    binary = str(Path(args.client_bin).resolve(strict=True))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC", "AIDR_", "AGENT_MANAGER_AIDR"))
           and k not in {"ENV", "BASH_ENV", "ZDOTDIR"}}
    allowed = {"ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
               "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"}
    configured = json.loads(Path(args.settings).read_text()).get("env", {})
    team_model = resolve_team_model(configured, getattr(args, "team_model", None)) if args.mode == "team" else None
    env.update({k: v for k, v in configured.items() if k in allowed and isinstance(v, str)})
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home), SHELL="/bin/bash", ZDOTDIR=str(home),
               AIDR_CLIENT_BIN=binary, AIDR_HOOK_SOCKET=str(sock), DISABLE_AUTOUPDATER="1",
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
    if args.mode == "team":
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        env["CLAUDE_CODE_SUBAGENT_MODEL"] = team_model
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = team_model
    receiver_env = {k: v for k, v in env.items() if not k.startswith("ANTHROPIC")}
    receiver_env["AIDR_TEST_TOKEN"] = Path(args.token_file).read_text().strip()
    report = {"root": str(root), "scope": "native_claude_interactive_probe", "mode": args.mode,
              "status": "unverified", "host_version": subprocess.check_output(
                  [args.claude, "--version"], text=True, timeout=10).strip()}
    if team_model:
        report["requested_team_model"] = team_model
        report["requested_team_model_alias"] = "sonnet"
    receiver = native = None
    with (root / "receiver.json").open("wb") as out, (root / "receiver.stderr").open("wb") as err:
        try:
            receiver = subprocess.Popen([binary, "aidr-hook-serve", "--state-dir", str(root / "state"),
                "--socket", str(sock), "--server", args.server, "--client-id", args.client_id,
                "--token-env", "AIDR_TEST_TOKEN"], env=receiver_env, stdout=out, stderr=err)

            def health():
                p = subprocess.run([binary, "aidr-hook", "--socket", str(sock), "--health"],
                                   capture_output=True, timeout=5)
                return json.loads(p.stdout)["state"] if p.returncode == 0 else None

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = health()
                if state is not None:
                    report["initial_health"] = state
                    break
                if receiver.poll() is not None:
                    raise RuntimeError("receiver_start_failed")
                time.sleep(.2)
            else:
                raise RuntimeError("receiver_readiness_timeout")
            print("独立测试目录 / Isolated probe:", root, flush=True)
            if args.mode == "team":
                print("仅信任此临时目录。唯一队友完成、空闲并关闭后立即输入 /exit；失败也请退出，不新建替代队友。"
                      " Review this profile. After the sole teammate finishes, becomes idle and shuts down, /exit. "
                      "Exit on failure without a replacement.", flush=True)
            elif args.mode == "permission":
                print("仅信任此临时目录。权限提示等待至少8秒后拒绝；回复完成后保持空闲75秒，再输入 /exit。"
                      " Review this profile; deny the permission prompt after 8 seconds. Wait 75 seconds after the reply, then /exit.", flush=True)
            else:
                print("仅信任此临时目录。回复完成后保持空闲75秒，再输入 /exit。"
                      " Review this profile. Wait 75 seconds after the reply, then /exit.", flush=True)
            print("测试最长300秒，会自动结束。Maximum test duration: 300 seconds.", flush=True)
            command = [args.claude, "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--plugin-dir", str(repo / "client/aidr-plugins/aidr-claude"), "--permission-mode", "manual"]
            if args.mode != "team":
                command += ["--tools", "Bash" if args.mode == "permission" else ""]
            else:
                command += ["--settings", '{"teammateMode":"in-process"}', "--model", team_model]
            native = subprocess.Popen([*command, "--", prompt_for(args.mode, work, team_model)], cwd=work, env=env)
            report["native_exit"] = native.wait(timeout=300)
        except (Exception, KeyboardInterrupt) as exc:
            report["error_type"] = type(exc).__name__
        finally:
            if native is not None:
                if native.poll() is None:
                    native.send_signal(signal.SIGTERM)
                    try:
                        native.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        native.kill(); native.wait(timeout=5)
                report["native_exit"] = native.returncode
            # SessionEnd may arrive during native shutdown, including timeout.
            # Keep the receiver alive until that final outbox has drained.
            if receiver is not None and receiver.poll() is None:
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        state = health()
                        if state is not None:
                            report["final_health"] = state
                            if state["queued_records"] == 0:
                                break
                        time.sleep(.2)
                except Exception as exc:
                    report["drain_error_type"] = type(exc).__name__
            for process in (receiver,):
                if process is not None and process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
            if receiver is not None:
                report["receiver_exit"] = receiver.returncode
            if (root / "state/hooks.db").exists():
                report.update(receiver_evidence(root))
            report["socket_removed"] = not sock.exists()
            report["marker_exists"] = (work / "permission-marker").exists()
            (root / "report.json").write_text(json.dumps(report, indent=2))
    print("Evidence (requires independent verification):", root / "report.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("claude", "client-bin", "settings", "server", "client-id", "token-file"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--mode", choices=("permission", "idle", "team"), default="permission")
    parser.add_argument("--team-model", help="Explicit team model; defaults to ANTHROPIC_MODEL from the private provider settings")
    run(parser.parse_args())
