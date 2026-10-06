#!/usr/bin/env python3
"""Bounded, read-only macOS Agent installation and process snapshot discovery."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import plistlib
import subprocess
import time
from collections import Counter
from pathlib import Path

from snapshot_attribution import Component, ProcessIdentity, ProcessRecord, classify_snapshot

PROC_PIDTBSDINFO = 3
PROC_PIDPATHINFO_MAXSIZE = 4096
MAXCOMLEN = 16


class ProcBSDInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * MAXCOMLEN),
        ("pbi_name", ctypes.c_char * (2 * MAXCOMLEN)),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64), ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _codesign(path: Path) -> dict:
    result = subprocess.run(
        ["/usr/bin/codesign", "-d", "--verbose=2", str(path)],
        stdin=subprocess.DEVNULL, text=True, capture_output=True, timeout=5,
    )
    fields = {}
    for line in result.stderr.splitlines():
        if line.startswith(("Identifier=", "TeamIdentifier=")):
            key, value = line.split("=", 1)
            fields[key.lower()] = value
    return {"metadata_exit_status": result.returncode, **fields}


def _component(agent: str, surface: str, role: str, path: Path,
               root_candidate: bool, entry: Path | None = None) -> tuple[dict, Component] | None:
    try:
        canonical = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    stat = canonical.stat()
    data = {
        "agent": agent, "surface": surface, "role": role,
        "entry_path": str(entry or path), "canonical_path": str(canonical),
        "device": stat.st_dev, "inode": stat.st_ino,
        "root_candidate": root_candidate, "identity_basis": "catalog_path_match",
        "code_signature_observation": {**_codesign(canonical), "verification": "not_performed"},
    }
    return data, Component(agent, surface, role, str(canonical), root_candidate)


def _bundle(agent: str, bundle: Path) -> tuple[list[dict], list[Component], dict] | None:
    plist_path = bundle / "Contents/Info.plist"
    try:
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
        executable = bundle / "Contents/MacOS" / info["CFBundleExecutable"]
    except (OSError, KeyError, plistlib.InvalidFileException):
        return None
    rows: list[dict] = []
    components: list[Component] = []
    main = _component(agent, "desktop", "gui", executable, False, bundle)
    if main:
        rows.append(main[0]); components.append(main[1])
    helper_dir = bundle / "Contents/Frameworks"
    helper_paths = list(helper_dir.glob("*.app/Contents/MacOS/*"))
    helper_paths.extend(helper_dir.glob("*.framework/Versions/*/Helpers/*.app/Contents/MacOS/*"))
    helper_paths.extend(helper_dir.glob("*.framework/Versions/*/Frameworks/*.app/Contents/MacOS/*"))
    seen_helpers: set[str] = set()
    for helper in sorted(set(helper_paths))[:32]:
        item = _component(agent, "desktop", "helper", helper, False)
        if item and item[0]["canonical_path"] not in seen_helpers:
            rows.append(item[0]); components.append(item[1])
            seen_helpers.add(item[0]["canonical_path"])
    metadata = {
        "path": str(bundle), "bundle_id": info.get("CFBundleIdentifier"),
        "version": info.get("CFBundleShortVersionString"),
        "build": info.get("CFBundleVersion"),
    }
    return rows, components, metadata


def discover_installations() -> tuple[list[dict], list[Component], list[dict]]:
    rows: list[dict] = []
    components: list[Component] = []
    bundles: list[dict] = []
    home = Path.home()
    cli_entries = {
        "claude": [home / ".local/bin/claude", Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")],
        "codex": [home / ".local/bin/codex", Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex")],
    }
    cli_entries["codex"].extend(sorted((home / ".nvm/versions/node").glob("*/bin/codex")))
    seen: set[tuple[str, str, str]] = set()
    for agent, entries in cli_entries.items():
        for entry in entries:
            if not entry.exists():
                continue
            item = _component(agent, "cli", "cli_native" if entry.resolve().suffix != ".js" else "cli_entry", entry, entry.resolve().suffix != ".js", entry)
            if item and (agent, item[0]["role"], item[0]["canonical_path"]) not in seen:
                rows.append(item[0]); components.append(item[1]); seen.add((agent, item[0]["role"], item[0]["canonical_path"]))
            if agent == "codex":
                package = entry.resolve().parent.parent
                for native in sorted(package.glob("node_modules/@openai/codex-darwin-*/vendor/*/codex/codex"))[:8]:
                    backend = _component(agent, "cli", "backend", native, True, entry)
                    if backend and (agent, "backend", backend[0]["canonical_path"]) not in seen:
                        rows.append(backend[0]); components.append(backend[1]); seen.add((agent, "backend", backend[0]["canonical_path"]))
    for agent, name in (("claude", "Claude.app"), ("codex", "Codex.app")):
        for base in (Path("/Applications"), home / "Applications"):
            result = _bundle(agent, base / name)
            if result:
                new_rows, new_components, metadata = result
                rows.extend(new_rows); components.extend(new_components); bundles.append(metadata)
    # The Codex desktop product is currently distributed as ChatGPT.app. Its
    # native backend is an Agent candidate; Electron helpers and the code-mode
    # tool host are components, but are not ancestry roots.
    for base in (Path("/Applications"), home / "Applications"):
        chatgpt = base / "ChatGPT.app"
        result = _bundle("codex", chatgpt)
        if result:
            new_rows, new_components, metadata = result
            rows.extend(new_rows); components.extend(new_components); bundles.append(metadata)
            special = (("backend", chatgpt / "Contents/Resources/codex", True),
                       ("tool_host", chatgpt / "Contents/Resources/codex-code-mode-host", False))
            for role, path, root_candidate in special:
                item = _component("codex", "desktop", role, path, root_candidate, chatgpt)
                if item:
                    rows.append(item[0]); components.append(item[1])
    return rows, components, bundles


class ProcessReader:
    def __init__(self):
        location = ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib"
        self.lib = ctypes.CDLL(location, use_errno=True)
        self.lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]

    def info(self, pid: int) -> tuple[ProcessIdentity, int] | None:
        value = ProcBSDInfo()
        size = self.lib.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(value), ctypes.sizeof(value))
        if size != ctypes.sizeof(value):
            return None
        return ProcessIdentity(pid, value.pbi_start_tvsec * 1_000_000 + value.pbi_start_tvusec), value.pbi_ppid

    def path(self, pid: int) -> str | None:
        buffer = ctypes.create_string_buffer(PROC_PIDPATHINFO_MAXSIZE)
        size = self.lib.proc_pidpath(pid, buffer, len(buffer))
        return os.fsdecode(buffer.value) if size > 0 else None

    def _list_pids(self, maximum: int) -> tuple[int, int, list[int]]:
        count = self.lib.proc_listallpids(None, 0)
        if count <= 0:
            return count, 0, []
        capacity = min(max(count + 32, 64), maximum)
        values = (ctypes.c_int * capacity)()
        found = self.lib.proc_listallpids(values, ctypes.sizeof(values))
        return found, capacity, list(values)[:min(max(found, 0), capacity)]

    def snapshot(self, maximum: int, max_duration_ms: int = 500) -> tuple[list[ProcessRecord], dict]:
        started = time.monotonic()
        found, capacity, pids = self._list_pids(maximum)
        if found <= 0:
            return [], {"status": "unavailable", "listed": found, "capacity": capacity,
                        "stable_records": 0, "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                        "errors": {"process_list_unavailable": 1}}
        records: list[ProcessRecord] = []
        errors = Counter()
        for pid in pids:
            if (time.monotonic() - started) * 1000 >= max_duration_ms:
                errors["duration_limit"] += 1
                break
            if pid <= 0:
                continue
            before = self.info(pid)
            if before is None:
                errors["identity_unavailable"] += 1; continue
            path_before = self.path(pid)
            if not path_before:
                errors["path_unavailable"] += 1; continue
            after = self.info(pid)
            path_after = self.path(pid)
            if (time.monotonic() - started) * 1000 >= max_duration_ms:
                errors["duration_limit"] += 1; break
            if after is None or before != after or not path_after or path_before != path_after:
                errors["changed_during_sample"] += 1; continue
            records.append(ProcessRecord(before[0], before[1], path_before))
        partial = found >= capacity or bool(errors)
        return records, {"status": "partial" if partial else "complete", "listed": found,
                         "capacity": capacity, "stable_records": len(records),
                         "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                         "errors": dict(errors)}


def attach_classification_coverage(coverage: dict, classification: dict) -> None:
    coverage["classification"] = classification
    if coverage.get("status") == "complete" and (classification.get("truncated") or classification.get("conflicted_pids", 0) > 0):
        coverage["status"] = "partial"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-processes", type=int, default=4096)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval-ms", type=int, default=50)
    parser.add_argument("--max-duration-ms", type=int, default=500)
    parser.add_argument("--expect-pid", type=int)
    args = parser.parse_args()
    if not 1 <= args.max_processes <= 16384 or not 1 <= args.samples <= 200 or not 0 <= args.interval_ms <= 1000 or not 10 <= args.max_duration_ms <= 5000:
        parser.error("bounds: max-processes 1..16384, samples 1..200, interval-ms 0..1000, max-duration-ms 10..5000")
    installations, components, bundles = discover_installations()
    reader = ProcessReader()
    snapshots = []
    expectation = False
    for index in range(args.samples):
        records, coverage = reader.snapshot(args.max_processes, args.max_duration_ms)
        classification = {}
        matches = classify_snapshot(records, components, classification)
        attach_classification_coverage(coverage, classification)
        if args.expect_pid is not None:
            expectation = expectation or any(item["pid"] == args.expect_pid and item["attribution"] == "snapshot" for item in matches)
        snapshots.append({"index": index, "captured_unix_ns": time.time_ns(), "coverage": coverage, "matches": matches})
        if index + 1 < args.samples:
            time.sleep(args.interval_ms / 1000)
    output = {
        "schema": "macos-agent-observation/v1", "mode": "read_only_snapshot",
        "identity_basis": "pid+start_time_us", "catalog_match": "exact_canonical_path",
        "installations": installations,
        "bundles": bundles, "snapshots": snapshots,
        "privacy": {"process_argv": "not_collected", "process_environment": "not_collected", "file_contents": "not_collected"},
        "limitations": [
            "Snapshots are non-atomic; identity and path are each read twice to reject common PID reuse or exec races, but ABA cannot be excluded.",
            "A catalog path match identifies an installed component candidate; it is not code-signing authentication.",
            "Snapshot and inferred labels do not mean ES direct/inherited, session, turn, or tool-call attribution.",
        ],
        "expectation": None if args.expect_pid is None else {"pid": args.expect_pid, "exact_component_seen": expectation},
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if args.expect_pid is None or expectation else 2


if __name__ == "__main__":
    raise SystemExit(main())
