#!/usr/bin/env python3
"""Verify one release-provenance.json against an expected formal release."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def read_payload(path: str) -> dict[str, object]:
    if path == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("release provenance must be a JSON object")
    return payload


def validate(
    payload: dict[str, object],
    *,
    version: str,
    commit: str,
    platform: str,
    require_clean_clone: bool,
) -> None:
    architecture = platform.removeprefix("linux/")
    archive_layout = {"amd64": "x86", "arm64": "arm"}[architecture]
    expected = {
        "schema": "agent-manager-release-provenance@1",
        "version": version,
        "git_commit": commit,
        "platform": platform,
        "architecture": architecture,
        "archive_layout": archive_layout,
    }
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            raise ValueError(f"{field} mismatch: expected {expected_value!r}")

    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("generated_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", commit) is None:
        raise ValueError("expected commit must be a full hexadecimal identifier")

    if require_clean_clone:
        if payload.get("source_mode") != "git_clone":
            raise ValueError("formal release must use git_clone source mode")
        if payload.get("worktree_dirty") is not False:
            raise ValueError("formal release worktree must be clean")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Path to provenance JSON, or - for stdin")
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--platform", required=True, choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--require-clean-clone", action="store_true")
    args = parser.parse_args()
    try:
        payload = read_payload(args.file)
        validate(
            payload,
            version=args.version,
            commit=args.commit,
            platform=args.platform,
            require_clean_clone=args.require_clean_clone,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"release provenance verification failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "version": args.version,
                "commit": args.commit,
                "platform": args.platform,
                "clean_clone": args.require_clean_clone,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
