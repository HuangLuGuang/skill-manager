"""Inspect native plugin hook trust in an owned profile without starting a turn."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", required=True)
    parser.add_argument("--client")
    parser.add_argument("--managed-home", type=Path,
                        help="Inspect the connected candidate in an owned desktop acceptance profile")
    parser.add_argument("--expected-trust", choices=("untrusted", "trusted"), default="untrusted")
    args = parser.parse_args()
    os.umask(0o077)
    repo = Path(__file__).resolve().parents[2]
    if args.managed_home:
        desktop_home = args.managed_home.resolve(strict=True)
        root = desktop_home.parent
        if (root.parent != Path("/private/tmp") or not root.name.startswith("aidr-governance-")
                or desktop_home.name != "home"):
            parser.error("managed home must belong to an isolated governance acceptance directory")
        marker = root / "codex-0159-candidate.json"
        if marker.is_symlink() or not marker.is_file():
            parser.error("connected candidate marker is missing")
        candidate = json.loads(marker.read_text())
        home = desktop_home / ".codex"
        if (candidate.get("scope") != "native_codex_0159_connected_candidate"
                or candidate.get("home") != str(home) or home.is_symlink()):
            parser.error("connected candidate identity does not match")
        work = root / "codex-work"
        work.mkdir(mode=0o700, exist_ok=True)
        report_path = root / ("codex-inventory-" + args.expected_trust + ".json")
    else:
        if not args.client or args.expected_trust != "untrusted":
            parser.error("a new inventory requires --client and starts untrusted")
        root = Path(tempfile.mkdtemp(prefix="aidr-p3-hook-inventory-", dir="/private/tmp"))
        home, work, market = root / "home", root / "work", root / "market"
        home.mkdir(); work.mkdir()
        subprocess.run([args.client, "aidr-plugin-package", "--source-dir", str(repo / "client/aidr-plugins"),
                        "--destination", str(market)], capture_output=True, check=True, timeout=30)
        subprocess.run([args.client, "aidr-plugin-install", "--agent", "codex", "--host-bin", args.codex,
                        "--host-config-dir", str(home), "--marketplace-path", str(market)],
                       capture_output=True, check=True, timeout=60)
        report_path = root / "report.json"
    inbox = queue.Queue(maxsize=128)
    overflow = threading.Event()
    report = {"status": "incomplete", "model_calls": 0, "profile": str(home),
              "expected_trust": args.expected_trust}
    with (root / "native.stderr").open("w") as stderr:
        process = subprocess.Popen([args.codex, "app-server", "--stdio"], cwd=work,
            env={**{k: v for k, v in os.environ.items() if not k.startswith("AIDR_")},
                 "CODEX_HOME": str(home)}, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=stderr, text=True)
        def read():
            while True:
                line = process.stdout.readline((1 << 20) + 1)
                if not line:
                    return
                if len(line) > (1 << 20) or not line.endswith("\n"):
                    overflow.set()
                    return
                try:
                    inbox.put_nowait(json.loads(line))
                except (ValueError, queue.Full):
                    overflow.set()
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def request(index, method, params):
            process.stdin.write(json.dumps({"id": index, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if overflow.is_set():
                    raise RuntimeError("native_inventory_response_budget")
                try:
                    message = inbox.get(timeout=.2)
                except queue.Empty:
                    if process.poll() is not None:
                        raise RuntimeError("native_inventory_exited")
                    continue
                if message.get("id") == index:
                    if "error" in message:
                        raise RuntimeError("native_inventory_request_rejected")
                    return message["result"]
            raise RuntimeError("native_inventory_timeout")
        try:
            request(1, "initialize", {"clientInfo": {"name": "aidr-isolated-inventory", "version": "1"},
                                      "capabilities": {"experimentalApi": True}})
            process.stdin.write('{"method":"initialized"}\n'); process.stdin.flush()
            result = request(2, "hooks/list", {"cwds": [str(work)]})
            # Only protocol metadata, never arbitrary commands or hook payloads.
            groups = result["data"]
            assert len(groups) == 1 and not groups[0]["errors"] and not groups[0]["warnings"]
            fields = ("eventName", "enabled", "trustStatus", "source", "pluginId", "currentHash", "key")
            inventory = [{k: h[k] for k in fields} for h in groups[0]["hooks"]]
            assert len(inventory) == 12
            assert all(h["enabled"] and h["trustStatus"] == args.expected_trust and h["source"] == "plugin"
                       and h["pluginId"] == "aidr-codex@aidr-local" for h in inventory)
            (root / "inventory.json").write_text(json.dumps(inventory, indent=2))
            report.update(status=("native_enabled_but_untrusted_verified" if args.expected_trust == "untrusted"
                                  else "native_enabled_and_trusted_verified"), hook_count=len(inventory))
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)
            reader.join(timeout=3)
            report["owned_process_reclaimed"] = process.poll() is not None and not reader.is_alive()
            report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(report_path), **report}))


if __name__ == "__main__":
    main()
