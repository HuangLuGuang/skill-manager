#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected JSON object")
        records.append(value)
    return records


def has_exit(log_path: Path, target_pid: int) -> bool:
    return any(record.get("event") == "exit" and record.get("pid") == target_pid
               for record in load_jsonl(log_path))


def validate(log_path: Path, result_path: Path, stderr_path: Path, parent_pid: int) -> None:
    records = load_jsonl(log_path)
    result = json.loads(result_path.read_text())
    target_pid = result.get("pid")
    if not isinstance(target_pid, int) or target_pid <= 0:
        raise ValueError("target result has no valid integer pid")
    expected_result = {
        "protected_denied": 100,
        "protected_unexpected_success": 0,
        "allowed_success": 100,
        "allowed_failures": 0,
    }
    for key, expected in expected_result.items():
        if result.get(key) != expected:
            raise ValueError(f"target result {key}={result.get(key)!r}, expected {expected}")

    forks = [r for r in records if r.get("event") == "fork" and r.get("pid") == target_pid]
    execs = [r for r in records if r.get("event") == "exec" and r.get("pid") == target_pid]
    exits = [r for r in records if r.get("event") == "exit" and r.get("pid") == target_pid]
    auths = [r for r in records if r.get("event") == "auth_open" and r.get("pid") == target_pid]
    if not forks or not execs or not exits:
        raise ValueError("missing correlated fork, exec, or exit event")
    if any(r.get("parent_pid") != parent_pid for r in forks + execs + exits):
        raise ValueError(f"lifecycle parent_pid does not equal test script pid {parent_pid}")

    exec_versions = {r.get("pidversion") for r in execs}
    if len(exec_versions) != 1 or not all(isinstance(v, int) and v > 0 for v in exec_versions):
        raise ValueError("exec events do not identify exactly one valid pidversion")
    instance_version = next(iter(exec_versions))
    if any(r.get("pidversion") != instance_version for r in exits):
        raise ValueError("exit pidversion does not match exec instance")
    if len(auths) != 100:
        raise ValueError(f"expected 100 target auth events, got {len(auths)}")
    for record in auths:
        if record.get("pidversion") != instance_version:
            raise ValueError("auth pidversion does not match exec instance")
        if record.get("decision") != "deny" or record.get("response") != 0:
            raise ValueError("auth denial has a non-success response")
        if not isinstance(record.get("deadline_remaining_ticks"), int) or record["deadline_remaining_ticks"] <= 0:
            raise ValueError("auth denial has no positive deadline margin")
        if record.get("cache") is not False:
            raise ValueError("auth denial was cacheable")

    summary = stderr_path.read_text()
    if "SUMMARY response_errors=0 dropped_logs=0 log_drain=complete" not in summary:
        raise ValueError("monitor summary reports response/logging failure")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    exit_parser = sub.add_parser("has-exit")
    exit_parser.add_argument("log", type=Path)
    exit_parser.add_argument("pid", type=int)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("log", type=Path)
    validate_parser.add_argument("result", type=Path)
    validate_parser.add_argument("stderr", type=Path)
    validate_parser.add_argument("parent_pid", type=int)
    args = parser.parse_args()
    try:
        if args.command == "has-exit":
            return 0 if has_exit(args.log, args.pid) else 1
        validate(args.log, args.result, args.stderr, args.parent_pid)
        print("evidence validation passed")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"evidence validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
