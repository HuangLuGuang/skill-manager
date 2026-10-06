#!/usr/bin/env python3
"""Observe suspended real Agent --version processes without a model request."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
from pathlib import Path

from observe_agents import ProcessReader, attach_classification_coverage, discover_installations
from snapshot_attribution import classify_snapshot


def main() -> int:
    root = Path(__file__).resolve().parent
    launcher = root / "build/snapshot-launcher"
    if not launcher.exists():
        print("build/snapshot-launcher is missing; run make all", file=sys.stderr)
        return 66
    installations, components, bundles = discover_installations()
    targets = {}
    for item in installations:
        if item["surface"] == "cli" and item["role"] in ("cli_native", "backend"):
            targets.setdefault(item["agent"], item["canonical_path"])
    evidence = []
    reader = ProcessReader()
    for agent in ("claude", "codex"):
        executable = targets.get(agent)
        if not executable:
            evidence.append({"agent": agent, "status": "not_installed"})
            continue
        child_pid = None
        process = subprocess.Popen(
            [str(launcher), "--timeout-ms", "5000", executable, "--version"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            readable, _, _ = select.select([process.stdout], [], [], 5)
            if not readable:
                raise TimeoutError("launcher pid handshake")
            line = process.stdout.readline().strip()
            pid = int(line); child_pid = pid
            records, coverage = reader.snapshot(4096, 1000)
            classification = {}
            matches = [item for item in classify_snapshot(records, components, classification) if item["pid"] == pid]
            attach_classification_coverage(coverage, classification)
            exact = [item for item in matches if item["attribution"] == "snapshot" and item["agent"] == agent]
            stdout_tail, stderr = process.communicate("c", timeout=10)
            stdout_tail = stdout_tail.strip(); stderr = stderr.strip()
            status = process.returncode
            evidence.append({
                "agent": agent, "status": "passed" if exact and status == 0 else "failed",
                "pid": pid, "executable": executable, "snapshot_matches": exact,
                "coverage": coverage, "version_output": stdout_tail or stderr,
                "exit_status": status,
            })
        except Exception as error:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if child_pid is not None:
                    try: os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                process.kill(); process.wait(timeout=2)
            evidence.append({"agent": agent, "status": "failed", "error": type(error).__name__})
    output = {
        "schema": "macos-agent-real-observation-test/v1", "model_requests": 0,
        "installations": installations, "bundles": bundles, "evidence": evidence,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if all(item["status"] == "passed" for item in evidence) else 1


if __name__ == "__main__":
    raise SystemExit(main())
